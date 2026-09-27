# Preallocated CPU finite-pipeline benchmark

This is a separate C++17 implementation of the Revision J N12/L256/H128/F15/G128/D384 datapath. It does not modify or call the guarded reference model. The scalar C++ source allows normal compiler auto-vectorization; it does not contain handwritten NEON or floating-point transform arithmetic. All fixed-point calculations use 32/64-bit integers, with no 128-bit integer dependency.

The benchmark is a CPU datapath measurement. It does not include FPGA JTAG control, host transfers, file I/O, reference checking, telemetry, or quality-metric aggregation. Whole-system runtime or energy comparisons must state those boundaries.

## Build

```sh
cmake -S src -B build/native -DCMAKE_BUILD_TYPE=Release
cmake --build build/native --parallel
```

GNU/Clang Release normally uses `-O3`; compiler auto-vectorization remains allowed. LTO is disabled so the output consumer remains opaque to the timed caller. Exact flags are retained in `compile_commands.json`. Cross-compile with a supplied toolchain and CPU/FPU/ABI flags confirmed against the target; the source does not infer board identity or operating frequency from compiler options. For a manual build, compile `main.cpp`, `kernel.cpp`, and `consumer.cpp` as separate translation units with C++17, optimization, and `-fno-lto`. Keep the exact compiler command and executable/source/input SHA-256 hashes in an external build/run manifest.

## Run

```sh
build/native/trecap_cpu_benchmark --cpu 0 \
  --input x_in.memh --expected y_masked.memh --coeff-dir coefficients \
  --threshold 100000000000 --epochs 1 --trials 20 --warmup 3 \
  --output new_cpu_result.json
```

Choose a new JSON filename and an existing parent directory. Optional Linux `--cpu N` binds the current benchmark thread to exactly one CPU before loading, admission, or warmup, then reads back and verifies the complete affinity mask. Failure to set or verify affinity terminates the run; non-Linux use of `--cpu` also fails explicitly. Omitting `--cpu` preserves inherited affinity, which is suitable for unpinned native functional qualification. BusyBox `taskset` is not required.

The wrapper should record the actual board, governor, clock/thermal state, OS, executable hash, and acquisition context. The JSON records requested affinity and its successful readback, observed architecture, selected `/proc/cpuinfo` fields, allowed CPUs, compiler metadata, and clock choices. Frequency is explicitly unknown unless measured externally. Non-ARM execution is labeled `host_smoke_not_arm_measurement`; an ARM binary does not by itself attest physical DE1-SoC execution.

Use `--verify-only --output-samples new_output.memh` for functional checks without timing records. `--expected` remains mandatory. Input and expected files contain unsigned hexadecimal encodings of signed 12-bit values; coefficient files are the frozen 256-entry `window_qw.memh`, `twiddle_re.memh`, `twiddle_im.memh`, `twiddle_inv_re.memh`, and `twiddle_inv_im.memh`. Loading, parsing, expected-output comparison, and optional output export are outside timing. Coefficients are loaded, never regenerated with host floating-point functions.

## Arithmetic and work contract

Each finite epoch resets the sample and OLA rings and local pointers. Scratch transform arrays and the complete output array are overwritten before observation. The epoch includes zero extension, the complete finite tail, and every output sample. Geometry is `frames=(Ns+254)/128`, `tau_last=frames*128`, and `Ny=tau_last+384`; Ns1024 therefore gives nine frames and 1,536 outputs. Output precedes the frame trigger at each hop, preserving the reference's 384-sample delay.

Analysis-window products retain Q15 precision. FFT input is bit reversed, the radix-2 FFT rounds each butterfly by two, and complex multiply rounding is nearest with ties away from zero. Canonicalization rounds the positive pair once and conjugates that result. The strict unsigned 56-bit magnitude comparison protects DC and permits masking Nyquist; each conjugate pair shares one decision. The bit-reversed IFFT has no stage normalization. Synthesis rounds the window product by15, WOLA adds at the same relative offset, and final output rounds by15 then saturates to signed12.

FFT workspace is signed32 with the signed28 arithmetic contract; IFFT and OLA use signed64 with signed36 and signed37 contracts. Twiddles use signed32 so +32768 is representable, and the window uses unsigned16 with an admitted maximum32768. Worst contract product/pre-sum widths (FFT45/46, IFFT53/54) and unsigned56 magnitude fit 64-bit arithmetic. Multiplications explicitly widen before evaluation. No negative signed shift or signed-overflow wraparound is used.

The checked instantiation rejects internal out-of-range values instead of saturating away a reference-contract violation. It executes outside timing before and after every record. The timed instantiation uses identical arithmetic with those redundant guards removed, under the admitted immutable input/coefficient/threshold assumption. Final signed12 saturation remains active in both paths.

## Timing and validation

Default measurements use one epoch per trial and at least20 repeated trials. Three warmup epochs execute before records; an additional checked epoch immediately before each record also warms the kernel. Buffers and record storage are preallocated. On Linux, wall time uses `CLOCK_MONOTONIC_RAW` when supported, otherwise `CLOCK_MONOTONIC`; thread time uses `CLOCK_THREAD_CPUTIME_ID`. A non-Linux smoke run uses a monotonic `steady_clock` and reports unavailable thread CPU time rather than substituting process time. Thread timestamps enclose the wall timestamps and loop.

Every timed epoch resets logical state, runs the entire finite datapath, then calls a separately compiled opaque consumer with a compiler memory barrier, one volatile output read, and an O(1) rolling checksum. The measured cost includes this small consumer overhead. No oracle comparison, allocation, or per-sample checksum occurs in the timed loop.

The full checked and fast outputs must match the supplied expected file before timing begins. Before each record, a checked epoch and full comparison run outside timing. Immediately after each record, the actual last timed output is fully compared before being overwritten, then another checked epoch is compared. With `--epochs 1`, every timed epoch's complete output is checked. For optional multi-epoch batching, only the final timed epoch receives a full check; every epoch reaches the opaque consumer, and JSON explicitly reports that the intermediate timed epochs were not individually fully checked.

This source produces per-trial wall/CPU measurements and exact work counts. It does not invent a CPU clock, claim ARM results from a host smoke run, infer board energy from elapsed time, or assert a CPU/FPGA speedup without matched on-board evidence. Reference FPGA finite work is 88,524 cycles for one epoch; longer batches have 88,138 cycles per additional epoch plus the initial386-cycle setup. Those counts are context for a separately controlled comparison, not hardcoded CPU timing expectations.
