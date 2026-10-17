"""Loopback-only demo server; one serialized hardware worker, no simulated data."""
from __future__ import annotations
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, unquote
import argparse, copy, hashlib, json, secrets, threading, time, uuid
from queue_contract import QueueBusy, THRESHOLDS

ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'outputs/trecap_visualizer_v01'
WEB=Path(__file__).resolve().parent/'web'

def need(x,message):
    if not x:raise ValueError(message)
def json_bytes(x):return json.dumps(x,allow_nan=False,separators=(',',':')).encode('utf-8')
def save(p,x):Path(p).write_bytes(json_bytes(x))
def read(p):return json.loads(Path(p).read_text(encoding='utf-8-sig'))

class JobQueue:
    """Keep only the newest pending request; never abort a started capture."""
    def __init__(self,store,hardware,output_root=OUT):
        self.store=store;self.hardware=hardware;self.output_root=Path(output_root)
        self.condition=threading.Condition();self.jobs={};self.pending=None;self.active=None;self.closed=False
        self.job_clocks={}
        self.thread=threading.Thread(target=self._worker,name='serialized-fpga-worker',daemon=True);self.thread.start()

    def submit(self,source_id,threshold,force=True):
        need(isinstance(source_id,str) and len(source_id)<=160,'Invalid recording identifier')
        self.store.record(source_id)
        need(type(threshold) is int and 0<=threshold<=THRESHOLDS[-1],'Threshold must be an integer from 0 through 100000000000')
        need(type(force) is bool,'force must be boolean')
        with self.condition:
            need(not self.closed,'Demo server is stopping')
            if self.pending and self.jobs[self.pending].get('remote_owner'):
                raise QueueBusy('A remote capture is already accepted; wait for it to start or finish')
            if self.pending:
                self.jobs[self.pending].update(status='superseded',message='A newer selection replaced this queued request',finished_at=time.time())
                self._progress(self.pending,'superseded','A newer selection replaced this queued request')
            ident=uuid.uuid4().hex[:16]
            self.jobs[ident]={'job_id':ident,'source_id':source_id,'threshold':threshold,'force':force,'status':'queued',
                              'message':'Waiting for the current hardware transaction to finish' if self.active else 'Queued',
                              'created_at':time.time(),'events':[]}
            self.job_clocks[ident]=time.monotonic()
            self._progress(ident,'queued',self.jobs[ident]['message'])
            self.pending=ident;self.condition.notify_all()
            return copy.deepcopy(self.jobs[ident])

    def submit_remote(self,source_id,threshold,owner,request_key):
        """Caller holds the gateway policy lock; this condition is the atomic reservation.

        Remote requests never queue behind or replace local/remote work. The same
        worker and Hardware instance execute both listeners' accepted requests.
        """
        with self.condition:
            if self.active or self.pending or self.closed:
                raise QueueBusy('The board is busy; try again after the current capture finishes')
            job=self.submit(source_id,threshold,True)
            self.jobs[job['job_id']].update(remote_owner=owner,request_key=request_key)
            return copy.deepcopy(self.jobs[job['job_id']])

    def cancel_remote_pending(self):
        """Disarming never interrupts an epoch that has already started."""
        with self.condition:
            if self.pending and self.jobs[self.pending].get('remote_owner'):
                ident=self.pending
                self.jobs[ident].update(status='superseded',finished_at=time.time())
                self._progress(ident,'superseded','The owner paused remote requests before this capture started')
                self.pending=None;self.condition.notify_all()

    def get(self,ident):
        with self.condition:
            if ident not in self.jobs:raise KeyError('Unknown job')
            return copy.deepcopy(self.jobs[ident])

    def _update(self,ident,**values):
        with self.condition:self.jobs[ident].update(values)

    def _progress(self,ident,phase,message,pass_kind=None,threshold=None,**details):
        """Record observed operation boundaries, never estimated hardware stages.

        Elapsed time uses the server's monotonic clock from submission. The wall
        timestamp is only for chronology. Return values are deep snapshots so
        polling clients cannot mutate a worker's history.
        """
        with self.condition:
            job=self.jobs[ident];previous=job.get('progress',{})
            value={'phase':phase,'message':message,
                   'elapsed_ms':round((time.monotonic()-self.job_clocks[ident])*1000,3),
                   'pass_kind':pass_kind if pass_kind is not None else previous.get('pass_kind','selected'),
                   'threshold':threshold if threshold is not None else previous.get('threshold',job['threshold']),
                   **details}
            job['progress']=value
            job['message']=message
            job['events'].append({**value,'sequence':len(job['events'])+1,'at':time.time()})

    def status(self):
        with self.condition:
            return {'active_job':copy.deepcopy(self.jobs[self.active]) if self.active else None,
                    'pending_job':copy.deepcopy(self.jobs[self.pending]) if self.pending else None}

    def _physical(self,ident,record,threshold,suffix=''):
        pass_kind='baseline' if suffix=='_baseline' else 'selected'
        self._progress(ident,'preparing','Preparing registered PCM for '+pass_kind+' capture',pass_kind,threshold)
        entry=self.store.record(record)
        raw=self.store.pcm(record,padded=True).tobytes()
        folder=self.output_root/'hardware_jobs'/(ident+suffix)
        result=self.hardware.capture(raw,threshold,entry['input_sha256'],folder,
                  progress=lambda event:self._progress(ident,pass_kind=pass_kind,threshold=threshold,**event))
        self._progress(ident,'reference','Verifying every reconstructed sample and spectral packet on the PC',pass_kind,threshold)
        try:
            return self.store.register_capture(record,threshold,**result,capture_dir=self.output_root/'captures'/(ident+suffix))
        except Exception as exc:
            self.hardware.available=False
            self.hardware.message='Capture verification failed; explicit reconnect required: '+str(exc)
            save(folder/'reference_failure.json',{'status':'FAIL_REFERENCE_VERIFICATION','error':str(exc),'time':time.time()})
            raise

    def _work(self,job):
        ident,record,threshold=job['job_id'],job['source_id'],job['threshold']
        if not job['force']:
            try:
                capture=self.store.get_capture(record,threshold)
                self._progress(ident,'cached','Reusing a completed physical capture; no board transaction',threshold=threshold)
                self._progress(ident,'consumer','Preparing audio, charts and measured laptop comparisons from the saved capture',threshold=threshold)
                return self.store.get_bundle(capture['result_id'])
            except KeyError:pass
        need(self.hardware is not None and self.hardware.available,'Board is unavailable. Reconnect it, or select a recorded capture.')
        try:self.store.get_capture(record,0)
        except KeyError:
            baseline_id=self._physical(ident,record,0,'_baseline')
            if threshold==0:
                self._progress(ident,'consumer','Preparing synchronized audio, charts and measured laptop comparisons','baseline',0)
                return self.store.get_bundle(baseline_id)
        result_id=self._physical(ident,record,threshold)
        self._progress(ident,'consumer','Preparing synchronized audio, charts and measured laptop comparisons','selected',threshold)
        return self.store.get_bundle(result_id)

    def _worker(self):
        while True:
            with self.condition:
                self.condition.wait_for(lambda:self.pending is not None or self.closed)
                if self.closed and self.pending is None:return
                ident=self.pending;self.pending=None;self.active=ident
                self.jobs[ident].update(status='running',started_at=time.time(),message='Preparing requested result')
                self._progress(ident,'preparing','Preparing requested result')
                job=copy.deepcopy(self.jobs[ident])
            try:
                result=self._work(job)
                with self.condition:
                    self._progress(ident,'complete','Verified result ready')
                    self._update(ident,status='complete',result_id=result['result_id'],result_url='/api/results/'+result['result_id'])
            except Exception as exc:
                with self.condition:
                    self._progress(ident,'failed',str(exc))
                    self._update(ident,status='failed')
            finally:
                self._update(ident,finished_at=time.time())
                folder=self.output_root/'jobs';folder.mkdir(parents=True,exist_ok=True);save(folder/(ident+'.json'),self.get(ident))
                with self.condition:self.active=None;self.condition.notify_all()

    def close(self):
        with self.condition:
            self.closed=True
            if self.pending:
                self.jobs[self.pending].update(status='superseded',finished_at=time.time())
                self._progress(self.pending,'superseded','Server stopped before this request started');self.pending=None
            self.condition.notify_all()
        self.thread.join(timeout=80)

class App:
    def __init__(self,store,hardware=None,output_root=OUT):
        self.store=store;self.hardware=hardware;self.output_root=Path(output_root)
        self.token=secrets.token_urlsafe(32);self.queue=JobQueue(store,hardware,self.output_root)
        self.result_lookup={};self.initial_result=None;self.ready=time.time()
        self.restore_errors=[]
        restorations=[]
        for manifest in (self.output_root/'captures').glob('*/capture.json'):
            try:
                metadata=read(manifest)['physical_metadata']
                recorded=datetime.fromisoformat(metadata['recorded_at'].replace('Z','+00:00'))
                need(recorded.tzinfo is not None and recorded.utcoffset() is not None,'Capture timestamp must include a timezone')
                epoch=metadata['epoch'];need(type(epoch) is int and epoch>0,'Capture epoch must be a positive integer')
                restorations.append((recorded.astimezone(timezone.utc),epoch,str(manifest),manifest))
            except Exception as exc:self.restore_errors.append({'path':str(manifest),'error':str(exc)})
        # Random job IDs do not establish chronology. Restoring oldest first
        # leaves each source/threshold latest pointer at its newest capture.
        for _,_,_,manifest in sorted(restorations):
            try:store.restore_capture(manifest)
            except Exception as exc:self.restore_errors.append({'path':str(manifest),'error':str(exc)})
        # Register names lazily; decoding all recordings is not startup work.
        for key,row in store.actuals.items():
            if key[2]!=0:continue
            digest=row['sha256'][row['actual_wire_path']]
            result_id='recorded-'+row['capture_id']+'-'+digest[:10]
            self.result_lookup[result_id]=key
        try:self.initial_result=store.bundle('1-19898-A-41',10000000)['result_id']
        except KeyError:pass

    def board_status(self):
        return self.hardware.status() if self.hardware else {'available':False,'status':'Recorded-capture mode; no hardware admitted','checked_at':None}

    def config(self):
        with self.store.lock:
            result=self._config_locked()
        remote=getattr(self,'remote_gateway',None)
        result['remote']=remote.local_status() if remote else {'configured':False,'enabled':False}
        return result

    def _config_locked(self):
        cat=self.store.catalog();sources=[]
        for item in cat['records']:
            source=dict(item);rid=source['id'];cached=[]
            for threshold in source['thresholds']:
                latest=self.store.latest.get((rid,threshold))
                if latest:result_id=latest
                else:
                    keys=[ident for ident,key in self.result_lookup.items() if key==(rid,threshold,0)]
                    if not keys:continue
                    result_id=keys[0]
                cached.append({'threshold':threshold,'result_id':result_id})
            source.update(description=f'{source["kind"].title()} · {source["duration_seconds"]:.2f} seconds',
                          original_audio_url='/api/sources/'+rid+'/audio',cached_results=cached)
            sources.append(source)
        return {'sources':sources,'thresholds':THRESHOLDS,'board':self.board_status(),'csrf_token':self.token,
                'initial_source_id':'1-19898-A-41',
                'initial_result_url':'/api/results/'+self.initial_result if self.initial_result else None,
                'catalog':cat,'restore_errors':self.restore_errors,'version':'1.0',
                'scope':'Interactive buffered FPGA processing with playback-synchronized visualization. Threshold applies to a new complete transaction.'}

    def bundle(self,ident):
        with self.store.lock:
            return self._bundle_locked(ident)

    def _bundle_locked(self,ident):
        if ident not in self.store.result_captures:
            if ident not in self.result_lookup:raise KeyError('Unknown actual result')
            record,threshold,trial=self.result_lookup[ident]
            # Historical addresses stay tied to their original actual capture.
            key=(record,threshold,trial)
            latest=self.store.latest.pop((record,threshold),None)
            try:self.store.get_capture(record,threshold,trial)
            finally:
                if latest:self.store.latest[(record,threshold)]=latest
        return self.store.get_bundle(ident)

    def reconnect(self):
        with self.queue.condition:
            need(not self.queue.active and not self.queue.pending,'Wait for the queued captures to finish before reconnecting')
            need(self.hardware is not None,'No hardware deployment has been configured')
            return self.hardware.connect()

class Handler(BaseHTTPRequestHandler):
    protocol_version='HTTP/1.1'
    server_version='TRecapDemo/1.0'
    def log_message(self,*args):pass
    @property
    def app(self):return self.server.app
    def reply(self,status,data,mime='application/json; charset=utf-8',head=False):
        if not isinstance(data,bytes):data=json_bytes(data)
        self.send_response(status);self.send_header('Content-Type',mime);self.send_header('Content-Length',str(len(data)))
        self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff')
        self.send_header('Content-Security-Policy',"default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; connect-src 'self'; media-src 'self' blob:; img-src 'self' data:; object-src 'none'; frame-ancestors 'none'")
        self.end_headers()
        if not head:
            try:self.wfile.write(data)
            except (BrokenPipeError,ConnectionResetError):pass
    def valid_host(self):
        return self.headers.get('Host') in (f'127.0.0.1:{self.server.server_port}',f'localhost:{self.server.server_port}')
    def do_GET(self):
        try:
            need(self.valid_host(),'Invalid local Host header')
            path=urlparse(self.path).path
            if path in ('/','/index.html','/styles.css','/app.js','/pipeline.js'):
                target=WEB/('index.html' if path=='/' else path[1:])
                mime={'.html':'text/html; charset=utf-8','.css':'text/css; charset=utf-8','.js':'text/javascript; charset=utf-8'}[target.suffix]
                return self.reply(200,target.read_bytes(),mime)
            if path=='/api/config':return self.reply(200,self.app.config())
            if path=='/api/status':return self.reply(200,{'board':self.app.board_status(),**self.app.queue.status()})
            parts=path.strip('/').split('/')
            if len(parts)==3 and parts[:2]==['api','jobs']:return self.reply(200,self.app.queue.get(parts[2]))
            if len(parts)>=3 and parts[:2]==['api','results']:
                ident=parts[2];bundle=self.app.bundle(ident)
                if len(parts)==3:return self.reply(200,bundle)
                if len(parts)==5 and parts[3]=='audio':return self.reply(200,self.app.store.wav(ident,parts[4]),'audio/wav')
            if len(parts)==4 and parts[:2]==['api','sources'] and parts[3]=='audio':
                from data import make_wav
                record=self.app.store.record(parts[2]);pcm=self.app.store.pcm(parts[2],padded=False)
                pcm=pcm[:record.get('audio_ns',len(pcm))]
                return self.reply(200,make_wav(pcm,8),'audio/wav')
            self.reply(404,{'error':'Not found'})
        except KeyError as exc:self.reply(404,{'error':str(exc)})
        except ValueError as exc:self.reply(400,{'error':str(exc)})
        except Exception as exc:self.reply(500,{'error':str(exc)})
    def do_POST(self):
        try:
            need(self.valid_host(),'Invalid local Host header')
            need(secrets.compare_digest(self.headers.get('X-Demo-Token',''),self.app.token),'A valid local demo token is required')
            origin=self.headers.get('Origin')
            need(origin is None or origin in (f'http://127.0.0.1:{self.server.server_port}',f'http://localhost:{self.server.server_port}'),'Cross-origin requests are not accepted')
            need(self.headers.get('Transfer-Encoding') is None,'Chunked requests are not accepted')
            path=urlparse(self.path).path;length=int(self.headers.get('Content-Length','0'))
            maximum=32*1024*1024 if path=='/api/upload' else 4096
            need(0<length<=maximum,'Request body is missing or too large')
            self.connection.settimeout(15);raw=self.rfile.read(length);need(len(raw)==length,'Incomplete request body')
            if path=='/api/upload':
                need(self.headers.get('Content-Type','').split(';')[0] in ('audio/wav','audio/x-wav','application/octet-stream'),'Expected a WAV upload')
                filename=unquote(self.headers.get('X-Filename','upload.wav'))[:240]
                ident=self.app.store.register_wav(filename,raw)
                source=next(x for x in self.app.config()['sources'] if x['id']==ident)
                return self.reply(201,{'source_id':ident,'source':source})
            need(self.headers.get('Content-Type','').split(';')[0]=='application/json','Expected application/json')
            request=json.loads(raw);need(isinstance(request,dict),'Expected a JSON object')
            if path=='/api/shutdown':
                with self.app.queue.condition:
                    need(not self.app.queue.active and not self.app.queue.pending,'Wait for hardware work to finish before stopping the demo')
                    self.app.queue.closed=True
                    self.app.queue.condition.notify_all()
                self.reply(200,{'status':'stopping'})
                threading.Thread(target=self.server.shutdown,daemon=True).start()
                return
            if path=='/api/run':
                job=self.app.queue.submit(request.get('source_id'),request.get('threshold'),request.get('force',True))
                return self.reply(202,job)
            if path=='/api/remote-control':
                need(set(request)=={'enabled'} and type(request['enabled']) is bool,'Expected only enabled: boolean')
                need(getattr(self.app,'remote_gateway',None) is not None,'Remote gateway is not configured')
                return self.reply(200,self.app.remote_gateway.control(request['enabled']))
            if path=='/api/connect':return self.reply(200,{'board':self.app.reconnect()})
            self.reply(404,{'error':'Not found'})
        except QueueBusy as exc:
            self.close_connection=True;self.reply(409,{'error':str(exc)})
        except (KeyError,ValueError,TypeError,json.JSONDecodeError) as exc:
            self.close_connection=True;self.reply(400,{'error':str(exc)})
        except Exception as exc:
            self.close_connection=True;self.reply(500,{'error':str(exc)})

def main():
    p=argparse.ArgumentParser();p.add_argument('--port',type=int,default=8767);p.add_argument('--hardware-manifest',type=Path);p.add_argument('--recorded-only',action='store_true');p.add_argument('--remote-config',type=Path);a=p.parse_args()
    if a.remote_config:
        from remote_gateway import read_policy
        read_policy(a.remote_config)  # Fail before any startup board admission.
    from data import CaptureStore
    from hardware import Hardware
    store=CaptureStore();hw=None
    if not a.recorded_only:
        manifest=a.hardware_manifest
        if manifest is None and (OUT/'active_hardware.json').exists():
            active=read(OUT/'active_hardware.json');manifest=Path(active['manifest'])
            need(hashlib.sha256(manifest.read_bytes()).hexdigest()==active['manifest_sha256'],'Active hardware deployment changed')
        if manifest:
            hw=Hardware(manifest)
            try:hw.connect()
            except Exception as exc:print('Hardware unavailable: '+str(exc),flush=True)
    app=App(store,hw)
    server=ThreadingHTTPServer(('127.0.0.1',a.port),Handler);server.app=app
    server.daemon_threads=True
    remote=None
    if a.remote_config:
        from remote_gateway import RemoteGateway
        remote=RemoteGateway(app,a.remote_config)
        app.remote_gateway=remote
        remote.start()
    state={'status':'RUNNING_LOCAL_VISUALIZER','url':f'http://127.0.0.1:{server.server_port}','pid':__import__('os').getpid(),'started_at':time.time(),'board':app.board_status(),'remote':remote.local_status() if remote else {'configured':False,'enabled':False}}
    save(OUT/'server_state.json',state);print(json.dumps(state),flush=True)
    try:server.serve_forever(poll_interval=.2)
    finally:
        if remote:remote.close()
        server.server_close();app.queue.close();save(OUT/'server_state.json',{**state,'status':'STOPPED','stopped_at':time.time()})
if __name__=='__main__':main()
