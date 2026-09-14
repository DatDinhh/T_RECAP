# Repository architecture

We keep one Phase 2 implementation tree with a reusable software reference model and explicit hardware/software boundaries. The [integrated specification](../specs/README.md) defines the baseline; this document describes ownership in the current repository.

## Directory ownership

| Directory | Owner and responsibility |
| --- | --- |
| `rtl/core/`, `rtl/fft/` | Fixed-point STFT/WOLA computation, frame state, mathematical metrics |
| `rtl/common/`, `rtl/interfaces/` | Reusable storage/control primitives and typed interfaces |
| `rtl/sources/` | BRAM, audio, ADC, and diagnostic normalization/admission |
| `rtl/telemetry/` | Valid-only taps, packet formation, scheduling, FIFO/drop policy |
| `rtl/hps_bridge/` | CSR adapter/bank, command commits, record builder, DDR writer and pointers |
| `rtl/top/` | Pin-independent compositions and source/core ownership |
| `rtl/platform/de1soc/` | Physical board top, codec/ADC control, clocks, resets, platform wrapper |
| `sw/reference_model/` | C++ arithmetic library and reference-artifact tools |
| `sw/hps/` | Linux DDR consumer, UDP sender, command lifecycle |
| `sw/pc_dashboard/` | Packet parsing, presentation, capture, command client |
| `spec/` | Arithmetic/interface source contracts and schemas |
| `config/` | Board decisions, build profiles, telemetry/runtime presets |
| `platform/de1soc/`, `constraints/de1soc/` | Platform Designer, address map, Linux memory reservation, pin/timing constraints |
| `filelists/` | Generated source lists consumed by RTL and synthesis builds |
| `artifacts/` | Coefficients, inputs, expected outputs, manifests, optional capture data |
| `docs/` | Specification, architecture, integration procedures, history |
| `legacy/` | Historical material outside active Phase 2 dependency lists |
| `build/`, `runs/`, `out/` | Local generated work, excluded from source distribution |

## Source and generated files

Existing documents use these file classes:

- `[0]`: reference-model source or reference-generated artifacts.
- `[1]`: hand-written project source, documentation, or configuration.
- `[2]`: generated output, owned by its generator.

A directory named `generated/` is not enough to determine ownership. Some JSON files under `spec/generated/` are input contracts; emitted headers and manifests are outputs. The [generated-contract guide](generated_contracts.md) identifies those roles.

Root `scripts/gen_headers.py` emits the shared SV, HPS C, and dashboard Python constants. `scripts/gen_filelists.py` emits the active compilation order. The reference model owns its arithmetic configuration flow and exports the source snapshot used by the integrated build. Consumers must not maintain independent executable copies of CSR offsets, packet fields, or baseline arithmetic constants.

## Dependency boundaries

The mathematical core builds independently of the platform and transports. HPS and PC code never compute the FPGA FFT/IFFT, mask, WOLA, or sample-by-sample core error. Telemetry formats and buffers records; only the HPS bridge writes DDR. Board-specific memory and IP wrappers stay outside `rtl/core/`.

The physical board hierarchy contains one core. `trecap_source_core_integration` owns source selection and the core instance; `trecap_de1soc_full_top` consumes the exported taps for telemetry/HPS. The standalone `trecap_core_telemetry_top` is a different composition and must not be inserted into that board hierarchy as a second core.

For full dependency rules, see [dependency_rules.md](dependency_rules.md), [module_inventory.md](module_inventory.md), and [module_api.md](module_api.md).

## Build compositions

| Filelist | Purpose |
| --- | --- |
| `rtl_core.f` | Core sources without FFT implementation closure |
| `rtl_core_plus_fft.f` | Independent core including FFT/IFFT dependencies |
| `rtl_core_telemetry.f` | Reusable core plus telemetry, without board/HPS ownership |
| `rtl_telemetry.f` | Packet formatting and telemetry buffering |
| `rtl_hps_bridge.f` | CSR, ring pointers, record builder, DDR writer |
| `rtl_bram_replay_system.f` | Deterministic replay through core and transport boundary |
| `rtl_de1soc_full.f` | Physical DE1-SoC composition |

The physical Quartus top is `rtl/platform/de1soc/de1_soc_trecap_top.sv`. The name `rtl/top/trecap_de1soc_full_top.sv` denotes a pin-independent telemetry/HPS composition, not the physical top. Generated vendor `system` HDL remains Platform Designer/QIP-owned.

## Profiles and artifacts

Build profiles select sources, platform dependencies, and telemetry presets. They reference shared contracts and do not redefine `N`, `L`, `H`, `F`, `G`, `D`, widths, packet IDs, or CSR offsets. BRAM replay is the default board profile; live sources are selected explicitly.

`artifacts/reference_outputs/` contains expected outputs promoted from the reference model. Reference-package naming and source-import manifests describe provenance, not board completion. Preserve logical paths and manifest relationships when updating either tree; do not merge unrelated generated output directories by hand.

## Project history

Phase 1 Haar sources and reports remain under `legacy/phase1/` and are excluded from active Phase 2 filelists. Existing historical diagnostic files are retained as development context. The active architecture and implementation status is described in the [implementation plan](architecture_implementation.md), not inferred from a historical filename or log.
