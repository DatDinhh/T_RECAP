# T-RECAP Phase 2

**Threshold-based Reduction and Encoding for Controlled Audio Processing**

See [project naming and scope](docs/project_identity.md) for the current name and historical document labels.

**Current verified application: finite-file FPGA spectral sparsification, waveform reconstruction, and laptop spectral monitoring.**

The [main project README](https://github.com/DatDinhh/T_RECAP#readme) explains the objective, architecture, processed-audio spectrograms, measured data/workload tradeoffs, and design verification. Start there for a visual overview. This page maps the implementation and reproduction paths.

**New to the terminology?** See [Terms and abbreviations](#terms-and-abbreviations), including the difference between TSH2, THR2 and TSP1.

## Current profile and objective

The **TSH2 finite-file profile** retains the FFT, tunable squared-magnitude threshold, and IFFT/WOLA reconstruction. It additionally exports sparse spectral powers so a compatible host consumer can avoid processing omitted bins. Evaluation measures waveform distortion, spectral packet bytes, and host consumer time separately.

![Current TSH2 architecture](docs/architecture/tsh2/01-system.png)

The [current eight-view TSH2 atlas](docs/architecture/tsh2/README.md) details finite frames, transform storage, epoch/feed-drain sequencing, TSP1/Y outputs, TCP/HPS/MMIO, configuration/backpressure and clock/reset/verification boundaries.

A laptop uploads complete PCM input to the ARM HPS over TCP. The HPS buffers it and interleaves MMIO writes to the FPGA's input FIFO with reads from waveform and spectral output FIFOs. The FPGA produces reconstructed samples and phase-free TSP1 powers. The HPS returns both outputs. Laptop software validates and visualizes them, then computes spectral features or monitoring events.

This path is finite and unpaced. Threshold and packet mode remain fixed during an epoch. Ready/valid output flow control and spectral-record credit can pause progress while preserving overlap state. Live microphone/codec operation, hard real-time transport, and original DDR-ring/UDP acceptance remain separate work.

| Current profile | Recorded value |
|---|---|
| Signal geometry | Signed 12-bit input, 256-point FFT/IFFT, a 128-sample hop and a 384-sample reconstruction delay |
| Full physical epoch | 384,000 input samples, 3,001 frames and 384,512 full-tail waveform samples |
| Numerical control | Fixed precision `F = 15`, unsigned 56-bit squared-magnitude `THR2` and protected DC |
| Hardware | DE1-SoC at nominal 50 MHz. Source-bound fit uses 6,521 ALMs, 47 M10Ks and 35 DSP blocks |
| Latest registered campaign | 14 fresh RTL suites and 58 physical epochs, with exact numerical/packet checks |

The [results guide](docs/project_overview/README.md) separates current physical captures, historical host timing, software-reference monitor replay, and original architecture studies. Read the denominators before comparing figures. No qualified electrical energy saving or FPGA advantage over the laptop is claimed.

## Choose an entry point

| Goal | Start here |
|---|---|
| Understand the application and view results | [Main README](https://github.com/DatDinhh/T_RECAP#readme), [figures and provenance](docs/project_overview/README.md) |
| Explore the current architecture in detail | [Eight-view TSH2 atlas](docs/architecture/tsh2/README.md) |
| Review the DV methodology and outcome | [Verification portfolio](verification/README.md), [academic PDF and LaTeX](docs/verification/portfolio/README.md) |
| Run reproducible off-board RTL tests | [Portable TSH2 package](verification/tsh2/README.md) |
| Inspect physical run evidence | [58-case campaign ledger](docs/results/verification_20261017/README.md) |
| Read the actual finite-file application source | [TSH2 workbench archive](profiles/tsh2/README.md) |
| Build the shared numerical model | [C++ reference model](sw/reference_model/README.md) |
| Explore the original broad architecture | [Historical atlas, 2026-09-14](docs/architecture/diagrams/README.md), [design](docs/architecture/architecture_design.md), [specification](docs/specs/README.md) |
| View a recorded demonstration | [Spectral Studio repository](https://github.com/DatDinhh/trecap-spectral-studio) |

## Terms and abbreviations

Start here if you are new to the project. **TSH2 is an implementation name, THR2 is a threshold setting, and TSP1 is an output format.** They refer to different things.

In one sentence: the **TSH2** FPGA profile applies **THR2** to FFT-bin power, exports retained spectral powers in **TSP1** packets, and separately produces reconstructed audio **Y**.

### Project names and output labels

| Term | Meaning in this repository |
|---|---|
| **T-RECAP** | Threshold-based Reduction and Encoding for Controlled Audio Processing. |
| **TSH2** | The internal identifier for the current finite-file FPGA application profile and its host register interface. A *profile* is a particular implementation with a defined configuration and interface. The repository does not document a long-form expansion of the letters T/S/H. |
| **TSH1** | The earlier FPGA profile used for the historical 1,024-sample resident-compute comparison. Its timing results must not be read as current TSH2 measurements. |
| **THR2** | The threshold applied to squared FFT magnitude: `Re(X)^2 + Im(X)^2`. It is expressed in the implementation's fixed-point power units, not percent, decibels or sound-pressure level. Values below it are suppressed. Equality is retained, and DC is protected. |
| **TSP1** | The project's version-1 spectral packet format. It carries frame metadata and power values, with retained-bin indices in sparse mode. It omits phase, so these packets alone cannot reconstruct the audio. |
| **Y** | The reconstructed time-domain audio output from the IFFT/WOLA path. This sample stream is separate from TSP1 spectral packets. |

For the exact interfaces, see the [TSH2 contract](profiles/tsh2/work/trecap_stream8_v01/CONTRACT.md) and [output architecture](docs/architecture/tsh2/README.md).

### Audio and signal processing

| Term | Meaning and why it matters here |
|---|---|
| **DSP** | Digital signal processing: numerical operations on sampled signals. A hardware *DSP block* is a dedicated arithmetic resource inside the FPGA. |
| **PCM / WAV** | Pulse-code modulation represents audio as numeric samples. WAV is a file container that can store those samples. WAV-file size and spectral-packet size are different measurements. |
| **FFT / IFFT** | Fast Fourier transform and inverse fast Fourier transform. The FFT maps a time-domain frame to frequency coefficients. The IFFT maps coefficients back to time-domain samples. |
| **WOLA** | Weighted overlap-add. Windowed, overlapping frames are combined to form the reconstructed waveform. |
| **Frame / hop** | A frame is one window of samples processed together. The hop is how far the next frame advances. Current settings use 256 samples per FFT frame and a 128-sample hop. |
| **Fixed-point arithmetic** | Integer arithmetic with an agreed binary scale. Rounding, saturation and scaling are part of the implementation and must match the numerical reference. |
| **Bin / canonical bins** | A bin is one discrete FFT frequency index. A real 256-point FFT has 129 unique bins including DC and Nyquist. These are the canonical bins used by the exporter. |
| **Magnitude / power / phase** | Magnitude is the size of a complex FFT coefficient. Power here is its squared magnitude. Phase describes its angle. TSP1 retains power, while waveform reconstruction requires the appropriate complex coefficients. |
| **DC / Nyquist** | DC is the zero-frequency component. Nyquist is half the sample rate. The threshold protects DC. The Nyquist bin can be suppressed. |
| **Dense / sparse / sparsification** | Dense spectra store every canonical bin, including zeros. Sparse spectra store retained bins with their indices. Sparsification suppresses selected coefficients and permits this compact representation. Dense and sparse data at the same threshold represent the same retained powers. |
| **Spectrogram / band energy** | A spectrogram shows spectral strength over time and frequency. Band energy groups and sums powers over selected bins. The 16-band consumer uses 16 disjoint bin groups. |
| **Spectral centroid / dominant frequency** | The centroid summarizes where spectral weight is concentrated. Dominant frequency identifies the strongest spectral component. Both are monitoring features computed downstream. |
| **NRMSE** | Normalized root-mean-square error. Here it is the waveform error-vector norm divided by the reference waveform's norm, reported as a percentage. It measures numerical waveform difference, not recognition accuracy or perceived audio quality. |
| **Consumer / features / AI** | A consumer is downstream software using the output. Features are summaries such as band energies. AI means artificial intelligence. YAMNet is the pretrained audio-event model explored here. The measured 16-band consumer is separate from AI inference. |

### Hardware, transport and timing

| Term | Meaning and why it matters here |
|---|---|
| **FPGA / SoC / DE1-SoC** | Field-programmable gate array / system on a chip. DE1-SoC is the development board used here. Its Cyclone V device contains FPGA fabric and an ARM processor subsystem. |
| **CPU / HPS / host** | CPU means central processing unit. HPS means hard processor system, the ARM side of the board running Linux. In the workload plots, the host CPU is the laptop's Intel CPU. The board CPU and laptop CPU are distinct measurement targets. |
| **MMIO** | Memory-mapped input/output. Software reads or writes hardware registers through addresses, allowing the HPS to configure, feed and drain the FPGA. |
| **FIFO / BRAM / M10K** | First-in, first-out queue / block RAM. FIFOs buffer ordered data. BRAM is on-chip memory. M10K names a Cyclone V embedded memory-block resource. |
| **RAM / DDR** | Random-access memory / double data rate. DDR refers to external memory in the historical architecture. It should not be confused with the current FPGA's on-chip FIFOs. |
| **Ready/valid / backpressure / credit** | A ready/valid transfer occurs when both signals are asserted. Backpressure pauses acceptance until the receiver has space. Spectral-record credit reserves capacity before producing another frame's records. |
| **TCP/IP / UDP / Ethernet** | Transmission Control Protocol / Internet Protocol and User Datagram Protocol are network protocols. Ethernet provides the network link. The current finite-file path uses TCP. UDP appears in the historical architecture. |
| **Epoch / tail / drain** | An epoch is one accepted processing run. The tail completes the final overlapping frames after input ends. Draining reads pending outputs. FPGA DONE alone does not mean the laptop has received every output. This use of epoch is unrelated to AI training. |
| **Latency / throughput / elapsed cycles** | Latency is delay to a defined output. Throughput is the amount processed per unit time. Elapsed cycles count clock ticks between defined events. The current TSH2 counter includes stalls caused by host feed/drain, so it is not a pure arithmetic-only timing measurement. |
| **ADC / LINE-IN** | Analog-to-digital converter / analog line-level input. These concern physical audio capture. The qualified implementation uses finite audio files. Live input through the board's audio jack is outside the verified scope. |

### Design verification and evidence

| Term | Meaning and why it matters here |
|---|---|
| **RTL / DUT** | Register-transfer level / design under test. RTL describes the hardware. DUT identifies the module or subsystem being checked. |
| **UVM** | Universal Verification Methodology. A SystemVerilog framework that organizes stimulus, drivers, monitors and scoreboards into reusable simulation components. Using UVM alone does not establish verification completeness. |
| **Sequence / driver / monitor / scoreboard** | A sequence supplies test transactions, which a driver applies to the DUT. A monitor observes actual interface activity, and a scoreboard compares those observations with expected results. |
| **Reference model / bit-exact** | The reference model computes expected numerical results. Bit-exact means the checked integer values match exactly, including the required rounding and saturation behavior. |
| **Seed / regression / coverage** | A seed makes a stimulus schedule reproducible. A regression runs a collection of tests. Coverage records what was exercised. The current observed counters are not a claim of complete code or functional coverage. |
| **Formal verification / assertion / assumption** | Formal tools analyze a mathematical model of the RTL. An assertion states what must hold. An assumption limits permitted inputs or behavior. A passing proof applies only to its stated model, properties and assumptions. |
| **SBY / Yosys** | Tools used by this project's formal flow. SBY, also known as SymbiYosys, coordinates formal jobs. Yosys processes the RTL into the model used by the proof flow. These names do not imply that the entire design was proved. |
| **Proof / cover / counterexample** | A proof establishes a property within its stated scope. A cover witness shows that a selected event is reachable. A counterexample is a trace that violates an assertion. A cover witness is not a universal correctness proof. |
| **Negative control** | An intentionally incorrect expected value or property used to check that the verification flow detects a fault. Its expected failure is evidence about the checker, not automatically a DUT defect. |
| **VCD / waveform** | Value Change Dump, a file format containing signal changes over simulation or formal-trace time. A waveform viewer displays those changes for inspection. |
| **CDC / RDC** | Clock-domain crossing / reset-domain crossing. These refer to checks on signals crossing clock or reset boundaries. They require their own analysis. Local functional proofs do not establish CDC/RDC signoff. |
| **Provenance** | The recorded source version, tool configuration, inputs and run artifacts that connect a reported result to the work that produced it. |

## Reproduce portable verification

Run from this `phase2/` directory with Python 3.12:

```sh
python verification/tsh2/run.py --check-package
python docs/results/verification_20261017/export_public_evidence.py --check docs/results/verification_20261017
```

The first command checks source/fixture admission and scoreboard controls. It does not run a DUT. For actual RTL simulation with a ModelSim-compatible installation:

```sh
python verification/tsh2/run.py --suite regression --sim-bin /path/to/modelsim/bin --out ../../tsh2_regression_01
```

Use a fresh output directory. The package contains project-generated synthetic stimuli and exact checkers. No board or third-party recording is required. See its README for dependencies, smoke tests, logs, event coverage, and JUnit results.

For the C++20 reference model, use CMake 3.24 or later:

```sh
cmake --preset verify
cmake --build --preset verify --parallel 2
ctest --preset verify
```

GitHub Actions executes source hygiene, RTL frontend elaboration, reference functional tests, checker qualification, and public evidence integrity on Linux and Windows. Licensed simulator runs and board measurements have their own receipts. The [verification scope](verification/README.md) records remaining requirements and separates procedural SystemVerilog checking from formal or UVM claims.

## Source map and deployment boundaries

| Path | Role |
|---|---|
| `rtl/`, `spec/`, `config/` | Shared datapath and original architecture source/contracts |
| `sw/reference_model/` | Fixed-point arithmetic, finite reference processing and artifact generation |
| `profiles/tsh2/` | Archived finite TCP/MMIO profile, stream wrapper, consumer, monitor and local visualizer |
| `verification/tsh2/` | Self-contained admitted RTL source/fixtures and portable simulator runner |
| `verification/campaign_sources/` | Accepted directed bench archive for the larger campaign |
| `sim/` | Original simulation environments and reference adapter |
| `sw/hps/`, `sw/pc_dashboard/` | Original DDR/UDP transport and dashboard implementation |
| `platform/`, `constraints/` | Platform Designer boundary, board setup and timing/pin constraints |
| `artifacts/` | Shared coefficients, synthetic vectors, numerical expectations and manifests |
| `docs/` | Current verification/results and explicitly scoped historical design records |
| `legacy/` | Historical material excluded from active builds |

The TSH2 archive preserves maintained source, not every fitted/generated dependency or runtime plan. Its [README](profiles/tsh2/README.md) lists missing external artifacts and fresh admission requirements. Do not treat the old DDR/UDP dashboard launch instructions as a TSH2 board deployment. The recorded web demonstration does not give remote users access to a physical board.

## Earlier architecture and experiments

The original Phase 2 plan includes BRAM replay, LINE-IN, optional ADC input, nonbackpressuring telemetry taps, a reserved-DDR ring, HPS UDP transport, and a desktop dashboard. Those sources and design documents remain available, but successful TSH2 verification does not close every original requirement. The earlier overview is preserved [at its reviewed commit](https://github.com/DatDinhh/T_RECAP/blob/351ff6a8ef9f7ebd9893a531d71ac7626f95a0e2/phase2/README.md).

- [Original Lite fit and JTAG checkpoint](docs/results/de1soc_lite_bram_20260915.md): the earlier 21,220-ALM image, not the current TSH2 fit.
- [FPGA-only power study](docs/results/board_power_20260925/README.md): physical measurements that do not establish an electrical energy saving.
- [ARM HPS timing study](docs/results/hps_cpu_benchmark_20260925/README.md): a comparison with the CPU on the board, not the laptop, with explicit timer exclusions.
- [IFFT operand isolation](experiments/ifft_zero_isolation/README.md): a separate experimental overlay.
- [Original build sequence](docs/architecture/build_order.md) and [documentation guide](docs/README.md): component implementation and historical bring-up procedures.

See [contributing](CONTRIBUTING.md) for source ownership and generated-file rules, and [repository maintenance](docs/repository_maintenance.md) for publication checks.
