# Avalon-MM CSR adapter

File class: **[1] hand-written architecture contract**.

This document freezes the source-level behavior implemented in Step 5 by
`rtl/hps_bridge/trecap_avmm_csr_adapter.sv`. The adapter is the protocol and
address-protection layer between one Avalon-MM CSR agent interface and the
private request/response interface of `trecap_csr_bank`.

Step 5 implements and connects this source path inside the logical RTL hierarchy.
Step 6 connects it to the hand-written Platform Designer wrapper and to the typed
Avalon export in the checked-in Qsys source. This source-level connection is not
Quartus or hardware evidence: the generated `system` HDL, real SOPCINFO, Quartus
compile, and board bring-up remain pending.

The machine-readable contract is:

```text
platform/de1soc/address_map/avalon_csr_adapter.json
spec/schemas/avalon_csr_adapter.schema.json
```

The dependency-free source-consistency gate is:

```text
python3 scripts/check_csr_adapter.py
```

## Why this block exists

The Step-4 address map defines two different address widths:

- the HPS lightweight aperture carries a 21-bit byte address and spans 2 MiB;
- the T-RECAP CSR leaf consumes a 12-bit byte offset and spans 4 KiB.

Connecting the lower 12 address bits directly to the leaf would silently mirror
the CSR bank 512 times across the aperture. The adapter prevents that aliasing by
checking every one of the 21 input address bits before it forwards any request.
Only offsets `0x000000` through `0x000fff` are eligible for forwarding. The
accepted window starts at lightweight-aperture offset zero.

The adapter also turns a bus transaction into the deliberately smaller CSR leaf
protocol. That separation keeps Avalon timing, malformed-access rejection, and
response encoding out of the register bank.

## Ownership boundary

```text
Avalon-MM CSR agent
  21-bit byte address, read/write, data, byteenable, burstcount
        |
        v
trecap_avmm_csr_adapter
  full-window decode, transfer validation, serialization, response mapping
        |
        v
private CSR request/result interface
  valid/ready, write, 12-bit byte offset, wdata, rvalid/rdata/error
        |
        v
trecap_csr_bank
  generated offsets, access permissions, shadow/commit, snapshot, W1P/W1C
```

The adapter owns failures detected before a leaf request. The CSR bank owns
unknown-register, access-permission, and safe-command rejection once a leaf
request has been issued.

`local_reject_pulse_o` pulses only for the first category. In
`trecap_hps_bridge_top`, that pulse joins the existing CSR command-reject
accounting path through a dedicated bank input. Keeping it separate prevents an
adapter rejection and an unrelated external/writer rejection in the same cycle
from being coalesced into one count. A leaf rejection is already counted by the
CSR bank and must not be counted again as an adapter-local reject.

## Frozen interface values

| Property | Step-5 value |
| --- | --- |
| Avalon address unit | byte |
| Avalon address width | 21 bits |
| Lightweight aperture | 2 MiB |
| CSR base within aperture | `0x000000` |
| CSR span | 4096 bytes |
| Leaf address width | 12 byte-offset bits |
| Data width | 32 bits |
| Byte order | little-endian |
| Legal alignment | 4 bytes |
| Legal byteenable, read and write | `4'b1111` |
| Legal burstcount | exactly 1 |
| Maximum outstanding transactions | 1 |
| CSR base parameter | zero in `trecap_hps_bridge_top` |

The byteenable restriction is intentional even for reads. It gives HPS software
one simple, frozen rule: every CSR access is a complete aligned 32-bit word.
Byte, halfword, unaligned, and multi-beat accesses are unsupported.

## Request acceptance and backpressure

`avs_waitrequest_o` is asserted while reset is active and in every non-idle
adapter state. A request is accepted only while the adapter is idle and
`avs_waitrequest_o` is low.

Once accepted, the adapter latches address, direction, and write data. It then
owns that transaction until a response is emitted. This produces the following
properties:

- no second request can overtake the first request;
- read and write responses remain ordered;
- the shared response bus is never used for a read and a write response in the
  same cycle;
- native CSR request fields remain stable while `csr_valid_o` is waiting for
  `csr_ready_i`;
- the Avalon host must keep its request fields stable whenever waitrequest is
  asserted, as required by the surrounding Avalon contract.

Reset is fail-closed: waitrequest is high, leaf valid is low, and both response
valid outputs are low while `rst_n` is low.

## Validation order

For an asserted read or write, the adapter computes these conditions before
issuing a leaf request:

1. Read and write are not asserted together.
2. The full 21-bit address is inside the 4 KiB CSR window.
3. Address bits `[1:0]` are zero.
4. `avs_byteenable_i` equals `4'b1111`.
5. `avs_burstcount_i` equals one.

All conditions must pass. Any failure is completed locally and is never visible
at the CSR leaf.

Address classification owns the response-code precedence. An address outside
the 4 KiB window returns `DECODEERROR`, even when that transaction is also
malformed. An in-window alignment, byteenable, burst, or read/write-direction
violation returns `SLVERR`.

The response classifier defaults to `DECODEERROR` and overrides it only for an
unambiguous in-window address. This makes an unknown address fail closed in RTL
simulation instead of exposing an `X` response code. Parameter guards are repeated
at the adapter, HPS-bridge top, logical top, and board top for the required
`CSR_AVMM_ADDR_W >= CSR_ADDR_W >= 2` and `CSR_BURSTCOUNT_W >= 1` relationships.

## Response policy

The two-bit response values are the standard Avalon-MM encodings used here:

| Encoding | Name | Adapter use |
| ---: | --- | --- |
| `2'b00` | `OKAY` | Successful leaf completion. |
| `2'b10` | `SLVERR` | In-window malformed request, leaf error, or missing read-valid. |
| `2'b11` | `DECODEERROR` | Address outside the 4 KiB CSR window. |

The adapter implements one write response for each accepted write and one read
response for each accepted read. `avs_readdatavalid_o` and
`avs_writeresponsevalid_o` are mutually exclusive. An error read always returns
`32'h0000_0000`; stale CSR data is never exposed with an error response.

Simultaneously asserting read and write is a host protocol violation. The
adapter handles it deterministically instead of forwarding an ambiguous leaf
operation: the read response channel wins, exactly one response is emitted, and
no write response is emitted. An in-window dual assertion returns `SLVERR`; an
out-of-window dual assertion returns `DECODEERROR` because address classification
still takes precedence.

## Leaf timing contract

The native CSR side is intentionally bound to the current
`trecap_csr_bank` timing:

- `csr_valid_o` stays high until `csr_ready_i` accepts the request;
- request direction, 12-bit byte offset, and write data remain stable during
  that wait;
- the bank supplies its registered result one cycle after request acceptance;
- a successful read must assert `csr_rvalid_i` and provide `csr_rdata_i`;
- a write completes successfully when `csr_error_i` is low;
- a bank error becomes `SLVERR`;
- a read completion with neither error nor `csr_rvalid_i` is treated as a
  malformed leaf completion and becomes `SLVERR`.

The adapter returns zero data for writes and for all failed reads.

## State sequence

The implementation uses four states.

| State | Avalon behavior | CSR-leaf behavior | Exit condition |
| --- | --- | --- | --- |
| `IDLE` | waitrequest low; may accept one request | valid low | Legal request goes to `ISSUE`; rejected request goes to `RESPOND`. |
| `ISSUE` | waitrequest high | valid high with latched fields | `csr_ready_i` goes to `WAIT_RESULT`. |
| `WAIT_RESULT` | waitrequest high | valid low; sample fixed-latency result | Unconditionally capture the result and go to `RESPOND`. |
| `RESPOND` | waitrequest high; pulse exactly one response-valid | valid low | Return to `IDLE`. |

A locally rejected request skips the two leaf states. A legal request cannot
produce a response until the leaf result has been classified.

### Legal read example

```text
cycle edge E0: IDLE accepts aligned, full-width, in-window read
cycle E0-E1:   ISSUE drives stable csr_valid/address
cycle edge E1: CSR leaf accepts request
cycle E1-E2:   WAIT_RESULT observes registered leaf result
cycle edge E2: adapter captures data/response
cycle E2-E3:   RESPOND asserts readdatavalid with data and response
cycle edge E3: adapter returns to IDLE
```

### Local reject example

```text
cycle edge E0: IDLE accepts out-of-window request and pulses local_reject
cycle E0-E1:   RESPOND emits DECODEERROR; csr_valid remains low
cycle edge E1: adapter returns to IDLE
```

## Source integration completed in Step 5

The source hierarchy is connected as follows:

```text
rtl/top/trecap_de1soc_full_top.sv
    -> rtl/hps_bridge/trecap_hps_bridge_top.sv
        -> rtl/hps_bridge/trecap_avmm_csr_adapter.sv
            -> rtl/hps_bridge/trecap_csr_bank.sv
```

`trecap_de1soc_full_top` exposes the 21-bit Avalon CSR interface and passes it to
`trecap_hps_bridge_top`. The HPS bridge top instantiates the adapter, connects its
private request/result side to the CSR bank, and merges the adapter-local reject
pulse into CSR reject accounting.

Step 6 completes the source hierarchy above it:

```text
hps_0.h2f_lw_axi_master (raw HPS AXI3)
    -> Platform Designer AXI-to-Avalon adaptation
    -> trecap_csr_bridge.m0 (21-bit byte-addressed Avalon-MM)
    -> platform_designer_wrapper.sv
    -> de1_soc_trecap_top.sv
    -> trecap_de1soc_full_top.sv
```

The board top is source-connected and contains no safe-idle CSR stubs. The wrapper
passes every request and response field, including `response` and
`writeresponsevalid`, without narrowing the 21-bit address.

The adapter is included by the generated HPS bridge filelist, full DE1-SoC
filelist, and Quartus QSF include.

## Source connectivity completed; generated evidence pending

The checked-in Platform Designer source now instantiates `trecap_csr_bridge`,
connects the raw HPS lightweight AXI master to its Avalon slave side at offset
zero, and exports `trecap_csr_bridge.m0` as `trecap_csr_lw_master`. Qsys owns the
AXI-to-Avalon protocol conversion. The hand-written class `[1]` wrapper and board
top own the typed SystemVerilog connection.

`board_connectivity_complete` remains false because source connectivity is not
hardware evidence. Completion still requires a Quartus 20.1 normalized graph,
generated `system` HDL/QIP, `system.sopcinfo`, a successful Quartus compile, and
board bring-up evidence.

## Evidence boundary

Steps 5 and 6 are source-implementation milestones. The following evidence is
explicitly recorded as absent:

- no functional testbench or behavioral verification result;
- no Platform Designer generation/normalization result;
- no generated `system` module or verified flattened-port ABI;
- no SOPCINFO identity evidence;
- no Quartus compile report;
- no hardware read/write evidence.

`scripts/check_csr_adapter.py` is a structural/source-consistency gate only;
`scripts/check_platform_designer_wrapper.py` has the same evidence boundary.
They check frozen contracts, key RTL semantics, source graph and top-chain wiring,
filelist membership, and documentation. Passing them must not be presented as
functional verification or hardware signoff.

## Change control

Any edit to `trecap_avmm_csr_adapter.sv` changes its raw SHA-256 and intentionally
fails the Step-5 checker. A reviewed behavioral change must update together:

1. the RTL;
2. `avalon_csr_adapter.json` and its pinned hash;
3. `avalon_csr_adapter.schema.json` if the contract shape changes;
4. this document;
5. the structural checks; and
6. later Platform Designer/custom-component metadata that exposes the port.

Do not relax the 21-bit full decode, 32-bit access rule, single-outstanding rule,
or error-data-zeroing merely to make an integration shortcut compile.
