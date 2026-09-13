# DE1-SoC Address Map

File class: **[1] hand-written platform address-map contract**  
Project: **T_RECAP_Phase2**  
Board: **DE1-SoC**  
Current integration stage: **Step 7 source-to-core integration source implemented / RTL compile, functional verification, generated Quartus, and hardware evidence pending**

## Step 2 source freeze

The Platform Designer/HPS source contract is now frozen for this repository:

- Quartus release: `20.1`; Qsys Tcl API package: `16.0`; `altera_hps`
  component version: `20.1`.
- Preset profile: `terasic_de1soc_revh_qp20_1_trecap_f2sdram64`.
- HPS parameter snapshot: all 520 parameters from the official Terasic
  DE1-SoC Rev-H Quartus 20.1 GHRD, with the T-RECAP FPGA-to-HPS SDRAM
  interface overlaid as `Avalon-MM Bidirectional`, 64 bits. The generator
  applies the 476 vendor-exported writable parameters; the other 44 are frozen
  readback-only tool-derived/system-information observations.
- Physical board revision status:
  `unverified_requires_board_label_confirmation`. The Rev-H source preset is
  the explicit build assumption, not a claim that the board on the desk has
  been inspected. A Rev-F/G board needs its own reviewed preset.
- At Step 2, tool-produced `system.qsys`, `system.sopcinfo`, QIP, generated HDL,
  Linux reserved-memory evidence, and physical-board confirmation were still
  pending, so the address values were candidates rather than a frozen contract.

## Step 3 generation-flow boundary

Step 3 fixes the lifecycle without changing the frozen HPS configuration or
promoting provisional addresses:

```text
validate      check the frozen source/config/address contract without Intel tools
emit-configs  validate and preserve the reviewed runtime/address JSON files
construct     explicitly rebuild and normalize system.qsys from the frozen graph
generate      reuse normalized system.qsys and invoke qsys-generate directly
```

Only `construct` may add instances, interfaces, exports, or connections. It
atomically replaces the bootstrap after strict validation and captures the 44
tool-derived/readback-only HPS values. `generate` rejects the bootstrap and
must not mutate the normalized graph. The first real run is `construct` then
`generate`; ordinary rebuilds use `generate` only.

A successful real generation requires `system.sopcinfo`,
`system/synthesis/system.qip`, `system/synthesis/system.v` or `system.sv`, the
per-run 44-value `hps_readback.tsv`, and the generation manifest that embeds
those values. These outputs prove tool-flow completeness only. They do not
prove the CSR bridge, DDR ring, HPS software, board wiring, or signal-processing
behavior.

The exact frozen Platform Designer boundary is:

| Export | Internal interface | Direction |
| --- | --- | --- |
| `clk_50` | `clk_0.clk_in` | clock sink exported to the board top |
| `reset_n` | `clk_0.clk_in_reset` | paired clock-source reset sink exported to the board top |
| `trecap_csr_lw_master` | `trecap_csr_bridge.m0` | Typed 21-bit byte-addressed Avalon master → FPGA CSR adapter |
| `trecap_f2h_sdram0` | `trecap_f2h_sdram_bridge.s0` | Typed 32-bit byte-addressed, 64-bit Avalon slave ← FPGA writer |
| `h2f_reset` | `hps_0.h2f_reset` | Qsys Tcl reset `source` (serialized direction `start`) |
| `hps_io` | `hps_0.hps_io` | board HPS peripheral pins |
| `memory` | `hps_0.memory` | board HPS DDR pins |

`clk_0.clk` is internal and must drive all four HPS bridge clock sinks:
`hps_0.f2h_sdram0_clock`, `hps_0.h2f_axi_clock`,
`hps_0.f2h_axi_clock`, and `hps_0.h2f_lw_axi_clock`.

The raw HPS interfaces remain behind explicit Platform Designer bridges:

```text
hps_0.h2f_lw_axi_master -> trecap_csr_bridge.s0 @ 0
trecap_f2h_sdram_bridge.m0 -> hps_0.f2h_sdram0_data @ 0
```

Qsys owns AXI-to-Avalon adaptation on the CSR path and address-unit adaptation
on the DDR path. The wrapper never connects a raw HPS AXI interface directly to
the Step-5 Avalon agent.

## Step 4 address-map source freeze

Step 4 promotes the reviewed address assignments from provisional candidates
to a source-frozen architecture contract. The canonical machine-readable
record is:

```text
platform/de1soc/address_map/hps_bridge_regions.json
```

The freeze pins the following semantic tuple and its canonical SHA-256:

```text
- HPS lightweight-bridge base and span;
- CSR offset, HPS physical base, span, width, alignment, and byte order;
- DDR ring HPS physical base, FPGA-visible base, size, guard, and range;
- identity address-translation assumption for the current Cyclone V plan;
- FPGA-to-HPS SDRAM data/byte-enable/burst widths;
- waitrequest, write-response, and producer-commit behavior;
- exact Qsys, SOPCINFO, runtime-config, and generated-contract locations.
```

`scripts/check_address_map.py` recomputes the semantic fingerprint and checks
every duplicated consumer. `python3 scripts/freeze_address_map.py` prints the
review candidate, while `python3 scripts/check_address_map.py` is the
non-mutating review command; changing the fingerprint requires an explicit
reviewed source update rather than an automatic rewrite during normal builds.

This is deliberately a **source freeze**, not hardware signoff. The exact
hardware-evidence boundary and SOPCINFO location are documented in
`platform/de1soc/address_map/sopcinfo_location.md`. A real Quartus 20.1
SOPCINFO, the boot bridge/remap state, the physical board revision, and the
Linux reserved-memory result remain mandatory before board signoff.

## Step 5 Avalon-MM CSR adapter boundary

Step 5 implements `rtl/hps_bridge/trecap_avmm_csr_adapter.sv` and integrates it
ahead of `trecap_csr_bank.sv`. The canonical machine-readable adapter contract is:

```text
platform/de1soc/address_map/avalon_csr_adapter.json
```

The adapter owns the fail-closed source decode. It receives the complete 21-bit
lightweight-aperture byte address, accepts only offset range
`0x000000..0x000fff`, then passes the lower 12 byte-offset bits to the CSR leaf.
Reads and writes must be aligned 32-bit, little-endian, full-byte-enable,
single-beat accesses. The adapter permits one outstanding transaction and maps
outside-window requests to Avalon `DECODEERROR`, malformed or leaf-rejected
requests to `SLVERR`, and successful requests to `OKAY`.

The adapter is propagated through `trecap_hps_bridge_top.sv` and
`trecap_de1soc_full_top.sv`. Step 6 connects that hierarchy to the hand-written
`platform_designer_wrapper.sv`; the board top no longer contains safe-idle CSR or
DDR bus stubs. The checked-in Qsys source connects
`hps_0.h2f_lw_axi_master` to `trecap_csr_bridge.s0` at offset zero and exports the
bridge's 21-bit byte-addressed Avalon `m0` interface as
`trecap_csr_lw_master`. This is source connectivity only: Quartus 20.1 must still
normalize and generate the graph, prove the flattened `system` ABI, compile the
design, and produce hardware evidence before the path is considered signed off.

This document is the board-specific address-map record for the DE1-SoC
implementation. It is not a generated header and it is not a replacement for
`spec/generated/csr_map.json`. Its job is to document how the HPS-visible CSR
window and the FPGA-visible DDR telemetry ring are connected in the current
Platform Designer plan.

The frozen values must match:

```text
platform/de1soc/qsys/hps_config.tcl
platform/de1soc/qsys/system.qsys
sw/hps/config/trecap_hps_config.json
platform/de1soc/address_map/hps_bridge_regions.json
platform/de1soc/address_map/sopcinfo_location.md
```

These values are now stable inputs for the remaining architecture
implementation. Do not claim that they are board-proven or enable the
direct-link hardware demo until they have been checked against the real
Quartus-generated `system.sopcinfo`, the HPS boot bridge/remap state, the Linux
memory-reservation result, and the physical board revision.

## Non-negotiable address-space rule

Do not write a Linux userspace virtual pointer into `RING_BASE_LO` or
`RING_BASE_HI`.

There are four different address notions in this project:

| Name | Meaning | Example in current repo |
| --- | --- | --- |
| HPS physical address | Linux physical address used by `/dev/mem`, kernel drivers, or reserved-memory setup. | `0x3e000000` for the DDR ring |
| HPS userspace virtual address | Process-local pointer returned by `mmap()`. | Not recorded in CSRs |
| FPGA-visible bus address | Address used by the FPGA DDR writer bus master. | `0x3e000000` for current ring plan |
| CSR byte offset | Register offset inside the T-RECAP CSR window. | `0x034` for `RING_BASE_LO` from generated CSR contract |

Only the FPGA-visible bus address is written to `RING_BASE_LO` and
`RING_BASE_HI`. HPS software is responsible for translating from its allocation
or reserved-memory view into the FPGA-visible bus address required by the
Platform Designer integration.

## Current summary

| Item | Current value | Source |
| --- | ---: | --- |
| Platform Designer system | `system` | `platform/de1soc/qsys/hps_config.tcl` |
| Qsys source | `platform/de1soc/qsys/system.qsys` | bootstrap until explicit `construct`; reviewed tool-normalized source afterward |
| SOPCINFO target | `platform/de1soc/qsys/system.sopcinfo` | generated by real Platform Designer run |
| SOPCINFO location policy | `platform/de1soc/address_map/sopcinfo_location.md` | exact location and hardware-evidence gate |
| HPS runtime config | `sw/hps/config/trecap_hps_config.json` | reviewed runtime source; parity checked against the frozen map |
| Canonical bridge/address contract | `platform/de1soc/address_map/hps_bridge_regions.json` | Step 4 machine-readable source freeze |
| Canonical CSR-adapter contract | `platform/de1soc/address_map/avalon_csr_adapter.json` | Step 5 decode, transfer, response, and integration policy |
| Lightweight HPS-to-FPGA aperture | `[0x00000000ff200000, 0x00000000ff400000)` / 2 MiB | Cyclone V HPS address map |
| CSR HPS physical base | `0x00000000ff200000` | current HPS-to-FPGA lightweight window plan |
| CSR span | `0x00001000` / 4096 bytes | enough for Revision G CSR map through `0x088` |
| CSR access width | 32 bits | Revision G CSR contract |
| Lightweight master byte-address width | 21 bits | full 2 MiB aperture; do not truncate before decode |
| CSR leaf byte-address width | 12 bits | 4 KiB subwindow after full aperture decode |
| CSR byte order | little-endian | Revision G CSR contract |
| CSR Avalon access policy | aligned 32-bit, `byteenable=0xf`, `burstcount=1`, one outstanding | Step 5 adapter contract |
| CSR Avalon response policy | `OKAY=0`, `SLVERR=2`, `DECODEERROR=3` | Step 5 adapter contract |
| DDR ring HPS physical base | `0x000000003e000000` | current reserved-DDR plan |
| DDR ring FPGA-visible base | `0x000000003e000000` | current Platform Designer bridge assumption |
| DDR ring size | `0x02000000` / 33,554,432 bytes / 32 MiB | recommended first implementation size |
| DDR ring address range | `[0x3e000000, 0x40000000)` | current reserved-DDR plan |
| Ring guard | 64 bytes | writer free-space guard |
| Ring alignment | 64 bytes minimum; currently also 32 MiB aligned | DDR record contract |
| DDR record header | 32 bytes | telemetry packet header contract |
| DDR record alignment | 64 bytes | ring record contract |
| DDR writer data width | 64 bits | current `hps_config.tcl` plan |
| DDR writer byteenable width | 8 bits | current `hps_config.tcl` plan |
| DDR writer burstcount width | 1 bit | current single-beat baseline |
| Telemetry UDP port | 5005 | HPS runtime config |
| Command UDP port | 5006 | HPS runtime config |
| PC direct-link IP | `192.168.10.1/24` | demo network plan |
| HPS direct-link IP | `192.168.10.2/24` | demo network plan |
| Transport version | `1.8` / `0x00010008` | generated CSR/package contract; Step 14 command/replay extension |

## CSR window

The T-RECAP CSR bank is exposed to HPS software through the HPS-to-FPGA
lightweight bridge or an equivalent memory-mapped CSR bridge.

| Field | Value |
| --- | --- |
| Region name | `trecap_csr_window` |
| Parent lightweight aperture | `[0x00000000ff200000, 0x00000000ff400000)` / 2 MiB |
| HPS physical base | `0x00000000ff200000` |
| Span | 4096 bytes |
| Access width | 32 bits |
| Lightweight master byte-address width | 21 bits |
| CSR leaf byte-address width | 12 bits |
| Alignment | 32-bit word aligned |
| Endian | little-endian |
| RTL owner | `rtl/hps_bridge/trecap_csr_bank.sv` |
| Source of register offsets | `spec/generated/csr_map.json` |
| HPS generated header | `sw/hps/include/generated/trecap_csr.h` |
| Python generated constants | `sw/pc_dashboard/generated/trecap_packet.py` |
| Smoke script | `scripts/bringup/smoke_csr.py` |
| Unused aperture policy | unmapped/decode error; never mirror the 4 KiB CSR bank |

Individual CSR offsets are not re-owned by this document. They come from
`spec/generated/csr_map.json` and generated headers. This document only owns the
board-specific base address and bridge region.

The 4 KiB T-RECAP CSR region occupies offset zero inside the 2 MiB Cyclone V
lightweight bridge aperture. The eventual Platform Designer interconnect or
typed wrapper must perform a full address decode. Ignoring upper address bits
would alias the CSR bank repeatedly across the aperture and is forbidden.
The raw exported lightweight master therefore retains all 21 byte-address bits.
Only after the upper nine bits have decoded offset range `0x000000..0x000fff`
may the lower 12 byte-offset bits be presented to the current CSR leaf. A future
Platform Designer interconnect may own this decode by assigning an exact 4 KiB
slave range; the leaf width does not redefine or shrink the master aperture.

Minimum CSR sanity reads for bring-up:

| CSR | Offset | Expected value / behavior |
| --- | ---: | --- |
| `ID` | `0x000` | `0x54524350` |
| `VERSION` | `0x004` | `0x00010008` |
| `CONTROL` | `0x008` | readable/writable level bits plus W1P controls |
| `STATUS` | `0x00c` | live transport state bits |
| `DMA_STATUS` | `0x064` | DDR writer state bits |

A read/write smoke test may write harmless values to `WAVE_DECIM` and
`SPEC_SHIFT`, then read them back. It shall not enable telemetry until the ring
initialization sequence below has completed.

## DDR telemetry ring

The DDR telemetry ring is the memory region written by the FPGA DDR ring writer
and consumed by the HPS UDP streamer.

| Field | Value |
| --- | --- |
| Region name | `telemetry_ddr_ring` |
| HPS physical base | `0x000000003e000000` |
| FPGA-visible base | `0x000000003e000000` |
| Size | 33,554,432 bytes |
| Address range | `[0x000000003e000000, 0x0000000040000000)` |
| Guard | 64 bytes |
| Minimum alignment | 64 bytes |
| Current natural alignment | 32 MiB aligned |
| Pointer model | 64-bit monotonic byte pointers `W` and `Rd` |
| Physical offset rule | `off(p) = p & (R - 1)` |
| Record header | 32 bytes |
| Normal record length | `align64(32 + payload_bytes)` |
| WRAP record type | `0x007f` |
| WRAP effective length | remaining physical tail, not `align64(32)` |
| RTL owner | `rtl/hps_bridge/trecap_ddr_ring_writer.sv` |
| Record builder | `rtl/hps_bridge/trecap_ddr_record_builder.sv` |
| Pointer control | `rtl/hps_bridge/trecap_ring_pointer_ctrl.sv` |
| HPS consumer | `sw/hps/src/ring_reader.c` |

The current `0x3e000000` to `0x40000000` interval is the top 32 MiB of a 1 GiB
physical address space. Linux shall not allocate this region for unrelated
memory if the reserved-DDR prototype is used. A kernel driver may replace this
with a DMA-coherent allocation, but it must still provide the FPGA-visible base
address written into `RING_BASE_LO` and `RING_BASE_HI`.

## DDR writer bridge

The FPGA writer connects through the Platform Designer FPGA-to-HPS SDRAM path or
an equivalent FPGA-side master path.

| Field | Value / rule |
| --- | --- |
| Platform export | `trecap_f2h_sdram0` |
| RTL master | `trecap_avmm_write_master.sv` through `trecap_ddr_ring_writer.sv` |
| Data width | 64 bits |
| Byte-enable width | 8 bits |
| Current burst policy | single-beat baseline, `burstcount = 1` |
| Repository / wrapper / exported bridge burst widths | 1 / 1 / 1 bits |
| Raw HPS F2SDRAM burst width behind PD adaptation | 11 bits |
| Repository / wrapper byte-address widths | 64 / 32 bits |
| Waitrequest policy | hold address, data, byteenable, and write stable while `waitrequest` is asserted |
| Legal-write response policy | raw HPS F2SDRAM exposes no Avalon write-response channel; wrapper returns response-valid low and `OKAY` idle |
| Out-of-range policy | address `>= 0x40000000` is accepted locally, is not forwarded, returns a registered wrapper-local `SLVERR` one cycle later, and cannot advance the producer pointer |
| Commit rule | update producer pointer only after all DDR writes for that record complete |
| Backpressure rule | DDR/ring blockage drops telemetry and counts it; it shall not stall the STFT/WOLA core |

The current single-beat policy is conservative. It is simpler to debug and
matches the first implementation wrapper already written. A later burst-capable
writer may change the burst limit only after the Platform Designer interconnect,
writer FSM, and HPS parser are updated together.

## Ring initialization sequence

HPS software shall initialize the ring in this order:

```text
1. clear CONTROL.telemetry_enable and CONTROL.ring_writer_enable
2. pulse CONTROL.telemetry_soft_reset
3. write RING_BASE_LO, RING_BASE_HI, and RING_SIZE_BYTES
4. pulse RING_CONFIG_COMMIT while telemetry is disabled
5. write RING_RD_LO_SHADOW = 0
6. write RING_RD_HI_SHADOW = 0
7. pulse RING_RD_COMMIT
8. verify producer pointer W = 0 using RING_WR_SNAPSHOT
9. configure packet enable, decimation, spectrum mode, and threshold
10. set CONTROL.ring_writer_enable = 1
11. set CONTROL.telemetry_enable = 1
```

Do not enable `telemetry_enable` or `ring_writer_enable` before both `W` and
`Rd` have been reset/committed. Stale pointer state is a ring-corruption bug,
not a dashboard bug.

## HPS memory mapping policy

For the first userspace prototype:

```text
- reserve the DDR ring range from Linux;
- map the ring as non-cacheable or explicitly invalidate before each read;
- map the CSR window through /dev/mem only for lab bring-up;
- never expose this unauthenticated command path outside an isolated lab/demo network.
```

For a cleaner implementation:

```text
- use a kernel driver or UIO-style controlled mapping for the CSR window;
- allocate or expose a DMA-coherent telemetry ring;
- return both HPS physical and FPGA-visible ring addresses to the HPS streamer;
- keep the runtime manifest as the source used by userspace software.
```

## Relationship to generated contracts

This document owns board-specific base addresses and bridge descriptions only.
It does not own these contracts:

| Contract | Owner |
| --- | --- |
| CSR offsets and bit fields | `spec/generated/csr_map.json` |
| Packet types and payload sizes | `spec/generated/packet_layouts.json` |
| Shared SV structs | `spec/generated/interface_types.json` |
| Generated SV packages | `rtl/include/generated/*.sv` |
| Generated HPS C headers | `sw/hps/include/generated/*.h` |
| Generated Python packet constants | `sw/pc_dashboard/generated/trecap_packet.py` |
| Runtime endpoint/config values | `sw/hps/config/trecap_hps_config.json` |

If a base address changes after a real Platform Designer run, update this file,
`hps_bridge_regions.json`, `sopcinfo_location.md` when paths/policy change,
`platform/de1soc/qsys/hps_config.tcl`, the Qsys source metadata, and
`sw/hps/config/trecap_hps_config.json` together. Recompute and review the frozen
fingerprint. Do not patch HPS C source, RTL literals, or generated Intel files
by hand.

## SOPCINFO and generated artifact locations

| Artifact | Current path | Policy |
| --- | --- | --- |
| Qsys source | `platform/de1soc/qsys/system.qsys` | commit once stable |
| SOPCINFO location policy | `platform/de1soc/address_map/sopcinfo_location.md` | committed source policy |
| SOPCINFO | `platform/de1soc/qsys/system.sopcinfo` | generated local evidence; excluded from the current source ZIP |
| QIP | `platform/de1soc/qsys/system/synthesis/system.qip` | generated by Platform Designer |
| Generated wrapper HDL | `platform/de1soc/qsys/system/synthesis/` | do not hand-edit |
| HPS readback evidence | `runs/platform/de1soc/qsys/<UTC>-<PID>/hps_readback.tsv` | per-run tool output with exactly 44 sorted values; never copied into the preset directory |
| Generation run manifest | `runs/platform/de1soc/qsys/<UTC>-<PID>/generate_system_manifest.json` | embeds the 44 readbacks and records modes, resolved tools/version, Qsys state, and Qsys/SOPCINFO/QIP/top-HDL hashes; native commands remain in adjacent logs |
| Generated-note document | `platform/de1soc/generated_notes/generated_files_readme.md` | describes final generated-file policy |

The current environment has not produced a real Quartus `system.sopcinfo` or
per-run readback evidence. Therefore the address assignments are source-frozen
but are not a proven Quartus export or hardware signoff map.

## Bring-up checklist

```text
[x] hps_config.tcl validates as a source contract.
[x] hps_bridge_regions.json parses and carries the Step 4 freeze fingerprint.
[x] sw/hps/config/trecap_hps_config.json matches the frozen address values.
[x] source Qsys metadata, CSR contract, bridge rules, and SOPCINFO path are checked by scripts/check_address_map.py.
[ ] construct produced a reviewed tool-normalized system.qsys and exactly 44 readback-only values.
[ ] generate produced SOPCINFO, QIP, top HDL, and a complete hashed run manifest without changing system.qsys.
[ ] scripts/check_address_map.py --require-sopcinfo passes on that exact generated output.
[ ] HPS can read CSR ID = 0x54524350.
[ ] HPS can read CSR VERSION = 0x00010008.
[ ] HPS can write/read harmless WAVE_DECIM and SPEC_SHIFT values.
[ ] HPS performs ring init with telemetry disabled.
[ ] RING_WR_SNAPSHOT returns W = 0 after telemetry soft reset/ring config commit.
[ ] STATUS-only records appear in DDR and are forwarded by HPS.
[ ] WRAP handling is tested before enabling high-rate WAVE/SPEC telemetry.
[ ] Linux memory reservation or DMA-coherent allocation is documented.
```

## Do not do this

```text
- Do not write mmap() return values into RING_BASE registers.
- Do not put CSR offsets in HPS C source manually.
- Do not put packet payload sizes in Python parser manually.
- Do not connect Ethernet directly in FPGA fabric for this architecture.
- Do not move trecap_ddr_ring_writer.sv into rtl/telemetry/.
- Do not let DDR waitrequest or a full ring stall the core sample/frame path.
- Do not treat PC dashboard telemetry as bit-accurate signoff.
```
