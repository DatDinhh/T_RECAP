# Baseline PDF page 064

Historical Part II, DDR and UDP telemetry. Printed page 51. [Original PDF page](../../specs/t_recap_phase2_integrated_spec.pdf#page=64).

[Previous](page-063.md) | [Index](../README.md) | [Next](page-065.md)

[Edit Markdown and LaTeX source](../source/baseline/page-064.md). Equations are rendered locally as SVG.

## 21 PC Command Contract

### 21.1 Command Header

Commands sent from PC to HPS use a compact UDP command format. The HPS validates the command, checks the source, and translates accepted commands into CSR writes. All PC command fields are little-endian and packed with no implicit C padding. The Revision G command packet length is exactly 28 bytes. The command magic is parsed as a little-endian `uint32_t` numeric constant, not as four literal transmitted ASCII characters.

**Table 23. PC-to-HPS command packet.**

| Offset | Field | Type | Meaning |
| --- | --- | --- | --- |
| 0 | magic | `uint32_t` | Numeric little-endian constant 0x54524343. TRCC is a human mnemonic only. |
| 4 | version | `uint16_t` | Command version. Revision G uses 1. |
| 6 | `cmd_type` | `uint16_t` | Command type from Table 24. |
| 8 | seq | `uint32_t` | PC command sequence number. |
| 12 | arg0 | `uint32_t` | Command-specific argument. |
| 16 | arg1 | `uint32_t` | Command-specific argument. |
| 20 | arg2 | `uint32_t` | Command-specific argument. |
| 24 | crc32 | `uint32_t` | Revision G disables command CRC. This field shall be zero. HPS shall not compute CRC and shall reject nonzero values. |


### 21.2 Command Types and Valid Ranges

**Table 24. PC command types and valid argument ranges.**

| Code | Name | Action and range |
| --- | --- | --- |
| 0x0001 | `SET_THR2` | arg0=low 32 bits, arg1=high bits. Upper bits beyond bit 55 shall be zero. Valid ![0 &#92;le&#92;mathrm{THR2}<2^{56}](../math/baseline-page-064-001.svg) . |
| 0x0002 | `CLEAR_METRICS` | HPS pulses metrics clear through `CONTROL.clear_metrics`. Arguments shall be zero. |
| 0x0003 | `SET_SOURCE_MODE` | arg0∈ {0, 1, 2, 3}. Source-mode change rule applies. |
| 0x0004 | `SET_PACKET_ENABLE` | arg0 uses bits from Table 10. Reserved bits shall be zero. `PEAKS_EN` and `DEBUG_EN` shall also be zero in Revision G unless a later exact extension is defined. |
| 0x0005 | `SET_WAVE_DECIM` | 1 ≤ arg0 ≤ 65535. A power of two is recommended but not required. |
| 0x0006 | `SET_SPEC_SHIFT` | For baseline Wmag2 = 56, 0 ≤ arg0 ≤ 55. |
| 0x0007 | PING | HPS returns a STATUS packet. No separate ACK packet exists in Revision G. If HPS synthesizes the response instead of forwarding a cached FPGA-originated STATUS, it shall set `status_diagnostic`. Arguments shall be ignored. |
