# DE1-SoC Platform Designer Generated Files Policy

File class: **[1] hand-written repository policy**  
Owner: T-RECAP Phase 2 implementation repository  
Path: `platform/de1soc/generated_notes/generated_files_readme.md`

This file defines which DE1-SoC Platform Designer/Qsys files are source files
and which tool outputs must stay local under the current source-package policy.
It is intentionally narrow: it covers the DE1-SoC Platform Designer boundary
only. It does not define the STFT/WOLA arithmetic core, telemetry packet
formats, HPS UDP streamer internals, or PC dashboard behavior.

## 1. Authority

The active specification requires the DE1-SoC Platform Designer/Qsys integration to be owned under `platform/de1soc/` and `rtl/platform/de1soc/`. The same section lists this directory, `platform/de1soc/generated_notes/`, and this exact file as part of the platform ownership tree.

The selected policy is:

```text
Commit source files:
  platform/de1soc/qsys/platform_designer.tcl
  platform/de1soc/qsys/hps_config.tcl
  platform/de1soc/qsys/generate_system.sh
  platform/de1soc/qsys/system_blueprint.xml
  platform/de1soc/qsys/system.qsys after reviewed tool normalization
  platform/de1soc/address_map/address_map.md
  platform/de1soc/address_map/hps_bridge_regions.json
  platform/de1soc/address_map/avalon_csr_adapter.json
  platform/de1soc/address_map/sopcinfo_location.md

Commit provenance-locked generated configuration snapshots:
  platform/de1soc/qsys/presets/terasic_de1soc_revh_qp20_1_hps.tsv
  platform/de1soc/qsys/presets/terasic_de1soc_revh_qp20_1_hps_manifest.json

Regenerate locally; do not commit in the current source ZIP:
  platform/de1soc/qsys/system.sopcinfo
  platform/de1soc/qsys/system/synthesis/system.qip
  platform/de1soc/qsys/system/synthesis/**

Never hand-edit generated Platform Designer HDL, QIP, SOPCINFO, or generated
IP submodule files.

The implemented `rtl/platform/de1soc/platform_designer_wrapper.sv` is hand-written
class `[1]` RTL and is included in the source snapshot. It must never be overwritten
by vendor output.
```

The address-map rule is also part of this policy: `RING_BASE` is the FPGA-visible DDR-writer bus address, not a Linux userspace virtual address. Any generated Platform Designer artifact that implies an address must be checked against `platform/de1soc/address_map/hps_bridge_regions.json`, `address_map.md`, and `sopcinfo_location.md` before use or any future source-policy change.

## 2. Current source-of-truth files

These files are source files. They are reviewed and committed as hand-managed repository inputs.

| File | Class | Role |
|---|---:|---|
| `platform/de1soc/qsys/hps_config.tcl` | `[1]` | Central DE1-SoC HPS, CSR, DDR-ring, and network configuration used by platform generation and HPS runtime config emission. |
| `platform/de1soc/qsys/platform_designer.tcl` | `[1]` | Deterministic Platform Designer/Qsys construction script. |
| `platform/de1soc/qsys/generate_system.sh` | `[1]` | Canonical lifecycle entry point. It validates contracts, preserves reviewed config, explicitly constructs Qsys source, or invokes `qsys-generate` from an existing normalized Qsys graph. |
| `platform/de1soc/qsys/system_blueprint.xml` | `[1]` | Canonical reviewed bootstrap graph contract used to validate both the checked-in seed and a later tool-normalized Qsys source. |
| `platform/de1soc/qsys/system.qsys` | `[1]` | Bootstrap source now; commit a tool-normalized replacement only after reviewing it against the blueprint. |
| `platform/de1soc/qsys/presets/terasic_de1soc_revh_qp20_1_hps.tsv` | `[2]` | Deterministic 520-parameter HPS snapshot derived from the official Terasic Rev-H Quartus 20.1 GHRD and consumed by `platform_designer.tcl`. Regenerate only with `scripts/import_de1soc_hps_preset.py`. |
| `platform/de1soc/qsys/presets/terasic_de1soc_revh_qp20_1_hps_manifest.json` | `[2]` | Source URL, upstream hashes, board/tool assumptions, overlay, exact interface directions, and effective snapshot hash. |
| `platform/de1soc/address_map/address_map.md` | `[1]` | Human-readable rendering of the Step 4 source-frozen CSR/ring assignments and bridge rules. |
| `platform/de1soc/address_map/hps_bridge_regions.json` | `[1]` | Canonical machine-readable Step 4 address contract, semantic fingerprint, and pinned source evidence. |
| `platform/de1soc/address_map/avalon_csr_adapter.json` | `[1]` | Canonical Step 5 Avalon-MM CSR decode, transfer, response, and hierarchy-integration source contract. |
| `platform/de1soc/address_map/sopcinfo_location.md` | `[1]` | Only accepted SOPCINFO path, source-versus-hardware evidence boundary, and fail-closed change procedure. |
| `constraints/de1soc/de1soc.qsf` | `[1]` | DE1-SoC Quartus settings and constraint hooks. |
| `constraints/de1soc/de1soc.sdc` | `[1]` | DE1-SoC timing constraints. |
| `constraints/de1soc/clocks.sdc` | `[1]` | Board clock constraint helpers. |
| `constraints/de1soc/pin_assignments.tcl` | `[1]` | Board pin assignment policy and opt-in physical pin assignment modes. |

These files are not generated scratch files. Do not overwrite them from a GUI export without reviewing the diff and preserving the repository policy.

`rtl/platform/de1soc/platform_designer_wrapper.sv` is a hand-written
class `[1]` adapter between the generated `system` entity and typed repository
RTL. It was completed in Step 6 and must never be classified as vendor-generated
Platform Designer HDL.

## 3. Generated-file classes

### 3.1 Real Platform Designer outputs regenerated locally

Produce and review these with Intel Platform Designer on the target Quartus
version, but keep them out of the current source ZIP:

| Generated artifact | Class | Current policy |
|---|---:|---|
| `platform/de1soc/qsys/system.sopcinfo` | `[2]` | Required real-run output; retain in the run/build environment, not the source ZIP. |
| `platform/de1soc/qsys/system/synthesis/system.qip` | `[2]` | Required real-run output consumed as one generated IP boundary; regenerate locally. |
| `platform/de1soc/qsys/system/synthesis/*.v` / `*.sv` | `[2]` | Required top HDL plus generated implementation files; regenerate locally. |
| `platform/de1soc/qsys/system/synthesis/submodules/**` | `[2]` | Local vendor output; never copy or commit a partial subset. |

Required changes must be made in `hps_config.tcl`, `platform_designer.tcl`, the
Platform Designer source system, or a documented generator, then regenerated.
Manual edits to generated HDL or QIP are not valid fixes. Changing this local-
only policy requires an explicit source-package decision and a coherent-set
whitelist; never add one generated submodule in isolation.

### 3.2 Generated files that should not be committed

Do not commit local build/cache output:

```text
platform/de1soc/qsys/system/simulation/**
platform/de1soc/qsys/system/testbench/**
platform/de1soc/qsys/system/.qsys_edit/**
platform/de1soc/qsys/system/.ip/**
platform/de1soc/qsys/system/**/*.bak
platform/de1soc/qsys/system/**/*.log
platform/de1soc/qsys/system/**/*.rpt
platform/de1soc/qsys/system/**/*.html
platform/de1soc/qsys/system/**/*.cmp
platform/de1soc/qsys/system/**/*.spd
platform/de1soc/qsys/system/**/*.ppf
platform/de1soc/qsys/system/**/*.qmsg
platform/de1soc/qsys/system/**/*.qws
runs/platform/de1soc/qsys/<UTC>-<PID>/hps_readback.tsv
runs/platform/de1soc/qsys/<UTC>-<PID>/generate_system_manifest.json
```

If a Quartus version creates another local cache directory, classify it as local output unless the real Quartus project cannot build without it and the team explicitly decides to commit it.
The per-run readback TSV and generation manifest are execution evidence, not
source inputs or preset updates; do not publish either under `qsys/presets/`.

## 4. Current repository state

At Step 2, the repo acquired a fail-closed, provenance-locked source contract. The
HPS pin mux and bridge settings are no longer empty or guessed: all 520
`altera_hps` 20.1 values are frozen, the 476 writable values are applied, and
the 44 derived/system-information values are explicitly readback-only. HPS IO/memory exports are required,
the lightweight CSR master and 64-bit bidirectional FPGA-to-HPS SDRAM path use
their exact component interface names, `h2f_reset` is a reset source, and the
four HPS bridge clock sinks are mandatory.

Step 3 defines the generation lifecycle without claiming a real board build.
`construct` is the only mode allowed to rebuild the Qsys graph and replace the
bootstrap. `generate` requires an existing tool-normalized `system.qsys`, never
reconstructs that graph, and invokes `qsys-generate` directly. The current
source package still does not contain real Quartus-generated Platform Designer
output.

Step 4 freezes the source address map without fabricating Intel output. The CSR
window, DDR ring region, address-translation assumption, bridge widths, burst
limit, waitrequest behavior, and exact artifact locations are fingerprinted in
`hps_bridge_regions.json`. `scripts/check_address_map.py` verifies the frozen
semantic tuple and all checked-in consumers. Real SOPCINFO, boot-remap, Linux
reservation, and physical-board evidence are still pending and are required
before hardware signoff.

Step 5 adds the hand-written `trecap_avmm_csr_adapter.sv`, integrates it before
the private CSR bank, and propagates the Avalon agent ports through the logical
RTL hierarchy. `scripts/check_csr_adapter.py` pins the adapter source identity and
checks the 21-bit-to-12-bit byte-address decode, strict full-width/single-beat
policy, deterministic response mapping, filelists, and top-chain wiring. This
does not change the generated-file policy.

Step 6 adds `trecap_csr_bridge` and `trecap_f2h_sdram_bridge` to the checked-in
Platform Designer source graph, exports their typed Avalon boundaries, implements
the hand-written wrapper, passes HPS DDR/peripheral pins through it, and replaces
the board-top safe-idle CSR/DDR stubs. Generated `system` HDL/QIP/SOPCINFO, Quartus
compile evidence, functional verification, and physical-board evidence remain
pending.

Step 7 adds the pin-agnostic `trecap_source_core_integration.sv`, instantiates all
four normalized sources through the guarded source mux, implements the exact C0
finite-replay analysis/tail split, and connects real core taps, counters, safe
boundaries, and new-fault events into the board/transport hierarchy. This is a
source implementation milestone only: RTL compile, functional verification,
generated Platform Designer/Quartus evidence, live audio/ADC readiness, and hardware
signoff remain pending.

The pinned Terasic board-revision-H GHRD is compatible with the active Quartus
20.1 toolchain. The physical board revision is a separate fact and has not been
inspected; its explicit status is
`unverified_requires_board_label_confirmation`. Do not use this snapshot on a
Rev-F/G board without importing and reviewing the matching vendor preset.

Current expected state:

```text
present:
  platform/de1soc/qsys/hps_config.tcl
  platform/de1soc/qsys/platform_designer.tcl
  platform/de1soc/qsys/generate_system.sh
  platform/de1soc/qsys/system_blueprint.xml
  platform/de1soc/qsys/system.qsys
  platform/de1soc/qsys/presets/terasic_de1soc_revh_qp20_1_hps.tsv
  platform/de1soc/qsys/presets/terasic_de1soc_revh_qp20_1_hps_manifest.json
  platform/de1soc/address_map/address_map.md
  platform/de1soc/address_map/hps_bridge_regions.json
  platform/de1soc/address_map/avalon_csr_adapter.json
  platform/de1soc/address_map/sopcinfo_location.md
  constraints/de1soc/de1soc.qsf
  constraints/de1soc/de1soc.sdc
  constraints/de1soc/clocks.sdc
  constraints/de1soc/pin_assignments.tcl

not expected until a real Intel Platform Designer run:
  platform/de1soc/qsys/system.sopcinfo
  platform/de1soc/qsys/system/synthesis/system.qip
  platform/de1soc/qsys/system/synthesis/*.v
  platform/de1soc/qsys/system/synthesis/*.sv

hand-written integration present after Steps 6 and 7:
  rtl/platform/de1soc/platform_designer_wrapper.sv
  rtl/top/trecap_source_core_integration.sv
  rtl/platform/de1soc/de1_soc_trecap_top.sv
```

A missing `system.sopcinfo` or `system.qip` is not a source-tree error before the real Platform Designer generation milestone. It becomes an error only when `make quartus-de1soc` or the HPS/address-map tooling explicitly requires those artifacts.

## 5. Generation flow

Run these commands from the repository root.

### 5.1 Validate platform configuration without Intel tools

```bash
platform/de1soc/qsys/generate_system.sh \
  --mode validate \
  --print-summary
```

This first runs `scripts/check_hps_platform.py`, which verifies snapshot hashes,
source/config parity, and exact interface directions. The dedicated
`scripts/check_address_map.py` gate verifies the Step 4 frozen semantic
fingerprint and every checked-in address consumer. The Step 5
`scripts/check_csr_adapter.py` gate verifies the adapter source contract and RTL
hierarchy integration. The flow then validates the Tcl configuration. It does not
require `qsys-script`.

### 5.2 Validate reviewed runtime/address-map config files

```bash
platform/de1soc/qsys/generate_system.sh \
  --mode emit-configs
```

This validates and preserves the reviewed config files below; it does
not silently regenerate or overwrite them:

```text
sw/hps/config/trecap_hps_config.json
platform/de1soc/address_map/hps_bridge_regions.json
platform/de1soc/address_map/avalon_csr_adapter.json
```

`hps_bridge_regions.json` is hand-reviewed platform config in this repository.
The generator must not silently overwrite reviewed address-map changes. Its
Step 4 semantic fingerprint must pass before the file may be used.

### 5.3 Explicitly construct and normalize Qsys source

Run this when creating the normalized source for the first time:

```bash
platform/de1soc/qsys/generate_system.sh \
  --mode construct \
  --print-summary
```

Replacing an already normalized source after an intentional reviewed contract
change requires the explicit destructive opt-in:

```bash
platform/de1soc/qsys/generate_system.sh \
  --mode construct \
  --force \
  --print-summary
```

`construct` requires `qsys-script` plus a Quartus 20.1 version check through
`quartus_sh`; it does not require `qsys-generate`. It creates the graph from the
frozen Tcl and HPS preset, validates it, saves to a staging file, atomically
replaces `system.qsys`, and captures all 44 readback-only HPS values. This mode
is explicitly destructive to the previous Qsys source; review the normalized
diff before committing it. Do not use `construct` as the normal incremental
build path.

### 5.4 Generate HDL/IP from normalized Qsys

After the normalized source has been reviewed, run:

```bash
platform/de1soc/qsys/generate_system.sh \
  --mode generate \
  --print-summary
```

`generate` requires `qsys-script` for readback capture, `qsys-generate` for
HDL/IP emission, and a Quartus 20.1 version check through `quartus_sh`. It
rejects the bootstrap Qsys source and does not call the graph constructor or
add/remove instances, interfaces, or connections. A successful real run
requires this coherent output set:

```text
platform/de1soc/qsys/system.sopcinfo
platform/de1soc/qsys/system/synthesis/system.qip
platform/de1soc/qsys/system/synthesis/system.v or system.sv
runs/platform/de1soc/qsys/<UTC>-<PID>/hps_readback.tsv
runs/platform/de1soc/qsys/<UTC>-<PID>/generate_system_manifest.json
```

The per-run readback TSV records exactly the 44 sorted tool-derived values; it
does not rewrite the frozen preset. The run manifest embeds that ordered
44-value section and records the mode, resolved tool identities and version,
Qsys state, and hashes for Qsys, SOPCINFO, QIP, and top-level generated HDL.
Native command lines and output remain in the adjacent `qsys_construct.log`,
`qsys_readback.log`, and `qsys_generate.log` files. Missing or partial evidence
is an error. A dry-run prints the exact command and expected artifacts without
requiring or modifying a normalized source.

### 5.5 First run and Quartus build integration

The first real Intel-tool run is deliberately two commands:

```bash
make platform-construct
make platform-generate
```

Ordinary rebuilds use only `make platform-generate`. The full-board build
wrapper invokes generation exactly once and assumes normalized Qsys already
exists. CI that runs construct/generate explicitly must pass
`--skip-platform-generate` to `scripts/quartus/build_de1soc.sh`.

After a real Platform Designer generation run, check that `constraints/de1soc/de1soc.qsf` or the Quartus project includes the required QIP generated by Platform Designer. The generated filelist `filelists/quartus_de1soc.qsf.inc` owns RTL source assignment order. The Platform Designer `system.qip` owns generated IP/HDL inclusion.

The two mechanisms must not be mixed manually. Do not paste generated Platform Designer HDL paths into hand-maintained source lists one by one.

## 6. Review checklist for generated Platform Designer output

Before accepting a real run or retaining any `[2]` output locally:

1. Run `make check-generated` and `make rtl-filelist`.
2. Run `platform/de1soc/qsys/generate_system.sh --mode validate --print-summary`.
3. Run `python3 scripts/check_address_map.py --require-sopcinfo` to confirm the expected generated artifact and interface identities; do not treat that identity check as proof of hardware CSR reachability or Linux reservation.
4. Confirm `RING_BASE` is still the FPGA-visible address, not an HPS userspace `mmap()` pointer.
5. Confirm no generated HDL file contains an absolute path to a local machine directory.
6. Confirm no generated file changed CSR offsets, packet IDs, or payload sizes. Those belong to `spec/generated/` and generated headers, not Platform Designer output.
7. Confirm generated HPS pin assignments match the DE1-SoC board revision before enabling `physical_full_hps` pin mode.
8. Confirm the Quartus build consumes `system.qip` as a generated IP boundary instead of manually adding individual generated HDL files.
9. Confirm the per-run readback TSV contains exactly the frozen 44 readback-only names and that the run manifest embeds them and hashes Qsys, SOPCINFO, QIP, and top HDL.
10. Confirm generated output is reproducible by deleting the generated directory and rerunning `generate` on the same normalized Qsys and Quartus version.
11. Keep generated output out of the current source ZIP. If a later policy explicitly whitelists it, retain only a complete coherent set, never one generated submodule.

## 7. What to do when a generated file needs to change

Do not patch generated HDL or QIP by hand.

Use this sequence:

```text
1. Identify the real source of the change.
2. Edit hps_config.tcl, platform_designer.tcl, or system.qsys as appropriate.
3. Regenerate Platform Designer output.
4. Run generated-header/filelist checks.
5. Run Quartus compile or dry-run build checks.
6. Review the generated diff.
7. Commit the reviewed source change and normalized `system.qsys` when applicable; keep SOPCINFO/QIP/HDL as local regenerated output under the current policy.
```

If the required change came from the Platform Designer GUI, export or reconstruct the change in `platform_designer.tcl` or in a reviewed `system.qsys` diff. Do not leave the only copy of the design change inside a generated HDL file.

## 8. Relationship to HPS software and Ethernet

Generated Platform Designer output only exposes the hardware bridge boundary. It does not implement the HPS UDP streamer, PC dashboard, or signal-processing algorithm.

The intended division remains:

```text
FPGA fabric:
  source/core/taps -> telemetry formatter -> DDR ring writer

Platform Designer:
  HPS CSR bridge + FPGA-to-HPS SDRAM/DDR path + HPS pins/memory interfaces

HPS software:
  DDR ring reader -> UDP sender -> command receiver -> CSR writer

PC software:
  UDP parser/dashboard -> command client
```

HPS owns Ethernet transport. FPGA fabric owns real-time signal processing and the DDR ring writer. Platform Designer is only the bridge/interconnect boundary between those layers.

## 9. Failure policy

Treat the following as hard errors:

```text
- A generated Platform Designer HDL file is hand-edited.
- system.qsys is changed by Quartus but the diff is not reviewed.
- generate is requested for the bootstrap Qsys source or mutates a normalized graph.
- a real generate run lacks system.sopcinfo, system.qip, system.v/system.sv, its 44-value per-run readback capture, or its run manifest.
- The generated wrapper exposes different CSR/ring interfaces than address_map.md documents.
- RING_BASE is configured as an HPS virtual address.
- Generated Platform Designer output is added to the current source package or retained partially without an explicit coherent-set policy change.
- Generated output embeds local absolute paths that break another user's checkout.
- HPS Ethernet or sample-processing logic is moved into generated Platform Designer HDL.
```

Treat the following as acceptable during pre-Quartus skeleton stages:

```text
- system.sopcinfo is absent.
- system/synthesis/system.qip is absent.
- generated Platform Designer module `system` HDL is absent; the separate
  hand-written `platform_designer_wrapper.sv` source boundary is present.
- build_de1soc.sh dry-run warns that the real Quartus project has not been created yet.
```

## 10. Minimal acceptance for this file

This policy file is complete when:

```text
- It states that Platform Designer generated output is not hand-edited.
- It identifies the hand-written source files.
- It identifies real generated files that remain local under the current source-package policy.
- It identifies generated/cache files that should not be committed.
- It documents the validate, emit-configs, construct, and generate commands.
- It requires direct generation from normalized Qsys, a 44-value per-run readback capture, and a hashed run manifest.
- It preserves the RING_BASE address-space warning.
- It matches hps_config.tcl, platform_designer.tcl, generate_system.sh, system.qsys, and address_map.md.
```
