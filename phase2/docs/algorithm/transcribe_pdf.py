"""Reproduce all historical baseline Markdown pages from the pinned PDF layout.

The default mode compares without modifying files. The explicit --write mode
recreates baseline pages. It never changes the original PDF or current RF appendix.
"""
from pathlib import Path
import hashlib
import json
import re
import textwrap

ROOT = Path(__file__).resolve().parent
RULES = json.loads((ROOT / 'conversion_rules.json').read_text(encoding='utf-8'))
TABLES = RULES['table_regions']
OVERRIDES = RULES
SOURCE_SHA = '7de45d2764bacc090d2837501382c82a7f081884b7c929b8b4aa4b536bff2aaf'
PAGES = []

def norm(s):
    s=s.replace('\u2013','-').replace('\u2014',', ').replace('\u2011','-').replace('\u00a0',' ')
    s=s.replace('\u2212','-').replace('\ufb01','fi').replace('\ufb02','fl')
    return s

def prose(s):
    s=norm(s)
    s=re.sub(r';\s*([a-z]+)\b(?!_)', lambda m:'. '+m[1].capitalize(), s)
    s=re.sub(r';\s*', '. ', s)
    return s.rstrip()

def join(lines):
    out=''
    for l in lines:
        l=l.strip()
        if not l:continue
        if out.endswith('-') and l[0].isalpha():
            prefixes={'source','time','frequency','frame','packet','full','fixed','low','high','core','non','zero','real','multi','word','read','write','little','big','bit','board','build','cross','sign','phase','two','one','right','left','near','round','run','post','pre','finite','active','short','long','hard','first','per','top','same','thread','line','double','single','sample','user','transport','signed','unsigned','two’s','stream','reserved','Reserved'}
            last=out.rsplit(' ',1)[-1][:-1]
            out=(out if last in prefixes or l[0].isupper() else out[:-1])+l
        elif (out.endswith('_') or (out.endswith('.') and re.fullmatch(r'[\w/.-]+',out) and '/' in out)) and re.match(r'^[\w.]+\b',l):out+=l
        else:out+=(' ' if out else '')+l
    return re.sub(r' {2,}',' ',out)

def inline(s):
    # File paths and register identifiers should not accidentally become emphasis.
    s=prose(s)
    s=s.replace('Nf rames','Nframes').replace('Wf f t','Wfft').replace('Wif f t','Wifft').replace('Ff ree','Ffree').replace('Tf rame','Tframe').replace('Ff rame','Fframe')
    for old,new in {'thr2_commit pending':'thr2_commit_pending','source_commit pending':'source_commit_pending','WAVEpayloads':'WAVE payloads','METRICSpayloads':'METRICS payloads','STATUSskeleton':'STATUS skeleton','STATUSpayload':'STATUS payload','Multiplies √ frame samples by frozen quantized Hann coefficients.':'Multiplies frame samples by frozen quantized square-root Hann coefficients.'}.items():s=s.replace(old,new)
    for old,new in {'0 ≤ THR2 < 256':'$0 \\le\\mathrm{THR2}<2^{56}$','THR2≥ 256':'$\\mathrm{THR2}\\ge2^{56}$','modulo-232':'modulo-$2^{32}$','modulo-264':'modulo-$2^{64}$'}.items():s=s.replace(old,new)
    s=re.sub(r'\b2(Wmag2|F|W|P|B)\b',lambda m:'$2^{'+m[1]+'}$',s)
    math=[]
    def hold(m):
        math.append(m[0]);return f'MATHPLACEHOLDER{len(math)-1}TOKEN'
    s=re.sub(r'\$[^$]+\$',hold,s)
    s=re.sub(r'(?<![`\w])([A-Za-z_][A-Za-z0-9_./+-]*_[A-Za-z0-9_./+-]*[A-Za-z0-9_/+-])(?![`\w])',r'`\1`',s)
    for i,m in enumerate(math):s=s.replace(f'MATHPLACEHOLDER{i}TOKEN',m)
    s=re.sub(r'<(?:sha256-hex|decimal-string)>',lambda m:'`'+m[0]+'`',s)
    return s

def table_rows(t,lines):
    num=t['table']
    starts=t['col_starts'][:]
    if num==8:starts=[2,14,35,45]
    if num==44:starts=[2,16,58]
    if num==9:starts=[0,13,40,55]
    if num not in (8,9):
        starts=[starts[0]]+[min([s]+[m.end() for l in lines[1:] for m in re.finditer(r' {2,}',l) if abs(m.end()-s)<=4]) for s in starts[1:]]
    bounds=[0]+[s-1 for s in starts[1:]]+[1000]
    raw=[[l[bounds[j]:bounds[j+1]].strip() for j in range(len(bounds)-1)] for l in lines]
    if num==8:
        raw=[]
        for l in lines:
            if 'Offset' in l and 'Access' in l:raw.append(['Offset','Name','Access','Meaning'])
            else:
                m=re.match(r'\s*(0x[0-9A-F]+)\s+(\w+)\s+(R/W|W1P|W1C|R|W)\s+(.*)',l)
                if m:raw.append(list(m.groups()))
                else:
                    # Wrapped register names start left of the meaning column.
                    b=45 if t['page']==41 else 39 if t['page']==42 else 48
                    raw.append(['',l[10:b].strip(),' ',l[b:].strip()])
    if num==9:
        raw=[['Bit','Name','Type','Meaning']]
        for l in lines[1:]:
            m=re.match(r'\s*(\d+(?::\d+)?)\s+(\w+)\s+(Level|W1P|-)\s+(.*)',l)
            raw.append(list(m.groups()) if m else ['','','',l.strip()])
    rows=[]
    for cells in raw:
        if not any(cells):continue
        if rows and (not cells[0] or (not any(cells[1:])) or rows[-1][0].endswith(('_','.'))):
            rows[-1]=[join([a,b]) for a,b in zip(rows[-1],cells)]
        else:rows.append(cells)
    return rows

def table_md(t,lines):
    rows=table_rows(t,lines)
    rows=OVERRIDES.get('tables',{}).get(str(t['table'])+'-'+str(t['page']),OVERRIDES.get('tables',{}).get(str(t['table']),rows))
    rows=[[inline(c).replace('|',r'\|') for c in r] for r in rows]
    return '**Table '+str(t['table'])+'. '+prose(t['caption'])+'**\n\n'+'\n'.join(['| '+' | '.join(rows[0])+' |','| '+' | '.join(['---']*len(rows[0]))+' |']+['| '+' | '.join(r)+' |' for r in rows[1:]])+'\n'

def para_blocks(lines):
    out=[]
    buf=[]
    def flush():
        if buf:
            out.append(inline(join(buf)))
            buf.clear()
    for l in lines:
        st=l.strip()
        if not st:flush();continue
        if re.match(r'^(?:\d+(?:\.\d+)*|[A-D])\s{2,}[A-Z]',st):
            flush()
            n,title=re.split(r'\s{2,}',st,maxsplit=1)
            out.append(('### ' if '.' in n else '## ')+n+' '+inline(title))
        elif re.match(r'^Part [IV]+ - ',st) or st in ['Executive Summary','Contents','List of Algorithms','List of Tables','Appendices','References']:
            flush();out.append('## '+st)
        elif re.match(r'^(?:•|[0-9]+\.|INV[0-9]+\.|AC[0-9]+\.)\s',st):
            flush();buf.append(('- '+st[1:].strip()) if st.startswith('•') else st)
        elif st.startswith('Algorithm '):
            flush();out.append('### '+inline(st))
        else:buf.append(st)
    flush()
    return '\n\n'.join(out)

def convert(n,p):
    ls=p.splitlines()
    replacements=[]
    for t in TABLES:
        if t['page']==n:
            replacements.append((t['caption_start'],t['end'],table_md(t,ls[t['start']:t['end']])))
    # One long CSR table continues across two following PDF pages.
    if n in [42,43]:
        end=49 if n==42 else 10
        t={'table':8,'page':n,'col_starts':[2,14,35,45],'caption':'Normative CSR map, continued.'}
        replacements.append((4,end,table_md(t,ls[4:end])))
    if n in [69,79]:
        t={'table':26 if n==69 else 28,'page':n,'col_starts':[8,35,74] if n==69 else [5,29],'caption':'Failure modes and required observability, continued.' if n==69 else 'Repository directory responsibilities, continued.'}
        end=13 if n==69 else 24
        replacements.append((4,end,table_md(t,ls[4:end])))
    for item in OVERRIDES.get('pages',{}).get(str(n),[]):
        replacements.append((item['start'],item['end'],item['markdown']))
    replacements.sort()
    for a,b in zip(replacements,replacements[1:]):
        assert a[1]<=b[0],(n,a[:2],b[:2])
    # Running page header and footer are layout furniture. Physical-page provenance is retained below.
    start=0 if n==1 else 1
    end=len(ls)
    while end and (not ls[end-1].strip() or re.fullmatch(r'(?:\d+|[ivx]+)',ls[end-1].strip())):end-=1
    chunks=[]
    for a,b,md in replacements:
        if a>=end:continue
        chunks.append(para_blocks(ls[start:a]))
        chunks.append(md)
        start=b
    chunks.append(para_blocks(ls[start:end]))
    body='\n\n'.join(c for c in chunks if c.strip())
    label='cover' if n==1 else ('front matter '+str(n-1) if n<=13 else 'printed page '+str(n-13))
    part='Historical baseline'
    if n>=14 and n<=36:part='Historical Part I, core algorithm'
    elif n>=37 and n<=72:part='Historical Part II, DDR and UDP telemetry'
    elif n>=73 and n<=101:part='Historical Part III, repository architecture'
    elif n>=102:part='Historical appendices and references'
    nav=[]
    if n>1:nav.append(f'[Previous](page-{n-1:03}.md)')
    nav.append('[Index](../README.md)')
    if n<106:nav.append(f'[Next](page-{n+1:03}.md)')
    pre=f'# Baseline PDF page {n:03}\n\n{part}. {label.capitalize()}. [Original PDF page](../../specs/t_recap_phase2_integrated_spec.pdf#page={n}).\n\n'+ ' | '.join(nav)+'\n\n'
    return pre+body.strip()+'\n'

def main():
    import argparse
    import shutil
    import subprocess
    import tempfile
    global PAGES
    parser = argparse.ArgumentParser(description='Reproduce the historical PDF transcription with reviewed notation repairs.')
    parser.add_argument('--layout', type=Path, help='Existing pdftotext -layout UTF-8 extraction')
    parser.add_argument('--pdftotext', help='Path to pdftotext when extracting directly from the PDF')
    parser.add_argument('--write', action='store_true', help='Explicitly overwrite the 106 editable baseline page files')
    args = parser.parse_args()
    source = ROOT.parent / 'specs/t_recap_phase2_integrated_spec.pdf'
    if hashlib.sha256(source.read_bytes()).hexdigest() != SOURCE_SHA:
        raise SystemExit('Source PDF differs from the reviewed historical baseline')
    if args.layout:
        raw = args.layout.read_text(encoding='utf-8')
    else:
        executable = args.pdftotext or shutil.which('pdftotext')
        if not executable:
            raise SystemExit('Supply --layout or install pdftotext and pass --pdftotext')
        with tempfile.TemporaryDirectory(prefix='trecap-spec-') as directory:
            target = Path(directory) / 'layout.txt'
            subprocess.run([executable, '-layout', '-enc', 'UTF-8', str(source), str(target)], check=True)
            raw = target.read_text(encoding='utf-8')
    PAGES = [p for p in raw.split('\f') if p.strip()]
    inventory = json.loads((ROOT / 'source_inventory.json').read_text(encoding='utf-8'))
    if len(PAGES) != 106:
        raise SystemExit('Expected exactly 106 source pages')
    for p, record in zip(PAGES, inventory['source_pages']):
        if hashlib.sha256(p.encode()).hexdigest() != record['extraction_sha256']:
            raise SystemExit('Extraction layout differs on PDF page '+str(record['pdf_page'])+'. Use the reviewed pdftotext layout or review new extraction rules.')
    changed = []
    for n, p in enumerate(PAGES, 1):
        text = convert(n, p)
        target = ROOT / 'baseline' / f'page-{n:03}.md'
        if args.write:
            target.write_text(text, encoding='utf-8')
        elif not target.exists() or target.read_text(encoding='utf-8') != text:
            changed.append(n)
    if changed:
        raise SystemExit('Transcription differs on PDF pages '+str(changed))
    print(json.dumps({'status':'PASS', 'pages':106, 'mode':'write' if args.write else 'compare', 'hardware_access':False}))

if __name__ == '__main__':
    main()
