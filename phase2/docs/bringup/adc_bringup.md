# DE1-SoC LTC2308 ADC bring-up

> **Step 17 status:** `source_implemented_pending_native_rtl_compile_timequest_and_hardware_evidence`

File class: **[1] hand-written bring-up and architecture documentation**.

## Scope

Step 17 completes the checked-in live-ADC source path:

```text
DE1-SoC LTC2308
  -> adc_wrapper
  -> trecap_adc_adapter
  -> guarded source mux
  -> trecap_core_top
  -> non-stalling telemetry / DDR / HPS path
```

This is an optional live demonstration source. It does not replace the frozen
artifact path:

```text
reference input artifact -> BRAM replay -> core -> artifact comparison
```

BRAM replay remains the bit-accurate correctness prerequisite. The ADC path may
be built or debugged later without blocking BRAM replay or the Step-16 LINE-IN
profile.

## Frozen board interface

This contract is pinned to the DE1-SoC Rev-H board and its 12-bit Linear
Technology LTC2308. Older DE1-SoC revisions may use an AD7928 and are not
interchangeable with this RTL. Verify the PCB revision and the converter marking
before enabling the source. The board signal
named `ADC_CS_N` is a legacy top-level alias for the converter's `CONVST`
input; the suffix is misleading. It idles low and a high pulse starts a
conversion. It is not an active-low SPI chip select.

| Logical signal | Cyclone V pin | Direction | Electrical/protocol role |
| --- | --- | --- | --- |
| `ADC_CS_N` | `PIN_AJ4` | FPGA output | LTC2308 `CONVST`, idle low, pulse high. |
| `ADC_DIN` | `PIN_AK4` | FPGA output | Six-bit next-conversion command. |
| `ADC_DOUT` | `PIN_AK3` | FPGA input | Twelve-bit conversion result, MSB first. |
| `ADC_SCLK` | `PIN_AK2` | FPGA output | Registered serial clock, idle low. |

The checked-in pin source assigns 3.3-V LVTTL. Step 18 must still bind and
review the external input/output timing; a pin assignment is not TimeQuest or
electrical evidence.

Protocol authority is the primary ADI LTC2308 Rev-C datasheet. The Rev-H Terasic
manual/System CD corroborates the board device and pin identity. The official
Terasic demo's legacy CONVST width is not the timing authority; T-RECAP
intentionally uses the ADI short-pulse guidance instead.

| Authority | Pinned reference |
| --- | --- |
| LTC2308 datasheet | `https://www.analog.com/media/en/technical-documentation/data-sheets/2308fc.pdf` |
| LTC2308 product page | `https://www.analog.com/en/products/ltc2308.html` |
| Terasic Rev-H System CD | `https://download.terasic.com/downloads/cd-rom/de1-soc/DE1-SoC_v.6.0.0_HWrevH_SystemCD.zip`, SHA-256 `e9743031e4574effd776100f8ad0874581f3234ef8ce21e2e8e1b4ab10ca088d` |
| Rev-H manual inside System CD | `UserManual/DE1-SoC_User_manual.pdf`, SHA-256 `f9d743dec68e9d5cc3d9a64c44231fde1d4ac0fed3f4961088fcacca2624e5b1` |

These references establish a source contract, not the revision or behavior of a
physical board on the bench.

## Frozen conversion and serial protocol

The controller runs entirely in the 50 MHz `clk_fabric` domain. One transaction
performs the following sequence:

1. Raise `ADC_CS_N`/`CONVST` for the configured short pulse, then return it low.
2. Wait through the complete conversion holdoff.
3. Generate exactly twelve `ADC_SCLK` pulses.
4. Sample one `ADC_DOUT` bit on each generated rising edge, MSB first. `B11` is
   already valid after conversion; `B10` through `B0` advance after subsequent
   falling SCLK edges.
5. Present the next six-bit command on `ADC_DIN`; advance it on falling edges,
   then send zero for the remaining result clocks.
6. Hold the acquisition guard before admitting another conversion.

The 50 MHz board profile freezes:

| Parameter | Value | Result |
| --- | ---: | --- |
| `CONVST_PULSE_CYCLES` | 2 | 40 ns high pulse. |
| `CONVERSION_WAIT_CYCLES` | 80 | 1.6 us conversion holdoff before the serial-read state. |
| `SCLK_HALF_DIV` | 10 | 2.5 MHz `ADC_SCLK`. |
| `FRAME_BITS` | 12 | Exactly twelve result bits. |
| `ACQUISITION_GUARD_CYCLES` | 12 | 240 ns explicit post-read guard. |
| re-entry recovery | 92 cycles | 1.84 us before any request is accepted after enable or abort. |
| `SAMPLE_RATE_HZ` | 100,000 | Exact-average continuous request cadence required by the Phase 2 profile. |

The first generated SCLK rising edge occurs only after the pulse, conversion
wait, and first half-period: 92 fabric cycles, or 1.84 us, with the frozen
values. The complete default transaction is 334 fabric cycles, or 6.68 us, and
is shorter than the 10-us scheduler interval. Elaboration-time assertions use
wide cross-multiplied timing checks so parameter overrides cannot rely on the
default cycle literals accidentally. Fail-closed behavior applies to
structurally well-formed parameter overrides; degenerate zero-width overrides
are outside the module ABI and may be rejected during elaboration.

`ADC_SCLK` is a peripheral protocol output. It is not used in an `always_ff`
event control and is not a second fabric clock.

## Channel command and epoch rule

The six command bits are shifted in this order:

```text
{S/D, O/S, S1, S0, UNI, SLP}
```

The board uses single-ended, unipolar, awake operation. Synchronized
`SW[6:4]` chooses channel 0 through 7. The generated command is:

```text
{1'b1, channel[0], channel[2], channel[1], 1'b1, 1'b0}
```

| Channel | Binary command | Hex command |
| ---: | --- | --- |
| 0 | `100010` | `0x22` |
| 1 | `110010` | `0x32` |
| 2 | `100110` | `0x26` |
| 3 | `110110` | `0x36` |
| 4 | `101010` | `0x2A` |
| 5 | `111010` | `0x3A` |
| 6 | `101110` | `0x2E` |
| 7 | `111110` | `0x3E` |

The command sent during one serial read configures the following conversion.
Therefore the board latches the selected channel only when entering
`TSRC_ADC_LIVE`, holds that channel for the whole source epoch, and primes by
discarding the first old-configuration result. Moving `SW[6:4]` during an ADC
epoch does not mix channels silently. To apply a different channel, leave and
re-enter ADC mode; the new epoch is marked as a source discontinuity and is
primed again.

Local request controls are:

```text
SW[7] = 0  exact-average continuous conversion requests
SW[7] = 1  one debounced diagnostic-only request from KEY[2]
```

Manual conversions do not enter the mathematical core. With `SW[9:8]=00`,
HEX5..3 show the low 12 bits of the eligible raw-sample count and HEX2..0 show the
latest raw code. The first request after enable/abort primes the converter and is
discarded. FPGA telemetry reports `sample_rate_hz=0` while manual diagnostics are
selected; the dashboard labels that as no periodic DSP stream.

Changing SW[7] clears the source/core epoch and briefly disables the controller,
which aborts any in-flight conversion and primes the pipeline again. This does not
change the channel latched on ADC-source entry and does not reset transport.

Requests arriving while the wrapper is busy are not queued. They set the
overrun diagnostic instead.

The wrapper accepts only single-ended, unipolar, awake command encodings. A
sleep, bipolar, or differential command presented through its reusable command
input is rejected with idle pins and the protocol-error sticky set, so the
unsigned downstream format cannot be changed silently.

The board contract exposes no ADC reset pin and assumes no guaranteed power-on
MUX command. For that reason, serial outputs return to idle-low while disabled
and prime/discard is mandatory after reset, enable, abort, or command change.
The frozen command keeps `SLP=0`; the 200-ms wake requirement applies only after
entering sleep and must not be inserted into ordinary awake transactions.

## Sample format and normalization

The hardware-facing sample is unsigned 12-bit data for the frozen unipolar
0-to-4.096-V board range:

```text
raw ADC code = 0 .. 4095
default zero code = 2048
centered code = raw - 2048 = -2048 .. +2047
```

`adc_wrapper` owns only conversion/serial timing and emits raw data plus a valid
pulse. `trecap_adc_adapter` owns recentering, signed core-width scaling,
saturation, and ready/valid staging. With the current 12-bit core baseline the
centered value maps exactly to the signed core sample range. The Step-17 profile
keeps the optional zero-code override invalid and DC blocking disabled; changing
either option changes live-source semantics and requires a new explicit profile.

The raw wrapper cannot be backpressured. If its event arrives while the adapter
cannot replace or release its pending output, the adapter drops that event and
counts/reports it; telemetry pressure still must not return to the core or ADC
controller.

## CDC and source switching

No sample-data async FIFO is required for this ADC implementation:

- the state machine, sample scheduler, result register, adapter, source mux, and
  mathematical core all use `clk_fabric` and `rst_n_platform`;
- `ADC_SCLK` is generated by registered fabric logic and only clocks the
  external converter;
- `ADC_DOUT` first passes through the wrapper's two-flop fabric synchronizer and
  the synchronized bit is captured atomically into the twelve-bit shift register
  on the fabric edge that generates the selected SCLK edge; and
- synchronized board controls are latched before they affect an ADC epoch.

The implemented external timing policy is in
[physical_timing.md](../architecture/physical_timing.md): a 10 ns absolute
`ADC_DOUT` pin-to-first-stage budget and 5 ns registered-output data-path budgets,
with a mandatory fitted gate defined in [build_order.md](../architecture/build_order.md).
These allocations require their full serial return-budget assumptions and do not
establish physical converter operation. If a later design places the ADC controller
or adapter in another domain, it must add a reviewed atomic CDC path; independent
bit synchronizers are forbidden.

Selecting `adc_live` through the generated source-mode commit is the only legal
route to the core. On a real mode change, the transition guard blanks acceptance,
the source mux applies the new mode at its safe boundary, the source epoch is
cleared, and one discontinuity pulse resets source-dependent core alignment.
The ADC wrapper is disabled outside its own mode and returns its serial outputs
to idle. It may not bypass `trecap_source_core_integration`. Disable or abort
also restarts a 92-cycle recovery holdoff. A manual or scheduled request during
that holdoff is rejected and sets the request-overrun sticky; the first accepted
transaction is then still subject to the normal prime/discard rule.

## Counters and faults

The live path keeps different failure domains attributable:

| Observability | Meaning |
| --- | --- |
| wrapper `sample_count_o` | Saturating count of eligible current-command samples published with `sample_valid_o`. |
| `transaction_done_pulse_o` | One-cycle evidence that a physical serial transaction completed; it is not a retained counter. |
| request-overrun sticky | A manual or scheduled request arrived during re-entry recovery or while a transaction was active. |
| protocol-error sticky | The controller entered an illegal state, rejected an unsupported well-formed static configuration, or rejected a non-single-ended/non-unipolar/sleep command. |
| adapter samples-seen/admitted/accepted counts | Raw events, normalized events, and core-accepted samples. |
| adapter dropped-sample count | A raw event could not enter the one-entry adapter stage. |
| adapter clip/config stickies | Normalization saturation or unsupported adapter configuration. |

The wrapper sample count and adapter drop count saturate; no wraparound may look
like a reset. Other adapter accounting remains owner-local unless a named status
or debug path exports it. Sticky
fault clearing is explicit; it is not implied by merely leaving ADC mode. These
ADC diagnostics remain dedicated board/source observability because the frozen
CSR overflow register has no honest one-to-one field for them. `LEDR[7]` may
aggregate their fault levels, but that does not make them separately CSR-visible.

## Profile and non-blocking milestones

Select the ADC build/bring-up profile explicitly:

```text
config/profiles/de1soc_adc_demo.json
```

The profile freezes `adc_live`, LTC2308, channel selection at ADC-epoch entry,
100 ksample/s, 2.5 MHz SCLK, 12-bit unsigned input, unsigned-midscale recentering,
DC blocking disabled, and the physical DE1-SoC top. The profile resolver binds
the matching RTL constants.

The default board profile remains `de1soc_bram_replay`. The ADC profile does not
alter the BRAM artifacts, core arithmetic, telemetry packet ABI, DDR ownership,
HPS transport, PC dashboard, or the independent `de1soc_linein_demo` profile.

## Source checks versus hardware evidence

The Step-17 source gate should cover at least:

```text
profile/schema validation
pin and protocol ownership
command/channel mapping for all eight channels
first-result prime/discard behavior
post-abort/re-entry recovery and early-request sticky attribution
100 ksample/s exact-average scheduler bounds
2.5 MHz SCLK and transaction-fit arithmetic
raw-to-signed normalization boundaries
source-mode disable/re-entry and discontinuity behavior
counter saturation and sticky-clear policy
generated full-board filelist inclusion
```

Passing source/model checks proves only that the checked-in contracts agree. It
does **not** prove:

```text
native RTL elaboration or simulator execution
Quartus compilation or fitter placement
TimeQuest setup/hold closure for ADC_DOUT or serial outputs
measured CONVST/SCLK frequency or edge placement
physical channel identity, analog settling, reference accuracy, gain, or noise
live ADC samples through DDR/HPS/UDP/dashboard
hardware correctness or signoff
```

Step 18 owns the complete Quartus project and timing constraints. Step 20 owns
vendor-generated build artifacts and physical-board evidence.

## Controlled hardware bring-up order

Do not enable the entire system at once:

1. Pass artifact-driven BRAM replay independently.
2. Select the explicit ADC profile and channel 0 with ADC mode still disabled.
3. Verify idle-low `ADC_CS_N` and `ADC_SCLK` before enabling ADC mode.
4. Enter ADC mode and inspect CONVST, SCLK, DIN, and DOUT with SignalTap or a
   suitable logic analyzer.
5. Confirm one discarded priming transaction before the first valid sample.
6. Use one-shot mode before continuous mode.
7. Apply a known safe DC input, compare raw code and centered sample, then test
   the remaining channels one epoch at a time.
8. Only after local capture is stable, enable telemetry and inspect the exported
   ADC fault summary plus FIFO, DDR, HPS, and PC loss counters. Inspect the
   owner-local adapter counters only through an explicitly preserved named
   SignalTap/debug tap; they are not currently exported through CSR telemetry.

Do not claim a passed live-ADC milestone without preserving the selected profile,
Quartus/TimeQuest reports, measured serial timing, input stimulus, raw/normalized
samples, counter snapshots, and tool/board versions.
