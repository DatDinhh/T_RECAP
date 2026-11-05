# T-RECAP system architecture atlas

**Threshold-based Reduction and Encoding for Controlled Audio Processing**

This is the primary whole-project architecture after recorded RF integration. Eight coordinated views connect audio and accelerometer replay, the new I/Q hardware adapter, the shared numerical core, HPS transport and laptop consumers.

[Open the offline gallery](index.html) | [Read the academic LaTeX atlas](TRECAP_System_Architecture_Atlas.pdf)

TSH2 and TRF1 are alternative fitted applications. Their shared core is one implementation reused by both profiles. The diagrams do not imply a runtime input selector or simultaneous processing of all signal types.

The colors identify responsibilities consistently. Sage denotes signal input, blue denotes storage or platform interfaces, lilac denotes DSP, peach denotes returned signal representations, and warm cream denotes host software or transaction control.

## Eight views

| View | What it explains |
|---|---|
| [1. One project, adapted inputs, one numerical core](01-system-overview.png) | The diagram combines application routes while preserving the boundary between the TSH2 and TRF1 fitted images. |
| [2. Input contracts and application boundaries](02-input-profiles.png) | Physical units and signal sample rates remain metadata even though all core input samples use the same signed 12-bit representation. |
| [3. The common spectral-processing datapath](03-shared-dsp.png) | RF is adapted before this chain. FFT size, hop, threshold rule and reconstruction arithmetic are preserved. |
| [4. The new I/Q block inside the full architecture](04-rf-input-adapter.png) | One shared multiply-accumulate datapath schedules the four interpolation phases before the existing real-sample core. |
| [5. Two outputs and the work performed on the laptop](05-outputs-and-consumers.png) | The waveform path preserves a time-domain result. The spectral path supports consumers that understand sparse power records. |
| [6. Host transport and finite-transaction ownership](06-host-and-transactions.png) | Both applications use HPS MMIO feed and drain, while the outer file-transfer protocols remain distinct. |
| [7. Control, buffering and recovery across the system](07-control-and-backpressure.png) | Transport can pause progress. Accepted samples, reconstruction history and frame identity must remain consistent. |
| [8. Platform and verification boundaries](08-platform-and-verification.png) | The combined architecture is documented at system level. Evidence remains attached to the profile and source that produced it. |

## 1. One project, adapted inputs, one numerical core

![One project, adapted inputs, one numerical core](01-system-overview.png)

T-RECAP moves a finite signal record into the FPGA, applies a common fixed-point spectral-processing chain, and returns two representations to the laptop. The RF extension changes the input conversion and application interface. It does not replace the FFT, threshold, IFFT or reconstruction arithmetic.

Audio and accelerometer records are real-valued signals. Host software prepares their sample representation before replay through TSH2. Recorded RF is complex baseband I/Q. TRF1 transports its raw CU8 pairs to a new hardware adapter that produces the real signed 12-bit stream expected by the same numerical core.

TSH2 and TRF1 are separate fitted FPGA images. The lines converge to show shared implementation and numerical behavior, not an implemented runtime multiplexer. A host must identify and admit the loaded profile before using its registers.

| Block | Responsibility |
|---|---|
| Audio and motion records | Audio files or a captured sensor axis. Real-valued samples with a known rate. |
| Laptop preparation | Decode or map the input to signed 12-bit. Keep sample-rate and scaling metadata. |
| HPS + TSH2 entry | Upload the finite PCM record. MMIO FIFO feeds the existing source. |
| Recorded RF I/Q | Receiver has already downconverted RF. File stores alternating unsigned I and Q. |
| Laptop + HPS file transport | Upload unchanged CU8 bytes. TRF1 client feeds the raw-pair FIFO. |
| New FPGA RF adapter | Center, FIR interpolate, mix to real IF. Round and saturate to signed 12-bit. |
| Laptop applications | Listen and compare reconstructed audio. Inspect spectra and run sparse consumers. |
| Two returned representations | Y contains reconstructed time samples. TSP1 contains spectral power records. |
| Shared FPGA DSP core | FFT, tunable threshold, IFFT and WOLA. Same numerical core in each profile. |

**Interpretation:** The two routes describe alternative fitted applications. They do not run simultaneously on the board and there is no runtime audio/RF selector. Accelerometer replay uses the real-sample route.

Source bindings: C01, A01, A02, A03, R01, R04, R05.

[Editable SVG](01-system-overview.svg) | [Vector PDF](01-system-overview.pdf)

## 2. Input contracts and application boundaries

![Input contracts and application boundaries](02-input-profiles.png)

A common integer interface does not make audio, acceleration and radio signals interchangeable. The sample rate, scaling and original units are needed to label time, frequency and physical amplitude correctly. An eight-second audio label must not be reused for a shorter RF record simply because the buffer length is the same.

The local accelerometer workflow reads the onboard ADXL345 through HPS I2C, records a bounded sample set, selects one axis on the laptop and pads it for TSH2 replay. Its native-rate axis adapter does not resample or remove DC. These acquisition scripts remain a local extension and are identified in the review record rather than presented as a published live FPGA interface.

TRF1 instead accepts one to 96,000 raw I/Q pairs. It generates exactly four valid real samples per pair, then supplies zeros to the 384,000-sample core transaction. The raw RF center frequency is already downconverted by the receiver that produced the file.

| Block | Responsibility |
|---|---|
| Audio record | PCM waveform from a file or prior recording. Host conversion produces admitted samples. |
| Accelerometer record | Local workflow captures ADXL345 through HPS. One selected X, Y or Z axis is replayed. |
| RF receiver recording | Complex CU8 baseband pairs. Sample rate and RF center frequency supplied. |
| Audio preparation | Decode and scale into the signed 12-bit range. Finite record is prepared on the laptop. |
| Axis preparation on laptop | Preserve native-rate signed sensor counts. Pad one axis to the finite core transaction. |
| TRF1 hardware preparation | 4x interpolating FIR and real-IF mixer. Gain, rounding, saturation and padding. |
| TSH2 real-sample application | Input word carries one signed sample. Audio and axis records share this interface. |
| TRF1 raw-I/Q application | Input word carries two unsigned bytes. RF conversion occurs in FPGA fabric. |

**Interpretation:** The accelerometer application is a capture-and-replay workflow without a new FPGA sensor frontend. The RF profile adds an actual I/Q hardware adapter. Neither route establishes continuous live acquisition.

Source bindings: A01, A02, R01, R02, R04.

[Editable SVG](02-input-profiles.svg) | [Vector PDF](02-input-profiles.pdf)

## 3. The common spectral-processing datapath

![The common spectral-processing datapath](03-shared-dsp.png)

The core groups accepted samples into overlapping 256-point frames at a hop of 128. A fixed analysis window precedes the forward FFT. The frame scheduler, ring buffer and output flow control preserve overlap state when transport stalls.

After Hermitian canonicalization, the power comparison produces a conjugate-pair mask. Eligible powers below THR2 are suppressed, equality is retained, and DC is protected. The same thresholded spectrum supplies both reconstruction and spectral export. Threshold values are implementation power units rather than percentages or decibels.

The IFFT and synthesis weighted overlap-add stage return Y. A separate exporter captures 129 canonical power bins per frame for TSP1. The RF profile uses byte-identical shared FFT, IFFT, magnitude-mask, synthesis and top-level numerical core sources.

| Block | Responsibility |
|---|---|
| Finite real-sample source | Indexed signed 12-bit sample tokens. Real input followed by analysis zeros. |
| Input ring and analysis window | 256-sample frames with a 128-sample hop. Multiply by fixed window coefficients. |
| 256-point FFT | 28-bit complex components. Eight radix-2 stages with per-stage scaling. |
| 256-point IFFT | 36-bit complex components. Inverse twiddles reconstruct each frame. |
| Paired spectral mask | Power = Re squared + Im squared. Suppress eligible bins below THR2. |
| Hermitian canonicalization | One consistent decision for each pair. Real DC and Nyquist components. |
| Synthesis and overlap-add | Window and accumulate overlapping frames. Emit 128 mature samples per hop. |
| Reconstructed samples Y | Signed 12-bit output with sample index. Full finite tail retained for comparison. |
| Spectral exporter branch | 129 canonical-bin rows per frame. Powers and retained-bin identities. |

**Interpretation:** THR2 is an unsigned 56-bit threshold in fixed-point squared-magnitude units. Equality is retained and DC is protected. Removing bins trades signal information for a smaller sparse spectral representation.

Source bindings: C01, C02, C03, C04, C05, C06, C07, C08.

[Editable SVG](03-shared-dsp.svg) | [Vector PDF](03-shared-dsp.pdf)

## 4. The new I/Q block inside the full architecture

![The new I/Q block inside the full architecture](04-rf-input-adapter.png)

CU8 contains unsigned I and Q bytes, not amplitude and phase values stored independently. Centering maps each byte to an odd signed integer with the expression 2*b - 255. Exact zero flush samples are inserted after centering because neither unsigned byte 127 nor byte 128 represents exact zero under this convention.

The 81-tap FIR is decomposed into four phases. The schedule uses one multiplier with 21 tap positions per phase and a signed 36-bit accumulator. Even phases read I history and odd phases read Q history. The quarter-rate real-IF sign sequence is applied at successive interpolated times, not as four copies of a raw input pair.

After gain, rounding and saturation, the finite-record wrapper discards startup delay, flushes the FIR and emits exactly 4*N real samples. It then pads the common transaction. The clip count and valid-prefix count remain available to the host so that interpolation, clipping and padding are not mistaken for threshold effects.

| Block | Responsibility |
|---|---|
| Raw pair FIFO | Low byte I, next byte Q. Upper 16 input-word bits must be zero. |
| Center and retain I/Q history | Each byte becomes 2*b - 255. 21 signed 9-bit samples in each history. |
| Polyphase FIR hardware | 81 signed 18-bit coefficients. One multiplier and 36-bit accumulator. |
| Gain and output quantization | Round half ties away from zero. Saturate to signed 12-bit and count clips. |
| Quarter-rate real-IF mixer | Successive phases select +I, -Q, -I, +Q. Sign selection avoids a general oscillator. |
| Phase and tap schedule | Four phases, 21 MAC clocks per phase. Unused coefficient positions contribute zero. |
| Finite-record alignment | Discard 40 startup outputs. Flush ten exact zero pairs internally. |
| Valid prefix and core padding | Emit exactly 4*N valid real samples. Pad the transaction to 384,000 samples. |
| Existing DSP core | FFT to threshold to IFFT/WOLA. Y and TSP1 output paths are unchanged. |

**Interpretation:** At a 250 ksample/s complex input rate, the equivalent real stream is 1 Msample/s and centered at 250 kHz. The sequential converter takes multiple fabric clocks for each sample and can stall.

Source bindings: R01, R02, R03, R04, C07.

[Editable SVG](04-rf-input-adapter.svg) | [Vector PDF](04-rf-input-adapter.pdf)

## 5. Two outputs and the work performed on the laptop

![Two outputs and the work performed on the laptop](05-outputs-and-consumers.png)

Y and TSP1 serve different purposes. Y is a reconstructed sample stream that can be turned into a playable waveform for audio or analyzed as a real-valued signal for other applications. TSP1 is a versioned spectral-power representation with bin identities in sparse mode. It does not contain the complex phase required for waveform reconstruction.

For a fair consumer benchmark, dense and sparse records must represent the same thresholded powers. Their feature outputs are compared for equality. A separate comparison against the original signal measures the information lost to thresholding. This separates representation efficiency from signal distortion.

The laptop also performs plotting, playback, packet validation and optional application logic. Archived visualizer code separates a new physical capture from a saved-result load. RF protocol decoding after real-IF recovery remains a host operation. Dense AI consumers do not automatically execute fewer operations when more input bins are zero.

| Block | Responsibility |
|---|---|
| Y from IFFT/WOLA | Reconstructed signed 12-bit samples. Index, finite tail and comparison context. |
| Waveform FIFO + HPS return | 1,024 words with sign-extended values. Host drains the complete sample stream. |
| Waveform applications | Audio playback and distortion measures. Acceleration traces or real-IF analysis. |
| Canonical spectral powers | 129 bins and frame identities. Power has no retained complex phase. |
| TSP1 records + HPS return | Dense powers or sparse bin/power entries. Header, checksum and word-aligned transport. |
| Spectral consumers | Band energies, monitoring and plots. Sparse-aware loops visit retained entries. |
| Signal-quality comparison | Original versus thresholded reconstruction. Quantization and threshold error separated. |
| Representation comparison | Dense and sparse at the same threshold. Equal features isolate encoding workload. |
| Application-dependent benefit | Smaller TSP1 can reduce compatible host work. A dense AI input may retain the same workload. |

**Interpretation:** TSP1 byte reduction is measured against dense TSP1, not WAV or raw I/Q file size. A faster sparse consumer is not a faster FPGA FFT. TSP1 alone cannot reconstruct the waveform because it omits phase.

Source bindings: A03, A04, A01, R04, R05, C01.

[Editable SVG](05-outputs-and-consumers.svg) | [Vector PDF](05-outputs-and-consumers.pdf)

## 6. Host transport and finite-transaction ownership

![Host transport and finite-transaction ownership](06-host-and-transactions.png)

The outer transports are not identical. TSH2 exposes a finite TCP request and reply around resident HPS buffers. The RF workflow uploads a bounded archive into HPS RAM, executes a local TRF1 client and downloads a bounded result archive. Neither should be described as a continuous packet-stream radio receiver.

Both clients must identify the loaded application and respect its register contract before issuing input. The HPS interleaves bounded input writes with output reads so that limited FPGA queues do not deadlock the transaction. TRF1 uses a 256-pair raw-input FIFO and registered prefetch rather than treating the FIFO pop as an immediate data response.

The standard core transaction consumes 384,000 real samples. The source additionally owns the analysis-zero tokens and WOLA tail needed for 3,001 frames and 384,512 returned samples. FPGA completion records produced totals. Host retrieval is complete only after any remaining queued output has been drained and checked.

| Block | Responsibility |
|---|---|
| Laptop prepares a request | Audio uses the TSH2 TCP service. RF uses bounded file-archive transfer. |
| HPS admission and buffers | Verify profile, ABI and source identity. Validate file length and sample contract. |
| Idle configuration + START | Set THR2 and packet mode. TRF1 also sets pair count and gain. |
| Input FIFO and source | TSH2 accepts signed PCM words. TRF1 accepts raw CU8 pairs then converts. |
| HPS feed and drain loop | Write only available input capacity. Interleave reads of Y and spectral words. |
| FPGA finite processing epoch | 384,000 core input samples. 3,001 frames and 384,512 full-tail Y samples. |
| Laptop validation and analysis | Check returned counts and packet integrity. Compare signal quality and consumer work. |
| Drain and return complete results | Finish retrieving queued Y and TSP1. TCP reply or result archive returns to laptop. |
| DONE and exact production counts | Core and exporter finish the epoch. Queued output may still need host reads. |

**Interpretation:** The application keeps one configured geometry for admission and completion checks. Only the valid input interval should determine the physical time axis and headline RF data-reduction denominator.

Source bindings: A01, A02, R04, R05, R07, R08, C07, C08.

[Editable SVG](06-host-and-transactions.svg) | [Vector PDF](06-host-and-transactions.pdf)

## 7. Control, buffering and recovery across the system

![Control, buffering and recovery across the system](07-control-and-backpressure.png)

Ready/valid ownership is local and precise. A producer presenting a valid sample retains its value and sidebands while the consumer is not ready. An input FIFO pop may also have registered latency. TRF1 therefore tracks a pending read and a held prefetched pair explicitly.

The waveform output directly uses backpressure. Spectral observation taps are valid-only, so the surrounding source and exporter enforce next-hop credit to prevent an unbounded accumulation of frames. The HPS must drain both output types because either path can limit progress.

Clear and reset are transaction events, not benign changes to a threshold. They withdraw current output ownership and clear the enclosing pipeline. The RF verification includes reset while a FIFO response is pending, clear while a prefetched pair is held, watchdog recovery and restart checks.

| Block | Responsibility |
|---|---|
| Configuration is admitted while idle | THR2 and packet mode remain fixed per epoch. TRF1 latches pair count and gain. |
| Source ownership and prefetch | Advance only on accepted handshakes. TRF1 holds a registered raw pair until used. |
| Shared core state | Sample index, overlap and WOLA history. A stall must not restart the signal. |
| HPS releases queue occupancy | Drain both output FIFOs regularly. Feed input only when capacity is available. |
| Spectral credit and FIFO | Frame capture and packing have finite capacity. Completed record releases next-hop credit. |
| Waveform FIFO backpressure | A full FIFO deasserts downstream ready. Y and its index stay stable until accepted. |
| Fault detection | Invalid words, counts and configuration. Watchdog and exporter/core faults. |
| CLEAR or reset aborts ownership | Cancel pending prefetch and held samples. Reset counts and clear the enclosing core. |
| Re-admit and restart cleanly | New transaction receives its own epoch. Verify counts and faults before completion. |

**Interpretation:** Y has a ready/valid path. Spectral taps are valid-only, so upstream frame credit protects the exporter instead. Treating every internal link as an interchangeable streaming interface would hide this distinction.

Source bindings: A01, R01, R02, R04, R07, C07, V01.

[Editable SVG](07-control-and-backpressure.svg) | [Vector PDF](07-control-and-backpressure.pdf)

## 8. Platform and verification boundaries

![Platform and verification boundaries](08-platform-and-verification.png)

The finite processing fabric uses the nominal 50 MHz board clock. HPS-owned clocks, DDR calibration, Ethernet and generated platform IP have their own implementation requirements. Board rebuilds require the matching generated system, pin and timing assignments, handoff files and boot assets in addition to the published non-vendor simulation closure.

Source and interface identity prevent an audio client from accidentally using an RF register map. Physical timing and capture evidence refer to a particular fitted image. Fresh RTL simulation refers to the source and test package it actually executed. A documentation refresh is not a new board measurement.

The preserved TSH2 UVM and formal results retain their documented scope. The RF addition has its own independent numerical reference and five fresh self-checking suites, including 32 actual-core integration epochs. Its historical five-epoch physical qualification is reported separately. The unified diagram does not imply continuous acquisition or full-platform signoff.

| Block | Responsibility |
|---|---|
| DE1-SoC fabric clock | Nominal constrained CLOCK_50 domain. Sources, DSP, exporter and synchronous FIFOs. |
| Reset and finite initialization | HPS reset asserts asynchronously. Synchronized release and explicit core clear. |
| HPS platform remains external | CPU, Ethernet and DDR clocks are platform-owned. Generated IP, handoff and boot assets required. |
| Profile and build identity | TSH2 and TRF1 have distinct register magic. ABI, SOURCE_ID and geometry admit each run. |
| Existing TSH2 evidence | Procedural RTL and physical campaigns. Scoped UVM and local formal supplement. |
| New RF evidence | Independent conversion model and RTL tests. Actual-core MMIO, stalls and recovery checks. |
| Historical physical RF capture | Source-bound fitted image and five epochs. Exact Y and TSP1 comparison to references. |
| Fresh RF publication regression | Five self-checking suites with actual VCDs. 32 actual-core integration epochs. |
| Evidence must keep its scope | No new RF formal proof or RF UVM claim. No live-rate or electrical-power claim. |

**Interpretation:** These are source-derived architecture views with reproducible figures and written descriptions. Drawing the complete system does not rerun synthesis, program hardware or extend an existing proof beyond its checked modules.

Source bindings: R06, A01, R04, V01, V02.

[Editable SVG](08-platform-and-verification.svg) | [Vector PDF](08-platform-and-verification.pdf)

## Source review and reproduction

The source bindings below hash the public files used to review these views. The generator checks these identities and the artifact inventory. It does not execute RTL, access a board or rerun a hardware benchmark.

| ID | Published source |
|---|---|
| C01 | [rtl/core/trecap_core_top.sv](../../../rtl/core/trecap_core_top.sv) |
| C02 | [rtl/include/generated/trecap_core_pkg.sv](../../../rtl/include/generated/trecap_core_pkg.sv) |
| C03 | [rtl/fft/trecap_fft256.sv](../../../rtl/fft/trecap_fft256.sv) |
| C04 | [rtl/fft/trecap_ifft256.sv](../../../rtl/fft/trecap_ifft256.sv) |
| C05 | [rtl/core/trecap_mag2_mask.sv](../../../rtl/core/trecap_mag2_mask.sv) |
| C06 | [rtl/core/trecap_synthesis_wola.sv](../../../rtl/core/trecap_synthesis_wola.sv) |
| C07 | [verification/tsh2/rtl/trecap_pcm_stream_top.sv](../../../verification/tsh2/rtl/trecap_pcm_stream_top.sv) |
| C08 | [verification/tsh2/rtl/trecap_pcm_stream_source.sv](../../../verification/tsh2/rtl/trecap_pcm_stream_source.sv) |
| A01 | [profiles/tsh2/work/trecap_stream8_v01/rtl/trecap_stream_adapter.sv](../../../profiles/tsh2/work/trecap_stream8_v01/rtl/trecap_stream_adapter.sv) |
| A02 | [profiles/tsh2/work/trecap_laptop_fpga_v01/service/service.c](../../../profiles/tsh2/work/trecap_laptop_fpga_v01/service/service.c) |
| A03 | [profiles/tsh2/work/trecap_visualizer_v01/server.py](../../../profiles/tsh2/work/trecap_visualizer_v01/server.py) |
| A04 | [profiles/tsh2/work/trecap_visualizer_v01/data.py](../../../profiles/tsh2/work/trecap_visualizer_v01/data.py) |
| R01 | [profiles/trf1/adapter/rtl/trecap_rf_iq_adapter.sv](../../../profiles/trf1/adapter/rtl/trecap_rf_iq_adapter.sv) |
| R02 | [profiles/trf1/adapter/rtl/trecap_rf_file_source.sv](../../../profiles/trf1/adapter/rtl/trecap_rf_file_source.sv) |
| R03 | [profiles/trf1/adapter/coefficients/rf_coefficients.svh](../../../profiles/trf1/adapter/coefficients/rf_coefficients.svh) |
| R04 | [profiles/trf1/board/rtl/trecap_rf_board_adapter.sv](../../../profiles/trf1/board/rtl/trecap_rf_board_adapter.sv) |
| R05 | [profiles/trf1/board/host/trf1_client.c](../../../profiles/trf1/board/host/trf1_client.c) |
| R06 | [profiles/trf1/board/platform/trecap_hps_top.sv](../../../profiles/trf1/board/platform/trecap_hps_top.sv) |
| R07 | [profiles/trf1/board/rtl/stream_fifo.sv](../../../profiles/trf1/board/rtl/stream_fifo.sv) |
| R08 | [profiles/trf1/board/orchestration/capture.py](../../../profiles/trf1/board/orchestration/capture.py) |
| V01 | [verification/rf_iq/evidence/summary.json](../../../verification/rf_iq/evidence/summary.json) |
| V02 | [verification/tsh2/admission.json](../../../verification/tsh2/admission.json) |

The accelerometer acquisition and axis-replay workflow was reviewed from local scripts. Their relative workspace identifiers and digests are preserved in `atlas_definitions.json`. These files are not bundled here, so the public checker does not claim to re-execute or revalidate that local acquisition workflow.

From the repository root:

```sh
python phase2/docs/architecture/system/build_atlas.py --check
```

To regenerate, install Matplotlib and Pillow, run the same script without `--check`, and compile `TRECAP_System_Architecture_Atlas.tex` twice with `pdflatex` from this directory. Review the rendered figures and pages, update `visual_review.json`, then run the generator with `--seal`. Rendering does not change source RTL or verification evidence.

The [audio atlas](../tsh2/README.md) and [RF specialist atlas](../rf_iq/README.md) retain their original detailed scopes. The [RF verification supplement](../../verification/rf_iq/README.md) contains the executed results behind the RF evidence summary.
