# Baseline PDF page 053

Historical Part II, DDR and UDP telemetry. Printed page 40. [Original PDF page](../../../specs/t_recap_phase2_integrated_spec.pdf#page=53).

[Previous](../../baseline/page-052.md) | [Index](../../README.md) | [Next](../../baseline/page-054.md)

### 18.3 Timestamp Semantics

The header timestamp field shall be interpreted by packet type:

- WAVE: sample index of the first represented output sample. It shall equal `sample_base` in the payload.

- SPEC64 and SPEC129: STFT frame index associated with the spectrum payload.

- METRICS: frame index for per-frame metrics, or the latest frame index included in the aggregate metrics.

- STATUS: current core sample count when the packet is FPGA-originated or HPS-patched from an FPGA-originated record. For HPS-synthesized diagnostic STATUS packets, the timestamp is the latest coherent core sample count known to HPS and the `status_diagnostic` flag shall be set.

- WRAP: ignored and shall be zero.

### 18.4 Packet Types

**Table 16. Telemetry packet types.**

| Code | Name | Purpose |
| --- | --- | --- |
| 0x0001 | WAVE | Time-domain delayed input, reconstructed output, and error. |
| 0x0002 | SPEC64 | 64-bucket compressed spectrum with bucket suppression counts. |
| 0x0003 | SPEC129 | 129 unique-bin compressed spectrum for baseline L = 256. |
| 0x0004 | METRICS | Frame or aggregate metrics. |
| 0x0005 | STATUS | Source mode, sample rate, active threshold, overflow flags, and drop counters. |
| 0x0006 | PEAKS | Reserved optional top-K peak-bin summary. Reserved-disabled in Revision G baseline. |
| 0x007E | DEBUG | Reserved optional low-rate debug record. Reserved-disabled in Revision G baseline. |
| 0x007F | WRAP | Ring wrap marker. Payload length is zero. |


### 18.5 Packet Validation Rules

Before forwarding or consuming a record, the HPS shall validate:

1. magic == 0x54524350.

2. version is supported.

3. `header_bytes` == 32.

4. `packet_type` is known.

5. reserved and packet-illegal flag bits are zero. `status_diagnostic` may be set only for HPSsynthesized diagnostic STATUS.
