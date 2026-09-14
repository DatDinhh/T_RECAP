# Magnitude/mask accumulation timing

The magnitude/mask stage retains one registered output entry. On each accepted
canonical bin, its existing output fields and per-frame statistics advance on the
same clock. Backpressure, frame completion, clear priority, threshold comparison,
protection rules, and numerical widths are unchanged.

We calculate the two 65-bit candidate sums from the current total/kept counters
and the weighted magnitude before choosing whether the bin contributes. This
lets each carry chain run in parallel with the magnitude/threshold comparison.
The eligibility and mask decision select the sum or the unchanged counter after
the addition; they do not gate a carry-chain operand.

For a 64-bit counter `Q`, 65-bit weighted addend `W`, and contribution decision
`C`, the old and new selected result are exactly:

```text
old = zero_extend_65(Q) + (C ? W : 0)        [modulo 2^65]
new = C ? (zero_extend_65(Q) + W) : zero_extend_65(Q)
overflow = C && (candidate_sum[64] || W[64])
```

Both forms select the same low 64 bits and the same overflow condition for every
counter/addend value. The addend's high bit remains part of overflow detection
because the candidate sum itself wraps at 65 bits. Total contribution uses
`eligible`; kept contribution uses `eligible && !mask`. First-bin initialization
continues to use the selected addend directly, and existing accepted-beat logic
retains all reset, clear, and sticky-flag precedence. No pipeline stage is added.

This factoring addresses the serial path observed in the native11 fitted report:
square/product combination, magnitude sum, threshold comparison, selected kept
addend, 65-bit accumulation, and truncation flag. That path had 20.869 ns data
delay and -1.761 ns setup slack at the slow 85 C corner. These measurements
identify the previous implementation's limiting path; timing improvement requires
a subsequent fit. This change makes no extra input-range assumption. The full-width branch below
removes an unreachable magnitude-overflow condition while retaining the generic
narrow-width saturation path and all accumulator overflow handling.

## Exact signed-input width

For any signed `DATA_W`-bit input, including its most-negative value:

```text
abs(x), abs(y) <= 2^(DATA_W - 1)
x*x, y*y       <= 2^(2*DATA_W - 2)
x*x + y*y      <= 2^(2*DATA_W - 1)
```

Each square therefore needs `2*DATA_W - 1` unsigned bits, and their sum needs
`2*DATA_W` unsigned bits. At the baseline signed 28-bit input width, the largest
possible magnitude is `2^55`, attained when both inputs equal `-2^27`; it fits the
unsigned 56-bit magnitude format exactly. This is a bound for every representable
input bit pattern, independent of FFT scaling or signal amplitude.

When `MAG2_W >= 2*DATA_W`, the implementation adds the proven square widths into
a `2*DATA_W`-bit sum and zero-extends it to the output width. Magnitude-width
overflow is constant zero in this branch, eliminating the otherwise unreachable
extra carry and saturation selection. For narrower `MAG2_W`, the existing full
sum, overflow detection, and saturation remain. The 65-bit weighted additions,
64-bit accumulated results, and their overflow flags remain intact in both
branches; the per-bin bound does not authorize removing aggregate carries.

Implementation: [trecap_mag2_mask.sv](../../rtl/core/trecap_mag2_mask.sv).
