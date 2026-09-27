# T-RECAP

**Transform-domain Representation and Energy-aware Computation Accelerator with Controlled Precision**

We are building a fixed-point signal-processing system on the Terasic DE1-SoC for our senior capstone project. T-RECAP converts a sample stream into overlapping frequency-domain frames, suppresses selected low-energy bins, and reconstructs a delayed output with weighted overlap-add (WOLA). We use a software reference model to define the arithmetic and an FPGA implementation to realize the stream processing.

Our engineering question is: **how can we make selective spectral suppression deterministic, causal, and observable within the compute and memory limits of an FPGA?** The project brings together custom FFT/IFFT arithmetic, stream scheduling, fixed-point width design, board integration, and a transport path that cannot stall the signal-processing core.

## Project scope

The main deliverable is a DE1-SoC system with deterministic BRAM input replay, configurable suppression threshold, FPGA-owned error metrics, and a PC dashboard connected through HPS DDR and Ethernet. LINE-IN is the primary live-source extension. The LTC2308 ADC is an independent optional source and does not block the main deliverable.

We keep the following responsibilities separate:

| Component | Responsibility |
| --- | --- |
| FPGA core | Windowing, FFT, Hermitian canonicalization, threshold mask, IFFT, WOLA, delayed-reference error metrics |
| FPGA telemetry and HPS bridge | Best-effort observation, packet formatting, control registers, reserved-DDR ring writer |
| HPS software | DDR record consumption, UDP transport, command handling |
| PC dashboard | Waveform/error views, spectrum history, counters, control results, capture playback |
| Software reference model | Finite-stream arithmetic, coefficients, input vectors, expected-output artifacts, offline analysis |

```text
BRAM replay / LINE-IN / ADC / diagnostic source
    -> source selection and normalization
    -> FPGA STFT/WOLA core
    -> valid-only telemetry taps
    -> packet FIFO -> DDR ring -> HPS UDP -> PC dashboard

PC controls -> HPS command bridge -> FPGA CSRs -> safe-boundary updates
```

Explore the [architecture atlas](docs/architecture/diagrams/README.md) for eight detailed diagrams, an interactive viewer, and downloadable SVG, PNG and PDF versions.

The core has a separate source composition without HPS, Ethernet, or the dashboard. Telemetry is allowed to drop data under congestion and reports those drops; it cannot propagate backpressure into the core.

## What the energy and precision terms mean

The baseline uses fixed arithmetic widths and fractional precision `F = 15`. `THR2` controls which eligible spectral bins are suppressed; it does not change the arithmetic widths at runtime. The dashboard's retained spectral-energy and suppression ratios describe the signal representation.

Suppressed bins are a **potential downstream-work reduction metric**, not a measurement of electrical energy saved. The baseline still performs its FFT/IFFT schedule. A power-saving claim needs a concrete mechanism that reduces switching activity or executed work, plus a separate energy study. The optional IFFT operand-isolation experiment retains the schedule and is documented separately from the production baseline. We also do not claim general-purpose denoising: usefulness depends on the signal and the chosen threshold.

## Baseline design

| Quantity | Value |
| --- | --- |
| External sample width | 12-bit signed |
| FFT length / hop | 256 / 128 samples |
| Fractional precision | 15 bits |
| Scheduling cushion | 128 samples |
| Causal delay | `D = L + G = 384` samples |
| Fabric clock | 50 MHz |
| Nominal BRAM / LINE-IN rate | 48 ksample/s |
| Nominal continuous ADC rate | 100 ksample/s |
| Protected bins | DC protected; Nyquist unprotected |
| Transform | Custom radix-2 DIT; bit-reversed input, natural-order output |

The delay corresponds to 8 ms at 48 ksample/s or 3.84 ms at 100 ksample/s. These are sample-domain design values, not measured analog or network latency. Executable constants come from the [shared contracts](spec/generated/core_config.json), not this table.

## Current status

**This project is still in progress.** Selected reference/RTL verification campaigns, FPGA-only board-power studies, and a resident-input ARM/FPGA timing comparison have recorded results. Full-system verification, integrated HPS/Linux transport acceptance, end-to-end offload comparisons, and a qualified energy-efficiency improvement remain open.

We have source implementations for the reference model, FPGA core, source adapters, telemetry, HPS transport/control, dashboard, and board wrappers. The repository also includes a pinned integrated specification and explicit build profiles.

The baseline architecture is now implemented in source: registered FFT/IFFT arithmetic, synchronous frame/history/OLA memories, RAM-backed telemetry, source continuity and recovery, physical I/O timing allocations, and a Linux driver for noncached DDR and codec-mux ownership. The [architecture design](docs/architecture/architecture_design.md) derives an 18000-clock frame allocation and records memory/transport budgets; the [implementation status](docs/architecture/architecture_implementation.md) separates source completion from tool and board results.

Quartus Prime **Lite 20.1.1 Build 720** rebuilt the corrected RTL, generated the real Platform Designer system and completed placement/routing for the BRAM profile on the Cyclone V 5CSEMA5F31C6. The fit uses **21,220 of 32,070 ALMs (66%)**. All **209 board pin comparisons** and the required fitted timing gate pass at all four operating conditions. The fresh `.sof` was successfully programmed into the connected DE1-SoC FPGA through JTAG on 15 September 2026, with zero programmer errors or warnings. See the [Lite build and deployment result](docs/results/de1soc_lite_bram_20260915.md) and [public result JSON](docs/results/de1soc_lite_bram_20260915.json).

This establishes volatile FPGA configuration. Deployment of the integrated HPS transport application, BRAM-to-DDR/UDP operation and full-system physical acceptance remain pending. A separate RAM-only HPS/Linux boot and CPU benchmark subsequently passed, as documented below.

On 25 September 2026, a separate [FPGA-only measurement image](docs/bringup/fpga_measurement.md) completed twelve nonzero replay trials on the board. Its checker compared **301,989,888 output samples with zero mismatches and zero fault flags**. The same-image threshold comparison measured about **6.5 W at the board DC input**, with a mean masked-minus-dense active-power difference of **-1.897 mW** across six pairs. This small difference does **not** establish a calibrated energy-saving result; the complete-batch energy timing bounds include zero difference. The [measurement report, plots and portable data](docs/results/board_power_20260925/README.md) document the boundary, output-quality tradeoff and uncertainty. The [earlier Standard Edition implementation](docs/results/fpga_implementation.md) is preserved as a historical checkpoint.

A subsequent [IFFT operand-isolation experiment](docs/results/ifft_zero_isolation_20260925/README.md) adds an optional exact-zero datapath hold, with independent RTL checks, fitted timing/resource evidence and a same-image board comparison. Its [reproducible source overlay](experiments/ifft_zero_isolation/README.md) is kept separate from the production baseline. The report distinguishes workload-specific zero opportunities, measured electrical results, timing uncertainty and added implementation cost.

We call the software package a **reference model**. Historical executable/package names containing `golden` remain for compatibility and do not indicate a signed-off implementation.

The [physical ARM/HPS benchmark](docs/results/hps_cpu_benchmark_20260925/README.md) now provides a matched resident-input timing comparison. On one Cortex-A9 core reporting 925 MHz, 30 warmed trials per condition gave median complete-record times of **2.3715 ms dense** and **2.3224 ms masked**. The earlier admitted FPGA run took **88,524 clocks, or 1.77048 ms at nominal 50 MHz**, for the same 1,024 inputs, nine frames and 1,536 outputs. These service-time ratios are **1.339×** and **1.312×**. All timed CPU outputs matched their reference. The [separate CPU source and qualification package](experiments/hps_cpu_benchmark/README.md) preserves the baseline reference model and RTL.

The [benchmark and evaluation plan](docs/evaluation/benchmark_plan.md) separates CPU offload, processing acceleration, and electrical energy efficiency. The CPU datapath timer excludes reference checking and metrics that remain active in the FPGA measurement image. Neither timer includes a complete HPS-to-FPGA transfer path. The result therefore supports this bounded processing comparison; end-to-end speedup and electrical energy savings remain unqualified.

The [verification design](docs/verification/README.md) now defines the DUT environments, independent reference qualification, test/assertion catalogs, requirement traceability and signoff evidence. The [first executed campaign](docs/results/verification_baseline_20260915.md) records independent reference qualification, arithmetic checks and four passing finite-core replay cases, including stalls. It also describes two functional RTL defects and one stale assertion corrected during verification. The [finite-boundary campaign](docs/results/verification_boundaries_20260915.md) adds 80 passing cases across 20 input lengths, two fixed thresholds and output stalls, plus a passing repeat of the four baseline cases. Full requirement closure remains open.

## Getting started

Start with the [documentation guide](docs/README.md), [integrated specification](docs/specs/README.md), and [architecture design](docs/architecture/architecture_design.md).

The root Makefile uses Bash and exposes the component build targets. Python 3.12 is our repository-maintenance and CI baseline; the reference-model and dashboard packages retain a Python 3.10 minimum. The reference model requires C++20 and CMake 3.24 or newer; the HPS application targets Linux. Board generation and synthesis require the supported Intel FPGA toolchain described in the [platform guide](docs/bringup/quartus_programming.md).

To build the software reference model without hardware tools or test targets:

```bash
cmake --preset host
cmake --build --preset host
```

The preset selects a Release build. The [build guide](docs/architecture/build_order.md) lists executable locations for single-configuration and Visual Studio generators. To regenerate the integrated interface headers and RTL source lists:

```bash
make help
make gen-headers
make rtl-filelist
```

See the [reference-model README](sw/reference_model/README.md) for artifact generation and offline analysis. On the target HPS/Linux environment, `make hps-build` builds the transport application. The [build guide](docs/architecture/build_order.md) explains the FPGA and platform steps.

To start the dashboard after installing its package dependencies and configuring the direct Ethernet link:

```bash
python -m pip install -e "sw/pc_dashboard[gui]"
python sw/pc_dashboard/scripts/run_dashboard.py --config sw/pc_dashboard/configs/dashboard_direct_link.json
```

For offline capture playback, add `--capture-read <capture-file> --no-live-controls` and omit pre-run command options. Network addresses and board runtime setup are described in the [dashboard guide](docs/bringup/pc_dashboard_bringup.md) and [HPS guide](docs/bringup/hps_ethernet_bringup.md).

## Repository map

| Path | Contents |
| --- | --- |
| `rtl/` | Core arithmetic, source integration, telemetry, HPS bridge, board wrappers |
| `sw/reference_model/` | C++ reference library and artifact/analysis tools |
| `sw/hps/` | Linux transport and command application |
| `sw/pc_dashboard/` | Python dashboard and packet/control clients |
| `spec/`, `config/` | Shared arithmetic/interface contracts and runtime profiles |
| `platform/`, `constraints/` | DE1-SoC Platform Designer sources, address maps, timing/pin constraints |
| `artifacts/` | Coefficients, input vectors, reference outputs, manifests |
| `docs/` | Specification, design decisions, integration guides, project history |
| `legacy/` | Historical Phase 1 material excluded from active Phase 2 builds |

The included [specification](docs/specs/t_recap_phase2_integrated_spec.pdf) is the algorithm/interface authority. [Contributing](CONTRIBUTING.md) explains ownership, generated files, and how we record design changes.
