import datetime as dt
import gzip
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import workflow as w

class CatalogTests(unittest.TestCase):
    def loc(self,i,lon,depth=10):
        return dict(event_id=i,latitude=0,longitude=lon,depth_km=depth)

    def test_transitive_clusters_not_pair_centroids(self):
        pairs=[dict(label='a',index1=1,index2=2),dict(label='b',index1=3,index2=2)]
        self.assertEqual(w.components(pairs,[1,2,3,9]),[[1,2,3],[9]])
        with self.assertRaises(ValueError): w.components(pairs+[pairs[0]],[1,2,3])
        with self.assertRaises(ValueError): w.components(pairs,[1,2])

    def test_robust_dateline_and_tie(self):
        rows=[self.loc(2,-179.9,20),self.loc(1,179.9,10)]
        ref=w.reference(rows)
        self.assertEqual(ref['epicentral_medoid_event_id'],1)
        self.assertEqual(ref['depth_km'],15)
        self.assertLess(w.vector(rows[0],rows[1])['horizontal_km'],23)
        rows=[self.loc(1,0),self.loc(2,.1),self.loc(3,.2),self.loc(4,60,500)]
        self.assertLess(abs(w.reference(rows)['longitude']),1)
        self.assertEqual(w.reference(rows)['depth_km'],10)
        self.assertEqual(w.reference(rows),w.reference(rows[::-1]))

    def test_vector_sign_and_magnitude(self):
        v=w.vector(self.loc(1,0),self.loc(2,1))
        self.assertAlmostEqual(v['east_km'],111.19508,places=4)
        self.assertAlmostEqual(v['north_km'],0,places=6)

    def test_match_priority_ambiguity_and_seed_isolation(self):
        e=dict(index=1,time='2000-01-01T00:00:00',lat=0,lon=0,dep=10,lat_best=85,lon_best=90,depth_best=500)
        config=w.read(w.ROOT/'config.json')
        row=dict(self.loc(2,0),catalog_id='a',origin_time=e['time'],source_catalog='ISC-EHB')
        catalogs={'ISC-EHB':[row],'USGS-ComCat':[]}
        self.assertEqual(w.match(e,catalogs,config)[0]['status'],'matched')
        catalogs['ISC-EHB'].append(dict(row,catalog_id='b'))
        self.assertEqual(w.match(e,catalogs,config)[0]['status'],'ambiguous')
        catalogs={'ISC-EHB':[],'USGS-ComCat':[dict(row,source_catalog='USGS-ComCat')]}
        self.assertEqual(w.match(e,catalogs,config)[0]['status'],'fallback')
        catalogs['USGS-ComCat'][0]['origin_time']='2000-01-01T00:00:31'
        self.assertEqual(w.match(e,catalogs,config)[0]['status'],'unresolved')

    def test_utc_offsets(self):
        self.assertEqual(w.utc('2000-01-01T01:00:00+01:00'),w.utc('2000-01-01T00:00:00Z'))

    def test_depth_quality_and_invalid_coordinates(self):
        self.assertEqual(w.depth_class('DEQ',' ',4,3),'L1')
        self.assertEqual(w.depth_class('FEQ','h',0,0),'L2')
        self.assertEqual(w.depth_class('FEQ','s',0,0),'Not recovered')
        with self.assertRaises(ValueError): w.validate(self.loc(1,float('nan')))
        with self.assertRaises(ValueError): w.parse_hdf('short',2000,'fixture',1)

    def test_real_hdf_record(self):
        # Fixed expected fields from the frozen official 1991 record, independent
        # of workbook best coordinates. Guards column offsets and century handling.
        with gzip.open(w.ROOT/'inputs/raw/1991.hdf.gz','rt') as f:
            rows=[w.parse_hdf(s,1991,'fixture',i) for i,s in enumerate(f,1) if s.strip()]
        row=min(rows,key=lambda r:abs((w.utc(r['origin_time'])-w.utc('1991-04-15T20:39:47.81')).total_seconds()))
        self.assertEqual(row['latitude'],-56.325)
        self.assertEqual(row['longitude'],-26.829)
        self.assertEqual(row['catalog_id'],'335522')
        self.assertEqual(row['depth_km'],70)
        self.assertEqual(row['origin_time'],'1991-04-15T20:39:53.510000+00:00')

    def test_offline_reproducibility_and_input_protection(self):
        with tempfile.TemporaryDirectory() as temp:
            a=w.run(output=Path(temp)/'a');b=w.run(output=Path(temp)/'b')
            self.assertEqual({p.name:p.read_bytes() for p in a.iterdir()}, {p.name:p.read_bytes() for p in b.iterdir()})
            with self.assertRaises(FileExistsError): w.run(output=a)
        with patch.object(w,'sha',return_value='tampered'):
            with self.assertRaisesRegex(ValueError,'checksum mismatch'): w.run()

    def test_collision_and_incomplete_clusters_are_blocked(self):
        real_match=w.match
        def collide(e,catalogs,config):
            m,c=real_match(e,catalogs,config)
            if e['index'] in [701,726]:
                m['location']['catalog_id']='forced-collision'
            return m,c
        with tempfile.TemporaryDirectory() as temp, patch.object(w,'match',side_effect=collide):
            out=w.run(output=Path(temp)/'collision')
            matches=w.read(out/'matches.json')
            self.assertEqual([m['status'] for m in matches if m['event_id'] in [701,726]],['catalog_id_collision']*2)
            cluster=next(c for c in w.read(out/'clusters.json') if c['cluster_id']=='C701')
            self.assertIsNone(cluster['reference'])
            self.assertEqual(cluster['status'],'blocked_incomplete')

    def test_frozen_workbook_extraction_matches_snapshot(self):
        import openpyxl
        manifest=w.read(w.ROOT/'inputs/baseline_manifest.json')
        record=next(r for r in manifest if Path(r['source']).name=='ICevents_full.xlsx')
        book=openpyxl.load_workbook(w.ROOT/record['snapshot'],read_only=True,data_only=True)
        try:
            tables={}
            for name in ['events','pairs']:
                rows=iter(book[name].values)
                headers=[str(v).strip().lower() if v is not None else f'unnamed_{i}' for i,v in enumerate(next(rows))]
                tables[name]=[dict(zip(headers,row)) for row in rows if row[0] is not None]
            tables=json.loads(json.dumps(tables,default=str))
            self.assertEqual(tables,w.read(w.ROOT/'inputs/workbook_tables.json'))
            all_events={int(e['index']):e for e in tables['events']}
            pairs=tables['pairs']
            components=w.components(pairs,list(all_events))
            selected=w.read(w.ROOT/'inputs/study_events.json')
            selected_ids={e['index'] for e in selected}
            self.assertEqual([all_events[i] for i in sorted(selected_ids)],selected)
            self.assertTrue(all(not (set(c)&selected_ids) or set(c)<=selected_ids for c in components))
        finally:book.close()

if __name__=='__main__': unittest.main()
