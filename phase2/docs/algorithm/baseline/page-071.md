# Baseline PDF page 071

Historical Part II, DDR and UDP telemetry. Printed page 58. [Original PDF page](../../specs/t_recap_phase2_integrated_spec.pdf#page=71).

[Previous](page-070.md) | [Index](../README.md) | [Next](page-072.md)

## 28 First Implementation Scope

Revision G intentionally keeps optional transport features in the specification for future growth, but the first successful Level-3 bring-up shall not attempt every optional packet or software path at once.

### 28.1 Required First-Demo Scope

The first demo implementation shall include:

- CSR bridge bring-up and register read/write sanity checks.

- ring initialization, reset, producer/consumer pointer commit, and dummy STATUS records.

- WAVE packets for delayed input, reconstructed output, and error.

- exactly one spectrum mode for first integration, either SPEC64 or SPEC129.

- METRICS packets with Revision G flags and unscaled low-64-bit values.

- `SET_THR2` command path with frame-boundary commit.

- drop/error counters and PC-side sequence-gap display.

### 28.2 Deferred Optional Scope

The following features are reserved for later integration and shall not block the first demo:

- PEAKS packet.

- DEBUG packet.

- CRC enablement.

- kernel DMA-coherent driver path.

- simultaneous support for both SPEC64 and SPEC129 in one scheduler.
