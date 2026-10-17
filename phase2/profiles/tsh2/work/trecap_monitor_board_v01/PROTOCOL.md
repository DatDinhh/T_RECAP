# Physical DE1-SoC spectral monitor validation

Registered before new board captures. This experiment moves the completed
revision02 consumer test to the unchanged, previously qualified TSH2 FPGA image.
There is no RTL change, no threshold reselection, no new machine learning model,
and no claim that these machine sounds diagnose faults.

## Frozen cases and finite transaction

Use all four prior revision02 held-out natural recordings and all eight prior
synthetic controls, with their stored signed12 samples unchanged. The cases
are now a hardware replication set, not a new unseen application test. Run
threshold0 and the already selected threshold1e7 for each, in sparse mode,
twice per case:24 configurations,48 physical epochs. Retain every attempt,
including failures. The repetitions establish exact repeatability, not an
independent sample size or a hardware performance benchmark.

TSH2 accepts exactly384000 samples at48k per finite transaction. Append zeros
after each original240000-sample natural or245760-sample synthetic recording
to satisfy this fixed8s geometry. Do not concatenate clips, alter the original
samples, change amplitude, or recompile RTL. Record the padding separately.
The added silence is an interface accommodation, not scientific source audio.

For each epoch the qualified finite TCP service receives a16-byte request
header (magic, threshold, PCM byte count), followed only by384000 little-endian
signed int32 PCM values restricted to[-2048,2047]. The client shuts down its
write side after the exact PCM payload. Gold waveform, spectra, features,
and expected events stay on the PC. The existing HPS driver feeds
the actual FPGA via MMIO and drains both IFFT/WOLA and spectral outputs. The
golden reference is never executed on the board in place of the FPGA.

## Admission and exact checks

Use only TSH2 source identity
39db0fdf3d451dfbf2d878575725cedd3df450980b40b2a742620dfb76a1a8ed
and the preserved SOF whose SHA256 is
f96bc5a35adf08711a5f392baf9f8cbf5ec65a17211a58117bdb53f62acbb7ab.
Bind the unchanged finite TCP service ARM binary and its qualification, included
host02 controller source, build registration, coefficients,
prior revision02 calibration/quality/code, and all source/derived data hashes.
Current hardware boot, source ID, bridge state and safety admission must be
verified by the root operator before MMIO; historical receipts do not admit
the current board. All deployment and capture happens in temporary RAM paths.

Validate each complete physical epoch:384000 accepted inputs,384512 signed12
waveform samples,3001 strict TSP1 frames, monotonic expected epoch, zero drops,
zero faults, matching source and boot. Match every waveform sample and packet
byte to the PC-only8s fixed-point gold. Match both repetitions exactly.
Strict decode validates frame order, threshold, count, payload and checksum.

Before hardware execution, the padded8s gold must reproduce the saved original
feature, spectrum, packet and consumer prefix exactly. The original finite
waveform including its tail must also match the corresponding8s prefix. At
threshold0 the delay-aligned complete8s waveform must equal its input exactly.

## Application analysis and bytes

Apply the unchanged revision02 monitor only to the original source support:
first original_NS/128+1 frames, with original_NS supplied to its grouping
function. Preserve its startup/tail omissions,48-frame groups, clustering,
quality tolerances and independently specified synthetic event targets.
Compare physical threshold1e7 with physical threshold0 and with the frozen
software result. Natural agreement is a replication of prior engineering
tolerances; it is not labeled fault recognition. Report all eight controls,
their five intended persistent additions/switches, misses and extra clusters.

Report two distinct byte scopes. Full transaction bytes include all3001
physical frames, added silence, finite tail and metadata. Original-support
prefix bytes cover the1876 natural or1921 synthetic frames and are the
like-for-like comparison to the previous5s/5.12s software result. Never present
the full8s padded saving as the5s natural-data saving. Compact dense control
costs952 bytes per frame at the same threshold and preserves identical powers;
it is a host-generated comparator, not an additional physical capture.
Also retain PCM16, packed12 and task-summary controls with matching durations.

## Timing boundaries

Physical client fabric cycles include HPS input starvation and output draining;
they are not pure FFT/threshold/IFFT compute latency. Board roundtrip time
includes host/network/setup and must never be substituted for compute time.
The primary new result is physical correctness plus application behavior.

After all board activity finishes, the laptop may repeat the prior receiver
benchmark using actual physical spectral prefixes:3 warmups and30 matched
trials for sparse decode+monitor, generated compact-dense decode+monitor and
CPU PCM-to-features+monitor. Inputs are preloaded; allocations and returned
copies within called routines count; context setup and checking are untimed.
Use the same prior batching and deterministic ordering, verify all outputs.
Cached receiver paths exclude producer/transport and cannot establish complete
FPGA system speedup. Do not infer power savings, live microphone behavior,
machine diagnosis, AI improvement or continuous24/7 operation.

## Deliverables

Preserve protocol, PC-only fixtures, admission/deployment/capture receipts,
hashes, every failed attempt, complete raw physical wire/waveform output,
validation, natural/control quality tables and English plots. Explicitly
distinguish actual FPGA captures, software gold and host-generated dense data.
