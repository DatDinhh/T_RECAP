# Golden selfcheck

This directory contains source-controlled expectations for the fast smoke selfcheck of the T-RECAP golden-model repository.

It is not an artifact-output directory. It does not replace `artifacts/`, and it does not contain hand-written coefficient tables, input streams, golden outputs, metrics, or release hashes.

## Files

- `smoke_suite_expected_manifest.json` is a reviewed expectation file for the `configs/suites/smoke.json` workflow.
- It records the expected smoke vector names, classes, frame counts, output lengths, row counts, fixed baseline constants, and required workflow gates.
- It deliberately does not record generated hashes. Frozen hashes belong in generated artifacts under `artifacts/` after the coefficient/vector/golden/release flow runs.

## Intended use

The selfcheck manifest is consumed by scripts such as:

```bash
scripts/check_reproducible.sh --quick
scripts/regenerate_all.sh --suite configs/suites/smoke.json --release-config configs/releases/phase2_revJ_dev.json
```

The expected policy is:

1. Reviewed configs live under `configs/`.
2. Generated/frozen artifacts live under `artifacts/`.
3. This directory only stores source-controlled smoke expectations used to detect accidental suite drift.

## What this directory must not contain

Do not place these here:

- `window_qw.memh` or twiddle ROM data;
- `x_in.memh` or `y_out.memh`;
- `metrics.json`, `frame_stats.csv`, or `bin_stats.csv`;
- `artifact_index.json` or `frozen_release_manifest.json`;
- telemetry captures.

Those are generated or captured outputs and belong in the artifact tree defined by the spec.
