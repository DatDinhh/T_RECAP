# DE1-SoC SOPCINFO Location and Address-Evidence Policy

File class: **[1] hand-written platform address-map policy**  
Project: **T_RECAP_Phase2**  
Board: **DE1-SoC**  
Address-map milestone: **Step 4 source freeze**

## Canonical locations

| Item | Repository path | Class |
| --- | --- | --- |
| Platform Designer source | `platform/de1soc/qsys/system.qsys` | `[1]` reviewed working source |
| Immutable graph blueprint | `platform/de1soc/qsys/system_blueprint.xml` | `[1]` hand-written source |
| Frozen address contract | `platform/de1soc/address_map/hps_bridge_regions.json` | `[1]` hand-reviewed source |
| Human-readable address contract | `platform/de1soc/address_map/address_map.md` | `[1]` hand-written source |
| Generated SOPCINFO | `platform/de1soc/qsys/system.sopcinfo` | `[2]` Intel-tool output |
| Generation evidence | `runs/platform/de1soc/qsys/<UTC>-<PID>/generate_system_manifest.json` | `[2]` per-run output |

`platform/de1soc/qsys/system.sopcinfo` is the only accepted SOPCINFO location
for the `system` Platform Designer system. Scripts must not search recursively
for another `.sopcinfo` file and must not silently accept one from a different
Quartus installation, build directory, or archived project.

## Source freeze versus hardware evidence

Step 4 freezes the reviewed source assignments below:

```text
CSR HPS physical base       0x00000000ff200000
HPS lightweight aperture    [0x00000000ff200000, 0x00000000ff400000)
CSR span                    0x00001000 bytes
DDR ring HPS physical base  0x000000003e000000
DDR ring FPGA-visible base  0x000000003e000000
DDR ring size               0x02000000 bytes
DDR ring interval           [0x000000003e000000, 0x0000000040000000)
```

This is a source contract, not proof that a particular board image implements
the contract. Hardware signoff still requires all of the following:

1. Quartus Prime Standard Edition 20.1 constructs and generates the frozen
   Platform Designer system.
2. The generated SOPCINFO exists at the exact path above and is non-empty.
3. The generated metadata agrees with the frozen CSR bridge path and address
   assignments that it exposes, including a non-aliased 4 KiB CSR subwindow
   at offset zero of the 2 MiB lightweight aperture.
4. The physical board revision matches the selected Rev-H source profile.
5. The boot handoff keeps the expected Cyclone V bridge/remap configuration.
6. Linux reserves `[0x3e000000, 0x40000000)` or a reviewed DMA-coherent
   replacement is adopted and the complete source freeze is revised.

Absence of SOPCINFO is allowed for a source-only package and for the normal
static contract gate. It is an error for the hardware-evidence gate.

## Required checks

Source-only review:

```bash
python3 scripts/check_address_map.py
```

After a real Quartus generation:

```bash
python3 scripts/check_address_map.py --require-sopcinfo
```

The hardware-evidence mode must fail closed when SOPCINFO is missing, empty,
unreadable, or inconsistent. It must not create a substitute file, infer a
passing address from this document, or copy an artifact from another run.

The current checker establishes artifact presence, the expected HPS/export
identities, and that `system.qsys` was normalized by the pinned tool flow. The
checked-in Qsys source now routes the raw lightweight AXI master through
`trecap_csr_bridge` and routes the exported 64-bit Avalon DDR agent through
`trecap_f2h_sdram_bridge`; the hand-written `platform_designer_wrapper.sv` binds
those exports to the board RTL hierarchy. This is source connectivity only.
The generated SOPCINFO and flattened `system` HDL must still prove CSR
reachability, the non-aliasing 4 KiB assignment, and the exact port ABI. Boot-time
remap state, Linux reservation, and physical-board identity remain separate
hardware-signoff blockers even when `--require-sopcinfo` passes.

## Change procedure

If the generated address evidence disagrees with the frozen source:

1. Stop the board build and do not patch SOPCINFO.
2. Determine whether the Platform Designer graph, HPS bridge configuration,
   Linux reservation, or source address plan is wrong.
3. Update `hps_bridge_regions.json`, `address_map.md`, `hps_config.tcl`, the
   working/blueprint Qsys metadata, and `trecap_hps_config.json` together.
4. Recompute the Step 4 freeze fingerprint with the repository helper.
5. Re-run the source gate, reconstruct the Qsys system only when the reviewed
   graph changed, regenerate with Quartus 20.1, and run the hardware-evidence
   gate again.

Generated Platform Designer HDL, QIP, SOPCINFO, and per-run manifests shall not
be hand-edited. They remain excluded from the cumulative architecture source
ZIP under the current repository policy.
