# T-RECAP reference-model presentation figures

Team #2

## Scope
We ran the maintained C++ fixed-point reference model on the checked-in input and coefficient artifacts. This package contains 11 threshold settings for the same multitone input, one impulse run, and one zero-input run. These are software reference results, not final golden results, FPGA captures, or electrical measurements.

The original multitone directory ends in thr64, but its configuration uses the raw squared threshold THR2=4096. Plot labels follow configuration metadata.

## Present these first
For a short TA discussion, use figure 01 (alignment), figure 02 (mask decision), and figure 04 (tradeoff). The other figures support a longer explanation.

## Files
- index.html: local gallery.
- T_RECAP_Reference_Model_Figures.pdf: seven full-page figures.
- figures/*.png: 2880 by 1620 pixels for slide insertion.
- figures/*.svg: vector plots.
- metrics_summary.csv: results for every run.
- data/: exact input, coefficient and model-output snapshots.
- provenance.json: source, executable and data hashes.
- validation_report.json: independent artifact consistency checks, when available.

## Figure explanations
### 1. Waveform and causal delay
The model reproduces this multitone vector exactly after aligning the input by 384 samples. The comparison includes startup and the complete tail. This is one test, not a universal zero-error claim.

### 2. Spectrum and threshold decision
These are canonical pre-mask FFT bins from the C++ model, not an FFT of the entire output stream. An eligible bin is suppressed when magnitude squared is strictly less than THR2. The lower panel shows the actual final mask. Zero magnitudes use a display floor of 1 on the log plot.

### 3. Threshold impact on waveforms
Increasing THR2 changes the output and can spread error around the finite input boundaries. Shaded areas in the lower panel lie outside the delayed input support. They remain part of the error calculation.

### 4. Threshold tradeoff
At THR2=10^11, this vector suppresses 93.06% of eligible unique-bin instances and retains 99.21% of weighted eligible spectral magnitude squared, with 22.71 LSB full-stream RMSE. Spectral retention is a representation metric, not electrical energy saved.

### 5. Spectrum and mask across frames
The upper heatmap uses canonical pre-mask magnitudes with a log-display floor of 1. The lower heatmap shows exact binary mask decisions. Protected DC at k=0 stays kept. Frame index is not a hardware-clock or measured-time axis.

### 6. Window and overlap-add coefficients
The top plot decodes the frozen coefficient table. The lower plot shows the quantized squared-window overlap sum, which is close to but not mathematically identical to one. This coefficient property supports reconstruction but is not a standalone proof for all signals.

### 7. Impulse diagnostic
The input and output impulses are separated by exactly 384 samples. At an assumed 48 ksample/s replay rate this design delay corresponds to 8 ms. This plot uses sample indices and does not measure hardware timing.

## Quantitative checkpoints
| Raw THR2 | Eligible bins suppressed | Eligible spectral magnitude squared retained | Full-stream RMSE (LSB) | Max absolute error (LSB) |
| --- | ---: | ---: | ---: | ---: |
| 4096 | 1.1285% | 99.99999999% | 0.000000 | 0 |
| 1000000 | 47.5694% | 99.99996019% | 0.044194 | 1 |
| 100000000000 | 93.0556% | 99.21089788% | 22.714000 | 211 |
| 10000000000000 | 99.3924% | 66.77399770% | 129.554412 | 616 |

## Methods and limits
- Fixed baseline: signed 12-bit samples, FFT length 256, hop 128, F=15, causal delay 384 samples, protected DC, unprotected Nyquist.
- Compare y[n] with x[n-384], zero-extended outside the original input. Errors include every emitted output sample, including startup and tail.
- The multitone and impulse runs have Ns=1024, 9 active frames and Ny=1536. The zero run has Ns=4096, 33 frames and Ny=4608.
- Plot axes use sample indices and FFT bins because vector metadata does not specify a sampling frequency.
- Canonical bin statistics precede masking. A final mask value of 1 suppresses the bin. THR2 is an unsigned raw magnitude-squared threshold, not a voltage or dB level.
- Suppression counts unique eligible bin instances. Retained spectral magnitude squared weights mirrored interior bins by two. Zero-input spectral retention is undefined and appears blank in the summary.
- These results demonstrate this signal and model. They do not establish general denoising usefulness or a universal quality bound.
- Spectral-bin suppression does not measure electrical energy saved. The baseline reference executes its fixed FFT/IFFT computation.
- Spectrum plots use model-exported bin statistics rather than substituting NumPy FFT results.

## Reproduce
From the project root, build the reference target and choose a fresh run directory:

    cmake --build build/host --config Release --target phase2_golden_model
    python scripts/analysis/plot_reference_presentation.py --repo . --run-reference --run-dir runs/reference_presentation_new --out docs/presentation/reference_model_new

Python requires NumPy and Matplotlib. To render recorded runs without executing the model again, omit --run-reference and point --run-dir at the recorded run directory. The script recomputes waveform error metrics before plotting. When running the copied script from this figure package, always pass --repo explicitly.

## Source contracts
- sw/reference_model/README.md
- sw/reference_model/docs/stft_wola_contract.md
- spec/schemas/bin_stats.schema.md
- spec/schemas/frame_stats.schema.md
- docs/evaluation/benchmark_plan.md
