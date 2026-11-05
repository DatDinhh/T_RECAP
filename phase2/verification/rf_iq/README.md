# Recorded RF design verification

This package exercises the TRF1 recorded-file application and its new I/Q adapter against the unchanged T-RECAP core. It contains runnable SystemVerilog testbenches, synthetic numerical fixtures, an independent full-convolution reference check, exact source bindings and recorded execution evidence.

The input is a finite file of unsigned 8-bit I/Q pairs. The adapter centers each byte with `2*b - 255`, interpolates by four with an 81-tap fixed FIR, mixes to a quarter-rate real IF and rounds to signed 12-bit samples. The file wrapper emits the valid `4*N` prefix and pads the remainder of the configured core transaction. The existing FFT, threshold, IFFT/WOLA and TSP1 exporter are preserved.

## Check boundaries

| Suite | Scope and checking method |
|---|---|
| Adapter | 36 synthetic numerical fixtures and four recovery replays for each of three deterministic seeds. Every accepted sample, clipping flag, index and final marker is checked against independent full convolution. Includes input gaps, output stalls, held output stability, changing busy configuration pins, invalid lengths, reset and clear |
| Limit | 96,000 I/Q pairs and 384,000 exact output samples. Deliberate gain-3 clipping, signed half ties and randomized flow control |
| Wrapper | Valid-prefix equivalence to the adapter, exact zero padding, indices, last marker, counters, stalls, invalid counts and abort recovery |
| Integration | Actual RF application and PCM comparison application through the same core. Sixteen configurations produce 32 completed epochs. Every source sample, Y sample, TSP1 byte and host FIFO read is compared. Added corners include one I/Q pair at gain 0, gain 2, and the maximum 56-bit threshold |
| Admission | Malformed input while ready, busy configuration rejection, source watchdog, reset while the input FIFO response is pending and clear while a prefetched pair waits. Recovery checks follow the aborts |

The numerical fixtures use no third-party recordings. Three recorded-source fixtures from the earlier local adapter campaign are excluded from this public package. Its fresh adapter counts therefore differ from the historical campaign.

The integration comparison uses an independent RF numerical model to prepare the PCM baseline. Both paths then use the same existing DSP core. It verifies integration equivalence and does not independently prove FFT arithmetic. Simulation uses 2,048 core input samples. The historical full-length physical campaign uses 384,000 samples and is documented separately.

## Reproduce

Run from the repository root. Python 3.12 is used by the recorded run. `--check-package` needs only the standard library and does not simulate RTL.

```sh
python phase2/verification/rf_iq/run.py --check-package
```

Reference regeneration requires NumPy and SciPy.

```sh
python -m pip install numpy scipy
python -m unittest discover -s phase2/profiles/trf1/adapter/model -p test_reference.py
python phase2/verification/rf_iq/check_reference.py --out rf_reference_check.json
python phase2/verification/rf_iq/make_fixtures.py --out regenerated_rf_fixtures
```

The portable runner accepts a directory containing ModelSim-compatible `vlib`, `vmap`, `vlog` and `vsim` executables. The recorded execution uses ModelSim Intel FPGA Edition 2020.1. Licensing and simulator installation are external prerequisites.

```sh
python phase2/verification/rf_iq/run.py --suite all --sim-bin /path/to/modelsim/bin --out rf_regression_01
```

Individual suites are `adapter`, `limit`, `wrapper`, `integration` and `admission`. Each run requires a fresh output directory. The runner copies immutable DUT sources and fixtures into that directory before compiling, so it does not write simulator products into the source tree. Each simulator process has a bounded timeout. The `all` command runs suites sequentially.

A positive result requires a zero process exit code, the expected completion marker, an explicit `checker_done=1` signal and no simulator error. The adapter suite also deliberately corrupts an expected value and requires a nonzero exit with `GOLD_MISMATCH`. That expected failure qualifies the scoreboard and is not a DUT failure.

## Source binding and evidence

- [Package manifest](package_manifest.json) binds testbenches, synthetic fixtures, runners and reference identities.
- [Frozen simulation closure](../../profiles/trf1/snapshot/manifest.json) contains the exact project-authored build02 RTL and coefficients needed by the testbench. It excludes the vendor-generated HPS bridge and top-level platform wrapper.
- [Editable RF source](../../profiles/trf1/README.md) is checked for byte equality with its frozen counterpart.
- [Bench changes](bench_origins.json) record the original bench hashes and the targeted extensions made for this publication.
- [Fresh execution summary](evidence/summary.json) links the accepted runs, observed counters and checker qualification.
- [Verification report](../../docs/verification/rf_iq/README.md) separates fresh simulation from historical fitting and physical execution.

Published logs substitute portable labels for local filesystem prefixes. Their records retain both original-output and published-output hashes. Generated build products and proprietary simulator binaries are not redistributed. The observed VCD is a simulator trace, not an illustrative waveform.

## Limits

This package performs no board access. It does not establish continuous RF throughput, physical RF reception, electrical-power reduction, universal denoising or arbitrary-protocol preservation. No formal proof, UVM execution or complete structural code coverage is claimed for the new RF adapter. Existing TSH2 formal and UVM evidence applies to its separately defined original scope.

The shared-core simulation uses `SYNTHESIS` to match the established wrapper build. The standalone adapter and wrapper suites run without that define. Reviewed inherited compiler diagnostics remain visible. The evidence is not described as warning-free.
