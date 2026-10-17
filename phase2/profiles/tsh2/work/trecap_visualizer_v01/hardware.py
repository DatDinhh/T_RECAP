"""Serialized, on-demand physical capture using the frozen one-request service.

No RTL changes, persistent board writes, or automatic fault recovery. The GUI
worker must finish every started hardware epoch, including superseded jobs.
"""
from pathlib import Path
from datetime import datetime, timezone
import hashlib, io, json, re, socket, struct, subprocess, tarfile, threading, time, uuid

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'outputs/trecap_visualizer_v01'
RUNNER = ROOT / 'work/ai_audio_frontend_v01/platform/run_uart_plan.ps1'
SOURCE = '39db0fdf3d451dfbf2d878575725cedd3df450980b40b2a742620dfb76a1a8ed'
SOF = 'f96bc5a35adf08711a5f392baf9f8cbf5ec65a17211a58117bdb53f62acbb7ab'
SERVICE = ROOT / 'outputs/trecap_laptop_fpga_v01/service_build01/service.arm'
SERVICE_SHA = 'e1e762c820ec8054864cea687f27d3299ba51d6616759fb7fce82ee93e8511ea'
SYSTEM_PROBE = ROOT / 'outputs/trecap_stream8_v01/host_build02/hps_system_probe.arm'
SYSTEM_SHA = 'b72ceeb68ab6ca015d201f3dbe1a4886d4a0945d16cb78f7eda228d16e26fe92'
FPGA_PROBE = OUT / 'probe_build02/tsh2_probe.arm'
FPGA_PROBE_SHA = 'd859e3835254013dc8a477321248133ffb8a725394c29abbbc7f95311968568d'
BB = '/opt/fma-net/busybox'
IP = '169.254.196.128'
PROC = 'for p in /proc/[0-9]*; do printf "%s " "$p"; cat "$p/comm"; cat "$p/cmdline"; printf "\\n"; done'

def now(): return datetime.now(timezone.utc).isoformat()
def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def read(p): return json.loads(Path(p).read_text(encoding='utf-8-sig'))
def save(p, x): Path(p).write_text(json.dumps(x, indent=2, allow_nan=False)+'\n', encoding='utf-8')
def need(x, why):
    if not x: raise RuntimeError(why)

def command(text, marker, seconds=15, reject=''):
    token='VIZ_'+marker.upper()+'_RC'
    cmd=text+f'; rc=$?; printf "\\n{token}=%s\\n" "$rc"'
    need(len(cmd)<=1024, 'UART command bound')
    return {'command':cmd,'completion_regex':fr'(?m)^{token}=[0-9]+\r*$',
            'expect_regex':fr'(?m)^{token}=0\r*$',
            'reject_regex':fr'(?m)^{token}=[1-9][0-9]*\r*$|Bus error|Segmentation fault|applet not found'+('|'+reject if reject else ''),
            'timeout_seconds':seconds}

def uart(folder, name, steps):
    folder=Path(folder); folder.mkdir(parents=True,exist_ok=True)
    plan, receipt=folder/(name+'_plan.json'),folder/(name+'.json')
    need(not plan.exists() and not receipt.exists(), 'Fresh UART evidence required')
    save(plan,{'scope':'User-requested interactive FPGA visualizer, RAM only, existing qualified TSH2. No RTL, SD, flash, or Windows network change.','commands':steps})
    proc=subprocess.run(['pwsh.exe','-NoProfile','-ExecutionPolicy','Bypass','-File',str(RUNNER),'-PlanPath',str(plan),'-OutputPath',str(receipt)],capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=90)
    need(receipt.exists(), 'UART did not produce a receipt: '+proc.stderr[-800:])
    value=read(receipt)
    need(proc.returncode==0 and value['status']=='PASS' and value['closed'], 'Board command failed; inspect '+str(receipt))
    return value

def body(receipt): return '\n'.join(r['response_body'] for r in receipt['records'])
def json_rows(receipt):
    return [json.loads(line) for line in body(receipt).splitlines() if line.startswith('{') and line.endswith('}')]
def boot(receipt):
    values=set(re.findall(r'(?m)^([a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12})\r?$',body(receipt)))
    need(len(values)==1,'Exactly one observed boot ID required');return values.pop()
def idle(text):
    rows=text.replace('\x00',' ').splitlines()
    need(not any(len(s.split())>=4 and s.split()[0].rstrip(':').isdigit() and s.split()[3]=='0A' for s in rows), 'Another TCP listener is active on board')
    need(not any(re.search(r'(?:service\.arm|tsh2_client|nc -l|timeout -s)',s) for s in rows), 'Another board capture is active')

class Hardware:
    def __init__(self, manifest):
        self.manifest_path=Path(manifest); self.meta=read(manifest)
        self.lock=threading.Lock();self.available=False;self.message='Not verified';self.checked_at=None
        need(self.meta['source_id']==SOURCE and self.meta['sof_sha256']==SOF and self.meta['service_sha256']==SERVICE_SHA,'Deployment identity')
        need(self.meta['fpga_probe_sha256']==FPGA_PROBE_SHA,'Qualified read-only probe identity')
        need(re.fullmatch(r'[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}',self.meta['boot_id']),'Valid deployment boot UUID')
        self.base=self.meta['target']
        need(re.fullmatch(r'/tmp/trecap-visualizer-[a-f0-9]{8}',self.base),'Bounded board RAM path')

    def status(self):
        return {'available':self.available,'status':self.message,'checked_at':self.checked_at,'boot_id':self.meta['boot_id'],
                'mode':'Buffered FPGA capture; threshold applies to the next complete 8-second transaction.', 'ip':IP}

    def _verify(self, folder, label='admission', include_idle=True):
        b=self.base
        steps=[command(f'cat /proc/sys/kernel/random/boot_id; cat /proc/mounts','boot',reject='/dev/mmc|/dev/sd|overlay|nfs')]
        if include_idle: steps.append(command(PROC+'; cat /proc/net/tcp; cat /proc/net/tcp6','idle'))
        preflight=uart(folder,label+'_preflight',steps)
        need(boot(preflight)==self.meta['boot_id'],'Board rebooted; fresh deployment admission required')
        if include_idle: idle(preflight['records'][1]['response_body'])
        steps = [command(f'printf "{SERVICE_SHA}  {b}/service.arm\\n{SYSTEM_SHA}  {b}/system_probe.arm\\n{FPGA_PROBE_SHA}  {b}/tsh2_probe.arm\\n" | {BB} sha256sum -c -','hash'),
                  command(f'{b}/system_probe.arm --require-lw-only','system'),
                  command(f'{BB} timeout -s KILL 10 {b}/tsh2_probe.arm --read-only --source {SOURCE}','fpga')]
        rec=uart(folder,label,steps)
        rows=json_rows(rec)
        need(any(x.get('status')=='PASS_HPS_SYSTEM_STATE_ONLY' and x.get('bridge_reset')==5 and x.get('manager_mode')==4 for x in rows),'Lightweight bridge admission')
        # Exact FPGA predicate is qualified by the read-only probe; its rc must be0.
        fpga=rows[-1];need(fpga.get('status','').startswith('PASS') and fpga.get('source_id')==SOURCE,'Read-only FPGA identity/idle admission')
        self.available=True;self.message='Ready: verified FPGA';self.checked_at=now()
        return rec,fpga

    def connect(self):
        need(self.lock.acquire(blocking=False),'Board capture already running')
        try:
            folder=OUT/'runtime'/('connect_'+uuid.uuid4().hex[:12]);self._verify(folder)
            return self.status()
        except Exception as exc:
            self.available=False;self.message=str(exc);raise
        finally:self.lock.release()

    def capture(self, pcm, threshold, input_sha256, folder, progress=lambda event:None):
        need(type(threshold) is int and 0<=threshold<(1<<56),'Invalid threshold')
        need(len(pcm)==1536000 and hashlib.sha256(pcm).hexdigest()==input_sha256,'Exact registered PCM required')
        values=memoryview(pcm).cast('i')
        need(all(-2048<=v<=2047 for v in values),'Signed12 PCM range')
        need(self.lock.acquire(blocking=False),'Concurrent board access rejected')
        folder=Path(folder)
        b=self.base;run=b+'/run_'+uuid.uuid4().hex[:12];begin=time.perf_counter_ns()
        try:
            folder.mkdir(parents=True,exist_ok=False)
            progress({'phase':'admission','message':'Verifying board identity and idle state'})
            before,fpga_before=self._verify(folder)
            progress({'phase':'starting','message':'Starting one bounded FPGA transaction'})
            start=f'if test ! -e {run}.log; then ( {BB} timeout -s KILL 65 {b}/service.arm --execute-hardware --source {SOURCE} --boot-id {self.meta["boot_id"]} --requests 1; r=$?; printf "%s\\n" "$r" > {run}.rc ) </dev/null > {run}.log 2> {run}.err & p=$!; printf "%s\\n" "$p" > {run}.pid; kill -0 "$p"; else false; fi'
            uart(folder,'start',[command(start,'start')])
            t0=time.perf_counter_ns(); deadline=time.monotonic()+3
            while True:
                try: s=socket.create_connection((IP,18082),timeout=2);break
                except ConnectionRefusedError:
                    if time.monotonic()>=deadline:raise
                    time.sleep(.04)
            with s:
                s.settimeout(50)
                progress({'phase':'sending','message':'Sending registered PCM from the laptop to the board over Ethernet',
                          'completed_bytes':0,'total_bytes':len(pcm)})
                s.sendall(struct.pack('<IQI',0x31515254,threshold,len(pcm))+pcm);s.shutdown(socket.SHUT_WR)
                progress({'phase':'sending','message':'PCM accepted by the laptop socket; waiting for the board reply',
                          'completed_bytes':len(pcm),'total_bytes':len(pcm)})
                progress({'phase':'processing','message':'Waiting for the FPGA service response; internal FFT, threshold and IFFT stages are not separately instrumented'})
                def receive(n,on_chunk=None):
                    parts=[]
                    while n:
                        chunk=s.recv(min(n,1<<20));need(chunk,'Truncated hardware reply');parts.append(chunk);n-=len(chunk)
                        if on_chunk is not None:on_chunk(len(chunk))
                    return b''.join(parts)
                header=receive(40);(folder/'reply.bin').write_bytes(header)
                magic,status,ny,nw,epoch,wall,cpu=struct.unpack('<IIIIQQQ',header)
                need(magic==0x31535254 and status==0 and ny==1538048 and 0<nw<=3241080 and wall>0 and cpu>0,'FPGA reply status/geometry')
                need(epoch==fpga_before['epoch']+1,'One new physical epoch required')
                received=0;reported=0;total=ny+nw
                progress({'phase':'receiving','message':'Receiving reconstructed audio and sparse spectral packets from the board',
                          'completed_bytes':0,'total_bytes':total})
                def received_chunk(count):
                    nonlocal received,reported
                    received+=count
                    # Report measured bytes, with bounded telemetry overhead.
                    if received-reported>=131072 or received==total:
                        progress({'phase':'receiving','message':'Receiving reconstructed audio and sparse spectral packets from the board',
                                  'completed_bytes':received,'total_bytes':total})
                        reported=received
                y=receive(ny,received_chunk);(folder/'y.i32le').write_bytes(y)
                wire=receive(nw,received_chunk);(folder/'sparse.tsp1').write_bytes(wire)
                need(s.recv(1)==b'','Trailing hardware payload')
            roundtrip=time.perf_counter_ns()-t0
            progress({'phase':'verifying','message':'Checking service completion, physical epoch and final board admission'})
            finish=uart(folder,'finish',[command(f'i=0; while test ! -e {run}.rc && test "$i" -lt 3; do {BB} sleep 1; i=$((i+1)); done; test "$(cat {run}.rc)" = 0 && test ! -s {run}.err && cat {run}.log','finish')])
            messages=json_rows(finish)
            need(messages[0]['status']=='LISTENING_FINITE' and messages[0]['requests']==1 and messages[0]['boot_id']==self.meta['boot_id'] and messages[0]['source_id']==SOURCE,'One-request service identity')
            rr=[v for v in messages if 'sequence' in v]
            need(len(rr)==1 and rr[0]['sequence']==0 and rr[0]['success'] and rr[0]['reply_sent'] and rr[0]['epoch']==epoch and rr[0]['threshold']==threshold and rr[0]['board_wall_ns']==wall and rr[0]['board_thread_ns']==cpu,'Service/raw reply agreement')
            need(messages[-1]['status']=='COMPLETED_FINITE_SERVICE','Finite service completion')
            _,fpga_final=self._verify(folder,'final')
            need(fpga_final['epoch']==epoch,'Same completed physical epoch at final admission')
            timings={'host_roundtrip_ns':roundtrip,'board_wall_ns':wall,'board_thread_cpu_ns':cpu,'hardware_job_with_admission_ns':time.perf_counter_ns()-begin}
            meta={**self.meta,'epoch':epoch,'input_sha256':input_sha256,'gold_uploaded':False,'kind':'physical_fpga','recorded_at':now()}
            meta['admission_sha256']={str(p):sha(p) for p in folder.glob('*.json')}
            meta['admission_sha256'][str(self.manifest_path)]=sha(self.manifest_path)
            save(folder/'capture_receipt.json',{'status':'PASS_ACTUAL_ONE_REQUEST_CAPTURE','threshold':threshold,'metadata':meta,'timing':timings,'outputs_sha256':{str(p):sha(p) for p in folder.glob('*') if p.suffix in ('.bin','.i32le','.tsp1')}})
            return {'y_bytes':y,'wire_bytes':wire,'reply_header':header,'physical_metadata':meta,'timing':timings}
        except Exception as exc:
            self.available=False;self.message='Hardware stopped after an error: '+str(exc)
            if folder.exists() and not (folder/'failure.json').exists():
                save(folder/'failure.json',{'status':'FAIL_NO_AUTOMATIC_MMIO_RECOVERY','error':str(exc),'time':now(),'ram_run':run,'bounded_service_exit_seconds':65})
            raise
        finally:self.lock.release()

def provision():
    need(sha(SERVICE)==SERVICE_SHA and sha(SYSTEM_PROBE)==SYSTEM_SHA,'Frozen qualified tools changed')
    need(FPGA_PROBE.exists() and sha(FPGA_PROBE)==FPGA_PROBE_SHA,'Qualified read-only probe identity')
    qualification=read(FPGA_PROBE.parent/'qualification.json')
    need(qualification['status'].startswith('PASS'),'Qualified read-only FPGA probe required')
    tag=uuid.uuid4().hex[:8];folder=OUT/'deployments'/tag;folder.mkdir(parents=True)
    base='/tmp/trecap-visualizer-'+tag
    inv=uart(folder,'inventory',[command('uname -a; cat /proc/sys/kernel/random/boot_id; cat /proc/mounts','inventory',reject='/dev/mmc|/dev/sd|overlay|nfs'),command(PROC+'; cat /proc/net/tcp; cat /proc/net/tcp6','idle'),command('cat /sys/class/net/eth0/carrier; ip -4 addr show dev eth0','network')])
    idle(inv['records'][1]['response_body']);need('6.12.33-fma-h1-console' in body(inv),'Known RAM kernel')
    prior=read(ROOT/'outputs/trecap_monitor_board_v01/captures01/index.json')
    need(boot(inv)==prior['physical_metadata']['boot_id'],'Different board boot; inspect/re-admit before deploying')
    archive=folder/'tools.tar.gz'
    with tarfile.open(archive,'w:gz') as tar:
        for p,name in [(SERVICE,'service.arm'),(SYSTEM_PROBE,'system_probe.arm'),(FPGA_PROBE,'tsh2_probe.arm')]:
            data=p.read_bytes();info=tarfile.TarInfo(base.split('/')[-1]+'/'+name);info.size=len(data);info.mode=0o755;info.mtime=0;tar.addfile(info,io.BytesIO(data))
    receive=f'if test ! -e {base}.tar.gz && test ! -e {base}; then ( {BB} timeout -s KILL 45 {BB} nc -l -p 18080 > {base}.tar.gz; r=$?; printf "%s\\n" "$r" > {base}.receive.rc ) </dev/null > {base}.receive.log 2>&1 & p=$!; {BB} sleep 1; kill -0 "$p"; else false; fi'
    uart(folder,'receive',[command(receive,'receive')])
    with socket.create_connection((IP,18080),timeout=5) as s:
        s.settimeout(10);s.sendall(archive.read_bytes());s.shutdown(socket.SHUT_WR);need(s.recv(1)==b'','Unexpected archive reply')
    uart(folder,'extract',[command(f'test "$(cat {base}.receive.rc)" = 0 && printf "{sha(archive)}  {base}.tar.gz\\n" | {BB} sha256sum -c - && test ! -e {base} && {BB} tar -xzf {base}.tar.gz -C /tmp','extract')])
    manifest=folder/'manifest.json'
    save(manifest,{'status':'DEPLOYED_PENDING_ADMISSION','boot_id':boot(inv),'source_id':SOURCE,'sof_sha256':SOF,'service_sha256':SERVICE_SHA,'fpga_probe_sha256':sha(FPGA_PROBE),'target':base,'gold_uploaded':False,'probe_qualification_sha256':sha(FPGA_PROBE.parent/'qualification.json'),'previous_program_receipt_sha256':sha(ROOT/'outputs/trecap_stream8_v01/program_monitor01/receipt.json'),'created_at':now()})
    hw=Hardware(manifest);hw._verify(folder,'admission')
    save(OUT/'active_hardware.json',{'manifest':str(manifest),'manifest_sha256':sha(manifest),'status':'PASS_VOLATILE_DEMO_DEPLOYMENT','time':now()})
    print(json.dumps({'status':'PASS_VOLATILE_DEMO_DEPLOYMENT','manifest':str(manifest),'board':hw.status()}),flush=True)

if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser();p.add_argument('action',choices=['provision','connect']);p.add_argument('--manifest',type=Path);a=p.parse_args()
    if a.action=='provision':provision()
    else:print(json.dumps(Hardware(a.manifest).connect()))
