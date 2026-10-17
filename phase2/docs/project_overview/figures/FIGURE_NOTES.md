# README figure sources and interpretation

These are source-bound scientific graphics from retained verification and timing evidence. Generating this bundle did not run hardware, launch a service, or rerun a timing benchmark. No raw recording, returned waveform array, board address, runtime identity or workstation path is included.

| Figure | Evidence and interpretation |
|---|---|
| `current_architecture.png` / `.svg` | Conceptual finite-file TSH2 data flow from admitted sources. CPU boxes and FPGA fabric are explicit. THR2 is configured before START and remains fixed during the epoch. Feeding and draining are two activities of the same HPS service. No internal stage timing is inferred. |
| `flute_captured_spectrograms.png` / `.svg` | Registered input and physical output epochs 49, 51 and 57 at thresholds 0, 100000000 and 100000000000. Trial 1 at each threshold is byte-identical. This is a new diagnostic visualization of existing captured samples, not a new capture. |
| `host_workload_flute.png` / `.svg` | Historical physical FPGA sparse packets replayed on the recorded Intel Core i7-8750H Windows host. Compares same-threshold dense and sparse CPU consumers. Includes threshold zero, where sparse processing is slower. Does not compare CPU execution against FPGA execution. |
| `host_workload_monitor_replay.png` / `.svg` | Separate revision02 monitor timing campaign using software-reference spectra. Four held-out five-second recordings, 30 paired trials per recording. CPU model was not retained. Physical board output verification is separate. |
| `flute_waveform.png` | Byte-for-byte copy of the accepted five-threshold waveform plot. Same gain and fixed 384-sample alignment at every threshold. |
| `flute_error_agreement.png` | Byte-for-byte copy of the accepted plot separating difference from original input from difference from the threshold-specific reference. |
| `flute_packet_sizes.png` | Byte-for-byte copy of the accepted captured TSP1 size plot. The denominator is the compact dense spectral representation, not WAV or PCM. |
| `dv_topology.png` | Byte-for-byte copy of the accepted oracle/host/physical-capture boundary diagram. |
| `dv_handshake.png` | Byte-for-byte copy of actual simulator ready/valid stall traces. Testbench clock is 10 ns; the nominal/constrained physical clock period is 20 ns. |
| `dv_reset.png` | Byte-for-byte copy of actual clear/reset waveform excerpts. Separate numerical scoreboards establish recovery; the excerpts do not show an entire recovery epoch. |
| `dv_rounding.png` | Byte-for-byte copy of measured old/repaired executable responses for the retained rounding counterexamples. |

## Spectrogram definition

The input rate is 48,000 samples/s. Each displayed signal has 384,000 samples. The physical output has 384,512 samples; the plot uses `Y[384:384384]` against `input[0:384000]`. The complete returned output, including its tail, matches its registered threshold-specific reference.

The diagnostic transform uses a periodic Hann window of 1,024 samples, a 256-sample hop, and a 2,048-point real FFT. It has 1,497 valid windows, no centered framing and no edge padding. FFT zero padding extends each 1,024-sample window to 2,048 points. This diagnostic STFT is distinct from the hardware's 256-point transform and 128-sample hop.

The amplitude is normalized by the coherent window gain and a full-scale reference of 2,048 signed12 units. Positive interior rFFT bins are doubled; DC and Nyquist are not. Color is `20*log10(amplitude/full_scale)`, clipped to a common -100 to -20 dBFS display range. Every panel uses the full 0 to 24 kHz frequency interval and the same eight-second time interval. There is no per-panel normalization. Zero, coherent sine, DC and Nyquist normalization controls passed; the threshold-zero input/output STFT arrays are exactly equal.

The nonzero-threshold images show changes to the signal, not a measured improvement in perceptual quality or inference accuracy. Scalar input/reference error checks are in `spectrogram_metrics.json`.

## CPU timing definitions

Bars show route-wise median elapsed times. Ratios are medians of matched dense/sparse trial ratios, not ratios of bar heights. Error bars show descriptive within-session interquartile ranges, not confidence intervals or cross-host uncertainty bounds. The flute chart uses the same recorded CPU for its compared routes and reports 30 paired warm-RAM trials at each threshold. Its threshold-zero control is unfavorable to sparse processing. No live network, FFT/IFFT or AI inference is timed.

The optional monitor replay chart uses a separate recorded Windows session. Its cached receiver routes exclude DSP production, transport, disk and context construction. The source campaign did not record a CPU model. Four recorded categories and their selected activity gates do not establish fault-classification accuracy.

## Reproduce from an authorized archive

`build_figures.py` requires Python, NumPy and Matplotlib. The exact generation versions and input hashes are in `figure_provenance.json`. The script is read-only with respect to evidence and creates a new output directory. From this directory:

```sh
python build_figures.py --workspace <campaign-archive-root> --profile <phase2/profiles/tsh2> --evidence ../data --out <new-output-directory>
```

The public checkout intentionally does not contain the raw licensed input/audio capture arrays or every original archive artifact. A full regeneration therefore requires the separately retained, authorized campaign archive with matching hashes. Host plotting tables are included under `../data`; they were independently reconciled against the recorded raw paired trials. The figure script accepts an optional `--python-packages` directory for an already provisioned scientific Python environment.

Audio attribution and dataset terms are documented in the [public data provenance](../../results/verification_20261017/data_provenance/dataset_terms.json). The published images are derived visualizations; no raw audio is bundled here.

`figure_provenance.json` identifies every original source by a public archive/repository alias and SHA256. The seven reused PNGs are copied byte-for-byte. `figure_audit.json` records image validity, source binding, rendering review and public-text hygiene checks. Original source hashes are not presented as hashes of transformed exports.
