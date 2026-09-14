# Step 12 DDR-ring ownership and boundary gate

Windows examples read `MODELSIM_EXE` and `MODELSIM_BIN` from the local shell environment. Set these to the executable and installation directory on the current machine; installation paths are not part of the repository.

Run every simulator-independent Step 12 gate, including the source contract,
the dependency-free boundary model, repository layout, generated contracts,
and frozen-artifact checks:

```bash
make check-ddr-ring-ownership
make check-step12-ring-model
make step12-source
```

With ModelSim/Questa (`vlib`, `vlog`, and `vsim`) available, compile and run
the directed DDR-ring regression:

```bash
make compile-step12-ddr-ring
make sim-step12-ddr-ring-ownership
make step12
```

On Windows, the native runner provides the same fail-closed model, compile,
simulation, and sentinel checks:

```powershell
powershell -ExecutionPolicy Bypass -File `
  scripts/windows/run_step12_ddr_ring_ownership.ps1
```

`step12` is intentionally not a source-only alias: it succeeds only after the
native simulator reaches `STEP12_DDR_RING_OWNERSHIP_PASS`. The regression
checks the explicit HPS `Rd=0` re-arm, monotonic/aligned `Rd`, FPGA-only `W`,
exact-end and WRAP boundaries, guard/free-space admission, response-failure
atomicity, and deterministic reset/reconfigure behavior. The dependency-free
model is an independent arithmetic oracle, not evidence that RTL was executed.

The static reservation source under `platform/de1soc/linux/` is part of this
gate. Its presence and source checks do not by themselves prove that a deployed
kernel loaded the expected DTB or excluded the range at runtime; hardware
bring-up must retain the boot-log, active-DTB, and `/proc/iomem` evidence.

# Step 11 BRAM-replay end-to-end source gate

Run the static path-contract gate independently:

```bash
make check-bram-replay-path
```

With ModelSim/Questa (`vlib`, `vlog`, and `vsim`) available, compile or run the
logical BRAM-replay closure with:

```bash
make compile-bram-replay-system
make sim-step11-bram-e2e
make step11
```

On Windows, use the fail-closed native runner:

```powershell
& ".\scripts\windows\run_step11_bram_e2e.ps1" `
  -Repo (Resolve-Path ".").Path `
  -ModelSimBin "$env:MODELSIM_BIN"
```

This repository snapshot contains the testbench and runner source; it does not
claim that ModelSim/Questa was executed. The board wrapper's registered local
`OKAY` response proves only that the generated bridge accepted a legal write
beat. It is not physical-DDR completion or downstream hardware-error evidence.

# C0 functional regressions

## Full-width mag2, delayed-x history, and exact metrics (v70b)

`tb/tb_trecap_mag2_width.sv` verifies that signed canonical real/imaginary
components are squared at the full 56-bit product width. It includes the exact
first row that exposed the v70a native mismatch, signed extrema, the maximum
legal `2^55` result, a below-threshold case, and an exact-threshold case.

`tb/tb_trecap_delay_history.sv` directly verifies the 1,024-entry delayed-x
FIFO, synchronous tagged read, strict x/y indices, full backpressure, more than
two pointer wraps, startup zero extension, nonzero extreme arithmetic, hard
fail-stop, mid-run clear, metric-clear admission, and restart from index zero.

Run the architectural model anywhere:

```bash
python3 scripts/sim/check_c0_delay_history_model.py
```

Run the complete native suite on Windows:

```powershell
Set-ExecutionPolicy -Scope Process Bypass -Force
& ".\scripts\windows\run_c0_golden_v70.ps1" `
  -Repo (Resolve-Path ".").Path `
  -ModelSimExe "$env:MODELSIM_EXE" `
  -PythonExe "python"
```

v70b first proves that every top invoked by the runner is in its exact compile
closure. The added native sentinels are:

```text
C0_NATIVE_RUNNER_CLOSURE_PASS
C0_MAG2_WIDTH_PASS
C0_DELAY_HISTORY_PASS
```

## Exact frozen-artifact scoreboard (v68)

`tb/tb_trecap_c0_golden.sv` drives the full C0 BRAM-replay path with the
frozen near-threshold vector. Its fail-closed scoreboard checks:

- every accepted output sample and index against `y_out.memh`;
- every valid frame-stat transaction against `frame_stats.csv`;
- every unique canonical-bin transaction, including signed real/imaginary
  values and the pre-mask decision, against `bin_stats.csv`;
- independently accumulated suppression, spectral-energy, and time-domain
  metrics against `metrics.json`;
- the core's own time-error accumulator outputs at exact completion;
- stable output payload under deterministic backpressure and a directed
  37-cycle stall of `y[Ny-1]`;
- exactly one done pulse followed by 32 cycles with no extra activity.

The Python preflight validates the artifact schemas, hashes, row counts,
ordering, stream geometry, threshold semantics, cross-artifact totals, and
fixed-point widths before compilation. The post-check then compares the
simulator's canonical capture files byte-for-byte with the frozen artifacts.

The historical v68 runner is no longer shipped. Run its current v70b superset
on Windows:

```powershell
Set-ExecutionPolicy -Scope Process Bypass -Force
& ".\scripts\windows\run_c0_golden_v70.ps1" `
  -Repo (Resolve-Path ".").Path `
  -ModelSimExe "$env:MODELSIM_EXE"
```

The run is valid only if it ends with all four artifact sentinels:

```text
C0_ARTIFACT_SNAPSHOT_PASS
C0_ARTIFACT_RTL_PASS
C0_ARTIFACT_POSTCHECK_PASS
C0_GOLDEN_SUITE_PASS vectors=1
```

This v68 harness intentionally supports only
`near_threshold_multitone_Ns1024_thr64`, the only frozen vector with
`bin_stats.csv`. The raw RTL threshold is read from `config.json` and is
`THR2=4096`; the `thr64` suffix is not a raw threshold value. See
`docs/bringup/c0_artifact_scoreboard_v68.md` for the exact contract and
known coverage limits.

## Busy, frame count, and exact public-output completion (v67)

`tb/tb_trecap_c0_active_tail.sv` now stalls the final public output
`y[Ny-1]`, not the first drain output. Replay and WOLA are already complete
during this stall, so the test directly proves that their internal counts
cannot assert top-level completion early.

For `Ns=1024`, the regression requires:

- a persistent, monotonic scheduler frame count ending at exactly nine;
- `core_busy_o` during input-ring, FFT, IFFT, WOLA, and final-output-buffer
  work, including internal compute intervals with no output valid;
- public output count `1535` and `done=0` while `y[1535]` is stalled;
- public output count `1536` before the single completion pulse;
- exact replay, WOLA, analysis-sample, and frame counts at completion;
- `top_busy_o=0`, sticky `top_done_o=1`, and no completion error afterward.

The dependency-free completion model also exercises fail-closed undercount,
wrong-index, and extra-output paths:

```bash
python3 scripts/sim/check_c0_exact_completion_model.py
```

The historical v67 runner is no longer shipped. Run the current v70b superset
on Windows:

```powershell
Set-ExecutionPolicy -Scope Process Bypass -Force
& ".\scripts\windows\run_c0_golden_v70.ps1" `
  -Repo (Resolve-Path ".").Path `
  -ModelSimExe "$env:MODELSIM_EXE"
```

The runner first requires `C0_EXACT_COMPLETION_MODEL_PASS`, then all four RTL
sentinels: `C0_FLOW_CONTROL_PASS`, `WOLA_TAIL_DRAIN_PASS`,
`C0_EXACT_COMPLETION_PASS`, and `C0_ACTIVE_TAIL_PASS`.

## Historical active-frame scheduling and WOLA tail drain (v66)

The v66 release's version of `tb/tb_trecap_c0_active_tail.sv` instantiated the
complete C0 BRAM-replay top with an all-zero `Ns=1024` vector and the
Revision-J full-tail policy. The current v67 file supersedes that test and
stalls the final output as described above.

```text
Nframes       = 9
tau_last      = 1152
analysis zero = 128 ticks
pure drain    = D = 384 ticks
Ny            = 1536
```

Replay still presents all `Ny` logical ticks. The top routes indices below
`tau_last` through the input ring and scheduler; indices at or above
`tau_last` use the WOLA drain ready/valid path only.

The regression requires:

- exactly 1,536 accepted replay ticks and continuous indices `0..1535`;
- exactly nine frame boundaries and nine frame-stat events;
- exactly `9*129 = 1,161` unique-bin events;
- no frame/bin/stat event while the WOLA drain state is active;
- exactly 384 drain-token handshakes;
- exactly 1,536 accepted output samples with continuous indices;
- stable output payload through a directed stall at output index 1,152;
- no dummy frame, duplicate output, protocol error, or saturation.

`tb/tb_trecap_wola_tail_drain.sv` independently exercises the WOLA boundary
without FFT/IFFT latency. It holds the first tail token before the final active
frame, feeds nine nonzero IFFT frames through a test-only unity-Q15 window,
checks the exact nonzero overlap sum at every output, stalls output index 1,152
for 73 clocks, and requires:

- 2,304 accepted active-frame beats;
- 384 accepted drain tokens and 384 matching accept pulses;
- exactly 1,536 outputs with continuous indices `0..1535`;
- stable output and drain-token payloads through backpressure;
- one drain-done pulse only after output 1,535 is accepted.

The dependency-free geometry model is:

```bash
python3 scripts/sim/check_c0_active_tail_model.py
```

The historical v66 runner is no longer shipped. Run the current v70b superset,
which includes the conservation and tail regressions:

```powershell
Set-ExecutionPolicy -Scope Process Bypass -Force
& ".\scripts\windows\run_c0_golden_v70.ps1" `
  -Repo (Resolve-Path ".").Path `
  -ModelSimExe "$env:MODELSIM_EXE"
```

The runner is fail-closed: compilation alone is insufficient; all three PASS
sentinels (`C0_FLOW_CONTROL_PASS`, `WOLA_TAIL_DRAIN_PASS`, and
`C0_ACTIVE_TAIL_PASS`) must appear, and any ModelSim Error/Fatal fails the run.

## Replay-to-scheduler flow control (v65)

`tb/tb_trecap_c0_flow_control.sv` verifies the accepted-sample boundary between
the instantiated BRAM replay source, input ring, and frame scheduler.

The test continuously offers `6*H = 768` indexed samples and stalls frame
extraction for 720 clocks. It requires:

- 768 source and ring sample handshakes with no index gaps or duplicates;
- six consecutive frame requests with trigger indices
  `127, 255, 383, 511, 639, 767`;
- exactly six accepted frame requests and six frame boundaries;
- exactly `6*L = 1536` extracted frame beats;
- frame indices and offsets in strict order, with no repeats, gaps, or reordering;
- correct zero extension and sample data on every beat;
- stable source payload whenever `ready=0`;
- stable frame payload whenever downstream `ready=0`;
- all 720 directed stall clocks overlap a valid held frame beat;
- at most one accepted post-boundary look-ahead sample before each request;
- exactly one accepted replay start and a clean replay `done`;
- no scheduler protocol error and no input-ring overflow/tag miss.

Six hops exceed the 512-entry physical ring depth, so the test exercises address
wrap and tag reuse rather than checking only the pre-wrap frame-drop case.

This is a flow-control regression, not a mathematical FFT/IFFT/WOLA signoff.

The dependency-free architectural model can be run anywhere with Python 3:

```bash
python3 scripts/sim/check_c0_flow_control_model.py
```

It must reproduce a dropped frame with the legacy always-ready policy and full
conservation with the conservative gate. It does not replace HDL simulation.

The historical v65 runner is no longer shipped. On Windows with Intel ModelSim
Starter Edition, run the current v70b superset:

```powershell
Set-ExecutionPolicy -Scope Process Bypass -Force
& ".\scripts\windows\run_c0_golden_v70.ps1" `
  -Repo (Resolve-Path ".").Path `
  -ModelSimExe "$env:MODELSIM_EXE"
```

The runner compiles and executes the test. A compile-only transcript is not
accepted as evidence. Logs are written under `runs/c0-flow-control-v65/`.
