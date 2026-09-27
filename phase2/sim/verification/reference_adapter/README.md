# Bounded reference qualification adapter

This executable observes public C++ reference APIs. It does not contain expected
values and is not a replacement reference model. The independent Python oracle
uses a recursive radix-2 decomposition and an absolute-index WOLA contribution
map; the production reference uses iterative transforms and circular buffers.
Both intentionally consume the same frozen integer coefficient files.

Run from the repository root:

```powershell
python scripts/verification/reference_qualification.py
```

CMake and a C++20 compiler must be available. `--generator`, `--build-dir` and
`--run-dir` provide explicit control. Build output is restricted to
`build/verification/`; evidence is restricted to a new directory under
`runs/verification/`. The driver always configures/builds the adapter and records
its executable hash. Existing build directories may be reused through CMake;
existing evidence directories are rejected.

The campaign currently checks:

- Eight selected existing C++ self-tests as supplementary evidence.
- Independent rounding and saturation cases, including signed integer extrema
  for shifts 0, 1, 2 and 15; coefficient endpoint/axis anchors.
- Hand-derived zero, impulse, DC, Nyquist and complex quarter-rate transforms,
  plus fixed reproducible mixed-sign transform operands.
- Canonical pair rounding, DC/Nyquist handling, mask equality, protection and
  maximum legal threshold.
- Both selected nonzero frozen vectors: `impulse_Ns1024_thr0` and
  `near_threshold_multitone_Ns1024_thr64` (the latter's actual THR2 is 4096).
- Exact output samples, every frame/bin statistic, ten integer aggregate metrics,
  and every analysis/FFT/canonical/masked/IFFT/synthesis-window intermediate word.
- Deliberately corrupt records and malformed transcripts to qualify the comparison
  and transcript parser's rejection paths.

The selected files under `artifacts/` remain read-only. Fresh expectation bundles
are written under each run's `<vector>/oracle/`. Their CSV and MEMH layouts match
the existing stream artifacts. The run-local metrics JSON uses the explicit
`trecap_reference_qualification_numeric_metrics_v1` schema, not the frozen
artifact schema. Its three numeric groups retain the existing field names. The
run-local `trecap_artifact_expectations_pkg.sv` exports the TEXP constants needed
by a core scoreboard, including independent full bin expectations for impulse,
whose historical frozen output set has no bin CSV. `ifft_output.csv` contains
`frame_idx,offset,re,im` for every accepted complex IFFT output expected at the
WOLA boundary (256 rows per frame); both components must compare exactly. The
export is round-trip checked. Each vector report pins all six emitted files in
`oracle_artifact_sha256`, including the generated TEXP package; a downstream
runner must validate that complete map before consuming the bundle. The report
also pins the qualification sources and `input_identities.json`. It does
not authorize a blanket allowance for imaginary residuals. A bundle is a candidate until
its parent run report records the applicable passing comparison and unchanged
input identities.

`report.json` and `SUMMARY.md` separate the bounded baseline status from broader
public-API findings. A baseline, build, parser or checker failure returns a
nonzero exit code. The public rounded-shift API is also probed at shift 63;
findings outside the qualified baseline shift set remain visible even when the
bounded baseline campaign returns zero. Therefore exit zero never means that
all public API inputs or all V1 requirements are qualified. The JSON explicitly
keeps `all_V1_qualified` false.

This campaign does not execute RTL, qualify dynamic thresholds or reset/metric
epochs, prove coefficient transcendental generation, admit the complete normative
vector suite, accept quality bounds, or establish board/electrical results. The
source and frozen-input hashes are rechecked at completion. Per-run stdout,
stderr, partial failures and the input inventory are retained; reruns do not
overwrite earlier failed evidence.