# Source-to-core integration contract

> **Step 7 status:** `source_implemented_pending_rtl_compile_functional_verification_quartus_and_hardware_evidence`

Step 7 replaces the synthetic tap generator that previously lived in the DE1-SoC board top with
the real source-to-core path. The implementation boundary is
`rtl/top/trecap_source_core_integration.sv`. It normalizes four source modes, selects exactly one
through `trecap_source_mux`, drives `trecap_core_top`, and returns the real valid-only core taps,
safe boundaries, counters, and fault events to the CSR/telemetry hierarchy.

The machine-readable authority is
`config/boards/de1soc_source_core_integration.json`; its schema is
`spec/schemas/source_core_integration.schema.json`. The source-only gate is
`scripts/check_source_core_integration.py`.

Step 17 completes the checked-in ADC wrapper/profile contract on this existing
source boundary. It does not claim native RTL compile/simulation,
functional verification, Quartus, TimeQuest, working LINE-IN/ADC hardware, analog accuracy,
or hardware signoff.

## Integrated paths

The only legal sample path is:

```text
BRAM replay source --------------------+
audio_codec_wrapper -> audio adapter --+
adc_wrapper         -> ADC adapter ----+-> source mux -> mathematical core
diagnostic source ---------------------+                    |
                                                              +-> y output
                                                              +-> valid-only sample tap
                                                              +-> valid-only frame tap
                                                              `-> valid-only unique-bin tap
```

The real observation/transport path is:

```text
trecap_core_top taps
  -> trecap_source_core_integration
  -> de1_soc_trecap_top
  -> trecap_de1soc_full_top
  -> telemetry packetizers and FIFO
  -> HPS/DDR ring writer
```

No telemetry, FIFO, DDR, HPS, or Platform Designer ready signal returns into the mathematical
core. Core-local ready/valid is used only to keep each selected source beat atomic with core
acceptance. The board ties the exposed `y_ready_i` high; telemetry is not a `y` consumer and
cannot stall it.

The reverse control path is:

```text
CSR shadow/commit logic
  +-> ctrl.thr2_active -------------------------> core threshold
  +-> ctrl.source_mode + source_mode_apply_pulse -> source mux transition
  +-> clear_metrics_pulse ----------------------> safe metrics-clear queue
  `-> CLEAR_STICKY_FLAGS W1C -------------------> owned core/source sticky state

source/core integration
  +-> core_config_safe_boundary -> THR2 safe commit input
  +-> source_safe_boundary      -> source-mode safe commit input
  `-> clear_metrics_apply_pulse -> core + telemetry metric-epoch clear
```

## Clock and reset

The Step-7 source/core and logical transport hierarchy use one fabric domain:

```text
clock = clk_fabric
reset = rst_n_platform
```

`clock_reset_ctrl` qualifies released `KEY[0]` high for 20 ms, combines it with
the HPS-to-FPGA reset, and uses the sole at-least-two-stage fabric synchronizer
to produce `rst_n_platform`. The board therefore instantiates
`trecap_de1soc_full_top` with `SYNC_TOP_RESET_DEASSERTION=0`; a second hidden reset-release delay
would make the source/core and CSR/transport sides leave reset on different cycles.

Audio bit-clock capture has explicitly documented internal CDC logic and separate
receive-edge/transmit-edge reset-release synchronizers inside
`audio_codec_wrapper`. A complete stereo-frame async FIFO emits each
`clk_fabric`-domain raw event before the audio adapter is reached; a second async
FIFO carries best-effort core-y monitor frames back to BCLK. The ADC wrapper also
emits its raw sample event in `clk_fabric`.

## Source inventory

| Generated mode | Normalization owner | Input cadence | Step-7 status |
| --- | --- | --- | --- |
| `TSRC_BRAM_REPLAY` | `trecap_bram_replay_source` | `source_tick_i` | Source-connected with frozen zero-vector defaults. |
| `TSRC_ADC_LIVE` | `adc_wrapper` then `trecap_adc_adapter` | 100 kS/s raw `adc_sample_valid` | Step-17 source implements Rev-H LTC2308 CONVST/2.5-MHz serial timing, two-flop DOUT synchronization, epoch-latched channel command, first-result discard, signed normalization, accounting, and explicit ADC profile; Step-18 timing and Step-20 hardware evidence remain pending. |
| `TSRC_AUDIO_WRAPPER` | `audio_codec_wrapper` then `trecap_audio_adapter` | Raw `audio_sample_valid` | Step-16 source implements 12.288 MHz XCK, WM8731 FPGA-I2C init, 48 kS/s/16-bit codec-master I2S, async-FIFO CDC, and the explicit LINE-IN profile; Step-18 timing and Step-20 hardware evidence remain pending. |
| `TSRC_DIAGNOSTIC` | `trecap_diagnostic_source` | `source_tick_i` | Source-connected for non-signoff bring-up. |

BRAM replay and diagnostic sources can hold a valid beat between board sample ticks. Step 7 gates
both ready and valid acceptance with `source_tick_i`, so neither source silently runs at the
50 MHz fabric rate. Audio and ADC events carry their own raw sample cadence and are not gated by
the synthetic tick.

Every normalized source enters `trecap_source_mux`. Selecting an inactive or not-yet-configured
live source may correctly produce no core samples; the implementation must not bypass the mux or
fabricate live data.

## Exact BRAM replay and full-tail routing

BRAM replay retains the frozen C0 full-tail geometry. All arithmetic is widened before evaluating
the parameter expressions:

```text
Nframes  = floor((Ns + L - 2) / H)
tau_last = Nframes * H
Ny       = tau_last + G + L
Nflush   = Ny - Ns
Ndrain   = G + L = D
```

For the Step-7 board default `Ns=4096`, `L=256`, `H=128`, and `G=128`:

```text
Nframes  = 33
tau_last = 4224
Ny       = 4608
Nflush   = 512
Ndrain   = 384
```

The selected BRAM stream is split at exactly `tau_last`:

```text
sample_idx <  tau_last -> normal core analysis input
sample_idx >= tau_last -> WOLA tail-tick input only
```

The two paths are mutually exclusive. Tail ticks bypass the input ring, FFT, magnitude/mask, and
IFFT scheduling and advance only the synthesis WOLA drain path. `finite_stream_i` is asserted only
while BRAM replay is selected; ADC, audio, and diagnostic operation are open-ended streams.
`replay_tail_drain_phase_o` remains high while a selected tail token is held between board sample
ticks; only `tail_tick_valid_w` is tick-qualified as the WOLA handshake event.

A replay start or restart is accepted only when BRAM mode is selected, no source switch is
pending, no selected source beat is held, the core pipeline is idle, the `y` output is empty, and
the frozen build geometry is valid. An accepted replay start marks a source discontinuity before
the replay's first beat can reach the core.

`replay_done_o` is deliberately a source-token status: it means the final BRAM/tail token was
accepted. It is not an exact-completion or structural-quiescence claim for the core output path.
Those stronger claims remain the responsibility of the later verification/signoff layer.

## Source-mode transition

The CSR bank validates the requested enum and waits for `source_safe_boundary` before updating
its active source-mode value. Its post-boundary `source_mode_apply_pulse` then reaches the source
mux. Because that first safe-boundary wait has already happened, the mux's local
`safe_to_switch_i` is tied true; introducing a second unrelated wait could split the active CSR
mode from the actual mux mode.

For a real mode change, Step 7 performs this sequence:

```text
1. Detect requested mode != currently selected mode.
2. Assert the transition guard so ready and valid acceptance are blanked.
3. Apply the new mux selection.
4. Clear the source epoch/adapters that hold source-dependent state.
5. Pulse source discontinuity into the core, clearing input/frame/WOLA/delay alignment state.
6. Release the guard only after the registered clear/discontinuity edge.
7. Permit the first beat from the new source.
```

The public/core discontinuity output is a one-cycle event. The mux's following-cycle registered
apply/discontinuity evidence extends the transition guard and source-epoch clear, but is not ORed
back into that public pulse.

An idempotent commit to the already active mode is accepted without clearing or
discontinuity-marking the stream.

Integration `clear_i` is a datapath/source-epoch clear and preserves the registered active mux
selection. Shared `rst_n` is the coordinated reset that returns both CSR control and the mux to
the BRAM reset mode; this avoids silently splitting them when only datapath state is cleared.

The source-mode CSR safe boundary is asserted only when the integration is not clearing,
switching, or holding a pending transition and either:

- the selected source is empty; or
- the selected beat is accepted atomically.

A free-running sample tick by itself is not a safe-boundary proof.

## THR2 and metrics-clear boundaries

`core_config_safe_boundary` is true at a real core frame boundary or while the core pipeline and
`y` output are structurally idle. It is the only boundary returned to the THR2 shadow/commit cell.

`tap_frame_i.valid` is late observation data produced after frame processing. It must never be
ORed into the THR2 commit boundary; doing so could apply a pending threshold after a frame has
already begun. `trecap_de1soc_full_top` therefore forwards only its dedicated
`frame_boundary_i` input to the CSR bank.

A raw `clear_metrics_pulse` is retained in `metrics_clear_pending_q` until
`core_config_safe_boundary` is true. Repeated requests while one is pending coalesce because
clearing an already-to-be-cleared accumulator again has no additional state meaning.
`clear_metrics_apply_pulse_o` exposes the exact event applied to the core so the Step-8 telemetry
aggregate can clear on the same clock. It also asserts on a public source-discontinuity event,
because that event resets the core's metric state and therefore starts a new shared metric epoch.
The board telemetry path must consume this applied output rather than the earlier raw CSR pulse.

## Fault and W1C projection

`external_overflow_flags_set` is a set-event interface into the CSR bank. It must receive
one-cycle new-fault events, not persistent sticky levels. Step 7 edge-detects only faults with an
exact generated CSR meaning:

| Generated mask | Step-7 source |
| --- | --- |
| `TCSR_OVERFLOW_FLAGS_ARITHMETIC_OVERFLOW_MASK` | New core arithmetic overflow/saturation level. |
| `TCSR_OVERFLOW_FLAGS_RING_OVERFLOW_MASK` | New core retained-history/input-ring overflow level. |
| `TCSR_OVERFLOW_FLAGS_SOURCE_MODE_ERROR_MASK` | New mux invalid-mode or switch-reject event. |

The source-mux reject pulse also enters the dedicated external CSR-reject input so the command
reject counter records the event.

The delayed W1C owner pulse also re-arms the corresponding edge-history bit. If an owner remains
high or faults again on its clear edge, the integration emits a fresh set event after that clear;
it never reconnects a persistent sticky level directly to the CSR set interface.

Live wrapper drops, clipping, ADC protocol faults, replay configuration faults, and core protocol
faults do not have honest one-to-one assignments in the frozen CSR bit map. They remain on
dedicated status outputs and may drive board debug indicators. They are not silently aliased onto
an unrelated generated bit.

W1C clear requests are divided by ownership:

- arithmetic, OLA, and ring/history masks clear core-owned sticky state; and
- source-mode-error clears source/mux/adapter-owned sticky state.

## Board binding

`de1_soc_trecap_top` owns the physical wrappers and integration instances:

```text
u_audio_codec_wrapper
u_audio_pll_wrapper
u_audio_codec_i2c_init
u_adc_wrapper
u_source_core_integration
u_full_top
```

`KEY[0]` remains board reset. The debounced `KEY[1]` press requests BRAM replay. Switch bits select
the diagnostic generator's local mode only; they do not bypass the generated source-mode CSR.

The board connects real core taps and counters into `u_full_top`, connects
`core_config_safe_boundary` and `source_core_safe_boundary` into the two CSR commit boundaries,
and returns the new-fault and source-reject pulses to CSR accounting. The old board-local
synthetic sample/frame/bin tap generator is forbidden.

The audio source includes the checked-in peripheral PLL, FPGA-side open-drain
codec initialization, I2S, and FIFO CDC. Audio readiness requires qualified PLL
lock, `HPS_I2C_CONTROL` low so FPGA has the codec-bus grant, and codec init done;
the FPGA never drives that HPS mux control. Dedicated saturating 64-bit RX-
overflow, TX-overflow, and TX-underflow counters remain separate board
diagnostics. This source structure still does not prove native RTL compilation,
external timing, Quartus/TimeQuest closure, I2C ACKs, measured clocks, or live
samples.

Step 17 separately freezes the pinned Rev-H LTC2308 path at 100 ksample/s with
a 2.5 MHz registered `ADC_SCLK`. `ADC_DOUT` is the only asynchronous ADC input;
it passes a preserved two-flop synchronizer before the 12-bit word is assembled
with valid in `clk_fabric`. `SW[6:4]` is latched only on entry to
`TSRC_ADC_LIVE`; the first result is discarded because the six-bit command
shifted during a read applies to the next conversion. `trecap_adc_adapter`
recenters unsigned straight binary at code 2048 and accounts for raw, admitted,
accepted, and dropped events without bypassing the mux. No async FIFO or second
ADC RTL clock exists in this implementation.

Those source contracts still do not prove post-fit ADC I/O timing, physical
channel identity, analog behavior, or live samples. An older board revision
with a different ADC is unsupported by the Rev-H profile. Neither live path is
hardware-ready merely because its wiring exists, and BRAM replay remains the
correctness prerequisite.

## Source-only check and evidence boundary

Run from the repository root:

```bash
python3 scripts/check_source_core_integration.py
```

The checker works with or without the third-party `jsonschema` package. Its dependency-free
fallback enforces the checked-in schema subset, and the source checks enforce the frozen module
inventory, data/control paths, tail split, transition guard, real tap binding, fault event policy,
late-frame-boundary prohibition, and generated filelist placement.

Passing this check means only that the reviewed source files are mutually consistent. These
evidence fields remain false until their own later gates run:

```text
rtl_compile                = false
functional_verification    = false
quartus_compile            = false
live_audio_hardware_ready  = false
live_adc_hardware_ready    = false
hardware_signoff           = false
```
