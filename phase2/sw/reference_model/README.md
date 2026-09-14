# T-RECAP reference model

This package contains the C++ fixed-point STFT/WOLA reference implementation and its Python input and artifact tools. It is part of the senior project in the repository root. Its outputs describe the current software model; they are not final golden results or FPGA signoff evidence.

The legacy C++ namespace, executable, Python package, and some artifact schema names contain “golden”. We retain those identifiers for compatibility. They do not change the status of this package as a reference model.

## Arithmetic baseline

The baseline uses signed 12-bit samples, a 256-point radix-2 FFT, a 128-sample hop, 15 fractional bits, and a 128-sample scheduling cushion. Its logical output delay is D = L + G = 384 samples. The forward FFT divides by two at each stage; the inverse is unscaled. Precision reduction rounds to nearest with ties away from zero.

The exact equations are documented in [arithmetic_contract.md](docs/arithmetic_contract.md), [fft_ifft_contract.md](docs/fft_ifft_contract.md), and [stft_wola_contract.md](docs/stft_wola_contract.md). The integrated specification and project architecture remain the project-level design contract.

## Source configuration

The spec/generated/core_config.json file supplies the arithmetic configuration used by this package. From the combined repository root:

    python sw/reference_model/scripts/gen_config.py

This generates two source bindings:

- include/trecap_golden/generated/core_config.hpp for the C++ model;
- python/trecap_golden/generated/_core_constants.py for Python tooling.

The compatibility module python/trecap_golden/generated/trecap_config.py imports those values and supplies geometry helpers. The separate generated/trecap_config.py belongs to the repository-level header generation flow.

Configuration generation does not generate coefficient tables, input vectors, result artifacts, or release manifests.

## Build

From this package directory:

    cmake -S . -B build -DTRECAP_BUILD_TESTS=OFF -DBUILD_TESTING=OFF
    cmake --build build --config Release

The executable retains its name phase2_golden_model. The MSVC build places it under build/Release/; single-configuration builds generally place it directly under build/.

## Run without changing the inputs

Use a new output directory for each run:

    python tools/run_vector.py --vector-dir artifacts/test_vectors/zero_Ns4096_thr0 --coeff-dir artifacts/coefficients --out runs/example

    python tools/run_suite.py --vectors artifacts/test_vectors --coeff-dir artifacts/coefficients --out runs/suite-example

The wrappers locate the executable under this package's build/ directory or the combined repository's build/host/reference_model/ directory. For a repository-level or custom build, pass --reference-exe PATH; --golden-exe remains a compatibility alias.

The direct C++ executable supports --vector-dir, --vectors, --input, --coeff-dir, --out, and --output-dir. The options --test-vector-dir and --golden-dir remain aliases for the corresponding input and output options. Run --help for the full list.

Each vector requires config.json. The runners reject malformed or duplicate-key JSON, unsupported baseline configuration, incompatible widths or arithmetic modes, incorrect input geometry, and input/coefficient hash mismatches. The C++ executable applies the same contract checks when invoked directly. The five checked-in coefficient memh files are read during a run; the runner does not regenerate them through host floating-point math.

The --thr2 option is an explicit per-run override. The effective threshold is recorded in output config.json; the source configuration remains unchanged. The model currently uses one threshold for the entire run.

The output directory must be new or empty and separate from input and coefficient directories. A run writes:

- y_out.memh, frame_stats.csv, metrics.json, and optional bin_stats.csv;
- output config.json describing the effective run;
- source_config.json, preserving the original input metadata byte-for-byte;
- run.json, recording input/config/coefficient provenance and reference status.

Suite runs add run_manifest.json under the output root. They do not rewrite test_vectors.json or mark results frozen. If a later vector fails, previously completed output directories remain available.

Coefficient/vector generation and legacy write_vector_artifacts are separate, explicit artifact-authoring APIs. They are not part of ordinary reference execution.

## Current limits

The public run API is a finite-batch model with full-tail output. It does not model FPGA clock cycles, FIFO occupancy, live source discontinuities, or mid-stream threshold commits. Frame-level arithmetic and ring APIs are available for a future streaming interface.

Library callers must supply one consistent CoreConfig across the run, window, twiddles, and OLA ring. Mismatched configurations are rejected. The CLI supports the pinned baseline; it does not silently reinterpret a different configuration.

Imported coefficient/input artifacts and their historical metadata are retained for traceability. A matching reference result or hash does not establish final RTL correctness or measured hardware performance.
