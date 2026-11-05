"""Assemble the editable page transcription and current profile appendix."""
from pathlib import Path
import argparse
import re

ROOT = Path(__file__).resolve().parent


def nest_headings(text):
    """Keep source-page sections below their page heading in the read-all view."""
    fenced = False
    out = []
    for line in text.splitlines():
        if line.startswith('```'):
            fenced = not fenced
        if not fenced and re.match(r'^#{1,5} ', line):
            line = '#' + line
        out.append(line)
    return '\n'.join(out)


def rebase_links(text, origin):
    """Rebase relative Markdown links while leaving external links untouched."""
    def replace(match):
        target = match.group(2)
        if re.match(r'^[a-zA-Z][a-zA-Z0-9+.-]*:', target) or target.startswith('#'):
            return match.group(0)
        file, sep, fragment = target.partition('#')
        if origin == 'baseline':
            if file.startswith('../../'):
                file = '../' + file[6:]
            elif file.startswith('../'):
                file = file[3:]
            else:
                file = 'baseline/' + file
        return match.group(1) + '(' + file + (sep + fragment if sep else '') + ')'
    return re.sub(r'(!?\[[^\]\n]*\])\(([^)\n]+)\)', replace, text)


def combined_text():
    out = [
        '# T-RECAP complete editable specification',
        '**Threshold-based Reduction and Encoding for Configurable Analysis Pipelines.**',
        'This document contains the complete historical 106-page specification followed by the finite-record audio, acceleration and RF implementation contracts. The historical core, DDR/UDP telemetry proposal and repository plan retain their original scope. The current appendix states how TSH2 and TRF1 differ from that plan. Historical requirements are not statements that every proposed feature is implemented.',
        '[Reading guide and page index](README.md) | [Current profiles and RF](#current-profiles-and-rf)',
        '| Historical part | Source PDF pages | Start |\n| --- | --- | --- |\n| Front matter | 1 to 13 | [Cover](#pdf-page-001) |\n| Part I, algorithm and signoff | 14 to 36 | [Part I](#pdf-page-014) |\n| Part II, DDR and UDP telemetry | 37 to 72 | [Part II](#pdf-page-037) |\n| Part III, repository architecture | 73 to 101 | [Part III](#pdf-page-073) |\n| Appendices and references | 102 to 106 | [Appendices](#pdf-page-102) |',
        'The editable source pages preserve source-page boundaries for comparison. Equation, algorithm and table numbers refer to the historical document. The original PDF remains unchanged.'
    ]
    for n in range(1, 107):
        text = (ROOT / 'baseline' / f'page-{n:03}.md').read_text(encoding='utf-8')
        text = rebase_links(text, 'baseline')
        text = nest_headings(text)
        out.append(f'<a id="pdf-page-{n:03}"></a>\n\n' + text.strip())
    appendix = (ROOT / 'current_profiles_and_rf.md').read_text(encoding='utf-8')
    out.append('<a id="current-profiles-and-rf"></a>\n\n' + nest_headings(appendix).strip())
    return '\n\n'.join(out) + '\n'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true', help='Compare the read-all file without modifying it')
    args = parser.parse_args()
    target = ROOT / 'complete_specification.md'
    text = combined_text()
    if args.check:
        if not target.exists() or target.read_text(encoding='utf-8') != text:
            raise SystemExit('Read-all Markdown differs. Run assemble_spec.py after editing source pages.')
        print('PASS: complete Markdown matches all 106 source pages and the current appendix')
    else:
        target.write_text(text, encoding='utf-8')
        print('Wrote complete_specification.md')


if __name__ == '__main__':
    main()
