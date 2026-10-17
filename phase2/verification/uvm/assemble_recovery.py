#!/usr/bin/env python3
"""Audit explicitly selected receipts after one preserved simulator startup crash.

This tool never launches or retries a simulator. It rejects an unexecuted seed,
an altered source/build input, a numerical failure, or a missing negative test.
"""
import argparse,json,re,shutil
from pathlib import Path
import run as r
ROOT=Path(__file__).resolve().parent
def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--manifest',type=Path,required=True);ap.add_argument('--source-root',type=Path,required=True);ap.add_argument('--uvm-home',type=Path,required=True);ap.add_argument('--selected',action='append',required=True,help='SEED=completed capture directory');ap.add_argument('--negative',type=Path,required=True);ap.add_argument('--failed-startup',type=Path,required=True);ap.add_argument('--out',type=Path,required=True);a=ap.parse_args()
    a.manifest=a.manifest.resolve();manifest=json.loads(a.manifest.read_text());source=a.source_root.resolve();out=a.out.resolve();r.require(not out.exists(),'New output directory required')
    chosen={int(x.split('=',1)[0]):Path(x.split('=',1)[1]).resolve() for x in a.selected}
    r.require(len(chosen)==len(a.selected) and set(chosen)==set(manifest['seeds'])=={1,7,20261017},'Exact selected three-seed matrix required')
    admission,cases=r.verify_source(source);r.require(r.sha(source/'admission.json')==manifest['source_admission_sha256'],'Sibling admission changed')
    for name,h in manifest['source_files'].items():r.require(r.sha(source/name)==h,'Source changed: '+name)
    for name,h in manifest['uvm_environment_files'].items():r.require(r.sha(ROOT/name)==h,'UVM environment changed: '+name)
    for name,h in manifest['uvm_library_files'].items():r.require(r.sha(a.uvm_home/name)==h,'Official UVM library changed: '+name)
    compilations={}
    def verify_compilation(build):
        key=str(build.resolve())
        if key in compilations:return compilations[key]['id']
        owner=build.parent;bound=json.loads((owner/'run_manifest.json').read_text());rec=json.loads((owner/'compile.command.json').read_text())
        for field in ('source_id','source_admission_sha256','source_files','compiled_filelist','uvm_environment_files','uvm_library_files','defines','DUT_SYNTHESIS_defined','tools'):
            r.require(bound[field]==manifest[field],'Per-build source/library/configuration manifest mismatch: '+field)
        r.require(Path(rec['cwd']).resolve()==build.resolve() and rec['exit_code']==0 and not rec.get('timed_out'),'Successful per-build compilation required')
        r.require(r.sha(owner/'compile.log')==rec['log_sha256'] and r.sha(rec['argv'][0])==rec['tool_sha256']==bound['tools']['vlog']['sha256'],'Per-build compiler/log identity')
        r.require(rec['argv'][-2:]==['-f','source_files.f'] and '+define+UVM_NO_DPI' in rec['argv'] and str((a.uvm_home/'src/uvm_pkg.sv').resolve()) in rec['argv'],'Per-build official UVM compile command')
        r.require('Errors: 0,' in (owner/'compile.log').read_text(errors='replace'),'Compiler completion receipt missing')
        identity='build_%02d'%(len(compilations)+1);compilations[key]={'id':identity,'owner':owner,'build':build,'manifest_sha256':r.sha(owner/'run_manifest.json'),'compile_command_sha256':r.sha(owner/'compile.command.json'),'compile_log_sha256':r.sha(owner/'compile.log')}
        return identity
    def read_receipt(folder,seed,negative=False):
        rec=json.loads((folder/'simulate.command.json').read_text());log=(folder/'simulate.log').read_text(errors='replace');argv=rec['argv'];build=Path(rec['cwd'])
        compilation_id=verify_compilation(build)
        r.require(r.sha(folder/'simulate.log')==rec['log_sha256'],'Transcript changed')
        r.require(not rec.get('timed_out') and r.sha(argv[0])==rec['tool_sha256'],'Tool identity/deadline failed')
        r.require(f'+SEED={seed}' in argv and 'work.tsh2_top' in argv and '+CASES=cases.txt' in argv and argv[-2:]==['-do','run.do'],'Unexpected simulation command')
        outputs=[x[5:] for x in argv if x.startswith('+OUT=')];r.require(len(outputs)==1 and (build/outputs[0]).resolve()==folder,'Output directory binding')
        r.require(('+INJECT_BAD_Y' in argv)==negative,'Negative-control command binding')
        for name,h in manifest['source_files'].items():r.require(r.sha(build/name)==h,'Compiled input copy changed: '+name)
        for name,h in manifest['uvm_environment_files'].items():
            if name!='run.py':r.require(r.sha(build/name)==h,'Compiled harness copy changed: '+name)
        r.require((build/'source_files.f').read_text().splitlines()==manifest['compiled_filelist'],'Compiled file list changed')
        if negative:
            r.require(rec['exit_code']!=0 and re.search(r'UVM_FATAL .*\[Y_GOLD_MISMATCH\]',log) and '[TSH2_UVM_COMPLETE]' not in log,'Expected UVM numerical rejection missing')
            r.require(re.search(r'UVM_FATAL\s*:\s*1',log) and re.search(r'UVM_ERROR\s*:\s*0',log),'Unexpected negative severity counts')
        else:
            r.require(rec['exit_code']==0 and 'UVM_EXIT_STATE=1' in log and f'[TSH2_UVM_COMPLETE] seed={seed} completed=4 reset_aborts=1' in log,'Nominal completion gate failed')
            r.require(re.search(r'UVM_ERROR\s*:\s*0',log) and re.search(r'UVM_FATAL\s*:\s*0',log) and not re.search(r'\*\* (?:Error|Fatal):',log),'Unexpected nominal diagnostics')
        return rec,compilation_id
    failed=a.failed_startup.resolve();failure=json.loads((failed/'simulate.command.json').read_text());flog=(failed/'simulate.log').read_text(errors='replace')
    r.require(failure['exit_code']==211 and not failure.get('timed_out') and 'SIGSEGV' in flog and '[RNTST]' not in flog and 'Loading work.uvm_pkg' not in flog,'Only the observed pre-UVM startup crash may be recovered')
    r.require('+SEED=7' in failure['argv'] and r.sha(failure['argv'][0])==failure['tool_sha256'],'Failed startup seed/tool binding')
    r.require(r.sha(failed/'simulate.log')==failure['log_sha256'],'Failed startup transcript changed')
    results=[];reports={};tests=[]
    for seed in manifest['seeds']:
        folder=chosen[seed];rec,compilation_id=read_receipt(folder,seed);epochs=r.reconcile(folder,source,cases,seed);results.extend(epochs)
        reports[seed]={'status':'PASS','seed':seed,'epochs':epochs,'command':rec,'compilation_id':compilation_id,'trace_sha256':r.sha(folder/'observed.csv'),'coverage_sha256':r.sha(folder/'coverage.csv'),'timing_sha256':r.sha(folder/'timing.csv')}
        tests.append({'name':f'seed_{seed}_four_epochs_reset_recovery','status':'PASS','detail':'Official UVM execution and independent exact trace reconciliation'})
    neg=a.negative.resolve();negative,negative_compilation=read_receipt(neg,1,True);tests.extend([{'name':'negative_wrong_y','status':'PASS','detail':'Executed UVM_FATAL Y_GOLD_MISMATCH, one fatal, zero errors and nonzero exit'},{'name':'postrun_source_binding','status':'PASS','detail':'Original sources, each compiled copy, per-build successful compiler receipts, runner, harness, official library and simulator executable rechecked'}])
    complete=[x['observed'] for x in results if x['observed']['status']=='COMPLETE'];r.require(len(complete)==12 and len(results)==15,'Exact completed/aborted campaign cardinality')
    totals={k:sum(x[k] for x in complete) for k in ('inputs','sources','y','taps','bytes','final_y_hold','masked','kept','ineligible')}
    out.mkdir(parents=True)
    # The aggregate is a new artifact. Original FAILED summaries/logs stay intact.
    lineage=[]
    def copy(src,dst):
        dst.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(src,dst);lineage.append({'original':src.relative_to(ROOT).as_posix(),'aggregate':dst.relative_to(out).as_posix(),'sha256':r.sha(src)})
    copy(a.manifest.resolve(),out/'run_manifest.json')
    for name in ('version','vlib','vmap','compile'):
        for suffix in ('.log','.command.json'):copy(a.manifest.parent/(name+suffix),out/(name+suffix))
    for seed,folder in chosen.items():
        target=out/f'seed_{seed}'
        for name in ('simulate.log','simulate.command.json','coverage.csv','observed.csv','timing.csv'):copy(folder/name,target/name)
        r.save(target/'report.json',reports[seed])
    for name in ('simulate.log','simulate.command.json'):copy(neg/name,out/'negative_wrong_y'/name)
    r.save(out/'negative_wrong_y/report.json',{'status':'PASS','expected_failure':'Y_GOLD_MISMATCH','command':negative,'compilation_id':negative_compilation})
    for build in compilations.values():
        for name in ('run_manifest.json','compile.command.json','compile.log'):copy(build['owner']/name,out/'compilations'/build['id']/name)
    for name in ('simulate.log','simulate.command.json'):copy(failed/name,out/'preserved_startup_failure'/name)
    copy(a.manifest.parent/'summary.json',out/'preserved_startup_failure/original_failed_run_summary.json')
    recovery={'schema':'tsh2-explicit-startup-recovery-v1','scope':'Recovered selected campaign, not an uninterrupted successful default runner invocation','failed_startup_count':1,'explicit_retry_count':1,'failed_startup_seed':7,'failed_startup_exit_code':211,'failure_classification':'Observed simulator startup SIGSEGV before UVM/DUT load; root cause unknown','assembler_sha256':r.sha(__file__),'source_manifest_sha256':r.sha(a.manifest),'compilations':[{k:v for k,v in b.items() if k not in ('owner','build')} for b in compilations.values()],'selection_and_copy_lineage':lineage,'checks':'All required positive epochs, expected numerical negative control, exact traces, per-build successful compile receipts and original/compiled source hashes recomputed; no automatic retry'}
    r.save(out/'recovery_manifest.json',recovery)
    r.save(out/'summary.json',{'status':'PASS','execution_mode':'explicit_recovered_campaign','uninterrupted_runner_pass':False,'preserved_startup_failure':'recovery_manifest.json','seeds':manifest['seeds'],'completed_epochs':12,'busy_reset_aborts':3,'immediate_recovery_epochs_included_in_completed':3,'negative_control_executed':True,'completed_epoch_totals':totals,'tests':tests,'epochs':results,'manifest_sha256':r.sha(a.manifest),'recovery_manifest_sha256':r.sha(out/'recovery_manifest.json')})
    r.junit(out/'junit.xml',tests);print(json.dumps({'status':'PASS','out':str(out),'totals':totals},indent=2))
if __name__=='__main__':main()
