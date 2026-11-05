# TRF1 recorded RF application

TRF1 identifies the recorded RF application interface of T-RECAP. It accepts complex unsigned 8-bit I/Q files and adapts them in FPGA hardware to the real signed 12-bit input of the existing FFT, adjustable threshold, IFFT/WOLA and TSP1 core.

The application was implemented and exercised on DE1-SoC before this publication. This package preserves that source, adds portable verification, and documents the complete architecture. The audio TSH2 and RF TRF1 applications are separate fitted profiles. They do not form a runtime audio/RF switch. No board is programmed by the offline verification commands.

[Eight-view RF architecture atlas](../../docs/architecture/rf_iq/README.md) | [Verification and report](../../docs/verification/rf_iq/README.md) | [Runnable tests](../../verification/rf_iq/README.md)

## Data path

1. A receiver records a raw CU8 file, with I followed by Q at each sample time. Sample rate and receiver center frequency are separate metadata.
2. The laptop uploads a bounded archive to HPS Linux RAM. A local ARM client reads the file and feeds raw I/Q pairs through memory-mapped registers.
3. A 256-entry input FIFO and registered prefetch stage feed the RF adapter. Hardware centers the bytes, interpolates by four, mixes to a real intermediate frequency, applies fixed gain, rounds, and reports saturation.
4. The finite-file source pads after the valid RF interval to the existing 384,000-sample core transaction.
5. The unchanged core exports reconstructed real-IF samples Y and separate TSP1 power records. The HPS drains both streams and returns a results archive.
6. The laptop validates counts and numerical output. Optional I/Q recovery and protocol decoding are separate CPU operations.

See [transport boundaries](board/TRANSPORT.md), the [RF arithmetic contract](adapter/CONTRACT.md), and the [TRF1 register contract](board/CONTRACT.md).

## Numerical interface

| Property | Value |
|---|---|
| Input | 1 through 96,000 CU8 pairs |
| Centering | `2*b - 255` for each unsigned byte |
| FIR | 81 fixed taps, four polyphase branches, signed 18-bit coefficients with 16 fractional bits |
| Datapath | One shared multiplier, signed 36-bit accumulator |
| Mixer | `+I, -Q, -I, +Q` at successive interpolated sample times |
| Output | Signed 12-bit, nearest rounding with half ties away from zero, saturation with explicit counters |
| Gain settings | 0 through 3, representing 256, 512, 1024 and 2048 counts per normalized input unit |
| Headroom | Gains 0 and 1 cannot clip for the fixed coefficients and legal CU8 input |
| Valid output | Exactly `4*N` real samples, followed by separate core-transaction padding |
| Core geometry | FFT 256, hop 128, 384,000 input samples, 384,512 full-tail Y samples, 3,001 frames |
| Hardware identity | Magic `0x54524631`, ABI `0x00010000`, build-specific 256-bit SOURCE_ID |

For the recorded 250 ksample/s complex input, the real output represents 1 Msample/s with its signal centered at 250 kHz. The receiver had already converted the original 433.92 MHz signal to baseband I/Q. These sample rates describe the representation, not measured execution throughput. Real IF is not demodulated audio. TSP1 omits phase and cannot reconstruct I/Q on its own.

## Source map

| Path | Role |
|---|---|
| [adapter/rtl](adapter/rtl) | RF numerical adapter and finite-file padding wrapper |
| [adapter/coefficients](adapter/coefficients) | Fixed interpolation coefficients |
| [adapter/model](adapter/model) | Independent full-convolution reference and synthetic fixture generators |
| [board/rtl](board/rtl) | TRF1 register interface, FIFO buffering and complete-core integration |
| [board/host](board/host) | Raw-I/Q ARM client and offline register/file-boundary tests |
| [board/platform](board/platform) | Exact project-authored top, HPS wrapper, constraints and fitted project settings |
| [board/orchestration](board/orchestration) | Archived bounded upload and capture controller with explicit external workspace dependencies |
| [snapshot](snapshot) | Frozen non-vendor DSP and adapter closure used by public simulation |
| [source_manifest.json](source_manifest.json) | Original and published source hashes with transformations identified |

The project name remains **Threshold-based Reduction and Encoding for Controlled Audio Processing**. RF extends the input applications while retaining the numerical core.

## Reproduce offline

From the repository root:

```sh
python -m pip install -r phase2/verification/rf_iq/requirements.txt
python phase2/verification/rf_iq/run.py --check-package
python phase2/verification/rf_iq/run.py --suite all --sim-bin /path/to/modelsim/bin --out rf_verification_01
```

The package check validates source and fixture identities. It is not an RTL simulation. The command with `--suite all` invokes the installed simulator. Use a fresh output directory. The [verification guide](../../verification/rf_iq/README.md) defines suite contents, dependencies and observed coverage. `python phase2/verification/rf_iq/check_evidence.py` separately checks the committed execution receipts against the published sources.

For the Linux HPS client, [board/host/README.md](board/host/README.md) provides native offline tests and optional ARM compilation. These tests never access physical MMIO.

## Board reproduction boundary

The published source closure supports RTL simulation without Intel generated HPS IP. A complete Quartus board rebuild additionally requires the qualified Platform Designer system, regenerated Intel IP, device support, DDR assignments, HPS handoff, boot assets and matching board admission. Those generated vendor files, compiled SOF and local boot artifacts are not bundled.

The settings in `board/platform` document the historical fitted project. Their relative paths describe the original build layout. They are not a standalone project directory, and their historical SOURCE_ID must not be reused to identify a changed build. The [platform guide](board/platform/README.md) describes the required closure and checks.

The initial physical campaign completed five full-size epochs with exact Y and TSP1 reference agreement. Those measurements are historical evidence, not newly repeated hardware runs during publication. The current board profile must be read and admitted before any later deployment. The most recent recorded local handoff had restored TSH2 audio after the RF experiments.

## Interpretation

RF sparsification trades retained spectral information for a smaller spectral representation. Packet reductions use dense TSP1 over the same valid interval as baseline. They are not reductions relative to the raw CU8 recording. Error against the fixed-point adapter output excludes the adapter's own conversion error.

This profile demonstrates buffered recorded-file processing. The reported checks do not establish live RF reception, lossless conversion, arbitrary-protocol preservation, power savings, or a CPU speedup. TSH2 UVM and formal results cover their documented modules and assumptions. RF verification is provided by the numerical model, self-checking RTL tests and source-bound physical captures listed above.
