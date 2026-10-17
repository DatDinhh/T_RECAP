from pathlib import Path
import ctypes as C,hashlib,json,statistics
ROOT=Path(__file__).resolve().parents[3];OUT=ROOT/'outputs/trecap_laptop_fpga_v01/cpu_build01';FIX=ROOT/'outputs/trecap_stream8_v01/fixtures02'
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
rows=[json.loads(s) for s in (OUT/'campaign.jsonl').read_text(encoding='utf-8-sig').splitlines()];assert rows[-1]['status']=='PASS_165_EXACT_NATIVE_LAPTOP_EPOCHS';assert not (OUT/'campaign.stderr').read_text().strip();trials=[r for r in rows if r['kind']=='trial'];assert len(trials)==165
lib=C.CDLL(str(OUT/'trecap.dll'));lib.trecap_create.argtypes=[C.c_char_p,C.c_char_p];lib.trecap_create.restype=C.c_void_p
for name in ('trecap_y','trecap_tsp1'):getattr(lib,name).argtypes=[C.c_void_p];getattr(lib,name).restype=C.c_void_p
for name in ('trecap_y_count','trecap_tsp1_bytes'):getattr(lib,name).argtypes=[C.c_void_p];getattr(lib,name).restype=C.c_uint64
lib.trecap_run.argtypes=[C.c_void_p,C.c_uint64];lib.trecap_run.restype=C.c_int;lib.trecap_destroy.argtypes=[C.c_void_p]
ctx=lib.trecap_create(str(FIX/'coefficients').encode(),str(FIX/'input.i32le').encode());assert ctx
cases=json.loads((FIX/'cases.json').read_text())['cases'];result=[];gold={}
try:
 for case in cases:
  t=case['threshold'];y=Path(case['y_i32le']);wire=Path(case['packets']['sparse']['path']);assert sha(y)==case['y_sha256'] and sha(wire)==case['packets']['sparse']['sha256'];gold[str(y)]=sha(y);gold[str(wire)]=sha(wire)
  assert lib.trecap_run(ctx,t)==0 and lib.trecap_y_count(ctx)==384512 and lib.trecap_tsp1_bytes(ctx)==wire.stat().st_size
  assert C.string_at(lib.trecap_y(ctx),384512*4)==y.read_bytes();assert C.string_at(lib.trecap_tsp1(ctx),wire.stat().st_size)==wire.read_bytes()
  records=[r for r in trials if r['threshold']==t];assert {r['trial'] for r in records}==set(range(-3,30))
  for r in records:
   assert r['status']=='PASS_EXACT' and r['y_samples']==384512 and r['frames']==3001 and r['spectral_bytes']==wire.stat().st_size
   for k in ('wall','process_cpu','thread_cpu'):assert r[k+'_ns']==r[k+'_end_ns']-r[k+'_start_ns'] and r[k+'_ns']>=0
  measured=[r for r in records if r['trial']>=0];metrics={}
  for k in ('wall','process_cpu','thread_cpu'):
   vals=[r[k+'_ns']/1e6 for r in measured];q=statistics.quantiles(vals,n=4,method='inclusive');metrics[k+'_ms']={'median':statistics.median(vals),'q25':q[0],'q75':q[2],'min':min(vals),'max':max(vals)}
  result.append({'threshold':t,'spectral_bytes':wire.stat().st_size,'dll_full_outputs_exact':True,'metrics':metrics})
finally:lib.trecap_destroy(ctx)
sources=[*Path(__file__).parent.glob('*.cpp'),*Path(__file__).parent.glob('*.hpp'),Path(__file__),Path(__file__).parent/'build.ps1',ROOT/'work/trecap_cpu_fpga_bench_v01/cpu02/main.cpp',ROOT/'work/trecap_cpu_fpga_bench_v01/cpu02/kernel.hpp',ROOT/'outputs/trecap_cpu_fpga_bench_v01/cpu02_build01/qualification.json']
for p in [FIX/'input.i32le',*(FIX/'coefficients').glob('*.memh')]:gold[str(p)]=sha(p)
report={'status':'PASS_NATIVE_WINDOWS_LAPTOP_CPU','environment':rows[0],'cases':result,'measured_epochs':150,'warmup_epochs':15,'dll_qualification_epochs':5,'source_sha256':{str(p):sha(p) for p in sources},'gold_sha256':gold,'binary_sha256':{name:sha(OUT/name) for name in ('campaign.exe','trecap.dll')},'artifacts_sha256':{p.name:sha(p) for p in OUT.iterdir() if p.is_file()},'scope':'Actual laptop native Windows x64 MSVC /O2, one pinned thread. Resident input/output CPU kernel; no file IO or initialization in timer. These standalone trials are not paired with a network service. Windows GetThreadTimes/GetProcessTimes may have coarse accounting resolution; QPC elapsed is primary. Exact CPU02 kernel reused; prior UBSan/extreme-frame qualifications bound above, no new algorithm.'}
assert not (OUT/'report.json').exists();(OUT/'report.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps({'status':report['status'],'environment':report['environment'],'cases':result,'dll_sha256':report['binary_sha256']['trecap.dll']}))
