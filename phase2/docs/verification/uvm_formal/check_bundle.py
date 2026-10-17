"""Check the published report's byte identities, without rerunning verification."""
from pathlib import Path
import hashlib,json

ROOT=Path(__file__).resolve().parent
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def child(base,name):
    rel=Path(name)
    if rel.is_absolute() or '..' in rel.parts:raise ValueError('Unsafe manifest path: '+name)
    p=base/rel
    if not p.resolve().is_relative_to(base.resolve()) or p.is_symlink():raise ValueError('Nonlocal manifest path: '+name)
    return p
def check():
    m=json.loads((ROOT/'manifest.json').read_text())
    files=m['files'];names=[r['path'] for r in files]
    if not names or len(names)!=len(set(names)):raise ValueError('Empty or duplicate file inventory')
    for row in files:
        p=child(ROOT,row['path'])
        if sha(p)!=row['sha256'] or p.stat().st_size!=row['bytes']:raise ValueError('Report file differs: '+row['path'])
    phase2=ROOT.parents[2]
    for row in m['verification_sources']:
        if sha(child(phase2,row['path']))!=row['sha256']:raise ValueError('Verification evidence differs: '+row['path'])
    print(json.dumps({'status':'PASS','report_files':len(files),'verification_bindings':len(m['verification_sources']),
                      'scope':'Published report integrity only; no new simulation, proof or PDF compilation'}))
if __name__=='__main__':check()
