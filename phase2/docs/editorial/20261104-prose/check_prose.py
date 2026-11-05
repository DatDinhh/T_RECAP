"""Check reader-facing prose without editing source or historical evidence."""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import re


FORMATS = {'.md', '.rst', '.tex', '.html'}
FORBIDDEN = {';': 'semicolon', '\u2013': 'en_dash', '\u2014': 'em_dash'}
EXCLUSIONS = {
    'phase2/platform/de1soc/linux/THIRD_PARTY_NOTICES.md':
        'Unmodified third-party legal notice. Original punctuation is retained.',
}


def blank(text: str) -> str:
    return ''.join('\n' if c == '\n' else ' ' for c in text)


def mask_pattern(text: str, pattern: str, flags: int = 0) -> str:
    return re.sub(pattern, lambda m: blank(m.group()), text, flags=flags)


def markdown_prose(text: str) -> str:
    lines = text.splitlines(keepends=True)
    fence = None
    result = []
    for line in lines:
        match = re.match(r'^\s*(`{3,}|~{3,})', line)
        if match:
            if fence is None:
                fence = match.group(1)[0]
            elif match.group(1)[0] == fence:
                fence = None
            result.append(blank(line))
        elif fence is not None:
            result.append(blank(line))
        else:
            result.append(line)
    text = ''.join(result)
    text = mask_pattern(text, r'(`+)([^`]*?)\1', re.DOTALL)
    text = mask_pattern(text, r'<!--.*?-->', re.DOTALL)
    text = mask_pattern(text, r'<(?:script|style|pre|code)\b[^>]*>.*?</(?:script|style|pre|code)\s*>', re.DOTALL | re.IGNORECASE)
    text = mask_pattern(text, r'<[^>\n]+>')
    text = mask_pattern(text, r'(?<=\])\([^\n]*?\)')
    text = mask_pattern(text, r'^\s*\[[^\]]+\]:\s*\S+', re.MULTILINE)
    text = mask_pattern(text, r'https?://[^\s)<>]+')
    return mask_pattern(text, r'&(?:#\d+|#x[0-9a-fA-F]+|[a-zA-Z]+);')


def tex_prose(text: str) -> str:
    # Verbatim material and TikZ paths are executable syntax. Their captions
    # outside these environments remain in the prose scan.
    text = mask_pattern(text, r'\\begin\{(lstlisting|verbatim\*?|minted|tikzpicture)\}.*?\\end\{\1\}', re.DOTALL)
    text = mask_pattern(text, r'(?<!\\)%[^\n]*')
    text = mask_pattern(text, r'\\(?:verb\*?|lstinline)([^\w\s]).*?\1')
    text = mask_pattern(text, r'\\(?:texttt|url|nolinkurl|path|epath)\{(?:[^{}]|\{[^{}]*\})*\}')
    text = mask_pattern(text, r'\\href\{[^{}]*\}')
    return mask_pattern(text, r'\\;')


class BodyProse(HTMLParser):
    def __init__(self, text: str):
        super().__init__(convert_charrefs=True)
        self.text = text
        self.ignored = []
        self.rows = []

    def handle_starttag(self, tag, attrs):
        if tag in {'script', 'style', 'pre', 'code'}:
            self.ignored.append(tag)

    def handle_endtag(self, tag):
        if self.ignored and tag == self.ignored[-1]:
            self.ignored.pop()

    def handle_data(self, data):
        if not self.ignored:
            self.rows.append((self.getpos()[0], data))


def scan(path: Path, text: str):
    if path.suffix == '.html':
        parser = BodyProse(text)
        parser.feed(text)
        rows = parser.rows
    else:
        source = tex_prose(text) if path.suffix == '.tex' else markdown_prose(text)
        rows = list(enumerate(source.splitlines(), 1))
    found = []
    for first, row in rows:
        for offset, line in enumerate(row.splitlines()):
            counts = {name: line.count(char) for char, name in FORBIDDEN.items() if char in line}
            if counts:
                found.append({'line': first + offset, 'counts': counts, 'text': line.strip()[:240]})
    return found


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo-root', type=Path, default=Path(__file__).resolve().parents[4])
    parser.add_argument('--check-ledger', action='store_true')
    parser.add_argument('--json-output', type=Path)
    args = parser.parse_args()
    root = args.repo_root.resolve()
    files = sorted(p for p in root.rglob('*') if p.is_file() and p.suffix.lower() in FORMATS and '.git' not in p.relative_to(root).parts)
    issues = []
    excluded = []
    scanned = 0
    for path in files:
        name = path.relative_to(root).as_posix()
        text = path.read_text(encoding='utf-8-sig')
        if name in EXCLUSIONS:
            excluded.append({'path': name, 'reason': EXCLUSIONS[name], 'raw_counts': {v: text.count(k) for k, v in FORBIDDEN.items()}})
            continue
        scanned += 1
        for item in scan(path, text):
            issues.append({'path': name, **item})
    ledger_failures = []
    if args.check_ledger:
        ledger = json.loads((Path(__file__).parent / 'manifest.json').read_text(encoding='utf-8'))
        records = ledger['prose_edits'] + ledger['current_publication_metadata'] + ledger['regenerated_atlas_artifacts']
        records += ledger.get('restyled_verification_previews', [])
        for row in records:
            path = root / row['path']
            actual = hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None
            if actual != row['current_sha256']:
                ledger_failures.append(row['path'])
    result = {'status': 'PASS' if not issues and not ledger_failures else 'FAIL',
              'scanned_authored_text_files': scanned, 'remaining_prose_findings': len(issues),
              'findings': issues, 'explicit_legal_exclusions': excluded,
              'ledger_hash_failures': ledger_failures,
              'scope': 'Markdown, RST, LaTeX prose and HTML text nodes. Protected code, markup, script, style, TeX listing and TikZ syntax are excluded. Machine JSON, logs and executable source are not prose documents.'}
    if args.json_output:
        args.json_output.write_text(json.dumps(result, indent=2, ensure_ascii=True) + '\n', encoding='utf-8')
    print(json.dumps(result, indent=2, ensure_ascii=True))
    return 0 if result['status'] == 'PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
