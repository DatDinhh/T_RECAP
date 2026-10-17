# Fixed-architecture spectral monitoring pilot: consumer revision02

Registered 3 October 2026 after v01 calibration and before any held-out signal
processing. v01 code and failed calibration are preserved unchanged in
work/trecap_spectral_monitor_v01 and outputs/trecap_spectral_monitor_v01.
At threshold0, four synthetic cases produced an intended band alert plus an
adjacent-band alert, so the original single-band event contract failed. This is
an explicit post-calibration consumer redesign. Calibration and synthetic
success in revision02 are developmental evidence; only four still-unseen
natural clips form the held-out evaluation. No numeric tolerance, data choice,
threshold grid, feature computation or RTL changes accompany this revision.

## Application and scope

A remote spectral monitor reports dominant frequency bin, spectral centroid,
16 disjoint band energies, and newly persistent band activity. This is a
measurement application, not machine fault diagnosis, AI or a safety alarm.
No RTL, model, original project, or existing benchmark evidence changes.
New-corpus DSP uses the frozen fixed-point software reference, independently
qualified against historical physical FPGA captures. Software outputs are not
new board captures. Historical physical flute data is a separate qualification.

## Inputs and partition

Eight official ESC-50 machine-category clips, all five seconds. Select the
lexicographically first two distinct original sources with explicit CC0,
CC-BY or CC-BY-NC licenses from each of vacuum_cleaner, washing_machine,
engine and chainsaw. Freeze pinned repository commit, metadata, licenses and
filenames before fetching audio. First filename in each category is calibration,
second is held out. This custom four/four split is not an official ESC evaluation.
Category labels do not establish faults or activity ground truth.

Preserve original amplitude, select channel0, convert PCM by its full-scale
integer range, resample44.1k to48k using pinned SciPy resample_poly/Kaiser5,
round/saturate to signed12 with scale2048. Record clipping and hashes. No gain
normalization, concatenation or inserted silence. Input length must be a
multiple128; these five-second inputs are240000 samples.

Eight deterministic synthetic controls, each5.12s at48k (245760 samples),
rounded/saturated signed12 without normalization. Frequencies are FFT bin
indices times187.5Hz. All sine phases start at zero; abrupt changes are known
test transitions. Persistent additions last [2.048,4.096) seconds:
1. all zero;
2. steady k8, amplitude512;
3. k8 amplitude512 plus k48 amplitude16;
4. k8 amplitude512 plus k48 amplitude32;
5. k8 amplitude512 plus k48 amplitude64;
6. k8 amplitude512 switches to k20 amplitude512 at2.048s;
7. k8 amplitude512 plus k48 amplitude32 only [2.048,2.176)s;
8. k8.4 amplitude512 plus k48.4 amplitude32 during the persistent interval,
   with independent NumPy default_rng(20261003) Gaussian noise SD2 throughout.
Controls3/4/5/8 each intend one persistent new event in band floor(16*48/129);
control6 intends one in band floor(16*20/129). Others intend none. These are
controlled signal tests, not natural fault examples. Do not remove failing ones.

## Monitor contract

Unchanged FFT256/H128 at48k,129 unique power bins, protected DC, thresholds
0,1e6,1e7,1e8,1e9,1e10,1e11. Frame f ends at128*(f+1) samples. Quality uses
full interior frames f=1 through NS/128-1. Form consecutive groups of48frames
(128ms), discard a remaining incomplete group. Record exact context end times.
Initial baseline is the per-band median of the first8 groups, ending at about
1.026667s. Do not generate activity events in this initialization period.

DC and Nyquist have weight1, interior power bins weight2. Band map is
floor(16*k/129). Monitor group energies are the mean of frame energies.
Centroid is summed weighted-bin power divided by summed power times187.5Hz.
Dominant bin is the mode of valid frame peak bins; ties select lowest index.
Frame peak uses unweighted power, lower-bin tie break. Zero-power groups have
invalid centroid and dominant bin, not fictitious zero-Hz measurements.

A band is active when its group energy is at least4 times its own initial
baseline, its increase is at least1e9 power units, and its share of current
total energy is at least1e-4. Emit one event on the third consecutive active
group. Any inactive group resets persistence, permitting later new events.
This rule detects persistent energy changes; it cannot identify semantic causes.
Retain those raw band alerts. In temporal order, group a new alert into the
nearest existing cluster only if it is in a NEW adjacent band and arrives
within0.256s of that cluster's FIRST alert (the deadline never extends).
Tie-break by earlier cluster creation. A repeated alert in an already present
band remains separate. Otherwise create a new cluster. Store each member's
actual detection time, the first display time, last update and band span.
The cluster is an incremental observation: its first timestamp is an initial
alert, with possible member updates during the following256ms. It is not the
time a final, closed cluster was available; no live notification latency is measured.
Synthetic matching requires the intended band MEMBER's own detection time;
never backdate it to an earlier neighboring band's cluster timestamp.
Clusters are coarse spectral activity, not a count of physical sound sources:
two independent adjacent tones may merge. Report raw and clustered counts.

## Frozen quality criteria and selection

Synthetic controls: all independently specified persistent events must be
detected in clusters containing the correct band by onset+0.512s; no extra clusters, including silence,
steady and brief-transient fixtures. These checks apply even at threshold0.
If the baseline detector fails a control, report the limitation; do not silently
change the rule or choose favorable controls.

Natural clips, separately for every recording: at least99% of nonzero baseline
groups retain a valid dominant bin within one bin; centroid absolute error p95
at most187.5Hz; active-band relative-energy error p95 at most10%, and worst
per-band p95 at most20%. Baseline-active means energy>=max(1e9,1e-4*total).
Thresholded invalid centroids against valid baseline fail. Report every band
and excluded weak-band counts. Additional zero-input activity must be absent.
Compare natural activity clusters to threshold0 by baseline primary band membership and greedy nearest
unused onset within0.256s; report misses/additions and delay, but natural
agreement is not independently labeled detection accuracy.

Choose the highest threshold passing all four calibration clips and all eight
synthetic controls. Freeze choice before processing the four held-out clips.
If none pass, use threshold0 as a nonaccepted fallback and report the failure.
All other thresholds on held-out data remain descriptive, never retuned.
These are exploratory engineering tolerances, not externally approved standards.

## Measurements and comparisons

For each threshold compare identical values in current sparse TSP1 versus
compact dense TSP1:129 unsigned56 powers, no indices, same48-byte header,
FNV checksum and alignment =952 bytes/frame. Sparse bytes are48+8*K,
including protected DC. Include every emitted frame, padding and finite tail
in packet byte counts, even where quality omits startup/tail frames.
Also compare PCM16 (2*NS bytes), tightly packed12 (ceil(12*NS/8)) and a
task-specific telemetry control: the CPU computes and transmits the monitor
outputs only. Last control exposes when sending all spectral bins is unnecessary;
it is not emitted by the unchanged FPGA.
Serialize each task-summary observation in168 bytes: magic/version/valid flags,
context-end sample, dominant-bin uint16 (65535 invalid), active-band bitmap,
float64 total and centroid,16 float64 band means, and64-bit FNV checksum.
This preserves the monitor's own float64 values, not the full spectral input.
Byte counts exclude Ethernet/IP/TCP headers for every format consistently.

Native C++ sparse and dense decode+frame features must match exactly. Common
Python monitor aggregation/event logic runs identically on both and is included
in complete receiver timing. Separately report native decode+features timing.
Practical laptop control: PCM through the same frozen FFT/threshold arithmetic
directly to features and monitor, avoiding IFFT/packet creation not needed by
this application. It is not an optimized FFT-library comparison. An optional
full DSP reference supplies IFFT waveform NRMSE outside timing for fidelity.

Preloaded RAM, three warmups and30 matched measured trials per recording/route
at the frozen threshold, deterministic rotating/reversing order. perf_counter
and process_time; context creation and validation outside timed interval;
returned arrays are materialized inside it. No stage median sums. Include
native-only repeated batches if individual intervals are below timer resolution.
For each recording/route choose a fixed power-of-two batch count from two
untimed warm pilot calls to target at least100ms (maximum256 repetitions).
Use that count for all warmups and measured trials; divide whole batch times
by repetitions. Report actual batch durations and retain zeros in CPU accounting.
Time real work, retain all trials and compare outputs. Cached spectral routes
exclude upstream DSP, board input and transport; cannot establish whole-system
FPGA speedup. No extrapolated multichannel/power/live-latency claims.

## Completion

Retain source/input/native hashes, selection before held-out output, quality,
bytes, timing and English plots. State whether accepted quality and measured
receiver benefit coexist, and whether sending task summaries is a better data
choice. Report a failed application test if criteria fail. Do not conflate
software implementation success with a successful scientific hypothesis.
