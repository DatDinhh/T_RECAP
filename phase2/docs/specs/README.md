# T-RECAP Phase 2 specifications

File class: **[1] hand-written repository documentation**.

This directory is reserved for frozen human-readable specification documents
for the T-RECAP Phase 2 implementation repository. The integrated PDF is not
bundled in the current source package. This is not a generated-output folder
and it is not a place for legacy Phase 1 drafts.

## Expected active specification

The historical R0 upload was named:

```text
doneeeeeeeeee.pdf
```

After an independently verified copy is supplied, use:

```text
t_recap_phase2_integrated_spec.pdf
```

Until that file exists and its hash is verified, this directory contains no
active PDF authority. Use exactly one active copy after import; do not keep both
names unless there is a specific traceability reason.

If the file is renamed, record the rename explicitly:

```text
t_recap_phase2_integrated_spec.pdf  # renamed from doneeeeeeeeee.pdf
```

The file name `T_RECAP_Phase2_Integrated_RevJ_RevG.pdf` is not an uploaded file
name. Do not use that name unless the team deliberately renames the PDF to it.

Known uploaded-file SHA-256 for the current PDF received during R0 staging:

```text
7de45d2764bacc090d2837501382c82a7f081884b7c929b8b4aa4b536bff2aaf  doneeeeeeeeee.pdf
```

Recompute this value after copying the PDF into the repository. If the hash does
not match, treat it as a different document and update this README deliberately.

## Active-spec inventory

Keep this table current whenever a spec PDF is added, renamed, replaced, or deprecated.

| Logical document | Repository filename | Original filename | Status | Authority |
| --- | --- | --- | --- | --- |
| Integrated Phase 2 implementation contract | `t_recap_phase2_integrated_spec.pdf` | `doneeeeeeeeee.pdf` | not bundled; independently verified import required | Core Revision J, Telemetry Revision G, Repository Architecture Revision D |

If the raw uploaded name is kept instead of renamed, change the repository filename column to
`doneeeeeeeeee.pdf`. The root `README.md` and this file must agree on the active filename.

## Spec identity

The active PDF is the integrated Phase 2 implementation contract for:

```text
T-RECAP: Transform-domain Representation and Energy-aware Computation
Accelerator with Controlled Precision

Phase 2 Algorithm, Ethernet/HPS Telemetry, and Repository Architecture
Specification
```

Project metadata captured by the active PDF:

```text
Team:            Sigma Force, Team #2
Platform target: DE1-SoC FPGA fabric, HPS DDR, HPS Ethernet
Spec date:        May 4, 2026
```

The active PDF has three normative parts:

```text
Part I   - Core Algorithm and Signoff Contract
Part II  - Ethernet/HPS DDR Telemetry and Control Architecture
Part III - Core Implementation Repository Architecture
```

The HPS and PC layers are transport, observability, and control infrastructure.
They do not replace BRAM replay signoff and they do not perform the STFT/WOLA
core computation.

## Authority order

Use this precedence when files disagree:

```text
1. Active integrated PDF in docs/specs/
2. Source-of-truth machine-readable schemas under spec/generated/ and spec/schemas/
3. Generated SV/C/Python headers emitted from those schemas
4. docs/architecture/ implementation notes
5. docs/bringup/ board and runtime notes
6. comments inside implementation source files
```

A document in `docs/architecture/`, `docs/bringup/`, `sw/`, `rtl/`, or `legacy/`
may clarify implementation details, but it cannot override the active spec.

## What belongs here

Allowed files:

```text
README.md                                             [1]
doneeeeeeeeee.pdf                                    [1]  # temporary uploaded name
# or
t_recap_phase2_integrated_spec.pdf                   [1]  # preferred cleaned name
```

Optional future files:

```text
SPEC_CHANGELOG.md                                    [1]
SPEC_IMPORT_NOTES.md                                 [1]
```

Rules:

1. Keep only frozen specification documents here.
2. Keep filenames deterministic and readable.
3. Prefer lowercase `snake_case` for repository-owned filenames.
4. Keep raw uploaded filenames only when traceability matters.
5. Record every rename or replacement in this README or `SPEC_IMPORT_NOTES.md`.
6. Do not put generated headers, schemas, test vectors, or telemetry captures here.

## What does not belong here

Do not put these in `docs/specs/`:

```text
Phase 1 Haar RTL files
Phase 1 ModelSim/Questa runners
Phase 1 golden-model outputs
old algorithm-report drafts used only as history
generated SV/C/Python headers
spec/generated/*.json machine-readable source files
filelists/*.f generated compile-order files
artifacts/**/*.memh
artifacts/**/*.csv
artifacts/**/*.json
runs/
out/
build/
```

Phase 1 and deprecated Phase 2 materials belong under:

```text
legacy/phase1/
docs/deprecation/
legacy/deprecated_phase2_docs/
```

They must not be compiled into the Phase 2 root build.

## Naming policy

Use this naming style for repository-owned spec files:

```text
t_recap_phase2_integrated_spec.pdf
t_recap_phase2_integrated_spec_rYYYYMMDD.pdf
t_recap_phase2_spec_changelog.md
```

Do not encode guessed revision names into the filename. For example, do not invent
`RevJ_RevG` in a filename unless the team explicitly approves that exact name.
The revision identity belongs in the document metadata and this README.

## Reference model naming correction

The uploaded ZIP package is a **reference model package**, not the final golden
signoff authority. It should be imported under:

```text
sw/reference_model/
```

Reference-model outputs should be staged under:

```text
artifacts/reference_outputs/
```

Use final `golden` naming only after the algorithm release, artifacts, hashes,
RTL simulation match, and BRAM replay signoff are frozen.

The spec may still use `sw/golden/` or `artifacts/golden/` wording because it
is describing the final authority model. During current implementation, this
repository uses `reference_model` terminology to avoid overstating the maturity
of the uploaded ZIP.

## Spec-controlled facts that must not drift

The following are examples of facts controlled by the active spec and later by
machine-readable generated contracts:

```text
N = 12
L = 256
P = 8
H = 128
F = 15
G = 128
D = L + G = 384
transport VERSION = 0x0001_0007
STATUS payload size = 72 bytes
DDR telemetry header size = 32 bytes
Revision G UDP maximum = 1200 bytes per telemetry record datagram
```

Do not duplicate these constants by hand in RTL, HPS C, or Python dashboard code.
They must flow through `spec/generated/`, generator scripts, and checked-in
generated headers.

## Relationship to existing root files

This README is written to match the R0 root infrastructure:

```text
README.md
Makefile
CMakeLists.txt
.gitignore
.editorconfig
.clang-format
.pre-commit-config.yaml
```

Expected behavior:

1. `README.md` points to the same active spec filename recorded here.
2. `Makefile` target `check-layout` requires `docs/specs/` to exist.
3. `Makefile` target `lint-basic` may check basic Markdown hygiene.
4. `make check-generated` and `make rtl-filelist` become authoritative after R1.
5. `.pre-commit-config.yaml` should allow committed PDFs under `docs/specs/` but
   should not allow generated files to be hand-edited.
6. `.gitignore` should not hide the active spec PDF once intentionally added.

## Change-control procedure

When the active specification changes:

1. Add the new PDF with a deterministic filename.
2. Compute and record its SHA-256.
3. Update the active-spec table in this README.
4. Update the root `README.md` current-authority section.
5. Move older replaced specs or notes to `docs/deprecation/` or
   `legacy/deprecated_phase2_docs/`.
6. If constants, CSRs, packet layouts, payload sizes, source modes, or interface
   structs changed, update `spec/generated/` and `spec/schemas/`.
7. Regenerate headers and filelists after R1.
8. Run the repo hygiene checks.

Expected commands after the relevant scripts exist:

```bash
make check-layout
make lint-basic
make gen-headers
make check-generated
make rtl-filelist
```

For R0, only the skeleton-safe targets are expected to work.

## R0 import checklist

Use this checklist when creating the first real repository checkout:

```text
[ ] docs/specs/ exists.
[ ] docs/specs/README.md exists and is committed.
[ ] The active PDF is copied into docs/specs/.
[ ] The active PDF filename matches the root README current-authority path.
[ ] The active PDF SHA-256 is recorded or intentionally marked as pending.
[ ] No old Phase 1 report is treated as active Phase 2 spec.
[ ] No generated files are stored in docs/specs/.
[ ] No implementation code is stored in docs/specs/.
[ ] make check-layout passes after the skeleton exists.
```

## Practical import command

From a clean repository root:

```bash
mkdir -p docs/specs
cp /path/to/doneeeeeeeeee.pdf docs/specs/t_recap_phase2_integrated_spec.pdf
sha256sum docs/specs/t_recap_phase2_integrated_spec.pdf
make check-layout
```

Then update this README if the hash or active filename differs from the R0 staging
record above.
