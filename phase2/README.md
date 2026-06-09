# T-RECAP Golden Model

Deterministic artifact-producing golden model repository for the T-RECAP Phase 2 fixed-point STFT/WOLA selective-suppression core.

This repository is for the **software reference and signoff artifacts** only. It is not the RTL implementation repository, not the HPS streamer, not the PC dashboard, and not the verification repository.

## Scope

The golden repository owns:

- coefficient generation for frozen window and twiddle ROM artifacts;
- deterministic test-vector generation;
- the bit-accurate C++ reference model;
- canonical `memh`, CSV, and JSON artifact writing;
- artifact checking, canonical SHA-256 hashing, and release freezing;
- no-suppression quality-bound generation.

It does **not** own:

- FPGA RTL modules;
- SystemVerilog testbench architecture;
- HPS Ethernet software;
- PC dashboard code;
- live audio or ADC integration.

## Current baseline contract

The active Phase 2 baseline is:

| Field | Value |
|---|---:|
| External sample width `N` | 12 |
| FFT length `L` | 256 |
| Radix-2 stages `P` | 8 |
| Hop size `H` | 128 |
| Fractional precision `F` | 15 |
| Scheduling cushion `G` | 128 |
| Causal delay `D = L + G` | 384 |
| Tail policy | `full_tail` |
| Rounding | round-to-nearest, ties away from zero |
| Forward FFT | custom radix-2 DIT, bit-reversed input, natural output |
| IFFT | custom radix-2 DIT unscaled inverse |

The canonical artifacts and hashes are the authority after a coefficient table or vector is frozen. Regenerating a mathematically equivalent table or vector is not enough unless the canonical hash matches.

## Deprecated documents warning

Older Phase 2 algorithm drafts are historical only.

Do **not** use `D = L` for the current DE1-SoC baseline.

Use the integrated Phase 2 specification:

- Core Revision J;
- Telemetry Revision G;
- current baseline delay: `D = L + G = 384` samples.

Phase 1 files must remain quarantined under `legacy/phase1/`. They must not be compiled into this Phase 2 golden flow.



### Source implementation layer

The compiled C++ source layer is now present under `src/`:

```text
src/
├── fixed_point.cpp
├── widths.cpp
├── signed_int.cpp
├── rounding.cpp
├── saturation.cpp
├── q_format.cpp
├── complex_int.cpp
├── coeffs.cpp
├── twiddles.cpp
├── window.cpp
├── fft_radix2_int.cpp
├── ifft_radix2_int.cpp
├── hermitian.cpp
├── mask.cpp
├── stft_wola_model.cpp
├── finite_stream.cpp
├── metrics.cpp
├── generators.cpp
├── memh.cpp
├── csv_io.cpp
├── json_io.cpp
├── canonical_hash.cpp
├── artifact_writer.cpp
├── artifact_checker.cpp
└── version.cpp
```

The public headers keep small `constexpr` primitives and API declarations. Runtime-heavy definitions now live in compiled translation units. That includes host-math-dependent generators, canonical `memh` parsing/writing, CSV and JSON artifact emission, SHA-256 hashing, coefficient/vector artifact writing, artifact checking, version tagging, FFT/IFFT execution, Hermitian canonicalization, masking, WOLA, and full-tail finite-stream execution. This keeps the golden model auditable without turning every downstream CLI tool into a header-only rebuild.

### Artifact I/O source implementation layer

The artifact-facing source files are not placeholders:

- `metrics.cpp` converts aggregate counters to schema-compatible decimal strings and derived display ratios.
- `generators.cpp` implements the frozen vector generator families before `x_in.memh` and `x_in_sha256` become authority.
- `memh.cpp` enforces fixed-width lowercase-hex LF-only signed/unsigned memory files.
- `csv_io.cpp` emits and checks the exact `frame_stats.csv` and `bin_stats.csv` headers and row ordering.
- `json_io.cpp` centralizes JSON escaping and shared contract fragments.
- `canonical_hash.cpp` implements SHA-256 over canonical logical integer-vector serialization.
- `artifact_writer.cpp` writes coefficient and per-vector artifacts from model outputs.
- `artifact_checker.cpp` checks row counts, canonical hashes, and basic artifact shape.
- `version.cpp` emits golden-model version and contract tags.

## Repository layout

```text
trecap-golden/
├── README.md
├── CHANGELOG.md
├── LICENSE
├── Makefile
├── CMakeLists.txt
├── pyproject.toml
├── requirements.lock
├── .gitignore
├── .editorconfig
├── .clang-format
├── .pre-commit-config.yaml
├── docs/
├── spec/
├── include/
├── src/
├── tools/
├── python/
├── configs/
├── artifacts/
├── tests/
├── scripts/
├── ci/
├── out/
├── runs/
└── legacy/
```

The main production paths are:

```text
spec/generated/              source-of-truth generated config inputs
include/trecap_golden/       public C++ headers
src/                          C++ model implementation
python/trecap_golden/         Python automation package
tools/                        command-line entry points
configs/                      reviewed suite/vector/release configs
artifacts/coefficients/       frozen coefficient memh + manifest
artifacts/test_vectors/       frozen x_in.memh vectors + configs
artifacts/golden/             frozen y_out.memh, frame_stats.csv, metrics.json
artifacts/manifests/          quality_bounds, stream hashes, release manifests
```



## Documentation set

The repository-level documentation lives directly under `docs/`:

```text
docs/
├── golden_model_overview.md
├── arithmetic_contract.md
├── fixed_point_widths.md
├── fft_ifft_contract.md
├── stft_wola_contract.md
├── artifact_contract.md
├── canonical_memh_hashing.md
├── vector_freeze_process.md
├── quality_bounds_process.md
├── release_process.md
└── dev_guide.md
```

Start with `docs/golden_model_overview.md`, then read the arithmetic, width, FFT/IFFT, and STFT/WOLA contracts before touching model code.

## Schema contract set

The schema layer lives under `spec/schemas/` and is part of the repository contract:

```text
spec/schemas/
├── core_config.schema.json
├── coeff_manifest.schema.json
├── test_vectors.schema.json
├── vector_config.schema.json
├── metrics.schema.json
├── quality_bounds.schema.json
├── artifact_index.schema.json
├── frozen_release_manifest.schema.json
├── frame_stats.schema.md
└── bin_stats.schema.md
```

The JSON schemas use Draft 2020-12 and intentionally reject placeholder hashes such as `<sha256-hex>`. Wide counters and `mag2`-derived fields are decimal strings, not JSON numbers. `frame_stats.csv` and `bin_stats.csv` are documented as Markdown contracts because CSV ordering, exact headers, and row-count checks are not cleanly expressible as plain JSON Schema.

Run the schema self-check with:

```bash
make check-schemas
```


## C++ public header layer

The public arithmetic API is under `include/trecap_golden/`:

```text
include/trecap_golden/
├── fixed_point.hpp
├── widths.hpp
├── signed_int.hpp
├── rounding.hpp
├── saturation.hpp
├── q_format.hpp
├── complex_int.hpp
├── coeffs.hpp
├── twiddles.hpp
├── window.hpp
├── fft_radix2_int.hpp
├── ifft_radix2_int.hpp
├── hermitian.hpp
├── mask.hpp
├── stft_wola_model.hpp
├── finite_stream.hpp
├── metrics.hpp
├── generators.hpp
├── memh.hpp
├── csv_io.hpp
├── json_io.hpp
├── canonical_hash.hpp
├── artifact_writer.hpp
├── artifact_checker.hpp
└── version.hpp
```

The headers are deliberately small and auditable. `signed_int.hpp`, `rounding.hpp`, and `saturation.hpp` define the primitive integer contract. `widths.hpp` freezes the current Revision J baseline constants and derived width schedule. `q_format.hpp` and `complex_int.hpp` define fixed-point products and complex operations. `coeffs.hpp`, `twiddles.hpp`, and `window.hpp` define the frozen coefficient surfaces. `fft_radix2_int.hpp`, `ifft_radix2_int.hpp`, `hermitian.hpp`, `mask.hpp`, `finite_stream.hpp`, and `stft_wola_model.hpp` define the public Phase 2 STFT/WOLA reference API; runtime-heavy definitions live in `src/`. `metrics.hpp`, `generators.hpp`, `memh.hpp`, `csv_io.hpp`, `json_io.hpp`, `canonical_hash.hpp`, `artifact_writer.hpp`, `artifact_checker.hpp`, and `version.hpp` define the artifact-facing surface that the active CLI tools will consume. After a release is frozen, canonical artifacts and hashes remain the signoff authority.

Run the header self-check with:

```bash
make check-headers
```

### Artifact-facing C++ headers

The artifact-facing headers are intentionally separate from the STFT/WOLA arithmetic headers:

- `metrics.hpp` converts arbitrary-precision metric accumulators into schema-compatible decimal-string fields and exposes display-only derived ratios.
- `generators.hpp` implements the Revision J input-vector families used before `x_in_sha256` becomes the signoff authority.
- `memh.hpp` implements fixed-width lowercase hexadecimal LF-only signed/unsigned memory files.
- `canonical_hash.hpp` computes SHA-256 over canonical logical integer-vector serialization.
- `csv_io.hpp` writes/checks the frozen `frame_stats.csv` and conditional `bin_stats.csv` headers and row ordering.
- `json_io.hpp` centralizes JSON escaping and common configuration/contract fragments.
- `artifact_writer.hpp` writes coefficient and per-vector artifacts from model outputs.
- `artifact_checker.hpp` checks memh line counts, canonical hashes, CSV rows, and basic artifact shape.
- `version.hpp` exposes golden-model, schema, generator, and artifact-contract string constants.

These are still library headers, not production command-line tools. The `tools/` layer now calls this API for coefficient generation, vector generation, golden execution, and artifact checking.

## Quick start

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.lock
pre-commit install
```

Configure and build the C++ layer:

```bash
cmake -S . -B build -DCMAKE_BUILD_TYPE=RelWithDebInfo
cmake --build build
ctest --test-dir build --output-on-failure
```

Equivalent Makefile path:

```bash
make setup
make configure
make build
make test
```

## Required Make targets

| Target | Purpose |
|---|---|
| `make check-layout` | Verify root files and required golden-model directories exist. |
| `make check-schemas` | Validate JSON Schema syntax and CSV schema documentation contracts. |
| `make check-python-contracts` | Import Python contract helpers and validate the generated core-config payload. |
| `make check-python-artifacts` | Import Python artifact helpers and check bundled smoke artifacts. |
| `make check-python-generators` | Import Python vector generators and verify bundled input-vector artifacts. |
| `make check-python-cli` | Import package CLI wrappers and smoke-test repository tool delegation. |
| `make setup` | Install Python tooling from `requirements.lock`. |
| `make configure` | Configure CMake. |
| `make build` | Build the C++ golden-model library/tools. |
| `make test` | Run C++ and Python self-tests when present. |
| `make lint-basic` | Run basic Python/C++/metadata lint checks. |
| `make format` | Apply Python and C++ formatting. |
| `make gen-config` | Generate derived config files from source schemas. |
| `make coeffs` | Generate coefficient `memh` files and coefficient manifest. |
| `make vectors` | Generate or validate frozen input vectors. |
| `make golden` | Run the golden model and emit expected artifacts. |
| `make check-artifacts` | Check canonical `memh`, hashes, CSV rows, and JSON schemas. |
| `make hash-memh` | Compute a canonical memh hash. Requires `MEMH=path`; optional `KIND=sample/window/twiddle`. |
| `make inspect-memh` | Inspect memh row count, value range, selected values, and hashes. Requires `MEMH=path`. |
| `make inspect-frame-stats` | Inspect frame statistics and optionally cross-check metrics. Requires `FRAME_STATS=path`; optional `METRICS=path`. |
| `make compare-artifacts` | Compare two artifact files or trees. Requires `LEFT=path RIGHT=path`. |
| `make quality-bounds` | Generate no-suppression quality-bound manifest. |
| `make freeze-release` | Freeze artifact hashes into a release manifest. |
| `make reproduce-release` | Regenerate and verify a frozen release bit-for-bit. |
| `make package-artifacts` | Build a release artifact archive under `out/`. |
| `make clean-runs` | Remove local generated run output. |

Targets that depend on implementation scripts intentionally fail if the script is missing. That is better than silently producing partial signoff artifacts.

## Artifact rules

Canonical `memh` files use:

- one value per line;
- lowercase hexadecimal only;
- no `0x` prefix;
- no blank lines;
- no trailing spaces;
- exactly one LF after each value;
- fixed width based on the declared signedness and bit width.

Canonical SHA-256 hashes are computed over the logical integer vector serialized in canonical `memh` form, not over arbitrary host bytes.

## C++ model rules

The C++ golden model must implement the frozen arithmetic directly:

- explicit signed saturation;
- arithmetic right shift semantics for negative integers;
- `rnd_shr` with ties away from zero;
- exact coefficient quantization;
- full-precision product sums before rounding;
- no silent internal wraparound;
- deterministic artifact emission order.

Use arbitrary-precision or checked wide integer accumulators for signoff metrics whenever native fixed-width integers cannot prove safety.

## Python automation rules

Python may orchestrate generation, schema validation, hashing, packaging, and release checks. Python must not become a second independent arithmetic model that can drift from the C++ bit-accurate reference.

Generated Python constants live under:

```text
python/trecap_golden/generated/
```

Generated files must contain an `AUTO-GENERATED - DO NOT EDIT` banner.

### Python contract package layer

The Python package now has a reviewed contract surface instead of ad-hoc path and schema code inside each tool:

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

`generated/trecap_config.py` is the checked-in generated Python view of the current Revision J golden-model baseline. It exposes `N`, `L`, `P`, `H`, `F`, `G`, `D`, the width schedule, artifact row-count helpers, required CSV headers, and a schema-compatible `core_config_payload()` function. This file is not a second arithmetic model; it only exposes contract constants and deterministic geometry helpers.

`contracts/contract_paths.py` discovers the repository root and returns canonical locations for `spec/schemas/`, `spec/generated/`, artifacts, configs, and the Python package. `contracts/schema_loader.py` loads Draft 2020-12 schemas and returns stable schema SHA-256 digests. `contracts/schema_validate.py` validates individual JSON files or the known JSON artifacts under an artifact tree.

Run the Python contract self-check with:

```bash
make check-python-contracts
PYTHONPATH=python python -m trecap_golden.contracts.schema_validate --inventory
PYTHONPATH=python python -m trecap_golden.contracts.schema_validate --artifacts artifacts
```

The schema validation package intentionally does not validate `core_config_snapshot.json`; that file is an interim freeze-release snapshot until the real `spec/generated/core_config.json` generation layer is populated.

### Python generator package layer

The Python package now has an importable generator layer for input-vector creation:

```text
python/trecap_golden/generators/
├── __init__.py
├── constant.py
├── impulse.py
├── step.py
├── sine.py
├── cosine.py
├── multitone.py
└── xorshift32.py
```

This layer implements only the frozen `x_in.memh` generator vocabulary: `constant`, `impulse`, `step`, `sine`, `exact_bin_sine`, `cosine`, `exact_bin_cosine`, `multitone_sine_sum`, and `uniform_noise_xorshift32`. It clips final samples with `satN`, uses explicit `qcoef(..., 0)` instead of Python `round()`, parses frequency as integer `f_num/f_den`, parses `phase_rad` as a decimal token before evaluation, and rejects illegal xorshift seeds or noise bit widths.

`tools/gen_vectors.py` now delegates sample generation through this package, so command-line vector generation and importable package behavior stay tied to one implementation surface. Sine/cosine/multitone vectors still become signoff artifacts only after `x_in.memh` and `x_in_sha256` are frozen; the generator name is documentation, not a substitute for the canonical stream hash.

Run the package-level generator self-check with:

```bash
make check-python-generators
PYTHONPATH=python python - <<'PY'
from trecap_golden.generators import generate_samples
x = generate_samples('impulse', 8, {'index': 2, 'amplitude': 1536})
print(x)
PY
```

This layer must not implement FFT, IFFT, Hermitian canonicalization, masking, WOLA, or time-domain error metrics. Those remain in the C++ golden model.

### Python artifact package layer

The Python package also has a reusable artifact layer:

```text
python/trecap_golden/artifacts/
├── __init__.py
├── memh.py
├── csv_io.py
├── hashes.py
├── manifests.py
└── checker.py
```

`memh.py` owns strict fixed-width lowercase-hex LF parsing/writing for signed stream files, unsigned `window_qw.memh`, and signed twiddle files. `hashes.py` exposes both raw byte hashes and the canonical logical-vector memh hash; only the latter is the signoff hash for `.memh` artifacts. `csv_io.py` owns exact `frame_stats.csv` and `bin_stats.csv` headers, row counts, row ordering, and metrics cross-check helpers. `manifests.py` discovers coefficient, vector, golden, and manifest files under the frozen artifact tree. `checker.py` exposes a programmatic artifact-tree checker for CI and release scripts.

Run the package-level artifact self-check with:

```bash
make check-python-artifacts
PYTHONPATH=python python -c "from trecap_golden.artifacts.checker import check_artifact_tree; r=check_artifact_tree('artifacts'); r.raise_for_errors()"
```

This layer is artifact I/O and contract enforcement. It is not a second STFT/WOLA arithmetic implementation.

## Release policy

A release is not frozen until all of these are true:

1. coefficient files exist and match `coeff_manifest.json`;
2. every vector in `test_vectors.json` has canonical `x_in_sha256`;
3. every golden output has canonical `y_out_sha256`;
4. row counts match `config.json` and schema rules;
5. `metrics.json`, `frame_stats.csv`, and conditional `bin_stats.csv` pass checks;
6. `quality_bounds.json` is generated from the frozen model, not invented by hand;
7. `frozen_release_manifest.json` records tool versions, schema hashes, artifact hashes, and model version.

## Minimum development flow

```bash
make check-layout
make gen-config
make coeffs
make vectors
make golden
make check-artifacts
make quality-bounds
make freeze-release
make reproduce-release
```

Do not move to RTL replay until this flow is reproducible.


### Public C++ core headers

The current public header layer is split by operator boundary. `fixed_point.hpp`, `signed_int.hpp`, `rounding.hpp`, `saturation.hpp`, `q_format.hpp`, `complex_int.hpp`, `widths.hpp`, and `coeffs.hpp` define the scalar arithmetic and coefficient contract. `twiddles.hpp`, `window.hpp`, `fft_radix2_int.hpp`, `ifft_radix2_int.hpp`, `hermitian.hpp`, `mask.hpp`, `finite_stream.hpp`, and `stft_wola_model.hpp` define the Phase 2 STFT/WOLA algorithm API. Headers are intentionally small enough to audit: coefficient tables, FFT/IFFT, Hermitian canonicalization, threshold masking, finite-stream timing, and WOLA state are not hidden in one monolithic source file.

### Public artifact I/O headers

The header layer now includes the C++ contracts needed by active tools: canonical memh encoding, canonical SHA-256, CSV emission, metrics formatting, frozen vector generators, coefficient/vector artifact writing, artifact checking, and version metadata. This does not replace `tools/`; it gives those tools a reviewed library surface instead of letting each CLI script reimplement hashes, row counts, and file formats independently.

## Command-line tools layer

The `tools/` layer is now active and consumes the compiled C++ library plus a small shared Python helper for orchestration:

```text
tools/
├── phase2_golden_model.cpp     C++ executable for one vector or a vector suite
├── gen_coeffs.py               coefficient memh + coeff_manifest.json generator
├── gen_vectors.py              input-vector generator + draft test_vectors.json
├── run_vector.py               one-vector Python wrapper around the C++ runner
├── run_suite.py                suite orchestrator and stream-hash finalizer
├── artifact_check.py           canonical memh/hash/CSV/schema checker
├── make_quality_bounds.py      quality_bounds.json generator from frozen metrics
├── freeze_release.py           artifact_index + frozen_release_manifest freezer
├── compare_artifacts.py        file/tree comparison using logical memh hashes
├── inspect_memh.py             memh row/value/hash inspector
├── inspect_frame_stats.py      frame_stats.csv inspector and metrics cross-checker
├── hash_memh.py                standalone canonical memh SHA-256 calculator
├── package_artifacts.py        deterministic release archive packager
└── _trecap_tool_common.py      internal Python helper shared by the tools
```

A clean artifact workflow is:

```bash
make coeffs
make vectors
make golden
make check-artifacts
make quality-bounds
make freeze-release
```

`make vectors` uses reviewed JSON files from `configs/vectors/` when present. The vector-config layer now uses class bundles instead of one file per vector instance:

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

Each bundle has schema `trecap_phase2_vector_bundle_v1` and contains one or more vector instances under a top-level `vectors` array. The bundle filename describes the required signoff class; the vector instance names inside remain the artifact identities used by `test_vectors.json`, `artifacts/test_vectors/<name>/`, and `artifacts/golden/<name>/`. If `configs/vectors/` contains no vector configs, the tool emits a small deterministic smoke suite so the end-to-end artifact flow remains testable before the final signoff suite is frozen. `make golden` runs the C++ `phase2_golden_model` through `tools/run_suite.py`; the Python layer finalizes `test_vectors.json` with canonical `y_out_sha256`, `metrics_sha256`, `frame_stats_sha256`, and conditional `bin_stats_sha256` fields.

Suite configs live under `configs/suites/` and select an ordered subset of reviewed vector configs without duplicating generator parameters. The active suite files are:

```text
configs/suites/
├── smoke.json
├── signoff_minimal.json
├── signoff_full.json
└── debug_near_threshold.json
```

Use `make check-vector-configs` to validate the reviewed vector bundles. Use `make check-suite-configs` to validate suite shape and vector references. Use `make vectors-suite SUITE=configs/suites/smoke.json` and `make golden-suite SUITE=configs/suites/smoke.json` when a workflow should run only one suite instead of every config under `configs/vectors/`. The suite files intentionally use `vector_selection`, not a top-level `vectors` array, so they cannot be mistaken for `test_vectors.json` or a vector-config bundle.

Release recipe configs live under `configs/releases/`. These are hand-reviewed input recipes, not generated manifests:

```text
configs/releases/
├── phase2_revJ_dev.json
└── phase2_revJ_signoff.json
```

`phase2_revJ_dev.json` selects the smoke workflow for fast developer/CI artifact checks. `phase2_revJ_signoff.json` selects the full candidate signoff workflow and records the extra gates that are outside the golden repo itself: RTL sample comparison, frame-stat comparison, metrics comparison, BRAM replay evidence, and quality-bound margin review. The generated authority remains `artifacts/manifests/frozen_release_manifest.json`, plus canonical hashes for the coefficient, vector, and golden output artifacts. Validate these reviewed release recipes with `make check-release-configs`.

The C++ executable is still the reference runner for STFT/WOLA arithmetic. Python generates coefficients/vectors, invokes the executable, validates artifacts, and freezes release manifests. Do not move FFT, IFFT, mask, WOLA, or time-error arithmetic into Python.


Useful inspection/package commands after a release is frozen:

```bash
make hash-memh MEMH=artifacts/test_vectors/zero_Ns4096_thr0/x_in.memh
make inspect-memh MEMH=artifacts/golden/zero_Ns4096_thr0/y_out.memh
make inspect-frame-stats \
  FRAME_STATS=artifacts/golden/zero_Ns4096_thr0/frame_stats.csv \
  METRICS=artifacts/golden/zero_Ns4096_thr0/metrics.json
make compare-artifacts LEFT=artifacts RIGHT=artifacts
make package-artifacts
```

`compare_artifacts.py` compares `memh` files by logical integer-vector canonical hashes, not by arbitrary host bytes. JSON comparison is semantic by default; pass `--json-byte-exact` when byte-for-byte JSON equality is required. `package_artifacts.py` runs `artifact_check.py` by default and emits deterministic archives plus a sidecar package manifest under `out/`.

## Python CLI package layer

The repository now exposes importable package CLI entry points under:

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

`_tool_adapter.py` is an internal bridge. The five user-facing modules are thin wrappers over the reviewed `tools/*.py` implementations. This is deliberate: the package gets stable `python -m trecap_golden.cli.*` entry points without creating a second coefficient generator, vector generator, suite runner, artifact checker, or release freezer. The adapter discovers the repository root through `TRECAP_GOLDEN_ROOT`, `--repo-root`, the current working directory, or the package location, then executes the repo-local tool from the repository root.

Supported module commands:

```bash
PYTHONPATH=python python -m trecap_golden.cli.gen_coeffs --out artifacts/coefficients
PYTHONPATH=python python -m trecap_golden.cli.gen_vectors --configs configs/vectors --out artifacts/test_vectors
PYTHONPATH=python python -m trecap_golden.cli.run_suite --vectors artifacts/test_vectors --out artifacts/golden --golden-exe build/phase2_golden_model
PYTHONPATH=python python -m trecap_golden.cli.artifact_check --artifacts artifacts
PYTHONPATH=python python -m trecap_golden.cli.freeze_release --artifacts artifacts --out artifacts/manifests/frozen_release_manifest.json
```

Equivalent direct-tool calls remain valid:

```bash
python tools/gen_coeffs.py --out artifacts/coefficients
python tools/gen_vectors.py --configs configs/vectors --out artifacts/test_vectors
python tools/artifact_check.py --artifacts artifacts
```

`pyproject.toml` declares the matching console-script names for editable/source-checkout installs:

```text
trecap-gen-coeffs
trecap-gen-vectors
trecap-run-suite
trecap-artifact-check
trecap-freeze-release
```

Run the CLI package self-check with:

```bash
make check-python-cli
```

The package CLI is not a new arithmetic layer. It delegates to the same tools that write coefficient artifacts, vector artifacts, golden outputs, checker reports, and frozen release manifests.
