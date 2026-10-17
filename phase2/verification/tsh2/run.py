#!/usr/bin/env python3
"""CPU-only TSH2 regression. Python3.10+ standard library and ModelSim/Questa."""
from __future__ import annotations
import argparse,copy,csv,datetime,hashlib,json,os,re,shutil,signal,subprocess,sys,tempfile,time,uuid
from pathlib import Path
import xml.etree.ElementTree as ET
from fixture_tools import synthetic_input,packets

ROOT=Path(__file__).resolve().parent
REQUIRED_BINS=('fifo_empty_cycles','fifo_one_cycles','fifo_full_cycles','input_gap_cycles','y_stall_cycles','export_stall_cycles','simultaneous_push_pop')
TAP_FIELDS=('frame_idx','bin_idx','real','imag','mag2','pre_mask','mask','eligible')
class CheckFailure(Exception):pass
def require(ok,message):
    if not ok:raise CheckFailure(message)
def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def save(path,data):Path(path).write_text(json.dumps(data,indent=2)+'\n',encoding='utf-8')
def read_csv(path):
    with Path(path).open(newline='',encoding='utf-8') as f:return list(csv.DictReader(f))
def signed_mem(path):
    values=[int(v,16) for v in Path(path).read_text().split()]
    require(all(0<=v<4096 for v in values),'12-bit fixture range')
    return [v-4096 if v>=2048 else v for v in values]
def packet_gold(case,base=ROOT):return bytes(int(v,16) for v in (base/case['packet_memh']).read_text().split())
def integrity():
    admission=json.loads((ROOT/'admission.json').read_text())
    for row in admission['admitted_files']:
        require(sha(ROOT/row['path'])==row['sha256'],'Admission hash mismatch: '+row['path'])
    filelist=(ROOT/'source_files.f').read_text().splitlines()
    expected={r['path'] for r in admission['admitted_files'] if r['kind']=='unchanged_registered_DUT'}|{'tb/dv_stream_tb.sv'}
    require(len(filelist)==len(set(filelist)) and set(filelist)==expected,'Exact admitted relative compile closure')
    cases=json.loads((ROOT/'fixtures/cases.json').read_text())
    require(len(cases)==4,'Expected four admitted case/mode combinations')
    for c in cases:
        require(len(signed_mem(ROOT/c['input']))==1024,'Input length')
        require(signed_mem(ROOT/c['input'])==synthetic_input(),'Synthetic input regeneration')
        require(len(signed_mem(ROOT/c['y']))==1536,'Y length')
        require(len(read_csv(ROOT/c['bins']))==1161,'Canonical row count')
        require(len(packet_gold(c))==c['packet_bytes'],'Packet size')
        require(packets(read_csv(ROOT/c['bins']),int(c['threshold']),c['sparse'])==packet_gold(c),'Independent packet regeneration')
    return admission,cases
def check_trace(directory,cases,seed,fixture_root=ROOT):
    """Fail closed on missing, duplicate, reordered, unknown or differing fields."""
    directory=Path(directory)
    source=read_csv(directory/'source.csv');y=read_csv(directory/'y.csv');taps=read_csv(directory/'taps.csv');coverage=read_csv(directory/'coverage.csv')
    require(len(source)==len(y)==1536*len(cases),'Complete source/Y cardinality')
    require(len(taps)==1161*len(cases),'Complete canonical cardinality')
    require(len(coverage)==len(cases),'Complete case coverage cardinality')
    result=[]
    for phase,c in enumerate(cases):
        x=signed_mem(fixture_root/c['input']);yg=signed_mem(fixture_root/c['y']);tg=read_csv(fixture_root/c['bins'])
        for index in range(1536):
            a=source[phase*1536+index];b=y[phase*1536+index]
            require([int(a[k]) for k in ('phase','index','value')]==[phase,index,x[index] if index<1024 else 0],f'source phase{phase} index{index}')
            require([int(b[k]) for k in ('phase','index','value')]==[phase,index,yg[index]],f'Y phase{phase} index{index}')
        for index,e in enumerate(tg):
            a=taps[phase*1161+index]
            require(int(a['phase'])==phase and int(a['threshold'])==int(c['threshold']),f'tap ownership phase{phase}')
            require(all(int(a[k])==int(e[k]) for k in TAP_FIELDS),f'tap values phase{phase} row{index}')
        require((directory/f'packet_{phase}.bin').read_bytes()==packet_gold(c,fixture_root),f'packet phase{phase}')
        row={k:int(v) for k,v in coverage[phase].items()}
        require(row['phase']==phase and row['seed']==seed,'coverage ownership')
        for k,v in {'input_tokens':1024,'source_tokens':1536,'y_tokens':1536,'tap_rows':1161,'packet_bytes':c['packet_bytes'],'write_wraps':4,'read_wraps':4,'final_y_hold_cycles':32+seed%32,'discontinuities':1}.items():require(row[k]==v,'coverage '+k)
        for k in REQUIRED_BINS:require(row[k]>0,'Unhit required event bin: '+k)
        errors=[(x[n-384] if 384<=n<1408 else 0)-v for n,v in enumerate(yg)]
        require([row[k] for k in ('metric_count','sum_abs','sum_sq','max_abs')]==[1536,sum(abs(e) for e in errors),sum(e*e for e in errors),max(abs(e) for e in errors)],'Final time metrics')
        result.append({'case':c['id'],'seed':seed,'observed':row})
    return result
def simulator(bin_dir):
    result={}
    folder=bin_dir or os.environ.get('MODELSIM_BIN')
    for name in ('vlib','vmap','vlog','vsim'):
        found=None
        if folder:
            for ending in ('.exe','') if os.name=='nt' else ('','.exe'):
                p=Path(folder)/(name+ending)
                if p.is_file():found=str(p.resolve());break
        else:found=shutil.which(name)
        require(found is not None,'ModelSim/Questa tool missing: '+name+'; use --sim-bin, MODELSIM_BIN or PATH')
        result[name]=found
    return result
def command(argv,cwd,log_path,timeout):
    start=time.monotonic();record={'argv':[str(a) for a in argv],'cwd':str(cwd),'timeout_seconds':timeout,'tool_sha256':sha(argv[0]),'started_utc':datetime.datetime.now(datetime.timezone.utc).isoformat()}
    with Path(log_path).open('wb') as f:
        p=subprocess.Popen(record['argv'],cwd=cwd,stdout=f,stderr=subprocess.STDOUT,start_new_session=os.name!='nt')
        record['pid']=p.pid
        try:record['exit_code']=p.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            record['timed_out']=True
            cleanup_start=time.monotonic()
            try:
                if os.name=='nt':
                    cleanup=subprocess.run(['taskkill','/PID',str(p.pid),'/T','/F'],capture_output=True,text=True,timeout=20,check=False)
                    record['cleanup']={'exit_code':cleanup.returncode,'stdout':cleanup.stdout[-4096:],'stderr':cleanup.stderr[-4096:]}
                else:os.killpg(p.pid,signal.SIGKILL)
                if p.poll() is None:p.kill()
                record['exit_code']=p.wait(timeout=10)
            except (OSError,subprocess.TimeoutExpired) as error:
                record['cleanup_error']=str(error);record['exit_code']=p.poll()
            record['cleanup_seconds']=round(time.monotonic()-cleanup_start,3)
    record.update(elapsed_seconds=round(time.monotonic()-start,3),log_sha256=sha(log_path))
    save(Path(log_path).with_suffix('.command.json'),record)
    return record,Path(log_path).read_text(errors='replace')
def xml_report(path,cases):
    suite=ET.Element('testsuite',name='trecap_tsh2',tests=str(len(cases)),failures=str(sum(c['status']=='FAIL' for c in cases)),errors=str(sum(c['status']=='ERROR' for c in cases)))
    for c in cases:
        node=ET.SubElement(suite,'testcase',name=c['name'],classname='trecap.tsh2',time=str(c.get('seconds',0)))
        if c['status']!='PASS':ET.SubElement(node,'failure' if c['status']=='FAIL' else 'error',message=c.get('message','failed')).text=c.get('message','failed')
        ET.SubElement(node,'system-out').text=c.get('detail','')
    ET.ElementTree(suite).write(path,encoding='utf-8',xml_declaration=True)
def self_test(cases):
    """Pure scoreboard qualification. Constructed traces are NOT DUT evidence."""
    seed=1
    with tempfile.TemporaryDirectory(prefix='trecap-scoreboard-') as temp:
        p=Path(temp);source=[];ys=[];taps=[];cov=[]
        for phase,c in enumerate(cases):
            x=signed_mem(ROOT/c['input']);y=signed_mem(ROOT/c['y'])
            source.extend({'phase':phase,'index':i,'value':x[i] if i<1024 else 0} for i in range(1536))
            ys.extend({'phase':phase,'index':i,'value':v} for i,v in enumerate(y))
            taps.extend({'phase':phase,**{k:r[k] for k in TAP_FIELDS},'threshold':c['threshold']} for r in read_csv(ROOT/c['bins']))
            errors=[(x[n-384] if 384<=n<1408 else 0)-v for n,v in enumerate(y)]
            cov.append({'phase':phase,'seed':seed,'cycles':1,'input_tokens':1024,'source_tokens':1536,'y_tokens':1536,'tap_rows':1161,'packet_bytes':c['packet_bytes'],**{k:1 for k in REQUIRED_BINS},'write_wraps':4,'read_wraps':4,'final_y_hold_cycles':33,'discontinuities':1,'schedule_hash':0,'metric_count':1536,'sum_abs':sum(abs(e) for e in errors),'sum_sq':sum(e*e for e in errors),'max_abs':max(abs(e) for e in errors)})
            (p/f'packet_{phase}.bin').write_bytes(packet_gold(c))
        def write(name,rows):
            with (p/name).open('w',newline='') as f:
                w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
        tables={'source.csv':source,'y.csv':ys,'taps.csv':taps,'coverage.csv':cov}
        for name,rows in tables.items():write(name,rows)
        check_trace(p,cases,seed);tests=[{'name':'scoreboard_positive_control','status':'PASS'}]
        for name,filename in [('wrong_Y','y.csv'),('missing_Y','y.csv'),('wrong_bin','taps.csv'),('unhit_bin','coverage.csv')]:
            modified=copy.deepcopy(tables[filename])
            if name=='wrong_Y':modified[0]['value']+=1
            elif name=='missing_Y':modified.pop()
            elif name=='wrong_bin':modified[0]['real']=int(modified[0]['real'])+1
            else:modified[0]['fifo_full_cycles']=0
            write(filename,modified)
            try:check_trace(p,cases,seed)
            except (CheckFailure,ValueError,KeyError):tests.append({'name':name,'status':'PASS','detail':'Deliberate mutation rejected'})
            else:raise CheckFailure('Scoreboard accepted deliberate '+name)
            write(filename,tables[filename])
        packet=p/'packet_0.bin';data=bytearray(packet.read_bytes());data[-1]^=1;packet.write_bytes(data)
        try:check_trace(p,cases,seed)
        except CheckFailure:tests.append({'name':'wrong_packet','status':'PASS','detail':'Deliberate mutation rejected'})
        else:raise CheckFailure('Scoreboard accepted deliberate packet mutation')
        return tests
def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--suite',choices=['smoke','regression'],default='smoke');ap.add_argument('--seeds',help='Comma-separated nonzero unsigned32 seeds; default smoke1, regression1,7,20261017')
    ap.add_argument('--sim-bin',help='Directory containing vlib/vmap/vlog/vsim');ap.add_argument('--out',type=Path,help='New result directory; never overwritten')
    ap.add_argument('--timeout',type=int,default=180,help='Host deadline seconds per tool invocation')
    ap.add_argument('--check',action='store_true',help='Check admitted source/fixture hashes only; no simulator')
    ap.add_argument('--self-test',action='store_true',help='Qualify pure Python checker with constructed traces; no DUT simulation')
    ap.add_argument('--check-package',action='store_true',help='CI: admission integrity plus pure checker controls; no simulator')
    args=ap.parse_args();tests=[];results=[];out=None
    try:
        admission,all_cases=integrity()
        if args.check:print(json.dumps({'status':'PASS','scope':'static_admission_integrity','files':len(admission['admitted_files'])}));return 0
        if args.self_test or args.check_package:
            tests=self_test(all_cases);print(json.dumps({'status':'PASS','scope':'admission_integrity_and_constructed_trace_scoreboard_controls_only','files':len(admission['admitted_files']),'tests':tests}));return 0
        seeds=[int(s) for s in (args.seeds or ('1' if args.suite=='smoke' else '1,7,20261017')).split(',')]
        require(len(seeds)==len(set(seeds)) and all(0<s<2**32 for s in seeds),'Seeds must be unique nonzero unsigned32 values')
        require(args.timeout>0,'Timeout must be positive')
        selected=[all_cases[0],all_cases[3]] if args.suite=='smoke' else all_cases
        out=(args.out or ROOT/'runs'/(datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'_'+uuid.uuid4().hex[:8])).resolve()
        require(not out.exists(),'Output directory already exists; choose a new --out')
        out.mkdir(parents=True);build=out/'build';build.mkdir();tools=simulator(args.sim_bin)
        for name in ('rtl','tb','artifacts','fixtures'):shutil.copytree(ROOT/name,build/name)
        for name in ('source_files.f','run.do'):shutil.copy2(ROOT/name,build/name)
        inputs={p.relative_to(ROOT).as_posix():sha(p) for folder in ('rtl','tb','artifacts','fixtures') for p in (ROOT/folder).rglob('*') if p.is_file()}
        inputs.update({n:sha(ROOT/n) for n in ('run.py','run.do','source_files.f','admission.json','fixture_tools.py')})
        save(out/'run_manifest.json',{'schema':'trecap-portable-regression-v1','source_id':admission['source_id'],'suite':args.suite,'seeds':seeds,'cases':selected,'files':inputs,'defines':[],'clock_ns':10,'precision_ps':1,'capabilities':'Procedural four-state SV monitors and exact file scoreboards; no UVM/SVA/coverage-database claim','tools':tools})
        for name,argv in [('vlib',[tools['vlib'],'work']),('vmap',[tools['vmap'],'-c']),('compile',[tools['vlog'],'-sv','-warning','2892','-work','work','-f','source_files.f'])]:
            r,log=command(argv,build,out/(name+'.log'),args.timeout);require(r['exit_code']==0 and not r.get('timed_out'),name+' failed; see '+str(out/(name+'.log')))
        for seed in seeds:
            target=out/f'seed_{seed}';target.mkdir()
            inventory=target/'cases.txt';inventory.write_text(''.join(f"{c['input']} {c['y']} {c['packet_memh']} {int(c['threshold']):014x} {int(c['sparse'])} {c['packet_bytes']}\n" for c in selected))
            argv=[tools['vsim'],'-c','-onfinish','stop','-voptargs=+acc','work.dv_stream_tb',f'+OUT=../seed_{seed}',f'+CASES=../seed_{seed}/cases.txt',f'+COUNT={len(selected)}',f'+SEED={seed}','-do','run.do']
            r,log=command(argv,build,target/'simulate.log',args.timeout)
            try:
                require(r['exit_code']==0 and not r.get('timed_out'),'Simulator failure/watchdog')
                require(f'DV_COMPLETE cases={len(selected)} seed={seed}' in log and not re.search(r'\*\* (?:Error|Fatal):',log),'Missing completion or simulator diagnostic')
                rows=check_trace(target,selected,seed);results.extend(rows)
                tests.append({'name':f'seed_{seed}','status':'PASS','seconds':r['elapsed_seconds'],'detail':f'{len(selected)} exact finite epochs; observed event bins satisfied'})
                save(target/'result.json',{'status':'PASS','coverage':rows,'artifacts':{p.name:sha(p) for p in target.iterdir() if p.is_file()}})
            except Exception as e:tests.append({'name':f'seed_{seed}','status':'FAIL','seconds':r['elapsed_seconds'],'message':str(e)})
        negative=out/'negative_control';negative.mkdir();shutil.copy2(out/f'seed_{seeds[0]}'/'cases.txt',negative/'cases.txt')
        argv=[tools['vsim'],'-c','-onfinish','stop','-voptargs=+acc','work.dv_stream_tb','+OUT=../negative_control','+CASES=../negative_control/cases.txt',f'+COUNT={len(selected)}',f'+SEED={seeds[0]}','+INJECT_BAD_Y','-do','run.do']
        r,log=command(argv,build,negative/'simulate.log',args.timeout)
        passed=r['exit_code']!=0 and not r.get('timed_out') and 'Y_GOLD_MISMATCH' in log and 'DV_COMPLETE' not in log
        tests.append({'name':'RTL_scoreboard_negative_control','status':'PASS' if passed else 'FAIL','seconds':r['elapsed_seconds'],'detail':'Only expectedY[0] altered in isolated simulator memory; DUT and frozen fixtures unchanged. Expected nonzero exit and Y_GOLD_MISMATCH.','message':'' if passed else 'Negative control did not fail by required checker'})
        require(all(sha(ROOT/p)==h for p,h in inputs.items()),'Package files changed during regression')
    except Exception as e:
        tests.append({'name':'infrastructure','status':'ERROR','message':str(e)})
        if out is None:print(json.dumps({'status':'ERROR','error':str(e)}));return 2
    status='PASS' if tests and all(t['status']=='PASS' for t in tests) else 'FAIL'
    if out:
        save(out/'summary.json',{'status':status,'tests':tests,'observed_coverage':results,'coverage_percentage':None,'evidence_scope':'Selected seeded functional simulations only; no formal/CDC/timing/industrial-certification claim'})
        xml_report(out/'junit.xml',tests)
    print(json.dumps({'status':status,'output':str(out),'tests':len(tests),'epochs':len(results)}))
    return 0 if status=='PASS' else 1
if __name__=='__main__':sys.exit(main())
