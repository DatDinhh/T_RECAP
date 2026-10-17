from pathlib import Path
import json,hashlib
ROOT=Path(__file__).resolve().parents[3]
WORK=ROOT/'work/trecap_laptop_fpga_v01/service'
OUT=ROOT/'outputs/trecap_laptop_fpga_v01/service_build01'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def need(ok,msg):
    if not ok:raise RuntimeError(msg)
parent=ROOT/'work/trecap_cpu_fpga_bench_v01/host02/tsh2_client.c'
need(sha(parent)=='36e2805f050fbd3635f536933f23fceb81567ff2824437786a04ff219020074a','frozen controller changed')
tests={}
for name in ('native_mock.jsonl','arm_mock.jsonl'):
    rows=[json.loads(s) for s in (OUT/name).read_text().splitlines()]
    need(len(rows)==2 and rows[0]['status']=='PASS_OFFBOARD_REGISTER_MOCK' and rows[0]['tests']==13 and rows[1]['status']=='PASS_SOCKETPAIR_FRAMING_AND_FULL_OUTPUT' and rows[1]['cases']==5,'mock qualification')
    tests[name]=rows
sources=[parent,WORK/'service.c',WORK/'build.sh',WORK/'PROTOCOL.md',Path(__file__).resolve()]
binary=OUT/'service.arm'
need(not (OUT/'qualification.json').exists(),'fresh qualification')
report={'status':'PASS_FINITE_TCP_SERVICE_OFFLINE','binary_path':str(binary),'binary_sha256':sha(binary),'hardware_access':False,'network_access':False,
 'source_sha256':{str(p):sha(p) for p in sources},'build_evidence_sha256':{str(p):sha(p) for p in OUT.iterdir() if p.is_file()},'tests':tests,
 'frozen_controller_unchanged':True,'request_header':'<IQI magic0x31515254 threshold inputbytes1536000','reply_header':'<IIIIQQQ magic0x31535254 status ybytes tspbytes epoch wallns threadns',
 'client_shutdown_write_required':True,'max_requests':165,'bind':'169.254.196.128:18082','idle_upload_reply_deadline_seconds':10,'request_alarm_seconds':60,
 'compiler':(OUT/'compiler.txt').read_text().splitlines()[0],'flags':(OUT/'flags.txt').read_text().splitlines(),
 'limitations':['Mock sockets only; no physical timer/affinity/network result.','Board timer remains resident-PCM controller interval; laptop end-to-end transport timer must use laptop clock.']}
(OUT/'qualification.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps({'status':report['status'],'binary_sha256':report['binary_sha256'],'qualification_sha256':sha(OUT/'qualification.json')}))
