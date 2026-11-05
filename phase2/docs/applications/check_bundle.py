"""Audit the published application pages and media without hardware or network."""
from pathlib import Path
import argparse
import hashlib
import json
import re
import wave
from urllib.parse import unquote, urlsplit

HERE = Path(__file__).resolve().parent
MANIFEST = HERE / 'bundle_manifest.json'
def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def inventory():
    return {p.relative_to(HERE).as_posix(): {'sha256':sha(p),'bytes':p.stat().st_size}
            for p in sorted(HERE.rglob('*')) if p.is_file() and p!=MANIFEST and '__pycache__' not in p.parts}
def check():
    expected=json.loads(MANIFEST.read_text(encoding='utf-8'))['files']
    current=inventory()
    assert current==expected, 'Published application file inventory or bytes changed'
    for name in current:
        p=HERE/name
        if p.suffix not in {'.md','.html'}: continue
        content=p.read_text(encoding='utf-8')
        links=re.findall(r'\]\(([^\s)]+)\)',content) if p.suffix=='.md' else re.findall(r'(?:href|src)="([^"]+)"',content)
        for target in links:
            url=urlsplit(target)
            if url.scheme or url.netloc or not url.path: continue
            dest=(p.parent/unquote(url.path)).resolve()
            assert dest.is_relative_to(HERE.parents[2]),f'Link outside repository: {name}'
            assert dest.exists(),f'Missing local target in {name}: {target}'
    bindings=json.loads((HERE/'audio/data/hardware_media_binding.json').read_text(encoding='utf-8'))
    assert len(bindings['variants'])==16
    physical=0
    for row in bindings['variants']:
        wav=HERE/'audio'/row['wav']
        flac=HERE/'audio'/row['flac']
        assert sha(wav)==row['wav_sha256']
        assert sha(flac)==row['flac_sha256'] and flac.stat().st_size==row['flac_bytes']
        assert flac.read_bytes()[:4]==b'fLaC'
        with wave.open(str(wav),'rb') as f:
            assert (f.getframerate(),f.getnchannels(),f.getsampwidth(),f.getnframes())==(48000,1,2,384000)
            assert hashlib.sha256(f.readframes(384000)).hexdigest()==row['pcm_sha256']
        assert row['libsndfile_sample_exact'] and row['ffmpeg_sample_exact']
        if row['route']!='original_pcm16':
            physical+=1
            assert row['complete_y_samples']==384512 and row['alignment_samples']==384
    assert physical==12
    print(f'PASS application bundle: {len(current)} files, all local links, 16 audio media bindings, 12 physical-output provenance entries')

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seal',action='store_true',help='Record a reviewed publication inventory. Does not validate experimental claims.')
    args=parser.parse_args()
    if args.seal:
        MANIFEST.write_text(json.dumps({'schema':'trecap-application-publication-v1','scope':'Archived results and publication audit, not new hardware execution','files':inventory()},indent=2)+'\n',encoding='utf-8')
    check()
