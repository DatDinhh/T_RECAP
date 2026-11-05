# Baseline PDF page 101

Historical Part III, repository architecture. Printed page 88. [Original PDF page](../../specs/t_recap_phase2_integrated_spec.pdf#page=101).

[Previous](page-100.md) | [Index](../README.md) | [Next](page-102.md)

7. `sw/hps/config/trecap_hps_config.json` exists and documents CSR base, ring addresses, ring size, and UDP ports.

8. legacy/phase1/ contains the old Haar proof-of-concept files, and those files are not part of the Phase 2 root build.

9. The root README.md warns that older Phase 2 drafts are deprecated and that the current baseline uses D = L + G = 384.

10. No verification-specific directory tree is required in this repository revision.

11. filelists/ contains the required generated filelists, and active builds consume those filelists.

12. Generated headers are checked in and make check-generated fails on regeneration drift.

13. `docs/architecture/module_api.md`, `docs/architecture/clock_reset_plan.md`, docs/architecture/ `generated_contracts.md`, and `docs/architecture/coding_style.md` exist.

14. `window_rom.sv` and `twiddle_rom.sv` consume frozen coefficient artifacts. No RTL coefficient generation exists.

15. Common RAM/FIFO wrappers exist under rtl/common/. Core modules do not instantiate board-specific memory IP directly.

16. Top-level build variants exist for core-only, BRAM replay core, core+telemetry, and full DE1-SoC builds.

17. Cut C0 can compile without telemetry, HPS bridge, HPS software, PC dashboard, live audio, ADC, or Platform Designer dependencies.

## 53 Conclusion

Revision D defines a cleaner implementation repository than the previous architecture draft. It keeps verification architecture out of scope, resolves DDR writer ownership, adds a generated sharedheader flow, makes the CSR map normative, freezes baseline interface typedefs, adds source-of-truth filelists, defines generated-file commit policy, adds clock/reset and module API rules, adds Platform Designer generated-artifact policy, adds HPS runtime profiles, defines coefficient ROM and memory wrapper ownership, adds top-level build variants, quarantines legacy Phase 1 code, and removes the remaining consistency issues in the generated software paths, minimum documentation list, and first-scope wording. This is the structure to use before writing real modules. The next step is not to build Ethernet or audio first. The next step is to restructure the repository, add generated constants, generate coefficients/vectors, and then implement the core-only RTL path.
