"""Bounded source-bound ModelSim runner for the root-owned Avalon testbench."""
from pathlib import Path
import argparse,json,re,shutil,subprocess,time
from build import verify,sha,save,require
SIM=Path('D:/Quartus20.1.1/QuartusFPGA/modelsim_ase/win32aloem')
def main():
    ap=argparse.ArgumentParser();ap.add_argument('--build',type=Path,required=True);ap.add_argument('--out',type=Path,required=True)
    ap.add_argument('--testbench',type=Path,required=True);ap.add_argument('--top',default='adapter_tb')
    ap.add_argument('--pass-marker',required=True);ap.add_argument('--plusarg',action='append',default=[]);ap.add_argument('--timeout',type=int,default=300)
    a=ap.parse_args();b=a.build.resolve();out=a.out.resolve();m=verify(b);require(not out.exists(),'fresh simulation output required')
    require(1<=a.timeout<=1800,'bounded simulation timeout');require(re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*',a.top),'invalid testbench module')
    out.mkdir(parents=True)
    for d in ('source','generated','sources','artifacts'):shutil.copytree(b/d,out/d)
    shutil.copyfile(a.testbench,out/'adapter_tb.sv')
    (out/'source_id.svh').write_text("localparam [255:0] TEST_SOURCE_ID=256'h"+m['source_id']+';\n')
    sources=[]
    for line in (b/'audio_hps.qsf').read_text().splitlines():
        prefix='set_global_assignment -name SYSTEMVERILOG_FILE '
        if line.startswith(prefix):
            rel=line[len(prefix):]
            if rel not in ('sources/platform_designer_wrapper.sv','sources/trecap_hps_top.sv'):sources.append(rel)
    sources+=['adapter_tb.sv']
    candidate={r['path']:r['sha256'] for r in m['files']}
    bound={rel:sha(out/rel) for rel in sources+['source_id.svh']}
    for rel in sources[:-1]:require(rel in candidate and candidate[rel]==bound[rel],'simulation source identity '+rel)
    registration=dict(build_registration_sha256=sha(b/'registration.json'),source_id=m['source_id'],source_hashes=bound,
      testbench_original=str(a.testbench.resolve()),runner_sha256=sha(__file__),pass_marker=a.pass_marker,timeout_s=a.timeout,
      scope='Root testbench assertions against actual application/core RTL. Generated HPS/vendor bridge not simulated.')
    save(out/'registration.json',registration);commands=[]
    def invoke(stage,argv,timeout):
        argv=[str(x).replace('\\','/') for x in argv];r=dict(stage=stage,argv=argv,tool_sha256=sha(argv[0]),cwd=str(out));commands.append(r);start=time.monotonic()
        with (out/(stage+'.log')).open('xb') as f:
            p=subprocess.Popen(argv,cwd=out,stdout=f,stderr=subprocess.STDOUT);r['pid']=p.pid;save(out/'commands.json',commands)
            try:r['returncode']=p.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                subprocess.run(['taskkill','/PID',str(p.pid),'/T','/F'],capture_output=True,timeout=15);p.wait(timeout=15);raise RuntimeError(stage+' timeout')
        r.update(elapsed_s=time.monotonic()-start,log_sha256=sha(out/(stage+'.log')));save(out/'commands.json',commands)
        require(r['returncode']==0,stage+' failed')
    result=dict(status='RUNNING',**registration)
    try:
        invoke('vlib',[SIM/'vlib.exe','work'],30);invoke('vmap',[SIM/'vmap.exe','-c'],30)
        args=[SIM/'vlog.exe','-sv','-warning','2892','-work','work','+define+SYNTHESIS','+incdir+.',
          '+incdir+source/rtl/include','+incdir+source/rtl/include/generated','+incdir+source/rtl/interfaces']+sources
        invoke('compile',args,180);print('COMPILE PASS',flush=True)
        args=[SIM/'vsim.exe','-c','-voptargs=+acc','work.'+a.top,'+OUT='+str(out)]+a.plusarg+['-do','onerror {quit -code 1}; onbreak {quit -code 1}; run -all; quit -code 0']
        invoke('simulate',args,a.timeout)
        log=(out/'simulate.log').read_text(errors='strict')
        require(a.pass_marker in log,'expected testbench completion absent')
        require(not re.search(r'\*\* (?:Fatal|Error):',log),'simulation error diagnostic')
        for rel,h in bound.items():require(sha(out/rel)==h,'simulation source changed '+rel)
        verify(b);require(sha(b/'registration.json')==registration['build_registration_sha256'],'build registration changed')
        result['status']='PASS'
    except Exception as e:result.update(status='FAIL',error=str(e))
    result['evidence_sha256']={str(p):sha(p) for p in out.glob('*') if p.is_file() and p.name not in ('report.json',)}
    save(out/'report.json',result);print(json.dumps(dict(status=result['status'],report=str(out/'report.json'))),flush=True)
    raise SystemExit(0 if result['status']=='PASS' else 1)
if __name__=='__main__':main()
