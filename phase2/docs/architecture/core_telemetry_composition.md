# Core plus telemetry composition

File class: **[1] hand-written Step-8 architecture contract**.

## Purpose and current status

Step 8 turns `rtl/top/trecap_core_telemetry_top.sv` into a real reusable
composition. The module owns exactly one mathematical core and exactly one
telemetry formatter:

```text
normalized sample ready/valid
    -> trecap_core_top
       |-> y ready/valid output
       |-> core status, counters, and safe-boundary outputs
       `-> valid-only sample/frame/unique-bin observation taps
              -> trecap_telemetry_top
                 -> packetizers
                 -> record-atomic scheduler
                 -> one priority-aware packet FIFO
                 -> formatted record ready/valid output
```

Before Step 8, the file named `trecap_core_telemetry_top.sv` was only a shell
around `trecap_telemetry_top`; it accepted taps from some other core. That was
not a core-plus-telemetry composition. The corrected boundary accepts the
normalized sample stream and core controls, instantiates `trecap_core_top`, and
connects the resulting taps directly to `trecap_telemetry_top`.

This milestone is **source-only**. Static contract checks can prove that source
files and ownership relationships are present. It is not functional
verification, an RTL compile, simulation, Quartus compile, timing closure, or
hardware evidence.

## Ownership boundary

`trecap_core_telemetry_top` owns composition, not the internals of either layer.

It may:

- instantiate one `trecap_core_top`;
- instantiate one `trecap_telemetry_top`;
- connect real core taps and authoritative counters to telemetry;
- pass through the core y stream, core state, taps, and formatted record stream;
- maintain composition-level telemetry status such as W1C overflow reporting.

It may not:

- duplicate any packetizer, scheduler, or packet FIFO;
- add a second formatted-record queue;
- write DDR, generate WRAP records, or allocate transport sequence numbers;
- instantiate Platform Designer, own board pins, or implement Ethernet;
- make telemetry ready state part of core input or y-output flow control.

The mathematical implementation stays in `rtl/core/trecap_core_top.sv`. Packet
formatting and pre-writer shedding stay in
`rtl/telemetry/trecap_telemetry_top.sv`.

## Public composition boundary

The reusable top accepts these classes of input:

- `clk` and `rst_n`;
- core enable, datapath clear, sticky clear, and metrics clear controls;
- normalized `sample_i`, `sample_valid_i`, and core-owned `sample_ready_o`;
- `thr2_i` and source-discontinuity control;
- finite-stream frame geometry and WOLA-only tail ticks;
- independent `y_ready_i` for the mathematical y stream;
- telemetry control, telemetry soft reset, and STATUS/METRICS ticks;
- integration-owned sample-rate, overflow-event, DMA, and command-reject status;
- downstream `record_ready_i` for formatted telemetry records.

It exposes:

- the real core y stream and sample index;
- tail-drain handshake and state;
- raw core frame-boundary, busy/alive, sample/frame/error counters, metrics,
  overflow, saturation, and protocol status;
- real sample, frame, and bin taps for observation;
- the formatted telemetry record stream;
- packetizer/scheduler/FIFO drop and configuration-health status.

`sample_ready_o` is owned only by `trecap_core_top`. `record_ready_i` terminates
in the telemetry packet FIFO. `y_ready_i` terminates in the core output path.
Those three flow-control paths are independent.

## Tap mapping

The tap mapping is direct. There is no synthetic tap generator and no external
tap input on the reusable composition.

| Core producer | Telemetry consumer | Packet use | Flow control |
|---|---|---|---|
| `tap_sample_o` | `tap_sample_i` | WAVE waveform triples | Valid-only; no ready |
| `tap_frame_o` | `tap_frame_i` | SPEC frame association and METRICS frame aggregates | Valid-only; no ready |
| `tap_bin_valid_o` | `tap_bin_valid_i` | SPEC unique-bin event | Valid-only; no ready |
| `tap_bin_frame_idx_o` | `tap_bin_frame_idx_i` | SPEC frame identity | Valid-only; no ready |
| `tap_bin_idx_o` | `tap_bin_idx_i` | SPEC unique-bin index | Valid-only; no ready |
| `tap_bin_mag2_o` | `tap_bin_mag2_i` | SPEC displayed magnitude | Valid-only; no ready |
| `tap_bin_mask_o` | `tap_bin_mask_i` | SPEC suppressed-bin state | Valid-only; no ready |
| `tap_bin_eligible_o` | `tap_bin_eligible_i` | SPEC eligible-bin state | Valid-only; no ready |
| `tap_bin_last_o` | `tap_bin_last_i` | End of compact unique-bin frame | Valid-only; no ready |

The core also exposes bin real, imaginary, and pre-mask observability. They may
be passed out of the composition, but they are not telemetry inputs in Revision
G and shall not be invented as extra packet payload fields.

STATUS is intentionally different. Its sample and frame counts come from the
explicit authoritative `core_sample_count_o` and `core_frame_count_o` outputs,
not from `tap_sample.sample_idx + 1` or `tap_frame.frame_idx + 1`. Sample and
frame taps can be delayed, absent between events, or dropped by observation
logic. Reconstructing authoritative STATUS counters from them would silently
report stale state.

## Packet modes and enables

All implemented telemetry requires `ctrl_i.telemetry_enable`. Each packet also
uses its generated per-packet gate.

| Packet | Additional enable | Observation/snapshot source | Drop priority |
|---|---|---|---:|
| WAVE | `PACKET_ENABLE.WAVE_EN` and waveform decimation | Sample tap | 0 |
| SPEC64 | `PACKET_ENABLE.SPEC_EN` and `SPEC_MODE=SPEC64` | Frame plus unique-bin taps | 1 |
| SPEC129 | `PACKET_ENABLE.SPEC_EN` and `SPEC_MODE=SPEC129` | Frame plus unique-bin taps | 1 |
| METRICS | `PACKET_ENABLE.METRICS_EN` and `metrics_tick_i` | Aggregate frame taps plus authoritative core error metrics | 2 |
| STATUS | `PACKET_ENABLE.STATUS_EN` and `status_tick_i` | Authoritative core counters plus supplied integration status | 3 |

`SPEC_MODE=DISABLED` suppresses spectrum records. `PEAKS` and `DEBUG` remain
reserved-disabled. The scheduler must reject or drain a candidate whose packet
type, payload length, flags, or mode does not match the generated Revision-G
contract.

The priority order is deliberate: WAVE is dropped first, then spectrum, then
METRICS, while STATUS is retained whenever a lower-priority resident can be
shed. Priority does not make telemetry lossless.

## Non-stalling and drop rules

Telemetry is best-effort observation. The mathematical core is the primary
datapath.

There is no tap-ready interface. When a packetizer is busy and cannot capture a
new selected sample, frame, bin sequence, STATUS tick, or METRICS tick, it drops
that telemetry event and emits a drop pulse. It must never stall sample input,
frame scheduling, FFT/IFFT, WOLA, core metrics, or the y stream.

The scheduler operates only on packetizer record streams. It locks one selected
packetizer until the accepted final payload beat so records cannot interleave.
A disabled or illegal candidate is drained locally and reported as a drop so a
runtime mode change cannot wedge telemetry. Drain ownership is latched per
candidate until that candidate's final beat; a one-cycle disable or malformed
configuration therefore cannot drain only the first beat and later admit the
remaining tail as if it were a new record.

`observation_epoch_reset_i` marks a source discontinuity without acting like a
telemetry soft reset. For that cycle, new packetizer admission is disabled:
partial WAVE/SPEC collections are discarded through their normal disabled-drop
paths. A record already selected by the scheduler continues to its final beat;
an unselected record candidate drains locally to its final beat and produces one
counted drop. The packet FIFO is not reset, so an already-admitted complete
record remains atomic and transport counters are not silently cleared. This
prevents a WAVE payload from mixing samples from two source epochs without
allowing a source change to backpressure the mathematical core.

The packet FIFO captures a complete record before admission. If capacity is
available, it appends the record. If full, it evicts the oldest resident whose
priority is lower than the incoming record. If no lower-priority resident is
eligible, it drops the incoming record. The output head is not evictable while
being presented downstream; this preserves ready/valid output stability.

`packet_fifo_drop_count_o` counts pre-writer loss from packetizers, scheduler,
and packet-FIFO admission. It is separate from `DMA_DROP_COUNT`, which belongs
to the later DDR writer. Mixing those counters would make it impossible to tell
whether telemetry was lost before or after writer admission.

## FIFO output ownership

The sole formatted-record output owner is:

```text
trecap_core_telemetry_top
    -> trecap_telemetry_top
        -> u_packet_fifo
            -> record_valid_o / record_ready_i
            -> record_meta_o
            -> record_payload_data_o
            -> record_payload_keep_o
            -> record_payload_last_o
```

Metadata stays stable for every payload beat of a record.
`record_payload_last_o` marks its final payload beat. The downstream HPS bridge,
not this composition, adds the 32-byte DDR/UDP header, allocates normal sequence
numbers, applies 64-byte DDR padding, generates WRAP records, and writes DDR.

Downstream backpressure may fill the telemetry FIFO and cause telemetry drops.
It shall not alter `sample_ready_o`, `y_ready_i`, or any core scheduling signal.

## Metrics, STATUS, and safe boundary semantics

The core emits a raw frame-boundary pulse when its frame scheduler starts a real
frame. A configuration-safe boundary is:

```text
raw core frame boundary OR structurally idle core
```

The late `tap_frame.valid` event reports completed frame statistics. It is not a
safe boundary for changing THR2 or clearing core aggregates. Similarly,
`status_tick_i` and `metrics_tick_i` are packet-emission triggers, not core
configuration boundaries.

The composition caller owns safe application of `clear_metrics_i`. It must hold
or queue a request until a true core frame boundary or structural core idle
condition. Repeated pending requests may coalesce. A telemetry soft reset is a
one-cycle synchronous clear in `clk`: it clears packetizer/scheduler partial state,
flushes all resident and partially captured FIFO records, and, depending on the
frozen parameter, clears telemetry drop counters. It never gates or derives
`rst_n`, and it shall not reset, clear, or discontinuity-mark the mathematical core.

On the DE1-SoC path this is one explicit event chain. The raw CSR request leaves
`trecap_hps_bridge_top` as `clear_metrics_pulse_o`; the source/core integration
queues it until safe and emits `clear_metrics_apply_pulse_o`. That exact applied
pulse drives both `trecap_core_top.clear_metrics_i` and
`trecap_telemetry_top.metrics_clear_i`. Wiring the raw request directly to
telemetry would split the two metric epochs whenever the core had to defer it.
The source/core output also asserts for a source-discontinuity event because that
event resets core-owned metric state. In the standalone composition, datapath
clear, core disable, and source discontinuity likewise clear the telemetry-owned
eligible-bin aggregate. Telemetry soft reset remains excluded from this epoch.

METRICS accumulates valid frame observations, combines them with authoritative
core error-metric outputs, and snapshots the aggregate at `metrics_tick_i`.
STATUS snapshots explicit authoritative core counters and
integration-supplied status at `status_tick_i`. These low-rate records may lag
the current datapath and are not exact-completion or bit-accurate signoff
evidence.

## Overflow and W1C ownership

The composition-level CSR-visible `OVERFLOW_FLAGS` mirror has one sticky owner.
Its update rule is:

```text
next = (current & ~w1c_clear) | new_fault_events
```

The set side is an event interface. Inputs must represent a one-cycle new-fault
bitmask, not a continuously asserted sticky level. W1C clears the sticky owner
without manufacturing a second event from a still-active fault episode. Once the
source level deasserts, the detector is re-armed so a later recurrence can set the
bit again.

For packet-FIFO loss, `packet_fifo_drop_pulse_o` is the set event. The
`packet_fifo_overflow_o` sticky level remains separately exposed for local
diagnostics; it must not be continuously ORed into the set expression. Doing so
would make W1C ineffective because the cleared CSR bit would be set again on the
next cycle by the still-high FIFO sticky level. Scheduler malformed-record
events likewise set only from their new-event pulse.

The board HPS bridge also treats writer status as fault episodes. Its previous
event history follows the current writer event bitmask rather than permanently
ORing every observed bit. A source deassertion therefore re-arms the detector,
and a later recurrence of the same fault can set the CSR-visible bit again.

## Filelist separation

The two build surfaces have different ownership:

- `filelists/rtl_telemetry.f` is the pure formatter build. It includes generated
  packages, common/interface dependencies, packetizers, scheduler, packet FIFO,
  and `trecap_telemetry_top`. It excludes `rtl/core/`, `rtl/fft/`, and
  `trecap_core_telemetry_top.sv`.
- `filelists/rtl_core_telemetry.f` is the reusable composed build. It includes
  the core and FFT dependencies, pure telemetry dependencies, and finally
  `trecap_core_telemetry_top.sv`.

This separation prevents a formatter-only consumer from silently acquiring an
algorithm core and prevents a compile target named telemetry from hiding the
real composition dependency.

## DE1-SoC system binding

The reusable composition is useful for a standalone normalized-source harness.
It is not inserted blindly into every system.

The Step-7 DE1-SoC source path already instantiates `trecap_core_top` inside
`trecap_source_core_integration`. Therefore the board transport path must use
the pure `trecap_telemetry_top` with the real external core taps and
authoritative counters. Instantiating `trecap_core_telemetry_top` behind that
source/core layer would create two mathematical cores and disconnect telemetry
from the source-selected core.

The unique-bin index width is explicit on `trecap_telemetry_top` and is passed as
`BIN_IDX_W` in both the standalone and board transport instances. This prevents a
non-default legal top-level width from being silently truncated or extended at
the SPEC packetizer boundary.

The legal board path is:

```text
board sources
    -> trecap_source_core_integration
        -> one trecap_core_top
        -> real taps and authoritative counters
            -> trecap_de1soc_full_top
                -> one trecap_telemetry_top
                -> HPS bridge
```

The legal standalone composition path is:

```text
normalized source or harness
    -> trecap_core_telemetry_top
        -> one trecap_core_top
        -> one trecap_telemetry_top
```

## Source-contract gate

Run:

```bash
python3 scripts/check_core_telemetry_composition.py
```

The checker validates the JSON schema, frozen values, one-core/one-telemetry
composition, direct tap and counter mappings, non-stalling ready ownership,
single FIFO output ownership, packet modes, pure/composed filelist separation,
and absence of a duplicate composed core in the DE1-SoC transport path.

Passing this checker means only that the checked-in source structure matches the
Step-8 contract. It does not mean the RTL compiles or behaves correctly.
