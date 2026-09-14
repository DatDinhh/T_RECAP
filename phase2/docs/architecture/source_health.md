# Live-source health and recovery

The source/core integration owns continuity of physical-time input. A missed live
sample ends the current DSP epoch: the design stops admission, clears the source
adapter and mathematical history, and waits for explicit rearm. It never closes a
missing-sample gap by assigning consecutive DSP indices to later physical samples.
The normalization arithmetic, four source enums, and telemetry packet layouts are
unchanged.

The implementation is `rtl/top/trecap_source_core_integration.sv`; physical status
comes from the DE1-SoC audio and ADC wrappers. The machine-readable register
contract is `spec/generated/csr_map.json`, with constants emitted by
`scripts/gen_headers.py` for RTL, HPS C, and dashboard Python.

## Admission and fault policy

A selected periodic live source passes through these states:

1. **Wait for stop:** capture is disabled. Audio acknowledges the returned,
   synchronized receive-BCLK capture-enable level; ADC acknowledges `busy=0`.
2. **Settle:** hold capture disabled for 4096 fabric clocks after stop acknowledgement.
   This drains prior audio FIFO/CDC traffic and gives the ADC a quiet recovery
   interval. The fabric runs at 50 MHz, so this interval is 81.92 microseconds.
3. **Wait for readiness and first sample:** admit only when physical configuration
   is ready. The first delivered sample establishes the physical sequence baseline.
   A one-second startup deadline begins after settling, including time spent waiting
   for codec readiness.
4. **Run:** every next raw sample sequence must equal the preceding sequence plus
   one, modulo 2^64. At 48 kS/s audio and 100 kS/s ADC, the maximum permitted raw
   event silence is 4096 fabric clocks. This 81.92-microsecond watchdog detects a
   stopped physical clock/stream; it is not a rate measurement or a clock-jitter
   specification.
5. **Fault:** latch the first fault event's complete cause mask, increment the epoch,
   pulse the existing source discontinuity path, clear in-flight source/core state,
   and disable capture. Remain stopped until rearm, an actual source-mode change,
   an explicit datapath clear, or board reset.

Fault causes are independent bits: sequence gap, adapter admission drop, wrapper
FIFO/request drop, readiness loss after the first sample, sample timeout, and
wrapper protocol/configuration failure. Audio readiness includes PLL configuration,
PLL lock, FPGA codec-bus grant, and successful codec initialization. The grant
comes from the kernel-owned `PLATFORM_CONTROL` level after GPIO48 output-low
readback; it is not a fabric sample of the dedicated HPS pin. See
[platform_grant.md](platform_grant.md) for its ABI and lifetime. ADC readiness
requires a supported periodic conversion command. Manual ADC is diagnostic mode;
it does not enter STFT/WOLA and advertises no periodic DSP rate.

On a detected sequence gap, the offending event is blocked combinationally before
adapter/core admission. An adapter drop or CDC overflow event can arrive after an
older valid prefix has already produced output; the discontinuity then invalidates
in-flight history and partial telemetry aggregates. Records already committed to
DDR remain committed. A consumer must treat the faulted epoch as interrupted;
this design does not retract earlier records or add an epoch field to Revision-G
UDP packets. Source-health epochs and legacy telemetry packet sequence numbers
have different ownership and are not interchangeable.

A source can be switched away while stopped, including manual mode or unavailable
hardware, once its adapter is empty. Core configuration can commit while the
stopped core is idle. BRAM replay start continues to wait for core initialization,
including the WOLA memory scrub reported through `core_busy`.

## CSR page

The existing registers at 0x000 through 0x0FC retain their offsets and behavior.
The optional page is identified by `SOURCE_HEALTH_CAPABILITY=0x53480100` at 0x100
(`SH`, ABI 1). Its final word is at 0x180, within the existing 4096-byte CSR aperture.
The separate platform-grant registers occupy 0x184 and 0x188. The RTL CSR leaf
requires at least nine address bits and software maps at least 512 bytes. Legacy
software can keep using the original registers.

`SOURCE_HEALTH_CONTROL` at 0x104 accepts separate W1P operations:

| Value | Operation |
| --- | --- |
| 0 | No operation. |
| 1 | Atomically snapshot all 31 health words. |
| 2 | Rearm the actual selected ADC or audio source. |

Writing both operations together or any reserved bit is rejected through existing
CSR reject accounting. Rearm is rejected when a source transition is pending or
the actual source is BRAM/diagnostic. It changes no ring pointers, transport enable,
packet sequence state, threshold, or selected source. Snapshot words at
0x108–0x180 remain stable until the next snapshot or board reset. Software must
serialize each snapshot-plus-read transaction; unrelated legacy core-counter
snapshots use a separate bank.

The status word reports `present`, `live`, `periodic`, `ready`, `running`, `fault`,
`waiting_stop`, `settling`, and the actual source enum. `running` means admission
is enabled and at least one raw sample established the new sequence baseline.
`RATE` is the configured nominal rate when live admission is enabled, otherwise
zero. It is not a measured rate; use raw-counter deltas over host time for a rough
observed delivery rate. The legacy HPS-synthesized STATUS packet still reports zero
when that packet cannot know the physical cadence.

All counters are saturating unsigned 64-bit values. They survive source changes,
rearm, telemetry clear, metric clear, and sticky-error W1C; only fabric hard reset
zeros them. Both halves are latched in the same snapshot.

| Counter | Meaning |
| --- | --- |
| `EPOCH` | Increments for fault, rearm, actual source-mode change, or entry to datapath clear/disable. Reset establishes epoch zero. |
| `AUDIO_RAW`, `ADC_RAW` | Wrapper-delivered fabric sample-valid events. ADC includes manual diagnostic samples; ADC pipeline priming results are excluded by its wrapper. Audio excludes FIFO words deliberately drained while capture is disabled. These are delivery counters, not analog conversion totals. |
| `AUDIO_ADMITTED`, `ADC_ADMITTED` | Raw events accepted into the selected normalized adapter. |
| `AUDIO_ACCEPTED`, `ADC_ACCEPTED` | Normalized samples accepted at the core input. |
| `AUDIO_ADAPTER_DROP`, `ADC_ADAPTER_DROP` | Selected raw events rejected by the adapter. |
| `AUDIO_WRAPPER_DROP` | Fabric-observed audio RX FIFO overflow events accumulated across wrapper sticky clears. It is an event counter, not a guaranteed exact lost-sample count: overflow CDC events may coalesce, and the sequence detector independently catches a gap. |
| `ADC_WRAPPER_DROP` | ADC conversion requests refused because the engine is busy, recovering, or the requested command is unsupported. |
| `GAP_EVENTS` | Fault events containing a raw sequence discontinuity. |
| `READY_LOSS` | Fault events containing readiness loss after running began. |
| `TIMEOUT_EVENTS` | Fault events containing startup or running sample timeout. |

Counts describe distinct boundaries. Subtracting raw minus admitted does not yield
a universal loss total because intentional stop/drain/manual events are outside
DSP admission. No physical-source counter is aliased onto transport drop counters.
Clipping and optional LINE-OUT TX overflow/underflow keep their existing diagnostic
meaning and do not claim loss of LINE-IN samples.

## HPS operator interface

Run from the deployed repository after the matching FPGA image and bridges are
active. The utility loads addresses from the same runtime JSON as the HPS streamer
and masks/offsets from generated Python constants. It maps only CSR device memory.

```bash
sudo python3 sw/hps/scripts/source_health.py
sudo python3 sw/hps/scripts/source_health.py --watch --interval 1
sudo python3 sw/hps/scripts/source_health.py --rearm
```

Use `--config path/to/trecap_hps_config.json` for another paired runtime file.
The utility emits JSON, including decoded faults, nominal rate, and all coherent
counters. Exit code 3 means the sampled source is faulted; 2 means configuration,
access, ABI, or rearm acknowledgement failed. The utility serializes its snapshot
transactions with `/run/lock/trecap-source-health.lock`; other health-page readers
must use that same lock. The existing HPS streamer does not touch this snapshot
bank and can continue running.

Rearm acknowledges when the epoch advances. That acknowledgement is not a claim
that acquisition has resumed: inspect subsequent snapshots for `running=1`,
`fault=0`, and increasing accepted counts. A stopped BCLK can leave
`waiting_stop=1` until the receive domain observes capture disable. Once BCLK
returns, the full settle interval still runs before new capture. This prevents an
immediate rearm from consuming stale FIFO samples. A saturated epoch requires
board reset for a distinct next identifier.

The board also re-arms codec initialization and clears physical wrapper diagnostic
sticky state when source rearm is accepted. Fix the missing clock/grant/configuration
first; rearming without fixing the cause leads to another explicit fault. Manual
ADC rearm leaves diagnostics selected and does not fabricate a periodic stream.

This is an implemented design contract. No simulation, functional test run,
fitted timing result, or live-board result is implied by the source changes.
