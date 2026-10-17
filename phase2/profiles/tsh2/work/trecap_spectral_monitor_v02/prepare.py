"""Register inputs, calibrate, then evaluate a frozen monitor without RTL changes."""
import argparse, sys
from pathlib import Path
sys.dont_write_bytecode=True
import numpy as np
from scipy.io import wavfile
from scipy.signal import resample_poly
from common import ROOT,WORK,OUT,DATA,NATIVE,COEFF,THRESHOLDS,need,read,save,sha,fresh,verify
from monitor import monitor,serial,natural_quality,match_events
sys.path.insert(0,str(NATIVE))
from native_api import Native

def lock():
    files=list(WORK.glob('*.py'))+[WORK/'PROTOCOL.md']+list(NATIVE.glob('*.py'))
    qpath=NATIVE/'build01/qualification.json'
    q=read(qpath)
    need(q['status'].startswith('PASS'),'Native qualification')
    # Qualification format is intentionally read from the completed receipt.
    evidence=q.get('evidence_sha256',q.get('files_sha256',{}))
    need(bool(evidence),'Native qualification must bind evidence')
    verify(evidence)
    files+=[qpath]
    result={str(p):sha(p) for p in files};result.update(evidence)
    return result

def inputs():
    out=fresh(OUT/'inputs01');manifest=read(DATA/'manifest.json')
    need(manifest['status']=='PASS_ORIGINAL_ESC50_SUBSET_VERIFIED','Original corpus')
    records=[]
    for category in sorted({r['category'] for r in manifest['files']}):
        entries=sorted([r for r in manifest['files'] if r['category']==category],key=lambda r:r['filename'])
        need(len(entries)==2,'Two per category')
        for j,r in enumerate(entries):
            need(sha(r['path'])==r['sha256'],'Original WAV binding')
            fs,a=wavfile.read(r['path']);need(fs==44100 and a.dtype==np.int16 and a.ndim==1,'Frozen source PCM format')
            x=resample_poly(a.astype(np.float64)/32768,160,147,window=('kaiser',5.0))
            quant=np.rint(x*2048);clipped=int(np.count_nonzero((quant<-2048)|(quant>2047)))
            pcm=np.clip(quant,-2048,2047).astype(np.int32);need(len(pcm)==240000,'Five seconds')
            p=out/(Path(r['filename']).stem+'.npy');np.save(p,pcm,allow_pickle=False)
            records.append({'id':p.stem,'category':category,'kind':'natural','split':'calibration' if j==0 else 'heldout',
                            'pcm':str(p),'ns':len(pcm),'sha256':sha(p),'clipped_samples':clipped,'source':r})
    n=245760;t=np.arange(n)/48000;angle=2*np.pi*np.arange(n)/256
    base=512*np.sin(8*angle);on=(t>=2.048)&(t<4.096)
    raw=[np.zeros(n),base.copy()]+[base+A*np.sin(48*angle)*on for A in (16,32,64)]
    raw += [np.where(t<2.048,base,512*np.sin(20*angle)),
            base+32*np.sin(48*angle)*((t>=2.048)&(t<2.176)),
            512*np.sin(8.4*angle)+32*np.sin(48.4*angle)*on+np.random.default_rng(20261003).normal(0,2,n)]
    names=['zero','steady','weak16','weak32','weak64','switch','transient','offbin_noise']
    for i,(name,x) in enumerate(zip(names,raw)):
        quant=np.rint(x);need(np.all((quant>=-2048)&(quant<=2047)),'Synthetic saturation not expected')
        pcm=quant.astype(np.int32);p=out/('synthetic_'+name+'.npy');np.save(p,pcm,allow_pickle=False)
        targets=[{'band':5,'time':2.048}] if i in (2,3,4,7) else [{'band':2,'time':2.048}] if i==5 else []
        records.append({'id':p.stem,'category':name,'kind':'synthetic','split':'control','pcm':str(p),
                        'ns':n,'sha256':sha(p),'clipped_samples':0,'expected_events':targets})
    save(out/'index.json',{'status':'PASS_REGISTERED_INPUTS','protocol_sha256':sha(WORK/'PROTOCOL.md'),
         'dataset_manifest_sha256':sha(DATA/'manifest.json'),'records':records,
         'sample_rate':48000,'quantization_scale':2048,'new_physical_captures':False})
    print('INPUTS REGISTERED',flush=True)

def process(entry,out,native,legacy):
    pcm=np.load(entry['pcm'],allow_pickle=False);need(sha(entry['pcm'])==entry['sha256'],'Frozen input')
    folder=out/entry['id'];folder.mkdir();cases=[];base=None
    for threshold in THRESHOLDS:
        prefix=folder/('thr'+str(threshold));produced=native.produce(pcm,threshold)
        features=produced['features'];dense=native.prepare(produced['wire'],threshold,len(features))
        need(np.array_equal(features,dense['features']),'Producer/sparse feature equality')
        need(np.array_equal(features,native.decode(dense['wire'],threshold,len(features),'dense')),'Dense feature equality')
        need(np.array_equal(features,native.run_pcm(pcm,threshold)),'Direct PCM equality')
        need(np.array_equal(produced['spectra'],dense['spectra']),'Dense/sparse power equality')
        full=legacy.run_full(pcm,threshold)
        need(full['wire']==produced['wire'],'Frozen full DSP packet equality')
        reconstructed=full['y'][384:384+len(pcm)]
        if threshold==0:need(np.array_equal(reconstructed,pcm),'Threshold0 waveform identity')
        den=float(np.linalg.norm(pcm.astype(float)));nr=float(np.linalg.norm(reconstructed.astype(float)-pcm))
        nrmse=100*nr/den if den else 0.0
        m=monitor(features,len(pcm))
        if base is None:base=m
        quality=natural_quality(base,m)
        synthetic=match_events(entry.get('expected_events',[]),m['events'],.512) if entry['kind']=='synthetic' else None
        files={}
        for suffix,value in [('features.npy',features),('spectra.npy',produced['spectra'])]:
            p=Path(str(prefix)+'_'+suffix);np.save(p,value,allow_pickle=False);files[suffix]=str(p)
        for suffix,value in [('sparse.tsp1',produced['wire']),('dense.tsp1',dense['wire'])]:
            p=Path(str(prefix)+'_'+suffix);p.write_bytes(value);files[suffix]=str(p)
        p=Path(str(prefix)+'_monitor.json');save(p,serial(m));files['monitor.json']=str(p)
        cases.append({'threshold':threshold,'quality':quality,'synthetic_events':synthetic,
                      'waveform_nrmse_percent':nrmse,'sparse_bytes':len(produced['wire']),
                      'dense_bytes':len(dense['wire']),'pcm16_bytes':len(pcm)*2,'packed12_bytes':len(pcm)*3//2,
                      'retained_entries':(len(produced['wire'])-len(features)*48)//8,
                      'frames':len(features),'monitor_groups':len(m['ends']),'files':files,
                      'sha256':{p:sha(p) for p in files.values()}})
    return {'id':entry['id'],'category':entry['category'],'kind':entry['kind'],'split':entry['split'],
            'ns':entry['ns'],'cases':cases}

def campaign(phase):
    idx=read(OUT/'inputs01/index.json');need(sha(WORK/'PROTOCOL.md')==idx['protocol_sha256'],'Frozen protocol')
    bindings=lock()
    if phase=='calibrate':out=fresh(OUT/'calibration01');entries=[e for e in idx['records'] if e['split']!='heldout']
    else:
        cal=read(OUT/'calibration01/calibration.json');verify(cal['sources_sha256'])
        need(cal['input_index_sha256']==sha(OUT/'inputs01/index.json'),'Input binding')
        out=fresh(OUT/'quality01');entries=[e for e in idx['records'] if e['split']=='heldout']
    # Import old immutable wrapper separately to avoid module-name collision.
    import importlib.util
    p=ROOT/'work/trecap_ai_scheduler_v01/native/native_api.py'
    spec=importlib.util.spec_from_file_location('old_reference',p);old=importlib.util.module_from_spec(spec);spec.loader.exec_module(old)
    oldq=read(p.parent/'build01/qualification.json');verify(oldq['evidence_sha256'])
    bindings.update(oldq['evidence_sha256']);bindings[str(p)]=sha(p)
    results=[]
    with Native(COEFF,384000) as native,old.Native(COEFF,384000) as legacy:
        for entry in entries:
            results.append(process(entry,out,native,legacy));print(phase.upper()+' '+entry['id']+' PASS_EXACT',flush=True)
    verify(bindings)
    if phase=='calibrate':
        candidate=[]
        for t in THRESHOLDS:
            checks=[]
            for r in results:
                c=next(c for c in r['cases'] if c['threshold']==t)
                passed=c['synthetic_events']['pass'] if r['kind']=='synthetic' else c['quality']['pass']
                checks.append({'recording':r['id'],'pass':passed})
            candidate.append({'threshold':t,'pass':all(c['pass'] for c in checks),'checks':checks})
        eligible=[r['threshold'] for r in candidate if r['pass']]
        chosen=max(eligible) if eligible else 0
        save(out/'calibration.json',{'status':'PASS_SELECTION_FROZEN','input_index_sha256':sha(OUT/'inputs01/index.json'),
             'sources_sha256':bindings,'results':results,'candidates':candidate,'threshold':chosen,
             'fallback_no_accepted_threshold':not bool(eligible),'new_physical_captures':False})
        print('FROZEN THRESHOLD '+str(chosen)+' accepted='+str(bool(eligible)),flush=True)
    else:
        chosen=cal['threshold'];pass_all=all(next(c for c in r['cases'] if c['threshold']==chosen)['quality']['pass'] for r in results)
        save(out/'quality.json',{'status':'PASS_HELDOUT_EVALUATION','calibration_sha256':sha(OUT/'calibration01/calibration.json'),
             'threshold':chosen,'heldout_quality_pass':pass_all,'results':results,'new_physical_captures':False})
        print('HELDOUT QUALITY '+str(pass_all),flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('phase',choices=['inputs','calibrate','evaluate']);a=p.parse_args()
    inputs() if a.phase=='inputs' else campaign(a.phase)
