# Interface contracts

File class: **[1] hand-written architecture document**.

This document defines implementation-facing contracts between the T-RECAP Phase 2 layers. These contracts prevent the most common project failure: RTL, HPS C, Python dashboard, and reference artifacts silently using different constants, packet offsets, widths, or ownership assumptions.

## Authority

The integrated specification defines the baseline. This document expresses the interface rules used by the current implementation.

This document does not define verification monitors or scoreboards.

## Contract sources

### Hand-written or imported source-of-truth files

```text
spec/generated/core_config.json                              [0]
spec/generated/width_config.json                             [0]
spec/generated/artifact_contract.json                        [0]
spec/generated/csr_map.json                                  [1]
spec/generated/packet_layouts.json                           [1]
spec/generated/interface_types.json                          [1]
```

### Generated outputs

```text
rtl/include/generated/trecap_core_pkg.sv                     [2]
rtl/include/generated/trecap_csr_pkg.sv                      [2]
rtl/include/generated/trecap_packet_pkg.sv                   [2]
rtl/include/generated/trecap_iface_pkg.sv                    [2]
sw/hps/include/generated/trecap_csr.h                        [2]
sw/hps/include/generated/trecap_packet.h                     [2]
sw/pc_dashboard/generated/trecap_packet.py                   [2]
sw/reference_model/generated/trecap_config.py                [2]
```

Generated files shall contain an `AUTO-GENERATED - DO NOT EDIT` banner. Edits go to schema files or generator scripts, not generated outputs.

## Baseline constants

These constants are shown here for readability only. Implementation code shall consume generated packages/headers.

| Symbol | Meaning | Baseline |
| --- | --- | --- |
| `N` | External signed sample width | 12 |
| `L` | FFT length | 256 |
| `P` | Radix-2 stages | 8 |
| `H` | Hop size | 128 |
| `F` | Fractional precision | 15 |
| `G` | Scheduling cushion | 128 |
| `D` | Exact causal delay, `L + G` | 384 |
| `W_Qw` | Unsigned window coefficient width | 16 |
| `W_tw` | Signed twiddle coefficient width | 17 |
| `W_mag2` | Magnitude-squared and `THR2` width | 56 |
| `PROTECT_DC` | Force DC bin kept | 1 |
| `PROTECT_NYQ` | Force Nyquist bin kept | 0 |

## SystemVerilog package contract

Every RTL layer imports only the generated packages it needs.

```systemverilog
import trecap_core_pkg::*;     // core constants and widths
import trecap_csr_pkg::*;      // CSR offsets, bits, access semantics
import trecap_packet_pkg::*;   // packet IDs, payload sizes, flags
import trecap_iface_pkg::*;    // shared structs and interface field types
```

Rules:

```text
rtl/core/ should normally import trecap_core_pkg and trecap_iface_pkg only.
rtl/core/ shall not depend on packet IDs, CSR offsets, UDP sizes, or DDR ring layout.
rtl/telemetry/ may import packet constants but shall not import platform bus details.
rtl/hps_bridge/ may import CSR and packet constants.
HPS C and Python dashboard code consume generated headers/modules only.
```

## Core sample stream contract

The core consumes one signed sample tick stream. The preferred generated struct shape is:

```systemverilog
typedef struct packed {
    logic                         valid;
    logic signed [T_SAMPLE_W-1:0] data;
    logic [63:0]                  sample_idx;
} trecap_sample_t;
```

Contract:

```text
valid=1 means data and sample_idx are meaningful for one core clock.
sample_idx is the accepted sample index, not wall-clock time.
External source adapters map every source to signed N-bit samples before core entry.
Source adapters may drop or resample before the core only if the source-mode contract records it.
The core does not know whether the sample came from BRAM, LINE-IN, ADC, or diagnostic source.
```

## Frame event contract

Preferred generated struct shape:

```systemverilog
typedef struct packed {
    logic        valid;
    logic [63:0] frame_idx;
    logic [63:0] trigger_sample_idx;
} trecap_frame_event_t;
```

Contract:

```text
A frame event occurs every H accepted samples.
trigger_sample_idx identifies the sample-count boundary for the frame.
frame_idx starts at zero for a fresh stream interval.
Frame state shall reset or discontinuity-mark on source-mode changes.
```

## Core statistics contract

Step 8 makes the owner of low-rate telemetry statistics explicit. STATUS takes
`core_sample_count` and `core_frame_count` from the mathematical core; it shall
not infer either value from delayed sample/frame tap indices. METRICS snapshots
core-owned error sums, maximum error, and truncation status, while its eligible-
bin counts and energy totals remain telemetry-owned frame-tap aggregates.

Both aggregate owners share one epoch. A raw `CLEAR_METRICS` CSR request may be
queued, but only the applied pulse at a true frame boundary or structural core
idle may clear the core and telemetry states. Telemetry soft reset clears
formatter/FIFO state only and shall not silently create a new core metric epoch.
It is a synchronous `clk_fabric` clear, not a derived active-low reset.

The unique-bin index uses the explicit `BIN_IDX_W` parameter at every core-to-
telemetry instance boundary. `record_ready` terminates in telemetry and cannot
affect the normalized sample ready/valid path or the mathematical output sink.

`observation_epoch_reset` is distinct from telemetry soft reset. It suppresses
new packetizer admission on a source discontinuity, causing partial collections
to be dropped without clearing the FIFO or truncating an already-selected
record. Any unselected disabled candidate is drained locally, and that drain
decision remains latched until the candidate's final beat.

## Step-9/16/17 physical-board binding contract

The board top binds complete CSR and F2SDRAM request/response channels between
`platform_designer_wrapper` and `trecap_de1soc_full_top`; safe-idle substitutes
are forbidden. Audio and LTC2308 samples enter `trecap_source_core_integration`
through their platform wrappers. The source/core owner's real taps, counters,
safe boundaries, discontinuity, and metric-clear apply event feed the
telemetry/HPS owner directly.

Core-y monitoring is valid/data-only at this boundary: `y_ready_i` remains
always accept, and a full fabric-to-BCLK async FIFO drops/counts monitor samples
instead of throttling the core. Epoch tagging plus a synchronized flush event
prevents stale audio after disable, loss of codec readiness, or source
discontinuity. Complete LINE-IN frames cross through a separate BCLK-to-fabric
async FIFO. Step-17 LTC2308 conversion uses idle-low CONVST, a 40-ns active-high
pulse, a 1.84-us conversion-start-to-first-SCLK interval, twelve result clocks
at 2.5 MHz, and a six-bit configuration for the next conversion. The single-bit
off-chip DOUT return passes a preserved two-flop synchronizer before the 12-bit
word and valid are registered together in `clk_fabric`; `ADC_SCLK` is not an RTL
clock and no multi-bit ADC CDC is required after the wrapper. The switch-
selected configuration is latched on entry to the ADC source epoch and cannot
change within that epoch; re-entry re-primes and discards the old-configuration
result. Reset, disable, or abort also starts a 92-cycle recovery holdoff before
the wrapper can accept another CONVST request; an early request is rejected and
sets the request-overrun sticky.

The ADC scheduler is 100 ksample/s, distinct from 48 ksample/s BRAM/audio. The
board status/telemetry sample-rate input must report 100,000 only while
`TSRC_ADC_LIVE` is active and 48,000 otherwise. The ADC adapter recenters
unsigned straight-binary code at 2048; it does not change packet ABI or core
arithmetic. BRAM replay remains the reset/default correctness path.

## Step-10 clock/reset binding contract

The full-board implementation has one active 50 MHz fabric clock:

```text
CLOCK_50 -> clock_reset_ctrl -> clk_fabric -> every fabric owner
```

The hard-reset interface is:

```text
KEY[0] released and stable high for 20 ms
active-low generated system h2f reset
    -> clock_reset_ctrl combination
    -> one trecap_reset_sync with at least two stages
    -> rst_n_platform -> every fabric owner simultaneously
```

The HPS-to-FPGA reset is a global reset for the full-board fabric. This does not
make C0 HPS-dependent: C0 uses separate core-only tops without the board/HPS
reset boundary. The physical board top shall disable the logical top's optional
second reset synchronizer.

Sample, STATUS, METRICS, and heartbeat events are exact-average fractional
clock-enable pulses at 48 kHz, 10 Hz, 30 Hz, and 2 Hz-toggle respectively. They
shall never be treated as clocks. `CLOCK2_50`, `CLOCK3_50`, and `CLOCK4_50` are
reserved, and the source architecture does not support split fabric clocks.

The audio BCLK receive and transmit edge domains own separate synchronized reset
releases. Step 16 drives peripheral-only `AUD_XCK` at 12.288 MHz, programs the
WM8731 at `0x1a` over open-drain FPGA I2C, and gates the 48 kS/s, signed 16-bit,
codec-master I2S path on qualified lock, FPGA bus grant, and configuration done.
`HPS_I2C_CONTROL` must remain low while the FPGA owns the bus; FPGA logic never
drives it. The [physical timing contract](physical_timing.md) supplies the audio
I/O and CDC constraints; the exercised BRAM-profile native12 fit passed their
required checks. See the [implementation results](../results/fpga_implementation.md)
for the complete gate outcome. Physical I2C ACKs, measured clocks and live-audio
operation remain unqualified.

## Core statistics payload shape

Preferred generated struct shape:

```systemverilog
typedef struct packed {
    logic [31:0] unique_bins;
    logic [31:0] unique_suppressed_bins;
    logic [31:0] eligible_unique_bins;
    logic [31:0] eligible_suppressed_bins;
    logic [63:0] eligible_kept_mag2_lo;
    logic [63:0] eligible_total_mag2_lo;
    logic        mag2_truncated;
} trecap_frame_stats_t;
```

Contract:

```text
Counts use final post-protection mask semantics.
Protected bins are excluded from eligible denominators.
Low-word display counters may truncate; exact signoff counters live in artifacts.
If omitted high bits are known nonzero, payload_truncated shall be set in METRICS.
```

## Core tap interface contract

Core taps are valid-only observation points:

```text
core output tap_sample_valid
core output tap_x_delayed
core output tap_y_out
core output tap_error
core output tap_sample_idx
core output tap_frame_valid
core output tap_frame_idx
core output tap_mag2_unique_bins
core output tap_mask_unique_bins
core output tap_frame_stats
```

Rules:

```text
No telemetry signal shall drive ready into the core sample path.
No telemetry signal shall stall frame scheduling, FFT/IFFT, WOLA, or metrics.
If telemetry cannot accept a tap event, the event is dropped and counted.
Core taps observe already-computed signals; they do not compute core behavior.
```

## Ready/valid stream contract outside the core

Ready/valid is allowed outside the non-stalling core tap boundary.

Required naming convention:

```text
in_valid
in_ready
in_payload
out_valid
out_ready
out_payload
```

Rules:

```text
Ready/valid may be used between packetizers, FIFOs, and record builders.
Ready/valid shall not cross into core algorithm scheduling as backpressure.
Skid buffers are allowed in transport layers.
For CDC, use async FIFO or handshake, not independent bit synchronizers.
```

## Telemetry record interface contract

Preferred generated metadata shape:

```systemverilog
typedef enum logic [15:0] {
    TPKT_WAVE    = 16'h0001,
    TPKT_SPEC64  = 16'h0002,
    TPKT_SPEC129 = 16'h0003,
    TPKT_METRICS = 16'h0004,
    TPKT_STATUS  = 16'h0005,
    TPKT_WRAP    = 16'h007f
} trecap_packet_type_e;

typedef struct packed {
    logic                valid;
    trecap_packet_type_e packet_type;
    logic [15:0]         flags;
    logic [31:0]         seq;
    logic [63:0]         timestamp;
    logic [15:0]         payload_bytes;
    logic [1:0]          drop_priority;
} trecap_record_meta_t;
```

Contract:

```text
Metadata and payload commit shall be atomic at record boundary.
Internal payload_bytes may be 16 bits because legal Revision G payloads fit under the UDP bound.
DDR/UDP header field zero-extends payload_bytes to 32 bits.
Packet FIFO carries metadata plus payload bytes, or metadata plus a payload RAM reference.
```

Drop priority:

| Priority | Packet class | Behavior |
| --- | --- | --- |
| 0 | WAVE | Lowest priority; dropped first. |
| 1 | SPEC64/SPEC129 | Spectrum display; may be dropped before metrics/status. |
| 2 | METRICS | Higher value for live observability. |
| 3 | STATUS | Highest normal telemetry priority; dropped last. |

A priority-aware packet FIFO shall not drop an incoming higher-priority record while a lower-priority resident record is evictable.

## CSR interface contract

All CSRs are:

```text
32-bit aligned
32-bit accessible
little-endian
memory-mapped through HPS-to-FPGA bridge
```

Required access rules:

```text
VERSION reports major/minor transport version.
CSR map is normative, not recommended.
Multiword values use snapshot or commit mechanisms.
Independent low/high half live updates are invalid for pointers and thresholds.
Writes shall not tear active core behavior in the middle of a frame.
Threshold and source-mode updates use shadow/commit and safe boundaries.
Sticky flags use write-one-to-clear through CLEAR_STICKY_FLAGS.
CONTROL[3] is reserved and shall not be used as a second sticky-clear path.
```

The Step 5 platform-facing boundary is `trecap_avmm_csr_adapter.sv`. It accepts a
21-bit Avalon-MM **byte** address for the complete 2 MiB lightweight aperture and
performs the full decode before presenting a 12-bit byte offset to the private CSR
leaf. Only offset range `0x000000..0x000fff`, four-byte alignment,
`byteenable=4'b1111`, and `burstcount=1` are accepted. These rules apply to reads
and writes; the adapter does not emulate partial accesses with read-modify-write.

The adapter serializes requests so only one transaction is outstanding. It asserts
`waitrequest` while busy and during reset. Outside-window requests return Avalon
`DECODEERROR`; misaligned, partial, dual read/write, unsupported burst, and leaf
errors return `SLVERR`. An error read still produces exactly one zero-data
`readdatavalid`, and every accepted write produces exactly one
`writeresponsevalid`. Locally rejected requests never reach the CSR bank. See
`docs/architecture/avalon_mm_csr_adapter.md` for the exact timing and ownership
contract.

Step 6 connects that agent to the HPS without changing its contract. Platform
Designer converts raw lightweight AXI3 through `trecap_csr_bridge`; the wrapper
maps the complete Avalon request/response bundle to the board hierarchy. On the
DDR path, `trecap_f2h_sdram_bridge` presents a 32-bit byte address and 64-bit data.
The wrapper accepts any repository write at or above `0x40000000` locally, forwards no write, and
returns a registered `SLVERR` exactly one cycle later, preventing truncation or aliasing while
obeying Avalon-MM response timing. The ring writer blocks both its `done`-to-commit transition and
producer advance when that error is visible, so a rejected write cannot advance the ring pointer.

The adapter-local reject pulse enters the CSR bank on a dedicated input. It is
counted independently from the pre-existing grouped external/writer reject input,
so a simultaneous adapter and external rejection contributes two events without
double-counting a leaf-level rejection.

Critical CSR ownership:

| CSR class | Owner |
| --- | --- |
| `THR2_LO`, `THR2_HI`, `THR2_COMMIT` | HPS writes shadow; FPGA applies at frame boundary. |
| `SOURCE_MODE_SHADOW`, `SOURCE_MODE_COMMIT` | HPS requests; FPGA performs safe source transition. |
| `RING_BASE_*`, `RING_SIZE_BYTES`, `RING_CONFIG_COMMIT` | HPS configures while telemetry disabled. |
| `RING_WR_*_SNAP` | FPGA-owned producer pointer snapshot for HPS. |
| `RING_RD_*_SHADOW`, `RING_RD_COMMIT` | HPS-owned consumer pointer committed into FPGA. |
| `CORE_COUNT_SNAPSHOT` and snapshot counters | Coherent counter reads. |
| `PACKET_FIFO_DROP_COUNT` | Pre-writer telemetry/FIFO drops. |
| `DMA_DROP_COUNT` | DDR writer/ring-space/writer-policy drops. |

## 64-bit pointer transfer contract

Producer pointer read by HPS:

```text
1. HPS writes RING_WR_SNAPSHOT=1.
2. CSR bank latches full 64-bit producer pointer.
3. HPS reads RING_WR_LO_SNAP and RING_WR_HI_SNAP.
```

Consumer pointer write by HPS:

```text
1. HPS writes RING_RD_LO_SHADOW.
2. HPS writes RING_RD_HI_SHADOW.
3. HPS writes RING_RD_COMMIT=1.
4. FPGA writer consumes committed value through CDC-safe commit.
```

No independent low/high live pointer sampling.

## DDR ring record contract

All DDR telemetry records use a 32-byte common header:

| Offset | Field | Type | Rule |
| --- | --- | --- | --- |
| 0 | `magic` | `uint32_t` | Numeric little-endian `0x54524350`; do not compare raw ASCII bytes. |
| 4 | `version` | `uint16_t` | Header/protocol version; baseline 1. |
| 6 | `header_bytes` | `uint16_t` | Baseline 32. |
| 8 | `packet_type` | `uint16_t` | Generated packet type. |
| 10 | `flags` | `uint16_t` | Common flags; reserved bits zero. |
| 12 | `seq` | `uint32_t` | PC-visible sequence for normal telemetry only. |
| 16 | `timestamp` | `uint64_t` | Semantics depend on packet type. |
| 24 | `payload_bytes` | `uint32_t` | Valid payload bytes after header. |
| 28 | `header_crc` | `uint32_t` | Revision G disabled; must be zero. |

Alignment contract:

```text
Normal record length = align64(32 + payload_bytes)
Records start on 64-byte boundaries
Normal records shall not cross physical ring end
WRAP record consumes the full physical tail
Producer pointer is the only commit signal
FPGA completes all writes before updating producer pointer
HPS does not read past committed producer pointer
```

Ring pointer contract:

```text
W  = monotonic 64-bit producer pointer
Rd = monotonic 64-bit consumer pointer
R  = ring size, power of two, at least 1 MiB baseline expectation
B  = FPGA-visible ring base address
used = W - Rd
0 <= used <= R
physical_offset(p) = p & (R - 1)
```

Free-space contract when a record would cross the physical end:

```text
o = W & (R - 1)
Ttail = R - o
if o + Lrec > R:
    Lreq = Ttail + Lrec
else:
    Lreq = Lrec
Ffree = R - (W - Rd) - Gguard
write only if Ffree >= Lreq
```

Checking only `Ffree >= Lrec` is wrong when a WRAP record is required.

## Packet payload-size contract

| Packet | Type code | Payload size rule |
| --- | ---: | --- |
| WAVE | `0x0001` | `payload_bytes = 16 + 6 * nsamp`, `1 <= nsamp <= 192`. |
| SPEC64 | `0x0002` | Exactly 268 bytes. |
| SPEC129 | `0x0003` | Exactly 287 bytes. |
| METRICS | `0x0004` | Exactly 56 bytes. |
| STATUS | `0x0005` | Exactly 72 bytes. |
| WRAP | `0x007f` | Payload bytes exactly 0; DDR effective length is physical tail. |

Revision G UDP no-fragmentation limit:

```text
32 + payload_bytes <= 1200
```

One UDP datagram contains exactly one telemetry header and payload. DDR alignment padding is not sent over UDP.

## Packet flag contract

Common flags include:

| Bit | Name | Rule |
| --- | --- | --- |
| 0 | `payload_truncated` | Set when payload omits known nonzero high bits or display truncation is active. |
| 1 | `payload_scaled` | Reserved for scaled display values; METRICS baseline uses 0. |
| 2 | `aggregate_metrics` | METRICS aggregate class. |
| 3 | `per_frame_metrics` | METRICS per-frame class. |
| 4 | `crc_enabled` | Must be 0 in Revision G. |
| 5 | `status_diagnostic` | Legal only for HPS-synthesized diagnostic STATUS. |
| 15:6 | reserved | Must be zero. |

METRICS baseline rule:

```text
Exactly one of aggregate_metrics and per_frame_metrics shall be set.
payload_scaled shall be zero.
```

## Timestamp contract

| Packet | Timestamp meaning |
| --- | --- |
| WAVE | Sample index of first represented output sample; equals payload `sample_base`. |
| SPEC64/SPEC129 | STFT frame index. |
| METRICS | Frame index for per-frame metrics or latest frame in aggregate metrics. |
| STATUS | Current core sample count for FPGA-originated or HPS-patched STATUS. |
| WRAP | Ignored and should be zero. |

WAVE time-axis rule:

```text
represented_sample_index[i] = sample_base + i * stride
```

The PC dashboard shall not assume `stride = 1` unless the payload says so.

## HPS UDP streamer contract

HPS responsibilities:

```text
configure Ethernet
strictly validate the frozen runtime profile and exact live reserved-memory node
map the CSR window read/write and the DDR ring read-only with the supported synchronous/non-cacheable policy
perform telemetry reset and ring initialization
write FPGA-visible ring base address to CSR
read producer pointer by snapshot
validate record before forwarding
send exactly header plus payload as one UDP datagram, with no DDR padding or fragmentation
drop a complete record larger than 1200 bytes without fragmentation, then commit Rd
advance and commit the consumer pointer even if UDP send fails
receive commands and translate accepted commands into CSR writes
```

Cached userspace ring mappings are forbidden because the Step-13 reader has no
cache-invalidation path. `--dummy-udp-counter` is a separate UDP-only mode: it
maps neither CSR nor DDR and emits legal diagnostic STATUS datagrams with
`status_diagnostic=1`, `seq=0`, and monotonic timestamp/sample count.

HPS shall validate at minimum:

```text
magic
version
header_bytes == 32
known packet type
complete header and body lie below the committed producer boundary
reserved flags zero
packet-specific legal flags
exact fixed payload size or bounded WAVE payload size, derived in 64-bit arithmetic
WAVE timestamp/sample base, channels, sample count, stride, and reserved fields
METRICS timestamp and exactly one metrics-class flag
STATUS timestamp and reserved field
SPEC64/SPEC129 bin count, shift, and unused mask bits
normal record does not cross ring boundary
WRAP has zero payload, valid sequence, zero tail padding, and consumes the exact physical tail
header_crc == 0
```

Malformed baseline policy:

```text
on the first incident, enter MALFORMED_LATCHED and increment the counter exactly once
disable telemetry and the ring writer, then recommit the unchanged current Rd once
do not reparse, recount, recommit, or byte-scan the bad record
remain alive for diagnostics by default
resume only after soft reset, ring reconfiguration, Rd=0 commit, zero-W verification, and normal re-arm
```

`--stop-on-malformed` is a debug-only exit-code-3 override; it does not weaken
the latch. Local consumer and forwarded accounting change only after the CSR
consumer commit succeeds.

## PC command contract

Command packet length:

```text
28 bytes
```

Command header:

| Offset | Field | Type | Rule |
| --- | --- | --- | --- |
| 0 | `magic` | `uint32_t` | Numeric little-endian `0x54524343`. |
| 4 | `version` | `uint16_t` | `1` for exact Revision-G baseline or `2` for the explicit Step-14 extension. |
| 6 | `cmd_type` | `uint16_t` | Generated command type. |
| 8 | `seq` | `uint32_t` | PC command sequence. |
| 12 | `arg0` | `uint32_t` | Command-specific. |
| 16 | `arg1` | `uint32_t` | Command-specific. |
| 20 | `arg2` | `uint32_t` | Command-specific. |
| 24 | `crc32` | `uint32_t` | Revision G disabled; must be zero. |

Exact version-1 command types:

| Code | Name | Required action |
| ---: | --- | --- |
| `0x0001` | `SET_THR2` | Write low/high shadow, then pulse `THR2_COMMIT`; upper bits beyond bit 55 zero. |
| `0x0002` | `CLEAR_METRICS` | Pulse `CONTROL.clear_metrics`; arguments zero. |
| `0x0003` | `SET_SOURCE_MODE` | Valid source mode only; source-mode change rule applies. |
| `0x0004` | `SET_PACKET_ENABLE` | Reserved bits zero; PEAKS/DEBUG disabled in baseline. |
| `0x0005` | `SET_WAVE_DECIM` | `1 <= decim <= 65535`. |
| `0x0006` | `SET_SPEC_SHIFT` | Baseline `0 <= shift <= 55`. |
| `0x0007` | `PING` | Return STATUS only; no undefined ACK packet. |

Version 1 remains exactly these seven commands and defines no generic result.
Version 2 accepts them and adds:

| Code | Name | Arguments |
| ---: | --- | --- |
| `0x0008` | `SET_SPEC_MODE` | `arg0=0..2`; rest zero. |
| `0x0009` | `SET_TELEMETRY_ENABLE` | `arg0=0/1`; rest zero. |
| `0x000A` | `CONFIGURE_DDR_RING` | all zero; use validated local geometry only. |
| `0x000B` | `RESET_TRANSPORT` | all zero. |
| `0x000C` | `CLEAR_COUNTERS` | all zero. |
| `0x000D` | `START_BRAM_REPLAY` | all zero. |
| `0x000E` | `READ_STATUS_VERSION` | all zero; return raw STATUS/VERSION as `NOOP` even when incompatible; only read failure is `FAILED`. |

Every version-2 non-PING request produces an exact little-endian 32-byte
result: `magic=0x54524352` at offset 0, version 2 at 4, command type at 6,
sequence at 8, disposition at 12, reject reason at 16, raw `STATUS` at 20, raw
`VERSION` at 24, and zero CRC at 28. Dispositions are `APPLIED=0`, `NOOP=1`,
`REJECTED=2`, and `FAILED=3`; reject reason values are generated. A byte-identical
duplicate returns the byte-identical cached result. Same-sequence/different-byte
requests conflict; stale or RFC1982-ambiguous requests reject. These rules also
cover `READ_STATUS_VERSION`.

PING in either version ignores arguments and returns one fresh diagnostic STATUS
with `seq=0`; it performs no CSR operation, emits no result, and has no sequence
ledger/cache effect. The production listener binds `192.168.10.2:5006` and
matches `192.168.10.1:5007` exactly. Wildcard bind/peer learning is explicit
lab/test policy only.

`CONFIGURE_DDR_RING` never takes a network-supplied address. Enable follows
RESET-to-CONFIGURE-to-ENABLE. Source mode, packet enable, wave decimation,
spectrum mode, and spectrum shift mutations in both versions require controls
disabled, `transport_epoch_idle`, no replay busy/pending, verified CSR apply and
readback, then verified safe restore; direct live CSR writes are rejected.

RESET is not an implicit replay abort. It writes `REPLAY_CONTROL.rearm` only
when a failed, quiescent epoch reports `rearm_required`; a healthy reset writes
no replay control. Pending/active/path-busy/E2E-busy state rejects RESET, and a
successful rearm must preserve `result_epoch` while clearing all retained replay
result/error flags.

HPS shall also reject bad length, magic, version, CRC, type, exact peer, ranges,
reserved arguments, unsafe lifecycle/replay state, sequence, CSR/readback, I/O,
timeout, reset-required, and identity/version conditions according to generated
reason constants. The complete contract is
`docs/architecture/de1soc_command_path.md`.

Before returning `NOOP` or `APPLIED`, every command other than PING and
`READ_STATUS_VERSION` must verify the generated CSR ID and VERSION 1.8. PING has
no CSR access. `READ_STATUS_VERSION` deliberately bypasses identity rejection so
the PC can inspect raw STATUS/VERSION from a stale image; read failure alone is
`FAILED`.

## STATUS ownership contract

FPGA-originated STATUS may contain FPGA-owned fields. HPS may patch only the local outgoing UDP copy of a STATUS packet with HPS-owned counters:

```text
udp_send_error_count
malformed_record_count
oversized_record_count
combined command_reject_count
sequence_gap_count
```

Rules:

```text
HPS shall not patch committed DDR ring contents.
HPS shall not patch WAVE, SPEC64, SPEC129, or METRICS payloads.
HPS-synthesized diagnostic STATUS sets status_diagnostic, uses seq=0, and is excluded from sequence-gap detection.
```

## PC dashboard contract

The dashboard parser shall:

```text
import generated trecap_packet.py
reject malformed headers and invalid payload sizes
track modulo-2^32 sequence gaps for normal telemetry
ignore WRAP and HPS diagnostic STATUS for sequence-gap detection
display dma_drop_count and packet_fifo_drop_count separately
show kept-energy ratio as N/A when eligible_total_mag2 is zero
```

The GUI shall not redraw on every UDP packet. It should parse in a receiver loop and redraw the UI at roughly 20-30 Hz.

## Clock and reset contract

Required naming:

```text
clk
clk_core
clk_csr
clk_avmm
rst_n
```

Rules:

```text
Reset deassertion is synchronized per clock domain.
No multi-bit signal crosses domains by independent bit synchronization.
Use async FIFO, snapshot/commit handshake, Gray-coded counter protocol, or documented equivalent.
HPS-written controls that affect the core use shadow/commit or safe-boundary update.
Counter reads use snapshots.
```

## Interface acceptance checklist

```text
[ ] Generated SV/C/Python constants exist and contain do-not-edit banners.
[ ] rtl/core/ does not hard-code CSR offsets or packet payload sizes.
[ ] HPS C includes generated CSR/packet headers.
[ ] Python parser imports generated packet constants.
[ ] Core taps are valid-only and non-stalling.
[ ] DDR ring writer owns producer pointer commit.
[ ] 64-bit ring pointers use snapshot/commit.
[ ] STATUS payload is 72 bytes in baseline.
[ ] METRICS payload is 56 bytes and has exactly one metrics-class flag.
[ ] UDP datagrams carry one record and no DDR padding.
[ ] PC commands are exactly 28 bytes and validated before CSR writes.
```
