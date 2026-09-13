# Platform Designer wrapper contract

> **Step 6 status:** `source_implemented_pending_quartus_generation_compile_and_hardware_evidence`

`rtl/platform/de1soc/platform_designer_wrapper.sv` is the hand-written boundary between the
DE1-SoC board RTL and the Quartus-generated Platform Designer module named `system`. It does not
replace Platform Designer, emulate the HPS, or provide a simulation-only `system` stub. Its job is
to bind a frozen flattened generated ABI to repository-native CSR and DDR buses, pass the HPS pins
to the board top, and reject DDR addresses that cannot be represented safely.

The machine-readable authority for this boundary is
`platform/de1soc/address_map/platform_designer_wrapper.json`; its schema is
`spec/schemas/platform_designer_wrapper.schema.json`.

## What is implemented now

The following source connections exist:

- `de1_soc_trecap_top` instantiates `platform_designer_wrapper` as
  `u_platform_designer_wrapper`;
- the CSR path is connected between the generated system and
  `trecap_de1soc_full_top`, with no board-level idle stub;
- the DDR write path is connected between `trecap_de1soc_full_top` and the generated system, with
  no board-level `waitrequest` stub;
- `platform_designer.tcl` creates `trecap_csr_bridge` and
  `trecap_f2h_sdram_bridge` and connects both into the HPS graph; and
- the generated HPS reset output participates in fabric reset release without being connected to
  an HPS reset sink.

This is a source implementation milestone only. The checked-in `system.qsys` is still a
hand-written bootstrap, not a Quartus-normalized Qsys file. Generated `system.v`/`system.sv`,
`system.qip`, and `system.sopcinfo` are not checked in. No Quartus compile, functional verification,
or hardware signoff is claimed.

## Source and generated ownership

| Item | Class | Rule |
| --- | --- | --- |
| `platform_designer_wrapper.sv` | `[1]` hand-written | Review and edit in source control. |
| `de1_soc_trecap_top.sv` | `[1]` hand-written | Owns board pins and reset composition. |
| `platform_designer.tcl`, `hps_config.tcl` | `[1]` hand-written | Authoritative graph construction and frozen parameters. |
| `system.qsys` | `[1]` bootstrap now, then tool-normalized source | Replace only through the documented Quartus 20.1 construct flow. |
| `system.v`/`system.sv`, `system.qip`, `system.sopcinfo` | `[2]` generated | Generate locally; never hand-edit or replace with a compatibility stub. |

The wrapper deliberately instantiates `system` without defining it. A source-only structural check
can therefore run without Quartus output, while a real full-board elaboration fails until the
generated QIP and HDL are available.

## CSR path

The complete path is:

```text
HPS h2f lightweight AXI manager
  -> trecap_csr_bridge.s0
  -> trecap_csr_bridge.m0 (export: trecap_csr_lw_master)
  -> platform_designer_wrapper
  -> trecap_avmm_csr_adapter
  -> trecap_csr_bank
```

`trecap_csr_bridge` is an `altera_avalon_mm_bridge`. Its source contract freezes symbol/byte
addressing, address width 21, data width 32, symbol width 8, maximum burst size 1, maximum pending
responses 1, automatic address-width reduction disabled, and response support enabled. The bridge
is mapped at lightweight-aperture offset zero.

The wrapper preserves all of this Avalon-MM agent ABI:

| Signal group | Width |
| --- | ---: |
| Byte address | 21 |
| Write/read data | 32 |
| Byte enable | 4 |
| Burst count | 1 |
| Response | 2 |

The return path is complete: `waitrequest`, `readdata`, `readdatavalid`,
`writeresponsevalid`, and `response` all cross the wrapper. The wrapper must not narrow the address
to the 12-bit CSR-leaf offset. Full aperture decode remains owned by
`trecap_avmm_csr_adapter`.

## FPGA-to-HPS DDR write path

The complete path is:

```text
trecap_avmm_write_master (64-bit repository byte address, 64-bit data, burstcount width 1)
  -> platform_designer_wrapper range guard
  -> trecap_f2h_sdram0 exported slave (32-bit byte address, burstcount width 1)
  -> trecap_f2h_sdram_bridge.s0
  -> trecap_f2h_sdram_bridge.m0
  -> hps_0.f2h_sdram0_data
```

`trecap_f2h_sdram_bridge` is a 64-bit `altera_avalon_mm_bridge` with symbol/byte addressing, a
32-bit exported address, 8 byte enables, a one-bit/single-beat exported burst count, automatic
address-width reduction disabled, response support disabled, and a base address of zero. Platform
Designer owns conversion between that typed external interface and the raw HPS F2SDRAM agent,
including adaptation to the raw agent's 11-bit burst-count field.

The repository writer always emits one beat, so its one-bit burst count passes unchanged into the
exported bridge interface. The exported bidirectional SDRAM port has read signals, but this wrapper
is write-only: `trecap_f2h_sdram0_read` is tied low and the generated read data/valid are unused.
Because the exported HPS F2SDRAM port has no write-response channel, the wrapper generates one
registered local response for each accepted repository-side beat. This response closes the local
ready/response protocol; it does not manufacture physical-DRAM completion or downstream error
evidence that the generated interface cannot provide.

### Legal writes

The board has 1 GiB of HPS DDR at FPGA-visible byte addresses
`[0x00000000,0x40000000)`. For a legal write:

- the low 32 address bits are forwarded;
- data, byte enable, and the one-bit burst count are forwarded unchanged;
- generated `waitrequest` is returned to the repository writer; and
- exactly one registered local `writeresponsevalid`/`OKAY` is returned after the generated bridge
  accepts the beat (`write && !waitrequest`).

The last point is bridge-acceptance evidence only. A legal DDR write can be flow-controlled, but
the current boundary cannot report a later downstream write error through Avalon response signals.
The local `OKAY` must never be described as proof that data reached physical DRAM.

### Invalid writes

For `avm_write_i=1` with `avm_address_i >= 64'h0000_0000_4000_0000`, the wrapper fails closed. In
the request cycle it accepts the command locally with `waitrequest=0` and suppresses the generated
write. Exactly one clock later it emits the registered Avalon write response:

```text
avm_waitrequest_o          = 0
trecap_f2h_sdram0_write    = 0

next cycle:
avm_writeresponsevalid_o   = 1
avm_response_o             = SLVERR (2'b10)
```

The one-cycle delay is required by Avalon-MM write-response timing. The invalid beat is never
forwarded, and silently truncating a 64-bit address to 32 bits is prohibited. The upstream write
master permits one outstanding beat and waits in `MSTATE_WAIT_RESPONSE`; it emits record
`write_done` only after the final beat's local response is `OKAY`. A response error moves the master
and ring writer to their fault states before `producer_advance_valid` can assert. A rejected write
therefore cannot advance the producer pointer.

## Reset contract

Step 10 moves canonical reset conditioning into `clock_reset_ctrl`. The topology
keeps all transaction-owning fabric blocks coherent without resetting the HPS
from its own reset output:

```text
system.h2f_reset_reset_n -> h2f_reset_n
KEY[0] released stable high for 20 ms
  + h2f_reset_n
  -> clock_reset_ctrl
  -> one trecap_reset_sync (CLOCK_50; asynchronous assertion, synchronized deassertion)
  -> rst_n_platform
       +-> trecap_de1soc_full_top
       +-> platform_designer_wrapper local response state
       `-> bridge_reset_n_i -> system.reset_n_reset_n
                                -> clk_0.clk_reset
                                -> trecap_csr_bridge.reset
                                `-> trecap_f2h_sdram_bridge.reset
```

`system.reset_n_reset_n` is a fabric-bridge reset input despite the generic generated name. The
checked-in Qsys graph connects it through `clk_0.clk_reset` only to the two typed Avalon bridges;
it is not connected to an HPS reset sink. Therefore `h2f_reset_n` may safely reach that input after
the `clock_reset_ctrl`-owned synchronizer without creating a self-sustaining reset loop. A warm HPS reset now
clears bridge pipeline state, the wrapper-local write-response registers, the CSR leaf, and the DDR
writer together. The board top does not own a second fabric reset synchronizer.

## Frozen generated-system ABI

The expected generated module name is `system`, instantiated as
`u_platform_designer_system`. The exact 94-port flattened ABI is frozen in
`generated_system_contract.expected_flattened_abi` in the JSON contract. It contains:

- `clk_50_clk`, `reset_n_reset_n`, and `h2f_reset_reset_n`;
- the complete `memory_mem_*` HPS DDR conduit;
- EMAC1, QSPI, SDIO, USB1, SPIM1, UART0, I2C0, I2C1, and the seven frozen GPIO pins under
  `hps_io_hps_io_*`;
- the complete `trecap_csr_lw_master_*` Avalon interface; and
- the write-capable `trecap_f2h_sdram0_*` Avalon interface, including its unused read signals.

The ABI is checked twice: the source checker compares the wrapper's named `system` connections
with the contract, and `--require-generated` parses the actual generated module header and checks
every port direction and width.

## Checks and evidence boundary

Run the source-only gate from the repository root:

```bash
python3 scripts/check_platform_designer_wrapper.py
```

This dependency-free default checks the JSON/schema identities, wrapper policy, board wiring,
reset topology, both Tcl bridge paths, working-Qsys/blueprint XML readability, and generated
filelists. It accepts the checked-in bootstrap or a reviewed normalized Qsys file, does not
require Quartus products, and does not count as simulation or synthesis.

After Quartus 20.1 generation, run:

```bash
python3 scripts/check_platform_designer_wrapper.py --require-generated
```

That stricter mode requires one generated `system.v` or `system.sv`, plus nonempty
`system/synthesis/system.qip` and `system.sopcinfo`. It rejects the hand-written bootstrap Qsys,
parses the generated module header, and requires the exact frozen flattened ABI. Passing it is
still not a Quartus compile result, functional verification result, Linux DDR-reservation proof,
or hardware signoff.

The board-build wrapper preserves that order on a clean checkout:
`scripts/quartus/build_de1soc.sh` runs the source-only gate before Platform Designer generation,
then runs `--require-generated` only after the HDL, QIP, and SOPCINFO presence checks and before
Quartus compilation. The generated-artifact gate must never run in the pre-generation block.

Before those later evidence steps are reviewed, these values remain false:

```text
generated_system_present = false
normalized_qsys          = false
quartus_compile           = false
functional_verification  = false
hardware_signoff          = false
```
