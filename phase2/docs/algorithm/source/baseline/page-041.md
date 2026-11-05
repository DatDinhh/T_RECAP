# Baseline PDF page 041

Historical Part II, DDR and UDP telemetry. Printed page 28. [Original PDF page](../../../specs/t_recap_phase2_integrated_spec.pdf#page=41).

[Previous](../../baseline/page-040.md) | [Index](../../README.md) | [Next](../../baseline/page-042.md)

## 16 CSR Register Contract

### 16.1 Register Access Rules

Control and status registers are memory-mapped through an HPS-to-FPGA bridge. All CSR words are 32-bit aligned, 32-bit accessible, and little-endian. Multiword values are transferred through explicit snapshot or commit mechanisms. Independent low/high half updates are not a valid transfer for live pointers or thresholds. A register write from HPS shall not directly change active core behavior in the middle of a frame unless the register is explicitly defined as asynchronous. Threshold and source-mode updates shall use shadow/commit mechanisms and shall become active only at a safe boundary.

### 16.2 CSR Map

**Table 8. Normative CSR map for Level-3 Ethernet/HPS telemetry, Revision G.**

| Offset | Name | Access | Meaning |
| --- | --- | --- | --- |
| 0x000 | ID | R | Numeric little-endian CSR value 0x54524350. TRCP is only the human mnemonic. Software shall compare the numeric value read from the CSR, not raw ASCII bytes. |
| 0x004 | VERSION | R | Transport specification version packed as VERSION[31:16]=major and VERSION[15:0]=minor. Revision G shall report 0x0001_0007. The minor value 7 is intentional and shall be used by HPS software for compatibility checks. |
| 0x008 | CONTROL | R/W | Level and write-one-pulse control bits. Bit definitions are frozen in Table 9. |
| 0x00C | STATUS | R | Live transport state bits. Bit definitions are frozen in Table 11. |
| 0x010 | `THR2_LO` | W | Shadow threshold bits [31 : 0]. |
| 0x014 | `THR2_HI` | W | Shadow threshold bits [55 : 32]. Upper bits beyond bit 55 shall be zero. |
| 0x018 | `THR2_COMMIT` | W1P | Writing 1 requests active threshold update at the next frame boundary. |
| 0x01C | `PACKET_ENABLE` | R/W | Packet-enable bitmask. Bit definitions are frozen in Table 10. |
| 0x020 | `WAVE_DECIM` | R/W | Waveform sample decimation factor. Valid range is 1 ≤ `WAVE_DECIM` ≤ 65535. The active value shall be reported as WAVE.stride. |
| 0x024 | `SPEC_MODE` | R/W | 0 disables spectrum, 1 selects SPEC64, 2 selects SPEC129. Other values are illegal. |
| 0x028 | `SPEC_SHIFT` | R/W | Right shift before clamping mag2 to `uint16_t`. For baseline Wmag2 = 56, valid range is 0 through 55. |
