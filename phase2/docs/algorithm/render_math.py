"""Publish editable Markdown with locally rendered LaTeX equation images.

Generation needs LaTeX with amsmath/amssymb and dvisvgm. Checking needs only Python.
No network, board access or shell escape is used by this renderer.
"""
from pathlib import Path
import argparse
import hashlib
import json
import math
import os
import re
import subprocess
import tempfile
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parent
SVG = 'http://www.w3.org/2000/svg'
ET.register_namespace('', SVG)
ET.register_namespace('xlink', 'http://www.w3.org/1999/xlink')
TOKEN = re.compile(r'(?P<fence>^\s*```[^\n]*\n.*?^\s*```\s*$)|(?P<code>`[^`\n]+`)|(?P<display>\$\$\s*\n?(.*?)\n?\s*\$\$)|(?P<inline>(?<![\\$])\$(?!\$)([^\n$]+)(?<!\\)\$)', re.M | re.S)


def sha_bytes(data):
    return hashlib.sha256(data).hexdigest()


def sources():
    return sorted((ROOT / 'source/baseline').glob('page-*.md')) + [ROOT / 'source/current_profiles_and_rf.md']


def rebase(text, old, new):
    def link(m):
        target = m[2]
        if re.match(r'^[a-zA-Z][\w+.-]*:', target) or target.startswith('#'):
            return m[0]
        file, sep, fragment = target.partition('#')
        path = os.path.relpath((old / file).resolve(), new).replace('\\', '/')
        return m[1] + '(' + path + sep + fragment + ')'
    return re.sub(r'(!?\[[^\]\n]*\])\(([^)\n]+)\)', link, text)


def collect():
    formulas = []
    documents = {}
    for path in sources():
        relative = path.relative_to(ROOT / 'source')
        output = ROOT / relative
        raw = path.read_text(encoding='utf-8')
        text = rebase(raw, path.parent, output.parent)
        index = 0

        def replace(m):
            nonlocal index
            if m.group('fence') or m.group('code'):
                return m[0]
            index += 1
            display = m.group('display') is not None
            tex = m[0][2:-2].strip() if display else m[0][1:-1].strip()
            stem = relative.with_suffix('').as_posix().replace('/', '-')
            key = f'{stem}-{index:03}'
            asset = 'math/' + key + '.svg'
            formulas.append({'id': key, 'source': path.relative_to(ROOT).as_posix(),
                             'kind': 'display' if display else 'inline', 'tex': tex,
                             'tex_sha256': sha_bytes(tex.encode()), 'svg': asset})
            label = re.search(r'\\tag\{([^}]+)\}', tex)
            # Accessible fallback is the actual TeX, escaped for Markdown tables.
            alt = ('Equation ' + label[1] + ': ' if label else '') + tex
            alt = alt.replace('\\', '&#92;').replace('[', '&#91;').replace(']', '&#93;').replace('|', '&#124;').replace('\n', ' ')
            target = os.path.relpath(ROOT / asset, output.parent).replace('\\', '/')
            return f'![{alt}]({target})'

        text = TOKEN.sub(replace, text)
        source_link = os.path.relpath(path, output.parent).replace('\\', '/')
        lines = text.splitlines()
        # Keep provenance as the third line for coverage checks.
        at = 6 if relative.parts[0] == 'baseline' else 2
        lines[at:at] = [f'[Edit Markdown and LaTeX source]({source_link}). Equations are rendered locally as SVG.', '']
        documents[relative.as_posix()] = '\n'.join(lines) + '\n'
    return formulas, documents


def latex_formula(row):
    tex = row['tex']
    labels = re.findall(r'\\tag\{([^}]+)\}', tex)
    tex = re.sub(r'\\tag\{([^}]+)\}', '', tex)
    # TeX operator names are text. Literal underscores require escaping.
    tex = re.sub(r'\\operatorname\{([^}]+)\}', lambda m: r'\operatorname{' + re.sub(r'(?<!\\)_', r'\\_', m[1]) + '}', tex)
    if labels:
        tex += r'\qquad\text{(' + labels[0] + ')}'
    return (r'\displaystyle ' if row['kind'] == 'display' else '') + tex


def make_svg(raw, row):
    node = ET.fromstring(raw)
    x, y, w, h = [float(v) for v in node.attrib['viewBox'].split()]
    assert w > 0 and h > 0
    padding = 6 if row['kind'] == 'display' else 1.5
    x, y, w, h = x-padding, y-padding, w+2*padding, h+2*padding
    scale = 1.6
    node.set('viewBox', f'{x:.6f} {y:.6f} {w:.6f} {h:.6f}')
    node.set('width', f'{w*scale:.3f}px')
    node.set('height', f'{h*scale:.3f}px')
    node.set('role', 'img')
    title = ET.Element(f'{{{SVG}}}title')
    title.text = row['tex']
    node.insert(0, title)
    # Explicit background and ink keep formulas legible in light and dark viewers.
    background = ET.Element(f'{{{SVG}}}rect', {'x':str(x), 'y':str(y), 'width':str(w), 'height':str(h), 'fill':'#ffffff'})
    node.insert(1, background)
    node.set('fill', '#172435')
    return ET.tostring(node, encoding='utf-8', xml_declaration=True) + b'\n'


def dimensions(data):
    node = ET.fromstring(data)
    assert node.tag == f'{{{SVG}}}svg', 'Invalid SVG root'
    w = float(node.attrib['width'].removesuffix('px'))
    h = float(node.attrib['height'].removesuffix('px'))
    view = [float(v) for v in node.attrib['viewBox'].split()]
    assert len(view) == 4 and all(math.isfinite(v) for v in [w,h,*view])
    assert w >= 4 and h >= 8 and view[2] > 0 and view[3] > 0, 'Collapsed equation dimensions'
    assert abs(w/h-view[2]/view[3]) < 0.01, 'Equation aspect ratio is distorted'
    assert list(node.iter(f'{{{SVG}}}path')), 'Equation contains no vector glyphs'
    assert not any(e.tag.rsplit('}',1)[-1] in {'script','foreignObject','image','text'} for e in node.iter()), 'Unexpected active/external/font-dependent SVG content'
    ids = {e.get('id') for e in node.iter() if e.get('id')}
    for element in node.iter():
        for name, value in element.attrib.items():
            if name.rsplit('}',1)[-1] == 'href':
                assert value.startswith('#') and value[1:] in ids, 'Unresolved/external SVG reference'
    return {'width_px':w, 'height_px':h}


def check():
    expected, documents = collect()
    manifest = json.loads((ROOT / 'math_manifest.json').read_text(encoding='utf-8'))
    actual = manifest['formulas']
    assert len(expected) == len(actual), 'Formula coverage changed'
    for row, bound in zip(expected, actual):
        assert all(bound.get(k) == v for k,v in row.items()), 'Formula source or mapping changed'
        data = (ROOT / row['svg']).read_bytes()
        assert sha_bytes(data) == bound['svg_sha256'], 'Equation SVG changed'
        assert dimensions(data) == bound['dimensions'], 'Equation size changed'
        assert ET.fromstring(data).find(f'{{{SVG}}}title').text == row['tex'], 'Equation accessible source differs'
    assert {p.relative_to(ROOT).as_posix() for p in (ROOT/'math').glob('*.svg')} == {r['svg'] for r in expected}, 'Missing or orphaned formula images'
    for name, text in documents.items():
        assert (ROOT/name).read_text(encoding='utf-8') == text, f'Stale rendered Markdown: {name}'
        # All math tokens outside code must be replaced by images.
        assert not any(m.group('display') or m.group('inline') for m in TOKEN.finditer(text)), f'Raw formula remains in {name}'
    return {'documents':len(documents), 'display_formulas':sum(r['kind']=='display' for r in expected),
            'inline_formulas':sum(r['kind']=='inline' for r in expected), 'svg_assets':len(expected)}


def build(latex, dvisvgm, work):
    rows, documents = collect()
    work.mkdir(parents=True, exist_ok=True)
    tex = ['\\documentclass{article}', '\\usepackage{amsmath,amssymb}', '\\begin{document}', '\\pagestyle{empty}', '\\newbox\\eqbox']
    for row in rows:
        tex += ['% '+row['id'], '\\setbox\\eqbox=\\hbox{$'+latex_formula(row)+'$}', '\\shipout\\box\\eqbox']
    tex += ['\\end{document}']
    (work/'equations.tex').write_text('\n'.join(tex)+'\n', encoding='utf-8')
    for label, command in [('latex',[latex,'-no-shell-escape','-interaction=nonstopmode','-halt-on-error','equations.tex']),
                           ('dvisvgm',[dvisvgm,'--page=1-','--no-fonts','--exact-bbox','--output=eq-%p.svg','equations.dvi'])]:
        result = subprocess.run(command, cwd=work, capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=180)
        (work/(label+'.txt')).write_text(result.stdout+'\n'+result.stderr, encoding='utf-8')
        if result.returncode:
            raise RuntimeError(label+' failed. Inspect '+str(work/(label+'.txt')))
    (ROOT/'math').mkdir(exist_ok=True)
    for n, row in enumerate(rows,1):
        data = make_svg((work/f'eq-{n:0{len(str(len(rows)))}}.svg').read_bytes(), row)
        row['dimensions'] = dimensions(data)
        row['svg_sha256'] = sha_bytes(data)
        (ROOT/row['svg']).write_bytes(data)
    for name, text in documents.items():
        (ROOT/name).write_text(text,encoding='utf-8')
    (ROOT/'math_manifest.json').write_text(json.dumps({'schema':'trecap-latex-svg-v1', 'renderer':'LaTeX amsmath/amssymb and dvisvgm with outlined glyphs', 'formulas':rows},indent=2)+'\n',encoding='utf-8')
    return check()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check',action='store_true')
    parser.add_argument('--latex',default='latex')
    parser.add_argument('--dvisvgm',default='dvisvgm')
    parser.add_argument('--work',type=Path)
    args=parser.parse_args()
    if args.check:
        result=check()
    elif args.work:
        result=build(args.latex,args.dvisvgm,args.work.resolve())
    else:
        with tempfile.TemporaryDirectory(prefix='trecap-math-') as work:
            result=build(args.latex,args.dvisvgm,Path(work))
    print(json.dumps({'status':'PASS_RENDERED_MATH',**result}))


if __name__ == '__main__':
    main()
