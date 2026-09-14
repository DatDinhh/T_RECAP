# C0 busy, frame count, and exact completion v67

> Historical design note. Revision-specific results and open items below belong to that development stage; they are not results or completion claims for the current source. See the [implementation plan](../architecture/architecture_implementation.md) for current scope.

File class: **[1] hand-written bring-up and verification note**.

## Scope

This revision builds on the v65 replay flow-control fix and the v66
active-frame/WOLA-tail split. It fixes three status contracts:

1. `core_busy_o` now covers internal compute states, not only visible
   ready/valid beats.
2. `core_frame_count_o` is the scheduler's persistent accepted-frame count.
3. top-level completion is based on the exact number of public output
   handshakes, followed by structural quiescence.

This is still a C0 control/counting milestone. It does not claim
bit-for-bit nonzero-vector signoff or DE1-SoC end-to-end integration.

## Frame-count contract

`trecap_frame_scheduler.sv` owns the authoritative frame counter. It increments
once per accepted frame request and is cleared on reset, `clear_i`, or source
discontinuity.

`trecap_core_top.sv` now exposes that counter directly:

```text
core_frame_count_o = scheduler accepted-frame count
```

It no longer derives a count from a one-cycle frame-statistics pulse. For
`Ns=1024`, the visible count is monotonic `0..9` and remains `9` after the last
statistics event.

## Busy contract

`core_busy_o` is asserted while any of the following work is in flight:

- an input sample is being accepted or forwarded;
- the input ring owns a frame extraction or held output beat;
- analysis-window load/output is active;
- FFT or IFFT load, compute, or output is active;
- canonicalizer, mask, or spectrum-builder data is held;
- WOLA collection/add/emit/drain work is active;
- the final public `y` beat is buffered and waiting for `y_ready_i`.

This closes the legal no-`valid` gaps during sequential FFT/IFFT compute and
WOLA `ADD`.

`top_busy_o` remains asserted for the entire accepted run. An early quiescent
undercount is fail-closed: it latches a completion error and keeps busy high
until reset or `clear_i`. A mid-run `clear_sticky_i` cannot erase a
completion-epoch fault and turn the same run into a pass.

## Exact output-count completion

The completion authority is the public interface handshake:

```systemverilog
y_valid_o && y_ready_i
```

`wola_output_count_o` is intentionally not sufficient. It counts accepted
WOLA-to-delay beats one buffer earlier than the public output.

For a valid finite run, v67 requires all five counts to be exact:

| Counter | Required final value |
| --- | ---: |
| Public accepted `y` outputs | `Ny` |
| Replay accepted logical ticks | `Ny` |
| WOLA accepted outputs | `Ny` |
| Core analysis samples | `tau_last` |
| Scheduler accepted frames | `Nframes` |

Completion is decided only on a later structurally idle cycle. Therefore the
handshake for `y[Ny-1]` cannot assert `done` combinationally on the same edge.

New top-level status outputs are:

```text
top_done_o                       sticky exact-completion level
top_done_pulse_o                 one-cycle completion event
top_output_accept_count_o        saturated public y-handshake count
top_expected_output_count_o      Ny for the configured finite stream
top_completion_error_sticky_o    undercount, extra output, or index/count mismatch
```

The public counter also checks that the accepted output index equals the
pre-increment count. It saturates at `Ny`; an extra beat cannot wrap or create
a false completion.

## Restart contract

An accepted replay start begins a new completion epoch and clears the public
count, `done`, and the prior completion error.

A new start is rejected while the prior run is still in flight, including the
case where replay and WOLA have completed but the final public output remains
stalled. This prevents a restart from clearing a buffered final beat.

Start admission also requires structural idle and a valid local build/geometry
contract. Auto-start-on-reset is disabled for an invalid configuration.
`clear_i` dominates a simultaneous explicit start and emits a reject pulse, so
the command cannot disappear without accept/reject evidence.

## Directed final-output stall

`sim/tb/tb_trecap_c0_active_tail.sv` now holds `y[1535]` for at least 73 clocks.
During that stall it requires:

```text
replay done/count       = true / 1536
WOLA output count       = 1536
public output count     = 1535
frame count             = 9
core_busy/top_busy      = 1 / 1
top_done/top_done_pulse = 0 / 0
```

After the final public handshake and structural idle:

```text
public output count     = 1536
top_done                = 1
top_done pulses         = exactly 1
top_busy                = 0
completion error        = 0
```

The test also requires coverage of hidden input-ring, FFT, and IFFT busy
intervals with no corresponding stage output valid.

It additionally presents one start together with `clear_i` and one start while
the final output is stalled. Each must produce exactly one reject pulse, no
second accepted run, and no disturbance to the active completion epoch.

## Verification

Dependency-free models:

```bash
python3 scripts/sim/check_c0_flow_control_model.py
python3 scripts/sim/check_c0_active_tail_model.py
python3 scripts/sim/check_c0_exact_completion_model.py
```

The exact-completion model uses explicit runtime checks, not Python `assert`,
so optimized Python cannot strip the fail-closed conditions while leaving a
false PASS sentinel.

The historical v67 runner is no longer shipped. Use the current native
ModelSim/Questa superset runner:

```powershell
& ".\scripts\windows\run_c0_golden_v70.ps1" `
  -Repo (Resolve-Path ".").Path `
  -ModelSimExe "$env:MODELSIM_EXE"
```

Required sentinels:

```text
C0_EXACT_COMPLETION_MODEL_PASS
C0_FLOW_CONTROL_PASS
WOLA_TAIL_DRAIN_PASS
C0_EXACT_COMPLETION_PASS
C0_ACTIVE_TAIL_PASS
```

Construction-environment results:

```text
direct SystemVerilog parse: 68/68 files PASS
flow-control RTL:           768 samples, 6 frames, 1536 beats PASS
WOLA RTL:                   9 frames, 384 drain, 1536 outputs PASS
full C0 RTL:                9 frames, 1536 public outputs PASS
directed final-y stall:     74 clocks, busy held, done blocked PASS
start admission:            clear collision and in-flight restart rejected PASS
completion model:           normal, undercount, wrong-index, extra-output PASS
```

The executable RTL checks used an old Icarus build with a verification-only
syntax compatibility translation. The checked-in SystemVerilog itself was
parsed directly and is what the native ModelSim runner compiles.

The RTL regression directly exercises normal exact completion, a final-output
stall, a clear/start collision, and an in-flight restart rejection. Undercount,
wrong-index, and extra-output fault branches are checked by the dependency-free
behavioral model in this revision; they are not yet forced into the native RTL
testbench.

ModelSim/Questa was not available for that historical revision. A native
runner result is required before treating v67 as Intel-simulator evidence.

## Explicitly deferred

- exact `y_out.memh`, `frame_stats.csv`, `metrics.json`, and `bin_stats.csv`
  comparison for nonzero frozen vectors;
- the delay-metrics RAM addressing issue identified in the broader audit;
- Quartus resource/timing closure and board BRAM replay;
- real core/CSR/DDR integration in the DE1-SoC platform top.
