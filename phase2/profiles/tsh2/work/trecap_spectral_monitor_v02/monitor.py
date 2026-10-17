"""Causal 128-ms spectral monitor; no model, labels or future-frame lookup."""
import numpy as np
from common import need

def cluster_events(events):
    """Group adjacent band activations causally; never backdate member detection."""
    groups=[]
    for e in sorted(events,key=lambda x:(x['time'],x['band'])):
        choices=[]
        for i,g in enumerate(groups):
            if 0<=e['time']-g['time']<=.256+1e-12 and e['band'] not in g['bands'] and any(abs(e['band']-b)==1 for b in g['bands']):
                choices.append((e['time']-g['time'],i))
        if choices:
            _,i=min(choices);g=groups[i]
            g['bands']=sorted(g['bands']+[e['band']]);g['members'].append(dict(e))
            g['last_update_time']=e['time'];g['bandwidth_bands']=max(g['bands'])-min(g['bands'])+1
        else:
            groups.append({**e,'bands':[e['band']],'members':[dict(e)],'last_update_time':e['time'],'bandwidth_bands':1})
    return groups

def monitor(features, ns):
    f=np.asarray(features)
    need(f.dtype==np.uint64 and f.shape==(ns//128+1,21),'Native feature geometry')
    block_count=(ns//128-1)//48
    need(block_count>=8,'At least eight baseline blocks')
    interior=f[1:1+48*block_count].reshape(block_count,48,21)
    bands=interior[:,:,:16].astype(np.float64).mean(axis=1)
    total=interior[:,:,16].astype(np.float64).sum(axis=1)
    numer=(interior[:,:,17].astype(np.float64)+interior[:,:,20].astype(np.float64)*2.0**64).sum(axis=1)
    valid=total>0
    centroid=np.divide(numer*187.5,total,out=np.zeros_like(total),where=valid)
    peak=[]
    for b in interior:
        ids=b[:,19][b[:,18]>0].astype(np.int64)
        need(np.all((ids>=0)&(ids<129)),'Invalid peak index')
        peak.append(int(np.argmax(np.bincount(ids,minlength=129))) if len(ids) else -1)
    ends=(1+48*np.arange(1,block_count+1))*128/48000
    baseline=np.median(bands[:8],axis=0)
    totals=total/48
    active=(bands>=4*baseline)&((bands-baseline)>=1e9)&(bands>=1e-4*totals[:,None])&(totals[:,None]>0)
    active[:8]=False
    persistence=np.zeros(16,dtype=np.int64);events=[]
    for i,a in enumerate(active):
        persistence=np.where(a,persistence+1,0)
        for b in np.flatnonzero(persistence==3):
            events.append({'band':int(b),'time':float(ends[i]),'block':i})
    return {'bands':bands,'total':totals,'centroid':centroid,'valid':valid,
            'peak':np.asarray(peak,dtype=np.int64),'ends':ends,'active':active,
            'raw_events':events,'events':cluster_events(events)}

def serial(m):
    return {k:(v.tolist() if isinstance(v,np.ndarray) else v) for k,v in m.items()}

def natural_quality(base, got):
    need(np.array_equal(base['ends'],got['ends']),'Same monitor geometry')
    valid=base['valid'];zero=~valid
    peak_ok=got['valid'] & (np.abs(got['peak']-base['peak'])<=1)
    peak_fraction=float(np.mean(peak_ok[valid])) if np.any(valid) else 1.0
    centroid_errors=np.abs(got['centroid'][valid]-base['centroid'][valid])
    centroid_invalid=int(np.count_nonzero(valid&~got['valid']))
    centroid_p95=float(np.percentile(centroid_errors,95)) if len(centroid_errors) else 0.0
    active=base['bands']>=np.maximum(1e9,1e-4*base['total'][:,None])
    errors=np.divide(np.abs(got['bands']-base['bands']),base['bands'],
                     out=np.zeros_like(base['bands']),where=base['bands']>0)*100
    p95=float(np.percentile(errors[active],95)) if np.any(active) else 0.0
    per_band=[]
    for b in range(16):
        mask=active[:,b];values=errors[mask,b]
        per_band.append({'band':b,'active_groups':int(mask.sum()),'excluded_groups':int((~mask).sum()),
                         'relative_error_p95_percent':float(np.percentile(values,95)) if len(values) else None,
                         'relative_error_max_percent':float(np.max(values)) if len(values) else None})
    worst=max([b['relative_error_p95_percent'] for b in per_band if b['active_groups']]+[0.0])
    extra_zero=int(np.count_nonzero(zero&got['valid']))
    passed=peak_fraction>=.99 and centroid_invalid==0 and centroid_p95<=187.5 and p95<=10 and worst<=20 and extra_zero==0
    return {'pass':bool(passed),'groups':len(valid),'valid_baseline_groups':int(valid.sum()),
            'peak_within_one_bin_fraction':peak_fraction,'centroid_p95_hz':centroid_p95,
            'centroid_invalid_groups':centroid_invalid,'active_band_error_p95_percent':p95,
            'worst_band_error_p95_percent':worst,'per_band':per_band,'extra_nonzero_groups':extra_zero,
            'activity_agreement':match_events(base['events'],got['events'],.256,symmetric=True)}

def match_events(expected, got, tolerance, symmetric=False):
    used=set();matches=[];missed=[]
    for e in sorted(expected,key=lambda x:(x['time'],x['band'])):
        candidates=[]
        for j,g in enumerate(got):
            if j in used:continue
            for member in g.get('members',[g]):
                delay=member['time']-e['time']
                if member['band']==e['band'] and ((abs(delay)<=tolerance+1e-12) if symmetric else (-1e-12<=delay<=tolerance+1e-12)):
                    candidates.append((abs(delay),j,member))
        if candidates:
            _,j,g=min(candidates,key=lambda x:(x[0],x[1]));used.add(j)
            matches.append({'band':e['band'],'expected_time':e['time'],'detected_time':g['time'],'delay':g['time']-e['time']})
        else:missed.append(e)
    extra=[g for j,g in enumerate(got) if j not in used]
    return {'pass':not missed and not extra,'expected':len(expected),'detected':len(got),
            'matched':len(matches),'missed':missed,'extra':extra,'matches':matches}
