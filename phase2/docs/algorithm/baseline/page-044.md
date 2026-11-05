# Baseline PDF page 044

Historical Part II, DDR and UDP telemetry. Printed page 31. [Original PDF page](../../specs/t_recap_phase2_integrated_spec.pdf#page=44).

[Previous](page-043.md) | [Index](../README.md) | [Next](page-045.md)

[Edit Markdown and LaTeX source](../source/baseline/page-044.md). Equations are rendered locally as SVG.

**Table 10. PACKET_ENABLE bit definitions.**

| Bit | Name | Meaning |
| --- | --- | --- |
| 0 | `WAVE_EN` | Enable waveform packets. |
| 1 | `SPEC_EN` | Enable spectrum packets. The spectrum format is selected only by `SPEC_MODE`. |
| 2 | `METRICS_EN` | Enable metrics packets. |
| 3 | `STATUS_EN` | Enable status packets. |
| 4 | `PEAKS_EN` | Reserved-disabled in Revision G baseline. Shall be zero unless an implementation-specific extension freezes an exact PEAKS payload layout and size limit. |
| 5 | `DEBUG_EN` | Reserved-disabled in Revision G baseline. Shall be zero unless an implementation-specific extension freezes an exact DEBUG payload layout and size limit. |
| 31:6 | reserved | Shall be zero. Commands setting reserved or reserved-disabled bits shall be rejected in the Revision G baseline. |


In the Revision G baseline, `PEAKS_EN` and `DEBUG_EN` are treated as reserved-disabled features. Commands setting either bit shall be rejected unless an implementation-specific extension explicitly defines exact PEAKS/DEBUG payload layouts, maximum sizes, and PC parser behavior.

### 16.5 Spectrum Packet Selection Rule

`SPEC_MODE` is the authoritative spectrum-format selector. `PACKET_ENABLE.SPEC_EN` is only the packet gate. Spectrum telemetry shall be generated only under the following conditions:

- `SPEC_EN`=0: no spectrum packet shall be generated, regardless of `SPEC_MODE`.

- `SPEC_EN`=1 and `SPEC_MODE`=0: no spectrum packet shall be generated.

- `SPEC_EN`=1 and `SPEC_MODE`=1: generate SPEC64 packets.

- `SPEC_EN`=1 and `SPEC_MODE`=2: generate SPEC129 packets. Values of `SPEC_MODE` other than 0, 1, or 2 are illegal and shall be rejected by command/config validation. This rule intentionally avoids separate `SPEC64_EN` and `SPEC129_EN` bits. There is only one spectrum enable and one format selector.
