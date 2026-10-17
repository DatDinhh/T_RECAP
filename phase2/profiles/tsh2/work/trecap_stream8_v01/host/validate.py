"""Exact downloaded TSH2 content, separate from physical provenance/performance."""
from pathlib import Path
import argparse,csv,hashlib,importlib.util,json,struct,sys,tarfile,wave
sys.dont_write_bytecode=True
import numpy as np
ROOT=Path(__file__).resolve().parents[3]
DECODER=ROOT/'work/trecap_jtag_readback_v01/physical/validate_tsp1.py'
THRESHOLDS=(0,100000000,1000000000,10000000000,100000000000)
def need(ok,msg):
    if not ok:raise ValueError(msg)
def sha(data):return hashlib.sha256(data).hexdigest()
def filehash(p):return sha(Path(p).read_bytes())
def writejson(p,d):Path(p).write_text(json.dumps(d,indent=2,allow_nan=False)+'\n',encoding='utf-8')
def load_fixtures(path):
    data=json.loads(path.read_text());need(data['status']=='PASS','qualified fixtures')
    need(data['geometry']==dict(Ns=384000,Ny=384512,frames=3001,sample_rate=48000,delay=384),'geometry')
    for n,h in json.loads((path.parent/'manifest.json').read_text()).items():need(filehash(path.parent/n)==h,'fixture drift '+n)
    need([c['threshold'] for c in data['cases']]==list(THRESHOLDS),'threshold matrix')
    need(filehash(data['input_i32le'])==data['input_sha256'],'input hash')
    return data
def verify_package(meta):
    need(filehash(meta['archive'])==meta['archive_sha256'],'upload hash')
    for group in ('source_files','build_files'):
        for n,h in meta[group].items():need(filehash(n)==h,'package source/build drift '+n)
    reg=meta['build_registration'];need(filehash(reg['path'])==reg['sha256'],'registration drift')
    need(json.loads(Path(reg['path']).read_text())['source_id']==meta['source_id'],'registered source')
def case_order(cases):return [(cases[0],False)]+[(c,True) for c in cases]
def name(c,sparse):return c['case_id']+('_sparse' if sparse else '_dense')
def archive_files(path,digest):
    need(path.stat().st_size<=64*1024*1024 and filehash(path)==digest,'bounded archive identity');files={};total=0
    with tarfile.open(path,'r:gz') as t:
        for e in t:
            need(e.isfile() and '/' not in e.name and '\\' not in e.name and e.name not in ('.','..') and e.name not in files,'regular unique root member')
            total+=e.size;need(0<=e.size<=4*1024*1024 and total<=64*1024*1024 and len(files)<64,'archive bounds');files[e.name]=t.extractfile(e).read()
    return files
def validate_content(wire,y,c,sparse):
    need(type(sparse)==bool,'mode');gold=c['packets']['sparse' if sparse else 'dense']
    need(len(wire)==gold['bytes'] and sha(wire)==gold['sha256'] and wire==Path(gold['path']).read_bytes(),'all spectral bytes exact')
    need(len(y)==384512*4 and sha(y)==c['y_sha256'] and y==Path(c['y_i32le']).read_bytes(),'all384512Y exact')
    spec=importlib.util.spec_from_file_location('stream_decoder',DECODER);decoder=importlib.util.module_from_spec(spec);spec.loader.exec_module(decoder)
    offset=0;feature_digest=hashlib.sha256()
    with Path(c['expected_features']).open(newline='') as f:
        rows=csv.DictReader(f)
        for frame in range(3001):
            need(len(wire)-offset>=48,'header truncation');size=(48+int.from_bytes(wire[offset+12:offset+16],'little')+7)&~7
            need(48<=size<=1080 and offset+size<=len(wire),'packet boundary');values=decoder.decode_record(wire[offset:offset+size],frame,c['threshold'],sparse)
            row=next(rows);need(int(row['frame_idx'])==frame and values==[int(row[f'band{k}']) for k in range(16)],'all16 features exact')
            feature_digest.update((','.join(map(str,values))+'\n').encode());offset+=size
        need(next(rows,None) is None and offset==len(wire),'exact frame count')
    return {'case_id':c['case_id'],'threshold':c['threshold'],'sparse':sparse,'bytes':len(wire),'wire_sha256':sha(wire),'y_sha256':sha(y),'y_samples':384512,'records':3001,'feature_components':48016,'features_sha256':feature_digest.hexdigest()}
def validate_receipt(r,c,sparse,meta,boot,epoch,bytecount):
    need(r['schema']=='tsh2-stream-client-v1' and r['status']=='CAPTURED_PENDING_PC_VALIDATION','client receipt')
    expected=dict(source_id=meta['source_id'],boot_id=boot,threshold=c['threshold'],sparse=int(sparse),epoch=epoch,input_count=384000,y_count=384512,frames=3001,drops=0,bytes=bytecount,performance_comparison=False)
    for k,v in expected.items():need(r.get(k)==v,'receipt '+k)
    need(type(r['fabric_cycles_including_host_stalls'])==int and 0<r['fabric_cycles_including_host_stalls']<=3000000000,'cycle bound')
    need(type(r['poll_iterations'])==int and 0<=r['poll_iterations']<2000000,'loop bound')
def save_wav(p,values):
    pcm=values.astype(np.int64)*64;need(np.max(pcm)<=32767 and np.min(pcm)>=-32768,'sharedgain4 no clipping')
    with wave.open(str(p),'wb') as w:w.setparams((1,2,48000,0,'NONE','not compressed'));w.writeframes(pcm.astype('<i2').tobytes())
def main():
    p=argparse.ArgumentParser();p.add_argument('--fixtures',type=Path,required=True);p.add_argument('--package',type=Path,required=True);p.add_argument('--archive',type=Path,required=True);p.add_argument('--archive-sha256',required=True);p.add_argument('--boot-id',required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args()
    need(not a.out.exists(),'fresh validation output');meta=json.loads((a.package/'package.json').read_text());need(meta['schema']=='tsh2-stream-package-v1','package schema');verify_package(meta);gold=load_fixtures(a.fixtures)
    need(filehash(a.fixtures)==meta['fixtures_sha256'] and filehash(a.fixtures.parent/'manifest.json')==meta['fixture_manifest_sha256'],'fixture binding')
    files=archive_files(a.archive,a.archive_sha256);ordered=case_order(gold['cases']);allowed={'boot_before.txt','boot_after.txt','hash_before.txt','hash_after.txt','system_before.json','system_after.json','RESULTS.sha256'}|{name(c,s)+ext for c,s in ordered for ext in ('.tsp1','.y.i32le','.json','.stdout','.stderr','.rc')}
    need(set(files)==allowed,'exact43-member result inventory')
    for phase in ('before','after'):
        need(files['boot_'+phase+'.txt'].decode().strip()==a.boot_id,'boot bracket');lines=files['hash_'+phase+'.txt'].decode().splitlines();need(set(lines)=={n+': OK' for n in meta['payload_files']} and len(lines)==len(meta['payload_files']),'immutable payload bracket')
        probe=json.loads(files['system_'+phase+'.json']);need(probe['status']=='PASS_HPS_SYSTEM_STATE_ONLY' and probe['bridge_reset']==5 and probe['manager_mode']==4 and not probe['fpga_aperture_accessed'] and not probe['writes_performed'],'HPS bridge/system bracket')
    hashes={}
    for line in files['RESULTS.sha256'].decode().splitlines():
        h,n=line.split('  ',1);need(n not in hashes,'duplicate manifest');hashes[n]=h
    need(set(hashes)==set(files)-{'RESULTS.sha256'},'manifest inventory')
    for n,h in hashes.items():need(sha(files[n])==h,'result manifest '+n)
    results=[];actual={};e=meta['first_epoch']
    for c,sparse in ordered:
        n=name(c,sparse);need(files[n+'.rc'].decode().strip()=='0' and files[n+'.stderr']==b'' and files[n+'.stdout'].decode().strip()=='CAPTURED_PENDING_PC_VALIDATION','client success')
        r=validate_content(files[n+'.tsp1'],files[n+'.y.i32le'],c,sparse);receipt=json.loads(files[n+'.json']);validate_receipt(receipt,c,sparse,meta,a.boot_id,e,r['bytes']);e+=1;r['epoch']=receipt['epoch'];r['fabric_cycles_including_host_stalls']=receipt['fabric_cycles_including_host_stalls'];results.append(r)
        actual[n]=np.frombuffer(files[n+'.y.i32le'],dtype='<i4').copy()
    verify_package(meta);a.out.mkdir(parents=True);x=np.frombuffer(Path(gold['input_i32le']).read_bytes(),dtype='<i4');save_wav(a.out/'00_before.wav',x);metrics=[]
    for c in gold['cases']:
        y=actual[name(c,True)];aligned=y[384:384+384000];ref=np.frombuffer(Path(c['y_i32le']).read_bytes(),dtype='<i4')[384:384+384000]
        need(np.array_equal(aligned,ref),'aligned equality');save_wav(a.out/f'after_threshold_{c["threshold"]}.wav',aligned)
        diff=aligned.astype(np.int64)-x.astype(np.int64);den=float(np.dot(x.astype(float),x.astype(float)));sse=float(np.dot(diff.astype(float),diff.astype(float)));nrmse=(sse/den)**.5*100 if den else (0.0 if not sse else None)
        metrics.append({'threshold':c['threshold'],'cpu_reference_nrmse_percent':nrmse,'fpga_nrmse_percent':nrmse,'full_y_mismatches':0,'sparse_spectral_bytes':c['packets']['sparse']['bytes'],'dense_baseline_spectral_bytes':2856952,'spectral_reduction_percent':100*(1-c['packets']['sparse']['bytes']/2856952),'shared_playback_gain':4,'different_aligned_samples':int(np.count_nonzero(diff))})
    report={'status':'PASS_EXACT_DOWNLOADED_CONTENT','cases':results,'epochs':6,'records':18006,'y_samples':2307072,'wire_bytes':sum(r['bytes'] for r in results),'feature_components':288096,'archive_sha256':a.archive_sha256,'package_sha256':filehash(a.package/'package.json'),'fixtures_sha256':filehash(a.fixtures),'validator_sha256':filehash(__file__),'decoder_sha256':filehash(DECODER),'comparison':metrics,'scope':'One continuous384000-sample mathematical epoch per threshold/mode with full tail. Physical provenance requires separate root-admitted programming/runtime/Ethernet receipts. PIO/file input is unpaced; no real-time, CPU-speedup or power claim.'}
    writejson(a.out/'report.json',report)
    rows=['# Downloaded eight-second stream comparison','','Exact content validated; board/Ethernet identity is established separately by the root physical provenance receipt.','','| THR2 | CPU reference NRMSE | FPGA NRMSE | Full-tail Y mismatches | Sparse spectral bytes | Spectral reduction vs dense0 |','|---:|---:|---:|---:|---:|---:|']
    for m in metrics:rows.append(f'| {m["threshold"]} | {m["cpu_reference_nrmse_percent"]:.6f}% | {m["fpga_nrmse_percent"]:.6f}% | 0 /384512 | {m["sparse_spectral_bytes"]:,} | {m["spectral_reduction_percent"]:.4f}% |')
    rows+=['','NRMSE uses reconstructed Y[384:384384] against the same384000 input samples, divided by input RMS. It is waveform error, not perceptual quality loss. CPU and FPGA refer to the same fixed-point algorithm, not timing results.','','All WAVs use identical gain4, signed12-to-PCM16 scale16,48kHz, no clipping and no independent normalization. TSP1 spectral sizes include headers/padding; they exclude Y debug returns, uploaded programs, archives and TCP/Ethernet overhead. TSP1 magnitudes alone do not reconstruct phase; WAVs use the actual downloaded IFFT/WOLA Y.','']
    (a.out/'README.md').write_text('\n'.join(rows),encoding='utf-8');print(json.dumps({k:v for k,v in report.items() if k not in ('cases','comparison')}))
if __name__=='__main__':main()
