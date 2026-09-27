# ARM/HPS finite-pipeline benchmark

This package contains the scalar-source fixed-point CPU implementation used for
the T-RECAP ARM/HPS comparison, its qualification tools, and the exact frozen
input/expected-output vectors. The measured results and their board evidence are
published in the [CPU benchmark result report](../../docs/results/hps_cpu_benchmark_20260925/README.md).
That link assumes this package is installed under the repository's experiments
directory. This package contains no board image, FPGA configuration file, or
third-party accelerator driver.

## Work and timing boundary

The kernel performs the complete finite N12/L256/H128/F15/G128/D384 pipeline:
analysis window, normalized radix-2 FFT, Hermitian canonicalization, strict
magnitude-squared mask, unscaled IFFT, synthesis window, and WOLA reconstruction.
It loads the frozen integer coefficients rather than generating floating-point
tables. FFT/IFFT rounding points, conjugate pairing, finite zero extension, and
final signed-12 saturation are preserved. For 1,024 input samples an epoch
produces nine frames and 1,536 output samples.

Each timed epoch resets its logical state and writes the complete output. All
buffers are allocated beforehand. Timing includes an opaque O(1) output consumer
to prevent removal of repeated computation. File I/O, allocations, coefficient
validation, output comparison, quality/telemetry metrics, and host transfers are
outside timing. The FPGA comparison includes its metrics and measurement
checker, so the CPU result is a datapath baseline with less instrumentation.
Elapsed time alone does not establish board power or energy savings.

The checked and fast instantiations must both pass full-output admission before
timing. Internal range checks remain outside the timed instantiation, under the
same immutable admitted input/table/threshold contract. With `--epochs 1`, the
actual output of every timed epoch is fully checked afterward. Multi-epoch
records check only the final timed epoch fully and report that distinction.

## Package contents

- `src/`: C++17 kernel, benchmark executable source, opaque consumer, CMake file,
  and detailed arithmetic/timing notes.
- `scripts/`: frozen vector generator, native qualification runner, offline board
  export validator, and a portable ARM build helper.
- `vectors/`: 20 bounded cases, comprising 19 accepted finite inputs and one
  required empty-input rejection. `manifest.json` pins every vector and source.
- `vectors/sources/`: exact recursive integer oracle, coefficient tables,
  multitone input, and measurement-vector identity snapshot.

The recursive oracle uses a different transform decomposition and absolute WOLA
indices. It shares the frozen coefficient bytes with the kernel. Qualification
of these cases is bounded; it does not prove the entire input domain, physical
execution, or timing. No unrelated logs, emulated/native smoke results, or
executables are included here.

## Build

Run commands from this directory. Native CMake build:

```sh
cmake -S src -B build/native -DCMAKE_BUILD_TYPE=Release
cmake --build build/native --config Release --parallel
```

For a Linux ARMv7 hard-float toolchain with static C++ runtime libraries:

```sh
ARM_CXX=arm-linux-gnueabihf-g++ sh scripts/build_arm.sh build/arm
```

`ARM_CXX` names one compiler executable, optionally by absolute path; it does not
contain extra flags. The helper uses `-O3 -static -mcpu=cortex-a9 -mfpu=neon
-mfloat-abi=hard -fno-lto`, C++17, and ordinary warning flags. Compiler
auto-vectorization is allowed; no handwritten NEON kernel is present. It records
the compiler version, argument list, build log, and available ELF/hash evidence
in a fresh output directory. It never runs the executable or accesses hardware.
Use `ARM_READELF` when the corresponding inspection tool has a different name.
Retain these build records: the direct-build executable does not embed all flags.

An equivalent generic CMake cross-build is:

```sh
cmake -S src -B build/arm-cmake -DCMAKE_BUILD_TYPE=Release \
  -DCMAKE_SYSTEM_NAME=Linux -DCMAKE_SYSTEM_PROCESSOR=arm \
  -DCMAKE_CXX_COMPILER=arm-linux-gnueabihf-g++ \
  -DCMAKE_CXX_FLAGS="-mcpu=cortex-a9 -mfpu=neon -mfloat-abi=hard" \
  -DCMAKE_EXE_LINKER_FLAGS=-static
cmake --build build/arm-cmake --parallel
```

The observed physical-run executable identity is recorded in
`package_manifest.json`; recompilation with another compiler/runtime can produce
different bytes and must receive its own qualification and identity record.

## Qualification

The Python scripts require Python 3.9 or newer and the standard library. Run the
qualification runner on a host that can execute the supplied binary:

```sh
python3 scripts/run_qualification.py \
  --binary build/native/trecap_cpu_benchmark \
  --vectors vectors --run-dir runs/native-qualification-01
```

On Windows with a multi-configuration generator, select the actual `.exe` under
the `Release` directory. A native host or emulator result is functional evidence,
not an ARM board timing result. The runner verifies vector hashes and compares
every output of each accepted case. The expected empty-input failure is checked
explicitly.

The frozen source snapshot is sufficient to regenerate expectations into a new
directory without a separate project checkout:

```sh
python3 scripts/generate_qualification_vectors.py \
  --repo vectors/sources --out regenerated-vectors-01
```

The generator's actual option is `--repo`. Keep the published `vectors/` unchanged.
The offline validator accepts a flat board export containing `CASE.json`,
`CASE.memh`, `CASE.log`, and `CASE.exit` for the 19 accepted cases. The empty-input
rejection must contain its log and exit status and must not produce JSON or MEMH:

```sh
mkdir -p runs
python3 scripts/verify_board_export.py --vectors vectors \
  --result-dir board-export --output runs/board-qualification-01.json
```

That validator inspects files only; physical board identity and the uploaded
executable hash belong in the surrounding acquisition record.

## On-board timing

After full functional qualification of the actual uploaded ARM executable, run
the dense and masked conditions independently with fresh output filenames:

```sh
mkdir -p results
./trecap_cpu_arm --cpu 0 --epochs 1 --trials 30 --warmup 5 \
  --input vectors/cases/multitone_dense/input.memh \
  --expected vectors/cases/multitone_dense/expected.memh \
  --coeff-dir vectors/sources/artifacts/coefficients --threshold 0 \
  --output results/dense-01.json
./trecap_cpu_arm --cpu 0 --epochs 1 --trials 30 --warmup 5 \
  --input vectors/cases/multitone_masked/input.memh \
  --expected vectors/cases/multitone_masked/expected.memh \
  --coeff-dir vectors/sources/artifacts/coefficients --threshold 100000000000 \
  --output results/masked-01.json
```

`--cpu 0` sets and verifies Linux thread affinity before admission and warmup;
BusyBox `taskset` is unnecessary. An additional checked epoch before each timing
record also warms the working set. JSON records wall and thread CPU clocks,
affinity, exact geometry, compiler metadata, and scope exclusions.

## HPS boot and transfer environment

The physical comparison used the Cortex-A9 HPS under Linux
`6.12.33-fma-h1-console`. The kernel boot log reported a 925 MHz CPU clock; this is
a kernel-reported operating rate, not an independently measured oscillator or a
guarantee for another boot. Record the actual clock, kernel, affinity, thermal
context, executable hash, and FPGA idle state for each new campaign.

The HPS boot reused its established DDR initialization and bootloader, loading
kernel, device tree, and initramfs into RAM. The CPU-only device tree disabled the
FPGA manager, FPGA region, all FPGA bridges, and the unrelated accelerator node.
No FMA FPGA image or accelerator driver is required by this benchmark; do not use
another project's FPGA configuration or bridge-activation sequence to run it.
No persistent boot-environment or SD write is part of the benchmark procedure.

Transfer a hash-checked archive containing the ARM executable and vectors over
the already configured HPS Ethernet link, and extract into a fresh tmpfs
directory. Archive the executable with mode `0755`: the available network
BusyBox supplies `wget`, `tar`, and `sha256sum`, but lacks `chmod`. Its tar restores
the archived executable mode. Verify the uploaded binary and vector identities
before execution, and export result files for independent checking. Downloads,
uploads, shell output, and filesystem preparation remain outside timed work.
