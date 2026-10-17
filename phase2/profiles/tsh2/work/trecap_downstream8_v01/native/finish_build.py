"""Retry installed MSVC outside sandbox SDK-read failure, then validation only."""
from build import HERE,ROOT,OUT,OLD,sha,save
import json,subprocess,time
def main():
    target=OUT/'receipt_attempt02.json';assert not target.exists()
    sources={p.name:sha(p) for p in HERE.iterdir() if p.is_file()}
    for n in ('codec.hpp','codec.cpp','consumer.cpp','observer.cpp','codec_selftest_main.cpp'):
        assert sha(HERE/n)==sha(OLD/('main.cpp' if n=='codec_selftest_main.cpp' else n))
    r={'status':'RUNNING','sources_sha256':sources,'preserved_initial_failure_sha256':sha(OUT/'receipt.json'),'commands':[]}
    def run(name,argv,timeout=180):
        row={'name':name,'argv':[str(x) for x in argv]};r['commands'].append(row);start=time.monotonic()
        with (OUT/(name+'.log')).open('xb') as f:p=subprocess.run(row['argv'],stdout=f,stderr=subprocess.STDOUT,timeout=timeout)
        row.update(returncode=p.returncode,elapsed_s=time.monotonic()-start,log_sha256=sha(OUT/(name+'.log')));save(target,r);assert p.returncode==0,name
    try:
        cmake='C:/Program Files/CMake/bin/cmake.exe'
        run('configure02',[cmake,'-S',HERE,'-B',OUT/'cmake','-G','Visual Studio 17 2022','-A','x64'])
        run('build02',[cmake,'--build',OUT/'cmake','--config','Release','--parallel','2'])
        run('codec_selftest',[OUT/'cmake/Release/codec_selftest.exe','--self-test'])
        exe=OUT/'cmake/Release/trecap_downstream8.exe'
        run('validation',[exe,'--cases',ROOT/'outputs/trecap_downstream8_v01/inputs01/cases.tsv','--out',OUT/'validation01','--validate-only'])
        assert 'VALIDATE_ONLY PASS' in (OUT/'validation.log').read_text()
        assert all(sha(HERE/n)==h for n,h in sources.items())
        r.update(status='PASS_BUILD_SELFTEST_VALIDATION_NO_TIMING',exe_path=str(exe),exe_sha256=sha(exe),validation_metadata_sha256=sha(OUT/'validation01/metadata.json'))
    except Exception as e:r.update(status='FAIL',error=str(e));raise
    finally:save(target,r)
    print(json.dumps(r))
if __name__=='__main__':main()
