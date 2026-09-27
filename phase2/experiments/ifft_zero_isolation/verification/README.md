# IFFT zero-operand isolation verification

`run_verification.py` creates a new, self-contained evidence directory and invokes native ModelSim. It accepts a frozen baseline repository, a candidate RTL overlay, an optional candidate repository containing the mode-3 measurement engine, and the Python profiler CSV. It does not program or query hardware and does not modify either input repository. It records input/tool SHA-256 hashes, exact commands, simulator logs, generated integer vectors, per-frame stage counters, and a machine-readable result in `manifest.json`.

Example (substitute your local paths):

```text
python -B run_verification.py --baseline-repo BASELINE --candidate-overlay OVERLAY --candidate-repo CANDIDATE --simulator-dir MODELSIM_BIN --run-dir NEW_RUN_DIRECTORY --profile-csv FRAME_STAGE_COUNTS_CSV
```

The run directory must not exist. All subprocesses have a bounded timeout (300 seconds by default, configurable with `--timeout-s`). Every simulation also has a testbench watchdog. A nonzero tool status, simulator Error/Fatal diagnostic, nonzero Errors summary, missing unique PASS banner, oracle/profile mismatch, or changed input file fails the run. `--skip-profile` runs only the arithmetic and IFFT tests.

## Checks

- `stage_lockstep_tb.sv`: frozen baseline versus compile-disabled, runtime-disabled, and enabled isolation. Two registered configurations use 36-bit operands: unnormalized 36-bit output (the physical IFFT path) and normalized 28-bit output. Each runs 2,304 independent integer-oracle vectors, then 24 recovery vectors. Cases include first-zero after reset, nonzero/zero transitions, scalar zeros, signed extrema, cancellation, half-way rounding, saturation, and deterministic random values (seed `0x5A17B00B`). Inputs change after acceptance; output stalls and reset/clear interruptions cover all six pipeline states. Hierarchical observations verify the actual multiplier input muxes retain the last accepted nonzero operands for zero transactions, including deterministic initial zeros.
- `ifft_lockstep_tb.sv`: frozen baseline and the same three candidate variants run 20 distinct 256-point frames plus recovery frames. Values, saturation/protocol status, all handshake/phase flags, output offset/frame/last tags, and completion timing match on every meaningful cycle. Nineteen nonsaturating frames also match the existing independent recursive integer oracle; the twentieth uses explicit saturating integer arithmetic and exercises full-frame saturation. Input gaps, output/last-output stalls, load/compute/output aborts, reset/clear recovery, protocol errors, and sticky retention are covered. Isolation control deliberately changes after the first accepted sample and during computation/output; the admitted frame's latched mode must remain unchanged.
- `core_profile_tb.sv`: passive baseline counters observe accepted IFFT butterflies through the full measurement replay engine. Two-epoch dense/masked batches exercise all nine frames per epoch and all eight stages. Candidate mode sequence 1Ã¢â€ â€™2Ã¢â€ â€™3Ã¢â€ â€™2 runs alongside an unisolated comparison engine, checking output, handshake, useful-input/frame counters, and elapsed cycles every cycle. Payload mode/count changes without a new start must not alter the admitted batch. Snapshot counters, mode-3 status, exact ROM outputs, retained completion, and explicit mode-0 idle admission are checked. The profile compares total/a-zero/b-zero/both-zero/neither-zero counts for every epoch/frame/stage with the Python profile.

## Evidence and limits

The [published experiment results](../../../docs/results/ifft_zero_isolation_20260925/README.md) identify the admitted evidence for this strengthened suite. Reproduction writes a fresh `manifest.json` with source/tool hashes and complete local diagnostics. Frozen baseline modules are copied into the run directory with only module identifiers changed, then instantiated alongside the candidate. Shared arithmetic helpers are also checked by independent Python integer goldens.

This is bounded simulation, not formal equivalence or a proof for all parameter combinations. It validates the registered butterfly and the deployed 256-point IFFT; it does not claim a power reduction, device timing closure, post-fit timing equivalence, or an exhaustive asynchronous-reset analysis. Full-core profiling uses the measured multitone workload at thresholds 0 and 100000000000. Hardware, fitted timing, VCD activity, and measured power are handled separately.

`verify_zero_host.py --candidate-repo CANDIDATE` runs ten pure host admission tests against the experimental runner, including the inherited timing/capture checks and protocol-2, isolation-status, command-mode and equal-cycle rejection cases. It uses no serial port, JTAG connection or external process.
