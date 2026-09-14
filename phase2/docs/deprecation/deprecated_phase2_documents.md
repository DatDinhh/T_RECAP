# Superseded Phase 2 documents

The active baseline is the [integrated Phase 2 specification](../specs/README.md): Core Revision J, Telemetry Revision G, and Repository Architecture Revision D. Earlier drafts remain useful background but do not define the current implementation.

In particular, older descriptions using `D=L` are superseded. The baseline delay is `D=L+G=384` samples. Phase 1 Haar behavior, including exact zero-threshold losslessness, cannot be carried over to quantized Phase 2 STFT/WOLA arithmetic.

## Keeping history separate

| Material | Location | Use |
| --- | --- | --- |
| Current integrated specification | `docs/specs/t_recap_phase2_integrated_spec.pdf` | Baseline authority |
| Current implementation decisions | `docs/architecture/` | Architecture and explicitly documented extensions |
| Earlier Phase 2 reports/drafts | `legacy/deprecated_phase2_docs/` | Background and design history |
| Phase 1 source and reports | `legacy/phase1/` | Earlier Haar proof of concept |
| Historical C0 revision notes | `docs/bringup/c0_*_v*.md` | Rationale for prior fixes, not current completion claims |

Keep superseded source out of active compilation lists. A historical document must not supply current constants, register offsets, packet layouts, or runtime assumptions. When a design decision changes, update its owning current document instead of relying on a new diary entry to override it.

Names containing `golden` in historical files or reference-package APIs are compatibility terminology. We describe the current software as a reference model and keep source provenance separate from hardware completion.
