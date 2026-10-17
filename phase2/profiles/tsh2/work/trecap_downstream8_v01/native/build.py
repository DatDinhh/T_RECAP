"""Build and self-test packet-input runner; never starts timing trials."""
from pathlib import Path
import hashlib,json,subprocess,time
HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
OUT=ROOT/'outputs/trecap_downstream8_v01/build01'
OLD=ROOT/'work/trecap_sparse_consumer_v01/native'
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def save(p,obj):p.write_text(json.dumps(obj,indent=2)+'\n')
def main():
    OUT.mkdir(parents=True,exist_ok=False)
    copied={n:sha(HERE/n) for n in ('codec.hpp','codec.cpp','consumer.cpp','observer.cpp','codec_selftest_main.cpp')}
    for n,h in copied.items():assert h==sha(OLD/('main.cpp' if n=='codec_selftest_main.cpp' else n)),n
    sources={p.name:sha(p) for p in HERE.iterdir() if p.is_file()}
    receipt={'status':'RUNNING','sources_sha256':sources,'identical_copied_sources':copied,'commands':[]}
    def run(name,argv,timeout=180):
        row={'name':name,'argv':[str(x) for x in argv]};receipt['commands'].append(row);start=time.monotonic()
        with (OUT/(name+'.log')).open('xb') as f:
            r=subprocess.run(row['argv'],stdout=f,stderr=subprocess.STDOUT,timeout=timeout)
        row.update(returncode=r.returncode,elapsed_s=time.monotonic()-start,log_sha256=sha(OUT/(name+'.log')));save(OUT/'receipt.json',receipt)
        assert r.returncode==0,name
    cmake=Path('C:/Program Files/CMake/bin/cmake.exe')
    try:
        run('configure',[cmake,'-S',HERE,'-B',OUT/'cmake','-G','Visual Studio 17 2022','-A','x64'])
        run('build',[cmake,'--build',OUT/'cmake','--config','Release','--parallel','2'])
        exe=OUT/'cmake/Release/trecap_downstream8.exe'
        run('codec_selftest',[OUT/'cmake/Release/codec_selftest.exe','--self-test'])
        assert 'self-test PASS' in (OUT/'codec_selftest.log').read_text()
        assert all(sha(HERE/n)==h for n,h in sources.items())
        receipt.update(status='PASS_BUILD_SELFTEST_NO_TIMING',exe_path=str(exe),exe_sha256=sha(exe),cmake_sha256=sha(cmake))
    except Exception as e:receipt.update(status='FAIL',error=str(e));raise
    finally:save(OUT/'receipt.json',receipt)
    print(json.dumps(receipt))
if __name__=='__main__':main()
