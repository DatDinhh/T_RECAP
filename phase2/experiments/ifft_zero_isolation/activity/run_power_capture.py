"""Collect separate, checked RTL VCDs for the optional IFFT datapath."""
import argparse,hashlib,importlib.util,json,re,subprocess,sys
from pathlib import Path

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--repo',required=True,type=Path)
    p.add_argument('--simulator-dir',required=True,type=Path)
    p.add_argument('--run-dir',required=True,type=Path)
    p.add_argument('--testbench',required=True,type=Path)
    a=p.parse_args()
    repo,run,sim,tb=[x.resolve() for x in (a.repo,a.run_dir,a.simulator_dir,a.testbench)]
    if run.exists(): p.error('Fresh run directory required')
    run.mkdir(parents=True)
    helper=repo/'scripts/measurement/run_measurement_sim.py'
    spec=importlib.util.spec_from_file_location('measurement_sim_helpers',helper)
    module=importlib.util.module_from_spec(spec)
    sys.dont_write_bytecode=True
    spec.loader.exec_module(module)
    args,sources,inc=module.resolve_filelist(repo)
    args=[s for s in args if not s.endswith('/sim/verification/measurement_engine_tb.sv')]
    args.append(tb.as_posix())
    ini=run/'modelsim.ini'
    commands=[]
    def invoke(name,argv,cwd):
        argv=[x.as_posix() if isinstance(x,Path) else str(x) for x in argv]
        result=subprocess.run(argv,cwd=cwd,capture_output=True,text=True,timeout=600)
        (run/(name+'.stdout.log')).write_text(result.stdout,encoding='utf-8')
        (run/(name+'.stderr.log')).write_text(result.stderr,encoding='utf-8')
        commands.append({'name':name,'argv':[str(x) for x in argv],'cwd':str(cwd),'exit_code':result.returncode})
        (run/'commands.json').write_text(json.dumps(commands,indent=2)+'\n',encoding='utf-8')
        if result.returncode or re.search(r'(?m)^#?\s*\*\* (?:Error|Fatal)',result.stdout+result.stderr):
            raise RuntimeError(name+' failed; see retained logs')
        if name in ('baseline','isolated'):
            assert result.stdout.count('POWER_CAPTURE_PASS mode=')==1,result.stdout[-1500:]
            assert 'POWER_CAPTURE_FAIL' not in result.stdout
        print(name+' passed',flush=True)
    invoke('vlib',[sim/'vlib.exe',run/'work'],run)
    invoke('vmap_ini',[sim/'vmap.exe','-c'],run)
    invoke('vmap',[sim/'vmap.exe','-modelsimini',ini,'work',run/'work'],run)
    invoke('compile',[sim/'vlog.exe','-modelsimini',ini,'-work','work','-sv','-warning','2892',*args],repo)
    dofile=run/'run.do'
    dofile.write_text('onerror {quit -code 1}\nrun -all\nquit -code 0\n',encoding='utf-8')
    for name,mode in [('baseline',2),('isolated',3)]:
        invoke(name,[sim/'vsim.exe','-c','-modelsimini',ini,'-onfinish','stop','-voptargs=+acc',
            '-l',(run/(name+'.transcript.log')).as_posix(),'work.power_capture_tb',
            f'+MODE={mode}','+VCD='+(run/(name+'.vcd')).as_posix(),'-do',dofile.as_posix()],repo)
    receipt={'status':'PASS','scope':'RTL VCDs, two checked finite epochs each; not physical power',
             'inputs':{str(path):hashlib.sha256(path.read_bytes()).hexdigest() for path in [*sources,tb]},
             'vcd':{name:{'sha256':hashlib.sha256((run/(name+'.vcd')).read_bytes()).hexdigest(),
                          'bytes':(run/(name+'.vcd')).stat().st_size} for name in ('baseline','isolated')}}
    (run/'manifest.json').write_text(json.dumps(receipt,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'status':'PASS','run':str(run)}))

if __name__=='__main__':main()
