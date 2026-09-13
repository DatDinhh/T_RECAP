# Frozen DE1-SoC HPS Preset

This directory owns the Step 2 Platform Designer/HPS configuration snapshot.
It freezes source inputs; it is not a substitute for a successful Quartus run.

## Selected profile

`terasic_de1soc_revh_qp20_1_trecap_f2sdram64`

- Board source profile: official Terasic DE1-SoC revision-H GHRD.
- Tool release: Quartus 20.1.
- Platform Designer Qsys Tcl API package: 16.0.
- HPS component: `altera_hps` 20.1 for `5CSEMA5F31C6`.
- Snapshot size: 520 parameters.
- Application partition: 476 vendor-exported writable parameters are applied;
  44 device/system-info/clock/INI values are retained as readback-only
  provenance because the Qsys API does not permit setting derived or
  `SYSTEM_INFO` parameters.
- Project overlay: `F2SDRAM_Type = Avalon-MM Bidirectional` and
  `F2SDRAM_Width = 64`, matching the existing 64-bit T-RECAP DDR writer.
- TSV values are canonical Qsys-XML semantics. At the Tcl API boundary,
  `platform_designer.tcl` marshals the eight list-valued parameters to the
  exact Quartus 20.1 list representation (including the one-element
  `Avalon-MM\ Bidirectional` setter value); this does not alter snapshot hashes.
- Effective canonical parameter hash:
  `bf0dc533f1a141c2a3d91058501b19b0a6ef5b479619bb4829fe94bea60e0888`.

The physical board revision has not been inspected. Its status remains
`unverified_requires_board_label_confirmation`. Do not silently use this Rev-H
preset for a Rev-F/G board; import and review a separate profile.

## Files

- `terasic_de1soc_revh_qp20_1_hps.tsv` is a generated, sorted, complete
  parameter snapshot consumed by `platform_designer.tcl`; its third column
  declares `set` versus `readback_only`.
- `terasic_de1soc_revh_qp20_1_hps_manifest.json` records provenance, hashes,
  overlay rationale, exact exports, clock connections, and pending signoff.
- Real Quartus runs capture the 44 readback-only values under their run
  directories as `hps_readback.tsv` and embed them in
  `generate_system_manifest.json`. These tool outputs do not update this
  source preset directory.
- `scripts/import_de1soc_hps_preset.py` is the only supported regenerator.
- `scripts/check_hps_platform.py` is the source/configuration parity gate.

## Re-import

Download the official Terasic Rev-H System CD and extract:

```text
Demonstrations/SOC_FPGA/de1_soc_GHRD/soc_system.qsys
```

Then run from the repository root:

```bash
python3 scripts/import_de1soc_hps_preset.py \
  --vendor-qsys /path/to/soc_system.qsys

python3 scripts/check_hps_platform.py
```

The importer rejects any source Qsys file whose SHA-256 differs from the value
recorded in the manifest. Review a new upstream release as a new preset instead
of weakening that check.

## Step 3 generation lifecycle

Step 3 separates graph construction from HDL/IP generation. On the first real
Quartus 20.1 run, execute:

```bash
platform/de1soc/qsys/generate_system.sh --mode construct --print-summary
platform/de1soc/qsys/generate_system.sh --mode generate --print-summary
```

`construct` uses `qsys-script` plus the `quartus_sh` 20.1 version check to
replace the bootstrap with a validated, tool-normalized `system.qsys` and
capture the 44 readback-only values. It is the only mode allowed to rebuild the
graph and does not require `qsys-generate`. `generate` uses `qsys-script` for
readback capture, then invokes `qsys-generate` on that normalized file without
adding, deleting, or reconnecting graph objects. Normal rebuilds therefore use
only `generate`. Reconstructing an already normalized Qsys after an intentional
reviewed contract change requires `--mode construct --force`.

A successful real generation requires all of:

```text
platform/de1soc/qsys/system.sopcinfo
platform/de1soc/qsys/system/synthesis/system.qip
platform/de1soc/qsys/system/synthesis/system.v or system.sv
runs/platform/de1soc/qsys/<UTC>-<PID>/hps_readback.tsv
runs/platform/de1soc/qsys/<UTC>-<PID>/generate_system_manifest.json
```

The readback TSV must contain the same 44 sorted names classified
`readback_only` in the frozen preset. It is per-run evidence from the installed
tool, not an input to rewrite that preset. The per-run manifest embeds the
ordered readbacks and binds Qsys, SOPCINFO, QIP, and top HDL hashes to the exact
mode and resolved tool identities/version. Native tool command lines and output
remain in the adjacent per-stage log files.

## Still outside Step 3

The source package may retain the bootstrap until a real Intel-tool run is
available; generated output must never be fabricated. HPS pin assignments, a
real typed hand-written class `[1]` RTL wrapper and top-level CSR/DDR wiring,
the Quartus QPF/QSF project, Linux reserved memory, physical-board revision
confirmation, and functional verification remain later work. Step 4 freezes
the CSR and ring values at source level, but they remain blocked from hardware
signoff until the real SOPCINFO, Linux memory policy, boot/remap state, and
physical board revision are reviewed.
