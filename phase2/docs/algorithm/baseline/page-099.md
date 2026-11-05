# Baseline PDF page 099

Historical Part III, repository architecture. Printed page 86. [Original PDF page](../../specs/t_recap_phase2_integrated_spec.pdf#page=99).

[Previous](page-098.md) | [Index](../README.md) | [Next](page-100.md)

**Table 45. Core-first implementation cut C0.**

| Class | Content |
| --- | --- |
| Required | rtl/include/, rtl/common/, rtl/interfaces/, rtl/sources/ `trecap_bram_replay_source.sv`, rtl/core/, rtl/fft/, sw/golden/, artifacts/coefficients/, `artifacts/test_vectors/`. |
| Excluded | rtl/telemetry/, `rtl/hps_bridge/`, sw/hps/, `sw/pc_dashboard/`, platform/ de1soc/, live audio, ADC, Ethernet, and HPS runtime integration. |
| Exit condition | make gen-headers, make rtl-filelist, make coeffs, make compile-core using `filelists/rtl_core_plus_fft.f`, and make golden complete without relying on telemetry/HPS/platform folders. |


### 50.2 Transport Implementation Cut T0

Cut T0 begins only after C0 is stable. It adds telemetry packetizers, packet FIFO, HPS bridge, HPS software, PC dashboard, and DE1-SoC Platform Designer integration. T0 shall not alter the core arithmetic contract.

## 51 First Implementation Scope

### 51.1 Core-first required now: Cut C0

The first implementation target is Cut C0. C0 is the core-only path and shall not require telemetry, HPS bridge logic, HPS software, PC dashboard software, Platform Designer integration, live audio, ADC, or Ethernet. It exists to make the arithmetic core buildable and artifact-driven before transport/demo code is introduced.

- Core schema generation and generated headers.

- Coefficient generator and coefficient artifact manifest.

- Frozen vector/artifact generation sufficient for BRAM replay.

- BRAM replay source and full-tail zero flush.

- Exact golden model path for Phase 2 artifacts.

- Core RTL skeleton using generated constants and filelists.

- FFT/IFFT implementation or wrapper shell with the selected contract clearly isolated.

- STFT/WOLA core with analysis windowing, Hermitian canonicalization, THR2 masking, synthesis windowing, and WOLA output.

- Core metrics and valid-only, non-stalling telemetry taps.

C0 exits only when make gen-headers, make rtl-filelist, make coeffs, make compile-core using `filelists/rtl_core_plus_fft.f`, and make golden complete without depending on telemetry/HPS/platform folders.
