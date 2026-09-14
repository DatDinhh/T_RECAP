# C0 full-width canonical magnitude-squared fix v70b

> Historical design note. Revision-specific results and open items below belong to that development stage; they are not results or completion claims for the current source. See the [implementation plan](../architecture/architecture_implementation.md) for current scope.

File class: **[1] hand-written bring-up and verification note**.

## Native failure

The v70a Intel ModelSim run passed delay history, flow control, WOLA tail drain,
exact completion, and active-tail regressions. The exact artifact scoreboard
then stopped at:

```text
C0_ARTIFACT_MISMATCH bin row=0 frame=0 bin=0
```

The frozen row is:

```text
real=193725 imag=0 mag2=37529375625
```

## Root cause

The original expression squared two signed `T_CAN_W=28` operands directly:

```systemverilog
$unsigned($signed(in_re_i) * $signed(in_re_i))
```

The multiply itself was 28 bits wide. Assignment to a 56-bit destination
zero-extended an already-truncated result. For the failing DC row:

```text
full value       193725^2 = 37529375625 = 0x8bcecd389
truncated value                         = 0x0cecd389
```

v70b sign-extends one operand to `SQUARE_W=2*T_CAN_W` before multiplication.
The multiply result is therefore full width before conversion to unsigned
magnitude.

The independent scoreboard recomputation uses the same explicit-width rule.
Mismatch diagnostics now print every actual and expected bin field.

## Directed regression

`sim/tb/tb_trecap_mag2_width.sv` checks:

- the exact native failure row;
- a non-self-conjugate signed real/imaginary row;
- both 28-bit signed extrema in one magnitude;
- the maximum legal magnitude-squared value `2^55`;
- a value below `THR2`;
- a value exactly equal to `THR2`.

The required sentinel is:

```text
C0_MAG2_WIDTH_PASS cases=6 product_width=56
```

The testbench is compiled from `sim/filelists/c0_mag2_width.f`. It is part of
the verification repository, not the synthesizable `rtl/` filelist or FPGA
bitstream.

## Evidence boundary

Static expression-width inspection and local lowered RTL execution can prove
the repaired multiplier width and directed values. Final C0 evidence still
requires the complete native Intel ModelSim run and exact artifact post-check:

```text
C0_ARTIFACT_RTL_PASS
C0_ARTIFACT_POSTCHECK_PASS
C0_GOLDEN_SUITE_PASS vectors=1 revision=v70b
```
