# Reference and core verification design

## 1. Scope and authority

This document designs the future verification of the numerical core and its software reference. It records no executed test, simulation, numerical equivalence result, or new hardware measurement. The system-level boundaries are defined in [verification architecture](architecture.md) and [system and interfaces](system_and_interfaces.md); campaigns and release decisions belong to [test catalog](test_catalog.md) and [coverage and signoff](coverage_and_signoff.md).

The baseline is signed 12-bit samples, L=256, H=128, F=15, G=128 and D=384. The [integrated specification](../specs/README.md), [shared configuration](../../spec/generated/core_config.json) and frozen coefficient identities define the intended arithmetic. Implementation behavior is evidence to inspect, not an automatic replacement for that contract. Package names containing `golden` do not qualify the reference model.

## 2. Three complementary oracle roles

| Role | Responsibility | Independence boundary |
| --- | --- | --- |
| Independent integer oracle | Predict windows, transforms, canonicalization, masks, WOLA and metrics using arbitrary-precision integers and explicit rounding/width rules | Derive equations and indexing independently; do not import production arithmetic helpers or copy RTL state machines |
| Production C++ reference | Supply the existing executable interpretation, frame intermediate results and finite-vector artifacts | Qualify against the independent oracle before accepting its outputs as expected data |
| Transaction and protocol oracle | Track acceptance, ownership, ordering, cancellation, backpressure, status and completion | Derive expected events from input/control contracts, not DUT output values or private counters |

The independent oracle should use an absolute-index contribution map for WOLA instead of duplicating the RTL circular RAM. Its transform must preserve the specified radix-2 arithmetic graph and rounding points. A floating-point DFT can support scaling and frequency sanity checks, but cannot decide bit equality for stage-rounded FFT/IFFT results.

At integration level, expected numerical results originate from accepted source samples and captured configuration. Feeding an observed, potentially incorrect DUT FFT result into every later expected stage would hide upstream errors. Local component scoreboards may use observed component inputs for diagnosis; the end-to-end scoreboard remains independent.

## 3. Qualifying the reference and artifacts

Qualification records the specification/configuration revision, source identity, coefficient byte hashes, interpreter/compiler identity and exact input vector identity. Compare the root exported configuration with the reference package configuration. Confirm signedness, width, row count, hexadecimal encoding and final LF on raw coefficient/input files before arithmetic comparison. Hashing a reserialized vector alone cannot establish that original bytes obey the artifact contract.

Use the same frozen coefficient integers for DUT and oracle arithmetic. Independently review coefficient generation and its rounding near half-integer boundaries; sharing frozen tables deliberately removes host-library trigonometry from RTL comparisons, but does not prove the tables themselves are correct. Cover window zero/peak values and twiddle 0, +32768 and -32768 with the required unsigned 16-bit/signed 17-bit representations.

Qualification proceeds through hand-derived primitive cases, exhaustive small primitive domains where meaningful, independent frame comparisons, and finite-stream comparisons. Compare intermediate arrays and statistics, not only final y. The existing [frame API](../../sw/reference_model/src/stft_wola_model.cpp) exposes raw FFT, canonical and masked results for localization.

The batch API accepts one THR2 for the entire run. Dynamic-threshold verification therefore needs a verification-side frame adapter: construct each frame from the accepted stream, supply that frame's captured THR2 to `process_frame_analysis_mask`, and preserve one continuous synthesis state. Repeatedly restarting the batch model per frame loses overlap history.

A discrepancy is unresolved until classified as specification ambiguity, oracle defect, reference defect, RTL defect or unsupported stimulus. Matching two implementations that share helpers is insufficient qualification.

## 4. Transaction identity and ownership

Use the following logical records. These are verification interfaces, not proposed RTL port changes.

| Record | Required identity and content |
| --- | --- |
| Source acceptance | source_epoch, sample_idx, signed sample, acceptance clock |
| Frame admission | source_epoch, frame_idx, trigger_sample_idx, captured THR2, configuration identity |
| Frame item | source_epoch, frame_idx, offset/bin_idx, complex/integer value, last |
| Reconstruction commit | source_epoch, sample_idx, x_delayed, y, error, metric_epoch |
| Output acceptance | source_epoch, sample_idx, y, acceptance clock |
| Cancellation/control | source_epoch, control kind, effective edge, affected in-flight identities |

A driver holds a valid beat unchanged until acceptance. Monitors sample accepted transactions once, with an explicit clocking convention separating pre-edge handshakes from post-edge registered pulses. Inactive payload bits are not required to be zero. Packed-struct valid fields and separate valid ports must follow their documented relationship.

The [core's atomic fork](../../rtl/core/trecap_core_top.sv) admits a sample to both input history and delayed-reference history on the same edge. The scheduler consumes the ring's registered acceptance pulse. Its first request follows H accepted samples, not L.

Capture THR2 at the actual frame-request handshake. The four-entry queue retains `{frame_idx, THR2}` until the last canonical bin is accepted. A post-edge boundary pulse may coexist with a newly committed CSR value; sampling the live threshold after that pulse can assign the wrong value to the previous frame. Cross queue occupancy, simultaneous push/pop and threshold changes while earlier frames remain in flight.

Full clear or source discontinuity begins a new source epoch and cancels owned work. Metric clear creates a metric epoch without resetting sample indices or history. Disable is not a universal pause: transforms have no enable port, while other blocks can reject an interrupted transaction or enter fail-stop.

## 5. Numerical hierarchy and comparison matrix

| Boundary | Exact checks and distinguishing cases |
| --- | --- |
| Rounded shift / saturation | SHIFT 0, 1 and 15; zero; positive/negative half ties and adjacent integers; minimum signed input; clipping limits and one step beyond; independent saturation flags |
| Complex multiply / butterfly | Four full products, sum before rounding, signed 17-bit twiddles, cancellation, zero B, extreme signs; FFT divides each stage by two, IFFT does not |
| Analysis window | Signed 12-bit times unsigned 16-bit, no fractional downshift, signed 27-bit result; coefficient 32768 must remain positive; first/last frame offsets and negative source values |
| FFT / IFFT | Bit-reversed load, eight stages, 1024 butterflies, natural output order and exact components; impulse, constant, alternating, bin-centered/off-bin tones and mixed-sign frames |
| Canonicalizer | Pair averages/differences, odd positive/negative pre-adds, conjugate partner construction, DC/Nyquist imaginary zero; compare overflow/diagnostic behavior separately |
| Magnitude and mask | Unsigned 56-bit Re-squared plus Im-squared; THR2 below/equal/above observed magnitude; threshold zero/max; protected DC, unprotected Nyquist; preliminary versus final mask |
| Spectrum builder | Every full-spectrum bin; decisions for 0..128 reused by mirror 256-k; zero both components when suppressed; no previous-frame mask leakage |
| Synthesis / WOLA | Real IFFT component, unsigned window, round by 15 into 36-bit z, 37-bit OLA addition, emit-before-add and final round by 15 into signed 12-bit |
| Error metrics | Exact `x_delayed - y`; signed 16-bit error, absolute/squared error, max, accepted count, low 64-bit sums and overflow status |

Use [transform microarchitecture](../architecture/transform_microarchitecture.md) for the exact 45/53-bit products, 47/55-bit product sums and 30/38-bit butterfly sums. Bit equality is the default numerical criterion. Quality bounds evaluate reconstruction usefulness separately; THR2=0 does not justify asserting perfect identity because fixed coefficients and intermediate rounding remain.

For any signed 28-bit pair, magnitude-squared is at most 2^55 and fits unsigned 56-bit. Cover the most-negative pair explicitly. Avoid unreachable overflow targets: range proofs and legal frame counts determine which flags can occur in the baseline. A protected bin may have preliminary mask=true and final mask=false. Interior unique bins have weight 2, endpoints weight 1, and protected bins are excluded from eligible totals.

## 6. Finite and continuous WOLA mapping

The [finite-stream contract](../../sw/reference_model/docs/stft_wola_contract.md) defines, for Ns>0:

- `tau_m = (m + 1) * H`.
- Frame item i is `xz[tau_m - L + i]`, with zero extension outside the real input.
- Frame contribution i targets output index `tau_m + G + i`.
- `Nframes = floor((Ns + L - 2) / H)`.
- `tau_last = Nframes * H`; `Ny = tau_last + G + L`.

The L-2 term matters because Qw[0]=0. A generic ceiling-based formula is wrong near specific short-stream boundaries.

| Ns | Nframes | tau_last | Ny |
| ---: | ---: | ---: | ---: |
| 1 | 1 | 128 | 512 |
| 2 | 2 | 256 | 640 |
| 128 | 2 | 256 | 640 |
| 129 | 2 | 256 | 640 |
| 130 | 3 | 384 | 768 |
| 4096 | 33 | 4224 | 4608 |

The [source integration](../../rtl/top/trecap_source_core_integration.sv) separates active input/zero-extension from pure drain. For Ns=4096, the core receives 4224 active sample tokens, followed by 384 WOLA-only drain tokens. Drain must not generate new FFT frames or bin/frame statistics. The C++ batch loop pushes zero extension through Ny; the adapter must compare logical outputs rather than require identical internal push counts.

D is delayed-reference alignment, not a universal assertion that the first 384 y values are zero. Frame 0 can contribute from index 256, and spectral masking can spread energy into the startup-padded portion. Compare startup and tail against the exact oracle, never against a blanket zero/identity assumption.

Continuous tests retain history across observation chunks and keep issuing hop-spaced frames; they do not append a finite tail to every chunk. To compare a live prefix with finite software output, require identical complete input windows and captured THR2 for every frame contributing to each compared output, as well as completed frame processing. A finite reference zero-extends beyond Ns while a live stream can supply additional real samples, so processing completion alone is insufficient. Alternatively, model the same explicit stopping/drain policy.

## 7. Tap timing and metric commit

The [delay/error block](../../rtl/core/trecap_delay_error_metrics.sv) distinguishes y-request acceptance, internal metric/output commit, and downstream output acceptance. A commit can fill a holding register before the sink accepts that y sample. Compare metric changes and sample taps at commit; compare the public y stream at its own handshake. Maintain separate ledgers and require one eventual public acceptance per non-cancelled commit.

Unique-bin taps occur only on accepted mask-stage outputs and terminate at bin 128. Full-spectrum last is bin 255. Frame-stat taps are another event stream; they are not interchangeable with either last marker. Observers have no ready return and must capture every valid tap.

In the delay/error owner, metric clear blocks new y requests and commits while preserving pending data/history. An already committed output can still be accepted during clear without being counted again. A pre-clear pending request can commit into the new metric epoch afterward. Generic sticky clear does not release alignment fail-stop or erase metric-truncation history.

The MAG2/mask owner needs a separate clear policy. Its input ready is not gated by metric clear, and accepted-bin updates later in the clocked process can overwrite accumulator clears using pre-edge values. Frame tracking survives clear. Do not apply the delay/error epoch model to every spectral accumulator. Direct CORE clear injection and SOURCE integration's qualified applied-clear pulse are distinct scenarios. Resolve clear-versus-bin precedence and frame-owned statistic semantics through O-05 in [decisions and open items](decisions_and_open_items.md) before assigning a universal expected result.

## 8. Positive and fault partitions

Separate legal numerical campaigns from interface-abuse and out-of-domain campaigns. The [C++ arithmetic contract](../../sw/reference_model/docs/arithmetic_contract.md) rejects many internal overflows, while RTL contains saturating operators and diagnostic flags. Do not silently teach the reference to reproduce RTL saturation or dismiss every divergence as a reference limitation. Document the qualified no-internal-overflow domain; use independent width/flag expectations for explicit robustness cases.

Malformed offset, frame identity, missing/duplicate last and discontinuity tests require a per-block response matrix. Canonicalizer and WOLA can fail-stop; other stages can flag and continue. Do not apply one generic recovery expectation to all modules. Nonzero IFFT imaginary residual is diagnostic in WOLA while real synthesis continues; universal imaginary-zero assertions are invalid. Canonical conjugacy checks must also distinguish saturation cases.

## 9. Assertions, coverage and completion

Assertions should establish stable stalled outputs, exact admission conservation, ordered frame/bin identities, no RAM read before ownership, distinct butterfly write addresses, no empty-history read, and no stale response after cancellation. Payload RAM is intentionally unreset; the environment must not initialize it to zero and conceal ownership defects. Full history does not borrow same-cycle pop credit for x admission.

Cover first/last beats, ring wraps at 512/1024, OLA phases 0/128/256, short-stream residues around 1/2, mixed masks, threshold equality, and clear while load/compute/output/drain is active. Cross stalls with frame boundaries, last outputs and pending RAM responses. Use bounded formal or explicitly identified state-boundary unit scenarios for 64-bit counter overflow; billions of ordinary frames are not a useful coverage strategy. Exclude unreachable bins only with a recorded argument.

Keep safety independent of fairness. Local 7936-clock transform service and the connected 18000-clock allocation require their documented availability/readiness assumptions. Arbitrary external stalls do not permit an unconditional timeout assertion. WOLA initialization requires 384 clear-free scrub clocks, including while processing is disabled.

A finite positive case passes only when every expected output/tap/statistic is matched, all exact counts agree, final public y acceptance and drain completion occur, no unexpected status appears, and no residual/extra transaction remains. Reset-aborted work is recorded as cancelled, never silently discarded to empty the scoreboard.

Qualify the checkers themselves with deliberately corrupted expected/observed transcripts: duplicate or missing output, wrong frame threshold, swapped bins, altered tie rounding, missing tail, premature done and forbidden status. Each targeted checker must reject its fault and accept the corresponding unmodified case. Store seeds, artifact/source identities, assumptions, mismatches and coverage evidence so a later pass is reproducible and its limits are visible.
