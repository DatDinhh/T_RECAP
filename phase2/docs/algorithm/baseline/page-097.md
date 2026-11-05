# Baseline PDF page 097

Historical Part III, repository architecture. Printed page 84. [Original PDF page](../../specs/t_recap_phase2_integrated_spec.pdf#page=97).

[Previous](page-096.md) | [Index](../README.md) | [Next](page-098.md)

[Edit Markdown and LaTeX source](../source/baseline/page-097.md). Equations are rendered locally as SVG.

Older Phase 2 Algorithm Report drafts are historical only. Do not use D = L for the current DE1-SoC baseline. Use the Integrated Phase 2 Specification Final: Core Revision J + Telemetry Revision G. Current baseline delay: D = L + G = 384 samples.

## 48 Build System Architecture

### 48.1 Required build targets

**Table 43. Core implementation build targets.**

| Target | Purpose |
| --- | --- |
| make check-layout | Verify required folders exist, legacy Phase 1 files are quarantined, and no forbidden root files are present. |
| make gen-headers | Generate SV, C, and Python constants from spec/generated/. |
| make check-generated | Regenerate headers and fail if outputs differ from checked-in generated files. |
| make rtl-filelist | Generate compile/synthesis filelists from repository layout. |
| make lint-basic | Run syntax/style checks only. This is build hygiene, not verification. |
| make compile-core | Compile core packages, interfaces, source adapters, core, and FFT/IFFT modules or wrappers using `filelists/rtl_core_plus_fft.f` for Cut C0. |
| make compile-telemetry | Compile telemetry packetizers and packet FIFO only. |
| make compile-hps-bridge | Compile CSR bank, pointer control, record builder, and DDR ring writer only. |
| make coeffs | Generate coefficient memh files and coefficient manifest. |
| make vectors | Generate or validate frozen input vectors. |
| make golden | Run the golden model and emit expected artifacts. |
| make check-artifacts | Check memh line counts, hashes, CSV rows, and JSON schema. |
| make quartus-core-smoke | Build a reduced core-only Quartus project if available. |
| make quartus-de1soc | Build the full DE1-SoC Quartus project. |
| make hps-build | Build the HPS UDP streamer. |
| make dashboard-import | Import Python dashboard/parser modules and verify generated constants load. |
| make clean-runs | Remove generated run outputs. |


The compile-only targets above are not verification architecture. They are implementation smoke checks. They do not require scoreboards, monitors, assertions, or regression infrastructure. Verification-specific targets such as full regression, scoreboards, and coverage shall be defined in the later verification architecture document.
