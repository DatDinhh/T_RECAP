"""Check complete editable specification coverage, links and reviewed identities.

These are source coverage and rendered publication checks, not a mathematical
equivalence proof. The recorded LaTeX render and SVG assets are checked without
invoking hardware, a network service or a third-party Python package.
"""
from pathlib import Path
import argparse
from collections import Counter
import hashlib
import importlib.util
import json
import re
from urllib.parse import unquote, urlsplit
import assemble_spec
import render_math

ROOT = Path(__file__).resolve().parent
PDF_SHA256 = '7de45d2764bacc090d2837501382c82a7f081884b7c929b8b4aa4b536bff2aaf'
MANIFEST = ROOT / 'bundle_manifest.json'

def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()
def read(name): return json.loads((ROOT / name).read_text(encoding='utf-8'))
def files():
    return {p.relative_to(ROOT).as_posix(): {'sha256':sha(p),'bytes':p.stat().st_size}
            for p in sorted(ROOT.rglob('*')) if p.is_file() and p!=MANIFEST and '__pycache__' not in p.parts}

def prose_checker():
    path = ROOT.parent / 'editorial/20261104-prose/check_prose.py'
    spec = importlib.util.spec_from_file_location('trecap_prose_audit',path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

def markdown_structure(path,text):
    fence = None
    math_open = False
    table_width = None
    for number,line in enumerate(text.splitlines(),1):
        mark=re.match(r'^\s*(`{3,}|~{3,})',line)
        if mark:
            if fence is None: fence=mark.group(1)[0]
            elif fence==mark.group(1)[0]: fence=None
            table_width=None
            continue
        if fence is not None: continue
        if line.strip()=='$$': math_open=not math_open
        if line.startswith('|') and line.rstrip().endswith('|'):
            width=len(re.split(r'(?<!\\)\|',line))-2
            if table_width is not None:
                assert width==table_width,f'Inconsistent table columns at {path.name}:{number}'
            table_width=width
        else: table_width=None
    assert fence is None,f'Unclosed code fence in {path.name}'
    assert not math_open,f'Unclosed displayed math in {path.name}'

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seal',action='store_true',help='Refresh reviewed page/publication hashes after an intentional edit. Does not certify correctness.')
    args=parser.parse_args()
    source=read('source_inventory.json')
    coverage=read('coverage_manifest.json')
    assert source['source_pdf_pages']==coverage['source_pdf_pages']==106
    assert source['source_pdf_sha256']==coverage['source_pdf_sha256']==PDF_SHA256
    assert sha(ROOT/source['source_pdf'])==PDF_SHA256,'Original source PDF changed'
    expected_names=[f'page-{n:03}.md' for n in range(1,107)]
    assert sorted(p.name for p in (ROOT/'baseline').glob('*.md'))==expected_names
    assert sorted(p.name for p in (ROOT/'source/baseline').glob('*.md'))==expected_names
    assert [p['pdf_page'] for p in coverage['pages']]==list(range(1,107))
    original={p['pdf_page']:p for p in source['source_pages']}
    all_text=[]
    for row in coverage['pages']:
        n=row['pdf_page']
        assert row['markdown']==f'baseline/page-{n:03}.md'
        assert row['source_extraction_sha256']==original[n]['extraction_sha256']
        path=ROOT/row['markdown']
        published=path.read_text(encoding='utf-8')
        editable=ROOT/'source'/row['markdown']
        text=editable.read_text(encoding='utf-8')
        for candidate in (text,published):
            assert candidate.startswith(f'# Baseline PDF page {n:03}\n')
            assert 'Historical' in candidate.splitlines()[2]
            assert f't_recap_phase2_integrated_spec.pdf#page={n}' in candidate
        labels=re.findall(r'\\tag\{([^}]+)\}',text)
        wanted=[e['label'] for e in source['numbered_equations'] if e['pdf_page']==n]
        assert Counter(labels)==Counter(wanted),f'Numbered equations differ on PDF page {n}'
        if args.seal:
            row['markdown_sha256']=sha(path)
            row['markdown_characters']=len(published)
            row['editable_source']=editable.relative_to(ROOT).as_posix()
            row['editable_source_sha256']=sha(editable)
            row['editable_source_characters']=len(text)
        assert sha(path)==row['markdown_sha256'],f'Unreviewed edit at {row["markdown"]}'
        assert row['editable_source']==editable.relative_to(ROOT).as_posix()
        assert sha(editable)==row['editable_source_sha256'],f'Unreviewed source edit at {row["editable_source"]}'
        assert row['markdown_characters']==len(published)
        assert row['editable_source_characters']==len(text)
        all_text.append(text)
    baseline='\n'.join(all_text)
    eq=re.findall(r'\\tag\{([^}]+)\}',baseline)
    assert len(eq)==len(set(eq))==116
    tables={int(x) for x in re.findall(r'^\*\*Table (\d+)[. ]',baseline,re.M)}
    assert tables=={r['table'] for r in source['tables']}==set(range(1,46))
    algorithms={int(x) for x in re.findall(r'^### Algorithm (\d+)\b',baseline,re.M)}
    assert algorithms==set(source['algorithms'])==set(range(1,8))
    sections={int(x) for x in re.findall(r'^## (\d+)\s',baseline,re.M)}
    assert sections==set(source['major_sections'])==set(range(1,54))
    combined=(ROOT/'complete_specification.md').read_text(encoding='utf-8')
    assert combined==assemble_spec.combined_text(),'Read-all file is stale. Run assemble_spec.py.'
    assert len(re.findall(r'<a id="pdf-page-\d{3}"></a>',combined))==106
    render_summary=render_math.check()
    audit=prose_checker()
    documents=list(ROOT.rglob('*.md'))
    for path in documents:
        text=path.read_text(encoding='utf-8')
        markdown_structure(path,text)
        assert not audit.scan(path,text),f'Forbidden prose punctuation in {path.relative_to(ROOT)}'
        for target in re.findall(r'\]\(([^\s)]+)\)',text):
            url=urlsplit(target)
            if url.scheme or url.netloc or not url.path: continue
            dest=(path.parent/unquote(url.path)).resolve()
            assert dest.is_relative_to(ROOT.parents[2]),f'Link outside repository: {target}'
            if args.seal and dest==MANIFEST:
                continue
            assert dest.exists(),f'Missing target in {path.name}: {target}'
    if args.seal:
        (ROOT/'coverage_manifest.json').write_text(json.dumps(coverage,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
        MANIFEST.write_text(json.dumps({'schema':'trecap-complete-editable-specification-v2',
            'source_pdf_sha256':PDF_SHA256,'scope':'Source completeness, source-to-SVG coverage and reviewed publication identities, not semantic certification or RTL signoff.',
            'source_pages':106,'numbered_equations':116,'numbered_tables':45,'numbered_algorithms':7,'major_sections':53,'files':files()},indent=2)+'\n',encoding='utf-8')
    assert read('bundle_manifest.json')['files']==files(),'Specification bundle inventory or bytes changed'
    print(json.dumps({'status':'PASS_COMPLETE_EDITABLE_SPECIFICATION','pages':106,'equations':116,'tables':45,
                      'algorithms':7,'major_sections':53,'markdown_documents':len(documents),
                      'math_render':render_summary,'hardware_access':False}))

if __name__=='__main__':
    main()
