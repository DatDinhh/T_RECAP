# DE1-SoC board-top integration

File class: **[1] hand-written cumulative Step-9/10/16/17 architecture contract**.

## Purpose and status

Step 9 replaces the remaining integration scaffold in
`rtl/platform/de1soc/de1_soc_trecap_top.sv`. The physical top now composes the
existing implementation owners instead of manufacturing fake taps, counters,
bus responses, or idle I/O:

```text
HPS lightweight bridge
  -> generated Platform Designer `system`
  -> platform_designer_wrapper CSR boundary
  -> trecap_de1soc_full_top
  -> trecap_hps_bridge_top / CSR adapter / CSR bank

CLOCK_50 -> audio_pll_wrapper -> 12.288 MHz AUD_XCK
HPS_I2C_CONTROL low -> FPGA bus grant -> WM8731 0x1a initialization

audio LINE-IN or LTC2308 ADC or BRAM replay or diagnostic source
  -> platform capture wrapper where applicable
  -> trecap_source_core_integration
  -> the sole mathematical core
  -> valid-only real taps and authoritative counters
  -> trecap_de1soc_full_top telemetry/HPS path
  -> DDR writer Avalon master
  -> platform_designer_wrapper F2SDRAM boundary
  -> generated Platform Designer `system`
  -> HPS DDR3

core y valid/data
  -> always-accepted non-stalling board sink
  `-> best-effort audio_codec_wrapper line-out monitor
      -> AUD_DACDAT
```

Step 10 freezes the clock/reset side of this composition. The board has one
active 50 MHz fabric domain from `CLOCK_50`. `clock_reset_ctrl` owns 20 ms
stable-high qualification of released `KEY[0]`, combination with the active-low
HPS-to-FPGA reset, and the only fabric reset synchronizer. Its canonical
`rst_n_platform` releases every fabric owner simultaneously. The physical top
does not create another reset chain.

Step 16 adds the checked-in audio control and data path around that unchanged
fabric domain. `audio_pll_wrapper` generates the peripheral-only 12.288 MHz
`AUD_XCK`; `audio_codec_i2c_init` programs the WM8731 at 7-bit address `0x1a`;
and `audio_codec_wrapper` implements 48 kS/s, signed 16-bit I2S with the codec as
BCLK/LRCK master. Audio admission is gated by qualified PLL lock, FPGA I2C-bus
grant, and codec configuration done.

Step 17 closes the separate pinned Rev-H/LTC2308 source contract. The ADC wrapper
runs at 100 ksample/s in `clk_fabric`, emits a 2.5 MHz registered protocol clock,
synchronizes the off-chip `ADC_DOUT` bit through two preserved flops, assembles
unsigned 12-bit straight-binary words, and publishes only results known to match
the epoch-latched six-bit channel command. The adapter recenters at 2048 before
the sole source mux. The explicit ADC profile does not change the BRAM-replay
default or the independent LINE-IN profile.

This milestone is **source-only**. The checker proves checked-in ownership and
named-port relationships. It is not functional verification, not a Quartus
compile, not Platform Designer generation, not timing closure, and not hardware
evidence.

## Required composition and ownership

The physical top owns board pins and composition only. It instantiates exactly
one of each:

| Module | Instance | Role |
| --- | --- | --- |
| `clock_reset_ctrl` | `u_clock_reset_ctrl` | Canonical 50 MHz fabric clock/reset, board reset qualification, synchronized controls, and fractional clock-enable pulses. |
| `platform_designer_wrapper` | `u_platform_designer_wrapper` | Typed boundary to generated HPS/CSR/F2SDRAM hardware. |
| `audio_pll_wrapper` | `u_audio_pll_wrapper` | Peripheral-only 50 MHz-to-12.288 MHz `AUD_XCK` generation and qualified lock. |
| `audio_codec_i2c_init` | `u_audio_codec_i2c_init` | Open-drain FPGA-I2C WM8731 initialization with bounded retry/error accounting. |
| `audio_codec_wrapper` | `u_audio_codec_wrapper` | Audio serial capture and best-effort line-out monitoring. |
| `adc_wrapper` | `u_adc_wrapper` | Rev-H LTC2308 100-kS/s conversion and 2.5-MHz serial-transfer protocol with synchronized DOUT and saturating eligible-sample count. |
| `trecap_source_core_integration` | `u_source_core_integration` | Source selection, finite replay, and the sole core instance. |
| `trecap_de1soc_full_top` | `u_full_top` | Telemetry formatter, CSR logic, DDR record writer, and status. |

The board top must not directly instantiate `trecap_core_top`. That instance is
owned by `trecap_source_core_integration`. It must also not instantiate
`trecap_core_telemetry_top`, because that standalone variant owns another core.

All fabric-facing owners run on the current shared `clk_fabric` and
`rst_n_platform` integration domain where their public APIs require it. The
audio PLL output is a codec peripheral clock, not a new core/telemetry/CSR/DDR
domain. Vendor HPS/peripheral pins terminate only at
`platform_designer_wrapper`; mathematical logic remains pin-agnostic.

`clock_reset_ctrl` exports `clk_fabric`, canonical `rst_n_platform`, synchronized
controls, source pacing, status/metrics ticks, and heartbeat only. The 48 kHz,
10 Hz, 30 Hz, and 2 Hz-toggle events are exact-average fractional clock enables,
not clocks. It no longer exports a
synthetic frame boundary or source-safe boundary; the real owners are
`trecap_source_core_integration` and its mathematical core. The direct
`CLOCK_50` baseline also does not report a fabricated `pll_locked=1` status or
make reset correctness depend on that value. `CLOCK2_50`, `CLOCK3_50`, and
`CLOCK4_50` are reserved; split-clock operation is unsupported pending a real
CDC redesign.

## Real Platform Designer paths

The CSR and DDR paths are bidirectional contracts, not one-way activity hints.

CSR request path:

```text
HPS lightweight AXI master
  -> Qsys AXI-to-Avalon adaptation
  -> csr_avs_address/read/write/writedata/byteenable/burstcount
  -> trecap_de1soc_full_top
```

CSR response path:

```text
trecap_de1soc_full_top
  -> csr_avs_waitrequest/readdata/readdatavalid/writeresponsevalid/response
  -> generated Qsys bridge
  -> HPS
```

DDR write request path:

```text
trecap_ddr_ring_writer
  -> avm_address/write/writedata/byteenable/burstcount
  -> platform_designer_wrapper
  -> generated F2SDRAM bridge
  -> HPS DDR3
```

DDR response path returns `waitrequest`, `writeresponsevalid`, and `response` to
the writer. The board top may not replace either path with safe-idle constants.
The hand-written wrapper requires the generated `system
u_platform_designer_system` instance; it does not provide a local `system` stub.
Therefore a missing generated Qsys product remains an honest full-board
elaboration failure.

## Source ingress and real core observation

Audio input moves from `AUD_ADCDAT`, `AUD_ADCLRCK`, and `AUD_BCLK` through
`audio_codec_wrapper` as complete signed 16-bit left/right frames in a
BCLK-to-fabric async FIFO. The codec remains serial-clock master at 48 kS/s.
Capture is exposed only after PLL lock, FPGA I2C-bus grant, and codec init done.
LTC2308 results move from
`ADC_DOUT` through `adc_wrapper` as unsigned 12-bit samples. Both wrappers feed
the matching inputs on `trecap_source_core_integration`; neither wrapper scales
samples directly into the core or bypasses the guarded source mux.

Continuous LTC2308 requests use an exact-average 100 kHz fractional phase
accumulator referenced to `FABRIC_CLK_HZ`. Individual intervals may differ by one
fabric cycle for a general supported parameterization; the frozen 50-MHz/100-kHz
profile divides exactly. This scheduler is a clock-enable source; the 2.5 MHz
`ADC_SCLK` remains a registered serial-protocol output and is never an internal
RTL clock. The asynchronous `ADC_DOUT` input passes a two-flop `async_reg`/
preserved synchronizer before the fabric shift register consumes it. No
post-wrapper ADC CDC or async FIFO exists because sample valid/data, adapter,
source mux, and core are all in `clk_fabric`.

The source/core owner returns the real sample tap, frame tap, unique-bin tap,
sample/frame counters, error aggregates, source/core safe boundaries, source
discontinuity event, and safely applied metric-clear event. Those exact nets
feed `trecap_de1soc_full_top`. The physical top does not synthesize an activity
counter and relabel it as a core tap.

Telemetry remains valid-only observation. Packet FIFO or DDR backpressure may
drop telemetry but must never drive the source mux ready path, core input ready,
FFT/IFFT/WOLA progress, or the core y stream.

## Core output and audio line-out policy

The mathematical output is no longer only a constant/disconnected board tieoff,
but the codec is also not allowed to backpressure the core.
`trecap_source_core_integration.y_ready_i` remains tied high as the non-stalling
board sink. The real `core_y_valid` and `core_y_data` are also fanned out to both
channels of the `audio_codec_wrapper` line-out monitor. This monitor is
best-effort and may drop samples when its async FIFO is full.

The mono core sample is sign-preservingly left shifted by
`AUDIO_SAMPLE_W - T_SAMPLE_W` and sent to both line-out channels. The top may
name that result `core_y_audio_scaled`, but the derived net must remain directly
traceable to the real source/core `y_data_o`; a same-width counter or switch
value is not an acceptable substitute.

If the fabric-to-BCLK async FIFO is full, the monitor sample is dropped and the
dedicated saturating 64-bit TX-overflow counter increments.
`audio_codec_wrapper.lineout_ready_o` is observability only; it does not become
`y_ready_i`. An epoch tag and synchronized flush event discard stale monitor
samples after disable, loss of codec readiness, or a source discontinuity. Once
primed, a missing frame produces digital silence and increments the dedicated
saturating 64-bit TX-underflow counter. RX-FIFO overflow is counted separately.
These three audio counters are not assigned to unrelated generated CSR overflow
bits.

`audio_pll_wrapper` supplies `AUD_XCK` at the frozen 12.288 MHz profile. After
qualified lock, `audio_codec_i2c_init` owns the open-drain
`FPGA_I2C_SCLK`/`FPGA_I2C_SDAT` transaction sequence for WM8731 address `0x1a`,
programming 48 kS/s, 16-bit I2S codec-master mode and ACTIVE last. The board's
HPS codec mux must leave `HPS_I2C_CONTROL` low while FPGA initialization runs.
FPGA logic observes the resulting bus grant and fails closed when it is absent;
it never drives the HPS control signal.

This is source implementation, not proof that audio hardware is ready. The
portable PLL branch is only an average-rate test model. Step 18 still owns
external audio timing constraints/review. Step 20 still owns native Quartus and
TimeQuest results, PLL lock/frequency measurement, codec I2C ACK evidence,
measured BCLK/LRCK, and live sample evidence. Physical artifact-driven BRAM
replay remains a prerequisite before live audio can be claimed.

## Step-17 LTC2308 board protocol

The pinned DE1-SoC Rev-H converter is the Linear Technology LTC2308. The
DE1-SoC signal
named `ADC_CS_N` is the converter's `CONVST` signal despite the misleading
chip-select-style name. It idles low and conversion starts on a rising edge; it
is not a generic active-low SPI chip-select.

The wrapper contract is:

1. From idle-low, drive a short active-high CONVST pulse and then return low to
   start a conversion.
2. Wait the frozen 80 fabric cycles after CONVST, so the first SCLK rise occurs
   1.84 microseconds after conversion start and covers the 1.6-us maximum
   conversion time.
3. Clock exactly 12 result bits from `ADC_DOUT`.
4. While reading that result, shift the real six-bit configuration word for the
   next conversion on `ADC_DIN`.
5. Treat the first returned value after enable or a channel/configuration change
   as the previous configuration's value. Prime and discard it.
6. Assert `sample_valid_o` only for a result known to use the current requested
   configuration.

The real six-bit command comes from synchronized `SW[6:4]`, but it does not
follow switch movement live. The board top latches it when entering
`TSRC_ADC_LIVE` and holds it for that entire source epoch. A different command
requires leaving and re-entering ADC mode, which creates a new source epoch and
re-primes the converter before any result becomes sample-valid. This prevents
two channels from being silently mixed under one core/telemetry epoch.

`SW[7]=0` selects continuous scheduling. `SW[7]=1` selects one-shot requests
from debounced `KEY[2]`. Neither control bypasses the wrapper's idle/busy and
overrun handling.

CONVST width, the at-least-1.6-us wait, acquisition spacing, SCLK frequency, and
complete transaction length are checked against `CLK_HZ` with overflow-safe
wide cross-multiplied arithmetic. The cycle counts remain parameterized, but
compile-time assertions validate every override; literal defaults such as 2,
80, or 12 cycles are not accepted as the only timing proof.

The supported Rev-H board-level input range is 0 to 4.096 V. The wrapper
publishes a saturating 64-bit count only for eligible current-command samples;
request overrun and protocol/config failures remain explicit stickies. The ADC
adapter owns its separate seen/admitted/accepted/drop and clip/config
observability. These meanings are not aliases for reserved CSR overflow bits.

Channel selection may be
driven by synchronized board controls, but the six-bit configuration must not be
a constant placeholder. An explicit `sample_request_i` may remain inactive when
the wrapper's real continuous-conversion enable is active.

The explicit source/build selection is
`config/profiles/de1soc_adc_demo.json`. It freezes 100 ksample/s, 2.5 MHz SCLK,
straight-binary unsigned 12-bit data, code-2048 recentering, channel-at-epoch
entry, full telemetry, and DC blocking disabled. STATUS reports 100 ksample/s
only while ADC is active; audio and BRAM replay remain 48 ksample/s.

This source contract still does not prove SCLK/CONVST/DOUT post-fit timing,
analog settling, channel identity, voltage accuracy/noise, or operation against
physical LTC2308 hardware. Bring-up must verify a Rev-H PCB and LTC2308 marking;
older board revisions with another ADC are outside this profile. The converter
has no reset pin or guaranteed power-on channel configuration in this contract,
so idle-low outputs, a 92-cycle post-enable/abort recovery holdoff, and
prime/discard are mandatory. Requests during that holdoff are rejected with
sticky attribution. The profile keeps `SLP=0`;
the sleep-wake delay must not be added to normal awake transactions.

## Board status

`HEX0` through `HEX5` select real sample count, frame count, STATUS, and
overflow/drop snapshots. `LEDR` reports reset, heartbeat, real core-tap and
telemetry activity, ring configuration, writer busy state, overflow state,
full-path activity, and aggregated implementation faults.

The display is bring-up observability only. A changing counter or LED is not
proof of bit-accurate core behavior, valid packet bytes, successful DDR writes,
or correct hardware I/O.

## Filelist boundary

Both `filelists/rtl_de1soc_full.f` and
`filelists/quartus_de1soc.qsf.inc` list the source/core owner, telemetry/HPS
owner, audio PLL/I2C/I2S platform wrappers, ADC wrapper, and physical board top
exactly once in dependency order. They deliberately exclude
`trecap_core_telemetry_top.sv` and generated
`system.sv`:

- the standalone composition would add a second core to the board closure;
- generated Platform Designer HDL belongs to the vendor-generation/QIP flow,
  not the hand-written SystemVerilog filelist.

## Source gate and evidence boundary

Run:

```text
python3 scripts/check_de1soc_board_top.py
make check-de1soc-board-top
python3 scripts/check_de1soc_clock_reset.py
make check-de1soc-clock-reset
python3 scripts/check_de1soc_audio_path.py
make check-de1soc-audio-path
```

The machine-readable authority is
`config/boards/de1soc_board_top_integration.json`; its schema is
`spec/schemas/de1soc_board_top_integration.schema.json`. Passing the gate means
only that the checked-in Step-9 composition, Step-10 clock/reset source, and
Step-16 audio source structure agree with their contracts. The Step-16 audio
authority is `config/boards/de1soc_audio_linein.json` with schema
`spec/schemas/de1soc_audio_linein.schema.json`. RTL compile/elaboration,
functional tests, Platform Designer generation, Quartus compilation, TimeQuest
timing, I2C ACKs, measured clocks, and physical board evidence remain pending.
