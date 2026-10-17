# README evidence review

Reviewed commit `351ff6a8ef9f7ebd9893a531d71ac7626f95a0e2`: 1,454 tracked files,
35,698,684 bytes. Every committed path is inventoried with its Git blob ID and
classified by role. This is a full inventory and a focused claims/source review,
not a claim that every line or historical hardware profile was functionally tested.

The current application is a finite-file spectral-activity monitor: observe
dominant frequency, spectral centroid, 16 band energies, and newly persistent
band activity while exploring whether thresholded spectra reduce receiver work
and spectral traffic. A separate IFFT/WOLA path allows the reconstructed audio to
be compared with the original. This gives the project a concrete engineering
question and a visible quality-versus-cost tradeoff. It does not require claims
about machine fault diagnosis, AI inference, or electrical energy savings.

## Current versus historical architecture

The active TSH2 implementation accepts a finite PCM epoch through a TCP service
on HPS, moves samples and results through MMIO FIFOs, and applies one-frame
spectral export credit. Output stalls can pause progress. It is not the original
best-effort, nonbackpressuring FPGA-to-DDR-to-UDP telemetry architecture.

The active profile's three concrete results should be linked separately:

1. Numerical and integration correctness: the October 17 physical/RTL campaign.
2. Reconstruction and spectral-size tradeoffs: actual flute captures with fixed
   amplitude scale, aligned by 384 samples, and matched threshold-specific gold.
3. Application and receiver benefits: the frozen monitor pilot and historical
   paired host measurements, with their exact workload and origin stated.

Power-only TSP1 cannot reproduce the waveform because it does not contain phase.
The returned Y stream is the reconstructed audio. Do not place a decoder-to-IFFT
arrow after TSP1 in the new architecture picture.

## Changes needed in the existing root README

- The opening describes broad Phase 2 architecture without explaining why a user
  would want the current monitor. Lead with the concrete application and the
  threshold tradeoff before the verification portfolio.
- The historical architecture atlas is useful, but label it as the original
  architecture; use a separate active-profile picture near the introduction.
- Verification is strong evidence, but the current front page lacks an actual
  processed-audio comparison and a receiver-work result. Show the spectrograms,
  waveform/quality panel, and a clearly scoped paired host plot.
- Keep old power and Cortex-A9 resident-input studies in a historical-results
  section. Their numbers must not become current TSH2 end-to-end comparisons.
- Keep the full project name, while explaining that electrical energy saving
  has not been established. A repeated warning banner need not replace a useful
  objective, measured result, and one concise limitations paragraph.

## Changes needed in phase2/README.md

Its top historical-status note is accurate but is followed by headings such as
"Project scope" and "Current status" that read as the active system. The main
diagram still shows LINE-IN/ADC selection, DDR ring, HPS UDP and safe-boundary
commands. Its statements about telemetry never backpressuring the core and
integrated HPS transport remaining pending need an explicit original-baseline
label. TSH2 has a separate finite TCP/MMIO path; this does not close the original
DDR/UDP requirements.

The 21,220-ALM/209-pin result is an older image. The current admitted TSH2 fit is
6,521 ALMs and has its own source/SOF binding. Neither should overwrite the
other's evidence. Nominal 50 MHz and a 384-sample algorithmic delay do not establish
analog, network or isolated-core latency.

The old source guide and commands can remain useful, but separate the shared
reference/core, original architecture, current TSH2 workbench, portable DV
entry point, and archived deployment dependencies in the repository map.

## Host results selected for the new README

The most application-relevant plot compares complete cached dense and sparse
receivers for the four held-out five-second machine-category recordings at the
frozen threshold of 10,000,000. All four recording medians favor sparse. The
median across per-recording median paired dense/sparse ratios is 1.31073x, with
an IQR of 1.27781 to 1.39267 across those four medians. Each recording has 30
matched measured trials. The same Python aggregation and persistence logic is
included in both routes, and their outputs match exactly.

This timing campaign used software-reference spectra, not a live FPGA producer.
It records Windows 11 and Python 3.12.14, but no CPU model. Do not transfer the
i7 identity from a different experiment. Later physical captures validate the
numerical monitor path; they do not retroactively turn the original host timing
into a fresh board or whole-system benchmark.

As a second, stronger machine-identified example, the downstream flute benchmark
replayed actual earlier FPGA packets on an Intel Core i7-8750H / Windows 11 host.
At threshold 100,000,000, strict decoding plus 16-band features saved 77.2067%
paired elapsed time, or 3.83659 ms per eight-second clip. The separately reported
dense/sparse medians are 5.01791/1.13780 ms. Isolated feature consumption saved
58.2199%. At threshold zero, sparse was worse: 20.7820% more decode-plus-feature
time and 185.8159% more isolated-consumer time. Include this unfavorable control.

Both results are warm-RAM batch measurements with materialized results and
validation outside the timed region. They are not CPU utilization, total system
latency, general AI speedup, or evidence that an FPGA beats a laptop. The saved
time is small in absolute terms for one audio stream. Paired statistics must not
be replaced by a ratio of unrelated medians.

## Representation and quality denominators

- Eight-second flute at threshold 100,000,000: 523,200 sparse spectral bytes
  versus 2,856,952 compact dense spectral bytes, an 81.6868% reduction. Aligned
  waveform NRMSE versus the original input is 1.7632%; maximum error versus the
  threshold-specific reference is zero LSB. These measure different things.
- Threshold-zero flute: sparse spectra grow 13.4454% relative to compact dense.
- Four held-out monitor clips: 24.79% to 44.57% less spectral data than matched
  dense. All four sparse streams still exceed 480,000-byte PCM16 and 360,000-byte
  packed PCM12. Neither representation is a compressed WAV.
- The task-summary-only CPU control needs 6,552 bytes for the 39 monitor groups.
  It loses fine-bin spectra, is not emitted by current FPGA RTL, and its
  serialization was not timed. This is a useful alternative baseline.

The monitor passes the registered engineering tolerances on four held-out clips.
Only the chainsaw clip has positive natural activity clusters: three, all
retained. The remaining recordings have no baseline clusters. This is agreement
with threshold-zero measurements, not independently labeled detection accuracy.
Revision 02 was developed after revision 01 failed calibration controls; the
held-out split remained frozen. Keep that development history visible in the
detailed results, even if the README uses one concise scope sentence.

## Evidence and publication

`claims_matrix.json` and `.csv` contain 18 scoped claims with exact artifact IDs
and SHA256 hashes. `host_workload_audit.json` records independent recomputation of
all paired medians and IQRs from the retained raw trials. The two raw trial CSV
copies are byte-identical and contain numeric measurements, recording IDs and
route names only. They include unfavorable cases and warmups.

`PUBLICATION_FILES.json` identifies a compact public subset. The audit scripts
and full tracked inventory can remain local review tools. Archive IDs are
provenance references, not promised repository files. This task performed no
new benchmark, hardware action, Git mutation or source edit.

Suggested GitHub About text: "Fixed-point FPGA spectral processing on DE1-SoC:
thresholded spectra, audio reconstruction, causal activity monitoring, and
source-bound verification."
