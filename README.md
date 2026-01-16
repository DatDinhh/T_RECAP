# T‑RECAP FPGA Demo (DE10‑Lite) — Transform-Domain + Selective Reconstruction MVP

This repository contains a **minimal, real-time FPGA demo** that illustrates the core T‑RECAP idea:

> **Change the data representation (transform-domain), selectively process only the “informative” components, then explicitly reconstruct back to the original domain.**

To keep the demo small and easy to bring up on the **Terasic DE10‑Lite**, the transform used is a **2‑sample Haar transform** (a tiny wavelet/subband transform). Even though it’s small, it preserves the key architectural structure you would later scale to STFT/FFT/filterbanks.

---

## What the demo does (high-level)

At a fixed “sample rate” derived from the 50 MHz clock, the design continuously:

1. Generates a pseudo-random noise stream (no external ADC required)
2. Converts it into a more “signal-like” correlated stream (noise shaping)
3. Processes the stream in a transform domain (Haar)
4. Suppresses small “detail” coefficients based on a configurable threshold
5. Reconstructs time-domain samples
6. Displays key internal values on the 7‑segment LEDs

The result is a real-time pipeline that runs autonomously after reset (no “press a key every step” behavior).

---

## Architecture overview

### Block diagram

