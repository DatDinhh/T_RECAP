# T-RECAP Phase 2

Transform-domain Representation and Energy-aware Computation Accelerator with Controlled Precision.

This repository is the Phase 2 implementation repository for the T-RECAP DE1-SoC system. It is organized for a core-first FPGA implementation, followed by a non-stalling telemetry path through HPS-visible DDR, HPS Ethernet/UDP streaming, and a PC dashboard.

The current source package includes an LF-derived embedded reference-model
proxy and legacy Phase 1 Haar RTL/DV files. It deliberately does not bundle
the truncated reference-model ZIP. Treat the embedded software package as a
reference model until the team verifies a clean source archive and freezes the
board-replay signoff results. Do not call it the final golden authority before
those gates pass.

## Current authority

The integrated Phase 2 specification PDF is not bundled in this source
package. Do not claim PDF provenance from this tree. After an independently
verified copy is supplied, place it at:

```text
docs/specs/t_recap_phase2_integrated_spec.pdf
```

The historical uploaded name was:

```text
doneeeeeeeeee.pdf
```

Keep the independently verified hash and rename record in
`docs/specs/README.md` when the PDF is restored.

## Deprecated documents

Older Phase 2 Algorithm Report drafts are historical only.

Do not use `D = L` for the current DE1-SoC baseline.

Use the integrated Phase 2 specification: Core Revision J + Telemetry Revision G.

Current baseline delay:

```text
D = L + G = 384 samples
```

Legacy Phase 1 documents and files are allowed only under `legacy/phase1/`. They must not compile into the Phase 2 root build.

## Baseline system

Phase 2 implements a deterministic fixed-point STFT/WOLA selective-suppression pipeline.

```text
BRAM replay / LINE-IN audio / ADC / diagnostic source
    -> trecap_source_core_integration
    -> FPGA STFT/WOLA selective-suppression core
    -> non-stalling FPGA telemetry taps
    -> FPGA telemetry packet formatter
    -> FPGA DDR ring writer
    -> HPS DDR ring reader
    -> HPS UDP streamer over Ethernet
    -> PC dashboard
```

Reverse control path:

```text
PC command
    -> exact-IP-and-port HPS command listener
    -> versioned parser and RFC1982 result cache
    -> HPS lifecycle/replay command bridge
    -> generated CSR writes and readback
    -> FPGA safe-boundary/replay owners
    -> version-2 command result to the validated PC peer
```

The FPGA fabric owns all real-time signal processing. HPS software performs transport and control only. The PC visualizes data and sends commands only. Ethernet telemetry is not the bit-accurate correctness path.

Architecture implementation is source-complete through Step 17. Step 17 closes
the checked-in DE1-SoC LTC2308 path at 100 ksample/s with a 2.5 MHz registered
serial clock, a two-flop `ADC_DOUT` synchronizer, six-bit next-conversion
commands, source-epoch channel latching, a 92-cycle post-enable/abort recovery
holdoff, first-result prime/discard, unsigned
12-bit-to-signed-core normalization, saturating sample/drop accounting, and the
explicit `config/profiles/de1soc_adc_demo.json` profile. The ADC rate is not the
48 ksample/s audio/BRAM rate; STATUS reports 100 ksample/s only while ADC is the
active source. This remains source implementation, not Quartus, TimeQuest,
measured serial timing, analog, or live-board evidence.

Step 15 previously closed
the PC dashboard source architecture around the generated telemetry parser. It
keeps dedicated waveform and error views, a latest-spectrum view plus a bounded
SPEC64/SPEC129 history heatmap keyed by `frame_idx`, rolling packet-rate and
sequence-loss observability, a live suppression-overlay toggle, and separate PC
receive, HPS transport, FPGA packet FIFO, and FPGA DDR-writer loss domains.
Malformed packets, UDP truncation or
oversize, and the protocol `payload_truncated` flag remain distinct visible
states. Live controls submit through one persistent, asynchronous, serialized
`CommandClient` session, preserve monotonic version-2 sequencing, and return
visible command disposition/reason/readback without blocking telemetry receive
or GUI refresh. Framed capture replay preserves recorded receive timestamps, and
validated append continues an existing capture without a second file header.

`make dashboard-step15-test` and the cumulative `make step15-source` are
host/source gates only. They do not prove live HPS/FPGA UDP traffic, a ten-minute
dashboard soak on the demo PC, a hardware CSR result, Ethernet-disconnect
behavior, or bit-accurate correctness signoff.

Step 14 previously kept the exact Revision-G version-1 28-byte, seven-command
protocol unchanged and added an explicit version-2 command extension using the
same request layout and an exact 32-byte result for every version-2 non-PING
request. It closed exact trusted-peer IP-and-port binding, RFC1982 at-most-once
handling, RESET-to-CONFIGURE-to-ENABLE transport lifecycle ownership, counter
clear, BRAM-replay admission/result observation, and raw STATUS/VERSION readback
against generated CSR minor 1.8. The checked-in source checker, non-native RTL
structural/model checker, and HPS/PC host-test sources do not prove a live
PC-to-HPS UDP exchange, HPS Linux mappings, lightweight-bridge traversal, FPGA
command application, native RTL simulation, Platform Designer generation,
Quartus/TimeQuest, or hardware behavior.

Step 13 previously closed
the checked-in HPS path from the frozen CSR and reserved-DDR interfaces to
Revision-G UDP: strict runtime configuration and live-reservation admission,
validation of all five normal record types, exact-tail WRAP handling,
send/drop/consumer-commit ordering, an exactly-once malformed latch and re-arm,
and UDP-only diagnostic STATUS mode. The source checker and RAM-backed host test
do not prove an active DTB reservation, native HPS `/dev/mem`, physical Ethernet,
systemd deployment, FPGA execution, Quartus/TimeQuest, or hardware behavior.

The FPGA/board implementation is source-connected through Step 14. Its
typed CSR/F2SDRAM Platform Designer graph, generated-system wrapper,
source/core integration, and physical Quartus top bind real sources, core taps,
counters, safe boundaries, transport-counter clear, and replay-result ownership
without changing the source-only evidence scope.

Step 12 previously froze DDR-ring ownership and the Linux reservation source
contract.
The FPGA is the sole producer-pointer owner, the HPS is the sole
consumer-pointer owner, WRAP consumes the exact remaining physical tail, and a
transport-reset epoch returns both sides to a defined empty-ring baseline. The
official Linux reservation source is
`platform/de1soc/linux/trecap_reserved_memory.dtsi`; `mem=992M` is not a second
active mechanism. The checked-in DTS, source checker, and directed testbench are
source implementation only and do not prove a compiled DTB, a booted Linux
reservation, runtime isolation, or hardware behavior.

Step 11 previously closed the deterministic BRAM-replay source hierarchy through
exact mathematical-core completion, STATUS telemetry, and the HPS-visible DDR
writer boundary. Its end-to-end testbench and runners remain named Step 11
because they are the cumulative historical gate; their presence is not accepted
ModelSim/Questa execution evidence.

Step 8 also turns `rtl/top/trecap_core_telemetry_top.sv` into a real reusable
normalized-source composition: exactly one `trecap_core_top` feeds exactly one
`trecap_telemetry_top` through direct valid-only taps. STATUS uses the core's
authoritative sample/frame counters, METRICS snapshots the core-owned error
aggregates, and the safe applied `CLEAR_METRICS` event defines one shared metric
epoch. `filelists/rtl_core_telemetry.f` builds that standalone variant, while the
DE1-SoC hierarchy continues to use its existing source/core owner plus the
telemetry-only logical top so it never instantiates a second core. Telemetry
record backpressure terminates below the packet FIFO and cannot reach source or
core ready paths.

Step 9 replaces the remaining physical-board scaffold. The DE1-SoC top now
binds the generated Platform Designer CSR and F2SDRAM channels end to end,
routes real audio and LTC2308 capture into the sole source/core owner, fans real
core taps and counters into telemetry/HPS, monitors the always-accepted core y
stream through best-effort audio line-out, and drives LED/HEX state from real
reset, core, telemetry, ring, writer, and fault signals. The LTC2308 contract
uses idle-low CONVST with a short active-high pulse, waits at least 1.6 us, then
clocks twelve result bits while shifting the six-bit next configuration; the
first old-configuration result is discarded. Step 16 replaces the audio
fail-closed placeholder with a source-level board path. A peripheral-only
fractional PLL wrapper drives `AUD_XCK` at 12.288 MHz from `CLOCK_50`; it does
not create a second fabric clock. FPGA-owned, open-drain I2C configures the
WM8731 at 7-bit address `0x1a` for 48 kS/s, signed 16-bit I2S with the codec as
BCLK/LRCK master. Configuration and capture remain inhibited until PLL lock and
the FPGA I2C-bus grant are present. `HPS_I2C_CONTROL` must stay low during FPGA
codec initialization; the FPGA observes that grant and never drives the HPS
control signal.

Step 10 freezes the board clock/reset architecture. One active 50 MHz fabric
domain, `clk_fabric`, comes directly from `CLOCK_50`. `clock_reset_ctrl` owns
the complete hard-reset path: it requires `KEY[0]` to remain released for 20 ms,
combines that qualified board request with the active-low HPS-to-FPGA reset, and
passes the result through one reset synchronizer of at least two stages to create
the canonical `rst_n_platform`. All fabric owners release together; the physical
top does not add a second reset synchronizer. Sample, STATUS, METRICS, and
heartbeat events are exact-average fractional clock-enable pulses, never clocks.
The LTC2308 continuous-request scheduler uses the same exact-average fractional
method at its configured 100 kHz rate; `ADC_SCLK` is a 2.5 MHz registered
protocol output, not a fabric clock. The single-bit off-chip `ADC_DOUT` return
passes an explicit two-flop synchronizer before fabric-domain word assembly.
Telemetry soft reset is a synchronous transport clear and does not create a
derived asynchronous reset or reset the mathematical core.

`CLOCK2_50`, `CLOCK3_50`, and `CLOCK4_50` remain reserved inputs. A split-clock
fabric is unsupported until its interfaces and CDC paths are redesigned. The
codec BCLK domain has edge-specific local reset-release synchronization.
Complete receive frames and processed monitor frames cross between codec BCLK
and `clk_fabric` through asynchronous FIFOs. Dedicated saturating 64-bit counters
record receive overflow, transmit overflow, and transmit underflow; these audio
diagnostics are not aliases of reserved CSR overflow bits. The explicit
`config/profiles/de1soc_linein_demo.json` profile selects the frozen 48 kS/s,
16-bit, codec-master configuration.

The separate `config/profiles/de1soc_adc_demo.json` profile selects the onboard
12-bit LTC2308 at 100 kS/s. `SW[6:4]` is latched only on entry to
`TSRC_ADC_LIVE`; its single-ended, unipolar, awake command remains constant for
the epoch. `SW[7]` selects continuous requests or debounced `KEY[2]` one-shot
requests. Raw straight-binary codes are recentered at 2048 before entering the
signed 12-bit core stream. The default board profile remains BRAM replay, and
the independent LINE-IN profile remains usable.

This is source implementation, not verification or hardware signoff. Quartus
20.1 Platform Designer generation/normalization, generated ABI checking, RTL
elaboration/compile evidence, accepted functional simulation, compiled-DTB and
Linux boot/runtime reservation evidence, full Quartus/TimeQuest compile and
timing evidence, physical BRAM-replay comparison, measured PLL/XCK/BCLK/LRCK
behavior, codec I2C ACKs, measured ADC serial/I/O timing, analog accuracy, and
live audio/ADC board evidence remain separate
pending gates. BRAM replay remains the correctness prerequisite; Step 18 owns
external audio/ADC timing closure and Step 20 owns Quartus and hardware evidence.

## Core baseline constants

These constants come from the generated contract flow. Do not duplicate them manually in RTL, HPS C, or Python.

```text
N = 12          external signed sample width
L = 256         FFT length
P = 8           radix-2 stages
H = 128         hop size
F = 15          fractional precision
G = 128         scheduling cushion
D = 384         exact causal delay, D = L + G
W_Qw = 16       unsigned window coefficient width
W_tw = 17       signed twiddle coefficient width
W_mag2 = 56     magnitude-squared / THR2 width
PROTECT_DC = 1
PROTECT_NYQ = 0
```

## Provenance tags

The repo tree uses these tags in architecture documents and staging notes.

```text
[0] imported from the embedded Phase 2 reference-model proxy, or generated by that reference model
[1] hand-written implementation/documentation/config source file
[2] generated file; do not edit by hand
```

`README.md` is `[1]`.

## Naming policy: reference model vs golden model

The embedded proxy was derived from a reference-model package; it is not final
golden signoff authority and does not prove the missing clean ZIP.

Use these names during implementation:

```text
sw/reference_model/             current imported Phase 2 software reference package
artifacts/reference_outputs/     current reference outputs produced by the reference model
```

The specification may use `sw/golden/` and `artifacts/golden/` as final signoff names. Do not rename the current reference package to golden until the following are true:

```text
1. algorithm release is frozen
2. coefficient and vector artifacts are frozen
3. canonical SHA-256 hashes are frozen
4. RTL simulation matches reference artifacts
5. BRAM replay on FPGA matches mandatory artifacts
6. release manifest records the frozen authority
```

### v69 reference integrity status

The current embedded package is an LF-derived `0.1.0-dev.1` development
release. Its embedded `artifacts/golden/` DAG and the architecture-level
`artifacts/reference_outputs/` DAG are independently complete and
hash-consistent.

The original uploaded ZIP was truncated, so its claimed `caf0...` SHA-256 is
not treated as verified provenance. The v3 import manifest deliberately records
`embedded_proxy_unverified_source_archive`; the signoff gate
`--require-verified-source` therefore fails until a complete independently
hash-pinned source archive is supplied.

For Makefile compatibility, targets may still use names such as `make golden`, but the README and architecture notes shall state whether that target is producing provisional reference artifacts or frozen golden artifacts.

## Repository ownership rules

These rules are non-negotiable.

1. `rtl/core/` shall build without HPS, Ethernet, DDR ring, UDP packets, dashboard code, or board-specific wrappers.
2. BRAM replay and artifact comparison come before live audio or Ethernet demo work.
3. CSR offsets, packet IDs, payload sizes, status bits, version numbers, and core constants shall come from generated shared headers.
4. `trecap_ddr_ring_writer.sv` belongs only under `rtl/hps_bridge/`.
5. `rtl/telemetry/` formats records but does not write DDR.
6. Telemetry shall not backpressure sample input, frame scheduling, FFT/IFFT, WOLA, or metrics accumulation.
7. HPS software shall not compute FFT, IFFT, masks, WOLA, reconstruction, or sample-by-sample error.
8. PC dashboard output is observability, not correctness signoff.
9. Generated files shall not be hand-edited.
10. Phase 1 files shall stay quarantined under `legacy/phase1/`.

## Intended top-level tree

```text
T_RECAP_Phase2/
├── README.md
├── Makefile
├── CMakeLists.txt
├── .gitignore
├── .editorconfig
├── .clang-format
├── .pre-commit-config.yaml
│
├── docs/
│   ├── specs/
│   ├── architecture/
│   ├── bringup/
│   └── deprecation/
│
├── spec/
│   ├── generated/
│   ├── schemas/
│   └── normative/
│
├── config/
│   ├── profiles/
│   └── boards/
│
├── scripts/
│   ├── gen_headers.py
│   ├── gen_filelists.py
│   ├── check_generated.py
│   ├── lint_repo_layout.py
│   ├── package_artifacts.py
│   ├── clean_outputs.sh
│   ├── format.sh
│   ├── lint.sh
│   ├── quartus/
│   └── bringup/
│
├── filelists/
│   ├── rtl_core.f
│   ├── rtl_core_plus_fft.f
│   ├── rtl_telemetry.f
│   ├── rtl_hps_bridge.f
│   ├── rtl_bram_replay_system.f
│   ├── rtl_de1soc_full.f
│   └── quartus_de1soc.qsf.inc
│
├── rtl/
│   ├── include/
│   ├── common/
│   ├── interfaces/
│   ├── sources/
│   ├── core/
│   ├── fft/
│   ├── telemetry/
│   ├── hps_bridge/
│   ├── platform/de1soc/
│   └── top/
│
├── sw/
│   ├── reference_model/
│   ├── hps/
│   └── pc_dashboard/
│
├── artifacts/
│   ├── coefficients/
│   ├── test_vectors/
│   ├── reference_outputs/
│   ├── manifests/
│   └── telemetry_captures/
│
├── constraints/
│   └── de1soc/
│
├── platform/
│   └── de1soc/
│       ├── qsys/
│       ├── address_map/
│       ├── linux/
│       └── generated_notes/
│
├── ci/
│   ├── github/
│   └── docker/
│
├── legacy/
│   ├── phase1/
│   └── deprecated_phase2_docs/
│
└── runs/
```

## Directory responsibilities

| Directory | Owner / responsibility |
|---|---|
| `docs/specs/` | Frozen specification PDFs and spec index. |
| `docs/architecture/` | Module ownership, dependency rules, generated contracts, memory map, build order, coding style. |
| `docs/bringup/` | DE1-SoC programming, HPS Ethernet setup, DDR ring bring-up, BRAM replay signoff, audio bring-up, and Rev-H LTC2308 ADC bring-up. |
| `docs/deprecation/` | Deprecated-document warnings and Phase 1 quarantine notes. |
| `spec/generated/` | Source-of-truth JSON contracts for core constants, CSR map, packet layouts, interface types, and generation manifest. |
| `spec/schemas/` | JSON schemas used to validate contract files and artifacts. |
| `config/profiles/` | Runtime/build/demo profiles. Profiles select modes; they do not redefine core constants. |
| `scripts/` | Header generation, filelist generation, repo checks, artifact packaging, helper scripts. |
| `filelists/` | Generated compile-order filelists consumed by simulation and synthesis flows. |
| `rtl/include/` | Generated and checked SystemVerilog packages. No conflicting hand-coded constants. |
| `rtl/common/` | Reset sync, CDC helpers, FIFOs, skid buffers, RAM wrappers, fixed-point helpers. |
| `rtl/interfaces/` | Typed sample, frame, tap, record, CSR, and Avalon-style interfaces. |
| `rtl/sources/` | BRAM replay source, audio adapter, ADC adapter, diagnostic source, source mux. |
| `rtl/core/` | STFT/WOLA core excluding FFT/IFFT implementation. No HPS/Ethernet dependency. |
| `rtl/fft/` | Custom FFT/IFFT or isolated vendor-IP wrapper matching the fixed-point contract. |
| `rtl/telemetry/` | Packet scheduler, WAVE/SPEC/METRICS/STATUS packetizers, packet FIFO. No DDR write master. |
| `rtl/hps_bridge/` | CSR bank, shadow/commit logic, pointer control, DDR record builder, DDR ring writer. |
| `rtl/platform/de1soc/` | Board wrappers, clocks/resets, Platform Designer wrapper, audio/ADC wrappers. |
| `rtl/top/` | Pin-agnostic build variants, including the source-to-core integration layer and logical transport top. |
| `sw/reference_model/` | Imported Phase 2 reference software, coefficient/vector tools, artifact writer/checker. |
| `sw/hps/` | HPS CSR access, DDR ring reader, UDP streamer, command server, status patcher. |
| `sw/pc_dashboard/` | UDP parser, dashboard buffers/plots, command client, PC config. |
| `artifacts/` | Frozen or provisional coefficients, vectors, outputs, manifests, captures. |
| `constraints/de1soc/` | QSF, SDC, clocks, pin assignments. |
| `platform/de1soc/` | Platform Designer/Qsys files, address maps, the canonical Linux reserved-memory DTS source, and generated-system notes. |
| `legacy/` | Quarantined Phase 1 and deprecated drafts. Not part of Phase 2 build. |
| `runs/` | Local generated run/build output. Not source-controlled except `.gitkeep`. |

## Build milestones

Implementation order is fixed. Do not start Ethernet or dashboard work before C0 is stable.

| Milestone | Work | Exit condition |
|---|---|---|
| R0 | Repo skeleton and legacy quarantine | Phase 2 root has no active Phase 1 build files. |
| R1 | Generated schema flow | `gen_headers.py` emits SV/C/Python headers from one schema source. |
| R2 | Coefficients and vectors | Manifests contain row counts and canonical hashes. |
| R3 | Reference model skeleton | Tool emits `config.json`, `x_in.memh`, and provisional output artifacts. |
| R4 | Source/core RTL skeleton | Core-only RTL compiles without telemetry/HPS/platform. |
| R5 | FFT/IFFT and STFT/WOLA core | Core exposes sample output, frame stats, and metric/tap signals. |
| R6 | Telemetry packetizers | Packetizers emit formatted records into packet FIFO; no DDR writer in telemetry. |
| R7 | HPS bridge RTL | CSR bank, pointer control, record builder, DDR writer integrated. |
| R8 | DE1-SoC platform | Physical `de1_soc_trecap_top`, source/core integration, Platform Designer wrapper, constraints, and address map present. |
| R9 | HPS UDP streamer | Step-13 source and RAM-backed host gates cover strict config, ring validation/WRAP, UDP send/drop/commit behavior, malformed latch/re-arm, and dummy diagnostic STATUS; native HPS/network evidence remains pending. |
| R10/S14-S15 | PC dashboard and versioned command path | Dashboard consumes generated packet constants; Step 15 adds dedicated waveform/error views, bounded frame-indexed spectrogram history, packet/loss state, persistent asynchronous live controls, visible results, and timestamp-preserving capture replay without reinterpreting v1. Live HPS/FPGA evidence remains pending. |
| R11 | LINE-IN bring-up | Step 16 source implements the 12.288 MHz audio PLL, WM8731 FPGA-I2C initialization, 48 kS/s/16-bit codec-master I2S, async-FIFO CDC, dedicated audio counters, and an explicit LINE-IN profile. Step 18 timing and Step 20 Quartus/hardware evidence still gate an operational claim. |
| R12 | ADC bring-up | Step 17 source implements the LTC2308 100 kS/s, 2.5 MHz serial path, synchronized DOUT, epoch-latched channel command, prime/discard rule, signed normalization, source accounting, and explicit ADC profile. Step 18 timing and Step 20 Quartus/analog/hardware evidence still gate an operational claim. |

## Core-first cut C0

C0 is the first implementation boundary.

Required for C0:

```text
rtl/include/
rtl/common/
rtl/interfaces/
rtl/sources/trecap_bram_replay_source.sv
rtl/core/
rtl/fft/
sw/reference_model/
artifacts/coefficients/
artifacts/test_vectors/
```

Excluded from C0:

```text
rtl/telemetry/
rtl/hps_bridge/
sw/hps/
sw/pc_dashboard/
platform/de1soc/
constraints/de1soc/
live audio
ADC
Ethernet
HPS runtime integration
```

C0 exit commands:

```bash
make gen-headers
make rtl-filelist
make coeffs
make compile-core
make golden
```

The current C0 control/counting regression is:

```bash
python3 scripts/sim/check_c0_flow_control_model.py
python3 scripts/sim/check_c0_active_tail_model.py
python3 scripts/sim/check_c0_exact_completion_model.py
python3 scripts/sim/check_c0_delay_history_model.py
```

Run `scripts/windows/run_c0_golden_v70.ps1` for the current native
ModelSim/Questa C0 suite. It first runs the dependency-free control/history
models, verifies that every invoked simulation top is present in the exact
compile-filelist closure, and checks the embedded frozen DAG plus architecture
v3 import chain.
It then runs the directed v70 history regression, the v65-v67
control/counting tests, and the v68 live RTL artifact comparisons against
`y_out.memh`, `frame_stats.csv`, `bin_stats.csv`, and `metrics.json`. The run
is accepted only after both integrity sentinels, the RTL sentinel, and the
independent byte-for-byte capture post-check pass.

The v70a packaging hotfix restored `sim/filelists/c0_v67_regression.f` to the
unified compile command and bound that filelist plus its three testbenches into
the artifact source snapshot.

v70b repairs the canonical magnitude-squared operator so both signed
`T_CAN_W` operands are evaluated into the full `2*T_CAN_W` product width before
spectral comparison or accumulation. The native suite now runs a dedicated
nonzero/extreme-value `C0_MAG2_WIDTH_PASS` regression before the exact artifact
scoreboard. See `docs/bringup/c0_mag2_width_fix_v70b.md`.

The v70 delay-history and atomic source-fork contract is documented in
`docs/bringup/c0_delay_history_fix_v70.md`.
The v69 integrity and runner delta is documented in
`docs/bringup/reference_import_hash_chain_v69.md`.
`docs/bringup/c0_artifact_scoreboard_v68.md` is retained as the historical
artifact-scoreboard contract and coverage record. The prior busy/done and
exact-completion boundary remains documented in
`docs/bringup/c0_exact_completion_v67.md`.

If the root Makefile keeps the spec-compatible target name `make golden`, document whether it currently means provisional reference artifacts or frozen golden artifacts.

## Transport cut T0

T0 begins only after C0 is stable. T0 adds telemetry packetizers, packet FIFO, HPS bridge, HPS software, PC dashboard, and DE1-SoC Platform Designer integration. T0 shall not alter the core arithmetic contract.

First full-demo scope after C0/T0:

```text
STATUS packets
WAVE packets
METRICS packets
one spectrum mode: SPEC64 or SPEC129
CSR map and shadow/commit path
DDR record builder and DDR ring writer
HPS UDP streamer
PC parser/dashboard
SET_THR2 command path
packet-enable command path
LINE-IN controlled demo wrapper
```

Deferred:

```text
PEAKS packet
DEBUG packet
CRC enablement
kernel DMA-coherent driver path
simultaneous SPEC64 and SPEC129 output
HPS/Linux audio path
PC-driven artifact signoff
verification repository architecture
```

## Generated contract flow

Manual duplication of constants is not allowed.

Source files:

```text
spec/generated/core_config.json
spec/generated/width_config.json
spec/generated/artifact_contract.json
spec/generated/csr_map.json
spec/generated/packet_layouts.json
spec/generated/interface_types.json
spec/generated/gen_manifest.json
```

Generated outputs:

```text
rtl/include/generated/trecap_core_pkg.sv
rtl/include/generated/trecap_csr_pkg.sv
rtl/include/generated/trecap_packet_pkg.sv
rtl/include/generated/trecap_iface_pkg.sv
sw/hps/include/generated/trecap_csr.h
sw/hps/include/generated/trecap_packet.h
sw/pc_dashboard/generated/trecap_packet.py
sw/reference_model/generated/trecap_config.py
```

Generated files shall contain this banner:

```text
AUTO-GENERATED - DO NOT EDIT
```

To change a generated file, edit the schema/source file and regenerate.

Required checks:

```bash
make gen-headers
make check-generated
make rtl-filelist
```

`make check-generated` shall fail if regenerated output differs from checked-in generated files.

## Filelists and compile order

Compile order is part of the implementation contract. Do not guess it manually.

```text
filelists/rtl_core.f              partial core skeleton smoke filelist
filelists/rtl_core_plus_fft.f     C0 core + FFT/IFFT filelist
filelists/rtl_telemetry.f         telemetry packetizer filelist
filelists/rtl_hps_bridge.f        CSR + record builder + DDR writer filelist
filelists/rtl_de1soc_full.f       full DE1-SoC integration filelist
filelists/quartus_de1soc.qsf.inc  Quartus file-assignment include
```

Packages compile before interfaces. Interfaces compile before modules. Core modules compile before integration tops.

## Reference model import policy

For a future complete, independently hash-pinned ZIP, use
`scripts/reference_import.py stage`; it validates the archive before
publishing a fresh tree. The current package contains only the explicit
unverified embedded proxy.

Copy/import:

```text
trecap-golden/include/      -> sw/reference_model/include/
trecap-golden/src/          -> sw/reference_model/src/
trecap-golden/tools/        -> sw/reference_model/tools/
trecap-golden/python/       -> sw/reference_model/python/
trecap-golden/configs/      -> sw/reference_model/configs/
trecap-golden/tests/        -> sw/reference_model/tests/
trecap-golden/docs/         -> sw/reference_model/docs/
trecap-golden/artifacts/coefficients/      -> artifacts/coefficients/
trecap-golden/artifacts/test_vectors/      -> artifacts/test_vectors/
trecap-golden/artifacts/golden/            -> artifacts/reference_outputs/
trecap-golden/artifacts/manifests/         -> artifacts/manifests/
trecap-golden/spec/generated/core_config.json       -> spec/generated/core_config.json
trecap-golden/spec/generated/width_config.json      -> spec/generated/width_config.json
trecap-golden/spec/generated/artifact_contract.json -> spec/generated/artifact_contract.json
```

Do not import:

```text
.venv/
.pytest_cache/
build/
out/
runs/
__pycache__/
*.pyc
```

Files with names containing `golden` may remain inside the imported reference package until the team performs a naming cleanup. Do not treat the name as proof that the package is final signoff authority.

## Legacy Phase 1 quarantine

The current root upload contains Phase 1 files. They are useful history, but they are not Phase 2 implementation sources.

Move these under `legacy/phase1/`:

```text
t_recap_demo_top.sv
golden_model.cpp
viz.py
run.py
tb_top.sv
tb_pkg.sv
board_if.sv
tap_if.sv
bind_taps.sv
board_driver.sv
ref_model_phase1.sv
golden_files_loader.sv
x_stream_monitor.sv
y_stream_monitor.sv
pair_monitor.sv
io_monitor.sv
metrics_monitor.sv
scoreboard_pairs.sv
scoreboard_y_stream.sv
scoreboard_metrics.sv
cov_phase1.sv
sva_phase1_bind.sv
test_base.sv
test_bypass_lossless.sv
test_golden_thresh16.sv
test_threshold_sweep.sv
test_clear_metrics_midrun.sv
test_mode_switch_stress.sv
x.memh
y.memh
sup.memh
metrics.json
T_RECAP_Phase1_Algorithm.pdf
Report-1.pdf
untitled-1.pdf
```

Phase 1 runner behavior is preserved only in `legacy/phase1/testbench/`. It shall not be reachable from Phase 2 root build targets.

## HPS/DDR/Ethernet transport contract

HPS software shall:

```text
1. configure Ethernet and UDP socket
2. map the FPGA CSR window
3. map the reserved DDR ring read-only with the supported synchronous/non-cacheable userspace policy; cached mappings are forbidden
4. disable telemetry and reset transport before ring configuration
5. configure ring base, ring size, packet enables, wave decimation, and spectrum shift
6. commit ring configuration and consumer pointer before enabling writer
7. snapshot producer pointer atomically
8. validate records before forwarding UDP
9. send exactly one telemetry record per UDP datagram
10. receive commands only on the configured HPS address/port, admit the lab peer
    by exact source IP and port, and translate accepted commands through
    the lifecycle/replay bridge into generated CSR writes and verified readback
```

`RING_BASE` is the FPGA-visible bus address for the DDR writer. It is not a Linux userspace virtual address.

The HPS streamer shall use nonblocking send or a bounded send timeout. If the PC is slow or disconnected, HPS shall drop/count UDP datagrams and continue advancing the consumer pointer.

## Packet/dashboard scope

First demo packet set:

```text
STATUS
WAVE
METRICS
SPEC64 or SPEC129
```

PC dashboard shall display:

```text
x[n - D]
y[n]
e[n] = x[n - D] - y[n]
spectrogram from SPEC64 or SPEC129
suppression ratio
kept-energy ratio
packet rate
dma_drop_count
packet_fifo_drop_count
sequence gaps
malformed/truncated state by distinct ownership domain
overflow flags
active THR2
source mode
live command controls and visible command results
```

The dashboard shall keep `dma_drop_count` and `packet_fifo_drop_count` separate.

## Build targets

These targets are the repository contract. A target may be a stub only during early R0/R1, but it shall not silently claim success for work that has not been implemented.

```bash
make check-layout          # verify required folders and legacy quarantine
make gen-headers           # generate SV/C/Python headers from spec/generated
make check-generated       # deterministic regeneration check
make check-de1soc-board-top # Step-9 physical board-top source contract
make check-de1soc-clock-reset # Step-10 clock/reset source contract
make check-hps-transport   # Step-13 HPS transport source contract
make check-command-path    # Step-14 versioned command/result source contract
make rtl-filelist          # generate compile/synthesis filelists
make lint-basic            # syntax/style hygiene only
make compile-core          # C0 core compile using filelists/rtl_core_plus_fft.f
make compile-telemetry     # telemetry packetizers and packet FIFO only
make compile-core-telemetry # standalone normalized-source core + telemetry composition
make compile-hps-bridge    # CSR bank, pointer control, record builder, DDR writer
make coeffs                # generate coefficient memh files and manifest
make vectors               # generate/validate frozen input vectors
make golden                # run reference model and emit expected artifacts
make check-reference-import # verify all embedded/promoted bytes and v3 provenance
make check-artifacts       # check memh rows, hashes, CSV rows, JSON schemas
make quartus-core-smoke    # reduced core-only Quartus build if available
make quartus-de1soc        # full DE1-SoC Quartus build
make hps-build             # build HPS UDP streamer
make hps-step13-test       # RAM-backed HPS transport test with ASan/UBSan
make step13-source         # simulator-independent cumulative Step-13 gate
make hps-step14-test       # HPS command-path host test
make dashboard-step14-test # dependency-free PC command-client host test
make step14-source         # cumulative source-only Step-14 gate
make dashboard-step15-test # dependency-free PC dashboard source/host test
make step15-source         # cumulative source-only Step-15 gate
make dashboard-import      # import Python parser/dashboard and generated constants
make clean-runs            # remove local run outputs
```

Compatibility alias:

```bash
make golden                # allowed only as an alias; document current authority status
```

## Minimum acceptance criteria

The implementation repository is acceptable when:

```text
1. rtl/core/ builds independently from HPS, DDR, Ethernet, dashboard, and board wrappers.
2. trecap_ddr_ring_writer.sv exists only under rtl/hps_bridge/.
3. spec/generated/ contains core_config.json, csr_map.json, packet_layouts.json, and interface_types.json.
4. scripts/gen_headers.py generates SystemVerilog, C, and Python outputs from the same schemas.
5. CSR offsets and packet payload sizes are not duplicated manually across RTL, HPS C, and Python.
6. filelists/ contains generated build-order filelists and active builds consume them.
7. generated headers are checked in and make check-generated detects drift.
8. platform/de1soc/ contains Platform Designer/Qsys ownership files and address-map notes.
9. sw/hps/config/trecap_hps_config.json documents CSR base, ring addresses, ring size, and UDP ports.
10. legacy/phase1/ contains old Haar proof-of-concept files and those files are not part of the root build.
11. window_rom.sv and twiddle_rom.sv consume frozen coefficient artifacts.
12. core modules do not instantiate board-specific memory IP directly.
13. top-level build variants exist for core-only, BRAM replay, core+telemetry, and full DE1-SoC builds.
14. C0 tops instantiate no telemetry, HPS bridge, board audio/ADC capture, or Platform Designer path; shared source-adapter files may still be syntax-compiled by generated core filelists.
15. trecap_source_core_integration.sv owns normalized source selection, guarded source epochs, exact BRAM tail routing, and the real core tap/status boundary.
16. de1_soc_trecap_top.sv is the physical Quartus top; trecap_de1soc_full_top.sv remains the pin-agnostic telemetry/HPS/DDR logical top.
17. trecap_core_telemetry_top.sv owns exactly one real core and one telemetry top; the DE1-SoC hierarchy reuses its existing source-owned core and does not instantiate this standalone composition.
18. telemetry record ready/backpressure terminates in the telemetry scheduler/FIFO path and never drives a source, core, frame, FFT/IFFT, WOLA, or mathematical-output ready path.
19. de1_soc_trecap_top.sv contains no synthetic taps or safe-idle CSR/DDR substitutes; its real core-y monitor remains best-effort and cannot backpressure the mathematical core.
20. adc_wrapper.sv implements the 100 kS/s LTC2308 CONVST/wait/2.5-MHz 12-bit-read/six-bit-next-config pipeline, consumes a two-flop-synchronized DOUT value, saturates its published sample count, and primes after enable or configuration changes before asserting sample valid.
21. command protocol version 1 remains exactly seven commands in one 28-byte request and defines no generic result; version 2 is an explicit extension.
22. every version-2 non-PING command uses RFC1982 sequence/cache handling and an exact 32-byte result, while PING remains fresh diagnostic STATUS only with no ledger effect.
23. the canonical HPS command listener binds `192.168.10.2:5006` and accepts the configured production peer only from `192.168.10.1:5007`; wildcard binding is an explicit lab/test override.
24. ring addresses never arrive over the command network, and transport enable requires verified RESET-to-CONFIGURE-to-ENABLE lifecycle completion.
25. the dashboard keeps waveform and error views separate from the latest spectrum and bounded frame-indexed spectrogram history.
26. packet rate, sequence gaps, HPS malformed state, PC parser/truncation state, `dma_drop_count`, and `packet_fifo_drop_count` remain separately attributable.
27. live dashboard controls use one persistent asynchronous serialized command session and expose command results without blocking UDP receive or GUI refresh.
28. capture replay uses recorded receive timestamps, and capture append validates and extends one framed stream.
```

## Development notes for new contributors

Start here:

```bash
make check-layout
make gen-headers
make check-generated
make rtl-filelist
make coeffs
make vectors
make compile-core
```

Do not start with:

```text
Ethernet dashboard
live audio
Platform Designer full integration
PC plots
HPS UDP streamer
```

Those are transport/demo layers. They come after the core-only C0 path is buildable and artifact-driven.

## License

Keep the license inherited from the imported reference package where applicable. Board-specific, RTL, and project-authored files should use the project license selected by the team before public release.
