# TSH2 seeded RTL verification

This is a compact, CPU-only verification example for the T-RECAP fixed-point audio pipeline. It exercises the registered PCM stream source, FFT, Hermitian canonicalizer, threshold mask, IFFT, WOLA, delayed error metrics and RAM-backed spectral exporter. The 26 DUT files are unchanged snapshots from the tested TSH2 FPGA image. No board or vendor HPS model is needed.

The example demonstrates test planning, deterministic constrained stimulus, procedural assertions, exact scoreboards, observed functional coverage, checker negative controls, bounded execution and machine-readable reporting. It is plain SystemVerilog and Python, not UVM or an SVA/concurrent-assertion environment.

## Quick start

Python 3.10 or newer is sufficient for the portable package and checker checks:

```sh
python run.py --check-package
```

That command audits admitted source and fixture hashes, then verifies that the Python scoreboard accepts a constructed correct trace and rejects deliberately damaged traces. These constructed traces are checker qualification, not RTL execution evidence.

For actual RTL simulation, install or use an existing licensed ModelSim/Questa environment and make `vlib`, `vmap`, `vlog` and `vsim` available:

```sh
python run.py --suite smoke --sim-bin /path/to/modelsim/bin --out runs/smoke_01
python run.py --suite regression --sim-bin /path/to/modelsim/bin --out runs/regression_01
```

`MODELSIM_BIN` or tools on `PATH` can replace `--sim-bin`. Paths with spaces are passed as separate process arguments; no shell is invoked. Output directories must be new and are never overwritten. Python exits nonzero for a failed test, missing tool, missing completion, unhit required event bin or watchdog expiration.

The smoke selection runs threshold zero/dense and threshold 100,000,000/sparse with seed 1. Regression runs both thresholds in both packet modes with seeds 1, 7 and 20261017. Each epoch accepts 1,024 input samples, checks 1,536 finite-tail output samples, nine frames and 1,161 canonical-bin rows. A seed can be reproduced exactly:

```sh
python run.py --suite regression --seeds 7 --out runs/reproduce_seed7
```

The default host watchdog is 180 seconds per tool invocation. `--timeout` changes that deadline. Independent simulation cycle limits also terminate missing progress. On timeout, the runner attempts to stop only its own child process tree and records the cleanup result; it also has a direct-child kill fallback. The recorded Windows host-level probe successfully terminated the spawned simulator trees. A separate sandbox probe denied tree cleanup, used the direct-child fallback and still failed closed. POSIX process-group cleanup is implemented but was not executed in this campaign. All functional compiles omit `SYNTHESIS`.

## What is checked

| Requirement | Observable check |
|---|---|
| Input preservation and finite zero extension | Every accepted source value and absolute sample index |
| Numerical equivalence | Every accepted Y value and index; all canonical real/imaginary/magnitude/mask/eligibility fields; exact packet bytes |
| Flow control | Held Y and packet payloads remain stable; input valid is held until acceptance; one-frame export credit is preserved |
| Finite completion | Exact counts, one discontinuity per epoch, empty PCM FIFO, all nine records retired |
| Final sample stall | Last Y token held for `32 + seed % 32` cycles; busy stays high and completion stays low until acceptance |
| Error metrics | Exact final sample count, absolute-error sum, squared-error sum and maximum error using an independent absolute-index calculation |
| FIFO events | Observed empty, one-entry and full cycles; simultaneous push/pop; exactly four read and write pointer wraps |
| Checker activation | A separate RTL run flips only the expected first Y value and must fail with `Y_GOLD_MISMATCH` and a nonzero simulator exit |

The driver uses an explicit 32-bit LFSR recurrence, with input pauses and independent output backpressure. It drives at falling clock edge +1 ns. The test coordinator operates at falling edge +2 ns. The monitor samples accepted transfers at the rising edge before nonblocking updates. The functional test clock is 10 ns with 1 ps precision; it is not a board timing or throughput measurement.

Required coverage bins increment on observed DUT transactions or states, not on scheduled stimulus. Counts and schedule fingerprints appear in `coverage.csv` and `summary.json`. There is no code-coverage percentage. A zero count in a required reachable bin fails the run.

## Results and CI

Each run retains:

- `run_manifest.json`: source/fixture hashes, selected cases, seeds, file list, defines and tool locations.
- `*.command.json` and raw logs: exact argv, working directory, tool hash, exit code and deadline.
- `seed_*/source.csv`, `y.csv`, `taps.csv`, `packet_*.bin` and `coverage.csv`: actual accepted DUT outputs and observed events.
- `summary.json` and `junit.xml`: CI-friendly status and individual seed/negative-control results.

Ordinary GitHub-hosted jobs can run `--check-package`. RTL simulation requires an appropriately licensed simulator on a local machine or a configured self-hosted runner. No unexecuted hosted RTL job is claimed. This package was developed against ModelSim Intel FPGA Starter 2020.1 on Windows. The Python runner uses portable standard-library APIs; Linux simulator execution is not claimed unless separately run and recorded. Icarus is not advertised for this active typed-interface source closure.

## Fixture and source provenance

`admission.json` binds the copied DUT bytes to the registered TSH2 source ID and original SOF hash. The source closure contains no vendor bridge, board constraints or proprietary simulator files. `fixtures/provenance.json` records the generated synthetic input, fixed C++ reference and independent integer-oracle comparison. The signal consists of integer triangle components and deterministic low-amplitude LCG noise. It is not a recording. Packet expectations encode the independently checked canonical-bin values using the existing TSP1 packet contract.

Coefficient bytes are the registered fixed-point window and twiddle tables. Source and fixture changes require an intentional admission update; a silent mismatch is rejected before simulation. Frozen release evidence is kept outside this package.

## Limits

This short regression complements the larger release campaign. It does not repeat full 384,000-sample runs, busy-reset phase sweeps, arithmetic corner suites or physical board checks. It does not prove formal properties, analog CDC/metastability behavior, physical timing, every arithmetic width or 64-bit counter overflow. Dynamic threshold commits, live codec/ADC, DDR and UDP profiles are outside this selected static TSH2 path. Passing these tests is bounded functional evidence, not industrial certification.
