# TRF1 recorded RF board profile

New RF application on the existing HPS50 platform. Preserve the HPS handoff, pin assignments, reset topology and numerical core. No website change. Raw CU8 pairs pass through the new FPGA RF adapter, then the existing finite core, Y FIFO and TSP1 exporter. Default transaction geometry stays384000 real samples,384512 Y samples and3001 frames.

The register interface derives from TSH2 but has distinct identity. Magic0x54524631 spells TRF1. ABI0x00010000. Existing source identity at0x080..0x09c binds the new build.

| Offset | Meaning |
| --- | --- |
| 0x000 | TRF1 magic |
| 0x004 | ABI0x00010000 |
| 0x008 | Existing status bits. Bit3 now means raw IQ input FIFO accepts a pair |
| 0x00c | Existing fault bits0..3. Bit4 RF adapter/configuration/count fault |
| 0x010 | 1CLEAR,2START. Same idle admission and epoch rules |
| 0x014,0x018,0x01c | Threshold56bit and sparse mode, unchanged |
| 0x020 | Append CU8 pair, lowbyteI,nextbyteQ, upper16bits must be zero |
| 0x024 | Accepted host IQ-pair writes |
| 0x028..0x034 | Epoch, spectral available words and Y available words, unchanged |
| 0x038,0x03c | Raw IQ FIFO level and free slots, capacity256. A prefetched stage is excluded from these queue counts |
| 0x040,0x044 | Pop spectral word and Y sample, unchanged |
| 0x048..0x070 | Existing Y, cycle, drop, frame, real core-input and output geometry counters, unchanged |
| 0x074 | Raw IQ FIFO capacity256 |
| 0x078,0x07c | Spectral andY capacity1024 each |
| 0x080..0x09c | New SOURCE_ID256 |
| 0x0a0 | RW configured pair count,1..INPUT_SAMPLES/4, idle only. Reset/CLEAR default INPUT_SAMPLES/4 |
| 0x0a4 | RW gain shift0..3, idle only. Reset/CLEAR default1 |
| 0x0a8 | Adapter RF output samples accepted, excludes transaction padding |
| 0x0ac | RF adapter IQ input pairs accepted |
| 0x0b0 | RF clipped output count |
| 0x0b4 | RF status bit0busy,bit1latched RF wrapper done,bit2clipsticky,bit3configerror |
| 0x0b8 | Valid real RF sample count4*configured pairs, recorded for plotting |

Register0x058 counts real samples consumed by the core, always INPUT_SAMPLES at success. Register0x024 counts host pairs and must equal configured pair count. At success RF input count matches configuredpairs, adapter output count equals4*pairs, wrapper outputcount equals INPUT_SAMPLES and RFdone is latched. Clipping is counted, not silently hidden. Initial qualification uses gain1 and requires zero clipping.

Use a256-entry raw input FIFO with registered prefetch to respect stream_fifo's one-cycle read response. Its free-space count retains the old bounded burst-write contract. Start the RF source only once the core has accepted its start and source-discontinuity clear has finished. RF source reset/clear cancels any prefetch. Do not send raw IQ before the new application acknowledges running and input-ready.

The C client verifies magic, ABI, SOURCE_ID, geometry and boot identity before MMIO. It sends raw file bytes without interpolation, mixing, scaling or FFT on HPS. It interleaves bounded writes with draining both output FIFOs. Save allY, allTSP1 and RF counters. Outer watchdogs and the existing physical ownership/admission checks remain in force.

Full build and board programming are root-owned. No agent other than root may access UART, JTAG, board network, reset or FPGA registers. Do not change SD/flash or host network configuration. Use fresh RAM paths and retain failed attempts as evidence.
