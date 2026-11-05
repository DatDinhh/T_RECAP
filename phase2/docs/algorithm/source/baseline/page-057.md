# Baseline PDF page 057

Historical Part II, DDR and UDP telemetry. Printed page 44. [Original PDF page](../../../specs/t_recap_phase2_integrated_spec.pdf#page=57).

[Previous](../../baseline/page-056.md) | [Index](../../README.md) | [Next](../../baseline/page-058.md)

For full-rate waveform telemetry, stride=1. For decimated waveform telemetry, stride shall equal the active `WAVE_DECIM`. Therefore the PC dashboard shall use `sample_base` + i · stride, not `sample_base` + i, for time-axis reconstruction. Thus `payload_bytes`=16 + 6 · nsamp. The waveform scheduler shall choose nsamp so that the DDR record and UDP datagram remain below the configured maximum. The Revision G WAVE payload is valid for the baseline N = 12 sample width. If N is raised above 15, the WAVE.err field width shall be revised or the display-error field shall be explicitly saturated for display.

### 19.3 SPEC129 Payload

For baseline L = 256, unique bins are k = 0, . . . , 128. The SPEC129 payload carries compressed magnitude-squared values and final mask bits.

**Table 19. Exact SPEC129 payload layout.**

| Offset | Field | Type | Meaning |
| --- | --- | --- | --- |
| 0 | `frame_idx` | `uint64_t` | STFT frame index. Must equal header timestamp. |
| 8 | nbin | `uint16_t` | Shall equal 129. |
| 10 | `spec_shift` | `uint16_t` | Right shift used before `uint16_t` clamp. |
| 12 | spec129[0] | `uint16_t` | clip16 (mag2[0] ≫ `spec_shift`). |
| 12 + 2k | spec129[k] | `uint16_t` | Compressed unique-bin magnitude for bin k. |
| 270 | `mask_bits`[0] | `uint8_t` | Packed final post-protection mask bits, LSB-first. |
| 270+j | `mask_bits`[j] | `uint8_t` | Bit b represents bin k = 8j + b. |


Unused bits in the final mask byte shall be zero. For L = 256, `payload_bytes`=287.

### 19.4 SPEC64 Payload

SPEC64 is a lower-bandwidth heatmap format. Bucket b ∈ {0, . . . , 63} covers:

$$
k_{\min}(b)=\left\lfloor\frac{129b}{64}\right\rfloor.\tag{19.2}
$$

$$
k_{\max}(b)=\left\lfloor\frac{129(b+1)}{64}\right\rfloor-1.\tag{19.3}
$$

The display magnitude is:

$$
\mathrm{spec64}[b]=\operatorname{clip}_{16}\left(\max_{k_{\min}(b)\le k\le k_{\max}(b)}(\operatorname{mag2}[k]\gg\mathrm{spec\_shift})\right).\tag{19.4}
$$

Revision G also carries per-bucket suppression counts so that the PC can draw a mask overlay even when SPEC129 is disabled.
