# Baseline PDF page 096

Historical Part III, repository architecture. Printed page 83. [Original PDF page](../../../specs/t_recap_phase2_integrated_spec.pdf#page=96).

[Previous](../../baseline/page-095.md) | [Index](../../README.md) | [Next](../../baseline/page-097.md)

```text
  twiddle_im.memh
  twiddle_inv_re.memh
  twiddle_inv_im.memh
  coeff_manifest.json
test_vectors/
  test_vectors.json
  vector_name/
    x_in.memh
    config.json
golden/
  vector_name/
    y_out.memh
    frame_stats.csv
    metrics.json
manifests/
  quality_bounds.json
  artifact_index.json
  frozen_release_manifest.json
telemetry_captures/
  capture_name/
    packets.bin
    capture_manifest.json
```

### 46.2 Artifact authority rule

After a vector or coefficient table is frozen, its canonical artifact and SHA-256 hash are the authority. Regenerating a vector from a generator equation is not sufficient unless the hash matches. This avoids math-library drift between Python, C++, MATLAB, and RTL ROM loaders.

## 47 Legacy and Deprecated Document Quarantine

### 47.1 Phase 1 quarantine

The repository shall not leave Phase 1 files at the Phase 2 root. Phase 1 code shall be moved under:

```text
legacy/phase1/
  rtl/
  testbench/
  golden_model/
  docs/
```

Examples of files that shall not remain in the Phase 2 root include old Phase 1 run.py, `tb_top.sv`, viz.py, `golden_model.cpp`, and Haar-specific scoreboards or monitors.

### 47.2 Deprecated Phase 2 warning

The root README.md shall contain a warning block: Deprecated documents:
