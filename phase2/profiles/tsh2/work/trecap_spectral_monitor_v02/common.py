from pathlib import Path
import hashlib, json, csv
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
WORK = Path(__file__).resolve().parent
OUT = ROOT / 'outputs/trecap_spectral_monitor_v01/revision02'
DATA = ROOT / 'outputs/trecap_spectral_monitor_v01/data'
NATIVE = ROOT / 'work/trecap_spectral_monitor_v01/native'
COEFF = ROOT / 'outputs/trecap_stream8_v01/fixtures02/coefficients'
THRESHOLDS = (0, 10**6, 10**7, 10**8, 10**9, 10**10, 10**11)

def need(ok, message):
    if not ok: raise ValueError(message)

def sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''): h.update(b)
    return h.hexdigest()

def read(path): return json.loads(Path(path).read_text(encoding='utf-8-sig'))

def save(path, obj):
    p=Path(path);p.parent.mkdir(parents=True,exist_ok=True)
    p.write_text(json.dumps(obj,indent=2,allow_nan=False)+'\n',encoding='utf-8')

def fresh(path):
    p=Path(path);need(not p.exists(),'Preserve existing evidence: '+str(p));p.mkdir(parents=True);return p

def verify(mapping):
    for p,h in mapping.items():need(sha(p)==h,'Changed evidence: '+str(p))

def csv_out(path,rows):
    need(bool(rows),'Empty CSV')
    with Path(path).open('w',newline='',encoding='utf-8') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
