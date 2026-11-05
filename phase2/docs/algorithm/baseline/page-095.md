# Baseline PDF page 095

Historical Part III, repository architecture. Printed page 82. [Original PDF page](../../specs/t_recap_phase2_integrated_spec.pdf#page=95).

[Previous](page-094.md) | [Index](../README.md) | [Next](page-096.md)

[Edit Markdown and LaTeX source](../source/baseline/page-095.md). Equations are rendered locally as SVG.

1. `sw/golden/tools/gen_coeffs.py` owns coefficient generation.

2. artifacts/coefficients/ owns frozen generated memh files and the coefficient manifest.

3. `rtl/core/window_rom.sv` may load only the frozen `window_qw.memh` artifact.

4. `rtl/fft/twiddle_rom.sv` may load only the frozen forward and inverse twiddle artifacts.

5. No RTL module shall generate sine, cosine, or window coefficients internally.

6. No separate hand-written coefficient table is allowed.

The required coefficient artifacts are:

```text
artifacts/coefficients/
  window_qw.memh
  twiddle_re.memh
  twiddle_im.memh
  twiddle_inv_re.memh
  twiddle_inv_im.memh
  coeff_manifest.json
```

### 45.2 Memory primitive policy

All inferred RAMs shall be wrapped through rtl/common/ memory wrappers unless a module has a documented reason to instantiate vendor primitives directly.

**Table 42. Baseline memory primitive wrappers.**

| Wrapper | Purpose |
| --- | --- |
| `true_dual_port_ram.sv` | Shared wrapper for memories requiring two independent read/write ports. |
| `simple_dual_port_ram.sv` | Shared wrapper for one-write, one-read memories. |
| `sync_fifo.sv` | Same-clock FIFO wrapper for core or telemetry streams. |
| `async_fifo.sv` | CDC FIFO wrapper when producer and consumer clocks differ. |


Core modules shall not directly instantiate board-specific memory IP. Board/platform-specific memory IP belongs under rtl/platform/de1soc/ or in documented vendor wrappers.

## 46 Artifact and Data Layout

### 46.1 Artifact directories

```text
artifacts/
  coefficients/
    window_qw.memh
    twiddle_re.memh
```
