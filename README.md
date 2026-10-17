# T-RECAP

**FPGA spectral sparsification, audio reconstruction, and measured host workload reduction on DE1-SoC.**

[![Source and host checks](https://github.com/DatDinhh/T_RECAP/actions/workflows/phase2-source.yml/badge.svg)](https://github.com/DatDinhh/T_RECAP/actions/workflows/phase2-source.yml)

[Verification report](phase2/docs/verification/portfolio/TRECAP_DV_Portfolio.pdf) | [Runnable RTL verification](phase2/verification/tsh2/README.md) | [Results and provenance](phase2/docs/project_overview/README.md) | [Recorded web demo](https://github.com/DatDinhh/trecap-spectral-studio)

T-RECAP is a senior capstone project built around a fixed-point **FFT → tunable threshold → IFFT/WOLA** pipeline. The FPGA produces both a reconstructed audio waveform and a sparse representation of its spectrum. A laptop can inspect the audio, visualize spectral changes, and compute monitoring features from the retained spectral bins.

## Objective

**Reduce the spectral data a host must receive and process, while measuring the signal information lost at each threshold.** The practical application is a spectral-activity monitor: track dominant frequency, spectral centroid, band energy, and changes in activity from compact spectral records. The reconstruction path lets us hear and measure what the threshold removed.

This asks a specific engineering question: can a consumer that understands sparse spectra do less work while retaining the information its task needs? We compare dense and sparse representations at the **same threshold**, check their feature outputs for equality, and separately compare thresholded results with the original signal.

The current verified implementation processes finite audio files on a real DE1-SoC. Live microphone input and continuous real-time transport have not been qualified. The name expands to *Transform-domain Representation and Energy-aware Computation Accelerator with Controlled Precision*; electrical energy savings have not been established.

## What the project demonstrates

| Capability | Evidence |
|---|---|
| Process complete audio files through physical FPGA hardware | 58 checked runs across 13 inputs, including two repeats of every configuration |
| Preserve the intended fixed-point algorithm | All 22,301,696 returned waveform samples and 107,200,224 spectral packet bytes matched their threshold-specific reference |
| Trade spectral data volume for waveform fidelity | On the eight-second flute excerpt, threshold `10^8` reduced spectral packet bytes by **81.69%**, with **1.76% waveform NRMSE** |
| Reduce work in a compatible laptop consumer | At `10^8`, strict packet validation plus 16-band features used **77.21% less elapsed time** in paired warm-RAM replay of actual FPGA output |
| Check application-specific quality | A separate spectral monitor retained its registered quality gates on four held-out natural recordings at `10^7` |
| Provide reviewable design verification | Independent arithmetic checks, directed and seeded RTL tests, scoreboards, negative controls, observed coverage, native waveforms, physical receipts, and an academic LaTeX report |

These are different measurement boundaries. A smaller spectral packet is not a smaller WAV file, a faster sparse consumer is not a faster FPGA FFT, and exact reference agreement does not mean the threshold preserved the original audio.

## Current architecture

![Current finite-file TSH2 architecture](phase2/docs/project_overview/figures/current_architecture.png)

1. **Laptop:** prepare signed 12-bit PCM samples and choose `THR2` for the run.
2. **ARM HPS on the board:** receive the complete file over TCP into Linux RAM, then interleave MMIO input writes with waveform and spectral FIFO reads.
3. **FPGA:** window overlapping frames, calculate the FFT, canonicalize the real-signal spectrum, suppress eligible bins below the power threshold, and reconstruct the waveform using IFFT and weighted overlap-add.
4. **FPGA spectral exporter:** emit retained powers and bin indices as sparse TSP1 records. The HPS returns these records and the separate reconstructed waveform to the laptop.
5. **Laptop consumer:** validate records, compute features or monitor activity, and display the results. Reference checking evaluates implementation correctness and signal distortion separately.

The **waveform output contains reconstructed samples**. The **TSP1 output contains squared magnitudes without phase**, so it cannot reconstruct audio by itself. The finite TCP service returns sparse records; the lower-level adapter also supports dense records for verification.

The current profile is named **TSH2**. It uses ready/valid waveform flow control and spectral-record credit to preserve state while the host feeds and drains data. Its elapsed FPGA counter includes host-induced stalls. The earlier DDR-ring/UDP architecture is retained as [historical design material](phase2/docs/architecture/diagrams/README.md), with separate implementation and acceptance status.

| Parameter | Current verified profile |
|---|---|
| Platform | Terasic DE1-SoC, Cyclone V, 50 MHz fabric clock |
| Input | Signed 12-bit PCM, represented in sign-extended 32-bit transport words |
| FFT / hop | 256 samples / 128 samples |
| Fixed-point fractional precision | 15 bits |
| Spectral representation | 129 canonical bins, unsigned 56-bit squared magnitudes |
| Eight-second run | 384,000 input samples at nominal 48 kHz; 3,001 frames; 384,512 full-tail output samples |
| Reconstruction delay | 384 samples, equivalent to 8 ms at 48 kHz; this is not network latency |
| Packet size | Dense: 952 bytes/frame; sparse: `48 + 8K` bytes/frame for `K` retained bins |
| Fitted profile resources | 6,521 ALMs, 47 M10K blocks, 35 DSP blocks; source-bound historical fit/timing evidence |

`THR2` is a power threshold on `Re(X)^2 + Im(X)^2`, not a percentage or a calibrated sound level. An eligible bin is suppressed when its power is **strictly less** than the threshold. Equality is retained, DC is protected, and Nyquist is eligible. Thresholds are configured while idle and remain fixed throughout a run. Increasing the threshold does not shorten the baseline FFT/IFFT schedule.

## What happens to an audio file?

The following plots use the actual reconstructed waveform captured from the board. They show an eight-second flute excerpt credited to the University of Iowa Musical Instrument Samples collection. Output is aligned by the known 384-sample delay before comparison. The full output tail is still checked during verification.

![Original and FPGA-processed flute spectrograms](phase2/docs/project_overview/figures/flute_captured_spectrograms.png)

The spectrograms use one shared scale. Threshold zero reproduces this prepared input exactly after alignment. Increasing the threshold removes weak spectral components; at high thresholds the audible waveform changes substantially. This is selective suppression, not a general-purpose denoising guarantee.

![Captured waveform before and after thresholding](phase2/docs/project_overview/figures/flute_waveform.png)

| `THR2` | Waveform NRMSE vs input | Sparse spectral bytes | Reduction vs dense spectral format |
|---:|---:|---:|---:|
| `0` | 0.00% | 3,241,080 | **13.45% larger** |
| `10^8` | 1.76% | 523,200 | 81.69% smaller |
| `10^9` | 3.80% | 410,192 | 85.64% smaller |
| `10^10` | 9.62% | 318,360 | 88.86% smaller |
| `10^11` | 27.19% | 237,232 | 91.70% smaller |

The dense baseline is **2,856,952 bytes** for the same 3,001 spectral frames. Sparse encoding adds an index to every retained bin, so it loses at threshold zero when all bins remain. These counts include TSP1 headers and padding but exclude the separately returned waveform and TCP/IP framing. They do not measure WAV compression or total network traffic reduction.

![Waveform distortion and exact reference agreement](phase2/docs/project_overview/figures/flute_error_agreement.png)

NRMSE is `100 × ||aligned_output - input||₂ / ||input||₂`. It measures total waveform error, not perceived quality. Every thresholded FPGA output matched its corresponding numerical reference exactly, even when it differed considerably from the input. A low aggregate error can also hide large relative losses in weak frequency bands.

![Spectral packet size by threshold](phase2/docs/project_overview/figures/flute_packet_sizes.png)

The physical campaign also processed natural environmental recordings and synthetic signals. The [case ledger](phase2/docs/results/verification_20261017/hardware/cases.csv) identifies all 58 runs; the [application results](phase2/docs/project_overview/README.md) explain the monitor quality gates and recording provenance. No new hardware execution was performed to redraw these overview figures.

## What work is reduced on the laptop?

A dense consumer visits every spectral bin, including bins that the FPGA has already zeroed. A sparse consumer iterates over retained `(bin index, power)` entries. It can validate fewer bytes and skip arithmetic for omitted bins while producing the same thresholded features.

![Laptop workload using actual captured FPGA spectra](phase2/docs/project_overview/figures/host_workload_flute.png)

This experiment replays actual captured sparse FPGA packets from RAM on an **Intel Core i7-8750H**, with 3,001 frames per eight-second flute clip and 30 matched dense/sparse trials. The host re-encodes the same thresholded values into dense control packets; those controls are not additional FPGA captures. Both paths produce identical integer 16-band features.

| Threshold | Feature computation: paired elapsed-time reduction | Packet validation + features: paired elapsed-time reduction |
|---:|---:|---:|
| `0` | 185.8% more time | 20.8% more time |
| `10^8` | 58.2% less time | 77.2% less time |
| `10^9` | 65.5% less time | 77.7% less time |
| `10^10` | 74.4% less time | 83.3% less time |
| `10^11` | 78.6% less time | 85.6% less time |

Percentages are medians of `100 × (dense_time - sparse_time) / dense_time` across 30 matched pairs. These are elapsed times for the measured consumer stages, with input already resident in RAM. FPGA execution, Ethernet, disk access, and AI inference are excluded. At `10^8`, the median paired saving for validation plus features is **3.84 ms per eight-second clip**. That is a small absolute saving for one stream. It establishes a benefit for this consumer, not a whole-laptop utilization reduction or an end-to-end system speedup. Raw trial extracts and calculation rules are linked in the [results guide](phase2/docs/project_overview/README.md).

The application adds a **causal spectral-activity monitor** with grouped band energy, peak frequency, centroid, and activity-change events. At `10^7`, all four held-out natural recordings passed its registered quality gates in the physical capture audit. A separate software-reference replay benchmark measured a dense/sparse receiver time ratio of **1.311x**, the median of four per-recording median paired ratios, with 30 pairs per recording. That receiver result has its own timing boundary and is not a fresh physical-board timing measurement.

![Complete spectral monitor receiver, software-reference replay](phase2/docs/project_overview/figures/host_workload_monitor_replay.png)

### Findings that limit the claim

- In an earlier resident-compute comparison of six 1,024-sample jobs, the TSH1 FPGA implementation took **4.23 to 6.25 times** the i7-8750H laptop's median time. This is a historical compute-only result, not a new TSH2 timing measurement. Sparse host processing is a different benefit.
- The FFT/IFFT schedule still runs at every threshold. Fewer retained bins do not imply fewer FPGA transform cycles.
- Thresholding a waveform did not establish fewer YAMNet inference calls or an AI inference speedup. This repository's demonstrated consumer is spectral monitoring.
- Electrical energy savings, live microphone acceptance, production reliability, and recognition accuracy remain unproven.

## Design verification

The verification work connects a defined contract, an independently checked numerical model, RTL simulation, and physical board output. It also tests whether the checkers reject incorrect results.

![Verification environment and evidence flow](phase2/docs/project_overview/figures/dv_topology.png)

| Verification layer | Executed evidence |
|---|---|
| Reference arithmetic | 729,156 independent arithmetic comparisons; 11 C++ tests; 248 finite-input corner checks |
| Directed RTL campaign | 14 fresh suites covering arithmetic boundaries, threshold semantics, finite geometry, malformed controls, stalls, and reset/recovery |
| Full-length RTL, included in the 14 suites | Two 384,000-input runs, checking 769,024 waveform outputs, 774,258 canonical-bin observations, and 6,002 frames in total |
| Public seeded regression | Three seeds across four threshold/packet-mode cases: 12 epochs, 18,432 exact waveform samples, 13,932 canonical rows, and 94,440 packet bytes |
| Checker qualification | Intentional corrupt/missing results, unknown-value and completion controls, bounded timeouts, plus a real RTL run with mutated expected output that must fail |
| Physical DE1-SoC campaign | 58 epochs, 29 configurations, 13 inputs; exact output/packet comparison and zero final fault/drop flags |
| Traceability | Source and fixture hashes, requirement dispositions, observed event coverage, JSON/JUnit receipts, native VCD traces, and published data provenance |

**A real defect was found and repaired:** the software reference's signed round-shift helper mishandled shifts 63 and 64. The failing boundary cases were reproduced before the fix, then checked independently after it. This repair concerns the reference arithmetic; it is not presented as a new FPGA speed optimization.

![Round-shift boundary defect and correction](phase2/docs/project_overview/figures/dv_rounding.png)

**Flow control and recovery are verified explicitly.** The traces below come from RTL simulation. They show held data during output stalls, completed transfers, and reset/recovery behavior. They are evidence excerpts, not schematic illustrations or complete full-run waveforms.

![RTL handshake and output backpressure](phase2/docs/project_overview/figures/dv_handshake.png)

![RTL reset and recovery](phase2/docs/project_overview/figures/dv_reset.png)

Open the native [startup](phase2/docs/results/verification_20261017/waveforms/startup.vcd), [reset/recovery](phase2/docs/results/verification_20261017/waveforms/reset_recovery.vcd), and [final-output-stall](phase2/docs/results/verification_20261017/waveforms/final_y_stall.vcd) traces in a waveform viewer. The [16-page academic report](phase2/docs/verification/portfolio/TRECAP_DV_Portfolio.pdf) includes eight figures, eleven tables, methodology, failures, source binding, and sign-off limits. Its [LaTeX source and build guide](phase2/docs/verification/portfolio/README.md) are committed with the report.

The disposition is **pass for the registered finite-file profile under the tested conditions**. The environment uses SystemVerilog procedural assertions and scoreboards. It is not UVM, formal verification, formal CDC/RDC, a code-coverage closure claim, or industrial certification. The broader original specification still has **30 partial and 16 excluded requirements**, which are requirement dispositions rather than a test pass rate. [Read the complete verification scope](phase2/verification/README.md).

## Reproduce the checks

Clone the repository, then check the public package using Python 3.12:

```sh
git clone https://github.com/DatDinhh/T_RECAP.git
cd T_RECAP
python phase2/verification/tsh2/run.py --check-package
```

This command validates the package and qualifies its scoreboards using constructed traces. It does not simulate RTL. With an installed ModelSim-compatible simulator, run:

```sh
python phase2/verification/tsh2/run.py --suite regression --sim-bin /path/to/modelsim/bin --out tsh2_regression_01
```

Build and test the C++20 reference model with CMake 3.24 or later:

```sh
cd phase2
cmake --preset verify
cmake --build --preset verify --parallel 2
ctest --preset verify
```

The [portable regression guide](phase2/verification/tsh2/README.md) documents simulator setup, output files, and fresh output-directory requirements. GitHub Actions runs reference functional tests, RTL frontend elaboration, hygiene checks, package/checker qualification, and public evidence integrity checks on Linux and Windows. Licensed RTL simulation and physical hardware runs are recorded separately.

The [TSH2 application archive](phase2/profiles/tsh2/README.md) includes the board adapter, service, consumers, monitor, and local visualizer source. It also documents external coefficients, native libraries, fitted-image dependencies, and runtime admission requirements. It is not a one-command board deployment. The separate [Spectral Studio repository](https://github.com/DatDinhh/trecap-spectral-studio) is a recorded demonstration; visiting it does not remotely operate this board.

## Repository map

| Path | Purpose |
|---|---|
| [`phase2/rtl`](phase2/rtl) | Fixed-point datapath and broader source/transport RTL |
| [`phase2/profiles/tsh2`](phase2/profiles/tsh2/README.md) | Archived current finite-file adapter, service, consumers, monitor, and visualizer |
| [`phase2/sw/reference_model`](phase2/sw/reference_model/README.md) | C++ arithmetic reference and artifact tools |
| [`phase2/verification/tsh2`](phase2/verification/tsh2/README.md) | Portable synthetic RTL regression and scoreboards |
| [`phase2/verification/campaign_sources`](phase2/verification/campaign_sources/README.md) | Accepted boundary/recovery bench source archive |
| [`phase2/docs/verification/portfolio`](phase2/docs/verification/portfolio/README.md) | Academic PDF, editable LaTeX, and report figures |
| [`phase2/docs/results/verification_20261017`](phase2/docs/results/verification_20261017/README.md) | Physical/RTL evidence ledger, coverage, source binding, and VCDs |
| [`phase2/docs/project_overview`](phase2/docs/project_overview/README.md) | README figures, tables, audit, provenance, and reproduction notes |
| [`phase2/docs`](phase2/docs/README.md) | Specifications, architecture, build guides, and historical results |
| [`phase1_demo`](phase1_demo) | Historical first-semester demonstration |

The earlier [architecture atlas](phase2/docs/architecture/diagrams/README.md), [board-power study](phase2/docs/results/board_power_20260925/README.md), and [ARM HPS benchmark](phase2/docs/results/hps_cpu_benchmark_20260925/README.md) remain available with their original scope. The HPS benchmark compares the CPU on the board, not the laptop CPU.

## About

T-RECAP is a senior capstone engineering project investigating the connection between fixed-point FPGA signal processing, sparse spectral data, and measurable downstream work. Its portfolio spans RTL design, numerical debugging, hardware/software integration, application evaluation, and reproducible design verification.

Project-authored code is distributed under the [MIT license](LICENSE). Third-party toolchains and audio datasets retain their own terms. The flute example is credited to Lawrence Fritts and the [University of Iowa Musical Instrument Samples collection](https://theremin.music.uiowa.edu/MIS.html); environmental recording credits and dataset distinctions are preserved in the [data provenance](phase2/docs/results/verification_20261017/data_provenance/dataset_terms.json). Raw third-party recordings are not bundled with the verification package.
