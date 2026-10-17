# Documentation guide

Start with the [main project README](https://github.com/DatDinhh/T_RECAP#readme) for the objective, current architecture, spectrograms, workload results and verification visuals. The current verified application is the finite-file **TSH2** TCP/MMIO profile. The broader DDR-ring/UDP/live-source architecture is retained as a separate historical design.

## Current TSH2 application and verification

| Document | Purpose |
|---|---|
| [Current Phase 2 entry point](../README.md) | Profile responsibilities, source map and reproducible checks |
| [Current TSH2 architecture atlas](architecture/tsh2/README.md) | Eight views of the finite-file datapath, storage, control, transport and verification boundaries |
| [Overview results and figures](project_overview/README.md) | Physical audio comparisons, host timing boundaries, claims audit and provenance |
| [Verification portfolio](../verification/README.md) | Methodology, executed evidence and sign-off limits |
| [Academic report and LaTeX](verification/portfolio/README.md) | Sixteen-page report with editable source |
| [Portable seeded RTL package](../verification/tsh2/README.md) | Admitted synthetic fixtures, scoreboards and simulator runner |
| [Physical and RTL evidence ledger](results/verification_20261017/README.md) | 58 board epochs, coverage, source binding and native VCDs |
| [TSH2 source archive](../profiles/tsh2/README.md) | Finite service, adapter, consumer, monitor, visualizer and reproduction boundaries |

The remaining sections document shared components and the original broad Phase 2 architecture. Their deployment milestones and open integration items belong to those named profiles; they do not describe the finite TCP/MMIO service as DDR/UDP or establish live microphone acceptance.

## Shared reference and original architecture

| Document | Purpose |
| --- | --- |
| [Project overview](../README.md) | Engineering question, contribution, scope, current status |
| [Specification index](specs/README.md) | Included normative PDF, revision identity, document precedence |
| [Architecture design](architecture/architecture_design.md) | Datapath choices, scheduling, capacity budgets, design boundaries |
| [Historical architecture atlas, 2026-09-14](architecture/diagrams/README.md) | Preserved broad DDR/UDP architecture snapshot; separate from current TSH2 verification |
| [Implementation plan](architecture/architecture_implementation.md) | Implemented deliverables, build dependencies, remaining platform results |
| [Repository ownership](architecture/repo_architecture.md) | File ownership, source/generated distinctions, dependency rules |
| [Build guide](architecture/build_order.md) | Tools and component build sequence |
| [Verification design](verification/README.md) | Environments, reference qualification, test/assertion catalogs, requirements, coverage and signoff rules |
| [Verification execution plan](verification/execution_plan.md) | Specification readiness, ordered milestones, dependencies and the first complete core replay |
| [First verification results](results/verification_baseline_20260915.md) | Executed software/RTL cases, corrected defects, evidence identities and remaining scope |
| [Finite-boundary verification](results/verification_boundaries_20260915.md) | 80 executed length/threshold/stall cases, baseline regression, checker qualification and exact tail accounting |
| [Lite FPGA deployment](results/de1soc_lite_bram_20260915.md) | Corrected-source fit, four-corner timing, 209-pin check and successful volatile JTAG configuration |
| [FPGA-only board-power results](results/board_power_20260925/README.md) | Twelve checked nonzero board trials, paired electrical measurements, plots, portable data and limits |
| [IFFT operand-isolation study](results/ifft_zero_isolation_20260925/README.md) | Per-stage zero profiles, exact RTL comparison, fitted implementation cost and same-image electrical measurements |
| [Physical ARM/HPS timing comparison](results/hps_cpu_benchmark_20260925/README.md) | Exact-output CPU qualification, 60 physical timing trials, historical FPGA comparison, plots and reproducible data |
| [Benchmark and evaluation plan](evaluation/benchmark_plan.md) | Verification milestones, fair CPU/FPGA comparisons, and energy-study decision gates |

## Detailed design references

- [Module inventory](architecture/module_inventory.md) and [module APIs](architecture/module_api.md): block-level responsibilities and ports.
- [Interface contracts](architecture/interface_contracts.md): samples, frames, telemetry records, commands, and safe-boundary rules.
- [Generated contracts](architecture/generated_contracts.md) and [header flow](architecture/generated_header_flow.md): shared JSON and SV/C/Python outputs.
- [Clock/reset plan](architecture/clock_reset_plan.md) and [CDC plan](architecture/cdc_plan.md): domain ownership and crossings.
- [Source/core integration](architecture/source_core_integration.md) and [core/telemetry composition](architecture/core_telemetry_composition.md): top-level ownership without duplicate cores.
- [Memory map](architecture/memory_map.md), [DDR ring ownership](architecture/de1soc_ddr_ring_ownership.md), and [CSR adapter](architecture/avalon_mm_csr_adapter.md): register and transport memory contracts.
- [Platform Designer boundary](architecture/platform_designer_wrapper.md) and [board top](architecture/de1soc_board_top_integration.md): generated-system and physical-board integration.
- [HPS transport](architecture/de1soc_hps_transport.md) and [command path](architecture/de1soc_command_path.md): software lifecycle, forwarding, and control results.

The [reference-model documentation](../sw/reference_model/README.md) explains arithmetic, finite streams, coefficients, and offline artifacts. Its finite input/output model and the FPGA's continuous stream interfaces serve different purposes; neither is a substitute for the other's design contract.

- [Transform microarchitecture](architecture/transform_microarchitecture.md) and [storage schedule](architecture/storage_schedule.md): RAM ports, arithmetic pipeline and cycle budgets.
- [Physical timing](architecture/physical_timing.md): codec/ADC I/O, CDC routing and external timing allocations.
- [Source health](architecture/source_health.md): discontinuity detection, coherent counters and explicit recovery.
- [Platform codec grant](architecture/platform_grant.md): dedicated HPS GPIO48 ownership and the FPGA-visible grant register.
- [Linux source baseline](../platform/de1soc/linux/README.md): static board DTS, noncached ring driver, GPIO ownership and build/install recipe.

## Board and application guides

| Guide | Topic |
| --- | --- |
| [Board connections](bringup/de1_soc_connections.md) | Physical connections and signal ownership |
| [FPGA-only power measurement](bringup/fpga_measurement.md) | Standalone measurement image, exact output checking, synchronized logger and repeatable campaign |
| [Quartus/platform setup](bringup/quartus_programming.md) | Project generation and board programming workflow |
| [DDR ring](bringup/ddr_ring_bringup.md) | Reserved memory and producer/consumer lifecycle |
| [HPS Ethernet](bringup/hps_ethernet_bringup.md) | Direct-link networking and runtime configuration |
| [PC dashboard](bringup/pc_dashboard_bringup.md) | Display, command controls, capture and playback |
| [LINE-IN](bringup/audio_linein_bringup.md) | WM8731 clock, control, data, and CDC path |
| [ADC](bringup/adc_bringup.md) | Optional LTC2308 source and diagnostic operation |
| [BRAM replay](architecture/de1soc_bram_replay_path.md) | Deterministic source, full-tail completion, transport boundary |

These guides describe implementation and operational procedures. They do not by themselves establish that the procedures have passed on a board. Full functional and system signoff remain open. The [Lite deployment result](results/de1soc_lite_bram_20260915.md) records the integrated fitted image and FPGA configuration; the [FPGA-only measurement result](results/board_power_20260925/README.md) records a separate checked core workload and its physical DC-input measurements. [Older implementation results](results/fpga_implementation.md) remain historical.

## History

The [deprecation guide](deprecation/deprecated_phase2_documents.md) explains superseded Phase 2 documents; [Phase 1 notes](deprecation/phase1_quarantine_notes.md) explain the earlier Haar design. The `c0_*_v*.md` notes in `bringup/` retain the rationale for earlier control, tail, arithmetic-width, and delayed-reference changes. Historical revision labels identify when a change was introduced, not the maturity of the current repository.
