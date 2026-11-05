# Baseline PDF page 056

Historical Part II, DDR and UDP telemetry. Printed page 43. [Original PDF page](../../../specs/t_recap_phase2_integrated_spec.pdf#page=56).

[Previous](../../baseline/page-055.md) | [Index](../../README.md) | [Next](../../baseline/page-057.md)

## 19 Telemetry Payload Formats

All telemetry payload fields are little-endian and packed with no implicit C padding. Each packet type defines exact byte offsets, array order, and unused-bit behavior. Live Ethernet telemetry is not a correctness artifact. Exact signoff remains BRAM replay plus the core artifact contract.

### 19.1 Magnitude Compression Operator

For unsigned integer input z ≥ 0, define the display clamp operator:

$$
\operatorname{clip}_{16}(z)=\min(z,65535).\tag{19.1}
$$

The SPEC64 and SPEC129 payloads shall apply clip16 after the configured unsigned right shift. No signed saturation is used for spectrum display compression.

### 19.2 WAVE Payload

The WAVE payload is interleaved by sample. The three channels are:

{xdel [i], yout [i], e[i]}, e[i] = xdel [i] - yout [i].

For Phase 2, xdel [i] is the input delayed by the core delay D = L + G, not the raw input sample.

**Table 18. Exact WAVE payload layout.**

| Offset | Field | Type | Meaning |
| --- | --- | --- | --- |
| 0 | `sample_base` | `uint64_t` | Sample index of the first represented output sample. Must equal header timestamp. |
| 8 | nsamp | `uint16_t` | Number of interleaved sample triples. Shall satisfy 1 ≤ nsamp ≤ 192. |
| 10 | channels | `uint16_t` | Shall equal 3. |
| 12 | stride | `uint16_t` | Sample-index stride between adjacent represented triples. Shall equal the active `WAVE_DECIM`. |
| 14 | reserved | `uint16_t` | Shall be zero. |
| 16 | sample[0].xdel | `int16_t` | First delayed-input sample. |
| 18 | sample[0].yout | `int16_t` | First output sample. |
| 20 | sample[0].err | `int16_t` | First time-domain error sample. |
| 16 + 6i | sample[i].xdel | `int16_t` | Delayed input for represented sample i. |
| 18 + 6i | sample[i].yout | `int16_t` | Reconstructed output for represented sample i. |
| 20 + 6i | sample[i].err | `int16_t` | Error for represented sample i. |


The represented output sample index for triple i is

`sample_base` + i · stride.
