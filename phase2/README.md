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

Suppressed bins are a **potential downstream-work reduction metric**, not a measurement of electrical energy saved. The baseline still performs its FFT/IFFT schedule. A power-saving claim would need a concrete downstream stage that skips work and a separate energy study. We keep that extension outside the main deliverable. We also do not claim general-purpose denoising: usefulness depends on the signal and the chosen threshold.

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

**This is an unfinished architecture and implementation milestone.** Functional verification and hardware power/energy measurements remain pending. We do not claim measured energy savings.

We have source implementations for the reference model, FPGA core, source adapters, telemetry, HPS transport/control, dashboard, and board wrappers. The repository also includes a pinned integrated specification and explicit build profiles.

The baseline architecture is now implemented in source: registered FFT/IFFT arithmetic, synchronous frame/history/OLA memories, RAM-backed telemetry, source continuity and recovery, physical I/O timing allocations, and a Linux driver for noncached DDR and codec-mux ownership. The [architecture design](docs/architecture/architecture_design.md) derives an 18000-clock frame allocation and records memory/transport budgets; the [implementation status](docs/architecture/architecture_implementation.md) separates source completion from tool and board results.

The native Quartus 20.1.1 build generated the real Platform Designer system and completed placement/routing for the BRAM profile on the Cyclone V 5CSEMA5F31C6. The latest fit uses **20,280 of 32,070 ALMs (63%)**. **All 209 board pin comparisons and the fitted timing gate pass**, including the 50 MHz fabric, DDR, CDC and ADC route checks at all four operating conditions. See the [FPGA implementation results](docs/results/fpga_implementation.md) and [public result JSON](docs/results/de1soc_bram_native12.json) for values and provenance.

The latest Assembler run produced no programmable `.sof` in Standard Edition Evaluation Mode, so the build remains incomplete for programming. The matched kernel/DTB/module build and physical board operation remain pending. These implementation results do not establish functional correctness; verification architecture and execution remain later project work.

We call the software package a **reference model**. Historical executable/package names containing `golden` remain for compatibility and do not indicate a signed-off implementation.

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
