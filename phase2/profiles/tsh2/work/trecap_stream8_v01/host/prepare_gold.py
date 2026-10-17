"""Create PC-only full-stream references; no hardware or network access."""
from pathlib import Path
import argparse,csv,hashlib,importlib.util,json,shutil,struct,subprocess,sys,time
sys.dont_write_bytecode=True
ROOT=Path(__file__).resolve().parents[3]
LISTEN=ROOT/'outputs/trecap_audio_listen_v01/sweep02'
REF=Path('D:/SeniorCapstoneProject/build/github-publish-20260914/phase2/build/host/reference_model/Release/phase2_golden_model.exe')
ORACLE=ROOT/'work/trecap_sparse_consumer_v01/audit_packets.py'
THRESHOLDS=(0,100000000,1000000000,10000000000,100000000000)
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def save(p,d):Path(p).write_text(json.dumps(d,indent=2)+'\n',encoding='utf-8')
def module(p):
    s=importlib.util.spec_from_file_location('stream_packet_oracle',p);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
def pcm(p):
    values=[int(v,16) for v in Path(p).read_text().split()]
    assert all(0<=v<4096 for v in values)
    return [v-4096 if v&2048 else v for v in values]
def main():
    p=argparse.ArgumentParser();p.add_argument('--out',type=Path,required=True);a=p.parse_args()
    assert not a.out.exists();assert sha(REF)=='b14d9b5c727897319ba5c1288636d5dedb1d1611169e8076832157ee763e3964'
    for n,h in json.loads((LISTEN/'manifest.json').read_text()).items():assert sha(LISTEN/n)==h,n
    a.out.mkdir(parents=True);shutil.copytree(LISTEN/'coefficients',a.out/'coefficients');shutil.copyfile(LISTEN/'input.memh',a.out/'input.memh')
    x=pcm(a.out/'input.memh');assert len(x)==384000
    (a.out/'input.i32le').write_bytes(struct.pack('<384000i',*x));oracle=module(ORACLE);cases=[]
    for threshold in THRESHOLDS:
        name=f'flute8s_thr{threshold}';vector=a.out/(name+'_vector');vector.mkdir()
        shutil.copyfile(a.out/'input.memh',vector/'x_in.memh');cfg=json.loads((LISTEN/f'reference_thr{threshold}/config.json').read_text())
        cfg['artifact_rows']['bin_stats_data_rows']=3001*129;save(vector/'config.json',cfg);target=a.out/name
        cmd=[str(REF),'--vector-dir',str(vector.resolve()),'--coeff-dir',str((a.out/'coefficients').resolve()),'--output-dir',str(target.resolve()),'--thr2',str(threshold),'--collect-bin-stats']
        start=time.monotonic();r=subprocess.run(cmd,capture_output=True,timeout=120)
        save(a.out/(name+'_execution.json'),{'argv':cmd,'returncode':r.returncode,'stdout':r.stdout.decode(errors='replace'),'stderr':r.stderr.decode(errors='replace'),'elapsed_seconds':time.monotonic()-start})
        assert r.returncode==0,r.stderr.decode(errors='replace')
        for f in ('y_out.memh','frame_stats.csv','metrics.json'):assert sha(target/f)==sha(LISTEN/f'reference_thr{threshold}'/f),f
        y=pcm(target/'y_out.memh');assert len(y)==384512;(target/'y.i32le').write_bytes(struct.pack('<384512i',*y))
        packets={False:bytearray(),True:bytearray()};features=[]
        with (target/'bin_stats.csv').open(newline='') as f:
            reader=csv.DictReader(f)
            for frame in range(3001):
                vals=[];keep=[];bands=[0]*16
                for k in range(129):
                    row={n:int(v) for n,v in next(reader).items()};assert row['frame_idx']==frame and row['bin_idx']==k
                    mag=row['real']**2+row['imag']**2;kept=k==0 or mag>=threshold
                    assert row['mag2']==mag and row['mask']==int(not kept) and row['eligible']==int(k!=0)
                    vals.append(mag);keep.append(kept)
                    if kept:bands[16*k//129]+=mag*(1 if k in (0,128) else 2)
                features.append(bands)
                for sparse in packets:packets[sparse]+=oracle.record(frame,threshold,vals,keep,sparse)
            assert next(reader,None) is None
        with (target/'expected_features.csv').open('w',newline='') as f:
            w=csv.writer(f,lineterminator='\n');w.writerow(['frame_idx']+[f'band{k}' for k in range(16)]);w.writerows([[i,*v] for i,v in enumerate(features)])
        info={}
        for sparse,data in packets.items():
            mode='sparse' if sparse else 'dense';path=target/(mode+'.tsp1');path.write_bytes(data);info[mode]={'path':str(path.resolve()),'bytes':len(data),'sha256':sha(path)}
        cases.append({'case_id':name,'threshold':threshold,'y_i32le':str((target/'y.i32le').resolve()),'y_sha256':sha(target/'y.i32le'),'bin_stats':str((target/'bin_stats.csv').resolve()),'expected_features':str((target/'expected_features.csv').resolve()),'packets':info})
        print(name+' PASS',flush=True)
    report={'status':'PASS','geometry':{'Ns':384000,'Ny':384512,'frames':3001,'sample_rate':48000,'delay':384},'input_i32le':str((a.out/'input.i32le').resolve()),'input_sha256':sha(a.out/'input.i32le'),'input_memh_sha256':sha(a.out/'input.memh'),'cases':cases,'reference_sha256':sha(REF),'oracle_sha256':sha(ORACLE),'driver_sha256':sha(__file__),'old_manifest_sha256':sha(LISTEN/'manifest.json'),'hardware_used':False}
    save(a.out/'cases.json',report);save(a.out/'manifest.json',{f.relative_to(a.out).as_posix():sha(f) for f in sorted(a.out.rglob('*')) if f.is_file()})
if __name__=='__main__':main()
