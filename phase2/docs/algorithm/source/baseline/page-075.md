# Baseline PDF page 075

Historical Part III, repository architecture. Printed page 62. [Original PDF page](../../../specs/t_recap_phase2_integrated_spec.pdf#page=75).

[Previous](../../baseline/page-074.md) | [Index](../../README.md) | [Next](../../baseline/page-076.md)

### 32.3 Out of scope

This document does not define:

- verification repository structure.

- scoreboards, monitors, assertion hierarchy, or regression test inventory.

- UVM or non-UVM verification architecture.

- detailed waveform-level debugging policy.

- final resource utilization or timing-closure results.

A later verification architecture document shall define testbench layout, scoreboards, monitors, assertions, coverage, and regression strategy.

## 33 Architectural Principles

### 33.1 Non-negotiable implementation rules

1. Core independence. rtl/core/ shall build without HPS, Ethernet, DDR ring, UDP packets, dashboard code, or board-specific wrappers.

2. BRAM replay first. The core repository shall include a BRAM replay source and artifactdriven golden-model flow before live audio or Ethernet integration is accepted.

3. Generated constants only. CSR offsets, packet type IDs, packet payload sizes, status bit positions, and transport version numbers shall come from generated shared headers.

4. No split ownership of DDR writer. Telemetry formats records. The HPS bridge owns DDR record building, wrap handling, producer pointer commit, and the DDR write master.

5. Telemetry cannot stall core. A full telemetry path drops records and increments counters. It shall not backpressure sample input, frame scheduling, FFT/IFFT, WOLA, or core metrics.

6. HPS does not process signal samples. HPS software may read records, patch outgoing STATUS copies, send UDP, receive commands, and write CSRs. It shall not compute FFT, IFFT, masks, WOLA, or reconstruction error.

7. Deprecated files are quarantined. Phase 1 files and older Phase 2 drafts shall be isolated so that the Phase 2 root build cannot accidentally compile or depend on them.

### 33.2 Ownership diagram

```text
PC dashboard
  packet parser + plots + command client
        ^
        | UDP Ethernet
        v
HPS software
  DDR ring reader + UDP streamer + command server + CSR writer
        ^
```
