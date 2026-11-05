# Baseline PDF page 092

Historical Part III, repository architecture. Printed page 79. [Original PDF page](../../specs/t_recap_phase2_integrated_spec.pdf#page=92).

[Previous](page-091.md) | [Index](../README.md) | [Next](page-093.md)

### 42.4 Address map file

`platform/de1soc/address_map/address_map.md` shall document:

- CSR base physical address from the HPS view.

- CSR span.

- FPGA-visible ring base address convention.

- HPS physical address convention.

- ring alignment requirements.

- bridge width, burst limits, and relevant waitrequest behavior.

- SOPCINFO or generated Platform Designer artifact location.

## 43 Software Implementation Layout

### 43.1 Golden software

Golden software remains part of the implementation repository because it generates coefficients and frozen artifacts. It is not the verification architecture.

```text
sw/golden/
  include/
    fixed_point.hpp
    fft_radix2_int.hpp
    stft_wola_model.hpp
    artifacts.hpp
    canonical_hash.hpp
  src/
    fixed_point.cpp
    fft_radix2_int.cpp
    stft_wola_model.cpp
    artifacts.cpp
    canonical_hash.cpp
  tools/
    gen_coeffs.py
    gen_vectors.py
    artifact_check.py
    make_quality_bounds.py
  phase2_golden_model.cpp
```

### 43.2 HPS software

```text
sw/hps/
  include/
    generated/
      trecap_csr.h             // generated from csr_map.json
      trecap_packet.h          // generated from packet_layouts.json
```
