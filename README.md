# T-RECAP

Transform-domain Representation and Energy-aware Computation Accelerator with Controlled Precision.

We are developing T-RECAP as a senior capstone project on the Terasic DE1-SoC. The current work is in [Phase 2](phase2/README.md): fixed-point FFT, a tunable spectral threshold, IFFT/WOLA reconstruction, source integration, bounded telemetry, and HPS-to-PC transport/control.

## Latest: design verification portfolio

The registered TSH2 finite-file profile now has a [design verification portfolio](phase2/verification/README.md), including a LaTeX-authored report, editable source, a portable seeded SystemVerilog regression, checker negative controls, source/fixture hashes, an observed coverage ledger and sanitized physical-board evidence. The campaign records 14 fresh RTL suites and 58 checked physical epochs. Read the report for the exact scope, reused evidence and remaining sign-off gaps.

- [Report, LaTeX source and build instructions](phase2/docs/verification/portfolio/README.md)
- [Run the portable verification package](phase2/verification/tsh2/README.md)
- [Inspect the 58-case public evidence ledger](phase2/docs/results/verification_20261017/README.md)
- [Active TSH2 profile and local visualizer source](phase2/profiles/tsh2/README.md)
- [Separate recorded web demo repository](https://github.com/DatDinhh/trecap-spectral-studio)

GitHub Actions checks source hygiene, RTL elaboration, reference functional tests, portable checker qualification and public evidence integrity. Licensed simulator runs and physical hardware measurements are recorded separately. This is a bounded verification result, not a claim of full production sign-off, energy savings or AI acceleration.

## Earlier Phase 2 milestone

The source architecture, FPGA fit/timing checkpoint, selected reference/RTL verification campaigns, and board measurements are available. This earlier milestone predates the TSH2 finite-file integration above; broad full-system acceptance remains open.

- [Finite-core verification](phase2/docs/results/verification_boundaries_20260915.md) records 80 passing boundary cases and the baseline regression.
- [Board-power measurements](phase2/docs/results/board_power_20260925/README.md) record twelve FPGA-only trials, 301,989,888 checked output samples and zero mismatches. The observed threshold-dependent power difference does **not** establish energy savings.
- [Resident-input HPS/FPGA timing](phase2/docs/results/hps_cpu_benchmark_20260925/README.md) records CPU/FPGA service-time ratios of 1.339x dense and 1.312x masked for one finite workload. The timers have disclosed checking/metrics differences and exclude the complete HPS-to-FPGA transfer path; this is not an end-to-end speedup claim.
- The optional [IFFT operand-isolation experiment](phase2/experiments/ifft_zero_isolation/README.md) and its [measurement report](phase2/docs/results/ifft_zero_isolation_20260925/README.md) remain separate from the production baseline.

**No qualified energy-saving result is claimed.** Spectral suppression and retained spectral-energy ratios describe the signal representation. The baseline still executes its FFT/IFFT schedule; downstream workload benefits require a consumer that actually avoids work and a matching measurement.

## Read the project

- [Phase 2 overview and status](phase2/README.md)
- [Eight-plate architecture atlas](phase2/docs/architecture/diagrams/README.md)
- [Architecture PDF](phase2/docs/architecture/diagrams/trecap-architecture-atlas.pdf)
- [Integrated specification](phase2/docs/specs/README.md)
- [FPGA implementation and deployment evidence](phase2/docs/results/de1soc_lite_bram_20260915.md)
- [Software reference model](phase2/sw/reference_model/README.md)
- [Documentation and build guides](phase2/docs/README.md)
- [Repository maintenance and publication](phase2/docs/repository_maintenance.md)

The [Phase 1 demonstration](phase1_demo/) is retained as historical work. Phase 2 contains the current implementation; its software model is an arithmetic reference, not a universally qualified golden model.

Run Phase 2 commands from its directory. The current CI runs reference functional tests as well as source checks; it does not run the licensed RTL campaigns or deploy to hardware. Published results identify their own measurement scope and retained evidence.
