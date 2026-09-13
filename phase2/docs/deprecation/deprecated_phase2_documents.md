# Deprecated Phase 2 documents

File class: **[1] hand-written repository documentation**.

This file records which older Phase 2 notes, drafts, reports, and copied PDFs are historical only. It prevents old assumptions from leaking into the active Phase 2 implementation repository.

This document is not a replacement for the active specification. It is a warning and traceability file.

## Authority

The active implementation authority is the integrated Phase 2 specification stored under `docs/specs/`:

```text
docs/specs/doneeeeeeeeee.pdf
# or, after deliberate rename:
docs/specs/t_recap_phase2_integrated_spec.pdf
```

The active specification controls:

```text
Core Revision J
Telemetry Revision G
Repository Architecture Revision D
```

The root `README.md` and `docs/specs/README.md` already state the same authority. This deprecation document shall not contradict those files.

## Non-negotiable warning

Deprecated documents:

```text
Older Phase 2 Algorithm Report drafts are historical only.
Do not use D = L for the current DE1-SoC baseline.
Use the integrated Phase 2 specification: Core Revision J + Telemetry Revision G.
Current baseline delay: D = L + G = 384 samples.
```

That warning belongs in the root `README.md`, and any old draft that disagrees with it is not an implementation source.

## What "deprecated" means here

Deprecated does not mean useless. It means:

```text
allowed:    background, motivation, history, comparison, report writing
forbidden: active architecture, build input, constants, CSR definitions, packet layouts, signoff rules
```

A deprecated document may explain how the project evolved, but it shall not decide current RTL, HPS C, Python dashboard, filelists, generated headers, memory maps, or artifact contracts.

## Deprecated-document storage policy

Use these locations:

```text
docs/deprecation/
    deprecated_phase2_documents.md       # this file
    phase1_quarantine_notes.md           # Phase 1 source/file quarantine rules

legacy/deprecated_phase2_docs/
    old Phase 2 drafts, copied PDFs, screenshots, notes, and replaced reports

legacy/phase1/docs/
    Phase 1 Haar reports and Phase 1-only algorithm notes
```

Do not store deprecated PDFs in `docs/specs/` unless the file is intentionally being kept as the active frozen spec. Do not store deprecated source code under `docs/`.

## Active versus historical documents

Use this classification table when importing or moving documents.

| Document class | Example filename | Correct location | Status | May control implementation? |
| --- | --- | --- | --- | --- |
| Current integrated Phase 2 spec | `doneeeeeeeeee.pdf` or `t_recap_phase2_integrated_spec.pdf` | `docs/specs/` | active | yes |
| Old Phase 2 algorithm draft | any older draft superseded by Core Rev J / Telemetry Rev G | `legacy/deprecated_phase2_docs/` | historical | no |
| Phase 1 algorithm PDF | `T_RECAP_Phase1_Algorithm.pdf` | `legacy/phase1/docs/` | historical Phase 1 | no |
| Early project report | `Report-1.pdf` | `legacy/phase1/docs/` or `legacy/deprecated_phase2_docs/` depending on content | historical | no |
| Early slide/report draft | `untitled-1.pdf` | `legacy/phase1/docs/` or `legacy/deprecated_phase2_docs/` depending on content | historical | no |
| Board-demo notes for old Haar RTL | any DE10-Lite / Phase 1 demo note | `legacy/phase1/docs/` | historical | no |

If a file contains both useful background and obsolete implementation details, keep it historical and write a short note in this file or in `legacy/deprecated_phase2_docs/README.md` explaining what is obsolete.

## Obsolete assumptions blocked by this file

Do not carry these assumptions into Phase 2 implementation:

```text
D = L
T = 0 implies exact sample-for-sample lossless reconstruction for Phase 2 STFT/WOLA
Phase 2 is still only planned future work
Phase 2 uses non-overlapping Haar pairs
Phase 2 correctness can be judged by live Ethernet telemetry or dashboard plots
HPS may compute FFT/IFFT/mask/WOLA/reconstruction/error
telemetry may stall the core when the PC or Ethernet path is slow
CSR offsets or packet sizes may be copied by hand into RTL/C/Python
Phase 1 DE10-Lite board top may be used as the Phase 2 DE1-SoC top
old `sw/golden/` wording means the current uploaded zip is already final golden authority
```

The current implementation repository uses:

```text
sw/reference_model/
artifacts/reference_outputs/
```

for the uploaded Phase 2 reference package until artifacts, hashes, RTL equivalence, and BRAM replay signoff are frozen. A `make golden` target may exist for compatibility with the spec vocabulary, but the current package should still be described as a reference model unless the release has been frozen.

## Current baseline facts to preserve

These facts are controlled by the active specification and generated-contract flow:

```text
N = 12
L = 256
P = 8
H = 128
F = 15
G = 128
D = L + G = 384
THR2 width = Wmag2 = 56
transport VERSION = 0x0001_0007
DDR telemetry header size = 32 bytes
STATUS payload size = 72 bytes
Revision G UDP no-fragmentation maximum = 1200 bytes
```

Do not repair old documents by editing them until they look current. Keep old documents old. Put current facts in active docs, schemas, generated headers, and implementation files.

## How to import an old document safely

When an old document is found:

1. Decide whether it is active, deprecated Phase 2, or Phase 1 historical material.
2. If active, put it in `docs/specs/` and update `docs/specs/README.md` with filename and SHA-256.
3. If deprecated Phase 2, put it in `legacy/deprecated_phase2_docs/`.
4. If Phase 1, put it in `legacy/phase1/docs/`.
5. Add a short entry to the inventory table below.
6. Run `make check-layout`.
7. Confirm no active filelist references the deprecated document or any source file packaged with it.

## Deprecated-document inventory

Maintain this table manually. Add rows as old files are imported.

| Filename | Location | Deprecated because | Safe uses | Unsafe uses |
| --- | --- | --- | --- | --- |
| `T_RECAP_Phase1_Algorithm.pdf` | `legacy/phase1/docs/` | Phase 1 Haar-only algorithm, not Phase 2 STFT/WOLA | Historical Phase 1 explanation | Phase 2 constants, delay, RTL architecture |
| `Report-1.pdf` | `legacy/phase1/docs/` or `legacy/deprecated_phase2_docs/` | Early report predates current integrated Phase 2 contract | Background and motivation | Current Rev J/G implementation rules |
| `untitled-1.pdf` | `legacy/deprecated_phase2_docs/` if kept | Early report/draft, superseded by active integrated spec | Presentation/report history | Current repo architecture or signoff |
| older Phase 2 drafts | `legacy/deprecated_phase2_docs/` | Superseded by current integrated spec | Traceability only | Generated constants, filelists, HPS/packet behavior |

If the exact destination differs during import, update the table. Do not leave rows ambiguous in the final repository.

## Relationship to generated contracts

Deprecated documents shall not be used as sources for:

```text
spec/generated/core_config.json
spec/generated/csr_map.json
spec/generated/packet_layouts.json
spec/generated/interface_types.json
rtl/include/generated/*.sv
sw/hps/include/generated/*.h
sw/pc_dashboard/generated/*.py
filelists/*.f
```

If an old document contains a useful value, copy the idea into the active schema only after checking it against the active spec. Then regenerate. Do not generate from the old document directly.

## Relationship to build and CI

The root `Makefile` and `.gitignore` are already written so that old Phase 1 root dumps are blocked or ignored at the repository root. This file adds the human explanation for that policy.

Required checks:

```bash
make check-layout
make lint-basic
```

After R1 scripts exist:

```bash
make gen-headers
make check-generated
make rtl-filelist
```

A deprecated document shall not cause these targets to change active generated outputs.

## Review checklist

Before accepting this directory:

```text
[ ] Active spec is in docs/specs/ and documented by docs/specs/README.md.
[ ] Deprecated Phase 2 drafts are not in docs/specs/.
[ ] Phase 1 documents are not treated as Phase 2 active specs.
[ ] Root README contains the D = L + G = 384 warning.
[ ] No old draft is cited as the authority for CSR offsets, packet layouts, filelists, or core constants.
[ ] No old draft is used to justify HPS-side signal processing.
[ ] No old draft is used to start Ethernet/dashboard work before C0.
[ ] make check-layout passes.
```
