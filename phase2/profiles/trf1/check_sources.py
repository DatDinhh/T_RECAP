"""Check published RF source identities without a simulator or board."""
from pathlib import Path
import hashlib
import json

HERE = Path(__file__).resolve().parent


def main():
    manifest = json.loads((HERE / 'source_manifest.json').read_text(encoding='utf-8'))
    names = set()
    exact = 0
    for row in manifest['files']:
        relative = Path(row['path'])
        target = (HERE / relative).resolve()
        if relative.is_absolute() or not target.is_relative_to(HERE.resolve()) or row['path'] in names:
            raise ValueError('Invalid or duplicate source manifest path')
        names.add(row['path'])
        actual = hashlib.sha256(target.read_bytes()).hexdigest()
        if actual != row['published_sha256']:
            raise ValueError('Published source mismatch: ' + row['path'])
        if row['disposition'] == 'Exact original bytes':
            if actual != row['original_sha256']:
                raise ValueError('Original source mismatch: ' + row['path'])
            exact += 1
    print(json.dumps(dict(status='PASS_RF_SOURCE_IDENTITIES', files=len(names),
                          exact_original_files=exact, documented_transformations=len(names)-exact,
                          hardware_access=False)))


if __name__ == '__main__':
    main()
