"""Assemble only a qualified source-bound HPS image. Never programs hardware."""
from pathlib import Path
import argparse,ctypes,json,os,subprocess,time
from build import verify,sha,save,require,QUARTUS
def main():
    p=argparse.ArgumentParser();p.add_argument('--build',type=Path,required=True);a=p.parse_args();out=a.build.resolve()
    target=out/'assembly_receipt.json';require(not target.exists(),'preserve previous assembly receipt')
    m=verify(out);gate=out/'final_assessment.json';g=json.loads(gate.read_text())
    require(g['status']=='PASS_PREASSEMBLY_HPS50','assessment gate')
    require(g['registration_sha256']==sha(out/'registration.json'),'registration drift')
    for path,h in g['evidence_sha256'].items():require(sha(path)==h,'evidence drift '+path)
    drive=next((c+':' for c in 'QZYXWUTSR' if not ctypes.windll.kernel32.GetLogicalDrives()&(1<<(ord(c)-65))),None)
    require(drive is not None,'no short alias')
    argv=[str(QUARTUS/'quartus_asm.exe'),'--read_settings_files=on','--write_settings_files=off','audio_hps']
    r=dict(status='RUNNING',argv=argv,tool_sha256=sha(argv[0]),registration_sha256=sha(out/'registration.json'),
      admission_evidence_sha256=sha(gate),assembler_sha256=sha(__file__),timeout_s=600)
    owned=False;start=time.monotonic()
    try:
        subprocess.run(['subst',drive,str(out)],check=True,capture_output=True,timeout=15);owned=True
        env=os.environ.copy();env.update(QUARTUS_ROOTDIR=str(QUARTUS.parent),QUARTUS_ROOTDIR_OVERRIDE=str(QUARTUS.parent),TEMP=str(out/'tmp'),TMP=str(out/'tmp'))
        env['PATH']=str(QUARTUS)+os.pathsep+env.get('PATH','')
        with (out/'assembly.log').open('xb') as f:
            proc=subprocess.Popen(argv,cwd=drive+'/',env=env,stdout=f,stderr=subprocess.STDOUT);r['pid']=proc.pid;save(target,r)
            try:r['returncode']=proc.wait(timeout=600)
            except subprocess.TimeoutExpired:
                subprocess.run(['taskkill','/PID',str(proc.pid),'/T','/F'],capture_output=True,timeout=20);proc.wait(timeout=20);raise RuntimeError('assembly timeout')
        require(r['returncode']==0,'assembly failed');verify(out)
        for path,h in g['evidence_sha256'].items():require(sha(path)==h,'assembly changed evidence '+path)
        handoff={p.relative_to(out/'hps_isw_handoff').as_posix():sha(p) for p in (out/'hps_isw_handoff').rglob('*') if p.is_file()}
        require(handoff==g['expected_hps_handoff_sha256'],'assembled HPS handoff differs from frozen50MHz platform')
        sof=out/'output_files/audio_hps.sof';require(sof.is_file(),'SOF missing')
        r.update(status='PASS_SOF_ASSEMBLED_NOT_PROGRAMMED',registered_sources_unchanged=True,sof_path=str(sof),sof_sha256=sha(sof),hps_handoff_sha256=handoff,hps_handoff_matches_parent=True)
    except Exception as e:r.update(status='FAIL',error=str(e))
    finally:
        if owned:r['alias_released']=subprocess.run(['subst',drive,'/D'],capture_output=True,timeout=15).returncode==0
    r['elapsed_s']=time.monotonic()-start
    if (out/'assembly.log').exists():r['log_sha256']=sha(out/'assembly.log')
    save(target,r);print(json.dumps(r));raise SystemExit(0 if r['status']=='PASS_SOF_ASSEMBLED_NOT_PROGRAMMED' else 1)
if __name__=='__main__':main()
