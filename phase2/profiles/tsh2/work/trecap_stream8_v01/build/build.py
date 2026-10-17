"""Isolated TSH2/HPS50 streaming build. No board operations; assembly is gated."""
from pathlib import Path
import argparse,ctypes,hashlib,json,os,re,shutil,subprocess,sys,time
ROOT=Path(__file__).resolve().parents[3]
HERE=Path(__file__).resolve().parent
WORK=HERE.parent
HPS=ROOT/'outputs/trecap_hps_transport_v01/build01'
CORE=HPS
QUARTUS=Path('D:/QuartusLite20.1.1/quartus/bin64')
PROJECT='audio_hps'
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def save(p,x):Path(p).write_text(json.dumps(x,indent=2)+'\n')
def require(ok,msg):
    if not ok:raise ValueError(msg)
def verify(out):
    m=json.loads((out/'source_manifest.json').read_text())
    for r in m['files']:require(sha(out/r['path'])==r['sha256'],'source drift '+r['path'])
    for rel,h in m['settings_sha256'].items():require(sha(out/rel)==h,'settings drift '+rel)
    return m
def prepare(out):
    require(not out.exists(),'fresh build required')
    base=json.loads((HPS/'source_manifest.json').read_text())
    prior=json.loads((CORE/'registration.json').read_text())
    for r in base['files']:require(sha(HPS/r['path'])==r['sha256'],'HPS base source drift '+r['path'])
    for rel,h in prior['sources_sha256'].items():require(sha(CORE/rel)==h,'qualified parent source drift '+rel)
    require(json.loads((HPS/'assembly_receipt.json').read_text())['status']=='PASS_SOF_ASSEMBLED_NOT_PROGRAMMED','parent assembly gate')
    new_sources=[WORK/'core'/n for n in ('trecap_pcm_stream_source.sv','trecap_pcm_stream_top.sv')]
    new_sources += [WORK/'rtl'/n for n in ('stream_fifo.sv','trecap_stream_adapter.sv')]
    for p in new_sources:require(p.is_file(),'new source must be frozen first: '+str(p))
    out.mkdir(parents=True)
    # Source-only snapshots; never copy stale databases or fitted artifacts.
    shutil.copytree(HPS/'legacy',out/'legacy')
    for n in ('hps_image.sdc','hps_peripheral_timing.sdc','hps_peripheral_io.tcl','capture_hps_ddr_assignments.tcl'):
        shutil.copyfile(HPS/n,out/n)
    (out/'sources').mkdir()
    shutil.copyfile(HPS/'sources/platform_designer_wrapper.sv',out/'sources/platform_designer_wrapper.sv')
    shutil.copytree(CORE/'source',out/'source')
    shutil.copytree(CORE/'artifacts',out/'artifacts')
    (out/'generated').mkdir()
    generated=['trecap_core_export_observed.sv','trecap_spectral_exporter.sv']
    for n in generated:shutil.copyfile(CORE/'generated'/n,out/'generated'/n)
    for p in new_sources:shutil.copyfile(p,out/('generated' if p.parent.name=='core' else 'sources')/p.name)
    top=(HPS/'sources/trecap_hps_top.sv').read_text()
    old='trecap_hps_adapter #(.SOURCE_ID(`TSH_SOURCE_ID)) adapter('
    require(top.count(old)==1,'HPS top adapter anchor')
    top=top.replace(old,'trecap_stream_adapter #(.SOURCE_ID(`TSH_SOURCE_ID)) adapter(')
    (out/'sources/trecap_hps_top.sv').write_text(top)
    shutil.copyfile(WORK/'CONTRACT.md',out/'CONTRACT.md')
    shutil.copyfile(__file__,out/'build_snapshot.py')
    (out/'review_scripts').mkdir()
    for n in ('timing_review.tcl','analyze_timing.py','review_image.py'):
        shutil.copyfile(HERE/n,out/'review_scripts'/n)
    files=[dict(path=p.relative_to(out).as_posix(),sha256=sha(p)) for p in sorted(out.rglob('*')) if p.is_file()]
    source_id=hashlib.sha256(json.dumps(files,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    qsf=(HPS/'audio_hps.qsf').read_text().splitlines()
    qsf=[s for s in qsf if '-name SYSTEMVERILOG_FILE' not in s and 'TSH_SOURCE_ID=' not in s and '-name SEARCH_PATH' not in s]
    qsf += [f'set_global_assignment -name VERILOG_MACRO "TSH_SOURCE_ID=256\'h{source_id}"']
    oldqsf=(CORE/'audio_hps.qsf').read_text().splitlines()
    qsf += [s for s in oldqsf if '-name SEARCH_PATH' in s or '-name SYSTEMVERILOG_FILE source/' in s]
    order=generated+['trecap_pcm_stream_source.sv','trecap_pcm_stream_top.sv']
    qsf += ['set_global_assignment -name SYSTEMVERILOG_FILE generated/'+n for n in order]
    qsf += ['set_global_assignment -name SYSTEMVERILOG_FILE sources/'+n for n in ('platform_designer_wrapper.sv','stream_fifo.sv','trecap_stream_adapter.sv','trecap_hps_top.sv')]
    (out/'audio_hps.qsf').write_text('\n'.join(qsf)+'\n')
    shutil.copyfile(HPS/'audio_hps.qpf',out/'audio_hps.qpf')
    (out/'hps_ddr_assignments.qsf').write_text('# Placeholder for map only; regenerate vendor DDR assignments before fit.\n')
    m=dict(schema='tsh2-hps50-snapshot-v1',status='PREPARED',source_id=source_id,files=files,
      qip_references=base['qip_references'],hps_bus_ports=base['hps_bus_ports'],fpga_pins=base['fpga_pins'],
      settings_sha256={n:sha(out/n) for n in ('audio_hps.qsf','audio_hps.qpf')},
      generated_input_initial_sha256={'hps_ddr_assignments.qsf':sha(out/'hps_ddr_assignments.qsf')},
      base_hps_manifest_sha256=sha(HPS/'source_manifest.json'),base_core_registration_sha256=sha(CORE/'registration.json'),
      new_application_sha256={p.name:sha(p) for p in new_sources},exporter_sha256=sha(out/'generated/trecap_spectral_exporter.sv'),
      adapter_sha256=sha(out/'sources/trecap_stream_adapter.sv'))
    save(out/'source_manifest.json',m)
    save(out/'registration.json',dict(schema='tsh2-build-registration-v1',source_id=source_id,source_manifest_sha256=sha(out/'source_manifest.json'),
      sources_sha256={r['path']:r['sha256'] for r in files}|m['settings_sha256'],device='5CSEMA5F31C6',clock_hz=50000000,
      adapter_sha256=m['adapter_sha256'],exporter_sha256=m['exporter_sha256'],new_application_sha256=m['new_application_sha256']))
    print(json.dumps(dict(status='PREPARED',build=str(out),source_id=source_id,registration_sha256=sha(out/'registration.json'))),flush=True)
def run(out,stage):
    m=verify(out);require(sha(__file__)==sha(out/'build_snapshot.py'),'runner changed')
    target=out/(stage+'_receipt.json');require(not target.exists(),'preserve prior receipt')
    previous={'ddr_capture':'map','fit':'ddr_capture','sta':'fit','review':'sta'}
    if stage in previous:require(json.loads((out/(previous[stage]+'_receipt.json')).read_text())['status']=='PASS','prior stage not PASS')
    if stage=='map':require(sha(out/'hps_ddr_assignments.qsf')==m['generated_input_initial_sha256']['hps_ddr_assignments.qsf'],'initial DDR placeholder drift')
    if stage in ('fit','sta','review'):
        require(sha(out/'hps_ddr_assignments.qsf')==json.loads((out/'ddr_capture_receipt.json').read_text())['ddr_assignments_sha256'],'captured DDR drift')
    drive=next((c+':' for c in 'QZYXWUTSR' if not ctypes.windll.kernel32.GetLogicalDrives()&(1<<(ord(c)-65))),None)
    require(drive is not None,'no free short alias')
    require(shutil.disk_usage(out).free>1024**3,'disk space below1GiB')
    receipt=dict(status='RUNNING',stage=stage,registration_sha256=sha(out/'registration.json'),source_verified_before=True,timeout_s=3600)
    start=time.monotonic();owned=False
    try:
        subprocess.run(['subst',drive,str(out)],check=True,capture_output=True,timeout=15);owned=True
        cwd=drive+'/'
        if stage in ('map','fit'):args=[str(QUARTUS/('quartus_'+stage+'.exe')),'--read_settings_files=on','--write_settings_files=off',PROJECT]
        elif stage=='sta':args=[str(QUARTUS/'quartus_sta.exe'),PROJECT]
        elif stage=='ddr_capture':args=[str(QUARTUS/'quartus_sta.exe'),'-t','capture_hps_ddr_assignments.tcl',PROJECT,PROJECT,
          'legacy/platform/de1soc/qsys/system/synthesis/submodules/hps_sdram_p0_pin_assignments.tcl','hps_ddr_assignments.qsf',sys.executable]
        else:args=[str(QUARTUS/'quartus_sta.exe'),'-t','review_scripts/timing_review.tcl',cwd,str(out/'timing_review')]
        tmp=out/'tmp';tmp.mkdir(exist_ok=True)
        env=os.environ.copy();env.update(QUARTUS_ROOTDIR=str(QUARTUS.parent),QUARTUS_ROOTDIR_OVERRIDE=str(QUARTUS.parent),TEMP=str(tmp),TMP=str(tmp),TMPDIR=str(tmp))
        env['PATH']=str(QUARTUS)+os.pathsep+env.get('PATH','')
        receipt.update(argv=args,cwd=cwd,tool_sha256=sha(args[0]));save(target,receipt)
        with (out/(stage+'.log')).open('xb') as f:
            proc=subprocess.Popen(args,cwd=cwd,env=env,stdout=f,stderr=subprocess.STDOUT);receipt['pid']=proc.pid;save(target,receipt)
            print(json.dumps(dict(stage=stage,pid=proc.pid)),flush=True)
            try:receipt['returncode']=proc.wait(timeout=3600)
            except subprocess.TimeoutExpired:
                subprocess.run(['taskkill','/PID',str(proc.pid),'/T','/F'],capture_output=True,timeout=20);proc.wait(timeout=20);raise RuntimeError('stage timeout')
        require(receipt['returncode']==0,stage+' failed')
        require(not re.search(r'^\s*Error\s*\(', (out/(stage+'.log')).read_text(errors='replace'),re.M),'error in log')
        verify(out);receipt.update(status='PASS',source_verified_after=True)
        if stage=='ddr_capture':receipt['ddr_assignments_sha256']=sha(out/'hps_ddr_assignments.qsf')
    except Exception as e:receipt.update(status='FAIL',error=str(e))
    finally:
        if owned:receipt['alias_released']=subprocess.run(['subst',drive,'/D'],capture_output=True,timeout=15).returncode==0
    receipt['elapsed_s']=time.monotonic()-start
    if (out/(stage+'.log')).exists():receipt['log_sha256']=sha(out/(stage+'.log'))
    receipt['artifact_sha256']={p.relative_to(out).as_posix():sha(p) for folder in ('output_files','timing_review') for p in (out/folder).glob('*') if p.is_file()}
    save(target,receipt)
    # Preserve legacy parser inputs while making the preassembly sequence explicit.
    stages=[]
    for name in ('map','ddr_capture','fit','sta'):
        p=out/(name+'_receipt.json')
        if p.exists():
            r=json.loads(p.read_text());stages.append(dict(stage=name,exit_code=r.get('returncode'),log=name+'.log',sha256=r.get('log_sha256')))
    rec=dict(status='PREASSEMBLY_BUILD',source_id=m['source_id'],source_manifest_sha256=sha(out/'source_manifest.json'),stages=stages,
      settings_before_tool_sha256=m['settings_sha256'],settings_after_tool_sha256={k:sha(out/k) for k in m['settings_sha256']},
      ddr_assignments_sha256=sha(out/'hps_ddr_assignments.qsf'),artifacts={})
    for ext in ('pin','map.rpt','fit.rpt','sta.rpt','fit.summary','sta.summary'):
        p=out/'output_files'/('audio_hps.'+ext)
        if p.exists():rec['artifacts'][ext]=dict(path=p.relative_to(out).as_posix(),sha256=sha(p))
    save(out/'build_receipt.json',rec)
    print(json.dumps(dict(status=receipt['status'],receipt=str(target))),flush=True)
    return receipt['status']=='PASS'
if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--out',type=Path,required=True);ap.add_argument('--stage',choices=['prepare','map','ddr_capture','fit','sta','review'],default='prepare');a=ap.parse_args()
    if a.stage=='prepare':prepare(a.out.resolve())
    else:raise SystemExit(0 if run(a.out.resolve(),a.stage) else 1)
