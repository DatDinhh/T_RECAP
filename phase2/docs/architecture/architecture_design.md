# System architecture and implementation decisions

T-RECAP is a fixed-point FPGA signal-processing system with a separate observation
and control path. We process a signed 12-bit sample stream through a 256-point
STFT, a magnitude-squared threshold mask, and WOLA reconstruction. The HPS moves
committed telemetry records from DDR to a desktop dashboard; it does not perform
the signal-processing algorithm.

This document records our current design, explicit resource budgets, and the
implemented memory, scheduling, source, and platform contracts. The integrated specification in
`docs/specs/t_recap_phase2_integrated_spec.pdf` defines the algorithm and interfaces.
Its executable arithmetic constants are in `spec/generated/core_config.json` and
`spec/generated/width_config.json`, with the reference implementation in
`sw/reference_model/`.

## Project boundary

Our essential system consists of deterministic BRAM replay, the mathematical
core, threshold control, a bounded telemetry path, and a usable waveform/spectrum
and status display. LINE-IN is the main live demonstration path. Continuous ADC
acquisition is an additional board capability. Button-paced ADC acquisition and
LINE-OUT monitoring are optional board diagnostics.

We keep the baseline FFT size, hop, coefficient format, and rounding rules fixed.
Additional FFT sizes, network protocols, and adaptive suppression algorithms
are separate extensions. The Linux platform driver is part of the baseline: it
provides the exact noncached DDR mapping and holds codec-mux GPIO ownership.

## Data and control ownership

```text
BRAM replay -------------------------------------+
WM8731 -> stereo RX FIFO -> audio adapter --------+-> source mux -> input history
LTC2308 -> continuous-only core admission -> ADC -+                   |
diagnostic generator ----------------------------+                   v
                                  analysis window -> FFT -> canonical spectrum
                                                                  |
                                                       frame-owned THR2 mask
                                                                  |
                                                  IFFT -> WOLA -> delayed-x metrics
                                                                  |
                                     valid-only taps -> packetizer/FIFO -> DDR
                                                                         |
                                               PC dashboard <- UDP <- HPS consumer
```

The fabric clock is `CLOCK_50` at 50 MHz. Audio serialization has its own positive
and negative BCLK edges and crosses to fabric through async FIFOs. ADC serial
edges are registered fabric outputs; the ADC controller never clocks RTL from
`ADC_SCLK`. HPS, DDR, UDP, and dashboard congestion can discard telemetry but
cannot control mathematical-core ready signals.

Core-local ready/valid protects the atomic source beat and bounded history. A
live converter cannot be backpressured indefinitely: its adapter may discard
input. This is a separate failure from telemetry loss, and must not be presented
as equivalent to successful continuous acquisition.

## Frame-owned threshold

A THR2 CSR commit changes the active value at the existing configuration boundary.
The core captures `{frame_idx, THR2}` when the scheduler's frame request is accepted
by the input ring. That frame retains its snapshot until its final canonical bin
is accepted by the magnitude/mask stage. Later CSR commits cannot split one frame
between thresholds.

The metadata queue has four entries of 120 bits each. Its capacity participates in
frame admission: the scheduler and input ring either accept a frame together with
its metadata or do not accept it. A queue head/frame-index mismatch stalls mask
admission and sets the existing core protocol fault. Reset, core clear, and source
discontinuity invalidate the queue with the data path.

The scheduler's boundary pulse is registered after frame admission. Therefore a
commit triggered by that pulse affects subsequent frame admissions; the frame
that raised the pulse keeps its preceding threshold. STATUS reports the current
CSR value, while already admitted frames may still complete with older snapshots.
We do not claim that a STATUS packet identifies the threshold of every in-flight
spectrum. A future per-frame configuration identifier would require an explicit
packet-contract extension.

## Continuous and manual ADC operation

`SW[7]=0` admits periodic 100 ksample/s ADC events to the mathematical core.
`SW[7]=1` allows one debounced `KEY[2]` conversion request at a time for board
diagnostics. Manual events do not enter STFT/WOLA. The first conversion following
an enable/abort primes the converter's next-command pipeline and is discarded.

Switching between continuous and manual acquisition clears the DSP epoch and
briefly disables the ADC controller so an unfinished conversion cannot cross the
transition. The channel remains the selection latched on entry to ADC source
mode; changing channel still requires leaving and re-entering that source.

With manual ADC selected, FPGA STATUS/METRICS use `sample_rate_hz=0` to mean there
is no periodic DSP sample stream. The dashboard labels that condition explicitly.
HPS-synthesized diagnostic STATUS uses zero to mean that physical cadence is not
available through the current CSR ABI; the dashboard distinguishes this from a
normal FPGA STATUS. This avoids guessing a rate after a source or manual-mode
change. The standalone dummy-UDP generator retains its requested diagnostic rate.
For `SW[9:8]=00`, the board displays the low 12 bits of the eligible raw-sample
count on HEX5..3 and the latest 12-bit raw code on HEX2..0. Other display pages
retain their normal meanings. This display policy does not change the packet format. Source health has its
own additive capability-discovered CSR page described below.

## Profiles are executable configuration

`scripts/resolve_runtime_profile.py` resolves a selected profile through the
existing profile/schema logic and generated enum/mask contracts. It emits:

- An effective JSON manifest with input selection, telemetry settings, source
  hashes, top-level parameters, and HPS startup arguments.
- A run-local QSF include for actual top-level parameters, including telemetry
  cadence, replay geometry/file, audio word/MCLK settings, and optional LINE-OUT.
- The exact argument vector for HPS source-mode, packet mask, spectrum format,
  decimation, diagnostic sample rate, and initial threshold commits.

`scripts/quartus/build_de1soc.sh --profile <profile>` creates and applies the QSF
include through `TRECAP_PROFILE_QSF`. The source-owned Quartus entry point is
`platform/de1soc/quartus/trecap_de1soc.qpf`. Vendor-generated HPS files are still
produced by the Platform Designer flow. Direct GUI builds use RTL defaults unless
the profile include is selected explicitly. Build `--dry-run` writes the resolved
configuration and log plan into its run directory but does not invoke Quartus.

`sw/hps/scripts/run_udp_streamer.sh --profile <profile>` applies the same profile
before starting the HPS binary and saves `effective_runtime.json` next to the launch
manifest. Explicit launcher options follow profile arguments and therefore override
them; the final argument vector is recorded. Without `--profile`, the launcher
retains STATUS-only startup. Source mode always resets to BRAM in hardware, and
HPS applies the selected source through the normal shadow/commit path.

Telemetry cadence is synthesized, so the bitstream and HPS launch must use matching
profiles. The current CSR ABI does not contain a bitstream/profile hash and cannot
automatically enforce that pairing. Use the paired build and launch manifests.
Selecting a BRAM profile never starts replay automatically. A zero metrics cadence
produces no metrics tick. LINE-OUT additionally requires `AUDIO_LINEOUT_ALLOWED=1`
in the bitstream and `SW[3]=1`; shipped profiles keep it disabled.

## Timing and cycle budget

These counts follow the implemented state machines at the fixed 256/128/384
geometry. They are source schedules, not measured execution or fitted timing.

| Quantity | 48 ksample/s BRAM / LINE-IN | 100 ksample/s continuous ADC |
| --- | ---: | ---: |
| Average fabric clocks per sample | 1041.67 | 500 |
| Frame rate at H=128 | 375/s | 781.25/s |
| Fabric clocks per hop | 133333.33 | 64000 |
| Hop duration | 2.6667 ms | 1.28 ms |
| Algorithmic alignment D=384 | 8 ms | 3.84 ms |

Each iterative transform performs 1024 butterflies at seven clocks each. Its
inclusive local service count is 7936 clocks: 256 load, 7168 compute, 512 output.
Canonicalization adds a four-clock sequence per output bin. The connected
pipeline has slower input spacing than those local block counts, so we budget
it from frame request acceptance instead of simply adding local latencies.

| Connected boundary | Latest edge relative to frame request acceptance at 0 |
| --- | ---: |
| Final analysis-window sample accepted by FFT | 515 |
| Final FFT output accepted by canonicalizer | 8195 |
| Final canonical output accepted by mask | 9219 |
| Final rebuilt spectrum sample accepted by IFFT | 9221 |
| Final IFFT sample accepted by WOLA | 16901 |
| WOLA product drain, 128 emissions and 256 OLA updates complete | 17671 |
| Conservative bound including metrics pipeline allowance | 17673 |

We allocate **18000 fabric clocks (360 us)** for this work. At 100 ksample/s this
is 28.125% of the 64000-clock hop and fits within the G=128 sample scheduling
cushion. The next frame request arrives after the prior frame releases every
store, closing the no-prior-frame-backlog assumption for steady operation.

The bound assumes ordered legal input, a cleared/initialized epoch, normal
periodic source cadence, and continuously ready core output. The physical top
meets the output condition because telemetry taps have no ready return path.
The generic reusable core permits external output stalls; unbounded stalls have
no finite service guarantee. WOLA needs 384 clear-free clocks to scrub its RAM
before accepting its first frame. Source recovery provides 4096 settling clocks
only after physical capture-stop acknowledgement.

Input extraction temporarily refuses new samples for about 514 clocks. Each live
adapter holds one pending sample. At 100 ksample/s the extraction request follows
the just-accepted hop-ending sample by about two clocks, so only the next raw
sample arrives during that refusal interval; it is consumed before the following
sample at about 1000 clocks. This argument requires healthy periodic phase and no
existing backlog. We do not claim arbitrary-phase or burst tolerance for a
one-entry adapter. Any actual refused event or sequence discontinuity stops the
epoch through the source supervisor.

A conservative delayed-history allowance is 549 samples, below its 1024 entries,
using `D+H+ceil(18000/500)` with one extra boundary sample. Finite replay tail
is paced by source ticks; its bound after frame work is `(D+1)*T_tick_max+4`,
not the local unpaced 768-clock WOLA drain. This is 192504 clocks at 100 ksample/s
or at most 401174 clocks with 1042-clock maximum tick spacing at 48 ksample/s.
It is a finite flush cost, separate from the recurring hop budget.

The algorithmic delay excludes codec analog delay, clock-domain FIFO residence,
DDR/HPS scheduling, network transmission and dashboard redraw. Detailed local
schedules are in [transform_microarchitecture.md](transform_microarchitecture.md)
and [storage_schedule.md](storage_schedule.md).

## Storage implementation and capacity

Large frame, history, and payload stores use explicit synchronous M10K port
schedules. Payload reset is replaced by ownership/validity invalidation or a
sequential scrub. The packet FIFO moves descriptors between nine ownership slots;
the DDR builder reads one payload RAM and generates header/padding while streaming.
Neither moves an entire resident record through a wide register vector.

| Storage group | Logical geometry | Planning allowance |
| --- | --- | ---: |
| Input history, delayed history, WOLA frame/OLA/window, packet payload and DDR builder payload | Seven non-replay arrays, 240000 bits | 31 M10K |
| FFT / IFFT / canonicalizer work RAM | 256x56 /256x72 /256x56 | 10 M10K |
| Direction-specific twiddle ROMs | Four 256x17 components | 4 M10K |
| Main-profile replay | 4096x12 | 8 M10K using conservative 512x20 slices |
| Analysis-window lookup | 256x16 | 4096 bits of logic ROM allowance |
| Audio RX / optional TX FIFO | 8x96 /512x33 | 768 /16896 logic payload bits |
| WAVE / SPEC / STATUS+METRICS capture | Fixed packet capture buffers | 9216 /4248 /1024 register bits |
| Threshold metadata / input validity | 4x120 /512x1 | 480 /512 register bits |

The **53 M10K planning allowance** deliberately uses conservative legal slices;
it is not a fitted count. It excludes control/arithmetic registers, pointer
metadata, packet header registers and implementation packing losses. Both
transforms have four logical DSP multipliers, with 36x17 or 28x17 operands;
physical DSP block use depends on width decomposition. Optional LINE-OUT is
constant-disabled in shipped profiles and is budgeted separately when enabled.
The device fit and selected ROM packing must come from Quartus reports.

WAVE sample values alone require 288000 B/s at 48 ksample/s or 600000 B/s at 100 ksample/s.
For the shipped profiles (STATUS at most 10 Hz and METRICS at most 20 Hz), the
active packet contracts bound a DDR record to 1216 bytes. As a conservative
all-types-every-frame envelope, four records per 100 ksample/s hop consume at most
4*1216*781.25 = **3.8 MB/s** of ring space. This deliberately overestimates WAVE,
which groups 192 samples, and small STATUS/METRICS records. Four maximum builder
records consume at most 4*1952 = 7808 fabric clocks before external DDR stalls;
the packet FIFO allows up to 600 clocks to transfer one configured maximum payload
into the builder. Counting capture and emission serially gives at most 10208 clocks
for four records, plus bounded control transitions and external Avalon stalls.
We allocate 11000 clocks of local telemetry service per hop; external memory stalls
consume queue/ring headroom rather than extending the mathematical-core schedule.

The usable ring capacity is 33554432-64 bytes, so the 3.8 MB/s envelope allows about
**8.83 seconds** with no consumer service. This is a capacity calculation, not an
HPS scheduling guarantee. A longer outage drops telemetry under the documented
priority/ring policy and leaves the core running. Record formats, guard space,
and pointer ownership remain defined in [de1soc_ddr_ring_ownership.md](de1soc_ddr_ring_ownership.md).

## Source continuity and recovery

`trecap_source_core_integration` owns physical readiness, sequence continuity,
source loss and epoch recovery. Its additive SOURCE_HEALTH page begins at 0x100
and is discovered through capability 0x53480100. Snapshot captures 31 words;
existing CSR offsets and UDP formats are preserved. The HPS utility reads each
word with an aligned 32-bit MMIO access and can request an explicit rearm.

Sequence gaps, refused live events, readiness loss and watchdog timeout invalidate
the active epoch and stop acquisition. Rearm waits for the wrapper's physical
stop acknowledgement and the complete settling interval before new admission.
Diagnostic status is separate from metric history. The register definitions,
lifetime counters and recovery commands are in [source_health.md](source_health.md).

## Platform and deployment ownership

The source baseline is Rev-H, Quartus 20.1 Platform Designer, Linux 6.12.109,
and a matched ARM hard-float toolchain/root filesystem. The actual hardware must
be reconciled with that selection before deployment. The source-owned board DTS
includes the fixed 32 MiB no-map DDR reservation and a platform device with a
GPIO descriptor for HPS GPIO48 (portb line 19).

The kernel driver holds the FPGA codec-bus grant and exposes `/dev/trecap-ring`
with an exclusive read-only noncached mapping. Its ioctl identifies ABI, physical
base, length and mapping properties. Userspace refuses a mismatch and has no
cached or `/dev/mem` ring fallback. CSR access remains `/dev/mem`. The platform
service precedes the streamer, whose device policy permits both required nodes.
See the [Linux build/install recipe](../../platform/de1soc/linux/README.md) and
[source boot template](../../platform/de1soc/linux/boot.cmd). The selected U-Boot
flow disables bridges, loads the full RBF, restores bridges from the matching
SPL handoff, and boots the selected kernel/DTB. Stock DE1-SoC handoff values
do not automatically enable this project's FPGA-to-SDRAM port.

The physical timing contract defines codec launch/capture edges, ADC serial
schedule and return-path allocation, I2C ACK synchronization, and narrow
clock-crossing route/skew bounds. Generated PLL/HPS clocks remain vendor-owned.
See [physical_timing.md](physical_timing.md) for numeric values and their sources.

Board reset is qualified and combined with HPS-to-FPGA reset before synchronized
fabric release. Audio domains release reset locally. Telemetry soft clear leaves
the mathematical epoch intact; source discontinuity clears dependent history.

Deployment loads a matched FPGA image and boots the selected kernel/DTB with
bridges configured, loads the platform driver, and starts HPS with the paired
runtime profile. HPS identifies capabilities, disables/drains/clears transport,
commits ring geometry and Rd=0, applies controls, then enables transport. Runtime
FPGA reprogramming or DT hot removal is outside this static boot lifecycle.

## Completion boundary

The baseline architecture now has source implementations for the arithmetic
schedule, storage ports/reset policy, source continuity, health observability,
board timing allocations, DDR cache policy and Linux ownership. They are
concrete design choices with corresponding RTL/C/DT/SDC source.

The native11 build generated the actual Platform Designer/PLL products and
completed placement and routing. Subsequent source revisions require their own
build and timing reports; see [architecture_implementation.md](architecture_implementation.md)
for current results and [build_order.md](build_order.md) for the acceptance flow.
The installed Standard Edition evaluation flow has not produced a programmable
SOF. A compiled kernel/DTB/module, matched board boot configuration, and physical
audio/ADC operation remain pending. Source elaboration and fitted reports do not
establish functional correctness; functional verification and board evaluation
remain separate project work.

The memory allowance uses the supported [Cyclone V M10K configurations](https://www.intel.com/content/www/us/en/programmable/quartushelp/17.0/reference/glossary/def_m10k.htm), including 512x20 slices for conservative planning.
