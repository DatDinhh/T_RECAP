# Baseline PDF page 072

Historical Part II, DDR and UDP telemetry. Printed page 59. [Original PDF page](../../../specs/t_recap_phase2_integrated_spec.pdf#page=72).

[Previous](../../baseline/page-071.md) | [Index](../../README.md) | [Next](../../baseline/page-073.md)

## 29 Development Milestones

**Table 27. Recommended Level-3 development milestones.**

| Milestone | Name | Pass condition |
| --- | --- | --- |
| M0 | HPS Ethernet bring-up | PC can ping HPS. HPS sends dummy UDP counter to PC. |
| M1 | CSR bridge | HPS reads FPGA ID. HPS writes a harmless control register. |
| M2 | DDR ring dummy writer | FPGA writes dummy STATUS records into DDR. HPS forwards them over UDP. |
| M3 | Waveform telemetry | PC plots x[n - D], y[n], and e[n]. |
| M4 | Metrics telemetry | PC plots eligible suppression ratio and kept-energy ratio. |
| M5 | Spectrum telemetry | PC plots SPEC129 or SPEC64 spectrogram. |
| M6 | PC-to-FPGA commands | PC changes THR2. FPGA applies it at frame boundary. |
| M7 | Full live demo | Live audio/ADC source, processed output, Ethernet dashboard, and stable counters. |


## 30 Conclusion

This addendum defines the Level-3 transport architecture for a fully functional T-RECAP Phase 2 DE1-SoC demonstration. The FPGA fabric remains responsible for deterministic real-time signal processing. The HPS provides the Ethernet and DDR bridge needed for high-bandwidth live visualization. The PC receives UDP telemetry and sends control commands, but it is not part of the signal-processing correctness path. Revision G is intentionally strict about ownership, memory ordering, packet records, atomic pointer semantics, CDC rules, command safety, packet validation, separate pre-writer versus DDR-writer drop accounting, and non-stall drop behavior. These details matter because the final demo should be visually rich without weakening the core verification story. A correct implementation of this addendum will allow real-time waveform plots, error plots, spectrograms, live metrics, and threshold control while preserving the Phase 2 core contract and BRAM replay signoff.
