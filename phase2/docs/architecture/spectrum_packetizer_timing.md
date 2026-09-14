# Spectrum packetizer compression timing

SPEC64 stores the maximum compressed magnitude in each bucket. Compression
remains `clip16(mag2 >> spec_shift)`, with the same first-bin shift clamp and
per-frame shift snapshot. SPEC129 and the first SPEC64 bin still store the
compressed value directly on the original capture edge.

We expose the shifted magnitude's low 16 bits and high-bit overflow separately.
The high-bit reduction and comparison of the low 16 bits with the current bucket
run in parallel. Bucket replacement then follows:

```text
S = unsigned_magnitude >> selected_shift
H = any set bit of S above bit 15
L = S[15:0]
B = current unsigned 16-bit bucket

if H || L > B:
    B_next = H ? 0xffff : L
else:
    B_next = B
```

If `H=0`, this is the original comparison against the exact compressed value.
If `H=1`, the compressed value is `0xffff`, which is at least every possible
bucket value. Writing it unconditionally also preserves an already-saturated
bucket. Thus the next stored value is exactly `max(B, clip16(S))` for every
magnitude, shift, and bucket value. First-bin direct seeding is retained because
its caller clears storage on the same edge and cannot compare against the old
frame's bucket.

For `16 < T_MAG2_W <= TMATH_WIDE_W`, the shift uses the generated magnitude
width; logical shifting before or after zero extension gives the same bits.
Other generated widths retain the original 128-bit helper cast before the
shift, including its truncation for inputs wider than the helper. Both branches
split the same low-16 and high-overflow information. The six-bit selected shift
is always below the helper's 128-bit width, so its out-of-range shift case is
unreachable without changing the existing interface.

The native11 fitted path into SPEC64 bucket 62 traversed shift selection, the
barrel shifter, high-bit reduction, saturation mux, and bucket comparison. It
reported 20.946 ns data delay and -1.546 ns setup slack at the slow 85 C corner.
This factoring removes the serial saturation-mux-to-comparator dependency; a
subsequent fit determines the physical timing result. It adds no pipeline and
changes no collection, drop, reset, payload, or handshake state.

Implementation: [trecap_spec_packetizer.sv](../../rtl/telemetry/trecap_spec_packetizer.sv).
