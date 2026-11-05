# Baseline PDF page 078

Historical Part III, repository architecture. Printed page 65. [Original PDF page](../../../specs/t_recap_phase2_integrated_spec.pdf#page=78).

[Previous](../../baseline/page-077.md) | [Index](../../README.md) | [Next](../../baseline/page-079.md)

```text
legacy/
  phase1/
  deprecated_phase2_docs/

runs/
```

### 34.2 Directory responsibilities

**Table 28. Repository directory responsibilities.**

| Directory | Responsibility |
| --- | --- |
| docs/specs/ | Frozen specifications, including the integrated spec, core spec, telemetry spec, and this architecture document. |
| docs/architecture/ | Module maps, dependency rules, interface notes, build-order notes, and implementation ownership records. |
| docs/bringup/ | DE1-SoC programming, HPS Ethernet setup, LINE-IN audio setup, and board connection notes. |
| docs/deprecation/ | Explicit warnings for old Phase 1/Phase 2 documents, including the rule that old delay assumptions such as D = L are deprecated. |
| spec/generated/ | Single source of truth for generated constants, CSR map, packet layouts, interface types, and generation manifests. |
| config/profiles/ | Runtime/build/demo profiles. These are not normative constants. They select source mode, packet enable, sample rate, and dashboard behavior for a run. |
| scripts/ | Header generation, filelist generation, repo layout checks, artifact packaging, and helper scripts. |
| filelists/ | Generated compile and build-order filelists. Build tools consume these instead of ad-hoc source ordering. |
| rtl/include/ | SystemVerilog packages generated or checked from spec/generated/. No hand-coded conflicting constants. |
| rtl/common/ | Reusable hardware utilities: reset synchronizers, FIFOs, skid buffers, ROM wrappers, fixed-point helpers, CDC helpers. |
| rtl/interfaces/ | Interface wrappers and typed port bundles for samples, frame events, core taps, records, CSR, and write channels. |
| rtl/sources/ | BRAM replay source, audio adapter, ADC adapter, diagnostic source, and source mux. |
| rtl/core/ | STFT/WOLA core excluding FFT/IFFT implementation files. This layer has no HPS/Ethernet dependency. |
| rtl/fft/ | Custom FFT/IFFT implementation or vendor-IP wrapper. Arithmetic behavior must match the core spec. |
| rtl/telemetry/ | Packet scheduler, WAVE/SPEC/METRICS/STATUS packetizers, packet FIFO, telemetry top. No DDR write master. |
| `rtl/hps_bridge/` | CSR bank, CSR shadow/commit, ring pointer control, DDR record builder, DDR ring writer, HPS bridge top. |
