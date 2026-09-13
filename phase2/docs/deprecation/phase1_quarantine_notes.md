# Phase 1 quarantine notes

File class: **[1] hand-written repository documentation**.

This file defines how old Phase 1 Haar files are kept for history without contaminating the active Phase 2 STFT/WOLA implementation repository.

The rule is simple:

```text
Phase 1 files may be preserved.
Phase 1 files shall not live at the Phase 2 root.
Phase 1 files shall not compile into Phase 2 build targets.
Phase 1 files shall not define current Phase 2 constants, delay, interfaces, packets, or signoff behavior.
```

## Why quarantine exists

Phase 1 and Phase 2 are related conceptually, but they are not the same implementation.

Phase 1:

```text
2-sample Haar transform
non-overlapping pairs
threshold T on |d|
exact lossless behavior when T = 0
DE10-Lite-style self-contained demo path
old non-UVM ModelSim/Questa testbench files
```

Phase 2:

```text
STFT/WOLA selective suppression
L = 256, H = 128, G = 128, D = L + G = 384
THR2 threshold in magnitude-squared domain
BRAM replay artifact signoff first
DE1-SoC FPGA fabric + HPS DDR + HPS Ethernet + UDP + PC dashboard after C0/T0
```

Keeping Phase 1 files around is useful for explanation and for the Phase 1 mathematical anchor. Mixing them into Phase 2 build paths is a real bug.

## Required quarantine tree

Use this structure for Phase 1 material:

```text
legacy/
└── phase1/
    ├── rtl/
    ├── testbench/
    ├── golden_model/
    ├── tools/
    ├── artifacts/
    └── docs/
```

The folder name `golden_model/` is allowed here because it is the historical Phase 1 software name. It does not mean the current Phase 2 uploaded zip is final golden authority. The current Phase 2 package belongs under:

```text
sw/reference_model/
artifacts/reference_outputs/
```

until the Phase 2 release is frozen.

## Current uploaded Phase 1 files and destination map

Use this map when moving the files that were uploaded during R0 staging.

### Phase 1 RTL

```text
t_recap_demo_top.sv
```

Destination:

```text
legacy/phase1/rtl/t_recap_demo_top.sv
```

Do not instantiate this file from any Phase 2 top. It is a historical Haar demo top, not a Phase 2 STFT/WOLA core.

### Phase 1 C++ model and visualization

```text
golden_model.cpp
viz.py
```

Destinations:

```text
legacy/phase1/golden_model/golden_model.cpp
legacy/phase1/tools/viz.py
```

These files may be used to explain the old Haar reference flow. They shall not generate Phase 2 coefficients, vectors, reference outputs, or `spec/generated/*.json`.

### Phase 1 generated example artifacts

```text
x.memh
y.memh
sup.memh
metrics.json
```

Destination:

```text
legacy/phase1/artifacts/example_haar_run/x.memh
legacy/phase1/artifacts/example_haar_run/y.memh
legacy/phase1/artifacts/example_haar_run/sup.memh
legacy/phase1/artifacts/example_haar_run/metrics.json
```

Do not copy these into `artifacts/test_vectors/` or `artifacts/reference_outputs/`. Phase 2 artifact names and row-count contracts are different.

### Phase 1 testbench and DV files

```text
run.py
tb_top.sv
tb_pkg.sv
board_if.sv
tap_if.sv
bind_taps.sv
board_driver.sv
ref_model_phase1.sv
golden_files_loader.sv
x_stream_monitor.sv
y_stream_monitor.sv
pair_monitor.sv
io_monitor.sv
metrics_monitor.sv
scoreboard_pairs.sv
scoreboard_y_stream.sv
scoreboard_metrics.sv
cov_phase1.sv
sva_phase1_bind.sv
test_base.sv
test_bypass_lossless.sv
test_golden_thresh16.sv
test_threshold_sweep.sv
test_clear_metrics_midrun.sv
test_mode_switch_stress.sv
tb_top.sv.bak_*
```

Destination:

```text
legacy/phase1/testbench/
```

These files are useful history. They are not the Phase 2 verification architecture. The active Phase 2 implementation repository intentionally does not define verification scoreboards, monitors, assertion hierarchy, or regression inventory yet.

### Phase 1 and early report PDFs

```text
T_RECAP_Phase1_Algorithm.pdf
Report-1.pdf
untitled-1.pdf
```

Destinations:

```text
legacy/phase1/docs/T_RECAP_Phase1_Algorithm.pdf
legacy/phase1/docs/Report-1.pdf
legacy/deprecated_phase2_docs/untitled-1.pdf    # if treated as an early Phase 2/report draft
```

The exact destination for mixed-content reports can be adjusted, but they shall not become active specs under `docs/specs/`.

## Files forbidden at Phase 2 repository root

The Phase 2 root shall not contain these Phase 1 files:

```text
t_recap_demo_top.sv
golden_model.cpp
viz.py
run.py
x.memh
y.memh
sup.memh
metrics.json
tb_top.sv
tb_top.sv.bak_*
tb_pkg.sv
board_if.sv
tap_if.sv
bind_taps.sv
board_driver.sv
ref_model_phase1.sv
golden_files_loader.sv
x_stream_monitor.sv
y_stream_monitor.sv
pair_monitor.sv
io_monitor.sv
metrics_monitor.sv
scoreboard_pairs.sv
scoreboard_y_stream.sv
scoreboard_metrics.sv
cov_phase1.sv
sva_phase1_bind.sv
test_base.sv
test_bypass_lossless.sv
test_golden_thresh16.sv
test_threshold_sweep.sv
test_clear_metrics_midrun.sv
test_mode_switch_stress.sv
```

The root `.gitignore` is allowed to ignore accidental root copies of these names. That does not mean the files are deleted. Deliberate archival copies belong under `legacy/phase1/`.

## Import procedure

From the repository root:

```bash
mkdir -p legacy/phase1/rtl
mkdir -p legacy/phase1/testbench
mkdir -p legacy/phase1/golden_model
mkdir -p legacy/phase1/tools
mkdir -p legacy/phase1/artifacts/example_haar_run
mkdir -p legacy/phase1/docs
mkdir -p legacy/deprecated_phase2_docs
```

Move files by ownership:

```bash
git mv t_recap_demo_top.sv legacy/phase1/rtl/ 2>/dev/null || true
git mv golden_model.cpp legacy/phase1/golden_model/ 2>/dev/null || true
git mv viz.py legacy/phase1/tools/ 2>/dev/null || true
git mv x.memh y.memh sup.memh metrics.json legacy/phase1/artifacts/example_haar_run/ 2>/dev/null || true
```

Move testbench files as a group:

```bash
git mv tb_top.sv tb_pkg.sv board_if.sv tap_if.sv bind_taps.sv board_driver.sv legacy/phase1/testbench/ 2>/dev/null || true
git mv ref_model_phase1.sv golden_files_loader.sv legacy/phase1/testbench/ 2>/dev/null || true
git mv x_stream_monitor.sv y_stream_monitor.sv pair_monitor.sv io_monitor.sv metrics_monitor.sv legacy/phase1/testbench/ 2>/dev/null || true
git mv scoreboard_pairs.sv scoreboard_y_stream.sv scoreboard_metrics.sv legacy/phase1/testbench/ 2>/dev/null || true
git mv cov_phase1.sv sva_phase1_bind.sv legacy/phase1/testbench/ 2>/dev/null || true
git mv test_base.sv test_*.sv run.py legacy/phase1/testbench/ 2>/dev/null || true
```

Then check:

```bash
make check-layout
```

Do not force these commands if a file was never present. The important result is that the Phase 2 root has no active Phase 1 build file.

## Build-system rules

Phase 2 active filelists shall never include files under:

```text
legacy/phase1/
legacy/deprecated_phase2_docs/
```

Generated filelists are the source of compile order after R1:

```text
filelists/rtl_core.f
filelists/rtl_core_plus_fft.f
filelists/rtl_telemetry.f
filelists/rtl_hps_bridge.f
filelists/rtl_de1soc_full.f
```

If a Phase 1 file appears in any active Phase 2 filelist, treat it as a release-blocking error.

## Allowed uses of Phase 1 material

Allowed:

```text
Use Phase 1 docs to explain the project origin.
Use Phase 1 Haar equations as the historical mathematical anchor.
Use Phase 1 C++/SV files as examples when writing explanatory notes.
Use Phase 1 metrics as old report evidence only.
```

Forbidden:

```text
Compile Phase 1 RTL into Phase 2 top modules.
Copy Phase 1 scoreboards into the active Phase 2 implementation tree.
Use Phase 1 `x.memh`, `y.memh`, or `sup.memh` as Phase 2 signoff vectors.
Use Phase 1 `metrics.json` as Phase 2 artifact schema.
Use Phase 1 exact T = 0 identity as a Phase 2 STFT/WOLA exactness claim.
Use Phase 1 switch threshold T as the Phase 2 THR2 contract.
Use Phase 1 board mapping as DE1-SoC platform mapping.
```

## Relationship to current R0 files

This document is written to match the R0 files already created:

```text
README.md
Makefile
CMakeLists.txt
.gitignore
.editorconfig
.clang-format
.pre-commit-config.yaml
docs/specs/README.md
docs/architecture/*.md
docs/bringup/*.md
```

Expected behavior:

```text
README.md warns that Phase 1 files are allowed only under legacy/phase1/.
Makefile check-layout fails if forbidden Phase 1 root files exist.
.gitignore ignores accidental root Phase 1 dumps but does not hide legacy/phase1/ archives.
docs/specs/README.md keeps old PDFs out of docs/specs/.
docs/architecture/dependency_rules.md forbids legacy files from active build dependencies.
docs/bringup/quartus_programming.md warns not to program old t_recap_demo_top.sv as Phase 2.
```

## Quarantine acceptance checklist

```text
[ ] `legacy/phase1/` exists.
[ ] Old Haar RTL is under `legacy/phase1/rtl/`.
[ ] Old Phase 1 testbench/DV is under `legacy/phase1/testbench/`.
[ ] Old Phase 1 C++ model is under `legacy/phase1/golden_model/`.
[ ] Old Phase 1 plots/tools are under `legacy/phase1/tools/`.
[ ] Old Phase 1 memh/json artifacts are under `legacy/phase1/artifacts/`.
[ ] Old Phase 1 PDFs are under `legacy/phase1/docs/`.
[ ] Deprecated early Phase 2/report drafts are under `legacy/deprecated_phase2_docs/`.
[ ] No Phase 1 source file remains at the Phase 2 root.
[ ] No active filelist references `legacy/phase1/`.
[ ] `make check-layout` passes.
[ ] Current implementation docs still use `D = L + G = 384`, not `D = L`.
```

## Practical rule for future contributors

If a file name starts with one of these patterns, stop and check ownership before adding it to the active repo:

```text
t_recap_demo_top
haar
phase1
scoreboard_
*_monitor
x.memh/y.memh/sup.memh from the old Haar flow
```

The safe default is to place it under `legacy/phase1/` and then explicitly promote only rewritten Phase 2 code into `rtl/`, `sw/`, `artifacts/`, or `spec/`.
