"""Actual warm-RAM CPU routes; physical capture and transfer are not timed."""
import sys,time,math,csv,platform
sys.dont_write_bytecode=True
import numpy as np
from common import WORK,OUT,NATIVE,COEFF,need,read,save,sha,fresh,verify
from monitor import monitor,serial
from telemetry import encode,validate
sys.path.insert(0,str(NATIVE))
from native_api import Native

ROUTES=['native_sparse','native_dense','native_cpu_pcm','receiver_sparse','receiver_dense','cpu_pcm_monitor']

def main():
    cal=read(OUT/'calibration01/calibration.json');q=read(OUT/'quality01/quality.json');idx=read(OUT/'inputs01/index.json')
    need(q['status']=='PASS_HELDOUT_EVALUATION','Completed quality')
    need(q['calibration_sha256']==sha(OUT/'calibration01/calibration.json'),'Same selected threshold')
    need(cal['input_index_sha256']==sha(OUT/'inputs01/index.json'),'Same inputs')
    verify(cal['sources_sha256']);out=fresh(OUT/'timing01');threshold=cal['threshold']
    native=Native(COEFF,384000);data=[]
    for r in q['results']:
        e=next(e for e in idx['records'] if e['id']==r['id']);c=next(c for c in r['cases'] if c['threshold']==threshold)
        verify(c['sha256']);need(sha(e['pcm'])==e['sha256'],'Input changed')
        from pathlib import Path
        data.append({'id':r['id'],'category':r['category'],'pcm':np.load(e['pcm'],allow_pickle=False),
                     'features':np.load(c['files']['features.npy'],allow_pickle=False),
                     'sparse':Path(c['files']['sparse.tsp1']).read_bytes(),'dense':Path(c['files']['dense.tsp1']).read_bytes(),
                     'monitor':read(c['files']['monitor.json']),'ns':e['ns'],'frames':c['frames']})
    need(len(data)==4,'Four held-out clips')
    def operation(route,d):
        if route in ('native_cpu_pcm','cpu_pcm_monitor'):f=native.run_pcm(d['pcm'],threshold)
        else:
            enc='sparse' if route.endswith('sparse') else 'dense'
            f=native.decode(d[enc],threshold,d['frames'],enc)
        return f if route.startswith('native_') else monitor(f,d['ns'])
    def check(route,got,d):
        if route.startswith('native_'):need(np.array_equal(got,d['features']),'Timed native output equality')
        else:need(serial(got)==d['monitor'],'Timed complete monitor equality')
    batch={};pilots=[]
    for d in data:
        for route in ROUTES:
            measured=[]
            for _ in range(2):
                t=time.perf_counter_ns();got=operation(route,d);elapsed=time.perf_counter_ns()-t
                check(route,got,d);measured.append(elapsed)
            minimum=min(measured)/1e9
            count=min(256,2**max(0,math.ceil(math.log2(.1/max(minimum,1e-9)))))
            batch[(d['id'],route)]=count
            pilots.append({'recording':d['id'],'route':route,'pilot_ns':measured,'repetitions':count})
    telemetry=[]
    for d in data:
        m=monitor(d['features'],d['ns']);wire=encode(m);validate(wire,m)
        p=out/(d['id']+'_summary.tsm1');p.write_bytes(wire)
        telemetry.append({'recording':d['id'],'groups':len(m['ends']),'bytes':len(wire),'path':str(p),'sha256':sha(p),
                          'source':'CPU_TASK_SPECIFIC_SUMMARY_NOT_CURRENT_FPGA_OUTPUT','encode_time_measured':False})
    save(out/'registration.json',{'calibration_sha256':sha(OUT/'calibration01/calibration.json'),
         'quality_sha256':sha(OUT/'quality01/quality.json'),'input_index_sha256':sha(OUT/'inputs01/index.json'),
         'routes':ROUTES,'threshold':threshold,'recordings':[d['id'] for d in data],
         'warmups':3,'trials':30,'pilots':pilots,'waveform_source':'SOFTWARE_REFERENCE_NOT_NEW_FPGA_CAPTURE',
         'boundary':'RAM input to copied feature outputs or complete monitor; no DSP producer in cached receiver routes; no transport/disk/context construction.',
         'telemetry':telemetry,'telemetry_encoding_timed':False})
    rows=[]
    with (out/'raw_trials.csv').open('w',newline='',encoding='utf-8') as file:
        fields=['trial','warmup','recording','route','order','repetitions','wall_batch_ns','cpu_batch_ns','wall_ns_per_clip','cpu_ns_per_clip']
        writer=csv.DictWriter(file,fieldnames=fields);writer.writeheader()
        for trial in range(-3,30):
            j=trial+3;order_data=data if j%2==0 else data[::-1]
            for i,d in enumerate(order_data):
                routes=ROUTES if (i+j)%2==0 else ROUTES[::-1];shift=(i+j)%len(routes)
                routes=routes[shift:]+routes[:shift]
                for pos,route in enumerate(routes):
                    count=batch[(d['id'],route)];ct=time.process_time_ns();wt=time.perf_counter_ns()
                    for _ in range(count):got=operation(route,d)
                    elapsed=time.perf_counter_ns()-wt;cpu=time.process_time_ns()-ct
                    check(route,got,d)
                    row={'trial':trial,'warmup':int(trial<0),'recording':d['id'],'route':route,'order':pos,
                         'repetitions':count,'wall_batch_ns':elapsed,'cpu_batch_ns':cpu,
                         'wall_ns_per_clip':elapsed/count,'cpu_ns_per_clip':cpu/count}
                    writer.writerow(row);rows.append(row)
            file.flush()
            if trial<0 or trial%5==4:print('TIMING '+str(trial)+' PASS',flush=True)
    need(len(rows)==792,'Complete33x4x6 matrix');verify(cal['sources_sha256']);native.close()
    save(out/'validation.json',{'status':'PASS_ACTUAL_SPECTRAL_MONITOR_TIMING','observations':len(rows),
         'measured_observations':sum(r['warmup']==0 for r in rows),'every_output_checked':True,
         'raw_trials_sha256':sha(out/'raw_trials.csv'),'threshold':threshold,'sources_unchanged':True,
         'new_physical_captures':False,'python':platform.python_version(),'platform':platform.platform(),
         'zero_cpu_batches':sum(r['cpu_batch_ns']==0 for r in rows),'minimum_batch_wall_ns':min(r['wall_batch_ns'] for r in rows)})
    print('BENCHMARK PASS',flush=True)

if __name__=='__main__':main()
