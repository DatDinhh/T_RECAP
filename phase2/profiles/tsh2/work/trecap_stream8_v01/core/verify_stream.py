"""Bounded actual-core regression with arbitrary host/output pauses, no FPGA build."""
from pathlib import Path
import csv,hashlib,json,shutil,subprocess,time,sys
ROOT=Path(__file__).resolve().parents[3]
WORK=Path(__file__).resolve().parent
BUILD=ROOT/'outputs/trecap_hps_transport_v01/build01'
FIX=ROOT/'outputs/trecap_hps_transport_v01/fixtures01'
SIM=Path('D:/Quartus20.1.1/QuartusFPGA/modelsim_ase/win32aloem')
OUT=WORK/(sys.argv[1] if len(sys.argv)>1 else 'verification01')
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
    OUT.mkdir(exist_ok=False)
    shutil.copytree(BUILD/'artifacts/coefficients',OUT/'artifacts/coefficients')
    sources=[]
    for line in (ROOT/'outputs/trecap_jtag_readback_v01/build01/trecap_sparse_board.qsf').read_text().splitlines():
        prefix='set_global_assignment -name SYSTEMVERILOG_FILE '
        if line.startswith(prefix):
            rel=line[len(prefix):]
            if rel.startswith('source/'):sources.append(BUILD/rel)
    sources += [BUILD/'generated/trecap_core_export_observed.sv',BUILD/'generated/trecap_spectral_exporter.sv']
    sources += [WORK/name for name in ('trecap_pcm_stream_source.sv','trecap_pcm_stream_top.sv','stream_tb.sv')]
    hashes={str(p):sha(p) for p in sources}
    def invoke(name,args,timeout=240):
        args=[str(a).replace('\\','/') for a in args]
        start=time.monotonic()
        with (OUT/(name+'.log')).open('w') as log:
            result=subprocess.run(args,cwd=OUT,stdout=log,stderr=subprocess.STDOUT,timeout=timeout)
        if result.returncode:raise RuntimeError(name+' failed: '+str(OUT/(name+'.log')))
        print(name,round(time.monotonic()-start,2),flush=True)
    invoke('vlib',[SIM/'vlib.exe','work']);invoke('vmap',[SIM/'vmap.exe','-c'])
    invoke('compile',[SIM/'vlog.exe','-sv','-warning','2892','-work','work','+define+SYNTHESIS']+sources)
    invoke('simulate',[SIM/'vsim.exe','-c','-voptargs=+acc','work.stream_tb','+OUT='+str(OUT),'+CASES='+str(FIX/'tb_cases.txt'),
        '-do','onerror {quit -code 1}; onbreak {quit -code 1}; run -all; quit -code 0'])
    log=(OUT/'simulate.log').read_text();assert 'PASS stream epochs=12' in log and 'Fatal:' not in log
    cases=json.loads((FIX/'cases.json').read_text())['cases']
    taps={i:[] for i in range(12)}
    for row in csv.DictReader((OUT/'taps.csv').open()):taps[int(row['phase'])].append(row)
    for phase in range(12):
        case=cases[phase//2];gold=list(csv.DictReader(Path(case['bin_stats']).open()))
        assert len(taps[phase])==len(gold)==1161
        for actual,expected in zip(taps[phase],gold):
            for field in ('frame_idx','bin_idx','real','imag','mag2','pre_mask','mask','eligible'):
                assert int(actual[field])==int(expected[field]),(phase,field)
            assert int(actual['threshold'])==case['threshold']
    assert all(sha(Path(p))==value for p,value in hashes.items())
    report={'status':'PASS','epochs':12,'input_samples':12288,'full_tail_y_samples':18432,
        'canonical_tap_rows':13932,'source_hashes':hashes,
        'coverage':next(line for line in log.splitlines() if 'PASS stream epochs=12' in line),
        'limitations':['1024-sample regression geometry;384000-sample full8-second simulation not performed.',
            'No FPGA compile, timing, programming, or physical execution.']}
    (OUT/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    print(report['coverage'],flush=True)
if __name__=='__main__':main()
