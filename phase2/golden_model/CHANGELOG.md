# Changelog

## 0.1.0-release-config-layer - 2026-05-28

### Added

- Added reviewed release recipe configs under `configs/releases/`: `phase2_revJ_dev.json` and `phase2_revJ_signoff.json`.
- Added `tests/python/test_release_configs.py` and `make check-release-configs` to validate release recipe shape, suite references, lifecycle gates, and freeze-command metadata.

### Changed

- Extended `make check-layout` so the release recipe configs are required repository content.
- Updated release documentation and README to distinguish hand-reviewed release recipes from generated `artifacts/manifests/frozen_release_manifest.json`.

## 0.1.0-python-cli-package-layer - 2026-05-28

### Added

- Added the Python CLI package layer under `python/trecap_golden/cli/` with wrappers for `gen_coeffs`, `gen_vectors`, `run_suite`, `artifact_check`, and `freeze_release`.
- Added internal `_tool_adapter.py` so package entry points delegate to the reviewed `tools/*.py` implementations instead of duplicating artifact-generation logic.
- Added `pyproject.toml` console-script entries: `trecap-gen-coeffs`, `trecap-gen-vectors`, `trecap-run-suite`, `trecap-artifact-check`, and `trecap-freeze-release`.
- Added `tests/python/test_python_cli_layer.py` and `make check-python-cli`.

### Changed

- Updated Makefile artifact-flow targets to use package CLI wrappers while preserving the reviewed top-level tool implementations under `tools/`.
- Extended `make check-layout` so package CLI files are required repository content.
- Updated README and developer guidance with package CLI usage and the `--repo-root` wrapper option.

## 0.1.0-python-generator-package-layer - 2026-05-27

### Added

- Added the Python input-vector generator package under `python/trecap_golden/generators/`: constant, impulse, step, sine, cosine, multitone sine-sum, and uniform xorshift32 noise generators.
- Added `generate_samples(...)` dispatch for the Revision J generator vocabulary, including exact-bin sine/cosine aliases.
- Added `tests/python/test_python_generators_layer.py` and `make check-python-generators`.

### Changed

- Updated `tools/gen_vectors.py` and `tools/_trecap_tool_common.py` so CLI vector generation delegates to the importable generator package instead of carrying an independent generator implementation.
- Extended `make check-layout` so generator package files are required repository content.


## 0.1.0-python-artifact-package-layer - 2026-05-27

### Added

- Added the Python artifact package layer under `python/trecap_golden/artifacts/`: canonical `memh` I/O, CSV artifact readers/writers, SHA-256 helpers, manifest discovery helpers, and a programmatic artifact-tree checker.
- Added `tests/python/test_python_artifacts_layer.py` for package-level artifact contract checks.
- Added `make check-python-artifacts` and extended `make check-layout` to require the artifact package files.

### Changed

- Python tools now have a reusable package surface for artifact inspection/checking instead of relying only on `tools/_trecap_tool_common.py`.

## 0.1.0-python-contract-layer - 2026-05-27

### Added

- Added the Python contract package layer under `python/trecap_golden/`: package exports, checked-in generated Revision J constants, repository contract path discovery, schema loading, and schema validation helpers.
- Added `tests/python/test_python_contract_layer.py` to cover generated constants, full-tail geometry, schema inventory, artifact JSON validation, artifact-tree validation, schema inference, and the validation CLI.
- Added `make check-python-contracts` and extended `make check-layout` to require the Python package contract files.

### Changed

- Updated README and developer guidance so tools can use `trecap_golden.contracts.*` instead of reimplementing schema/path logic in every CLI.

## 0.1.0-tools-inspection-packaging - 2026-05-27

### Added

- Added artifact utility tools: `compare_artifacts.py`, `inspect_memh.py`, `inspect_frame_stats.py`, `hash_memh.py`, and `package_artifacts.py`.
- Added Makefile targets `hash-memh`, `inspect-memh`, `inspect-frame-stats`, and `compare-artifacts`; `package-artifacts` now uses the deterministic package tool.
- Added Python CLI tests for canonical memh hashing, memh inspection, frame-stat/metrics cross-checking, artifact-tree comparison, and deterministic package creation.

### Changed

- Extended `make check-layout` so the additional artifact utility tools are required repository files.
- Updated README and developer guidance with the artifact inspection and packaging workflow.

## 0.1.0-src-artifact-io - 2026-05-27

### Added

- Added the compiled artifact-facing source implementation layer: `metrics.cpp`, `generators.cpp`, `memh.cpp`, `csv_io.cpp`, `json_io.cpp`, `canonical_hash.cpp`, `artifact_writer.cpp`, `artifact_checker.cpp`, and `version.cpp`.
- Added `tests/cpp/test_src_artifact_io_contracts.cpp` to exercise source-defined canonical memh I/O, SHA-256 hashing, CSV row checks, JSON escaping/writing, generator linkage, coefficient artifact writing, artifact checking, and version tags.

### Changed

- Refactored artifact-facing runtime-heavy functions out of public headers and into compiled source files while keeping headers as audited API declarations.
- Extended `make check-layout` so the artifact-facing source files are required repository files.


## 0.1.0-src-stft-wola - 2026-05-27

### Added

- Added the compiled STFT/WOLA source implementation layer: `twiddles.cpp`, `window.cpp`, `fft_radix2_int.cpp`, `ifft_radix2_int.cpp`, `hermitian.cpp`, `mask.cpp`, `stft_wola_model.cpp`, and `finite_stream.cpp`.
- Added `tests/cpp/test_src_stft_wola_contracts.cpp` to exercise source-defined table generation, FFT/IFFT path boundaries, frame analysis, WOLA synthesis, aggregate metrics, full-tail geometry, and empty-input rejection.

### Changed

- Refactored the STFT/WOLA runtime-heavy functions out of public headers and into compiled source files while retaining small `constexpr` helpers in headers for compile-time contract checks.
- Extended `make check-layout` so these source files are required repository files.

## 0.1.0-artifact-header-contracts - 2026-05-27

### Added

- Added artifact-facing public C++ headers: `metrics.hpp`, `generators.hpp`, `memh.hpp`, `csv_io.hpp`, `json_io.hpp`, `canonical_hash.hpp`, `artifact_writer.hpp`, `artifact_checker.hpp`, and `version.hpp`.
- Added deterministic generator helpers for constant, impulse, step, sine, cosine, multitone sine sum, and xorshift32 noise vectors.
- Added canonical memh serialization/parsing, pure C++ SHA-256 hashing, CSV writers/checkers, JSON fragment emitters, coefficient/vector artifact writers, and artifact row/hash check helpers.
- Added `tests/cpp/test_artifact_header_contracts.cpp` to cover generator, memh, hash, CSV, writer, checker, metrics, and version APIs.
- Extended `make check-layout` to require the complete artifact-facing header set.

## 0.1.0-stft-wola-header-contracts - 2026-05-27

### Added

- Added the second public C++ header contract layer for Phase 2 STFT/WOLA processing: `twiddles.hpp`, `window.hpp`, `fft_radix2_int.hpp`, `ifft_radix2_int.hpp`, `hermitian.hpp`, `mask.hpp`, `stft_wola_model.hpp`, and `finite_stream.hpp`.
- Added the public reference API for Revision J full-tail finite-stream processing, including xring/OLA scheduling, normalized forward FFT, Hermitian canonicalization, full-precision THR2 masking, unscaled IFFT, synthesis windowing, WOLA accumulation, and arbitrary-precision decimal aggregate counters. Runtime-heavy definitions now live in the compiled source layer.
- Added `tests/cpp/test_stft_wola_header_contracts.cpp` and expanded `make check-headers` to build and run all C++ header contract tests.
- Extended `make check-layout` to require the full public header set.

## 0.1.0-header-contracts - 2026-05-27

### Added

- Added the first public C++ header contract layer under `include/trecap_golden/`.
- Added fixed-point integer helpers for two's-complement width checks, canonical signed encoding/decoding, `asr`, `rnd_shr`, `rnd2`, `qcoef`, signed saturation, Q-format multiplication, integer complex arithmetic, Hermitian pair canonicalization, magnitude-squared computation, baseline Revision J width schedule, and coefficient table helpers.
- Added `tests/cpp/test_header_contracts.cpp` and `make check-headers` for compile-time and runtime header sanity checks.
- Extended `make check-layout` to require the public header set.


## 0.1.0-schema-contracts - 2026-05-27

### Added

- Added the `spec/schemas/` contract layer for core config, coefficient manifest, test-vector manifest, per-vector config, metrics, quality bounds, artifact index, and frozen release manifest.
- Added Markdown CSV contracts for `frame_stats.csv` and conditional `bin_stats.csv`.
- Added `make check-schemas` and extended `make check-layout` to require the schema contract files.



## Unreleased

- Added `spec/schemas/` JSON Schema Draft 2020-12 contracts for core config, coefficient manifests, frozen test vectors, per-vector configs, metrics, quality bounds, artifact index, and frozen release manifests.
- Added Markdown CSV schemas for `frame_stats.csv` and conditional `bin_stats.csv` row ordering, field typing, and semantic checks.
- Extended `make check-layout` to require schema files and added `make check-schemas` for metaschema validation.

All notable changes to this repository are recorded here.

This project follows the spirit of [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and uses semantic versioning for golden-artifact releases. The artifact contract is stricter than normal software versioning: changing a frozen coefficient, vector, output stream, hash rule, CSV schema, JSON schema, or fixed-point arithmetic behavior is a signoff-impacting change.

## [Unreleased]

### Added

- Initial industrial root layout for `trecap-golden`.
- Root build and hygiene files:
  - `README.md`
  - `CHANGELOG.md`
  - `LICENSE`
  - `Makefile`
  - `CMakeLists.txt`
  - `pyproject.toml`
  - `requirements.lock`
  - `.gitignore`
  - `.editorconfig`
  - `.clang-format`
  - `.pre-commit-config.yaml`
- CMake skeleton for a C++20 bit-accurate golden-model library and future CLI tools.
- Make targets for coefficient generation, vector generation, golden runs, artifact checks, quality-bound generation, release freezing, and release reproduction.
- Python tooling policy for schema validation, canonical hashing, and artifact packaging.
- Explicit warning that older Phase 2 drafts are deprecated and the active baseline uses `D = L + G = 384`.
- Phase 1 quarantine rule under `legacy/phase1/`.

### Not added yet

- No C++ arithmetic implementation.
- No coefficient generator implementation.
- No vector generator implementation.
- No artifact checker implementation.
- No frozen coefficient/vector/golden artifacts.

These are intentionally separate commits so infrastructure can be reviewed before model code is added.

## [0.1.0] - Planned

### Expected

- First complete C++ bit-accurate STFT/WOLA model.
- First frozen coefficient artifact set.
- First frozen vector manifest.
- First golden output streams and metrics.
- First `quality_bounds.json` generated from the frozen model.
- First reproducible release manifest.

## Unreleased - artifact I/O public header layer

- Added public C++ headers for metrics formatting, Revision J vector generators, canonical memh I/O, CSV writing/checking, JSON emission helpers, canonical SHA-256 hashing, coefficient/vector artifact writing, artifact row/hash checking, and golden-model version metadata.
- Extended header layout checks so the artifact I/O contract headers are treated as required repository files.

## Unreleased

### Added

- Added the first compiled `src/` implementation layer for fixed-point, width, integer, rounding, saturation, Q-format, complex-integer, and coefficient-generation contracts.
- Refactored runtime-heavy header definitions into compiled translation units while preserving compile-time contract checks for constants and small arithmetic primitives.
- Updated `make check-layout` to require the new source files.

### Changed

- `trecap_golden` now builds as a static C++ library when `src/*.cpp` files are present, with project warnings/options applied to the library itself and to consumers.


## Unreleased - tools implementation layer

### Added

- Added `tools/phase2_golden_model.cpp`, the C++ CLI runner for single-vector and suite STFT/WOLA golden execution.
- Added Python artifact tools for coefficient generation, input-vector generation, per-vector runs, suite orchestration, artifact checking, quality-bound generation, and release freezing.
- Added an internal shared Python helper for canonical memh encoding, canonical SHA-256, coefficient generation, vector generation, and release helper logic.
- Updated `make golden` to run the C++ executable through `tools/run_suite.py` so stream hashes in `test_vectors.json` are finalized after golden execution.
- Extended `make check-layout` so the tools layer is treated as required repository content.

### Changed

- The artifact workflow can now execute end-to-end from a clean artifact directory using `make coeffs`, `make vectors`, `make golden`, `make check-artifacts`, `make quality-bounds`, and `make freeze-release`.


## Unreleased - vector configuration bundle layer

### Added

- Added the reviewed vector-config bundle set under `configs/vectors/`: `zero_Ns4096_thr0.json`, `no_suppression_multitone_thr0.json`, `impulse_step.json`, `exact_bin_tone_sweep.json`, `off_bin_tone_sweep.json`, `near_threshold_multitone.json`, `noise_only_xorshift32.json`, `high_amplitude_headroom.json`, and `short_finite_stream.json`.
- Added `make check-vector-configs` for focused vector-bundle validation.

### Changed

- Replaced the earlier one-file-per-vector config layout with signoff-class bundles using `trecap_phase2_vector_bundle_v1`. Vector instance names remain unchanged so existing suite selectors and artifact paths continue to match the already generated artifacts.
- Hardened `load_vector_specs()` so it rejects suite files used as vector configs, rejects empty bundles, and fails on duplicate vector names across config files.

## Unreleased - suite configuration layer

### Added

- Added reviewed suite configs under `configs/suites/`: `smoke.json`, `signoff_minimal.json`, `signoff_full.json`, and `debug_near_threshold.json`.
- Added suite-aware vector/golden targets: `make vectors-suite SUITE=...` and `make golden-suite SUITE=...`.
- Added `make check-suite-configs` and Python tests that validate suite shape, required class coverage, and non-dangling vector references.
- Added the missing reviewed vector configs needed for the candidate signoff suites to cover the Revision J required vector classes.

### Changed

- `tools/gen_vectors.py` and `tools/run_suite.py` now accept `--suite` while preserving the existing full-manifest behavior when no suite is supplied.
