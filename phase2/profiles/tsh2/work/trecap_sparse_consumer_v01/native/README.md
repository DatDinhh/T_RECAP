# Native feasibility benchmark

This standalone host tool implements the adjacent frozen `CONTRACT.md`.
It does not access the DE1-SoC or change the original project.

Build on Windows with the installed Visual Studio 2022 C++ toolchain:

```powershell
cmake -S work/trecap_sparse_consumer_v01/native -B work/trecap_sparse_consumer_v01/native/build -G "Visual Studio 17 2022" -A x64
cmake --build work/trecap_sparse_consumer_v01/native/build --config Release
work/trecap_sparse_consumer_v01/native/build/Release/trecap_sparse_benchmark.exe --self-test
work/trecap_sparse_consumer_v01/native/build/Release/trecap_sparse_benchmark.exe --cases outputs/trecap_sparse_consumer_v01/fixtures01/cases.tsv --validate-only
work/trecap_sparse_consumer_v01/native/build/Release/trecap_sparse_benchmark.exe --cases outputs/trecap_sparse_consumer_v01/fixtures01/cases.tsv --out outputs/trecap_sparse_consumer_v01/benchmark01
```

Use a fresh output directory. The tool validates all fixtures before creating
outputs. A failed or interrupted benchmark may leave partial raw files and an
incomplete summary, but will not write `qualification.json` with PASS.

## Measurement stages

* `encode`: start from common canonical magnitudes and mask flags, prepare the
  masked dense array or scan/gather retained sparse entries, serialize the record
  and compute its FNV checksum.
* `decode`: validate and decode a preprepared packet, including metadata,
  exact size, integrity, ordering, protection and threshold constraints.
* `consumer`: compute 16 energy features from predecoded values/entries.
* `receive_consumer`: decode/validate the preprepared packet, then consume it.
* `complete`: prepare, encode, decode/validate and consume.

One common calibrated repeat count is used for all stages and both modes per
case. B and C are measured in alternating order for three warmups and30 measured
paired trials. Threshold0 B is also the unmasked A baseline, avoiding redundant
copies of the same baseline measurement. These are single-thread monotonic wall
elapsed times on this host, not CPU utilization or energy. There is no transport
or FFT/IFFT inside the intervals. Buffers are allocated and faulted in beforehand.

`observer.cpp` is a separate translation unit and LTO is disabled. Every timed
frame calls its opaque observer on real output memory, so callers must materialize
the results. This small observer cost is included in both representations.
Outside every timed trial, all frames from the final repetition are checked.
Intermediate repetitions are observed but are not individually fully compared.
Encode checks exact packet bytes; decode checks all values/indices and features;
consumer-containing stages check all16 independently expected integer features.

Canonical fixture admission validates unsigned56 magnitude range, complete ordered
frames, threshold/mask semantics, protection, and independent expected features.
Encoder numeric inputs are trusted after this admission; decoder byte input is
untrusted and fully checked. Sparse encoder also checks entry count before writing.
The fixed unsigned64 feature bounds follow directly from unsigned56 magnitudes:
total weighted energy is at most256*(2^56-1), which fits unsigned64.

## Outputs

`raw_trials.csv`: one row per trial, stage and B/C mode, retaining raw duration,
repeat and frame counts, bytes per pass and stable expected packet/feature hashes.
Warmups have trial IDs -3..-1; measured trials0..29.

`summary.json`: per-case byte counts and per-stage/mode median, quartiles and p95
nanoseconds per frame. These percentiles describe30 trial means, not individual
frame latency tails. No quality-acceptance budget is imposed by this tool.

`qualification.json`: machine/compiler/timer information, exact boundaries,
successful check counts and file FNV checksums. FNV is corruption detection,
not a cryptographic signature.

`packets/<case_id>_{dense,sparse}.bin`: all prequalified serialized records in frame
order, exported before timing for independent wire-format audit. Lengths are
recoverable from each header's payload length and the8-byte alignment rule.

Self-tests cover independent zero-frame golden checksums, extreme magnitudes,
threshold/protection/weight/band boundaries, corrupt/truncated/padded records,
metadata/count/flags mismatches, unordered/out-of-range/duplicate sparse indices,
missing protected DC, below-threshold entries and zero-threshold missing bins.
The current suite has8 positive scenarios and27 rejection scenarios. Fixture
validation additionally checks every frame of all56 frozen cases. The dense
implementation uses vectorization-friendly contiguous loops; this does not by
itself assert that every loop received SIMD code generation.
