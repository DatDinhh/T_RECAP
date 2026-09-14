# Storage and cycle schedule

We use synchronous embedded-memory ports for the frame history, WOLA workspaces,
error-alignment history, and telemetry payload queue. Their arrays have explicit
`ramstyle = "M10K"` attributes. Control registers carry validity, ownership, and
outstanding-read metadata; payload RAM has no asynchronous or full-array reset.
The schedules below are implementation contracts, not simulation results or a
Quartus fitted-resource report. Backpressure can extend every streaming interval.

## Storage allocation

Default dimensions come from `rtl/include/generated/trecap_core_pkg.sv` and each
module's public parameters. The input ring and delayed history store the complete
64-bit logical index with every 12-bit sample.

| Owner | Physical array declared in RTL | Logical bits | Ports and initialization |
| --- | --- | ---: | --- |
| Board replay ROM | 4096 x 12 | 49152 | One synchronous read; configuration-time vector initialization |
| Input frame ring | 512 x 76 | 38912 | One write and one synchronous read; reset 512 validity bits only |
| Delayed-x history | 1024 x 76 | 77824 | One write and one synchronous read; empty occupancy invalidates old words |
| WOLA accumulator | 384 x 37 | 14208 | One read and one write; 384 sequential zero writes after reset/clear |
| WOLA synthesis frame | 256 x 36 | 9216 | One write and one synchronous read; complete ordered frame overwrites every word before use |
| WOLA window ROM | 256 x 16 | 4096 | One synchronous read; configuration-time initialization from `window_qw.memh` |
| Telemetry packet payload | 2700 x 32 | 86400 | One write and one synchronous read; nine ownership slots, no payload reset |
| DDR record-builder payload | 292 x 32 | 9344 | Phase-exclusive capture write and synchronous read; no full-record buffer |

These eight arrays contain **289152 logical bits** at the board replay depth. A conservative allocation using
512 x 20 slices is 8 + 4 + 8 + 2 + 2 + 1 + 12 + 2 = **39 M10K blocks**. This is a
resource-planning allowance for these stores; the compiler can choose a denser
legal geometry. It excludes the transform/canonicalizer memories,
other coefficient ROMs, audio FIFOs, arithmetic registers, and all control logic.
The array attributes and clocked ports choose the intended memory implementation.
The BRAM-profile native12 fit reported 55 M10K blocks for the complete board,
including true-dual-port FFT/IFFT work memories. This fitted total is distinct
from the conservative allowance for the eight stores above. The
[implementation results](../results/fpga_implementation.md) record the fitted
resources and timing; these reports do not establish functional or board operation.

## Deterministic replay ROM

`rtl/sources/trecap_bram_replay_source.sv` uses a synchronous M10K ROM initialized
from the existing selected `x_in.memh`. Vector bytes and the configuration-time
zero initialization are unchanged. Board integration overrides the reusable
module's 65536-word default with 4096 words. The larger module default contains
786432 logical bits and needs a separate resource allowance when instantiated;
the board table above does not silently budget that larger geometry.

The source has two elastic stages: a ROM response with its logical index and
input/flush flag, followed by the existing output holding register. A read can
replace a response on the edge that the prior response moves forward. After
initial latency, continuous readiness therefore accepts one sample per clock,
matching the prior issue cadence. If start is accepted at edge 0 with enable and
ready continuously asserted, the first ROM read occurs at edge 1, the first output
is presented after edge 2, and the first sample is accepted at edge 3. The finite
N-sample stream finishes on acceptance at edge `N+2` under those conditions.

Backpressure holds the output unchanged and permits at most one prefetched
response behind it. `next_issue_idx_o` still counts issued logical samples and can
now lead the accepted count by two. `enable_i=0` pauses new issues while preserving
already issued samples; clear/reset cancels both stages and resets stream indices.
The done/last pulses belong exclusively to acceptance of the final logical sample,
so an unread ROM response cannot complete a replay prematurely.

Indices below `INPUT_SAMPLES` read the ROM. The configured `FLUSH_SAMPLES` follow
as zero-valued response tokens without any ROM read or address wrap. This source
preserves its finite stream contract; the integration layer's frame/drain policy
continues to decide how those source tokens feed the mathematical core.

## Transform workspaces

The transform and canonicalizer schedules are defined in
[transform_microarchitecture.md](transform_microarchitecture.md). FFT uses a
256 x 56 true-dual-port work RAM, IFFT uses 256 x 72, and the canonicalizer uses
256 x 56. Their payload arrays and RAM read-data registers have no reset. Ordered
frame admission writes every location before computation/output can begin.

Each FFT/IFFT butterfly has seven scheduled clocks: dual-port work/twiddle read,
four-product launch, product pre-add, twiddle rounding, butterfly add/subtract,
final rounding, and two-address writeback. Output uses two clocks per complex
sample. With an unstalled one-sample-per-clock input, each transform occupies
`L + 7*(L/2)*log2(L) + 2L = 7936` clocks inclusive of its first input acceptance
and last output acceptance. The canonicalizer has a four-clock READ/PRE/ROUND/EMIT
sequence per output and an inclusive `L + 4L = 1280` clock schedule. Real integration
can deliver input beats more slowly; these local counts are not a sum-proof of
whole-pipeline latency.

## Input frame extraction

`rtl/core/trecap_input_ring.sv` packs `{absolute_index, sample_bits}` in each RAM
word. Physical address is the low bits of the sample index. The power-of-two
512-entry ring covers the 256-sample frame and the scheduler's accepted look-ahead
sample. Source admission stops while a frame request, read, or output is active,
so extraction never races a ring overwrite.

Each output uses two stages:

1. Issue a synchronous RAM read and retain its signed 65-bit logical index,
   offset, frame index, last flag, and validity bit.
2. Compare the returned 64-bit tag and place the sample in the output register.
   Negative logical indices produce zero without reading RAM. A nonnegative
   missing/mismatched entry produces zero and raises the sticky overflow status.

A read reserves the output register while that register is free or its prior
sample is being accepted. The response cannot overwrite a stalled sample. With
continuous downstream readiness, accepted output samples are two clocks apart.
If the frame request is accepted at edge 0, the first sample is accepted at edge
3 and the final sample at edge `2L+1 = 513`. Full reset or `clear_i` cancels all
pending/output tokens and clears the validity bitmap. Old RAM words cannot become
valid merely because a new stream reuses index zero.

## Synthesis WOLA

`rtl/core/trecap_synthesis_wola.sv` implements this fixed sequence:

1. `SCRUB`: write zero to one of the `D=384` OLA addresses each clock. Scrubbing
   runs even with processing disabled. `busy_o` stays high and input/drain ready
   stay low until the final write completes. Holding clear restarts the scrub;
   384 subsequent rising edges complete initialization.
2. `COLLECT`: accept an ordered IFFT frame. The synchronous window lookup feeds a
   registered full-width signed product, then the existing round/saturate operator
   writes `z[i]`. This pipeline accepts one input per clock and drains for two
   clocks after the last accepted input. No z word is read before all L writes
   complete. The window remains unsigned: multiplication uses its zero-extended
   signed representation.
3. `EMIT_READ` / `EMIT_CAPTURE`: read the mature OLA location, round/saturate it to
   the output width, and clear that location through the RAM write port. Advance
   the read pointer only when the response is placed in the reserved output
   register. Emit H samples before adding the new frame.
4. `ADD_READ` / `ADD_WRITE`: read both `OLA[(rd+G+i) mod D]` and `z[i]`, then write
   the saturated sum on the following edge. Repeat for all L frame offsets.
5. At a finite-stream boundary, `DRAIN` / `DRAIN_CAPTURE` accepts exactly D drain
   ticks and reads, emits, and clears the remaining locations. The final done
   pulse follows acceptance of the final held output, not merely its RAM read.

For each legal frame, real-part multiplication widths, ties-away-from-zero
rounding, saturation widths, emit-before-add order, wrap addresses, and output
indices are unchanged. A nonzero IFFT imaginary residual raises the existing
protocol status while real-part synthesis continues. Malformed IFFT-input offset/last/frame
sequences or disabling an active transaction enter a fail-stop state; a full clear
is required before another epoch can use the partially written workspace.

With continuous input and output readiness, the interval between the first
accepted sample of a frame and the earliest first accepted sample of the next is
`L + 2 + 2H + 2L = 1026` clocks. WOLA emits one output every two clocks and performs
one overlap-add update every two clocks. The final output of a frame may still be
held while the add pass runs; the holding register preserves it. From the first
accepted drain tick to the final accepted output, an unstalled D-tick tail takes
`2D = 768` clocks. Entering the drain state adds one clock before the first tick
can be accepted. These are local block schedules; the full pipeline budget also
includes upstream frame/transform service and downstream error alignment.

## Delayed-x and error metrics

`rtl/core/trecap_delay_error_metrics.sv` uses an ordered tagged FIFO rather than an
index cache. Admission enforces consecutive x and y indices. For `y_index < D`,
the delayed reference is zero; later outputs require the FIFO head tag to equal
`y_index-D`. Empty history cannot be read, and a full FIFO never borrows credit
from a simultaneous pop, so legal traffic cannot read and write the same address.

A y request issues its history RAM read on the acceptance edge. Its metadata waits
for the one-cycle response and exact tag match. The response is retained locally
if downstream backpressure prevents the metric/output commit. The next y request
can replace the pending request on its commit edge, supporting one sample per
clock once flowing. A request accepted at edge 0 can populate the output register
at edge 1 and be accepted downstream at edge 2. Counter/metric updates remain at
that existing commit boundary.

Full clear resets FIFO pointers, occupancy, expected indices, pending validity,
and output validity. It also cancels RAM response validity; RAM contents and the
RAM read-data register are untouched. `clear_metrics_i` preserves the alignment
history and clears aggregate metrics under the existing control contract.

## Telemetry payload slot queue

`rtl/telemetry/trecap_packet_fifo.sv` retains eight admitted records and one
partially captured record in nine payload slots. At the default 32-bit beat width,
each slot contains `ceil(1200/4)=300` words. The single flat 2700-word RAM has the
address `slot_id * 300 + word_offset`. Queue entries contain only record metadata,
payload length, and slot ID. Pop and priority eviction compact these small entries;
payload words remain at their original addresses.

The first accepted beat reserves a free slot. Legal non-final beats have all keep
bits set; a legal final beat has nonempty contiguous low keep bits. Consequently,
valid records can be written one full RAM word per accepted input beat without a
byte-shuffling buffer. Malformed or oversized records are drained through their
last beat and dropped once. The byte counter saturates on overflow, and the sticky
malformed flag prevents wrapped lengths from admitting an oversized record.

Admission publishes the reserved slot only after capture and metadata validation
complete. When the resident queue is full, the existing priority helper selects
the oldest record among the lowest priorities below the incoming record. The
resident head stays protected throughout RAM read latency and output stalls. An
eviction releases only the victim's slot; a dropped incoming record releases its
reserved slot. Every output-pop/admission conflict waits for the pop first, so the
admission decision sees the available space.

The output port uses a synchronous read plus an output holding register. Metadata,
keep bits, and last flag travel with the read; unused final-beat bytes are zeroed.
Each accepted non-final beat can issue the next read on the same edge, giving one
accepted beat every two clocks. A record boundary adds one clock because the next
head is selected after the previous head is popped. From admission to its final
accepted output, an otherwise empty unstalled B-beat record takes `2B+1` clocks.
Input capture accepts one beat per clock and then uses one admission clock; a
coincident final output pop adds at most one further admission clock. Upstream
payload gaps and downstream stalls extend these bounds.

Metadata data fields remain connected to the output holding register when
`out_valid_o=0`; they are inactive values and consumers must ignore them.
`out_meta_o.valid` is qualified by `out_valid_o` and remains zero while inactive.
Record admission and payload acceptance require the ready/valid handshake.
This keeps combinational flush control out of downstream payload-length arithmetic
without adding a cycle or changing valid-beat metadata, flush, or drop behavior.

Reset/flush clears ownership, queue count, capture state, and output/read-valid
state. It does not clear payload RAM. A slot cannot be read until its declared
bytes have been freshly captured and admitted, and a flush cancels outstanding
read responses. Capture and output always own different slots, so their RAM ports
have no legal same-address read/write dependency. The payload queue therefore
uses 86400 RAM bits plus small stream/control registers instead of a resettable
86400-bit payload shift structure. This changes internal latency without changing
record framing, priority policy, drop accounting, or the external ready/valid ports.

## Source sequence and packet metadata timing

The live supervisor in
[trecap_source_core_integration.sv](../../rtl/top/trecap_source_core_integration.sv)
stores the expected next raw sequence on the existing raw-sample update edge.
The register replaces the previous last-sequence register and maintains
`expected = last + 1` modulo `2^64`: reset seeds one, a raw sample accepted by
that supervisor branch stores `raw_sequence + 1`, and every guard, fault and idle
branch retains the value. The first-sample exemption and all update conditions
remain unchanged. In particular, a sequence wrapping from all ones to zero is
accepted as before, while a repeated saturated all-ones sequence faults. The
comparison still raises the same-cycle fault and source-epoch clear; there is no
additional detection or source-handshake latency.

The physical board also selects `USE_WRAPPER_DROP_ADVANCE=1`. Its
[ADC wrapper](../../rtl/platform/de1soc/adc_wrapper.sv) and
[audio wrapper](../../rtl/platform/de1soc/audio_codec_wrapper.sv) register a
counter-advance output on the same edge that updates the corresponding drop
counter. The pulse is high only when that counter increases; an event at its
saturated maximum does not assert the pulse. Audio's existing overflow event
has priority over a same-edge sticky clear and increments the old counter value;
the pulse follows that same priority. A clear without an event lowers the counter
and leaves the pulse low. Both wrappers and the supervisor share the fabric clock
and reset, so each pulse equals the former `current_count > prior_count` fault
predicate during the following cycle, with no additional fault latency.

The supervisor's generic parameter default remains zero and retains the original
comparison of its counter inputs. Lifetime counts continue to use the original
full-width counter comparisons, differences and saturating accumulation in either
mode. Only the board fault-control dependency uses the producer flag; rearm,
source gating and health fault priority are unchanged.

[STATUS](../../rtl/telemetry/trecap_status_packetizer.sv) and
[METRICS](../../rtl/telemetry/trecap_metrics_packetizer.sv) expose their registered
metadata data fields continuously, using the same inactive-field contract as the
packet FIFO. Only `out_meta_o.valid` is qualified by `out_valid_o`; the existing
output-valid expressions, formatter-reset priority, payload stream and state
transitions are unchanged. Their only production consumer is the packet
scheduler. Candidate selection, illegal/disabled draining, record locking, drop
accounting and FIFO input acceptance all require the source valid signal or its
qualified handshake, so inactive data fields do not admit a record.

Native11 reported a 29.128 ns data path from the previous last-sequence register
through live-fault control, STATUS metadata masking, scheduler payload validation
and FIFO RAM write enable. Precomputing the sequence increment and keeping
registered metadata independent of valid/flush remove those serial dependencies.
The changes require a new fitted timing report; source compilation alone does
not establish timing closure or functional correctness.

## Waveform payload addressing

[trecap_wave_packetizer.sv](../../rtl/telemetry/trecap_wave_packetizer.sv)
retains full-width offset checks for header selection and the first byte beyond
`16 + 6*192 = 1168`. Only an offset inside that bound reaches sample addressing.
Its delta from the 16-byte header is 0..1151 and fits `PAYLOAD_OFF_W=11`, derived
from the maximum payload size. Other compile-time geometries retain explicitly
width-bounded quotient and remainder operators.

The 11-bit baseline computes the sample index as `(n*683) >> 12`, using a
22-bit unsigned product. For every 11-bit input, write `n=6q+r`, where `0<=r<6`.
Then `n*683=4096q+2q+683r`; the residual is at most 4095 because `r=5`
implies `q<=340`, and smaller remainders are also below 4096. Thus the selected
product bits equal `floor(n/6)` without a general divider or correction step.
The field offset is computed independently: split `n=2h+b`, sum the five radix-4
digits of `h`, and decode that sum modulo three. Since `4=1 mod3` and the digit
sum is at most 15, four-bit additions and a small case decode produce
`2*(h mod3)+b = n mod6`. This preserves all six byte positions in each sample
triplet. Header bytes, out-of-range zeros, payload order and handshake latency
are unchanged; neither path adds state or a pipeline stage.

The shared WAVE payload-length predicate in
[trecap_build_pkg.sv](../../rtl/include/trecap_build_pkg.sv) uses the same parity
and radix-4 identity to recognize integral six-byte triplets. Its full-width
minimum/maximum byte checks precede the narrow predicate. The digit-sum membership
set is `0,3,6,9,12,15`; no baseline modulo operator remains in this validation path.

Native11 synthesis confirmed that the preceding narrowing reduced the eight WAVE
quotient/remainder instances to 11-bit numerators, but its owner timing report
still found a -6.814 ns path through WAVE addressing into FIFO payload data.
The constant-product/radix-4 implementation therefore still requires its own
synthesis and fitted reports before resource or timing closure can be claimed.

## Spectrum bucket capture

The 129-bin/64-bucket baseline maps bins 0..127 with `bin >> 1` and maps
bin 128 to bucket 63. This equals `floor(((bin+1)*64-1)/129)` over the
accepted bin domain: bins `2q` and `2q+1` map to `q` for `q=0..63`,
and the final bin shares bucket 63. A constant geometry branch in
[trecap_spec_packetizer.sv](../../rtl/telemetry/trecap_spec_packetizer.sv)
retains the generic formula for other compile-time geometries. The baseline
capture path therefore needs no division by 129. Native10's fitted path through
that divider had 32.612 ns total data delay; this source change requires a new
fitted report before any timing improvement can be claimed.

On the first accepted bin, capture unconditionally seeds the bucket magnitude,
suppressed/eligible counts and first SPEC129 mask byte after the same-edge clear.
The SPEC129 magnitude is also assigned directly. Reading an array value while
scheduling its nonblocking clear would otherwise compare or increment the previous
frame's value. Later bins retain the existing maximum/count updates. This change
adds no state or cycles and preserves the valid-only tap interface, frame-order
checks, last-bin handling, drop policy and completed-record output behavior.

## Ring query state

[trecap_ring_pointer_ctrl.sv](../../rtl/hps_bridge/trecap_ring_pointer_ctrl.sv)
caches configuration legality on the same edge as the configuration fields.
Both reset paths clear the cached bit; a configuration commit evaluates the same
legality function on the incoming configuration, and all other cycles retain both
configuration and legality. Pointer, consumer-commit and snapshot behavior is
unchanged. The cache removes the size-minus-one and power-of-two check from each
query without adding a configuration-apply cycle.

Record length legality, tail crossing, required bytes and available-space fit
are calculated from candidate metadata and registered ring state before applying
`schedule_valid_i`. Qualified legality and public crossing/required/fit results remain zero
for an invalid query. The normal-address mux selects after address addition:
a crossing selects the base address; otherwise it selects base plus current
offset, including invalid queries. This is the original unsigned 64-bit address
arithmetic and preserves every valid-query result without adding registers,
changing the ring layout or moving pointer/sequence commits.

## DDR header, payload, and padding stream

`rtl/hps_bridge/trecap_ddr_record_builder.sv` stores one validated input record's
payload in a 292 x 32 M10K RAM at the default interface widths. Capture is one
32-bit word per accepted beat. The same keep/length rules as the packet FIFO make
all non-final writes aligned. Malformed streams are drained and dropped; their
length counter saturates and cannot wrap into an admissible record.

After capture, the BUILD boundary validates metadata and byte counts, snapshots
the writer-supplied sequence, creates the 32-byte common header, and pulses
`out_record_start_pulse_o`. CRC remains disabled: CRC-enabled input flags are
rejected and the header CRC field is zero, as required by the existing contract.
WRAP uses the existing zero sequence/timestamp/payload header and validated
physical-tail length. No sequence or producer-pointer commit moves into this block.

Emitted record length and offset use `$clog2(RECORD_STORE_BYTES+1)` bits, equal to
11 in the baseline. The constant addition is evaluated in 64 bits, including when
the public 32-bit maximum is all ones. Incoming normal and WRAP lengths pass their
original full-width bounds before entering these registers. The terminal-beat
comparison also widens the offset before adding the beat length, so large generic
records cannot lose that carry. Only a nonterminal accepted beat advances the
stored offset, and its next value remains strictly below the admitted length.
Reset/clear still zero both registers; record completion still zeros the offset.

The builder retains a 256-bit header, one input-width payload cache, and one
output-width holding register. It assembles each outgoing beat one byte per clock:
header bytes come from the header register, payload bytes come from the cache, and
padding bytes are generated as zero. A missing payload word takes a synchronous
RAM read and one cache-capture edge before assembly resumes. Payload words are
read once in ascending order; the cache survives output-beat boundaries. The
assembled output and record metadata stay fixed while valid waits for ready.
`out_record_done_pulse_o` occurs only on acceptance of the final output beat.

For a P-byte payload and R-byte aligned record, the interval from the start pulse
to final accepted output is `R + 2*ceil(P/IN_BEAT_BYTES) + ceil(R/OUT_BEAT_BYTES)`
clocks with continuous output readiness. At the default 32-bit input/64-bit output,
the maximum legal P=1168, R=1216 case takes 1952 clocks after that pulse. Capture
adds `ceil(P/4)` accepted-input clocks plus the BUILD edge; input gaps and DDR
backpressure add their actual wait cycles. WRAP has no payload reads and therefore
uses `R + ceil(R/8)` clocks after its start pulse at the default output width.

Reset, clear, or disable cancels capture, assembly, and cache validity. No payload
RAM word or RAM read-data register is reset. A later normal record can enter BUILD
only after its declared payload has been freshly captured; a WRAP never reads the
payload store. This replaces the previous 9344-bit capture vector plus 9728-bit
record vector with 9344 RAM bits and small header/cache/output registers. Header
serialization and zero padding require no full-record copy or full-record mux.
