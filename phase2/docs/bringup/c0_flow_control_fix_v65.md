# C0 flow-control fix v65

File class: **[1] hand-written bring-up and verification note**.

## Scope

This change fixes accepted-sample conservation between the real C0 BRAM replay
source, `trecap_input_ring`, and `trecap_frame_scheduler`.

It does not claim full C0 arithmetic or finite-tail signoff.

## Changed files

Production RTL:

- `rtl/core/trecap_input_ring.sv`: conservative sample admission, deterministic
  zero on a positive-index tag miss, and simulation-time safety checks.
- `rtl/sources/trecap_bram_replay_source.sv`: portable, clear-safe
  hold-under-backpressure monitor; datapath behavior is unchanged.

Regression and handoff:

- `sim/tb/tb_trecap_c0_flow_control.sv`
- `sim/filelists/c0_flow_control.f`
- `scripts/sim/check_c0_flow_control_model.py`
- `scripts/windows/run_c0_golden_v70.ps1` (current superset runner)
- `sim/README.md`

## Pre-fix failure

The old input ring asserted `sample_ready_o` continuously while enabled. With a
continuously-valid replay source:

- a frame becomes due every `H=128` accepted samples;
- one frame extraction requires at least `L=256` accepted frame beats;
- the scheduler can hold only one unaccepted request.

The third due frame therefore arrives while the second request is still
pending. The scheduler retains the old request, sets its protocol-error sticky
bit, and drops the new frame. Continued ring writes can then replace unread
sample tags.

## Fixed admission rule

`trecap_input_ring` now advertises source capacity only when no request or
extraction state owns the ring:

```systemverilog
sample_ready_o =
    enable_i &&
    !clear_i &&
    !frame_req_valid_i &&
    !frame_active_q &&
    !out_valid_q;
```

The BRAM replay source already holds `valid`, sample data, and `sample_idx`
stable while `ready=0`, so no source data or index is discarded.

Because the directly connected scheduler consumes the ring's registered
acceptance pulse, one post-boundary look-ahead sample may be accepted before
`frame_req_valid_i` rises. That sample is newer than the requested frame and
cannot replace its contents with the required `DEPTH >= 2*L`. This bound relies
on the scheduler raising and holding its request on the next clock; it is not a
standalone guarantee for an arbitrary external requester.

On a positive-index tag miss, the ring now emits deterministic zero and sets
its sticky error. It no longer leaks the newer sample stored at the reused
physical address. A simulation-time check also reports the tag miss
immediately.

## Required invariants

For the conservative C0 replay path:

1. A source index advances only on `sample_valid && sample_ready`.
2. Source payload and index remain stable throughout every ready-low interval.
3. `frame_req_valid || frame_active || frame_sample_valid` implies
   `sample_ready == 0`.
4. Each accepted-sample count that is a positive multiple of `H` creates one
   request.
5. Request triggers are `H-1, 2H-1, 3H-1, ...`.
6. Every accepted frame has exactly `L` beats, offsets `0..L-1`, and `last`
   only at `L-1`.
7. Every positive-index ring read has a matching valid tag.
8. Scheduler protocol error and ring overflow stay clear.

## Verification included

`sim/tb/tb_trecap_c0_flow_control.sv` instantiates
`trecap_bram_replay_source`, continuously offers 768 samples, applies a
720-clock extraction stall, and requires:

```text
accepted samples        = 768
accepted frame requests = 6
frame triggers          = 127, 255, 383, 511, 639, 767
completed frames        = 6
completed frame beats   = 1536
```

This exceeds the 512-entry physical ring depth and checks strict frame/offset
ordering, source/output hold-under-backpressure, known-valued payloads, source
completion, the one-sample look-ahead bound, and all sticky errors. Address
wrap across time, repeated frames, duplicated offsets, and reordered beats
cannot pass on aggregate counts alone.

The scoreboard also requires all 720 directed stall clocks to overlap a valid
held frame beat, so timing drift cannot silently reduce the test to its short
periodic stalls.

This regression instantiates the replay source, input ring, and scheduler
directly. It does not elaborate `trecap_core_top` or
`trecap_core_bram_replay_top`; backpressure is injected at the frame extractor
boundary rather than propagated through analysis, FFT, IFFT, and WOLA.

`scripts/sim/check_c0_flow_control_model.py` is a cycle-level executable model
that reproduces the legacy loss and checks the fixed conservation behavior.
It is not a substitute for RTL simulation.

The historical v65 runner is no longer shipped. The current superset runner is:

```text
scripts/windows/run_c0_golden_v70.ps1
```

## Verification status in the construction environment

- SystemVerilog 1800-2023 parse of the replay source, changed ring RTL,
  scheduler, generated packages, and testbench: pass.
- Synthesizable `trecap_input_ring` process/hierarchy check: pass, zero Yosys
  structural problems after substituting generated package constants for the
  checker's unsupported module-import syntax.
- CXXRTL execution of the patched ring plus scheduler, with 768 patterned
  samples, physical address wrap, the 720-cycle stall, periodic backpressure,
  and strict frame/offset/data checking:

```text
CXXRTL_PASS samples=768 frames=6 beats=1536 triggers=[127,255,383,511,639,767] cycles=3420
```

- Executable control model:

```text
LEGACY_FAIL due=6 accepted_frames=2 dropped=4 reserved_accepts=639
FIXED_PASS samples=768 frames=6 beats=1536 triggers=[127, 255, 383, 511, 639, 767] lookahead=1 cycles=3420
```

- ModelSim/Questa RTL execution: not run in the construction environment
  because no HDL simulator is installed there. Run the supplied PowerShell
  runner before treating this patch as hardware evidence.

The conservation guarantee assumes contiguous accepted sample indices,
`enable_i=1`, and no mid-frame clear/discontinuity. Arbitrarily long
backpressure preserves stored data, but infinite backpressure does not promise
completion.

## Known blockers not fixed here

Do not call C0 signoff complete after this patch. Separate fixes are still
required for:

- finite-tail ticks creating extra active frames;
- WOLA retaining its final registered output valid during `STATE_ADD`;
- delayed-input metric storage addressing modulo `D` instead of its declared
  `DEPTH`;
- exact `busy`, `done`, output-count, and stable frame-count semantics;
- full artifact comparison in RTL simulation and on the DE1-SoC board.
