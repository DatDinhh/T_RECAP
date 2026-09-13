# Developer Guide

## Purpose

This guide explains how to work in `trecap-golden` without breaking the artifact contract. It assumes the reader is new to the project but comfortable using a terminal.

## First setup

From repository root:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.lock
pre-commit install
```

Then check the scaffold:

```bash
make check-layout
```

Build C++ skeleton:

```bash
make configure
make build
make test
```

Some artifact targets intentionally fail until their implementation scripts exist. That is expected for the scaffold. Do not replace a clear failure with a fake success.

## Daily workflow

Typical development loop:

```bash
make check-layout
make build
make test
make lint-basic
```

When artifact tooling exists:

```bash
make coeffs
make vectors
make golden
make check-artifacts
```

Before release:

```bash
make quality-bounds
make freeze-release
make reproduce-release
make package-artifacts
```

Suite-specific debug flow:

```bash
make check-suite-configs
make vectors-suite SUITE=configs/suites/debug_near_threshold.json
make golden-suite SUITE=configs/suites/debug_near_threshold.json
make check-artifacts
```

## Where to put things

| Work item | Directory |
|---|---|
| C++ public API | `include/trecap_golden/` |
| C++ implementation | `src/` |
| C++ command-line entry point | `tools/` |
| Python package code | `python/trecap_golden/` |
| Python CLI wrapper | `python/trecap_golden/cli/` or `tools/` |
| vector configs | `configs/vectors/` |
| suite configs | `configs/suites/` |
| release configs | `configs/releases/` |
| frozen coefficients | `artifacts/coefficients/` |
| frozen input streams | `artifacts/test_vectors/` |
| frozen golden outputs | `artifacts/golden/` |
| release manifests | `artifacts/manifests/` |
| temporary runs | `runs/` |
| packaged outputs | `out/` |
| old Phase 1 files | `legacy/phase1/` |

The reviewed suite files are `smoke.json`, `signoff_minimal.json`, `signoff_full.json`, and `debug_near_threshold.json`. A suite is a selector over reviewed vector configs, not a replacement for `test_vectors.json`. Do not put generator parameters directly into suite files; put them in the class-oriented bundles under `configs/vectors/*.json`, then reference the concrete vector by name under `vector_selection`.

The required vector-config bundle files are:

```text
configs/vectors/
├── zero_Ns4096_thr0.json
├── no_suppression_multitone_thr0.json
├── impulse_step.json
├── exact_bin_tone_sweep.json
├── off_bin_tone_sweep.json
├── near_threshold_multitone.json
├── noise_only_xorshift32.json
├── high_amplitude_headroom.json
└── short_finite_stream.json
```

These are reviewed generator inputs. They are not frozen signoff manifests. The frozen authority is still `artifacts/test_vectors/test_vectors.json` plus canonical `x_in.memh` / `y_out.memh` hashes after the artifact flow runs.

A vector bundle uses schema `trecap_phase2_vector_bundle_v1` and carries one or more vector instances under `vectors`. The bundle filename names the signoff class. The instance names inside the bundle are still the frozen artifact identities.

## Naming rules

Use stable, descriptive names.

Good file names:

```text
fixed_point.cpp
fft_radix2_int.cpp
stft_wola_model.cpp
artifact_checker.py
near_threshold_multitone_Ns4096_thr_custom.json
```

Bad file names:

```text
new.cpp
final.py
test2.json
paul_debug_fixed.cpp
```

## How to add a C++ arithmetic helper

1. Add declaration in `include/trecap_golden/...`.
2. Add implementation in `src/...`.
3. Add unit tests in `tests/cpp/`.
4. Confirm the helper uses the contract in `docs/arithmetic_contract.md`.
5. Run:

```bash
make build
make test
```

Do not use default C++ rounding or signed division behavior without proving it matches the contract.

## How to add a vector

1. Add the new vector instance to the correct class bundle under `configs/vectors/`, or create a new reviewed bundle if it is a new class.
2. Use exact parameters, not floating shortcuts. Frequencies use `f_num`/`f_den`; phases use decimal-string `phase_rad`.
3. Run:

```bash
make vectors
```

4. Inspect generated `x_in.memh` and `config.json`.
5. Run:

```bash
make golden
make check-artifacts
```

6. Update release/changelog only after review.

Do not hand-edit `x_in.memh` after generation. Change the generator config and regenerate.

## How to debug a mismatch

Follow this order:

1. Check active config: `N`, `L`, `H`, `F`, `G`, `D`, `tail_policy`.
2. Check coefficient hashes.
3. Check `x_in.memh` canonical hash.
4. Check frame count and `Ny`.
5. Compare `frame_stats.csv` row by row.
6. If present, compare `bin_stats.csv` for first mismatching frame/bin.
7. Compare `y_out.memh` samples.
8. Check metrics last.

Do not start by staring at a late time-domain mismatch. It is usually downstream of a smaller earlier error.

## Common beginner mistakes

### Mistake 1: assuming `THR2 = 0` means exact identity

In Phase 2, `THR2 = 0` means no eligible bins are suppressed. It does not remove quantized windowing, twiddle quantization, FFT/IFFT rounding, WOLA accumulation, or output rounding. Expect deterministic near-lossless behavior under quality bounds.

### Mistake 2: hashing the raw file bytes

Canonical hashes are computed over the logical integer vector serialized as fixed-width lowercase hex plus LF. See `docs/canonical_memh_hashing.md`.

### Mistake 3: using signed 16-bit twiddles

Baseline twiddles are signed 17-bit because `+1.0` and `-1.0` must both be representable.

### Mistake 4: stopping after `Ns` input samples

Full-tail signoff continues zero-flush ticks until `Ny` outputs have been emitted.

### Mistake 5: using Python as a second arithmetic source of truth

Python orchestration is fine. Python schema validation and hashing are fine. But the bit-accurate model should not silently diverge from the C++ model.

## Commit hygiene

Before committing:

```bash
make check-layout
make build
make test
make lint-basic
```

When artifact tooling exists, also run:

```bash
make check-artifacts
```

Commit generated frozen artifacts only when they are intended to be reviewed and frozen. Do not commit random `runs/` outputs.

## Documentation update rule

If you change any of these, update docs in the same pull request:

- arithmetic behavior;
- width schedule;
- FFT/IFFT behavior;
- STFT/WOLA finite-stream policy;
- artifact schema;
- hash rule;
- vector freeze process;
- release process;
- Makefile target names.

Documentation drift is a real bug in this project because the repo is contract-heavy.

## Minimal local sanity commands

These commands should be safe on a clean scaffold:

```bash
make check-layout
cmake -S . -B build -DCMAKE_BUILD_TYPE=RelWithDebInfo
cmake --build build
ctest --test-dir build --output-on-failure
```

Artifact-producing commands will become active as tools are implemented:

```bash
make coeffs
make vectors
make golden
make check-artifacts
```

## Review checklist

For any nontrivial change, ask:

- Does this duplicate a constant already owned by `spec/generated/`?
- Does this change any canonical artifact bytes?
- Does this change any logical artifact values?
- Does this require a schema update?
- Does this require quality-bound regeneration?
- Does this require a new release manifest?
- Does this accidentally pull Phase 1 code into active Phase 2 paths?

If the answer is uncertain, do not merge yet.



## Public C++ header contract

The first C++ implementation layer lives in `include/trecap_golden/`. Treat these files as the audited arithmetic surface for the rest of the golden model:

- `signed_int.hpp`: two's-complement encoding, sign extension, width-fit checks.
- `rounding.hpp`: `asr`, `rnd_shr`, `rnd2`, and `qcoef`.
- `saturation.hpp`: signed saturation and range-checked assignments.
- `widths.hpp`: Revision J baseline constants and derived width schedule.
- `q_format.hpp`: fixed-point format metadata and product scaling helpers.
- `complex_int.hpp`: integer complex arithmetic, complex multiply, Hermitian pair canonicalization, and `mag2`.
- `coeffs.hpp`: coefficient table metadata and initial deterministic coefficient generation helpers.
- `twiddles.hpp`: forward/inverse twiddle table views, bit reversal, and FFT twiddle indexing.
- `window.hpp`: periodic sqrt-Hann table view plus analysis/synthesis window operators.
- `fft_radix2_int.hpp`: normalized radix-2 DIT FFT matching the Revision J butterfly schedule.
- `ifft_radix2_int.hpp`: unscaled radix-2 DIT IFFT matching the Revision J inverse schedule.
- `hermitian.hpp`: full-spectrum canonicalization and symmetry checks.
- `mask.hpp`: full-precision `mag2 < THR2` masking, protection rules, frame/bin stats, and decimal aggregate counters.
- `finite_stream.hpp`: full-tail zero extension, input ring, OLA ring, and time-error metrics.
- `stft_wola_model.hpp`: public integration API for frame analysis, mask, synthesis, WOLA, and finite-stream run output; the runtime definitions live in `src/stft_wola_model.cpp`.

Do not add alternate arithmetic operators in tool files. Extend this header layer first, then add source files or CLI tools that consume it.


## Header implementation boundary

The public C++ headers expose the core operator boundaries used by the compiled C++ source layer: coefficient/twiddle generation, windowing, normalized radix-2 FFT, unscaled radix-2 IFFT, Hermitian canonicalization, magnitude-squared masking, finite-stream timing, and the STFT/WOLA runner. Keep these boundaries intact. Do not collapse them into one `golden_model.cpp`; that would make one-bit RTL drift much harder to localize.

## Artifact I/O header layer

The public C++ include layer now includes the artifact-facing headers used by the active CLI tools:

- `metrics.hpp` converts aggregate golden-model counters into schema-compatible decimal-string fields and exposes derived ratios used for display only.
- `generators.hpp` implements the frozen Revision J input-vector generator families before stream hashes become the signoff authority.
- `memh.hpp` implements fixed-width lowercase hexadecimal LF-only signed and unsigned memory-file encoding.
- `canonical_hash.hpp` computes SHA-256 over canonical logical integer-vector serialization, not host raw bytes.
- `csv_io.hpp` writes and checks the frozen `frame_stats.csv` and `bin_stats.csv` headers and row ordering.
- `json_io.hpp` centralizes JSON escaping and common schema fragments.
- `artifact_writer.hpp` writes coefficient artifacts and per-vector artifacts from the C++ model.
- `artifact_checker.hpp` checks line counts, CSV data rows, and canonical memh hashes.
- `version.hpp` exposes golden-model version and schema/contract string constants.

These headers are the library layer consumed by the implemented command-line tools under `tools/`.

## Source implementation boundary

The `src/` layer mirrors both the arithmetic/coefficient headers and the STFT/WOLA algorithm headers. Keep these rules:

- Keep trivial `constexpr` primitives in headers when tests or schema checks need compile-time evaluation.
- Put runtime-heavy definitions in `src/*.cpp`, especially functions that use host math libraries, allocation, or checked arithmetic branches.
- Do not introduce duplicate constants in source files. Pull contract values from `CoreConfig`, `WidthConfig`, and the generated-config layer when that layer is built.
- A source file is not allowed to silently reinterpret arithmetic policy. Rounding, saturation, signedness, and coefficient widths must match the public header contract.



## STFT/WOLA source implementation layer

The second source layer moves the runtime-heavy STFT/WOLA path into compiled translation units: `twiddles.cpp`, `window.cpp`, `fft_radix2_int.cpp`, `ifft_radix2_int.cpp`, `hermitian.cpp`, `mask.cpp`, `finite_stream.cpp`, and `stft_wola_model.cpp`. These files implement the same operator boundaries exposed by the public headers. Do not collapse them into a monolithic model file. The separation is intentional because bit drift against RTL has to be localized to a specific operator: coefficient table, windowing, FFT stage, canonicalization, threshold/mask, IFFT, WOLA, or finite-stream scheduling.


## Artifact I/O source implementation layer

The artifact-facing runtime code now lives in compiled source files instead of inline-only headers:

- `metrics.cpp` owns metric string conversion and display-only ratios.
- `generators.cpp` owns Revision J generator execution before vectors are frozen by hash.
- `memh.cpp` owns canonical signed/unsigned memory-file serialization and parsing.
- `csv_io.cpp` owns exact CSV emission and row-count checks.
- `json_io.cpp` owns common JSON fragments used by manifests and configs.
- `canonical_hash.cpp` owns the internal SHA-256 implementation.
- `artifact_writer.cpp` owns coefficient and vector artifact emission.
- `artifact_checker.cpp` owns basic row/hash artifact checks.
- `version.cpp` owns library version/tag string construction.

Do not reimplement these behaviors in CLI tools. Tools should call the library API so canonical bytes, hashes, row counts, and schema-facing strings remain consistent across coefficient generation, vector generation, golden runs, and artifact checks.

## Tools implementation layer

The command-line tools are now implemented. The intended ownership split is:

- `phase2_golden_model.cpp` runs the compiled C++ STFT/WOLA reference path and writes per-vector artifacts through the C++ artifact writer.
- `gen_coeffs.py` writes coefficient ROM artifacts and `coeff_manifest.json`.
- `gen_vectors.py` writes `x_in.memh`, draft per-vector configs, and `test_vectors.json`. It accepts `--suite configs/suites/<name>.json` when you need a deterministic subset/order.
- `run_vector.py` and `run_suite.py` invoke the C++ runner; `run_suite.py` finalizes the stream hashes in `test_vectors.json`. It also accepts `--suite` to run only selected manifest entries.
- `artifact_check.py` checks canonical `memh`, row counts, hashes, and JSON schemas.
- `make_quality_bounds.py` derives quality bounds from frozen metrics.
- `freeze_release.py` creates `artifact_index.json`, `core_config_snapshot.json`, and `frozen_release_manifest.json`.

The normal local workflow is:

```bash
make build
make coeffs
make vectors
make golden
make check-artifacts
make quality-bounds
make freeze-release
```

Do not bypass `run_suite.py` when producing a release. Directly running `phase2_golden_model --vectors ...` produces the per-vector outputs, but the Python suite layer is what finalizes manifest hashes for signoff bookkeeping.

## Artifact inspection and packaging tools

The inspection/package tools are now part of the active tool layer:

- `hash_memh.py` computes the canonical SHA-256 over logical integer-vector serialization.
- `inspect_memh.py` validates canonical memh encoding and reports row count, value range, selected values, and hashes.
- `inspect_frame_stats.py` validates `frame_stats.csv`, computes suppression and kept-energy summaries, and can cross-check `metrics.json` aggregate fields.
- `compare_artifacts.py` compares two files or directory trees. For memh files it compares canonical logical-vector hashes; for CSV it uses byte-exact LF comparison; for JSON it uses semantic comparison unless `--json-byte-exact` is requested.
- `package_artifacts.py` runs `artifact_check.py` by default and writes deterministic release archives under `out/`.

Useful commands:

```bash
make hash-memh MEMH=artifacts/test_vectors/zero_Ns4096_thr0/x_in.memh
make inspect-memh MEMH=artifacts/golden/zero_Ns4096_thr0/y_out.memh
make inspect-frame-stats \
  FRAME_STATS=artifacts/golden/zero_Ns4096_thr0/frame_stats.csv \
  METRICS=artifacts/golden/zero_Ns4096_thr0/metrics.json
make compare-artifacts LEFT=artifacts RIGHT=artifacts
make package-artifacts
```

Do not use `sha256sum file.memh` as a signoff substitute for canonical memh hashes. For a canonical file the byte hash and canonical logical hash may match, but the contract is still the logical-vector hash. A checker may normalize input before hashing; release manifests record the canonical serialization hash.

## Python contract package layer

The Python package now has a small contract layer that active tools should reuse instead of copying schema/path logic:

```text
python/trecap_golden/
├── __init__.py
├── generated/
│   ├── __init__.py
│   └── trecap_config.py
└── contracts/
    ├── __init__.py
    ├── contract_paths.py
    ├── schema_loader.py
    └── schema_validate.py
```

Use `trecap_golden.generated.trecap_config` for Revision J constants and finite-stream geometry helpers. It provides `full_tail_nframes(Ns)`, `full_tail_ny(Ns)`, `artifact_rows_for_vector(Ns)`, and `core_config_payload()`. Do not add a second copy of `N`, `L`, `H`, `F`, `G`, `D`, or width constants to random Python tools.

Use `trecap_golden.contracts.contract_paths` for root discovery and canonical locations. This module respects `TRECAP_GOLDEN_ROOT` and validates that the target directory actually looks like the golden repository.

Use `trecap_golden.contracts.schema_loader` to load schemas and compute stable schema SHA-256 digests. Use `trecap_golden.contracts.schema_validate` to validate JSON files or a known artifact tree.

Typical commands:

```bash
PYTHONPATH=python python -m trecap_golden.contracts.schema_validate --inventory
PYTHONPATH=python python -m trecap_golden.contracts.schema_validate --artifacts artifacts
make check-python-contracts
```

This layer is not an arithmetic model. FFT, IFFT, Hermitian canonicalization, masking, WOLA, and error metric arithmetic still belong to the C++ golden model.


## Python generator package layer

Active Python code should use `trecap_golden.generators` for input-vector generation instead of copying generator equations into each CLI. The package surface is:

```text
python/trecap_golden/generators/
├── constant.py
├── impulse.py
├── step.py
├── sine.py
├── cosine.py
├── multitone.py
└── xorshift32.py
```

Use `generate_samples(generator, Ns, parameters)` when dispatching from `test_vectors.json` or a vector config. It supports `constant`, `impulse`, `step`, `sine`, `exact_bin_sine`, `cosine`, `exact_bin_cosine`, `multitone_sine_sum`, and `uniform_noise_xorshift32`. The generator modules validate nonempty `Ns`, final `satN` clipping, exact rational frequency fields, decimal `phase_rad` tokens, and xorshift32 seed/bit-width rules.

`tools/gen_vectors.py` delegates to this package. Do not reintroduce a second private vector-generator implementation in a tool script. The only accepted reason to add a new generator is to add a new generator name, document it, test it, and include its source in the `generator_source_sha256` computation.

Run:

```bash
make check-python-generators
```

The generator package produces only input streams. It does not create golden output streams and does not replace the C++ `phase2_golden_model` executable.

## Python artifact package layer

Active Python code should use `trecap_golden.artifacts.*` for artifact I/O instead of copying parser code into each CLI. The package surface is:

```text
python/trecap_golden/artifacts/
├── memh.py       canonical signed/unsigned memh encode/decode and row checks
├── csv_io.py     frame_stats/bin_stats exact header, row-order, and summary helpers
├── hashes.py     SHA-256 helpers and canonical memh logical-vector hashing
├── manifests.py  artifact-tree, vector, coefficient, and manifest discovery
└── checker.py    programmatic artifact-tree checker
```

Use `memh.contract_for_kind()` or `memh.infer_contract()` before reading `.memh` files. Do not guess widths from line length; the width and signedness are part of the spec contract. Use `hashes.canonical_memh_file_hash()` for signoff hashes. Use `hashes.sha256_file()` only when the intent is raw byte-file packaging diagnostics.

Use `csv_io.read_frame_stats()` and `csv_io.read_bin_stats()` for CSV artifacts. They enforce LF-only files, exact headers, decimal integer fields, frame/bin row ordering, and optional expected row counts. Use `csv_io.cross_check_frame_stats_metrics()` when comparing `frame_stats.csv` totals against `metrics.json`.

Use `checker.check_artifact_tree()` for CI or release-script checks:

```bash
make check-python-artifacts
PYTHONPATH=python python - <<'PY'
from trecap_golden.artifacts.checker import check_artifact_tree
report = check_artifact_tree('artifacts')
report.raise_for_errors()
print(report.checked)
PY
```

This package is allowed to parse, hash, validate, summarize, and discover artifacts. It must not implement an alternate FFT, IFFT, mask, WOLA, or reconstruction path.

## Python CLI package layer

Use `python/trecap_golden/cli/` for package-level command entry points. The CLI modules are wrappers, not independent implementations:

```text
python/trecap_golden/cli/
├── __init__.py
├── _tool_adapter.py
├── gen_coeffs.py
├── gen_vectors.py
├── run_suite.py
├── artifact_check.py
└── freeze_release.py
```

Each user-facing module delegates to the corresponding reviewed repository tool under `tools/` through `trecap_golden.cli.run_repository_tool()`. This keeps a stable module/console command surface while preserving one implementation of coefficient generation, vector generation, suite orchestration, artifact checking, and release freezing.

Rules:

1. Do not copy equations, hash rules, CSV readers, or manifest-writing logic into a CLI wrapper.
2. Do not parse memh, CSV, JSON schema, or manifests inside a CLI wrapper unless that logic already lives in `trecap_golden.artifacts`, `trecap_golden.contracts`, or the existing reviewed tool.
3. Keep the C++ `phase2_golden_model` as the arithmetic runner. The Python CLI may invoke it through `tools/run_suite.py`; it must not reimplement STFT/WOLA arithmetic.
4. CLI wrappers must work from the repo root, with `TRECAP_GOLDEN_ROOT` set, or with the wrapper-only `--repo-root <path>` argument. The adapter strips `--repo-root` before invoking the underlying tool so the older tool parsers do not need to understand it.

Smoke-test this layer with:

```bash
make check-python-cli
PYTHONPATH=python python -m trecap_golden.cli.artifact_check --artifacts artifacts
PYTHONPATH=python python -m trecap_golden.cli.gen_coeffs --repo-root . --out artifacts/coefficients
```

When the package is installed in editable/source-checkout mode, the same wrappers expose console-script names:

```text
trecap-gen-coeffs
trecap-gen-vectors
trecap-run-suite
trecap-artifact-check
trecap-freeze-release
```

The top-level `tools/*.py` files remain the audited script implementations and are still required by `make check-layout`. Keeping the package CLI as a delegation layer avoids drift while giving CI and local users a stable Python module path.

## Release recipe configs

`configs/releases/phase2_revJ_dev.json` and `configs/releases/phase2_revJ_signoff.json` are reviewed workflow inputs. They are not generated. Run `make check-release-configs` after editing them. Generated release manifests remain under `artifacts/manifests/`.
