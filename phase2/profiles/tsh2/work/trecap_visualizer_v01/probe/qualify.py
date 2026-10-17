from pathlib import Path
import hashlib,json
ROOT=Path(__file__).resolve().parents[3]
WORK=Path(__file__).resolve().parent
OUT=ROOT/'outputs/trecap_visualizer_v01/probe_build02'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
tests={}
for name in ('native_mock.json','arm_mock.json'):
    v=json.loads((OUT/name).read_text())
    assert v=={'status':'PASS_TSH2_PROBE_MOCK','register_cases':24,'source_parser_cases':3,'hardware_access':False,'writes_performed':False,'fifo_pop_performed':False}
    tests[name]=v
assert not (OUT/'qualification.json').exists()
binary=OUT/'tsh2_probe.arm'
sources=[WORK/n for n in ('tsh2_probe.c','build.sh','qualify.py','README.md')]
report={'status':'PASS_TSH2_READ_ONLY_PROBE_OFFBOARD','hardware_access':False,'binary_path':str(binary),'binary_sha256':sha(binary),
        'source_sha256':{str(p):sha(p) for p in sources},'build_evidence_sha256':{str(p):sha(p) for p in OUT.iterdir() if p.is_file()},'tests':tests,
        'limitations':['Root must first perform fresh HPS system-register and ownership admission.','Offline register mocks do not prove current hardware state.','Physical use requires an outer timeout; no automatic MMIO recovery.']}
(OUT/'qualification.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps({'status':report['status'],'binary_sha256':report['binary_sha256'],'qualification_sha256':sha(OUT/'qualification.json')}))
