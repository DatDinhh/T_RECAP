"""Verify the published overview bundle without replaying hardware or timing tests."""
import hashlib
import json
from pathlib import Path

root = Path(__file__).resolve().parent
manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
expected = {entry["path"]: entry for entry in manifest["files"]}
actual = {p.relative_to(root).as_posix() for p in root.rglob("*")
          if p.is_file() and p.name != "manifest.json" and "__pycache__" not in p.parts}
if actual != set(expected):
    raise SystemExit("Overview file inventory does not match the manifest")
for name, entry in expected.items():
    path = (root / name).resolve()
    if not path.is_relative_to(root) or path.is_symlink():
        raise SystemExit("Invalid overview path")
    content = path.read_bytes()
    if len(content) != entry["bytes"] or hashlib.sha256(content).hexdigest() != entry["sha256"]:
        raise SystemExit("Overview hash mismatch: " + name)
print("Overview integrity: " + str(len(expected)) + " files verified. No hardware or performance tests run.")
