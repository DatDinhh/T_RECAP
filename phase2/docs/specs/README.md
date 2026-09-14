# Integrated specification

We include the Phase 2 specification at [t_recap_phase2_integrated_spec.pdf](t_recap_phase2_integrated_spec.pdf). This is the canonical repository copy of the integrated algorithm, telemetry, and repository-architecture document.

| Field | Value |
| --- | --- |
| Project | T-RECAP: Transform-domain Representation and Energy-aware Computation Accelerator with Controlled Precision |
| Team in the document | Sigma Force, Team #2 |
| Document date | May 4, 2026 |
| Algorithm revision | Core Revision J |
| Telemetry revision | Telemetry Revision G |
| Repository architecture revision | Revision D |
| Repository filename | `t_recap_phase2_integrated_spec.pdf` |
| SHA-256 | `7de45d2764bacc090d2837501382c82a7f081884b7c929b8b4aa4b536bff2aaf` |

The file contains three parts: the core algorithm and artifact contract; Ethernet/HPS DDR telemetry and control; and the implementation repository architecture. The hash identifies this exact document. It does not certify that the implementation satisfies it.

## Reading the baseline

The fixed baseline uses `N=12`, `L=256`, `H=128`, `F=15`, `G=128`, and `D=L+G=384`. Thresholds are in the full-width unsigned magnitude-squared domain. The finite reference stream includes the specified full tail. Older drafts using `D=L` are superseded.

The core performs the STFT/WOLA computation in the FPGA. HPS and PC software provide transport, control, and observation. Suppression and retained spectral-energy metrics characterize the representation; they do not establish electrical power savings. Runtime threshold control does not imply runtime precision scaling.

## Document precedence

1. This integrated PDF defines the baseline algorithm and interfaces.
2. Machine-readable contracts in `spec/generated/` and `spec/schemas/` express executable constants and layouts.
3. Generated SV/C/Python files provide those contracts to implementations.
4. `docs/architecture/` records implementation decisions and explicitly identified extensions.
5. `docs/bringup/` records platform and runtime procedures.

When the PDF and source disagree, resolve the discrepancy explicitly. Do not silently edit a generated consumer or reinterpret an older draft. Later extensions, including the version-2 command/result protocol, must state their relationship to the baseline and preserve the documented version behavior.

## Reference-model terminology

The software source is maintained at `sw/reference_model/`; root expected outputs are under `artifacts/reference_outputs/`. Historical names such as `trecap_golden`, `phase2_golden_model`, `make golden`, and an internal `artifacts/golden/` path are compatibility names within that package.

The supplied reference source has been reconciled into the current repository. Its manifests track the checked-in snapshot and promoted files. This does not establish provenance for any historical archive or turn the package into final hardware signoff authority. Changes to arithmetic, coefficients, inputs, or output generation must remain traceable to the corresponding source and contract revision.

## Updating the specification

Retain one canonical active PDF here. For a revised document, update its revision identity, SHA-256, related machine-readable contracts, and affected implementation notes together. Record compatibility changes in the project changelog. Keep superseded documents under `legacy/` with a clear historical label, rather than alongside the active PDF without explanation.
