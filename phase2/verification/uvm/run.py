#!/usr/bin/env python3
"""Execute genuine UVM 1.2 against the unchanged sibling TSH2 package.

Python 3.10+ standard library. No board, network, or Git operations.
"""
from __future__ import annotations
import argparse,csv,datetime,hashlib,json,os,re,shutil,signal,subprocess,sys,time
from pathlib import Path
import xml.etree.ElementTree as ET
ROOT=Path(__file__).resolve().parent
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def save(p,obj):Path(p).write_text(json.dumps(obj,indent=2)+'\n',encoding='utf-8')
def require(ok,msg):
    if not ok:raise RuntimeError(msg)
def csv_rows(p):
    with Path(p).open(newline='',encoding='utf-8') as f:return list(csv.DictReader(f))
def mem(p):return [int(v,16) for v in Path(p).read_text().split()]
def signed12(v):return v-4096 if v>=2048 else v
def command(argv,cwd,log,timeout):
    rec={'argv':list(map(str,argv)),'cwd':str(cwd),'timeout_seconds':timeout,'tool_sha256':sha(argv[0]),'started_utc':datetime.datetime.now(datetime.timezone.utc).isoformat()};start=time.monotonic()
    with Path(log).open('wb') as f:
        p=subprocess.Popen(rec['argv'],cwd=cwd,stdout=f,stderr=subprocess.STDOUT,start_new_session=os.name!='nt');rec['pid']=p.pid
        try:rec['exit_code']=p.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            rec['timed_out']=True
            try:
                if os.name=='nt':
                    cleanup=subprocess.run(['taskkill','/PID',str(p.pid),'/T','/F'],capture_output=True,text=True,timeout=20)
                    rec['cleanup']={'exit_code':cleanup.returncode,'stdout':cleanup.stdout,'stderr':cleanup.stderr}
                else:os.killpg(p.pid,signal.SIGKILL)
                if p.poll() is None:p.kill()
                rec['exit_code']=p.wait(timeout=10)
            except (OSError,subprocess.TimeoutExpired) as e:rec['cleanup_error']=str(e);rec['exit_code']=p.poll()
    rec['elapsed_seconds']=round(time.monotonic()-start,3);rec['log_sha256']=sha(log);save(Path(log).with_suffix('.command.json'),rec)
    return rec,Path(log).read_text(errors='replace')
def verify_source(source):
    admission=json.loads((source/'admission.json').read_text())
    for row in admission['admitted_files']:require(sha(source/row['path'])==row['sha256'],'Source admission mismatch: '+row['path'])
    dut={r['path'] for r in admission['admitted_files'] if r['kind']=='unchanged_registered_DUT'}
    require(len(dut)==26,'Expected 26 unchanged DUT sources')
    filelist=(source/'source_files.f').read_text().splitlines()
    require(len(filelist)==27 and set(filelist)==dut|{'tb/dv_stream_tb.sv'},'Exact admitted compile closure')
    if (ROOT/'package_manifest.json').exists():
        anchor=json.loads((ROOT/'package_manifest.json').read_text())
        require(admission['source_id']==anchor['tsh2_source_id'] and sha(source/'admission.json')==anchor['tsh2_admission_sha256'],'Sibling TSH2 admission binding')
    cases=json.loads((source/'fixtures/cases.json').read_text());require(len(cases)==4,'Four cases required')
    return admission,cases
def reconcile(folder,source,cases,seed):
    """Independent complete trace readback, separate from UVM in-simulator checks."""
    rows=csv_rows(folder/'observed.csv');coverage=csv_rows(folder/'coverage.csv')
    require(len(coverage)==5,'Five observed epoch dispositions required')
    require(all(set(r)=={'epoch','case_id','kind','index','frame','value','real','imag','mag2','threshold','pre_mask','mask','eligible','last'} for r in rows),'Exact trace field set')
    require(all(r['kind'] in ('START','PCM','SOURCE','Y','TAP','PACKET') and int(r['epoch']) in range(5) for r in rows),'Unknown event kind or epoch')
    require([int(r['epoch']) for r in rows]==sorted(int(r['epoch']) for r in rows),'Epoch order')
    out=[]
    for epoch in range(5):
        c=cases[max(0,epoch-1)];rr=[r for r in rows if int(r['epoch'])==epoch]
        require(all(int(r['case_id'])==max(0,epoch-1) for r in rr),'Case ownership')
        require(len([r for r in rr if r['kind']=='START'])==1,'Exactly one observed accepted start')
        require(rr[0]['kind']=='START','Start precedes every observation')
        x=list(map(signed12,mem(source/c['input'])));y=list(map(signed12,mem(source/c['y'])));bins=csv_rows(source/c['bins']);packet=mem(source/c['packet_memh'])
        by={kind:[r for r in rr if r['kind']==kind] for kind in ('PCM','SOURCE','Y','TAP','PACKET')}
        for kind,gold in [('PCM',x),('SOURCE',x+[0]*512),('Y',y),('PACKET',packet)]:
            actual=by[kind];require(len(actual)<=len(gold),'Extra '+kind)
            if epoch:require(len(actual)==len(gold),'Missing '+kind)
            require(all(int(r['index'])==i and int(r['value'])==gold[i] for i,r in enumerate(actual)),kind+' exact order/value')
        if epoch:require(len(by['TAP'])==1161,'Exact taps')
        for i,r in enumerate(by['TAP']):
            b=bins[i]
            for field,col in [('frame','frame_idx'),('index','bin_idx'),('real','real'),('imag','imag'),('mag2','mag2'),('pre_mask','pre_mask'),('mask','mask'),('eligible','eligible')]:require(int(r[field])==int(b[col]),'Exact tap '+field)
            require(int(r['threshold'])==int(c['threshold']) and int(r['last'])==(int(b['bin_idx'])==128),'Tap threshold/last')
        cov={k:(v if k=='status' else int(v)) for k,v in coverage[epoch].items()}
        require(cov['epoch']==epoch and cov['seed']==seed and cov['case_id']==max(0,epoch-1),'Coverage ownership')
        for col,kind in [('inputs','PCM'),('sources','SOURCE'),('y','Y'),('taps','TAP'),('bytes','PACKET')]:require(cov[col]==len(by[kind]),'Observed count reconciliation: '+col)
        require(cov['masked']==sum(int(r['mask']) for r in by['TAP']) and cov['kept']==sum(int(r['eligible']) and not int(r['mask']) for r in by['TAP']) and cov['ineligible']==sum(not int(r['eligible']) for r in by['TAP']),'Observed spectral event reconciliation')
        require(cov['status']==('ABORT' if epoch==0 else 'COMPLETE'),'Epoch disposition')
        if epoch:
            for k in ['fifo_empty','fifo_one','fifo_full','input_gaps','y_stalls','packet_stalls']:require(cov[k]>0,'Observed bin '+k)
            require(cov['final_y_hold']==32+seed%32 and cov['discontinuities']==1,'Boundary events')
            err=[(x[i-384] if 384<=i<1408 else 0)-v for i,v in enumerate(y)]
            require([cov[k] for k in ('metric_count','sum_abs','sum_sq','max_abs')]==[1536,sum(map(abs,err)),sum(e*e for e in err),max(map(abs,err))],'Independent final metrics')
        else:require(len(by['TAP'])>=16 and len(by['TAP'])<1161,'Actual busy reset prefix')
        out.append({'case':c['id'],'epoch':epoch,'observed':cov})
    return out
def junit(path,tests):
    root=ET.Element('testsuite',name='tsh2_uvm',tests=str(len(tests)),failures=str(sum(t['status']!='PASS' for t in tests)))
    for t in tests:
        node=ET.SubElement(root,'testcase',classname='trecap.uvm',name=t['name'])
        if t['status']!='PASS':ET.SubElement(node,'failure').text=t.get('message','Failed')
        ET.SubElement(node,'system-out').text=t.get('detail','')
    ET.ElementTree(root).write(path,encoding='utf-8',xml_declaration=True)
def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--source-root',type=Path,default=ROOT.parent/'tsh2');ap.add_argument('--sim-bin',type=Path,default=os.environ.get('MODELSIM_BIN'));ap.add_argument('--uvm-home',type=Path,default=os.environ.get('UVM_HOME'));ap.add_argument('--out',type=Path);ap.add_argument('--seeds',default='1,7,20261017');ap.add_argument('--timeout',type=int,default=600);ap.add_argument('--check-package',action='store_true');ap.add_argument('--skip-negative',action='store_true',help='Debugging only; not complete regression')
    args=ap.parse_args();tests=[];out=None
    try:
        source=args.source_root.resolve();admission,cases=verify_source(source)
        if args.check_package:
            require((ROOT/'package_manifest.json').is_file(),'Required UVM package manifest missing')
            admitted=json.loads((ROOT/'package_manifest.json').read_text())['files']
            required={'run.py','run.do','tb/tsh2_if.sv','tb/tsh2_top.sv','tb/tsh2_uvm_pkg.sv','README.md'}
            require(set(admitted)==required,'Exact UVM package manifest closure')
            for p,h in admitted.items():
                require(not Path(p).is_absolute() and '..' not in Path(p).parts and '\\' not in p and (ROOT/p).resolve().is_relative_to(ROOT.resolve()),'Unsafe manifest path')
                require(sha(ROOT/p)==h,'UVM package mismatch: '+p)
            print(json.dumps({'status':'PASS','scope':'static package/source admission only; no UVM execution','dut_files':26}));return 0
        require(args.out is not None and args.sim_bin is not None and args.uvm_home is not None,'Set --out, --sim-bin and --uvm-home')
        seeds=list(map(int,args.seeds.split(',')));require(len(seeds)==len(set(seeds)) and all(0<s<2**32 for s in seeds),'Unique nonzero unsigned32 seeds required')
        require(args.timeout>0,'Timeout must be positive')
        out=args.out.resolve();require(not out.exists(),'Output must be a new directory');out.mkdir(parents=True);build=out/'build';build.mkdir()
        tools={name:(args.sim_bin/(name+('.exe' if os.name=='nt' else ''))).resolve() for name in ('vlib','vmap','vlog','vsim')}
        require(all(p.is_file() for p in tools.values()),'Missing simulator executable')
        uvm=args.uvm_home.resolve();require((uvm/'src/uvm_pkg.sv').is_file() and (uvm/'LICENSE.txt').is_file(),'Official UVM source distribution required')
        for directory in ('rtl','artifacts','fixtures'):shutil.copytree(source/directory,build/directory)
        shutil.copytree(ROOT/'tb',build/'tb');shutil.copy2(ROOT/'run.do',build/'run.do')
        filelist=[p for p in (source/'source_files.f').read_text().splitlines() if p.startswith('rtl/')]+['tb/tsh2_if.sv','tb/tsh2_uvm_pkg.sv','tb/tsh2_top.sv']
        (build/'source_files.f').write_text('\n'.join(filelist)+'\n')
        files={str(p.relative_to(source)).replace('\\','/'):sha(p) for d in ('rtl','artifacts','fixtures') for p in (source/d).rglob('*') if p.is_file()}
        own={str(p.relative_to(ROOT)).replace('\\','/'):sha(p) for p in [ROOT/'run.py',ROOT/'run.do',*sorted((ROOT/'tb').glob('*.sv'))]}
        uvm_files={str(p.relative_to(uvm)).replace('\\','/'):sha(p) for p in (uvm/'src').rglob('*') if p.is_file()}
        uvm_files.update({n:sha(uvm/n) for n in ('README.txt','LICENSE.txt','NOTICE.txt','release-notes.txt')})
        source_admission_sha=sha(source/'admission.json')
        save(out/'run_manifest.json',{'schema':'tsh2-real-uvm-v1','source_id':admission['source_id'],'source_admission_sha256':source_admission_sha,'seeds':seeds,'cases':cases,'source_files':files,'compiled_filelist':filelist,'uvm_environment_files':own,'uvm_library_files':uvm_files,'uvm_version':'Accellera UVM 1.2 bundled with simulator','defines':['UVM_NO_DPI'],'DUT_SYNTHESIS_defined':False,'clock_ns':10,'tools':{k:{'path':str(v),'sha256':sha(v)} for k,v in tools.items()},'scope':'Finite synthetic1024 stream/core/exporter; deterministic UVM sequence, TLM monitor and exact scoreboard; observed event counts, no constraint randomization or covergroups'})
        inv=''.join(f"{c['input']} {c['y']} {c['bins']} {c['packet_memh']} {int(c['threshold']):014x} {int(c['sparse'])} {c['packet_bytes']}\n" for c in cases);(build/'cases.txt').write_text(inv)
        for name,argv in [('version',[tools['vsim'],'-version']),('vlib',[tools['vlib'],'work']),('vmap',[tools['vmap'],'-c']),('compile',[tools['vlog'],'-sv','-warning','2892','+define+UVM_NO_DPI','+incdir+'+str(uvm/'src'),'-work','work',uvm/'src/uvm_pkg.sv','-f','source_files.f'])]:
            rec,log=command(argv,build,out/(name+'.log'),args.timeout);require(rec['exit_code']==0 and not rec.get('timed_out'),name+' failed')
        results=[]
        for seed in seeds:
            target=out/f'seed_{seed}';target.mkdir();argv=[tools['vsim'],'-c','-onfinish','stop','-voptargs=+acc','work.tsh2_top','+CASES=cases.txt',f'+OUT=../seed_{seed}',f'+SEED={seed}','-do','run.do']
            rec,log=command(argv,build,target/'simulate.log',args.timeout)
            require(rec['exit_code']==0 and not rec.get('timed_out') and '[TSH2_UVM_COMPLETE]' in log and 'UVM_EXIT_STATE=1' in log,'UVM run did not complete: '+str(seed))
            require(not re.search(r'^# UVM_(?:ERROR|FATAL)\s+[^:]|\*\* (?:Error|Fatal):',log,re.M),'Unexpected error/fatal')
            require(re.search(r'UVM_ERROR\s*:\s*0',log) and re.search(r'UVM_FATAL\s*:\s*0',log),'Nonzero/missing UVM report counts')
            result=reconcile(target,source,cases,seed);results.extend(result);tests.append({'name':f'seed_{seed}_four_epochs_reset_recovery','status':'PASS','detail':'Official UVM execution and independent recorded trace reconciliation'})
            save(target/'report.json',{'status':'PASS','seed':seed,'epochs':result,'command':rec,'trace_sha256':sha(target/'observed.csv'),'coverage_sha256':sha(target/'coverage.csv')});print('PASS seed',seed,flush=True)
        if not args.skip_negative:
            target=out/'negative_wrong_y';target.mkdir();argv=[tools['vsim'],'-c','-onfinish','stop','work.tsh2_top','+CASES=cases.txt','+OUT=../negative_wrong_y','+SEED=1','+INJECT_BAD_Y','-do','run.do']
            rec,log=command(argv,build,target/'simulate.log',args.timeout)
            require(rec['exit_code']!=0 and not rec.get('timed_out') and re.search(r'UVM_FATAL .*\[Y_GOLD_MISMATCH\]',log) and '[TSH2_UVM_COMPLETE]' not in log,'Negative control did not fail for exact expected UVM ID')
            tests.append({'name':'negative_wrong_y','status':'PASS','detail':'Deliberately changed expected Y rejected by UVM_FATAL Y_GOLD_MISMATCH; simulator nonzero exit'});save(target/'report.json',{'status':'PASS','expected_failure':'Y_GOLD_MISMATCH','command':rec})
        # Recheck after execution: reference, DUT, compiled copies, environment,
        # runner and official library bytes must remain the admitted inputs.
        for p,h in files.items():require(sha(source/p)==h and sha(build/p)==h,'Source changed during execution: '+p)
        for p,h in own.items():require(sha(ROOT/p)==h,'Harness changed during execution: '+p)
        for p,h in uvm_files.items():require(sha(uvm/p)==h,'UVM library changed during execution: '+p)
        require(sha(source/'admission.json')==source_admission_sha,'Sibling admission changed during execution');verify_source(source)
        tests.append({'name':'postrun_source_binding','status':'PASS','detail':'Source, copied build inputs, harness, runner and official UVM source unchanged'})
        status='INCOMPLETE' if args.skip_negative else 'PASS'
        save(out/'summary.json',{'status':status,'scope':'Executed genuine UVM; no board access','seeds':seeds,'completed_epochs':4*len(seeds),'busy_reset_aborts':len(seeds),'immediate_recovery_epochs_included_in_completed':len(seeds),'tests':tests,'epochs':results,'negative_control_executed':not args.skip_negative,'manifest_sha256':sha(out/'run_manifest.json')});junit(out/'junit.xml',tests);print(status,out);return 2 if args.skip_negative else 0
    except Exception as e:
        tests.append({'name':'regression','status':'FAIL','message':str(e)})
        if out is not None and out.exists():save(out/'summary.json',{'status':'FAIL','tests':tests});junit(out/'junit.xml',tests)
        print('FAIL:',e,file=sys.stderr);return 1
if __name__=='__main__':raise SystemExit(main())
