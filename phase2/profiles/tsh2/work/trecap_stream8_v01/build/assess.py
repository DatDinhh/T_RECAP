"""Seal fitted HPS timing, pin, simulation and source evidence before assembly."""
from pathlib import Path
import argparse,hashlib,json,subprocess,sys
from build import verify,sha,save,require,HPS,WORK
def main():
    p=argparse.ArgumentParser();p.add_argument('--build',type=Path,required=True);p.add_argument('--verification',type=Path,required=True)
    p.add_argument('--core-verification',type=Path,default=WORK/'core/verification02/report.json');a=p.parse_args()
    out=a.build.resolve();report=out/'final_assessment.json';require(not report.exists(),'preserve prior assessment')
    m=verify(out)
    require(json.loads((out/'review_receipt.json').read_text())['status']=='PASS','timing reports not complete')
    timing=out/'timing_assessment.json';pins=out/'pin_assessment/report.json'
    subprocess.run([sys.executable,str(out/'review_scripts/analyze_timing.py'),'--build',str(out),'--reports',str(out/'timing_review'),'--out',str(timing)],check=True)
    subprocess.run([sys.executable,str(out/'review_scripts/review_image.py'),'--build',str(out),'--out',str(pins.parent)],check=True)
    t=json.loads(timing.read_text());p=json.loads(pins.read_text());v=json.loads(a.verification.read_text())
    require(t['status']=='PASS_TIMING_ONLY','timing gate failed')
    require(p['status']=='PASS_SOURCE_AND_PIN_AUDIT_PENDING_TIMING_AND_RUNTIME','pin/source gate failed')
    require(v['status']=='PASS','simulation gate failed')
    require(v['build_registration_sha256']==sha(out/'registration.json'),'simulation registration mismatch')
    c=json.loads(a.core_verification.read_text());require(c['status']=='PASS','independent core gate failed')
    for path,h in c['source_hashes'].items():require(sha(path)==h,'independent core source drift '+path)
    for name in ('trecap_pcm_stream_source.sv','trecap_pcm_stream_top.sv'):
        original=str((WORK/'core'/name).resolve())
        require(sha(out/'generated'/name)==c['source_hashes'][original],'core evidence not candidate-bound '+name)
    # Quartus emits HPS handoff during assembly. Bind expected bytes now;
    # assembly must check the actual generated files before its PASS receipt.
    before={x.relative_to(HPS/'hps_isw_handoff').as_posix():sha(x) for x in (HPS/'hps_isw_handoff').rglob('*') if x.is_file()}
    require(len(before)==15,'expected HPS handoff incomplete')
    evidence=[out/'registration.json',out/'source_manifest.json',out/'build_receipt.json',out/'map_review.json',timing,pins,a.verification.resolve(),a.core_verification.resolve(),Path(__file__).resolve()]
    evidence += [out/(s+'_receipt.json') for s in ('map','ddr_capture','fit','sta','review')]
    files={str(f):sha(f) for f in evidence}
    for path,h in v.get('evidence_sha256',{}).items():
        f=Path(path) if Path(path).is_absolute() else a.verification.resolve().parent/path
        require(sha(f)==h,'adapter simulation evidence drift '+str(f));files[str(f)]=h
    files.update({str(p):sha(p) for p in a.core_verification.resolve().parent.glob('*.log')})
    # Quartus assembly legitimately updates flow bookkeeping. Bind actual fit,
    # pin and timing evidence, not the mutable flow summary.
    for row in json.loads((out/'build_receipt.json').read_text())['artifacts'].values():
        files[str(out/row['path'])]=row['sha256']
    files.update({str(f):sha(f) for f in (out/'timing_review').glob('*') if f.is_file()})
    assessment=dict(status='PASS_PREASSEMBLY_HPS50',source_id=m['source_id'],registration_sha256=sha(out/'registration.json'),
      registered_sources_unchanged=True,device='5CSEMA5F31C6',clock_hz=50000000,
      evidence_sha256=files,expected_hps_handoff_sha256=before,hps_handoff_gate='Actual handoff generated and checked during assembly before SOF admission',
      source_sha256={r['path']:r['sha256'] for r in m['files']},
      pins=p['pin_comparison'],clocks=t['clocks'],fabric_and_afi_paths=[r for r in t['independent_path_records'] if r['clock']=='CLOCK_50' or r['clock'].endswith('|afi_clk_write_clk')],
      calibrated_ddr=t['vendor_DDR_calibrated_records'],constraint_findings=t['constraints'],
      scope='One continuous384000-sample host-fed epoch with bounded FIFOs, original numerical core and TSP1 export; unpaced file correctness test, no live throughput claim. No hardware admission by this artifact.')
    save(report,assessment);print(json.dumps(dict(status=assessment['status'],path=str(report),sha256=sha(report))))
if __name__=='__main__':main()
