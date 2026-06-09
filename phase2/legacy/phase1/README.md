# Legacy Phase 1 quarantine

This directory is the quarantine location for Phase 1 Haar proof-of-concept
material. It exists so historical files can be preserved without becoming part
of the active Phase 2 golden-model build.

Allowed content here, if imported later:

```text
legacy/phase1/
├── rtl/
├── testbench/
├── golden_model/
└── docs/
```

Rules:

1. Do not include files under `legacy/phase1/` in the Phase 2 CMake build,
   Python package, artifact flow, or CI artifact signoff gates.
2. Do not leave old Phase 1 root files such as `run.py`, `tb_top.sv`,
   `viz.py`, `golden_model.cpp`, Haar scoreboards, or Haar monitors in the
   Phase 2 root tree.
3. Do not copy Phase 1 arithmetic into Phase 2 code unless the Phase 2 Revision J
   fixed-point contract explicitly defines the same operator.
4. Use this directory for historical reference only. Active Phase 2 source lives
   in `include/`, `src/`, `tools/`, `python/`, `configs/`, and generated/frozen
   artifact flows under `artifacts/`.

The Phase 2 baseline is STFT/WOLA with delay `D = L + G = 384`, not the older
Phase 1 Haar identity pipeline.
