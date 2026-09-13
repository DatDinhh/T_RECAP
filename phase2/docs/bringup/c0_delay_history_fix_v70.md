# C0 delayed-x history and metric alignment v70

File class: **[1] hand-written bring-up and verification note**.

## Scope

v70 repairs the delayed-input history used by:

```text
e[n] = xz[n-D] - y[n]
```

For Revision J:

```text
L = 256
G = 128
D = L + G = 384
HISTORY_DEPTH = 1024
```

This revision does not add Platform Designer, DDR, HPS, Ethernet, live audio,
or board signoff.

## Correct history contract

The old implementation addressed both x writes and delayed reads modulo
`D=384`, despite declaring 1,024 entries. Therefore `x[384]` reused the slot
holding `x[0]` before the module had proved that `y[384]` consumed it.

v70 uses an ordered FIFO with:

```text
write pointer
read pointer
occupancy 0..1024
next accepted x index
next admitted y index
next retired x index
synchronous tagged history RAM
```

For every admitted `y[n]`:

```text
n < D   -> delayed x is exact zero extension
n >= D  -> FIFO head tag must equal n-D
```

A future x sample causes legal y backpressure. A missing sample behind the
accepted-x frontier, a tag mismatch, a wrong index, count exhaustion, RAM
collision, or impossible occupancy enters fail-stop:

```text
x_ready = 0
y_ready = 0
busy    = 1
```

Only full alignment clear/reset releases fail-stop. Generic sticky clear cannot
hide it.

## Atomic source fork

The input ring and delayed-x FIFO must accept exactly the same source token.
The registered input-ring accept pulse is scheduler-only because it arrives one
clock too late for history credit reservation.

The core implements:

```systemverilog
sample_ready_o = input_ring_sample_ready_w && delay_x_ready_w;
ring_valid     = sample_valid_i && delay_x_ready_w;
delay_x_valid = sample_valid_i && input_ring_sample_ready_w;
```

Thus public handshake, ring write, and history write occur on one edge or not
at all.

## RAM and full policy

The history instantiates `trecap_simple_dual_port_ram` with `WRITE_FIRST=0`.
Memory contents are not reset; pointer and occupancy reset invalidate stale
data.

When occupancy is exactly 1,024, x does not borrow credit from a same-cycle
retirement. The required x is read first, then the freed address may be written
on the following clock. This one-cycle full-boundary bubble eliminates
same-address read/write dependence.

The synchronous RAM response is captured in a dedicated pending-response
register. `rd_valid` is only one clock wide, so the tag and delayed sample must
remain available if the public y output is stalled when that pulse arrives.
Without this latch, a valid delayed sample can be read once and then lost while
the pending y transaction waits for output credit.

## Metric behavior

The 16-bit observation error is produced from the full signed sample
difference. Aggregate metrics use the unsaturated full error:

```text
sum_abs_err_lo = low64(sum(abs(e[n])))
sum_sq_err_lo  = low64(sum(e[n]^2))
max_abs_err    = max(abs(e[n]))
```

Low words wrap normally and latch `metric_overflow_sticky`; they do not freeze.
Metric truncation survives generic sticky clear and clears only with the metric
epoch. `clear_metrics_i` blocks y admission for its pulse so no sample is
counted while omitted from sums.

Negative error detection uses the explicit sign bit of the full-width error.
It does not depend on the signedness that a simulator assigns to a comparison
against an unsized all-zero literal.

Private delay faults map only to generated global CSR meanings:

```text
arithmetic fault -> ARITHMETIC_OVERFLOW
history fault    -> RING_OVERFLOW
```

They never alias malformed-packet or illegal-command bits.

## Completion changes

Delay occupancy, a pending synchronous read, the public y buffer, and fail-stop
all participate in `core_busy_o`.

BRAM replay exact completion now also requires:

```text
core_error_sample_count_o == Ny
```

Any core protocol, metric-overflow, or core overflow status is latched into the
completion epoch and blocks `done`.

## Directed regression

Files:

```text
scripts/sim/check_c0_delay_history_model.py
scripts/sim/check_c0_native_runner_closure.py
sim/tb/tb_trecap_delay_history.sv
sim/filelists/c0_delay_history.f
sim/filelists/c0_v67_regression.f
scripts/windows/run_c0_golden_v70.ps1
```

Coverage includes:

- startup `y[0..383]` zero extension;
- `y[384]` waiting cleanly for `x[0]`;
- exact extreme error `-2048 - 2047 = -4095`;
- 1,024-entry full backpressure;
- a 41-clock public output stall;
- retention of a one-cycle synchronous RAM response across that stall;
- 2,304 x samples, crossing more than two address wraps;
- malformed index fail-stop and sticky-clear resistance;
- clear with retained history and stalled output;
- restart from index zero;
- finite geometry `x=1,152`, `y=1,536` through the native full-core suite.

Run:

```powershell
& ".\scripts\windows\run_c0_golden_v70.ps1" `
  -Repo (Resolve-Path ".").Path `
  -ModelSimExe "D:\Quartus\modelsim_ase\win32aloem\modelsim.exe" `
  -PythonExe "python"
```

Required new sentinels:

```text
C0_NATIVE_RUNNER_CLOSURE_PASS
C0_MAG2_WIDTH_PASS
C0_DELAY_HISTORY_MODEL_PASS
C0_DELAY_HISTORY_PASS
```

The suite still requires:

```text
C0_ARTIFACT_RTL_PASS
C0_ARTIFACT_POSTCHECK_PASS
C0_GOLDEN_SUITE_PASS vectors=1
```

## Evidence boundary

The dependency-free model and a locally lowered CXXRTL execution both run in
the construction environment. The CXXRTL run exercises 2,304 x samples, 2,688
y samples, more than two RAM wraps, a full FIFO, a 41-clock output stall,
metric equality, fail-stop, sticky-clear resistance, and full-clear recovery.
Slang/Yosys also elaborates the complete BRAM-replay core and reports zero
structural problems.

Native Intel RTL evidence still requires ModelSim/Questa. Quartus block-RAM
inference, Fitter use, and STA remain later gates; this source does not claim
them.
