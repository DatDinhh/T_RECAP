# Baseline PDF page 079

Historical Part III, repository architecture. Printed page 66. [Original PDF page](../../specs/t_recap_phase2_integrated_spec.pdf#page=79).

[Previous](page-078.md) | [Index](../README.md) | [Next](page-080.md)

[Edit Markdown and LaTeX source](../source/baseline/page-079.md). Equations are rendered locally as SVG.

**Table 28. Repository directory responsibilities, continued.**

| Directory | Responsibility |
| --- | --- |
| rtl/platform/de1soc/ | Board wrappers, clock/reset, audio codec wrapper, ADC wrapper, Platform Designer wrapper. |
| rtl/top/ | Integration top modules for core-only, core+telemetry, and full DE1-SoC builds. |
| sw/golden/ | Coefficient generation, vector generation, golden model, artifact writer/checker, quality-bound generation. |
| sw/hps/ | HPS UDP streamer, CSR access, ring reader, command server, status patcher, runtime config. |
| `sw/pc_dashboard/` | UDP packet parser, plotting dashboard, command client, and PC configuration. |
| artifacts/ | Frozen coefficients, vectors, outputs, manifests, and captured telemetry logs. |
| constraints/de1soc/ | QSF, SDC, and pin assignment files for DE1-SoC. |
| platform/de1soc/ | Platform Designer/Qsys files, address maps, SOPCINFO location notes, and generated-system notes. |
| legacy/ | Quarantined Phase 1 code and deprecated Phase 2 drafts. Nothing here is part of the Phase 2 build. |
| runs/ | Generated local build/run outputs. Not source-controlled by default. |


## 35 Generated Shared Contract Flow

### 35.1 Purpose

Manual duplication of constants across SystemVerilog, C, and Python is not acceptable for this project. The following items are too easy to mismatch:

- CSR offsets such as `PACKET_FIFO_DROP_COUNT`.

- transport version fields such as major 1, minor 7.

- STATUS payload size 72.

- packet type IDs for WAVE, SPEC64, SPEC129, METRICS, STATUS, and WRAP.

- packet-enable bit positions and `SPEC_MODE` values.

- overflow-flag bit positions.

- core constants such as N = 12, L = 256, H = 128, F = 15, G = 128, and D = 384.

Therefore, the repository shall use one schema source under spec/generated/ and generate implementation headers from that source.

### 35.2 Schema files
