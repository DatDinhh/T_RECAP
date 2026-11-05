# Baseline PDF page 077

Historical Part III, repository architecture. Printed page 64. [Original PDF page](../../../specs/t_recap_phase2_integrated_spec.pdf#page=77).

[Previous](../../baseline/page-076.md) | [Index](../../README.md) | [Next](../../baseline/page-078.md)

```text
     telemetry_status_only.json
     telemetry_full_demo.json

scripts/
  gen_headers.py
  gen_filelists.py
  package_artifacts.py
  lint_repo_layout.py
  check_generated.py

filelists/
  rtl_core.f
  rtl_core_plus_fft.f
  rtl_telemetry.f
  rtl_hps_bridge.f
  rtl_de1soc_full.f
  quartus_de1soc.qsf.inc

rtl/
  include/
     generated/
  common/
  interfaces/
  sources/
  core/
  fft/
  telemetry/
  hps_bridge/
  platform/de1soc/
  top/

sw/
  golden/
    generated/
  hps/
    include/generated/
  pc_dashboard/
    generated/

artifacts/
  coefficients/
  test_vectors/
  golden/
  manifests/
  telemetry_captures/

constraints/
  de1soc/

platform/
  de1soc/
    qsys/
    address_map/
    generated_notes/
```
