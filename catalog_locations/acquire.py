"""Explicit network acquisition; processing is offline. Never silently refresh files."""
import datetime as dt
import hashlib
import json
from pathlib import Path
import urllib.request
import urllib.parse

ROOT = Path(__file__).resolve().parent

def acquire():
    raw = ROOT / 'inputs' / 'raw'
    raw.mkdir(exist_ok=True)
    events = json.loads((ROOT / 'inputs/study_events.json').read_text())
    config = json.loads((ROOT / 'config.json').read_text())
    window = dt.timedelta(seconds=config['max_time_residual_s'])
    requests = [('format2.hdf', 'https://download.isc.ac.uk/isc-ehb/format2.hdf')]
    years = sorted({(dt.datetime.fromisoformat(e['time'].rstrip('Z'))+sign*window).year
                    for e in events for sign in [-1,1]
                    if 1964 <= (dt.datetime.fromisoformat(e['time'].rstrip('Z'))+sign*window).year <= 2021})
    requests += [(f'{y}.hdf.gz', f'https://download.isc.ac.uk/isc-ehb/{y}.hdf.gz') for y in years]
    # USGS ComCat preferred hypocentre is the declared fallback, queried for every
    # member so an EHB non-match inside its year coverage is handled as well.
    for e in events:
        t = dt.datetime.fromisoformat(e['time'].rstrip('Z'))
        params = dict(format='geojson', starttime=(t-window).isoformat(),
                      endtime=(t+window).isoformat(), orderby='time-asc')
        requests.append((f"usgs_{e['index']}.json", 'https://earthquake.usgs.gov/fdsnws/event/1/query?' + urllib.parse.urlencode(params)))
    manifest_path = ROOT / 'inputs/source_manifest.json'
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else []
    known = {r['file']: r for r in manifest}
    for name, url in requests:
        relative = 'inputs/raw/' + name
        dest = raw / name
        if relative in known:
            if known[relative]['url'] != url:
                raise ValueError('Query changed; create a new input release: '+relative)
            if not dest.exists() or hashlib.sha256(dest.read_bytes()).hexdigest() != known[relative]['sha256']:
                raise ValueError('Frozen source changed: ' + relative)
            continue
        if dest.exists():
            raise ValueError('Unmanifested source exists: ' + relative)
        data = urllib.request.urlopen(url, timeout=60).read()
        dest.write_bytes(data)
        manifest.append(dict(file=relative, url=url, retrieved_utc=dt.datetime.now(dt.timezone.utc).isoformat(),
                             sha256=hashlib.sha256(data).hexdigest(), bytes=len(data)))
        manifest_path.write_text(json.dumps(manifest, indent=2) + '\n')
        print(name, len(data), flush=True)

if __name__ == '__main__':
    acquire()
