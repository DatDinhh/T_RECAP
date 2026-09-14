# Contributing to T-RECAP

We use this repository for the Phase 2 capstone implementation, reference model, and project documentation. Changes should make the design easier to understand, build, and maintain while preserving the published arithmetic and interface contracts.

## Before changing a component

Read the [project overview](README.md), [specification index](docs/specs/README.md), and the relevant [architecture document](docs/README.md). Use the current canonical tree; historical Phase 1 code is not an implementation dependency.

Keep a change focused on one engineering decision or component. Describe the problem, resulting behavior, affected interfaces, and remaining limitations. When a change alters a design assumption, update its owning contract and document the reason alongside the implementation.

## Ownership and generated files

- `rtl/core/` and `rtl/fft/` own the mathematical core. They cannot depend on board pins, HPS, DDR transport, or the dashboard.
- `rtl/telemetry/` owns best-effort formatting and buffering. `rtl/hps_bridge/` owns the DDR writer and control registers.
- `sw/hps/` owns transport and control. `sw/pc_dashboard/` owns display and commands. Neither duplicates the FPGA signal-processing algorithm.
- `sw/reference_model/` owns the software reference implementation. Its documented public library API is the entry point for arithmetic experiments.
- Machine-readable contracts live under `spec/`; build/runtime selections live under `config/`. A profile does not redefine arithmetic constants or packet layouts.
- Change source contracts or generators, then regenerate their outputs. Do not edit files marked `AUTO-GENERATED` by hand. Some JSON under `spec/generated/` is source input despite the directory name; consult the [generated-contract guide](docs/architecture/generated_contracts.md).

## Working locally

The root Makefile expects Bash. Use `make help` for available commands, and the [build guide](docs/architecture/build_order.md) for component-specific tools. Keep local builds and captures under ignored `build/`, `runs/`, or `out/` directories.

Do not include machine-specific absolute paths, credentials, private network details, temporary source copies, or tool caches in a change. The documented direct-link IP addresses are intentional lab defaults; personal overrides belong in local configuration.

## Describing results

Distinguish design calculations, implemented source, compiled software, synthesis/timing results, and measured hardware behavior. Report only work actually performed. A reference output, plot, or successful script invocation is not evidence of a working FPGA board.

The current work focuses on architecture and implementation. Verification architecture and hardware evaluation have their own later milestones. Preserve existing diagnostic material as history without treating historical logs or checks as evidence for newly changed source.

## Compatibility and releases

The active PDF and machine-readable contracts define the baseline. A change to constants, rounding, finite-stream geometry, CSR layout, or packet layout needs an explicit compatibility decision and updates to every affected consumer. Document extensions separately from the frozen baseline.

Keep reference snapshots and promoted artifacts traceable through their manifests. Package names and targets containing `golden` are compatibility names. We use **reference model** in current project descriptions and reserve completion claims for a documented release with supporting results.
