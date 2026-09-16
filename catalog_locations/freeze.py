"""Freeze a new input release. Requires a new destination; never updates old inputs."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import openpyxl

def freeze(repo, destination):
    if destination.exists(): raise FileExistsError(destination)
    destination.mkdir(parents=True)
    baseline=destination/'baseline';baseline.mkdir()
    config=json.loads((repo/'analysis_config.json').read_text())
    paths=sorted(repo.glob('*.py'))+[repo/'analysis_config.json',repo/'README.md',repo/'AGENTS.md']
    paths += [Path(config[k]) for k in ['catalog_path','manual_pick_alignment_workbook']]
    paths += sorted((repo/'Notes').glob('*.md'))
    for pattern in ['*/median_absolute_relative_locations_no_pkikp.csv','*/median_relative_location_offsets_no_pkikp_with_bootstrap_uncertainty.csv','*/manifest.json','*/workflow_run_summary.json']:
        paths += sorted((repo/'outputs').glob(pattern))
    manifest=[]
    for i,path in enumerate(paths):
        copied=baseline/f'{i:03d}_{path.name}';shutil.copyfile(path,copied)
        digest=hashlib.sha256(copied.read_bytes()).hexdigest()
        if hashlib.sha256(path.read_bytes()).hexdigest()!=digest: raise ValueError('Source changed during freeze')
        manifest.append(dict(source=str(path),snapshot='inputs/'+str(copied.relative_to(destination)),sha256=digest,bytes=copied.stat().st_size))
    (destination/'baseline_manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    state={k:subprocess.check_output(['git',*args],cwd=repo,text=True) for k,args in {
        'root':['rev-parse','--show-toplevel'],'status':['status','--short'],'head':['rev-parse','HEAD'],
        'log':['log','-5','--oneline'],'remote':['remote','-v'],'diff':['diff','--binary']}.items()}
    (baseline/'git_state.json').write_text(json.dumps(state,indent=2)+'\n')
    source=next(r for r in manifest if r['source']==config['catalog_path'])
    workbook=openpyxl.load_workbook(destination.parent/source['snapshot'],read_only=True,data_only=True)
    tables={}
    try:
        for sheet,key in [('events','index'),('pairs','label')]:
            rows=iter(workbook[sheet].values)
            headers=[str(v).strip().lower() if v is not None else f'unnamed_{i}' for i,v in enumerate(next(rows))]
            if len(set(headers))!=len(headers): raise ValueError('Duplicate headers: '+sheet)
            tables[sheet]=[dict(zip(headers,row)) for row in rows if row[0] is not None]
            if len({r[key] for r in tables[sheet]})!=len(tables[sheet]): raise ValueError('Duplicate IDs: '+sheet)
    finally:workbook.close()
    events={int(r['index']):r for r in tables['events']}
    valid=[p for p in tables['pairs'] if p.get('index1') in events and p.get('index2') in events]
    excluded=[p for p in tables['pairs'] if p not in valid]
    active={p['label'] for p in valid}&set(config['pairs'])
    if active!=set(config['pairs']): raise ValueError('Missing active pair')
    members={int(p[k]) for p in valid if p['label'] in active for k in ['index1','index2']}
    while True:
        before=set(members)
        for p in valid:
            if p['index1'] in members or p['index2'] in members: members.update([int(p['index1']),int(p['index2'])])
        if members==before:break
    data={'workbook_tables.json':tables,'study_events.json':[events[i] for i in sorted(members)],
          'study_pairs.json':[p for p in valid if p['index1'] in members],'excluded_pairs.json':excluded}
    for name,value in data.items():
        (destination/name).write_text(json.dumps(value,indent=2,default=str,allow_nan=False)+'\n')
    (destination/'extraction_manifest.json').write_text(json.dumps([dict(file='inputs/'+name,sha256=hashlib.sha256((destination/name).read_bytes()).hexdigest()) for name in data],indent=2)+'\n')

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--repo',type=Path,required=True);parser.add_argument('--destination',type=Path,required=True)
    args=parser.parse_args();freeze(args.repo.resolve(),args.destination.resolve())
