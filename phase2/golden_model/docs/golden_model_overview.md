# Golden Model Overview

## Purpose

`trecap-golden` is the deterministic software reference and artifact authority for the T-RECAP Phase 2 core. Its job is not to look like a demo and not to be convenient for one simulation run. Its job is to produce bit-accurate, reviewable, hashable artifacts that RTL simulation and BRAM replay can consume without ambiguity.

The repository owns these functions:

- coefficient generation for the quantized periodic square-root Hann window and forward/inverse twiddle tables;
- deterministic vector generation from reviewed vector configurations;
- the C++ bit-accurate STFT/WOLA selective-suppression model;
- canonical `memh`, CSV, and JSON artifact emission;
- artifact checking, canonical SHA-256 hashing, and release freezing;
- no-suppression quality-bound generation.

It does not own RTL module implementation, SystemVerilog verification architecture, HPS Ethernet software, PC dashboard code, live audio, ADC integration, or board-specific telemetry.

## Current baseline

The active mathematical baseline is Phase 2 Core Revision J.

| Field | Baseline |
|---|---:|
| External sample width `N` | 12 signed bits |
| FFT length `L` | 256 |
| Radix-2 stages `P = log2(L)` | 8 |
| Hop size `H = L/2` | 128 |
| Fractional precision `F` | 15 |
| Scheduling cushion `G` | 128 |
| Exact causal delay `D = L + G` | 384 samples |
| Default tail policy | `full_tail` |
| DC protection | `PROTECT_DC = 1` |
| Nyquist protection | `PROTECT_NYQ = 0` |
| Threshold domain | unsigned magnitude-squared `THR2` |
| Forward FFT baseline | custom radix-2 DIT, bit-reversed input, natural output |
| IFFT baseline | custom radix-2 DIT, unscaled inverse |

The most important consequence: Phase 2 is not the Phase 1 exact-lossless Haar model. At `THR2 = 0`, Phase 2 should keep every eligible bin, but it is still a quantized fixed-point STFT/WOLA system. The expected behavior is deterministic near-lossless reconstruction, not mathematical identity.

## Repository layers

The root scaffold intentionally separates contract, model, tooling, artifact, and quality layers.

```text
contract layer   -> spec/, schemas/, generated config
model layer      -> include/, src/
tooling layer    -> tools/, python/
artifact layer   -> artifacts/, manifests/
quality layer    -> tests/, ci/, release reproducibility
```

This split prevents the usual failure mode where constants are duplicated in C++, Python, RTL, and dashboard code. The golden repository should consume generated contract files and should write artifacts whose schemas and hashes can be checked without re-running hidden logic.

## Dataflow owned by this repo

The production artifact flow is:

```text
spec/generated/core_config.json
        |
        v
tools/gen_coeffs.py ---------------> artifacts/coefficients/*.memh
        |                              artifacts/coefficients/coeff_manifest.json
        |
        v
tools/gen_vectors.py --------------> artifacts/test_vectors/test_vectors.json
                                       artifacts/test_vectors/<vector>/x_in.memh
                                       artifacts/test_vectors/<vector>/config.json
        |
        v
C++ golden model -------------------> artifacts/golden/<vector>/y_out.memh
                                       artifacts/golden/<vector>/frame_stats.csv
                                       artifacts/golden/<vector>/metrics.json
                                       optional bin_stats.csv
        |
        v
tools/artifact_check.py -----------> row-count, schema, and hash validation
        |
        v
tools/make_quality_bounds.py ------> artifacts/manifests/quality_bounds.json
        |
        v
tools/freeze_release.py -----------> artifacts/manifests/frozen_release_manifest.json
```

Generated scratch output belongs in `runs/` or `out/`. Only reviewed, checked, frozen files belong under `artifacts/`.

## Artifact authority rule

After a coefficient table or stream vector is frozen, the artifact file and its canonical SHA-256 hash are the authority. The generator equation remains documentation, but a regenerated table or vector is not accepted unless its canonical hash matches the frozen manifest.

This rule exists because different math libraries, constants for pi, floating-point rounding paths, JSON parsing behavior, or platform-specific formatting can generate mathematically close but bit-different outputs. For signoff, bit-different means not the same artifact.

## How this repo interacts with RTL

RTL should consume frozen artifacts, not reimplement coefficient generation.

| RTL need | Golden artifact source |
|---|---|
| Window ROM contents | `artifacts/coefficients/window_qw.memh` |
| Forward twiddle ROM real/imag | `twiddle_re.memh`, `twiddle_im.memh` |
| Inverse twiddle ROM real/imag | `twiddle_inv_re.memh`, `twiddle_inv_im.memh` |
| BRAM replay input | `artifacts/test_vectors/<vector>/x_in.memh` |
| Expected output | `artifacts/golden/<vector>/y_out.memh` |
| Expected frame stats | `frame_stats.csv` |
| Expected aggregate metrics | `metrics.json` |
| Optional bin-level debug | `bin_stats.csv` |

The golden model should never depend on RTL code. RTL may depend on golden artifacts for replay and comparison.

## Required command path

The root `Makefile` provides the public workflow names. The docs should match these names.

```bash
make check-layout
make setup
make configure
make build
make test
make gen-config
make coeffs
make vectors
make golden
make check-artifacts
make quality-bounds
make freeze-release
make reproduce-release
make package-artifacts
```

Targets that need future implementation scripts should fail clearly until the script exists. A clear fail is better than a fake pass because signoff artifacts are safety-critical for the project.

## Development status categories

Use these labels consistently in issues and release notes.

| Label | Meaning |
|---|---|
| `contract` | schemas, generated config, constants, width rules |
| `arithmetic` | saturation, shifts, rounding, fixed-point products |
| `coefficients` | window/twiddle generation and manifests |
| `vectors` | vector configs, generator determinism, freeze process |
| `model` | C++ bit-accurate STFT/WOLA implementation |
| `artifacts` | writers, checkers, hashes, schemas, CSV/JSON contracts |
| `quality` | no-suppression quality bounds and regression self-checks |
| `release` | frozen manifests, reproducibility, packaging |
| `legacy` | Phase 1 quarantine and deprecated documents |

## Acceptance checklist for this repository

A golden-model repository cut is acceptable only when:

1. root layout passes `make check-layout`;
2. generated config files exist or the generation target fails with a clear missing-tool error;
3. coefficient generation produces all five coefficient `memh` files and `coeff_manifest.json`;
4. vector generation produces `test_vectors.json`, each vector `x_in.memh`, and each vector `config.json`;
5. the C++ model emits `y_out.memh`, `frame_stats.csv`, and `metrics.json` for every frozen vector;
6. `artifact_check.py` verifies canonical `memh`, row counts, schemas, and hashes;
7. no-suppression quality numbers are generated by the frozen model, not invented by hand;
8. `freeze_release.py` records canonical artifact hashes in a release manifest;
9. `reproduce_release` can regenerate and compare a release bit-for-bit;
10. Phase 1 code remains in `legacy/phase1/` and cannot be pulled into this repo by default build targets.

## Common wrong designs

Do not do these:

- do not keep all golden logic in one long `golden_model.cpp` file;
- do not use Python as a second independent arithmetic model that can drift from C++;
- do not compute SHA-256 over raw host file bytes without canonicalizing the logical integer vector;
- do not accept uppercase hex, CRLF, comments, blank lines, or variable-width `memh` in signoff artifacts;
- do not silently saturate or wrap internal values unless the spec explicitly defines that behavior;
- do not let coefficient ROM contents be generated inside RTL;
- do not freeze a vector unless all generator parameters, threshold, protection flags, rounding mode, tail policy, and hashes are recorded.

## Reading order for new developers

1. `README.md`
2. `docs/golden_model_overview.md`
3. `docs/arithmetic_contract.md`
4. `docs/fixed_point_widths.md`
5. `docs/stft_wola_contract.md`
6. `docs/fft_ifft_contract.md`
7. `docs/artifact_contract.md`
8. `docs/canonical_memh_hashing.md`
9. `docs/vector_freeze_process.md`
10. `docs/quality_bounds_process.md`
11. `docs/release_process.md`
12. `docs/dev_guide.md`

