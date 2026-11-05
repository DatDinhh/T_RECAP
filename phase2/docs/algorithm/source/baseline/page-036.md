# Baseline PDF page 036

Historical Part I, core algorithm. Printed page 23. [Original PDF page](../../../specs/t_recap_phase2_integrated_spec.pdf#page=36).

[Previous](../../baseline/page-035.md) | [Index](../../README.md) | [Next](../../baseline/page-037.md)

Human-facing threshold controls are wrappers. If an amplitude-domain threshold Tamp,QF is exposed, then

$$
\mathrm{THR2}=T_{\mathrm{amp},QF}^{\,2}.\tag{9.6}
$$

For an 8-bit switch preset, a valid wrapper may define

$$
T_{\mathrm{amp},QF}=\mathrm{SW}[7:0]\ll K_{\mathrm{thr}},\qquad\mathrm{THR2}=T_{\mathrm{amp},QF}^{\,2}.\tag{9.7}
$$

but Kthr and the preset mapping shall be frozen in config.json. Directly interpreting the switch value as raw THR2 is allowed only if declared explicitly.

Wrapper computation of $\mathrm{THR2}=T_{\mathrm{amp},QF}^{\,2}$ shall be performed in a width large enough to hold the full square. The resulting threshold shall then be checked against $0\le\mathrm{THR2}<2^{W_{\mathrm{mag2}}}$. Out-of-range wrapper thresholds are illegal for the core signoff contract unless the wrapper explicitly defines saturation or clipping outside the core contract and records that policy in `config.json`.

## 10 Throughput and Power Interpretation

Let Fs be the input sample rate and fclk be the FPGA fabric clock. The number of fabric cycles per hop is

$$
C_{\mathrm{hop}}=f_{\mathrm{clk}}\frac{H}{F_s}.\tag{10.1}
$$

A burst-style implementation that begins frame processing at τm must make its frame contribution available before slot τm + G, so

$$
T_{\mathrm{frame}}<\frac{G}{F_s}.\tag{10.2}
$$

With G = H, this becomes Tframe < H/Fs . The baseline core computes the STFT every frame. Suppressed-bin count is therefore a workload proxy, not direct proof of power reduction. A real power-reduction claim requires a later downstream stage that uses the mask to skip feature extraction, detector operations, coefficient transport, memory writes, or other work.

## 11 Conclusion

This specification defines the Phase 2 T-RECAP core as a deterministic fixed-point STFT/WOLA selective-suppression operator. Revision J freezes the items that usually cause golden-model and RTL drift: coefficient representability, coefficient ROM widths, arithmetic shift behavior on negative integers, rounded shifts including zero-shift, active-window full-tail finite-stream scoring, exact custom radix-2 FFT/IFFT ordering, explicit forward/inverse twiddle aliases, inverse twiddle artifacts, full-precision unsigned threshold comparison, internal product widths, eligible spectral accounting, canonical signed and unsigned memh encodings and hashes, exact artifact line counts, conditional binstats row-count semantics, CSV row order, exact JSON schemas, stream hashes, wrapper threshold overflow policy, and frozen test-vector generator algorithms including `multitone_sine_sum`.
