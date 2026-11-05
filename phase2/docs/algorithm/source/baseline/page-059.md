# Baseline PDF page 059

Historical Part II, DDR and UDP telemetry. Printed page 46. [Original PDF page](../../../specs/t_recap_phase2_integrated_spec.pdf#page=59).

[Previous](../../baseline/page-058.md) | [Index](../../README.md) | [Next](../../baseline/page-060.md)

**Table 21. Baseline METRICS payload layout.**

| Offset | Field | Type | Meaning |
| --- | --- | --- | --- |
| 0 | `frame_idx` | `uint64_t` | Frame index associated with the metrics. |
| 8 | `eligible_unique_bins` | `uint32_t` | Eligible unique-bin denominator for the selected metrics class. |
| 12 | `eligible_suppressed_bins` | `uint32_t` | Eligible suppressed-bin count for the selected metrics class. |
| 16 | `eligible_kept_mag2_lo` | `uint64_t` | Low 64 bits of the selected counter. |
| 24 | `eligible_total_mag2_lo` | `uint64_t` | Low 64 bits of the selected counter. |
| 32 | `sum_abs_err_lo` | `uint64_t` | Low 64 bits of the selected counter. |
| 40 | `sum_sq_err_lo` | `uint64_t` | Low 64 bits of the selected counter. |
| 48 | `max_abs_err` | `uint32_t` | Maximum absolute error in sample units. |
| 52 | `overflow_flags` | `uint32_t` | Sticky overflow/status flags. |


For aggregate METRICS, `eligible_unique_bins` and `eligible_suppressed_bins` are low-32-bit modulo-$2^{32}$ display counters, and the low-64-bit fields are modulo-$2^{64}$ display counters. Exact signoff counters remain in the core artifact files, not live Ethernet telemetry. If the implementation can determine that any omitted high bits are nonzero, it shall set the common `payload_truncated` flag. Revision G keeps `payload_scaled`=0 for METRICS. Scaled display metrics require a later revision with explicit scale metadata.

### 19.6 STATUS Ownership and HPS Patch Rule

The baseline FPGA telemetry formatter may generate a STATUS record containing FPGA-owned fields such as sample count, frame count, source mode, sample rate, packet-enable mask, DMA drop count, overflow flags, and active THR2. Some status fields are HPS-owned because only the HPS UDP streamer can observe UDP send failures, malformed DDR records, oversized records, command rejects, and PC-visible sequence gaps. Therefore, Revision G permits two status paths. First, the HPS may patch the local UDP transmit copy of an FPGA-originated STATUS record. This patched packet remains part of the normal telemetry sequence stream. Second, the HPS may synthesize a diagnostic STATUS packet when telemetry is disabled or in response to PING. Such a packet shall set the `status_diagnostic` header flag, shall set the header seq field to zero, shall not be written back into the DDR ring, and shall not participate in PC-visible sequence-gap detection. The HPS shall not modify WAVE, SPEC64, SPEC129, or METRICS payloads. A patched STATUS packet shall preserve FPGA-owned fields and insert HPS-owned counters in the locations defined by Table 22.
