"""Two-pass real LaTeX build; retain immutable attempts and exact receipts."""
from pathlib import Path
import argparse,datetime,hashlib,json,shutil,subprocess,sys
HERE=Path(__file__).resolve().parent
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
ap=argparse.ArgumentParser();ap.add_argument('--compiler',default='pdflatex');args=ap.parse_args()
builds=HERE/'build';builds.mkdir(exist_ok=True)
n=1
while (builds/f'attempt{n:02d}').exists():n+=1
out=builds/f'attempt{n:02d}';out.mkdir()
version=subprocess.run([args.compiler,'--version'],cwd=HERE,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
(out/'compiler_version.stdout.txt').write_bytes(version.stdout)
(out/'compiler_version.stderr.txt').write_bytes(version.stderr)
if version.returncode:raise RuntimeError('Compiler version probe failed; see retained output')
miktex=b'MiKTeX' in version.stdout+version.stderr
sources=[HERE/'main.tex',HERE/'portfolio_integration.tex',HERE/'source_manifest.json',*sorted((HERE/'figures').glob('*.pdf'))]
inputs={str(p.relative_to(HERE)):sha(p) for p in sources}
for p in sources:
    dest=out/'inputs'/p.relative_to(HERE);dest.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(p,dest)
commands=[]
for run in (1,2):
    argv=[args.compiler]+(['-disable-installer'] if miktex else [])+['-interaction=nonstopmode','-halt-on-error','-file-line-error',
          '-jobname=TRECAP_DV_Portfolio','-output-directory='+str(out),'main.tex']
    start=datetime.datetime.now(datetime.timezone.utc).isoformat()
    result=subprocess.run(argv,cwd=HERE,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    (out/f'pass{run}.stdout.txt').write_bytes(result.stdout);(out/f'pass{run}.stderr.txt').write_bytes(result.stderr)
    commands.append({'argv':argv,'cwd':str(HERE),'started_utc':start,'exit_code':result.returncode,
                     'stdout':f'pass{run}.stdout.txt','stderr':f'pass{run}.stderr.txt'})
    if result.returncode:break
pdf=out/'TRECAP_DV_Portfolio.pdf'
ok=all(c['exit_code']==0 for c in commands) and len(commands)==2 and pdf.exists()
receipt={'status':'PASS_LATEX_COMPILE' if ok else 'FAIL_LATEX_COMPILE','engine':'real pdfLaTeX',
         'commands':commands,'input_hashes':inputs,'attempt':str(out),
         'compiler_version_stdout':'compiler_version.stdout.txt','compiler_version_stderr':'compiler_version.stderr.txt'}
if pdf.exists():receipt['pdf_sha256']=sha(pdf)
(out/'build_receipt.json').write_text(json.dumps(receipt,indent=2)+'\n')
if ok:
    shutil.copyfile(pdf,HERE/'TRECAP_DV_Portfolio.pdf')
    shutil.copyfile(out/'build_receipt.json',HERE/'build_receipt.json')
print(json.dumps({'status':receipt['status'],'attempt':str(out)},indent=2))
sys.exit(0 if ok else 1)
