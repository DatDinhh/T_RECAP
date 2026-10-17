"""Exactness, format and admission tests only; no timing trials or board writes."""
from pathlib import Path
import ctypes as C
import hashlib
import json
import struct
import tarfile
import numpy as np
from native_api import Native, FEATURE_COLUMNS

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
OUT=HERE/'build01'
evidence={}
def digest(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def bind(p,expected=None):
    p=Path(p).resolve();h=digest(p)
    if expected is not None: assert h==expected,str(p)
    evidence[str(p)]=h
    return p
def read(p): return json.loads(Path(p).read_text())
def affinity():
    class Group(C.Structure): _fields_=[('mask',C.c_size_t),('group',C.c_ushort),('reserved',C.c_ushort*3)]
    k=C.WinDLL('kernel32',use_last_error=True)
    k.GetCurrentThread.restype=C.c_void_p;k.GetThreadGroupAffinity.argtypes=[C.c_void_p,C.POINTER(Group)]
    g=Group();assert k.GetThreadGroupAffinity(k.GetCurrentThread(),C.byref(g))
    return {'mask':g.mask,'group':g.group}
def reference(d):
    out=np.zeros((len(d),21),dtype=np.uint64)
    for f,row in enumerate(d):
        total=weighted=peak=0;peakbin=(1<<64)-1;bands=[0]*16
        for k,v in enumerate(row):
            v=int(v);w=v if k in (0,128) else 2*v
            bands[16*k//129]+=w;total+=w;weighted+=k*w
            if v>peak:peak=v;peakbin=k
        out[f,:16]=bands;out[f,16]=total;out[f,17]=weighted&((1<<64)-1)
        out[f,18]=peak;out[f,19]=peakbin;out[f,20]=weighted>>64
    return out
def checksum(b):
    h=14695981039346656037
    for i,v in enumerate(b):
        if not 40<=i<48:h=((h^v)*1099511628211)&((1<<64)-1)
    return h
def sparse_packet(row,thr=0):
    entries=[(k,int(v)) for k,v in enumerate(row) if k==0 or int(v)>=thr]
    b=bytearray((48+8*len(entries)+7)&~7)
    struct.pack_into('<IHHIIQQHHI',b,0,0x31505354,1,1,0x10001,8*len(entries),0,thr,len(entries),1,0)
    for i,(k,v) in enumerate(entries):struct.pack_into('<Q',b,48+8*i,(v<<8)|k)
    struct.pack_into('<Q',b,40,checksum(b));return bytes(b)
def main():
    assert not (OUT/'qualification.json').exists(),'Fresh qualification required'
    for p in [HERE/'dll.cpp',HERE/'native_api.py',HERE/'build.ps1',HERE/'qualify.py',
              ROOT/'work/trecap_laptop_fpga_v01/cpu/shared.hpp',
              *[ROOT/'work/trecap_downstream8_v01/native'/n for n in ['codec.hpp','codec.cpp']],
              OUT/'trecap_monitor.dll',OUT/'build.log',OUT/'build_command.txt']:bind(p)
    cpu=read(bind(ROOT/'outputs/trecap_cpu_fpga_bench_v01/cpu02_build01/qualification.json'))
    assert cpu['status']=='PASS_EXACT_CPU02_NATIVE_AND_ARM_QEMU'
    for name in ['main.cpp','kernel.hpp']:
        p=ROOT/'work/trecap_cpu_fpga_bench_v01/cpu02'/name;bind(p,cpu['source_sha256'][str(p)])
    prov=read(bind(ROOT/'outputs/trecap_stream8_v01/physical_provenance.json'))
    assert prov['status']=='PASS_PHYSICAL_CONTINUOUS_8S_ROUNDTRIP'
    arc=ROOT/'outputs/trecap_stream8_v01/results01.tar.gz';bind(arc,prov['evidence_sha256'][str(arc)])
    fixtures=read(bind(ROOT/'outputs/trecap_stream8_v01/fixtures02/cases.json'))
    input_path=bind(fixtures['input_i32le'],fixtures['input_sha256'])
    coeff=input_path.parent/'coefficients'
    for p in coeff.glob('*.memh'):bind(p)
    pcm=np.fromfile(input_path,dtype='<i4')
    before=affinity();cases=[];negatives=[]
    with Native(coeff,384000) as native,tarfile.open(arc) as archive:
        for case in fixtures['cases']:
            thr=case['threshold'];wire=archive.extractfile(case['case_id']+'_sparse.tsp1').read()
            assert hashlib.sha256(wire).hexdigest()==case['packets']['sparse']['sha256']
            a=native.produce(pcm,thr);b=native.prepare(wire,thr,3001)
            gold=reference(b['spectra'])
            assert a['wire']==wire and np.array_equal(a['spectra'],b['spectra'])
            assert np.array_equal(a['features'],gold) and np.array_equal(b['features'],gold)
            assert np.array_equal(native.decode(wire,thr,3001),gold)
            assert np.array_equal(native.decode(b['wire'],thr,3001,'dense'),gold)
            assert np.array_equal(native.run_pcm(pcm,thr),gold)
            assert np.array_equal(native.consume_dense(b['spectra']),gold)
            dense=case['packets']['dense'];assert b['wire']==bind(dense['path'],dense['sha256']).read_bytes()
            old=np.loadtxt(bind(case['expected_features']),delimiter=',',skiprows=1,dtype=np.uint64)[:,1:]
            assert np.array_equal(gold[:,:16],old)
            assert len(b['wire'])==952*3001 and not np.any(gold[:,20])
            cases.append({'case_id':case['case_id'],'threshold':thr,'frames':3001,
                          'sparse_bytes':len(wire),'compact_dense_bytes':len(b['wire']),
                          'features_sha256':hashlib.sha256(gold.tobytes()).hexdigest(),
                          'old_actual_wire_and_bands_match':True,'all_monitor_routes_match_bigint_reference':True})
        rows=[np.zeros(129,dtype=np.uint64),np.full(129,(1<<56)-1,dtype=np.uint64)]
        tie=np.zeros(129,dtype=np.uint64);tie[4]=tie[90]=555;rows.append(tie)
        endpoints=np.zeros(129,dtype=np.uint64);endpoints[0]=13;endpoints[128]=17;rows.append(endpoints)
        for i,row in enumerate(rows):
            wire=sparse_packet(row);prep=native.prepare(wire,0,1);gold=reference(row[None,:])
            assert np.array_equal(prep['features'],gold)
            assert np.array_equal(native.decode(prep['wire'],0,1,'dense'),gold)
            assert np.array_equal(native.consume_dense(row[None,:]),gold)
        assert reference(rows[1][None,:])[0,20]>0
        assert reference(rows[0][None,:])[0,19]==(1<<64)-1
        assert reference(tie[None,:])[0,19]==4
        def reject(label,fn):
            try:fn()
            except (RuntimeError,ValueError,TypeError):negatives.append(label)
            else:raise AssertionError('Accepted invalid '+label)
        base=sparse_packet(rows[1]);dense=native.prepare(base,0,1)['wire']
        def damaged(data,offset,value,size=1,fix=False):
            b=bytearray(data);b[offset:offset+size]=int(value).to_bytes(size,'little')
            if fix:struct.pack_into('<Q',b,40,checksum(b))
            return bytes(b)
        for label,offset,value,size in [('magic',0,0,4),('version',4,2,2),('encoding',6,0,2),
                                       ('configuration',8,0,4),('payload_length',12,0,4),('frame',16,1,8),
                                       ('threshold',24,1,8),('count',32,0,2),('flags',34,0,2),('reserved',36,1,4),
                                       ('index_out_of_range',48,255,1),('duplicate_index',56,0,1),('missing_dc',48,1,1)]:
            reject(label,lambda o=offset,v=value,s=size:native.decode(damaged(base,o,v,s,True),0,1))
        reject('checksum',lambda:native.decode(damaged(base,40,0,8),0,1))
        reject('truncated',lambda:native.decode(base[:-1],0,1))
        reject('trailing',lambda:native.decode(base+b'\0'*8,0,1))
        reject('wrong_expected_encoding',lambda:native.decode(base,0,1,'dense'))
        reject('dense_padding',lambda:native.decode(damaged(dense,951,1,1,True),0,1,'dense'))
        reject('dense_count',lambda:native.decode(damaged(dense,32,128,2,True),0,1,'dense'))
        b=bytearray(dense);struct.pack_into('<Q',b,24,100);b[55:62]=(1).to_bytes(7,'little');struct.pack_into('<Q',b,40,checksum(b))
        reject('dense_below_threshold',lambda:native.decode(bytes(b),100,1,'dense'))
        sparse100=sparse_packet(rows[1],100)
        reject('sparse_below_threshold',lambda:native.decode(damaged(sparse100,56,(1<<8)|1,8,True),100,1))
        zero_partial=sparse_packet(rows[0],1)
        reject('threshold0_missing_bins',lambda:native.decode(damaged(zero_partial,24,0,8,True),0,1))
        reject('bad_threshold',lambda:native.run_pcm(pcm,-1))
        reject('overflow_threshold',lambda:native.run_pcm(pcm,1<<56))
        reject('not_multiple128',lambda:native.run_pcm(pcm[:127],0))
        reject('empty_pcm',lambda:native.run_pcm(pcm[:0],0))
        reject('outside_signed12',lambda:native.run_pcm(np.full(128,2048,dtype=np.int32),0))
        reject('wrong_pcm_dtype',lambda:native.run_pcm(pcm.astype(np.int64),0))
        reject('matrix_mag_overflow',lambda:native.consume_dense(np.full((1,129),1<<56,dtype=np.uint64)))
        reject('invalid_encoding',lambda:native.decode(base,0,1,'foo'))
        reject('frames_capacity',lambda:native.decode(base,0,3002))
        assert native.lib.tsm_pcm(None,None,0,0,0)==-1;negatives.append('null_context')
    after=affinity();assert before==after
    result={'status':'PASS_EXACT_MONITOR_NATIVE_AND_STRICT_COMPACT_CODEC',
            'feature_columns':FEATURE_COLUMNS,'cases':cases,
            'bigint_edge_cases':['all_zero','all_uint56_max','peak_lower_index_tie','DC_Nyquist_unit_weights'],
            'negative_checks':negatives,'affinity_before':before,'affinity_after':after,
            'no_new_board_execution':True,'evidence_sha256':evidence}
    (OUT/'qualification.json').write_text(json.dumps(result,indent=2,allow_nan=False)+'\n')
    print(json.dumps({'status':result['status'],'actual_capture_cases':len(cases),'negative_checks':len(negatives),'affinity_unchanged':True}),flush=True)
if __name__=='__main__':main()
