"""Offline, review-only absolute catalog locations. No production writer exists."""
import argparse
import csv
import datetime as dt
import gzip
import hashlib
import json
import math
from pathlib import Path
import statistics
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parent
R = 6371.0088

def read(path):
    return json.loads(path.read_text())

def write(path, value):
    path.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + '\n')

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def utc(value):
    parsed = dt.datetime.fromisoformat(value.replace('Z', '+00:00'))
    return parsed.replace(tzinfo=dt.timezone.utc) if parsed.tzinfo is None else parsed.astimezone(dt.timezone.utc)

def vector(a, b):
    """Great-circle distance and initial-bearing east/north: b minus a, km."""
    p, q = math.radians(a['latitude']), math.radians(b['latitude'])
    dl = math.radians(b['longitude'] - a['longitude'])
    h = math.sin((q-p)/2)**2 + math.cos(p)*math.cos(q)*math.sin(dl/2)**2
    distance = 2*R*math.asin(math.sqrt(max(0, min(1, h))))
    az = math.atan2(math.sin(dl)*math.cos(q), math.cos(p)*math.sin(q)-math.sin(p)*math.cos(q)*math.cos(dl))
    return dict(east_km=distance*math.sin(az), north_km=distance*math.cos(az), horizontal_km=distance)

def validate(row):
    for key in ['latitude', 'longitude', 'depth_km']:
        if not isinstance(row[key], (float, int)) or not math.isfinite(row[key]):
            raise ValueError('Invalid coordinate: ' + str(row))
    if not -90 <= row['latitude'] <= 90 or not -180 <= row['longitude'] <= 180 or not -10 <= row['depth_km'] <= 800:
        raise ValueError('Coordinate range: ' + str(row))
    return row

def depth_class(solution, flag, error, count):
    # Do not invent an official class for research/ISC/GEM/known-source flags.
    if flag in ('d', 'b') or (solution == 'DEQ' and 0 <= error < 5 and count >= 3):
        return 'L1'
    if flag == 'h' or (solution == 'DEQ' and 5 <= error <= 15):
        return 'L2'
    if flag in ('o', 'c', 't', 'v', 'n') or error > 15:
        return 'L3'
    return 'Not recovered'

def parse_hdf(line, year, source, number):
    # ISC format2.hdf Fortran widths; geographic coordinates (RES is geocentric).
    widths = [1,3,2,2,3,3,1,3,3,6,1,8,8,6,6,4,4,4,4,4,4,4,8,8,8,6,6,6,4,4,4,4,5,10]
    if len(line.rstrip('\r\n')) < sum(widths):
        raise ValueError(f'{source}:{number}: short HDF record')
    fields=[]; offset=0
    for width in widths:
        fields.append(line[offset:offset+width]); offset += width
    f=fields
    if int(f[3]) != year % 100:
        raise ValueError('HDF year mismatch')
    origin = dt.datetime(year,int(f[4]),int(f[5]),int(f[7]),int(f[8]),tzinfo=dt.timezone.utc)+dt.timedelta(seconds=float(f[9]))
    error=float(f[24]); count=int(f[20]); flag=f[2][1]
    return validate(dict(catalog_id=f[33].strip(), origin_time=origin.isoformat(),
        latitude=float(f[11]), longitude=float(f[12]), depth_km=float(f[13]),
        source_catalog='ISC-EHB', source_file=source, source_year=year, source_line=number,
        depth_quality_class=depth_class(f[1],flag,error,count), depth_quality_basis='derived conservatively from HDF flags and ISC definitions',
        solution_type=f[1], depth_flag=flag, depth_standard_error_km=error if error>=0 else None,
        position_standard_error_km=float(f[23]), defining_depth_phases=count))

def parse_usgs(data, source):
    if data.get('type') != 'FeatureCollection':
        raise ValueError('Invalid USGS response: '+source)
    result=[]
    for f in data['features']:
        lon,lat,depth=f['geometry']['coordinates']; p=f['properties']
        origin=dt.datetime.fromtimestamp(p['time']/1000,dt.timezone.utc)
        result.append(validate(dict(catalog_id=f['id'],origin_time=origin.isoformat(),latitude=lat,longitude=lon,
            depth_km=depth, source_catalog='USGS-ComCat',source_file=source,source_year=origin.year,
            depth_quality_class='Not recovered',review_status=p.get('status'),agency=p.get('net'),
            catalog_url=p.get('url'),depth_quality_basis='ComCat summary has no ISC-EHB depth class')))
    return result

def components(pairs, event_ids):
    adjacency={i:set() for i in event_ids}
    labels=set()
    for p in pairs:
        if p['label'] in labels:
            raise ValueError('Duplicate pair label')
        labels.add(p['label'])
        a,b=int(p['index1']),int(p['index2'])
        if a==b or a not in adjacency or b not in adjacency:
            raise ValueError('Invalid pair endpoints')
        adjacency[a].add(b); adjacency[b].add(a)
    groups=[]; unseen=set(adjacency)
    while unseen:
        stack=[min(unseen)]; found=set()
        while stack:
            i=stack.pop()
            if i in found: continue
            found.add(i); stack.extend(adjacency[i]-found)
        unseen-=found; groups.append(sorted(found))
    return groups

def seed(e):
    # Original event coordinate columns, never *_best or pair/new_* centroids.
    for keys in [('lat','lon','dep'),('neic lat','neic lon','neic dep')]:
        if all(isinstance(e.get(k),(int,float)) and math.isfinite(e[k]) for k in keys):
            return validate(dict(zip(['latitude','longitude','depth_km'],[e[k] for k in keys])))
    raise ValueError(f"No independent search seed for event {e['index']}")

def match(e, catalogs, config):
    candidates=[]; search=seed(e)
    for catalog in config['fallback_hierarchy']:
        eligible=[]
        for row in catalogs[catalog]:
            residual=(utc(row['origin_time'])-utc(e['time'])).total_seconds()
            if abs(residual)>config['max_time_residual_s']: continue
            delta=vector(search,row)
            if delta['horizontal_km']>config['max_horizontal_residual_km']: continue
            c=dict(row, event_id=int(e['index']),origin_time_residual_s=residual,
                spatial_residual_km=delta['horizontal_km'],depth_residual_km=row['depth_km']-search['depth_km'])
            eligible.append(c)
        eligible.sort(key=lambda r:(abs(r['origin_time_residual_s']),r['spatial_residual_km'],r['catalog_id']))
        candidates.extend(eligible)
        if len(eligible)>1:
            return dict(event_id=int(e['index']),status='ambiguous',source_catalog=catalog,location=None),candidates
        if eligible:
            status='matched' if catalog=='ISC-EHB' else 'fallback'
            reason=None if status=='matched' else ('outside_EHB_year_coverage' if not 1964<=utc(e['time']).year<=2021 else 'no_EHB_match_within_gates')
            return dict(event_id=int(e['index']),status=status,fallback_reason=reason,location=eligible[0]),candidates
    return dict(event_id=int(e['index']),status='unresolved',location=None),candidates

def reference(rows):
    if not rows: raise ValueError('Empty cluster')
    ordered=sorted(rows,key=lambda r:r['event_id'])
    medoid=min(ordered,key=lambda a:(sum(vector(a,b)['horizontal_km'] for b in ordered),a['event_id']))
    return dict(latitude=medoid['latitude'],longitude=medoid['longitude'],depth_km=statistics.median(r['depth_km'] for r in rows),
                epicentral_medoid_event_id=medoid['event_id'])

def csv_write(path, rows):
    keys=list(dict.fromkeys(k for row in rows for k in row))
    with path.open('w',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=keys or ['status']);writer.writeheader();writer.writerows(rows)

def run(root=ROOT, output=None):
    config=read(root/'config.json')
    if config['fallback_hierarchy'] != ['ISC-EHB','USGS-ComCat'] or config['adoption']!='review_only':
        raise ValueError('Unsupported hierarchy or adoption mode')
    if not 0 < config['max_time_residual_s'] <= 3600 or not 0 < config['max_horizontal_residual_km'] <= 1000:
        raise ValueError('Invalid match gates')
    for record in read(root/'inputs/extraction_manifest.json'):
        if sha(root/record['file'])!=record['sha256']: raise ValueError('Extracted workbook checksum mismatch')
    manifest=read(root/'inputs/source_manifest.json')
    for record in manifest:
        if sha(root/record['file'])!=record['sha256']: raise ValueError('Source checksum mismatch')
    for record in read(root/'inputs/baseline_manifest.json'):
        if sha(root/record['snapshot'])!=record['sha256']: raise ValueError('Baseline checksum mismatch')
    catalogs={'ISC-EHB':[], 'USGS-ComCat':[]}
    for item in manifest:
        path=root/item['file']
        if path.name.endswith('.hdf.gz'):
            with gzip.open(path,'rt') as f:
                for n,line in enumerate(f,1):
                    if line.strip(): catalogs['ISC-EHB'].append(parse_hdf(line,int(path.name[:4]),item['file'],n))
        elif path.name.startswith('usgs_'):
            catalogs['USGS-ComCat'].extend(parse_usgs(read(path),item['file']))
    # Deduplicate overlapping fallback queries, reject conflicting records.
    for catalog,rows in catalogs.items():
        unique={}
        for row in rows:
            key=row['catalog_id']
            if not key: raise ValueError('Empty catalog identifier')
            if key in unique and any(row[k]!=unique[key][k] for k in ['origin_time','latitude','longitude','depth_km']):
                raise ValueError('Conflicting catalog identifier: '+key)
            unique.setdefault(key,row)
        catalogs[catalog]=list(unique.values())
    events=read(root/'inputs/study_events.json');pairs=read(root/'inputs/study_pairs.json')
    ids=[int(e['index']) for e in events]
    if len(set(ids))!=len(ids): raise ValueError('Duplicate workbook event IDs')
    window=dt.timedelta(seconds=config['max_time_residual_s'])
    required_years={(utc(e['time'])+sign*window).year for e in events for sign in [-1,1]
                    if 1964<=(utc(e['time'])+sign*window).year<=2021}
    source_names={Path(r['file']).name for r in manifest}
    if any(f'{y}.hdf.gz' not in source_names for y in required_years) or any(f"usgs_{e['index']}.json" not in source_names for e in events):
        raise ValueError('Incomplete catalog acquisition; fallback must not hide missing sources')
    byname={Path(r['file']).name:r for r in manifest}
    for e in events:
        query=parse_qs(urlparse(byname[f"usgs_{e['index']}.json"]['url']).query)
        if utc(query['starttime'][0])>utc(e['time'])-window or utc(query['endtime'][0])<utc(e['time'])+window:
            raise ValueError('Frozen USGS request does not cover configured match window')
    matches=[];candidates=[]
    for e in events:
        m,c=match(e,catalogs,config); matches.append(m);candidates.extend(c)
    assigned={}
    for m in matches:
        if m['location']:
            loc=m['location']; key=(loc['source_catalog'],loc['catalog_id'])
            assigned.setdefault(key,[]).append(m)
    for group in assigned.values():
        if len(group)>1:
            for m in group: m.update(status='catalog_id_collision',location=None)
    byid={m['event_id']:m for m in matches}; original={int(e['index']):e for e in events}
    clusters=[];deviations=[]
    for members in components(pairs,ids):
        name='C'+str(min(members)); resolved=[byid[i]['location'] for i in members if byid[i]['location']]
        complete=len(resolved)==len(members)
        ref=reference(resolved) if complete else None
        cluster=dict(cluster_id=name,members=members,status='proposed_review_only' if complete else 'blocked_incomplete',reference=ref,
                     fallback_members=[i for i in members if byid[i]['status']=='fallback'])
        distances=[]
        for i in members:
            m=byid[i]; row=dict(cluster_id=name,event_id=i,status=m['status'])
            if m['location'] and ref:
                loc=m['location']; v=vector(ref,loc); dz=loc['depth_km']-ref['depth_km'];distances.append(v['horizontal_km'])
                row.update(v,depth_deviation_km=dz,separation_3d_km=math.hypot(v['horizontal_km'],dz))
            deviations.append(row)
        cluster['median_horizontal_scatter_km']=statistics.median(distances) if distances else None
        cluster['max_horizontal_scatter_km']=max(distances) if distances else None
        ehb=[r for r in resolved if r['source_catalog']=='ISC-EHB']
        cluster['ehb_only_sensitivity_reference']=reference(ehb) if ehb else None
        cluster['fallback_influence']=dict(vector(reference(ehb),ref),depth_change_km=ref['depth_km']-reference(ehb)['depth_km']) if ehb and ref else None
        clusters.append(cluster)
    # Content-derived run version covers all inputs and executable source files.
    hashed={str(p.relative_to(root)):sha(p) for p in sorted(root.rglob('*')) if p.is_file() and
        (p.is_relative_to(root/'inputs') or p.parent==root and p.suffix in ('.py','.json'))}
    run_id=hashlib.sha256(json.dumps(hashed,sort_keys=True).encode()).hexdigest()[:16]
    out=output or root/'runs'/run_id
    out.mkdir(parents=True,exist_ok=False)
    write(out/'run_manifest.json',dict(run_id=run_id,input_sha256=hashed,production_adoption=False,config=config))
    write(out/'matches.json',matches);write(out/'clusters.json',clusters)
    csv_write(out/'match_candidates.csv',candidates)
    csv_write(out/'member_deviations.csv',deviations)
    csv_write(out/'event_comparison.csv',[dict(status=m['status'],
        working_latitude=original[m['event_id']]['lat_best'],working_longitude=original[m['event_id']]['lon_best'],
        working_depth_km=original[m['event_id']]['depth_best'],**(m['location'] or {'event_id':m['event_id']})) for m in matches])
    csv_write(out/'cluster_references.csv',[dict(cluster_id=c['cluster_id'],members=' '.join(map(str,c['members'])),status=c['status'],
        fallback_members=' '.join(map(str,c['fallback_members'])),median_horizontal_scatter_km=c['median_horizontal_scatter_km'],
        max_horizontal_scatter_km=c['max_horizontal_scatter_km'],**(c['reference'] or {})) for c in clusters])
    csv_write(out/'working_pair_locations.csv',[{k:p.get(k) for k in ['label','index1','index2','lat','lon','depth','new_lat','new_lon','new_depth','centroid_lat','centroid_lon','centroid_depth_km','relative_location_phase_set','event2_minus_event1_delta_lat','event2_minus_event1_delta_lon','event2_minus_event1_delta_depth_km','event2_minus_event1_3d_km']} for p in pairs])
    print(out)
    return out

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path)
    args=parser.parse_args();run(output=args.output)
