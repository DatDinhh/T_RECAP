# Baseline PDF page 063

Historical Part II, DDR and UDP telemetry. Printed page 50. [Original PDF page](../../specs/t_recap_phase2_integrated_spec.pdf#page=63).

[Previous](page-062.md) | [Index](../README.md) | [Next](page-064.md)

```text
37:       commit Rd through RING_RD_COMMIT
38:    end while
39:    poll command UDP socket and process accepted commands
40: end while
```

### 20.5 Runtime Packet Validation Checklist

The HPS shall validate at least the following before forwarding a record:

- correct magic, supported version, and `header_bytes`=32.

- known packet type.

- reserved and packet-illegal flag bits zero. `status_diagnostic` may be set only for HPSsynthesized diagnostic STATUS.

- for METRICS, exactly one of `aggregate_metrics` and `per_frame_metrics` is set and `payload_scaled`=0.

- `payload_bytes` exactly matches the required size for fixed-size payloads, or is within bounds for variable-size WAVE.

- WAVE.channels=3, WAVE.nsamp≥ 1, WAVE.stride≥ 1, and WAVE.reserved=0 when packet type is WAVE.

- SPEC129.nbin=129. SPEC64.nbin=64.

- unused mask bits in SPEC129 are zero.

- normal records do not cross the ring boundary. WRAP records consume exactly the remaining physical tail and are advanced using R - off(Rd ).

- `header_crc`=0 in Revision G.

### 20.6 Ethernet Port Assignments

A recommended default is:

$$
\text{telemetry UDP port}=5005.\tag{20.2}
$$

$$
\text{command UDP port}=5006.\tag{20.3}
$$

The PC IP address should be configured statically for a direct board-to-PC link. For example:

$$
\text{PC}:192.168.10.1.\tag{20.4}
$$

$$
\text{DE1-SoC HPS}:192.168.10.2.\tag{20.5}
$$
