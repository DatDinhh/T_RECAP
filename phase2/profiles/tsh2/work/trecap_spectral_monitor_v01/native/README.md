# Native spectral monitor

This adds a CPU downstream consumer and matched CPU FFT reference. It does not
change FPGA RTL, reload a board, or claim new physical captures. Qualification
replays five existing 8-second physical capture files from the prior stream8
experiment and checks the new consumer against an independent Python integer
reference.

## Python API

`Native(coeff_dir, max_samples)` allocates buffers and loads frozen coefficients.
Do this outside all timers. One context is not thread safe; close it after use.

- `decode(wire_bytes, threshold, frames, encoding='sparse')`: strict checksum and
  format validation, followed by direct sparse or dense consumption. Returns
  copied `uint64[frames,21]` monitor features.
- `run_pcm(pcm_int32, threshold)`: frozen CPU02 window/FFT/canonicalization,
  magnitude, threshold, and monitor output. It performs no IFFT and emits no
  packet. Input must be preloaded, aligned, contiguous, signed12 values in an
  int32 array. Returns the same copied monitor output.
- `prepare(wire, threshold, frames, encoding='sparse')`: untimed preparation;
  returns `features`, `spectra` (`uint64[frames,129]`), and `wire` containing the
  matched compact dense representation. Omitted bins become zero, never altered
  nonzero values.
- `dense_wire(sparse_wire, threshold, frames)` and
  `decode_spectra(wire, threshold, frames, encoding='sparse')` are convenience
  wrappers around `prepare`.
- `produce(pcm, threshold)`: untimed reference-input preparation. Returns
  `features`, `spectra`, and **sparse** `wire`. The distinction between this wire
  and `prepare`'s dense wire is intentional.
- `consume_dense(spectra)`: trusted-predecoded matrix consumption with uint56
  bounds validation. No matched sparse arithmetic-only API is supplied, so do
  not compare this to packet decode and call the result an arithmetic speedup.

Input file reads and conversion to `bytes` happen before timing. Returned NumPy
arrays and bytes are copies made inside public calls. `decode` and `run_pcm`
return identical shape and copy cost. Context allocations are excluded; input
validation and feature result copies are included. No timers or thread-affinity
changes occur inside this DLL. These APIs describe batched host work, not live
system latency or total FPGA system processing time.

## Monitor output

| Columns | Definition |
|---|---|
| 0 through 15 | Band power sums, band index `floor(16*k/129)` |
| 16 | Total power across bands |
| 17 | Low 64 bits of power-weighted bin sum |
| 18 | Largest one-sided bin magnitude squared |
| 19 | Peak bin index; lower index wins ties; all-zero frame gives UINT64_MAX |
| 20 | High 64 bits of power-weighted bin sum |

Band and total power use weight 1 for DC and Nyquist and 2 for other bins, as
the previous 16-band consumer did. Weighted-bin sum uses those same weights:
`sum(k * weight(k) * magnitude_squared[k])`. The maximum valid uint56 spectrum
fits total power in uint64, but its bin-weighted sum can exceed uint64, hence
the explicit two-word result. Combine as `int(high) * 2**64 + int(low)` before
division. Spectral centroid is undefined for zero total energy. Peak power uses
one-sided magnitude, not the doubled energy contribution. Frames end at
`128 * (frame_index + 1)` input samples; there is no 384-sample spectrum shift.

## Packet fairness and validation

The existing strict TSP1 codec is reused read-only. Both formats use the same
48-byte header, 64-bit FNV checksum, and 8-byte record alignment. Compact dense
has 129 bins at seven bytes each (903 payload bytes), **952 bytes/frame total**.
Sparse entries have a one-byte index plus seven-byte magnitude, so sparse can
be larger at threshold zero. Dense and sparse carry exactly the same thresholded
values. The sparse consumer visits entries directly and does not create a dense
matrix; the dense consumer visits all 129 bins.

`qualification.json` binds sources, DLL, reused arithmetic and codec, coefficient
files, and old capture evidence by SHA256. Five physical-capture replays, four
integer edge cases, and 32 negative admission/packet checks passed. The build
uses MSVC `/O2`, C++20, no LTO, and reports no compiler warnings. CPU thread
group and affinity mask were identical before and after qualification.
