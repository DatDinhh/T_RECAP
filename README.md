# T‑RECAP FPGA Demo (DE10‑Lite) - Transform-Domain + Selective Reconstruction MVP

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


---

## Key idea: Haar transform + selective detail suppression

For each *pair* of time samples `(x0, x1)`:

### Forward transform (analysis)
- `a = x0 + x1`  → **approximation / low-frequency content**
- `d = x0 - x1`  → **detail / high-frequency content**

### Selective processing (energy knob)
- If `|d| < THRESH` then **force `d := 0`**
  - This is the demo’s “selective compute / skip low-information components” knob.
  - A larger threshold means more detail is discarded (more smoothing / more loss).

### Reconstruction (synthesis)
- `y0 = (a + d) >> 1`
- `y1 = (a - d) >> 1`

This makes reconstruction explicit: any error is controlled by the threshold and can be measured/observed.

---

## Why the noise shaper exists (important for a visible demo)

Raw LFSR noise changes rapidly and has lots of high-frequency energy. If you feed that directly into Haar, the detail `d` is frequently large, and thresholding may not look “interesting.”

So the demo includes a simple **integrator-based noise shaper**:

- `x[n] = x[n-1] + (noise_raw[n] >> NOISE_SHIFT)`

This creates a more correlated, low-frequency “wandering” signal so that the Haar **detail** term is often small and the threshold knob has a clear effect.

---

## Controls & Observability

### Inputs
- `KEY[0]`: **reset** (active-low)
- `SW[9:0]`: **THRESH** (threshold knob)
  - Internally scaled to match the sample bit width

### Outputs
- `HEX3..HEX0`: **reconstructed output sample** `y_out` (16-bit shown as hex)
- `HEX5..HEX4`: upper byte of `abs_d = |d|` (detail magnitude indicator)
- `LEDR[0]`: heartbeat (sanity that the bitstream is alive)
- `LEDR[9:1]`: mirrors `SW[9:1]`

The design runs continuously; switches can be adjusted live to see how thresholding changes the output/detail magnitude.

---

## File/module list

- `top.sv`
  - Board-level integration: clocking, reset, sample tick, threshold wiring, display
- `sample_tick.sv`
  - Generates a 1-cycle **clock enable pulse** `sample_en` at the target sample rate
- `lfsr_noise.sv`
  - Generates signed pseudo-random samples using an LFSR (updates only on `sample_en`)
- `haar_pair_core.sv`
  - Implements pair buffering + Haar fwd + thresholding + Haar inverse reconstruction
- `hex7seg.sv`
  - 4-bit nibble to 7-seg segment mapping (active-low segments)

---

## Parameters (defaults)

These are defined in `top.sv`:
- `SAMPLE_HZ` (default 8 kHz): how often the pipeline processes a new sample
- `W` (default 16): sample bit width
- `NOISE_SHIFT` (default 8): controls how “smooth” the shaped noise is
- `DISP_HZ` (default 20 Hz): latches values for readability on HEX displays

---

## Build & run (Quartus)

1. Create a Quartus project targeting the DE10‑Lite device.
2. Add the RTL files:
   - `top.sv`, `sample_tick.sv`, `lfsr_noise.sv`, `haar_pair_core.sv`, `hex7seg.sv`
3. Set the top-level entity to `top` (or rename to match your project’s required top).
4. Apply the correct DE10‑Lite pin assignments (via a provided `.qsf` or manual assignment).
5. Compile and program the board.

---

## What you should see

- `LEDR[0]` blinks (heartbeat).
- `HEX3..HEX0` shows the reconstructed sample `y_out` (changes continuously).
- `HEX5..HEX4` shows the magnitude of the Haar detail term `|d|`.
- Increasing `SW[9:0]` (threshold):
  - tends to reduce detail (more cases where `d` is suppressed)
  - makes the reconstructed output look “smoother” (less rapid changes)

---

## How this relates to “full” T‑RECAP

This demo is a minimal version of the broader T‑RECAP pipeline:

- Haar pair transform here ⇢ FFT/STFT/filterbank in the full design
- Thresholding detail here ⇢ selective coefficient processing / sparsity in the full design
- Explicit inverse Haar here ⇢ explicit inverse transform/reconstruction in the full design
- `sample_en` clock enable here ⇢ streaming pipeline enables/backpressure + activity reduction in the full design

The same verification and architecture principles scale upward from this MVP.
