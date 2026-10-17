"""Compile the academic report with real pdfLaTeX, preserving bounded attempts."""
from pathlib import Path
import argparse,datetime,hashlib,json,shutil,subprocess,sys

HERE=Path(__file__).resolve().parent
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
    ap=argparse.ArgumentParser();ap.add_argument('--compiler',default='pdflatex');args=ap.parse_args()
    builds=HERE/'build';builds.mkdir(exist_ok=True)
    n=1
    while (builds/f'attempt{n:02d}').exists():n+=1
    out=builds/f'attempt{n:02d}';out.mkdir()
    version=subprocess.run([args.compiler,'--version'],capture_output=True,timeout=30)
    (out/'compiler_version.txt').write_bytes(version.stdout+version.stderr)
    version.check_returncode();miktex=b'MiKTeX' in version.stdout+version.stderr
    sources=[*sorted(HERE.glob('*.tex')),*sorted((HERE/'figures').glob('*.pdf')),HERE/'report_data.json']
    inputs={p.relative_to(HERE).as_posix():sha(p) for p in sources}
    for p in sources:
        q=out/'inputs'/p.relative_to(HERE);q.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(p,q)
    commands=[]
    for run in (1,2):
        argv=[args.compiler]+(['-disable-installer'] if miktex else [])+[
            '-no-shell-escape','-interaction=nonstopmode','-halt-on-error','-file-line-error',
            '-jobname=TRECAP_UVM_Formal_Report','-output-directory='+str(out),'main.tex']
        start=datetime.datetime.now(datetime.timezone.utc).isoformat()
        result=subprocess.run(argv,cwd=HERE,capture_output=True,timeout=120)
        (out/f'pass{run}.stdout.txt').write_bytes(result.stdout)
        (out/f'pass{run}.stderr.txt').write_bytes(result.stderr)
        commands.append({'argv':argv,'started_utc':start,'exit_code':result.returncode})
        if result.returncode:break
    pdf=out/'TRECAP_UVM_Formal_Report.pdf'
    ok=len(commands)==2 and all(c['exit_code']==0 for c in commands) and pdf.is_file()
    receipt={'status':'PASS_LATEX_COMPILE' if ok else 'FAIL_LATEX_COMPILE','commands':commands,
             'inputs':inputs,'compiler_version_sha256':sha(out/'compiler_version.txt')}
    if pdf.is_file():receipt['pdf_sha256']=sha(pdf)
    (out/'build_receipt.json').write_text(json.dumps(receipt,indent=2)+'\n')
    if ok:shutil.copyfile(pdf,HERE/pdf.name)
    print(json.dumps({'status':receipt['status'],'attempt':str(out)}))
    return 0 if ok else 1
if __name__=='__main__':sys.exit(main())
