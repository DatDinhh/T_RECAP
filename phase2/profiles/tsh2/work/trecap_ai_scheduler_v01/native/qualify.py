"""Offline exact-output qualification only; no performance trials or hardware."""
from pathlib import Path
import ctypes as C
import hashlib
import json
import tarfile
import numpy as np
from native_api import Native

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
OUT = HERE / 'build01'
def sha(data): return hashlib.sha256(data).hexdigest()
def digest(path): return sha(Path(path).read_bytes())
def read(path): return json.loads(Path(path).read_text())
evidence = {}
def bind(path, expected=None):
    path = Path(path).resolve()
    actual = digest(path)
    if expected is not None: assert actual == expected, str(path)
    evidence[str(path)] = actual
    return path
def bands(path):
    bind(path)
    table = np.loadtxt(path, delimiter=',', skiprows=1, dtype=np.uint64)
    assert np.array_equal(table[:, 0], np.arange(len(table), dtype=np.uint64))
    return table[:, 1:].copy()
def affinity():
    class Group(C.Structure):
        _fields_ = [('mask', C.c_size_t), ('group', C.c_ushort), ('reserved', C.c_ushort * 3)]
    k = C.WinDLL('kernel32', use_last_error=True)
    k.GetCurrentThread.restype = C.c_void_p
    k.GetThreadGroupAffinity.argtypes = [C.c_void_p, C.POINTER(Group)]
    result = Group()
    assert k.GetThreadGroupAffinity(k.GetCurrentThread(), C.byref(result))
    return {'mask': result.mask, 'group': result.group}

def main():
    assert not (OUT / 'qualification.json').exists(), 'Fresh qualification required'
    cpu_path = bind(ROOT / 'outputs/trecap_cpu_fpga_bench_v01/cpu02_build01/qualification.json')
    cpu = read(cpu_path)
    assert cpu['status'] == 'PASS_EXACT_CPU02_NATIVE_AND_ARM_QEMU'
    for filename in ['main.cpp', 'kernel.hpp']:
        p = ROOT / 'work/trecap_cpu_fpga_bench_v01/cpu02' / filename
        bind(p, cpu['source_sha256'][str(p)])
    for p in [HERE/'dll.cpp', HERE/'native_api.py', HERE/'build.ps1', HERE/'qualify.py',
              ROOT/'work/trecap_laptop_fpga_v01/cpu/shared.hpp',
              *[ROOT/'work/trecap_downstream8_v01/native'/n for n in ['codec.hpp','codec.cpp','consumer.cpp']],
              OUT/'trecap_scheduler.dll', OUT/'build.log', OUT/'build_command.txt']:
        bind(p)
    prov = read(bind(ROOT/'outputs/trecap_stream8_v01/physical_provenance.json'))
    assert prov['status'] == 'PASS_PHYSICAL_CONTINUOUS_8S_ROUNDTRIP'
    report_path = ROOT/'outputs/trecap_stream8_v01/physical_validation01/report.json'
    archive_path = ROOT/'outputs/trecap_stream8_v01/results01.tar.gz'
    for p in [report_path, archive_path]: bind(p, prov['evidence_sha256'][str(p)])
    physical = read(report_path)
    assert physical['status'] == 'PASS_EXACT_DOWNLOADED_CONTENT'
    fixtures = read(bind(ROOT/'outputs/trecap_stream8_v01/fixtures02/cases.json'))
    input_path = bind(fixtures['input_i32le'], fixtures['input_sha256'])
    pcm = np.fromfile(input_path, dtype='<i4')
    coeff = input_path.parent/'coefficients'
    for p in coeff.glob('*.memh'): bind(p)
    before = affinity()
    results, negatives = [], []
    with Native(coeff, 3072000) as native, tarfile.open(archive_path) as archive:
        def check(case, samples, y_gold, wire_gold, label):
            expected = bands(case['expected_features'])
            full = native.run_full(samples, case['threshold'])
            assert full['y'].tobytes() == y_gold, label+' Y'
            assert full['wire'] == wire_gold, label+' TSP1'
            assert np.array_equal(full['bands'], expected), label+' full bands'
            assert np.array_equal(native.run_spectral(samples, case['threshold']), expected), label+' spectral bands'
            assert native.lib.tsa_y_count(native.handle) == 0 and native.lib.tsa_tsp1_bytes(native.handle) == 0
            assert np.array_equal(native.decode(wire_gold, case['threshold'], len(expected)), expected), label+' sparse decode'
            dense = case['packets']['dense']
            dense_bytes = bind(dense['path'], dense['sha256']).read_bytes()
            assert np.array_equal(native.decode(dense_bytes, case['threshold'], len(expected)), expected), label+' dense decode'
            results.append({'case_id':label, 'threshold':case['threshold'], 'samples':len(samples),
                            'frames':len(expected), 'y_sha256':sha(y_gold), 'wire_sha256':sha(wire_gold),
                            'bands_sha256':sha(expected.tobytes()), 'full_spectral_dense_sparse_exact':True})
        for case in fixtures['cases']:
            if case['threshold'] not in (0,100000000): continue
            name = case['case_id']+'_sparse'
            y = archive.extractfile(name+'.y.i32le').read()
            wire = archive.extractfile(name+'.tsp1').read()
            prior = next(c for c in physical['cases'] if c['case_id']==case['case_id'] and c['sparse'])
            assert sha(y)==prior['y_sha256']==case['y_sha256']
            assert sha(wire)==prior['wire_sha256']==case['packets']['sparse']['sha256']
            check(case, pcm, y, wire, name+'_actual_fpga')
        small = read(bind(ROOT/'outputs/trecap_hps_transport_v01/fixtures01/cases.json'))
        for case in small['cases']:
            if case['source_offset_samples'] != 192000 or case['threshold'] not in (0,100000000): continue
            samples = np.fromfile(bind(case['input_i32le'],case['input_sha256']), dtype='<i4')
            check(case,samples,bind(case['y_i32le'],case['y_sha256']).read_bytes(),
                  bind(case['packets']['sparse']['path'],case['packets']['sparse']['sha256']).read_bytes(),case['case_id'])
        # New 64-second software-only case checks dynamic bounds and all three routes.
        # It is deliberately not represented as a fresh FPGA validation.
        long_pcm = np.tile(pcm,8)
        long_full = native.run_full(long_pcm,100000000)
        assert len(long_full['y'])==3072512 and long_full['bands'].shape==(24001,16)
        assert np.array_equal(native.run_spectral(long_pcm,100000000),long_full['bands'])
        assert np.array_equal(native.decode(long_full['wire'],100000000,24001),long_full['bands'])
        results.append({'case_id':'flute_repeated64s_software_consistency_only','samples':3072000,'frames':24001,
                        'full_spectral_decode_exact':True,'y_sha256':sha(long_full['y'].tobytes()),
                        'wire_sha256':sha(long_full['wire']),'bands_sha256':sha(long_full['bands'].tobytes())})
        def rejection(label, fn):
            try: fn()
            except (RuntimeError,ValueError,TypeError): negatives.append(label)
            else: raise AssertionError('accepted invalid '+label)
        rejection('zero_samples',lambda:native.run_full(np.zeros(0,dtype=np.int32),0))
        rejection('non_multiple128',lambda:native.run_full(np.zeros(127,dtype=np.int32),0))
        rejection('outside_signed12',lambda:native.run_full(np.full(128,2048,dtype=np.int32),0))
        rejection('negative_threshold',lambda:native.run_spectral(pcm,-1))
        rejection('threshold_56bit_overflow',lambda:native.run_spectral(pcm,1<<56))
        assert native.lib.tsa_full(None,None,0,0) == -1
        negatives.append('native_null_context')
        sparse0 = archive.extractfile('flute8s_thr0_sparse.tsp1').read()
        rejection('truncated_wire',lambda:native.decode(sparse0[:-1],0,3001))
        rejection('trailing_bytes',lambda:native.decode(sparse0+b'\0'*8,0,3001))
        rejection('wrong_expected_threshold',lambda:native.decode(sparse0,100000000,3001))
        def damaged(offset,value,size=1,fix_checksum=False):
            b=bytearray(sparse0); b[offset:offset+size]=value.to_bytes(size,'little')
            if fix_checksum:
                length=(48+int.from_bytes(b[12:16],'little')+7)&~7
                h=14695981039346656037
                for j in range(length):
                    if not 40<=j<48: h=((h^b[j])*1099511628211)&((1<<64)-1)
                b[40:48]=h.to_bytes(8,'little')
            return bytes(b)
        for label,offset,value,size in [('magic',0,0,4),('version',4,2,2),('encoding',6,2,2),
                ('config',8,2,4),('frame_order',16,1,8),('threshold',24,1,8),('flags',34,0,2),
                ('reserved',36,1,4),('dc_missing',48,1,1),('duplicate_index',56,0,1)]:
            packet=damaged(offset,value,size,True)
            rejection(label,lambda packet=packet:native.decode(packet,0,3001))
            assert native.lib.tsa_frames(native.handle)==0 and not native.lib.tsa_features(native.handle)
        corrupt=damaged(60,255)
        rejection('checksum',lambda:native.decode(corrupt,0,3001))
        expected0=bands(fixtures['cases'][0]['expected_features'])
        assert np.array_equal(native.decode(sparse0,0,3001),expected0)
    assert affinity()==before, 'Thread affinity changed'
    for path,expected in evidence.items(): assert digest(path)==expected, 'Source changed during qualification'
    output={'status':'PASS_EXACT_NATIVE_FULL_SPECTRAL_AND_DECODE','hardware_used':False,'benchmark_run':False,
            'dll':str(OUT/'trecap_scheduler.dll'),'dll_sha256':digest(OUT/'trecap_scheduler.dll'),
            'abi':65536,'results':results,'negative_checks':negatives,'negative_check_count':len(negatives),
            'affinity_before_after':before,'affinity_unchanged':True,'evidence_sha256':evidence,
            'limits':['8-second full output validated against existing actual FPGA captures at0 and1e8.',
                      '64-second case checks software consistency only; no new FPGA/generalized hardware claim.',
                      'No model execution or performance measurement; output copies included by Python API.']}
    (OUT/'qualification.json').write_text(json.dumps(output,indent=2)+'\n')
    print(json.dumps({'status':output['status'],'cases':len(results),'negative_checks':len(negatives),'dll_sha256':output['dll_sha256']}))

if __name__=='__main__': main()
