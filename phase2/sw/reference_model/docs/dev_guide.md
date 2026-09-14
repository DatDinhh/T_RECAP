# Reference model development

Work from the combined repository root for project-level tasks, or from sw/reference_model for package-level builds. The reference model's legacy executable and Python package names remain stable for existing callers.

## Configuration flow

The source contract is spec/generated/core_config.json inside this package. Generate its C++ and Python bindings from the combined root:

    python sw/reference_model/scripts/gen_config.py

Generated bindings are checked in. The command writes source code only; it does not regenerate coefficient tables, input vectors, result artifacts, or release metadata.

The model's compatibility Python API imports these bindings. The separate repository-wide header generation flow owns root RTL/host definitions and the integration module at sw/reference_model/generated/trecap_config.py.

## Host build

The root CMake host preset builds the reference model with tests disabled. A standalone package build is also supported:

    cmake -S . -B build -DTRECAP_BUILD_TESTS=OFF -DBUILD_TESTING=OFF
    cmake --build build --config Release

C++20 is required. The default package build does not enable test targets. The static library retains the trecap_golden target name; the command-line target retains phase2_golden_model.

## Runtime inputs and outputs

Use the commands in [../README.md](../README.md). Both Python wrappers accept --reference-exe, with --golden-exe retained as an alias. They search the package build directory and the combined root's build/host/reference_model directory.

A vector consists of canonical x_in.memh and a complete config.json. The compiled executable parses JSON structurally, validates the baseline and geometry, and reads the five frozen coefficient tables. It rejects unsupported configuration instead of silently executing a different baseline.

Normal runs use new output directories under runs/. Output configuration and source configuration are separate files. The source vector directory and suite manifest are never rewritten. The suite orchestrator writes run_manifest.json in the output tree and labels entries reference_output. It does not finalize or freeze the input manifest.

The Makefile reference target invokes the ordinary output-only runtime. The old golden target remains an alias for compatibility. Reusing a nonempty output directory is rejected to avoid stale or mixed runs.

## Public C++ API

The frame functions, SampleRing, and OlaRing are reusable building blocks. The batch run function is finite and uses one THR2 for its whole input. Supply matching CoreConfig values for the run, window, twiddles, and OLA ring. Default-generated coefficient tables carry baseline configuration; callers selecting another library configuration must supply matching tables explicitly.

The CLI uses write_reference_outputs. The legacy write_vector_artifacts API is an explicit artifact-authoring operation that can write an input bundle; it is not the runtime API.

Rounding, FFT ordering/scaling, mask comparison, protection flags, Hermitian symmetry, and full-tail geometry are arithmetic contracts. Preserve them when changing implementation structure.

## Artifacts and project status

Coefficient and vector generation tools, historical release utilities, and checked-in test sources are retained separately from ordinary execution. Generated runtime files belong under ignored runs/ or build/ directories.

Do not edit imported artifact hashes or provenance to make a changed model appear identical to its source. Record source changes through the project's provenance flow. This package remains a reference implementation until the project's later validation and acceptance work establishes a final baseline.
