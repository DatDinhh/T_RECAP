# T-RECAP

Transform-domain Representation and Energy-aware Computation Accelerator with Controlled Precision.

We are developing T-RECAP as a senior capstone project on the Terasic DE1-SoC. The current work is in [Phase 2](phase2/README.md): fixed-point STFT, threshold masking, WOLA reconstruction, source integration, bounded telemetry, and HPS-to-PC transport/control.

## Current milestone

This is an unfinished architecture and implementation milestone. The source architecture and documented FPGA fit/timing checkpoint are available. Functional verification, matched hardware/Linux deployment, and hardware power/energy measurements remain to be completed.

**No measured energy-saving result is claimed.** Spectral suppression and retained spectral-energy ratios describe the signal representation. The baseline still executes its FFT/IFFT schedule; any power or energy benefit must be established by measurement against a defined baseline.

## Read the project

- [Phase 2 overview and status](phase2/README.md)
- [Eight-plate architecture atlas](phase2/docs/architecture/diagrams/README.md)
- [Architecture PDF](phase2/docs/architecture/diagrams/trecap-architecture-atlas.pdf)
- [Integrated specification](phase2/docs/specs/README.md)
- [FPGA implementation evidence](phase2/docs/results/fpga_implementation.md)
- [Software reference model](phase2/sw/reference_model/README.md)
- [Documentation and build guides](phase2/docs/README.md)

The [Phase 1 demonstration](phase1_demo/) is retained as historical work. Phase 2 contains the current implementation; its software model is an arithmetic reference, not a qualified golden model.

Run Phase 2 commands from its directory. GitHub Actions checks source hygiene, production RTL elaboration and host compilation; it does not execute functional tests or the reference model.
