# Baseline PDF page 038

Historical Part II, DDR and UDP telemetry. Printed page 25. [Original PDF page](../../../specs/t_recap_phase2_integrated_spec.pdf#page=38).

[Previous](../../baseline/page-037.md) | [Index](../../README.md) | [Next](../../baseline/page-039.md)

- using the HPS to compute FFT, IFFT, WOLA, magnitude-squared, masks, or error metrics.

- treating Ethernet dashboard output as a replacement for BRAM replay signoff.

## 13 System Boundary and Ownership Rules

### 13.1 Core Ownership Rule

The FPGA fabric owns the real-time signal-processing path:

source → STFT/WOLA suppression core → y[n].

The HPS is not permitted to process sample-by-sample data for the purpose of reconstruction or mask decision. Its role is limited to transport, logging, command handling, and register access.

### 13.2 Transport Ownership Rule

The HPS owns Ethernet because the DE1-SoC Ethernet path is HPS-facing. The board manual describes Gigabit Ethernet support through an external KSZ9021RN PHY and the HPS Ethernet MAC function [6]. Therefore, the practical Ethernet architecture is HPS-mediated transport, not direct FPGA Ethernet.

### 13.3 Non-Stall Rule

The telemetry system shall not backpressure the STFT/WOLA core. Telemetry taps are valid-only from the point of view of the core. The telemetry formatter may sample, buffer, or drop tap events, but it shall never assert backpressure into the sample path, frame-trigger path, FFT/IFFT path, WOLA path, or core metrics path. If a packet FIFO is full, the DDR writer is busy, a DDR waitrequest persists, the ring does not have enough free space, HPS is late, or Ethernet is unavailable, the implementation shall drop telemetry records according to the packet-priority order frozen below and increment a drop counter. It shall not stall the sample clock, frame trigger, FFT/IFFT schedule, WOLA output, or core metrics accumulation.

$$
\mathrm{transport\_blocked}\Rightarrow\begin{cases}\text{drop telemetry record}\\\text{increment the relevant drop/error counter}\\\text{continue core processing.}\end{cases}\tag{13.1}
$$

Revision G freezes the packet-priority order for priority-based telemetry shedding: priority 0 is lowest and is dropped first for WAVE. Priority 1 is used for SPEC64/SPEC129. Priority 2 is used for METRICS. Priority 3 is highest and is dropped last for STATUS. WRAP is a ring-control record rather than a normal telemetry record and does not participate in PC-visible packet scheduling. Priority shedding is an admission guarantee, not merely a descriptive label. A priority-aware packet FIFO shall not drop an incoming higher-priority record while a lower-priority resident record is
