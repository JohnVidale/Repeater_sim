"""Render comparison artifacts using frozen inputs; no waveform refit or adoption."""
import argparse
from collections import Counter
import csv
import math
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from workflow import ROOT, read, write, vector, csv_write, sha

def build(run, root=ROOT):
    manifest=read(run/'run_manifest.json')
    for file,digest in manifest['input_sha256'].items():
        if sha(root/file)!=digest: raise ValueError('Run input changed: '+file)
    matches=read(run/'matches.json');clusters=read(run/'clusters.json')
    events={int(e['index']):e for e in read(root/'inputs/study_events.json')}
    locations={m['event_id']:m['location'] for m in matches}
    pair_rows=read(root/'inputs/study_pairs.json')
    fig,axes=plt.subplots(5,3,figsize=(15,19),layout='constrained')
    for ax,c in zip(axes.flat,clusters):
        ref=c['reference']
        if ref is None:
            ax.text(.5,.5,c['cluster_id']+' blocked',ha='center');continue
        for i in c['members']:
            loc=locations[i];v=vector(ref,loc)
            color='#0072B2' if loc['source_catalog']=='ISC-EHB' else '#D55E00'
            ax.scatter(v['east_km'],v['north_km'],color=color,s=32)
            ax.annotate(str(i),(v['east_km'],v['north_km']),xytext=(3,4),textcoords='offset points',fontsize=7)
            e=events[i];old=dict(latitude=e['lat_best'],longitude=e['lon_best'])
            d=vector(ref,old);ax.scatter(d['east_km'],d['north_km'],marker='x',color='gray',s=25)
        for p in pair_rows:
            if int(p['index1']) in c['members'] and p['new_lat'] is not None and p['new_lon'] is not None:
                d=vector(ref,dict(latitude=p['new_lat'],longitude=p['new_lon']))
                ax.scatter(d['east_km'],d['north_km'],marker='+',color='#009E73',s=36)
        ax.scatter(0,0,marker='*',color='black',s=100)
        ax.set_title(f"{c['cluster_id']} | n={len(c['members'])} | depth={ref['depth_km']:.1f} km",fontsize=11)
        ax.set_xlabel('East from proposed reference (km)');ax.set_ylabel('North (km)')
        ax.set_aspect('equal',adjustable='datalim');ax.grid(alpha=.2);ax.margins(.2)
    for ax in axes.flat[len(clusters):]:ax.set_visible(False)
    fig.suptitle('REVIEW ONLY: blue ISC-EHB; orange USGS; gray × workbook best; green + pair new; black ★ proposed\nCatalog scatter is not physical repeater separation or centroid uncertainty',fontsize=13)
    fig.savefig(run/'cluster_maps.png',dpi=150);plt.close(fig)
    fig,axes=plt.subplots(1,2,figsize=(13,5),layout='constrained')
    for m in matches:
        loc=m['location']
        if not loc:continue
        axes[0].scatter(loc['origin_time_residual_s'],loc['spatial_residual_km'],c='#0072B2' if m['status']=='matched' else '#D55E00',s=24)
        axes[1].scatter(events[m['event_id']]['depth_best'],loc['depth_km'],c='#0072B2' if m['status']=='matched' else '#D55E00',s=24)
    axes[0].set(xlabel='Catalog minus workbook origin time (s)',ylabel='Distance from original event search seed (km)',title='Accepted matches: gates ±30 s and 100 km')
    axes[1].plot([0,100],[0,100],color='gray',lw=1)
    axes[1].set(xlabel='Workbook best depth (km)',ylabel='Individual catalog depth (km)',title='Depth comparison (blue EHB, orange USGS)')
    for ax in axes:ax.grid(alpha=.2)
    fig.savefig(run/'match_depth_qc.png',dpi=150);plt.close(fig)
    # Existing run vectors copied verbatim with exact source; no recalculation.
    differentials=[]
    for source in read(root/'inputs/baseline_manifest.json'):
        if Path(source['source']).name=='median_relative_location_offsets_no_pkikp_with_bootstrap_uncertainty.csv':
            with (root/source['snapshot']).open() as f:
                for r in csv.DictReader(f):
                    differentials.append(dict(source_file=source['source'],source_sha256=source['sha256'],**r))
    csv_write(run/'existing_differential_vectors.csv',differentials)
    sources=sorted({r['source_file'] for r in differentials})
    fig,axes=plt.subplots(1,max(1,len(sources)),figsize=(7*max(1,len(sources)),7),layout='constrained',squeeze=False)
    for ax,source in zip(axes.flat,sources):
        rows=[r for r in differentials if r['source_file']==source]
        for r in rows:
            try:e,n=float(r['east_km']),float(r['north_km'])
            except (ValueError,KeyError):continue
            if not math.isfinite(e+n):continue
            ax.annotate('',xy=(e,n),xytext=(0,0),arrowprops=dict(arrowstyle='->',color='#0072B2',alpha=.6))
            try:
                ax.errorbar(e,n,xerr=float(r['east_sigma_km']),yerr=float(r['north_sigma_km']),fmt='none',color='gray',alpha=.5)
            except (ValueError,KeyError):pass
        ax.set_title(Path(source).parent.name.replace('_workbook_','\n'),fontsize=10)
        ax.set(xlabel='Event 2 minus event 1 east (km)',ylabel='North (km)');ax.grid(alpha=.2);ax.set_aspect('equal',adjustable='datalim')
    fig.suptitle('Existing waveform fits: arrows + marginal bootstrap σ; separate from absolute cluster locations\nSource-run outputs, not fresh fits or confirmed current production results')
    fig.savefig(run/'existing_differential_vectors.png',dpi=150);plt.close(fig)
    fig,axes=plt.subplots(max(1,len(sources)),3,figsize=(15,5*max(1,len(sources))),layout='constrained',squeeze=False)
    for row_axes,source in zip(axes,sources):
        rows=[r for r in differentials if r['source_file']==source]
        for ax,key,sigma,title in zip(row_axes,['east_km','north_km','horizontal_km'],['east_sigma_km','north_sigma_km',None],['East','North','Horizontal magnitude']):
            for i,r in enumerate(rows):
                try:value=float(r[key])
                except (ValueError,KeyError):continue
                if not math.isfinite(value):continue
                if sigma:
                    try:err=float(r[sigma])
                    except (ValueError,KeyError):err=None
                else:err=None
                ax.errorbar(value,i,xerr=err,fmt='o',markersize=4,color='#0072B2',capsize=2)
            ax.set_yticks(range(len(rows)),[r['pair'] for r in rows]);ax.invert_yaxis();ax.axvline(0,color='gray',lw=.8)
            ax.set_title(title+' (km)');ax.grid(alpha=.2);ax.set_xlabel(Path(source).parent.name,fontsize=8)
    fig.suptitle('Existing differential components by pair; bars are marginal bootstrap σ\nHorizontal magnitude shown separately; full percentile intervals remain in CSV')
    fig.savefig(run/'differential_components.png',dpi=150);plt.close(fig)
    # Explicit vector/scalar comparison, without conflating catalog and waveform uncertainty.
    comparisons=[]
    for r in differentials:
        a,b=locations.get(int(r['event1'])),locations.get(int(r['event2']))
        if not a or not b:continue
        v=vector(a,b)
        row=dict(pair=r['pair'],source_file=r['source_file'],catalog_east_km=v['east_km'],catalog_north_km=v['north_km'],catalog_horizontal_km=v['horizontal_km'])
        try:
            east,north=float(r['east_km']),float(r['north_km'])
            row.update(waveform_east_km=east,waveform_north_km=north,waveform_horizontal_km=math.hypot(east,north),
                       vector_difference_km=math.hypot(east-v['east_km'],north-v['north_km']),scalar_difference_km=math.hypot(east,north)-v['horizontal_km'])
        except (ValueError,KeyError):pass
        comparisons.append(row)
    csv_write(run/'catalog_vs_differential_vectors.csv',comparisons)
    counts=Counter(m['status'] for m in matches)
    lines=['# Catalog location review','',f"Run `{manifest['run_id']}`. Review only; no locations adopted.",'',
        f"{len(matches)} events; {len(clusters)} connected components. Match status: {dict(counts)}.",'',
        '## Proposed exact rule','',
        'All valid pair-table edges are connected before retaining components touching active pairs. Each event contributes once. Match against ISC-EHB first, then USGS ComCat, within 30 seconds and 100 km of the original event LAT/LON/DEP (NEIC columns only if missing). Multiple candidates in the first nonempty catalog block selection; catalog-ID collisions block every affected event. No workbook best-location or station-acceptance fallback is allowed. Missing members block a complete cluster reference.','',
        'For each complete cluster, choose the member epicentre with minimum summed great-circle distance (6371.0088 km spherical radius; smallest workbook event ID resolves exact ties). Use the median of all member catalog depths. Fallback members receive equal weight. The EHB-only sensitivity below exposes that choice. This is a reference convention, not an uncertainty-weighted hypocentre inversion.','',
        '| Cluster | Members | Latitude | Longitude | Depth km | Median/max horizontal scatter km | Fallback count | Fallback influence horizontal/depth km |',
        '|---|---|---:|---:|---:|---:|---:|---:|']
    for c in clusters:
        r=c['reference'];influence=c['fallback_influence']
        if r:
            sensitivity=f"{influence['horizontal_km']:.2f}/{influence['depth_change_km']:.2f}" if influence else 'No EHB members'
            lines.append(f"| {c['cluster_id']} | {', '.join(map(str,c['members']))} | {r['latitude']:.4f} | {r['longitude']:.4f} | {r['depth_km']:.2f} | {c['median_horizontal_scatter_km']:.2f}/{c['max_horizontal_scatter_km']:.2f} | {len(c['fallback_members'])} | {sensitivity} |")
        else:lines.append(f"| {c['cluster_id']} | blocked incomplete | | | | | | |")
    lines += ['', '## QC and interpretation','',
        '![Cluster comparison](cluster_maps.png)','', '![Matches and depths](match_depth_qc.png)','',
        '![Separate differential vectors](existing_differential_vectors.png)','',
        '![Differential components by pair](differential_components.png)','',
        'Member scatter is not a confidence interval and does not establish physical source separation. The medoid can coincide with a fallback event; compare the EHB-only sensitivity before approval. Two-member medoids tie, so the smaller event ID determines the epicentre. No precision gain from shared biases is assumed. Depth classes are conservatively derived from ISC flags; unknown classes remain Not recovered. USGS depths do not acquire an EHB class.','',
        'The saved waveform vectors retain their source run, east/north components, scalar separation, and existing marginal bootstrap uncertainties. Catalog-minus-waveform vector differences and scalar differences are separate fields. No new differential fit or uncertainty calculation was performed. Neither those vectors nor station acceptance enter the absolute reference calculation.','',
        'Review the membership, fallback influence, depth rule, and large-scatter clusters before requesting any production migration. No writer or active-configuration switch is included.','',
        'Sources: [ISC-EHB](https://www.isc.ac.uk/isc-ehb/), [official HDF format](https://download.isc.ac.uk/isc-ehb/format2.hdf), [USGS query documentation](https://earthquake.usgs.gov/fdsnws/event/1/). Exact requests and retrieval times are in inputs/source_manifest.json.']
    (run/'REVIEW.md').write_text('\n'.join(lines)+'\n')
    write(run/'output_checksums.json',{p.name:sha(p) for p in sorted(run.iterdir()) if p.is_file() and p.name!='output_checksums.json'})

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('run',type=Path);build(p.parse_args().run)
