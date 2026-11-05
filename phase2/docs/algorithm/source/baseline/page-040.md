# Baseline PDF page 040

Historical Part II, DDR and UDP telemetry. Printed page 27. [Original PDF page](../../../specs/t_recap_phase2_integrated_spec.pdf#page=40).

[Previous](../../baseline/page-039.md) | [Index](../../README.md) | [Next](../../baseline/page-041.md)

The reverse command path is:

PC command → HPS command parser → CSR writes → FPGA control shadow/commit.

### 15.2 Functional Blocks

**Table 7. Level-3 functional block responsibilities.**

| Block | Responsibility |
| --- | --- |
| Core telemetry taps | Observe already-existing FPGA core signals such as delayed input, reconstructed output, time-domain error, compressed spectral bins, mask bits, frame metrics, and status flags. |
| Telemetry formatter | Builds packet payloads for waveform, spectrum, metrics, status, and optional debug records. |
| DDR ring writer | Writes formatted records to HPS-visible DDR and commits the producer pointer after write completion. |
| CSR bank | Exposes configuration, control, status, thresholds, packet-enable masks, ring base/size, producer/consumer pointers, and drop counters. |
| HPS UDP streamer | Reads committed records, sends UDP datagrams to the PC, receives commands, and writes CSR updates. |
| PC dashboard | Plots waveform, error, spectrogram, metrics, status, and provides live control input. |


### 15.3 DE1-SoC Bridge and Address-Mapping Assumption

The Level-3 writer is an FPGA-side bus master connected to HPS-visible DDR through the FPGAto-HPS SDRAM bridge, FPGA-to-HPS bridge, or an equivalent Platform Designer integration. The exact interconnect name may differ by project configuration, but the following address rule is normative:

`RING_BASE` is the address as seen by the FPGA DDR writer bus master. It is not a Linux virtual address.

HPS software is responsible for translating the allocated or reserved DDR physical address into the FPGA-visible bus address required by the platform integration. CSR registers are accessed through the HPS-to-FPGA lightweight bridge or an equivalent memory-mapped CSR bridge. The DDR ring shall be located in a memory region that Linux will not allocate for unrelated purposes. If a userspace /dev/mem prototype is used, the region shall be reserved from Linux. If a kernel driver is used, the driver shall allocate or expose a DMA-safe buffer and shall provide the FPGA-visible base address to the CSR bank.
