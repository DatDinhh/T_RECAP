# Baseline PDF page 054

Historical Part II, DDR and UDP telemetry. Printed page 41. [Original PDF page](../../specs/t_recap_phase2_integrated_spec.pdf#page=54).

[Previous](page-053.md) | [Index](../README.md) | [Next](page-055.md)

6. `payload_bytes` satisfies the packet-specific rule in Table 17.

7. for normal records, Lrec = align64 (32 + `payload_bytes`) is valid and does not exceed the ring size minus the guard. For WRAP, the effective record length is R - off(Rd ), not align64 (32).

8. normal records do not cross the ring end. Only WRAP records may consume the physical tail region, and a WRAP record shall consume the entire remaining tail.

9. `header_crc` == 0 in Revision G. Revision G baseline malformed-record policy is disable-and-reset, not byte scanning. On a malformed DDR record, the HPS shall increment `malformed_record_count`, disable the telemetry writer, commit the current consumer pointer, and require telemetry soft reset plus ring reconfiguration before streaming resumes. Byte-scanning resynchronization through the ring is not part of the Revision G baseline. Malformed records shall not cause an out-of-bounds DDR read.

### 18.6 Maximum Payload Rules

The HPS shall validate packet-specific payload sizes using Table 17. The Revision G UDP nofragmentation rule requires:

$$
32+\mathrm{payload\_bytes}\le P_{\mathrm{udp,max}}=1200.\tag{18.1}
$$

Records that violate the packet-specific rule or the global UDP limit are malformed or oversized as indicated in the table.

**Table 17. Maximum and exact payload-size rules by packet type.**

| Packet | Payload-size rule | Notes |
| --- | --- | --- |
| WAVE | `payload_bytes` = 16 + 6 nsamp, with 1 ≤ nsamp ≤ 192 | Recommended first value is 128 samples. Hard maximum follows 32+16+6 nsamp ≤ 1200. |
| SPEC129 | exactly 287 | Baseline L = 256: 129 uint16 bins plus 17 mask bytes. |
| SPEC64 | exactly 268 | 64 uint16 buckets plus 64 suppressed counts plus 64 eligible counts. |
| METRICS | exactly 56 | One metrics class per packet in Revision G. |
| STATUS | exactly 72 | HPS may patch a local UDP transmit copy. HPS-synthesized diagnostic STATUS packets shall set `status_diagnostic`. |
| WRAP | exactly 0 | Not forwarded to PC. Payload length is zero, but the DDR effective record length is the full physical tail R - o. |
| PEAKS, DEBUG | reserved-disabled in baseline | Commands setting reserved-disabled PEAKS/DEBUG enable bits shall be rejected unless a later extension defines exact payload layouts and size limits. |
