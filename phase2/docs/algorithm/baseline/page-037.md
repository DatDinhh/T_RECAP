# Baseline PDF page 037

Historical Part II, DDR and UDP telemetry. Printed page 24. [Original PDF page](../../specs/t_recap_phase2_integrated_spec.pdf#page=37).

[Previous](page-036.md) | [Index](../README.md) | [Next](page-038.md)

[Edit Markdown and LaTeX source](../source/baseline/page-037.md). Equations are rendered locally as SVG.

## Part II - Ethernet/HPS DDR Telemetry and Control Architecture

Part II defines the real-time observability and command layer. It does not redefine the STFT/WOLA arithmetic core. It moves already-computed core observability signals from FPGA fabric through HPS DDR and HPS Ethernet to the PC.

## 12 Purpose and Scope

### 12.1 Purpose

The purpose of this document is to specify the real-time Ethernet telemetry and control path for the Phase 2 T-RECAP implementation on DE1-SoC. The design target is a high-observability demonstration in which the PC displays:

- delayed input waveform, reconstructed output waveform, and time-domain error.

- real-time spectrogram based on compressed magnitude-squared bins.

- mask/suppression overlay or mask-derived statistics.

- suppression ratio, kept-energy ratio, error metrics, drop counters, and overflow flags.

- live threshold and source-mode controls.

### 12.2 Relationship to Part I

This addendum does not replace the Phase 2 core mathematical specification. The core specification remains normative for:

- STFT/WOLA frame timing, hop size, delay, and finite-stream scoring.

- fixed-point rounding, saturation, coefficient quantization, FFT/IFFT arithmetic, and Hermitian canonicalization.

- magnitude-squared thresholding and mask construction.

- BRAM replay signoff artifacts and golden-model comparison. This addendum is a transport and observability specification. It defines how already-computed core signals are moved to a PC dashboard and how PC commands are returned to the FPGA through the HPS.

### 12.3 Non-Goals

The following items are outside the scope of this document:

- redefining the STFT/WOLA core or its arithmetic contract.

- defining SystemVerilog module decomposition or signal-level RTL implementation.

- defining Linux kernel-driver source code.
