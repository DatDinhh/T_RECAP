# C0 exact artifact scoreboard v68

> Historical revision record. Do not use the v68 runner or its old provenance
> conclusions for the current tree. v69 replaced the import/release integrity
> layer, and v70b retains that repair plus the current AC9-AC12 scoreboard. Use
> `scripts/windows/run_c0_golden_v70.ps1` and
> `docs/bringup/reference_import_hash_chain_v69.md`.

## Purpose

This revision adds a fail-closed RTL regression for the Revision-J acceptance
artifacts:

```text
y_out.memh
frame_stats.csv
metrics.json
bin_stats.csv
```

The test exercises the complete C0 path:

```text
BRAM replay -> input ring -> scheduler -> analysis -> FFT -> mask
            -> IFFT -> WOLA tail drain -> public y stream
```

It builds on the v65 flow-control fix, the v66 active-frame/tail split, and the
v67 exact-completion contract.

## Supported frozen case

v68 supports one case:

```text
near_threshold_multitone_Ns1024_thr64
```

Its frozen geometry is:

```text
Ns          = 1024
Ny          = 1536
Nframes     = 9
unique bins = 129 per frame
bin rows    = 1161
THR2        = 4096
```

The `thr64` suffix is a historical amplitude-threshold name. It must not be
interpreted as the raw `THR2` input. The preflight reads `THR2=4096` from
`config.json`.

The other two frozen smoke vectors do not contain `bin_stats.csv`, so they are
not silently treated as four-artifact passes.

## Observation API added for AC12 and metrics

The former public unique-bin tap did not expose all fields in
`bin_stats.csv`. v68 propagates these valid-only diagnostic signals through
the core-only and BRAM-replay tops:

```systemverilog
tap_bin_re_o
tap_bin_im_o
tap_bin_pre_mask_o
```

It also corrects the unique-stream last marker. Full-spectrum `last` occurs at
bin 255, while the artifact tap ends at unique bin 128; combining the old two
conditions could never assert.

The following core metric observations are also exposed:

```systemverilog
core_error_sample_count_o
core_sum_abs_err_lo_o
core_sum_sq_err_lo_o
core_max_abs_err_o
core_metric_overflow_sticky_o
```

These are diagnostic outputs only. They do not return ready or otherwise
change core flow control.

## Preflight contract

Before any RTL is compiled,
`scripts/sim/trecap_artifact_scoreboard.py prepare` checks:

- strict JSON parsing with duplicate keys rejected;
- non-finite JSON constants (`NaN` and infinities) rejected;
- canonical ASCII/LF formatting, final LF, headers, and exact row counts;
- exactly three lowercase hexadecimal digits per 12-bit MEMH row;
- all promoted-root hashes and sizes in the normalized reference-import
  manifest;
- strict coefficient MEMH width, row, LF, manifest, and SHA-256 contracts;
- artifact hashes declared by the imported vector index;
- `config.json` consistency with the configuration, widths, and contracts in
  `metrics.json`;
- finite-stream geometry and exact frame/bin ordering;
- `mag2 = real^2 + imag^2`;
- strict `pre_mask = (mag2 < THR2)`;
- DC/Nyquist protection and final mask semantics;
- bin-to-frame and frame-to-metrics aggregate equality;
- independently recomputed time-domain metrics from frozen `x` and `y`.

The tool emits a typed SystemVerilog expectation package under `runs/`.
Expected wide decimal metrics therefore never pass through a simulator JSON
parser or a floating-point conversion. It also emits a complete source
snapshot covering the case artifacts, coefficients/manifests, generated
configuration/packages, compile filelists, RTL inputs, testbenches, and
runner/tool. The runner revalidates that snapshot immediately before
simulation and again during the post-check, so neither the reference inputs
nor the compiled source set can change silently between preflight and
comparison.

The dependency-free self-test also proves that the comparator rejects:

```text
a stale or modified preflight snapshot
an extra y row
an extra frame row
a corrupted bin/pre-mask row
corrupted observed RTL metrics
a duplicate JSON key
a non-finite JSON numeric constant
```

## Live RTL comparisons

### Output stream

The scoreboard advances only on:

```systemverilog
y_valid_o && y_ready_i
```

For every accepted row it requires the continuous sample index and exact
12-bit value from `y_out.memh`. It also checks that valid, data, and index stay
stable during backpressure.

### Frame statistics

Each `tap_frame_o.valid` pulse is compared in order with one CSV row:

```text
frame_idx
unique_bins
unique_suppressed_bins
eligible_unique_bins
eligible_suppressed_bins
eligible_kept_mag2
eligible_total_mag2
```

`mag2_truncated` and all overflow/protocol/saturation flags must remain clear.

### Unique-bin statistics

Each `tap_bin_valid_o` event is compared in order with:

```text
frame_idx,bin_idx,real,imag,mag2,eligible,pre_mask,mask
```

The scoreboard separately recomputes magnitude-squared, the strict threshold
decision, protection behavior, and the one-or-two-sided spectral weight.

### Metrics and completion

The scoreboard uses 128-bit independent accumulators for frame/bin spectral
totals and time-domain error totals. At the single registered completion
pulse, it requires:

```text
1536 accepted y rows
9 frame rows
1161 bin rows
1536 time-error samples
all metrics equal to metrics.json
the internal RTL metric outputs equal to the independent totals
all sticky error flags clear
```

The test applies deterministic output backpressure and holds the final output
for 37 clocks. It then watches 32 post-completion clocks and rejects any extra
sample, frame, bin, or done pulse.

## Independent post-check

The RTL scoreboard writes canonical capture files to:

```text
runs/c0-artifact-scoreboard-v68/capture/
```

After simulation, the Python `compare` step:

- revalidates the exact preflight package and complete source hash snapshot;
- reparses the captures under the same strict schema;
- byte-compares `y_out.memh`, `frame_stats.csv`, and `bin_stats.csv`;
- field-compares observed runtime metrics and status;
- rejects missing, extra, reordered, reformatted, or corrupted content.

This second layer prevents a testbench that merely prints a PASS sentinel from
being accepted.

## Current superseding run

The historical v68 runner is no longer shipped. Run the current v70b superset:

```powershell
Set-ExecutionPolicy -Scope Process Bypass -Force
& ".\scripts\windows\run_c0_golden_v70.ps1" `
  -Repo (Resolve-Path ".").Path `
  -ModelSimExe "D:\Quartus\modelsim_ase\win32aloem\modelsim.exe"
```

The runner first executes the v65-v67 regressions, then this artifact test. It
requires:

```text
C0_FLOW_CONTROL_PASS
WOLA_TAIL_DRAIN_PASS
C0_EXACT_COMPLETION_PASS
C0_ACTIVE_TAIL_PASS
C0_ARTIFACT_SNAPSHOT_PASS
C0_ARTIFACT_RTL_PASS
C0_ARTIFACT_POSTCHECK_PASS
C0_GOLDEN_SUITE_PASS vectors=1
```

Compile success without all sentinels is not a pass.

## Evidence and limitations at the time of v68

The Python scoreboard requires Python 3.10 or newer. The source package can be
checked without Intel tools using:

```bash
python3 scripts/sim/trecap_artifact_scoreboard.py self-test --repo .
python3 scripts/lint_repo_layout.py
python3 scripts/gen_filelists.py --check
```

Native ModelSim or Questa execution is still required before claiming an RTL
artifact match.

The provenance checks pin the normalized import manifest and its recorded
reference-source ZIP, so this regression proves equality to the current
imported smoke artifacts. The older outer `frozen_release_manifest.json`
still has the previously documented CRLF hashes and stale
`artifacts/golden/...` paths. Therefore a passing v68 run is not, by itself,
an official derivative-release or Phase-2 signoff claim.

`scripts/check_generated.py` additionally needs the optional `jsonschema`
package. In an environment without it, the pre-existing generator writes an
environment-dependent warning into `gen_manifest.json` and reports
warning-only manifest drift. The v68 preflight still verifies every committed
generated source/output hash, but that generator determinism debt remains a
separate fix.

The current frozen case has zero time-domain error. It checks event count,
delay alignment, error arithmetic, and equality of the RTL and independent
accumulators, but it does not meaningfully stress nonzero absolute-error,
squared-error, maximum-error, or near-overflow accumulation. A later frozen
vector with nonzero errors remains necessary for full metrics-arithmetic
coverage.

There is also no bin with `mag2 == THR2`, and every `pre_mask=1` bin in this
case is eligible. Therefore an exact threshold-equality row and a protected
bin whose pre-mask decision is overridden by protection remain directed
coverage gaps. Only one frozen vector currently supplies a full per-bin FFT
oracle.
