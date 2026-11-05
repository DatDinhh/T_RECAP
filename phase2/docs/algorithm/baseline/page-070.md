# Baseline PDF page 070

Historical Part II, DDR and UDP telemetry. Printed page 57. [Original PDF page](../../specs/t_recap_phase2_integrated_spec.pdf#page=70).

[Previous](page-069.md) | [Index](../README.md) | [Next](page-071.md)

`WRAP.payload_bytes`=0. The PC parser shall reject STATUS records with any other payload size unless a later compatible revision explicitly defines a different layout.

AC13. Spectrum packet generation uses `PACKET_ENABLE.SPEC_EN` plus authoritative `SPEC_MODE`. `PACKET_ENABLE` shall not contain separate `SPEC64_EN` and `SPEC129_EN` controls in Revision G.

AC14. METRICS packets set exactly one of `per_frame_metrics` and `aggregate_metrics`, and set `payload_scaled`=0 in Revision G.

AC15. The HPS may patch local UDP transmit copies of FPGA-originated STATUS packets. HPSsynthesized diagnostic STATUS packets shall set `status_diagnostic`, shall set seq=0, shall not be written into the DDR ring, and shall not participate in sequence-gap detection. The HPS does not modify committed DDR ring contents, WAVE, SPEC64, SPEC129, or METRICS payloads.

AC16. UDP telemetry is sent as one record per datagram with no Revision G protocol fragmentation. Oversized records are dropped and counted.

AC17. HPS UDP sends are nonblocking or bounded-timeout. Send failure increments a counter and does not prevent consumer-pointer advancement.

AC18. Malformed DDR records use the Revision G disable-and-reset policy. Byte-scanning ring resynchronization is not accepted in baseline.

AC19. Sticky flags are cleared only through `CLEAR_STICKY_FLAGS` write-one-to-clear semantics. CONTROL[3] is reserved.

AC20. PC command packets are accepted only from the configured trusted PC or validated direct-link peer.

AC21. Commands with out-of-range arguments are rejected and counted, including $\mathrm{THR2}\ge2^{56}$ , `WAVE_DECIM`=0, illegal `SOURCE_MODE`, reserved or reserved-disabled packet-enable bits including `PEAKS_EN/DEBUG_EN`, or illegal `SPEC_SHIFT`.

AC22. `SET_THR2` changes the active threshold only through the shadow/commit frame-boundary rule.

AC23. `SET_SOURCE_MODE` obeys the source-mode change rule and does not silently mix metrics from different sources.

AC24. PC dashboard detects telemetry sequence gaps using modulo-$2^{32}$ arithmetic and reports packet loss without crashing. Diagnostic STATUS packets marked with `status_diagnostic`=1 are excluded from this check.

AC25. PING returns a STATUS packet only. No undefined ACK packet is used in Revision G.

AC26. Aggregate METRICS low-32-bit eligible-bin counters are interpreted modulo-$2^{32}$ , low-64-bit counters are interpreted modulo-$2^{64}$ , and `payload_truncated` is set when known omitted high bits are nonzero.

AC27. Real WAVE, SPEC64 or SPEC129, METRICS, and STATUS packets can be plotted live.

AC28. BRAM replay and golden artifacts remain the correctness signoff path. Ethernet telemetry is not used as a substitute for bit-accurate artifact comparison.
