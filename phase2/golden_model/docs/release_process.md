# Release Process

## Purpose

A release freezes a coherent set of source contracts, generated config, coefficients, vectors, golden outputs, metrics, quality bounds, and canonical hashes. The purpose is reproducibility. Another developer should be able to check out the release, run the documented commands, and reproduce the same artifact hashes.

## Release outputs

A complete release includes:

```text
artifacts/coefficients/*.memh
artifacts/coefficients/coeff_manifest.json
artifacts/test_vectors/test_vectors.json
artifacts/test_vectors/<vector>/x_in.memh
artifacts/test_vectors/<vector>/config.json
artifacts/golden/<vector>/y_out.memh
artifacts/golden/<vector>/frame_stats.csv
artifacts/golden/<vector>/metrics.json
artifacts/golden/<vector>/bin_stats.csv       # if required
artifacts/manifests/quality_bounds.json
artifacts/manifests/artifact_index.json
artifacts/manifests/stream_hashes.json
artifacts/manifests/frozen_release_manifest.json
```

The package target may also create an archive under `out/`.

## Release recipe configs

Reviewed release recipes live under:

```text
configs/releases/
├── phase2_revJ_dev.json
└── phase2_revJ_signoff.json
```

These two files are written and reviewed by humans. They are not generated artifacts. They declare release intent, suite selection, required gates, package policy, and the exact freeze command to use. The generated files are the release outputs under `artifacts/manifests/`, especially `artifact_index.json` and `frozen_release_manifest.json`.

`phase2_revJ_dev.json` is for fast development and CI smoke checks. It is not RTL or board signoff. `phase2_revJ_signoff.json` is the full Revision J signoff recipe, but it remains `signoff_ready: false` until the golden artifacts, quality bounds, RTL replay, and BRAM replay evidence are all reviewed.

Validate the recipes with:

```bash
make check-release-configs
```

Do not place generated artifact hashes in these recipe configs. Hashes belong in `test_vectors.json`, per-vector `config.json`, `metrics.json`, `quality_bounds.json`, `artifact_index.json`, and `frozen_release_manifest.json`.

## Version naming

Use release names that identify project phase, spec revision, and intent.

Examples:

```text
phase2-revJ-golden-v0.1.0-dev
phase2-revJ-golden-v1.0.0-signoff
phase2-revJ-golden-v1.0.1-artifact-fix
```

Recommended semantic meaning:

| Version part | Meaning |
|---|---|
| major | incompatible contract/artifact change |
| minor | new vectors, new tooling, compatible manifest additions |
| patch | bug fixes that preserve contract intent |

## Pre-release gates

Before `freeze-release`, run:

```bash
make check-layout
make setup
make build
make test
make coeffs
make vectors
make golden
make check-artifacts
make quality-bounds
make check-artifacts
```

The second `check-artifacts` matters because quality-bound generation adds or modifies manifest files.

## Freeze command

```bash
make freeze-release
```

Expected output:

```text
artifacts/manifests/frozen_release_manifest.json
```

The manifest should record:

- release name;
- spec revision identifiers;
- git commit if available;
- tool versions;
- schema versions;
- generator version and source hash;
- coefficient artifact hashes;
- vector input hashes;
- golden output hashes;
- frame/metric artifact hashes;
- quality-bound hash;
- artifact row counts;
- build environment summary.

## Reproducibility check

After freezing, run:

```bash
make reproduce-release
```

This target should regenerate into a temporary location, canonicalize artifacts, and compare hashes against `frozen_release_manifest.json`.

A release that cannot reproduce is not a release.

## Artifact index

`artifact_index.json` should be a machine-readable directory of artifact paths and their roles.

Example shape:

```json
{
  "schema": "trecap_artifact_index_v1",
  "artifacts": [
    {
      "path": "artifacts/coefficients/window_qw.memh",
      "kind": "coefficient",
      "signed": false,
      "width": 16,
      "rows": 256,
      "sha256": "..."
    }
  ]
}
```

The index is useful for CI and external consumers that do not want to infer artifact meaning from path names only.

## Changelog requirements

Every release must update `CHANGELOG.md` with:

- release name and date;
- spec revision basis;
- added/removed/modified vector names;
- coefficient hash changes;
- golden output hash changes;
- quality-bound changes;
- known limitations;
- reproducibility status.

Do not write vague entries such as "updated files". Release notes should help debug future hash drift.

## Package command

```bash
make package-artifacts
```

Recommended archive content:

```text
README.md
CHANGELOG.md
docs/
spec/generated/
spec/schemas/
artifacts/
```

Do not include `runs/`, local build directories, `.venv`, or editor files.

## CI release gates

CI should check:

1. formatting/lint smoke;
2. C++ unit tests;
3. Python unit tests;
4. artifact checker;
5. release manifest schema;
6. reproducibility against frozen manifest;
7. no Phase 1 files at root;
8. no placeholder strings in frozen JSON;
9. no non-canonical `memh` files.

## Handling hash drift

If a hash changes unexpectedly:

1. stop the release;
2. identify the earliest changed artifact in the flow;
3. compare canonical logical values, not raw files first;
4. check generator source hash;
5. check coefficient hashes;
6. check schema/config changes;
7. check platform-dependent math calls;
8. only then regenerate downstream artifacts intentionally.

Never update the manifest first. The manifest records truth; it does not define truth by itself.

## Emergency artifact fix

Sometimes an artifact has formatting damage but the logical vector is identical. Example: CRLF line endings introduced by an editor.

Policy:

- if canonical hash after normalization matches the old hash, fix formatting and record a patch release note;
- if logical canonical hash changes, treat it as a real artifact change and run the full freeze process.

## Deprecating a release

Do not delete old releases without traceability. Mark them deprecated and explain why.

Common reasons:

- wrong delay assumption;
- wrong finite-tail policy;
- wrong rounding mode;
- bad coefficient table;
- missing stream hashes;
- schema too weak for signoff.

The root README already warns that older Phase 2 drafts using `D = L` are historical only. Current baseline is `D = L + G = 384`.

## Release signoff checklist

- [ ] `make check-layout` passes;
- [ ] root docs match current Makefile targets;
- [ ] all coefficient files present and hashed;
- [ ] all vector input files present and hashed;
- [ ] all golden outputs present and hashed;
- [ ] CSV row counts are exact;
- [ ] JSON schemas validate;
- [ ] wide integers are decimal strings;
- [ ] no placeholder strings remain;
- [ ] `quality_bounds.json` generated and checked;
- [ ] `frozen_release_manifest.json` generated;
- [ ] `make reproduce-release` passes;
- [ ] `CHANGELOG.md` updated;
- [ ] artifact package created under `out/`;
- [ ] release tag name matches release manifest.

