# Reference import and hash-chain repair v69

## Result

v69 replaces the normalized-but-stale reference hashes with two explicit,
acyclic release DAGs:

```text
embedded leaves
  -> sw/reference_model/artifacts/manifests/artifact_index.json
  -> sw/reference_model/artifacts/manifests/frozen_release_manifest.json

promoted leaves
  -> artifacts/manifests/artifact_index.json
  -> artifacts/manifests/frozen_release_manifest.json

embedded tree + 39 verbatim promotions
  -> artifacts/manifests/reference_import_manifest.json
```

The embedded DAG uses `artifacts/golden/`. The architecture DAG uses
`artifacts/reference_outputs/`. The two index/release manifests are therefore
derived independently; they are not mislabeled as verbatim promotions.

## Byte policy

The earlier import normalized text files to LF but retained raw SHA-256 values
from CRLF bytes. Five stale hashes then propagated through the index and
release manifests.

v69 does not pretend those bytes were unchanged. It publishes a new
`0.1.0-dev.1` LF-derived development release and regenerates the complete
downstream DAG. All JSON writers explicitly use LF.

Future ZIP imports preserve every included payload byte exactly. They do not
normalize line endings, add a final newline, reserialize JSON, or infer the
expected archive hash from the archive itself.

## Source provenance

The available `trecap-golden-new.zip` was truncated and lacked a valid central
directory. Only 11 of 210 old project files could be recovered directly. The
current embedded proxy is internally authenticated, but byte identity with the
other 199 source files cannot be proven.

The truncated archive is not bundled in v69. The integrated specification PDF
is also not bundled; `docs/specs/README.md` records the expected import name
and historical hash, but does not substitute for the missing PDF.

The v3 manifest therefore records:

```text
provenance_status = embedded_proxy_unverified_source_archive
source.verified   = false
```

This is deliberate. The normal integrity check passes, while the signoff gate
requiring a verified source archive fails closed.

## Checker contract

`artifact_check.py` fails on:

- missing `jsonschema` or a missing/invalid schema;
- duplicate JSON keys, UTF-8 BOMs, or non-finite JSON numbers;
- missing, extra, duplicate, unsafe, escaping, or symlinked artifact paths;
- raw or canonical hash mismatch;
- coefficient metadata/source-bundle mismatch;
- vector/config/metrics/frame/bin inconsistency;
- incomplete artifact-index inventory;
- release/index set or named-hash mismatch;
- import-manifest mirror, file count, tree digest, promotion map, source, or
  destination mismatch.

The default mode requires both `artifact_index.json` and
`frozen_release_manifest.json`. `--allow-unfrozen` is an explicit pre-freeze
construction mode only; `freeze_release.py` always follows it with a default
post-freeze check.

## Commands

Install the locked reference dependencies, then check both DAGs and the import
chain:

```bash
python3 -m pip install -r sw/reference_model/requirements.lock
make check-reference-import
make check-artifacts
```

The committed development release uses a deterministic timestamp. Re-freezing
and reproducing it must use the same value:

```bash
make -C sw/reference_model freeze-release \
  CREATED_UTC=2026-07-24T06:10:00Z
make -C sw/reference_model reproduce-release \
  CREATED_UTC=2026-07-24T06:10:00Z
```

`reproduce-release` freezes a temporary artifact copy and requires both
`artifact_index.json` and `frozen_release_manifest.json` to match byte-for-byte.

Refresh the current proxy manifest after an intentional embedded/promoted file
change:

```bash
make refresh-reference-import
```

The signoff provenance gate requires the independently hash-pinned clean
archive explicitly:

```bash
make check-reference-source-verified \
  REFERENCE_SOURCE_ARCHIVE=/path/to/clean-reference.zip
```

It remains red for the current embedded proxy even if an unrelated archive is
supplied.

Import a future complete source archive into a fresh staging directory:

```bash
python3 scripts/reference_import.py stage \
  --archive T_RECAP_Phase2_Reference_Model_RevJ_0.1.0-dev.1.zip \
  --expected-sha256 <independently-supplied-64-hex-digest> \
  --output /fresh/stage \
  --promotion-map config/reference_import_promotions.json
```

Before creating output, `stage` validates the independent SHA-256, complete ZIP
central directory, every member CRC, resource limits, archive root, portable
paths, collisions, encryption, symlinks, and special-file types. Any failure
leaves no published staging tree.

The historical v69 runner is no longer shipped. For the current RTL artifact
regression on Windows, use the v70b superset:

```powershell
& ".\scripts\windows\run_c0_golden_v70.ps1" `
  -Repo (Resolve-Path ".").Path `
  -ModelSimExe "D:\Quartus\modelsim_ase\win32aloem\modelsim.exe"
```

The integrity preflight must emit both:

```text
REFERENCE_EMBEDDED_DAG_PASS
REFERENCE_ROOT_IMPORT_DAG_PASS
```

## Non-claims

This repair closes internal artifact and import integrity. It does not prove
the truncated original ZIP, supply the missing integrated PDF, add missing
RTL/board signoff evidence, or make `phase2_revJ_signoff.json` ready.
