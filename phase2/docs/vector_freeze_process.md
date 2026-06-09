# Vector Freeze Process

## Purpose

This document defines how test vectors become frozen signoff artifacts. A vector is not a signoff vector because it has a useful name or because it was generated once. It becomes a signoff vector only when its generator configuration, stream hash, golden output hash, and manifest entries are frozen.

## Key rule

After freeze:

```text
x_in.memh + x_in_sha256 = input authority
y_out.memh + y_out_sha256 = expected-output authority
```

Generator equations remain traceability. The hashes are the authority.

## Required vector classes

The signoff suite must cover these vector classes:

| Class | Purpose |
|---|---|
| zero input | confirms zero-extension, windowing, FFT/IFFT, WOLA, and output rounding do not create nonzero samples |
| no suppression, `THR2 = 0` | confirms eligible masks are zero and establishes near-lossless baseline error |
| impulse and step | exercises startup, flush, delay `D`, and WOLA alignment |
| exact-bin tone sweep | verifies dominant-bin placement and expected window-shaped spread |
| off-bin tone sweep | exercises leakage behavior under periodic square-root Hann |
| near-threshold multitone | verifies full-precision unsigned threshold decisions and Hermitian consistency |
| noise-only stream | characterizes suppression ratio, kept-energy ratio, and error under low-value content |
| high-amplitude headroom | confirms no internal wraparound on frozen width schedule |
| short finite stream | forces startup, flush, and full-tail scoring |
| rectangular-window diagnostic | optional debug-only exact one-bin sinusoid test |

## Source configuration

Reviewed vector configs live under:

```text
configs/vectors/
```

Each vector config should define:

```text
name
Ns
generator
parameters
THR2
PROTECT_DC
PROTECT_NYQ
tail_policy
rounding
debug_artifacts policy
```

The generator config is human-reviewed input. The frozen manifest under `artifacts/test_vectors/test_vectors.json` is the signoff index.

## Generator names

Baseline generator names should match the spec:

```text
constant
impulse
step
sine
cosine
exact_bin_sine
exact_bin_cosine
multitone_sine_sum
uniform_noise_xorshift32
```

Do not invent a new generator behavior under an old name. If behavior changes, create a new generator name or update the generator version and regenerate intentionally.

## Exact frequency and phase representation

Frequency must be represented exactly as rational fields:

```json
{
  "f_num": 23,
  "f_den": 256
}
```

Do not use legacy strings such as:

```json
{ "frequency": "23/256" }
```

Phase values use decimal strings:

```json
{ "phase_rad": "0.5" }
```

The generator implementation must parse these deterministically. For sine, cosine, and multitone vectors, the frozen generator implementation is identified by `generator_version` and `generator_source_sha256`.

## Freeze states

Use these states in manifests and reviews:

| State | Meaning |
|---|---|
| `draft` | config exists but stream hash is not frozen |
| `x_frozen` | `x_in.memh` and `x_in_sha256` are frozen |
| `golden_frozen` | `y_out.memh`, `metrics.json`, `frame_stats.csv`, and hashes are frozen |
| `release_frozen` | vector is included in a frozen release manifest |
| `deprecated` | vector retained for history but not part of active signoff |

## Freeze workflow

### 1. Add or modify reviewed config

Create or edit:

```text
configs/vectors/<vector_name>.json
```

Review for:

- deterministic generator;
- legal `Ns > 0`;
- legal `THR2` range;
- correct protection flags;
- `tail_policy = full_tail` for signoff unless explicitly diagnostic;
- no binary-floating generator parameters;
- optional `bin_stats.csv` policy.

### 2. Generate input stream

Run:

```bash
make vectors
```

Expected output:

```text
artifacts/test_vectors/test_vectors.json
artifacts/test_vectors/<vector_name>/x_in.memh
artifacts/test_vectors/<vector_name>/config.json
```

### 3. Canonicalize and hash

Run:

```bash
make check-artifacts
```

At this stage `y_out_sha256` may be absent if the golden model has not yet run, but `x_in_sha256` must be present for frozen inputs.

### 4. Run golden model

Run:

```bash
make golden
```

Expected output:

```text
artifacts/golden/<vector_name>/y_out.memh
artifacts/golden/<vector_name>/frame_stats.csv
artifacts/golden/<vector_name>/metrics.json
artifacts/golden/<vector_name>/bin_stats.csv    # if enabled
```

### 5. Re-check artifacts

Run:

```bash
make check-artifacts
```

The checker must validate:

- `x_in_sha256`;
- `y_out_sha256`;
- coefficient hashes;
- row counts;
- CSV header contracts;
- JSON schemas;
- wide integer string rules;
- `THR2=0` mask invariant for eligible bins.

### 6. Freeze into manifest

Run:

```bash
make freeze-release
```

The release manifest records the vector names, artifact paths, hashes, schema versions, generator version, and golden-model version.

## Updating a frozen vector

Do not silently overwrite a frozen vector. A change to any of these fields invalidates the old vector hash:

- generator name;
- generator parameters;
- `Ns`;
- seed;
- threshold;
- protection flags;
- rounding mode;
- tail policy;
- arithmetic contract;
- coefficient artifacts.

Recommended update process:

1. create a new vector name if the old one is still useful;
2. regenerate input and golden artifacts;
3. compare old/new manifests;
4. explain the reason in `CHANGELOG.md`;
5. update quality bounds if no-suppression behavior changed;
6. freeze a new release.

## Naming convention

Use names that encode the important signoff knobs.

Good:

```text
zero_Ns4096_thr0
no_suppression_multitone_Ns4096_thr0
impulse_step_Ns1024_thr0
exact_bin_tone_sweep_Ns4096_thr0
off_bin_tone_sweep_Ns4096_thr_raw64
near_threshold_multitone_Ns4096_thr_custom
noise_xorshift32_seed1_B12_Ns4096_thr_custom
high_amplitude_headroom_Ns4096_thr0
short_finite_stream_Ns17_thr0
```

Bad:

```text
test1
newtone
final_vector
paul_debug
```

Names should be stable enough to appear in release manifests and bug reports.

## Manifest review checklist

Before a vector is accepted:

- [ ] `name` is unique and stable;
- [ ] `Ns > 0`;
- [ ] `tail_policy` is explicit;
- [ ] generator parameters are deterministic;
- [ ] sine/cosine frequencies use `f_num` and `f_den`;
- [ ] phase values are decimal strings;
- [ ] noise seed is nonzero;
- [ ] noise bit width `B` is between 1 and 32;
- [ ] `THR2` is a decimal string if wide;
- [ ] protection flags are present;
- [ ] `x_in_sha256` matches canonical stream;
- [ ] after golden run, `y_out_sha256` matches canonical output;
- [ ] artifact row counts match formulas;
- [ ] quality bounds exist for no-suppression vectors after quality freeze.

## Relationship to quality bounds

Vector freeze defines the input and expected output. Quality-bound freeze defines acceptable no-suppression quality limits produced by the golden model.

Do not mix the two concepts:

- vector freeze answers: "What exact stream and expected output are authoritative?"
- quality-bound freeze answers: "Does the golden model's no-suppression reconstruction quality remain within the accepted limit?"

