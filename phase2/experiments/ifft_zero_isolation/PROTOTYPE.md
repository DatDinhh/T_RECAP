# IFFT zero-operand isolation candidate

This staging overlay contains four RTL replacements. It does not change the
canonical baseline or the coefficient/input/expected-output artifacts.

## Interface and ownership

The measurement hierarchy is `trecap_core_bram_replay_top` ->
`trecap_core_top` -> `trecap_ifft256` -> `trecap_fft_stage`.
`trecap_core_only_top` is not on this instantiated path.

- The two core wrappers add `SUPPORT_IFFT_ZERO_ISOLATION`, default `0`, and
  input `ifft_zero_isolation_i`.
- IFFT and butterfly add `SUPPORT_ZERO_B_ISOLATION`, default `0`, and input
  `zero_b_isolation_i`.
- The IFFT captures the runtime level at the first accepted word of each IFFT
  frame, holding it through load, compute and output stalls. This is IFFT
  admission, not the earlier analysis-frame/threshold admission event.
- Compile-time support `0` ignores the runtime input and removes the added
  isolation datapath. Existing FFT users retain that default. The shared
  butterfly supports isolation only in registered mode.

Use support `1` with runtime `0` versus runtime `1` for a same-image comparison.
Both cases include the added circuitry; runtime `0` is the original numerical
operation schedule in the candidate image, not an area-identical old bitstream.

## Datapath

The registered butterfly detects `b_re == 0 && b_im == 0`. Four local registers
retain the two b operands and the two twiddle operands from the most recent
accepted nonzero-b transaction, independent of runtime mode. For the current
IFFT widths this is `2*36 + 2*17 = 106` held operand bits. Synchronous reset or
clear writes all held operands to zero, so a first accepted zero transaction
has deterministic multiplier inputs. Product registers keep their original
reset-free inference template.

When enabled and b is zero, muxes at **both inputs of all four multipliers**
select these held values, and the four product-register writes are inhibited.
The accepted transaction latches `zero_product_q`. The next `B_PRODUCT_SUM`
state explicitly writes zero real and imaginary sums when this flag is set.
Held products are never used as the numerical result of a zero transaction.
Nonzero transactions keep the original signed operand/product widths.

These are real source-level multiplier-input isolation muxes, not only a
zero-result mux or a disabled output register. Settled multiplier-input nets
are exposed internally as `gen_registered_output.mul_b_re`, `mul_b_im`,
`mul_tw_re`, and `mul_tw_im` for passive checking. Between transactions,
invalid input changes are not globally isolated; in the IFFT the RAM and ROM
already hold their data between scheduled reads. A runtime mode change or a
nonzero transaction can change the input nets. RTL stability does not prove
absence of physical mux glitches or guarantee a reduction in board power.

## Exactness and timing

For b=(0,0), every full-width real product is exactly zero for every signed
twiddle bit pattern. Both product sums are zero. The existing rounded shift
maps zero to zero and neither saturation flag is asserted. The original
addition/subtraction, output rounding, saturation reduction and handshake
therefore see exactly the same mathematical values. This argument includes
arbitrary a values and preserves their possible output saturation behavior.

No state, handshake, RAM access, twiddle read, butterfly write, frame load or
output schedule is added or removed. All 1,024 IFFT butterflies still execute
their original seven-clock transactions per frame. Each isolated transaction
inhibits four real multiplier product-register updates; it does not remove an
FFT butterfly, IFFT butterfly, memory transaction, or output sample.

Required validation includes frozen-baseline comparisons against support-off,
runtime-off and runtime-on candidates; first-zero and zero-after-nonzero cases;
signed extrema, saturation, stalls and clear/reset; frame-owned runtime
control; and actual held multiplier inputs plus product registers. Synthesis
must retain useful DSP mapping and meet timing. Electrical benefit must be
measured separately with matched workload, threshold, outputs and image.
