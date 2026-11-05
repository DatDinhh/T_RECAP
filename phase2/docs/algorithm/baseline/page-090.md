# Baseline PDF page 090

Historical Part III, repository architecture. Printed page 77. [Original PDF page](../../specs/t_recap_phase2_integrated_spec.pdf#page=90).

[Previous](page-089.md) | [Index](../README.md) | [Next](page-091.md)

[Edit Markdown and LaTeX source](../source/baseline/page-090.md). Equations are rendered locally as SVG.

## 41 Clock and Reset Ownership

### 41.1 Clock-domain baseline

`clock_reset_ctrl.sv` owns board-level reset conditioning and clock-domain reset synchronization. The first implementation may use one fabric clock for the core, telemetry, and HPS bridge. Even in that single-clock bring-up, module boundaries shall preserve CDC-safe structure so that a later clock split does not require rewriting the architecture.

**Table 41. Clock/reset domain ownership.**

| Domain | Owned logic |
| --- | --- |
| Core domain | STFT/WOLA core, source samples, frame scheduler, FFT/IFFT control, WOLA output, and core metrics. |
| Telemetry domain | Packetizers and packet FIFO, unless intentionally the same as the core domain. |
| HPS bridge / Avalon domain | CSR bank, DDR ring writer, pointer control, Platform Designer bus ports, and DDR write master. |
| Board wrapper domain | Board clocks, reset conditioning, audio/ADC clocks if used, and platform-specific clock crossing wrappers. |


### 41.2 CDC rules

1. No multi-bit signal may cross clock domains by independent bit synchronization.

2. Multi-bit transfers shall use an async FIFO, snapshot/commit handshake, Gray-coded counter protocol, or explicitly documented equivalent.

3. Reset deassertion shall be synchronized per clock domain.

4. HPS-written controls that affect the core, such as THR2 or source mode, shall cross using shadow/commit or safe-boundary update logic.

5. Telemetry taps shall never backpressure the STFT/WOLA core. If a packet FIFO or CDC FIFO cannot accept data, the telemetry event is dropped and the appropriate drop counter is incremented.

## 42 Platform Designer and DE1-SoC Ownership

### 42.1 Platform files

The DE1-SoC Platform Designer/Qsys integration shall be owned by platform/de1soc/ and rtl/ platform/de1soc/.

platform/de1soc/ qsys/ `platform_designer.tcl` system.qsys // if project stores Qsys directly
