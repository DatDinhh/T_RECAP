# C0 active-frame / WOLA-tail split v66

> Historical design note. Revision-specific results and open items below belong to that development stage; they are not results or completion claims for the current source. See the [implementation plan](../architecture/architecture_implementation.md) for current scope.

File class: **[1] hand-written bring-up and verification note**.

## Scope

This change separates finite-stream active-frame scheduling from pure WOLA
tail emission. It builds on the v65 replay flow-control fix.

It does not claim final C0 signoff. Exact global `busy/done/frame_count`,
delay-metric RAM addressing, and nonzero golden-artifact equivalence remain
separate work.

## Revision-J geometry

For `Ns > 0`:

```text
Nframes  = floor((Ns + L - 2) / H)
tau_last = Nframes * H
Ny       = tau_last + G + L
D        = G + L
```

With `L=256`, `H=128`, and `G=128`, `D=384`.

The finite stream has three distinct phases:

| Phase | Logical index | Datapath |
| --- | ---: | --- |
| Real input | `0 .. Ns-1` | input ring, scheduler, FFT/mask/IFFT |
| Active zero extension | `Ns .. tau_last-1` | input ring, scheduler, FFT/mask/IFFT |
| Pure WOLA drain | `tau_last .. Ny-1` | OLA emit/clear/advance only |

The active zero-extension phase is required. Gating the scheduler at `Ns`
would lose valid late-overlap frames.

## RTL split

`trecap_core_bram_replay_top.sv` retains the existing `Ny`-tick replay
lifecycle and demultiplexes each held ready/valid token by its logical index:

```systemverilog
sample_idx < tau_last  -> core analysis input
sample_idx >= tau_last -> WOLA drain input
```

The scheduler also receives the exact `Nframes` limit as a fail-safe.

The first drain token is allowed to remain pending while the last active frame
travels through FFT/IFFT. `trecap_synthesis_wola.sv` begins drain only after:

1. all `H` outputs preceding the last active frame contribution were issued;
2. all `L` final synthesis samples completed OLA `ADD`; and
3. the pending drain token index equals the WOLA output issue index
   (`tau_last`).

Each accepted drain token emits, rounds, clears, and advances exactly one OLA
slot. The final token has index `Ny-1`.

Pure drain ticks bypass the delayed-input write port safely because the largest
reference input needed by time-error metrics is:

```text
(Ny - 1) - D = tau_last - 1
```

## WOLA final-valid correction

v65 left the last registered hop output valid during the entire `STATE_ADD`.
With a ready downstream, that duplicated the same output index. v66 clears a
registered output on `valid && ready` unless the same cycle replaces it with a
new frame/drain beat.

Drain completion pulses only when the final registered WOLA output is accepted
by its immediate downstream.

## Required invariants

For `Ns=1024`:

```text
replay ticks             = 1536
analysis/scheduler ticks = 1152
active frames            = 9
last frame trigger       = 1151
pure drain ticks         = 384
WOLA outputs             = 1536
last output index        = 1535
```

No frame boundary, unique-bin event, or frame-stat event may be created by the
384 pure-drain ticks.

## Verification

The self-checking full-core regression is:

```text
sim/tb/tb_trecap_c0_active_tail.sv
```

The focused WOLA regression presents the first tail token early, feeds nine
nonzero active frames through a test-only unity-Q15 window, checks the exact
overlap sum at every output index, and stalls the first drain output for 73
clocks:

```text
sim/tb/tb_trecap_wola_tail_drain.sv
```

The historical v66 runner is no longer shipped. The retained v70b Windows runner
compiles the full C0 core and executes a superset containing the v65 flow-control
test and both v66 tail tests:

```powershell
& ".\scripts\windows\run_c0_golden_v70.ps1" `
  -Repo (Resolve-Path ".").Path `
  -ModelSimExe "$env:MODELSIM_EXE"
```

Expected sentinels:

```text
C0_FLOW_CONTROL_PASS
WOLA_TAIL_DRAIN_PASS
C0_ACTIVE_TAIL_PASS
```

Construction checks completed:

```text
direct SystemVerilog parse: 47/47 files PASS
geometry model:             Ns=1,2,17,248,1024,4096 PASS
legacy flow model:          4/6 frames dropped as expected
fixed flow model:           768 samples, 6 frames, 1536 beats PASS
WOLA RTL simulation:        9 nonzero frames, exact OLA data, 384 drain PASS
full C0 RTL simulation:     9 frames, 1161 unique bins, 1536 outputs PASS
```

The executable RTL checks used an old Icarus build with a verification-only
compatibility translation for syntax that build does not support (package
imports, typed/sized casts, and nested packed-struct field selection). The
translation preserves the all-zero control/counting test semantics and is not
part of the deliverable RTL. The checked-in sources themselves were parsed
directly without translation.

ModelSim/Questa was not available for that historical revision. Run the
fail-closed Windows runner on the checked-in source before treating v66 as
native Intel-simulator evidence.

## Explicitly deferred

This revision does not silently claim the next work item:

- `core_frame_count_o` still uses the transient frame-stat index expression
  and falls back to `Nframes-1` after the final stats pulse.
- analysis/FFT/IFFT internal `busy_o` signals are still not included in the
  global busy/done contract.
- `core_sample_count_o` counts analysis ticks (`tau_last`); replay logical-tick
  count remains available separately and reaches `Ny`.
- the resettable `ola_mem`/`z_mem` implementation may infer registers rather
  than M10K RAM and needs Quartus resource/timing review.
