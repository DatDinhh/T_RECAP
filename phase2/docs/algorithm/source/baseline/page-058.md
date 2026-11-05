# Baseline PDF page 058

Historical Part II, DDR and UDP telemetry. Printed page 45. [Original PDF page](../../../specs/t_recap_phase2_integrated_spec.pdf#page=58).

[Previous](../../baseline/page-057.md) | [Index](../../README.md) | [Next](../../baseline/page-059.md)

**Table 20. Exact SPEC64 payload layout.**

| Offset | Field | Type | Meaning |
| --- | --- | --- | --- |
| 0 | `frame_idx` | `uint64_t` | STFT frame index. Must equal header timestamp. |
| 8 | nbin | `uint16_t` | Shall equal 64. |
| 10 | `spec_shift` | `uint16_t` | Right shift used before `uint16_t` clamp. |
| 12 | spec64[0] | `uint16_t` | Compressed bucket magnitude. |
| 12 + 2b | spec64[b] | `uint16_t` | Compressed magnitude for bucket b. |
| 140 | `suppressed_count`[0] | `uint8_t` | Number of final masked bins in bucket 0. |
| 140 + b | `suppressed_count`[b] | `uint8_t` | Number of final masked bins in bucket b. |
| 204 | `eligible_count`[0] | `uint8_t` | Number of eligible bins in bucket 0. |
| 204 + b | `eligible_count`[b] | `uint8_t` | Number of eligible bins in bucket b. |


For L = 256, `payload_bytes`=268. The PC may display bucket suppression as the ratio

$$
\frac{\mathrm{suppressed\_count}[b]}{\mathrm{eligible\_count}[b]}
$$

when `eligible_count`[b] is nonzero.

### 19.5 METRICS Payload

Revision G baseline METRICS packets shall carry exactly one metrics class per packet. Exactly one of `per_frame_metrics` and `aggregate_metrics` shall be set. Setting both bits or neither bit is illegal in Revision G unless a later revision defines a larger payload with separate per-frame and aggregate sections. For Revision G, `payload_scaled` shall be zero for METRICS packets. Scaled display metrics are reserved for a later revision unless explicit scale metadata is added to the payload. Therefore, the fields in Table 21 are low 64-bit integer words of the selected core counters unless stated otherwise.
