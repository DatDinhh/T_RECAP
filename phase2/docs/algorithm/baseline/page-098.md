# Baseline PDF page 098

Historical Part III, repository architecture. Printed page 85. [Original PDF page](../../specs/t_recap_phase2_integrated_spec.pdf#page=98).

[Previous](page-097.md) | [Index](../README.md) | [Next](page-099.md)

## 49 Implementation Milestones

**Table 44. Implementation milestones for the core repository.**

| Milestone | Task | Exit condition |
| --- | --- | --- |
| R0 | Restructure repository and quarantine legacy code. | Phase 2 root contains no active Phase 1 build files. |
| R1 | Add generated schema flow. | `gen_headers.py` produces SV/C/Python headers from one schema source. |
| R2 | Generate coefficients and frozen vectors. | Coefficient and vector manifests contain hashes and row counts. |
| R3 | Implement golden model skeleton. | Golden tool emits config.json, `x_in.memh`, and placeholder output artifacts. |
| R4 | Implement source and core RTL skeleton. | Core-only RTL compiles without telemetry/HPS/platform dependencies. |
| R5 | Implement FFT/IFFT and STFT/WOLA top modules. | Core exposes sample input, output, frame stats, and metric taps. |
| R6 | Implement telemetry packetizers. | Packetizers emit formatted records into packet FIFO. No DDR writer is inside telemetry. |
| R7 | Implement HPS bridge RTL. | CSR bank, pointer control, record builder, and DDR ring writer are integrated. |
| R8 | Add DE1-SoC platform integration. | Platform Designer wrapper, constraints, and address map are present. |
| R9 | Implement HPS UDP streamer. | HPS code consumes generated CSR/packet headers and runtime manifest. |
| R10 | Implement PC dashboard. | Dashboard consumes generated packet constants and displays required live panels. |
| R11 | Add LINE-IN audio wrapper. | Audio adapter maps controlled LINE-IN samples into signed core scale. |


## 50 Implementation Cuts

### 50.1 Core Implementation Cut C0

Cut C0 is the first required implementation boundary. It exists to prevent the team from starting telemetry, Ethernet, HPS, dashboard, and audio integration before the core skeleton compiles.
