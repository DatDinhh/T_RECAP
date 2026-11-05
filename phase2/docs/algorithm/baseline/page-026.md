# Baseline PDF page 026

Historical Part I, core algorithm. Printed page 13. [Original PDF page](../../specs/t_recap_phase2_integrated_spec.pdf#page=26).

[Previous](page-025.md) | [Index](../README.md) | [Next](page-027.md)

Let E = {k ∈ {0, . . . , L/2} : ϵ[k] = 1}. For one frame,

$$
U_{\mathrm{uniq}}=L/2+1,\qquad S_{\mathrm{uniq}}=\sum_{k=0}^{L/2}\operatorname{mask}[k].\tag{7.2}
$$

$$
U_{\mathrm{elig}}=|\mathcal E|,\qquad S_{\mathrm{elig}}=\sum_{k\in\mathcal E}\operatorname{mask}[k].\tag{7.3}
$$

$$
E_{\mathrm{elig,total}}=\sum_{k\in\mathcal E}\omega[k]\operatorname{mag2}[k],\qquad E_{\mathrm{elig,kept}}=\sum_{k\in\mathcal E}(1-\operatorname{mask}[k])\omega[k]\operatorname{mag2}[k].\tag{7.4}
$$

These are normalized spectral magnitude-squared totals for deterministic accounting. They are not direct physical energy measurements unless Parseval scaling is applied. The name `unique_suppressed_bins` means the final post-protection mask count over all unique bins. Under the current post-protection mask semantics, protected bins are forced to mask=0, so `unique_suppressed_bins` and `eligible_suppressed_bins` are equal whenever those protection rules are applied. The useful distinction is in the denominators: `unique_bins` includes protected bins, while `eligible_unique_bins` excludes them. The preferred workload proxy is therefore `eligible_suppressed_bins/eligible_unique_bins`. If a debug flow needs to know which protected bins would have been suppressed before protection, it shall use the optional bin-level `pre_mask` field rather than changing the frame-statistics counters.

### 7.2 Time-domain quality metrics

For 0 ≤ n < Ny ,

$$
e[n]=x_z[n-D]-y[n].\tag{7.5}
$$

Required integer metrics are

$$
\mathrm{sum\_abs\_err}=\sum_{n=0}^{N_y-1}|e[n]|.\tag{7.6}
$$

$$
\mathrm{sum\_sq\_err}=\sum_{n=0}^{N_y-1}e[n]^2.\tag{7.7}
$$

$$
\mathrm{max\_abs\_err}=\max_{0\le n<N_y}|e[n]|.\tag{7.8}
$$

$$
\mathrm{error\_sample\_count}=N_y.\tag{7.9}
$$

RMSE may be reported as a derived floating field, but the integer numerator and denominator are the signoff quantities.

### 7.3 Canonical memory-file encoding

All memh files contain exactly one value per line, lowercase hexadecimal digits only, no 0x prefix, no leading or trailing spaces, no blank lines, and exactly one LF line ending after each value in the canonical form. For an unsigned W -bit memh file, each line shall contain exactly ⌈W/4⌉ hexadecimal digits. The value shall satisfy 0 ≤ value < $2^{W}$ . Readers shall mask to W bits and shall not sign-extend unsigned files.
