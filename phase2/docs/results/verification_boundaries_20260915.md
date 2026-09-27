# Short-length and finite-tail verification

Date: 2026-09-15. **All 80 selected boundary-core cases passed.** The four
previous baseline cases also passed with the expanded harness. No additional
production RTL defect was found in this campaign, and no production RTL or
frozen artifact was changed.

The [public result JSON](verification_boundaries_20260915.json) records every
selected case, configuration, exact count, capture hash and source identity.
This extends the [first campaign](verification_baseline_20260915.md); it does not
establish complete verification, board operation or energy savings.

## Executed matrix

Twenty positive input lengths each ran with raw THR2=0 and
THR2=8796093022208 (2^43). Each length/threshold pair ran with an always-ready
sink and with deterministic backpressure, giving 20 x 2 x 2 = 80 positive cases.
The native ModelSim environment and independent Python/C++ reference machinery
were reused with their qualified executable and source identities checked.

| Selected Ns | Frames per case | Active tokens per case | Outputs per case |
| --- | ---: | ---: | ---: |
| 1 | 1 | 128 | 512 |
| 2, 126, 127, 128, 129 | 2 | 256 | 640 |
| 130, 254, 255, 256, 257 | 3 | 384 | 768 |
| 258, 383, 384, 385 | 4 | 512 | 896 |
| 386, 511, 512, 513 | 5 | 640 | 1024 |
| 514 | 6 | 768 | 1152 |

The finite-stream specification defines frames=floor((Ns+254)/128), active
length=128*frames, and Ny=active length+384. The formula follows the nonzero
window support; the first window coefficient is zero. Frame-count changes
therefore occur at Ns=2,130,258,386,514. Testing only H+1 or L+1 would miss the
transition to the next frame.

Analysis zero extension is active length minus Ns, ranging from 127 to 254
samples in this matrix. The pure WOLA drain remains 384 samples. For example,
Ns=130 needs 130 input samples, 254 analysis zero-extension tokens and 384 drain
tokens, producing 768 outputs. Truncating to Ns+D would incorrectly discard
part of the required tail.

## Numerical and lifecycle results

| Check | Executed result |
| --- | --- |
| Supplemental reference qualification | 40/40 cases matched independent Python and public C++ results |
| Reference observation scope | 32768 outputs, 136 frames, 17544 bins, 34816 complex IFFT samples, six intermediate boundaries and ten aggregate metrics per vector |
| Native boundary replay | 80/80 positive cases passed |
| Native exact comparison totals | 65536 outputs, 272 frames, 35088 bins and 69632 complex IFFT samples |
| Final-output backpressure | All 40 stalled cases held the final output for 37 cycles; completion waited for acceptance |
| Completion | One accepted start and one done pulse per case; 1024 quiet cycles after completion |
| Baseline regression | Four original positive cases passed; the original wrong-y witness was rejected |
| Native checker qualification | Four supplemental wrong-y witnesses were rejected by the intended sample-value checker |
| Runner admission qualification | 31 tests passed |
| Capture-checker qualification | 49 tests passed on each of three real corpora: original impulse, Ns=1 and Ns=130 |

All source, oracle, input and staged ROM identities remained unchanged during
the final native runs. Compilation retained 369 existing warnings per vector
and no errors. Positive simulations had no error/fatal diagnostics. Functional
simulation kept production assertions enabled and did not define SYNTHESIS.

## What the new stimulus exercises

All lengths use a common deterministic prefix containing signed 12-bit extrema,
neighboring values, small signed values and integer-generated transitions. The
two thresholds use identical input bytes for each length. These are supplemental
verification inputs stored in the run directory, not replacements for the frozen
normative vector set.

The initial supplemental threshold 4096 suppressed no bins on this prefix. Its
reference run is retained as geometry evidence. The final 2^43 threshold changes
the output and suppression statistics at every selected length and exercises a
threshold bit above bit 31. Eighteen high-threshold vectors contain both retained
and suppressed eligible bins; Ns=1 and Ns=2 suppress all eligible bins while
protecting DC. No final-output saturation occurs in the selected reference
cases, and the native saturation checks remained clear.

The high threshold deliberately produces substantial reconstruction error.
Exact error metrics are part of the check. This is arithmetic and control
stimulus, not a recommended application threshold or evidence of signal quality.

Three reference cases have an exactly zero imaginary IFFT residual. The others
have nonzero residuals. Every real and imaginary word is compared in either
case. The Ns=1 capture mutation suite injects an imaginary error into an
otherwise real result and confirms rejection.

## Verification changes

The testbench now admits variable positive Ns within the fixed baseline
arithmetic profile and independently checks the finite-tail cardinalities. The
scoreboard allows a zero imaginary residual when the qualified oracle expects
zero; exact complex comparison remains mandatory.

The runner reads supplemental input identities from the qualified report,
validates path containment, signed width, row count and finite geometry, and
matches the compiled expectation package's vector, threshold and cardinality
constants to that report. It rejects duplicate case names even if one duplicate
is marked PASS and another FAIL. Mutation tests exercise metadata disagreement,
phantom frames, missing tail data, phase mislabeling and delayed-input boundaries.

Only verification code and documentation changed in this increment. The four
production files corrected in the first campaign are byte-identical to that
campaign's final RTL. Earlier reference attempts and baseline regressions remain
retained with their own source identities; they are not relabeled as final runs.

## Scope still open

This provides partial T-C-02, T-C-03 and T-C-08 evidence. It does not close the
complete normative signal suite, arbitrary input gaps, repeated history wraps,
remaining arithmetic/transform unit tests, dynamic frame-owned thresholds, or
reset/clear behavior. The known public C++ shift-63 findings and historical
quality-bound/provenance issues remain unresolved.

DDR/HPS/PC integration, vendor-IP behavior, physical timing/CDC and board capture
remain separate campaigns. No new Quartus fit, FPGA programming, acceleration
benchmark or electrical measurement was performed.

The next increment should exercise long records across repeated history wraps
and remaining arithmetic/transform boundaries. Dynamic threshold checks then
need a qualified frame-aware adapter; affected reset/clear expectations still
require the recorded contract decisions. The [execution plan](../verification/execution_plan.md)
tracks those dependencies.

## Reproduction and retained evidence

The [runner instructions](../../scripts/verification/README.md) give the commands.
The final reference bundle is reference-boundaries-20260915-03. The 40 vectors
were split into four isolated native batches, each running static and stalled
variants and one wrong-y witness. A serial invocation over the report's default
case list runs the same positive matrix; its default wrong-y witness count is
one instead of four. The JSON records the actual batch membership and evidence
hashes, including the final baseline regression.

Raw simulator logs, captures, libraries and local tool paths remain under
ignored runs/verification. Public documents use repository-relative paths and
hashes. Frozen inputs, coefficients and historical expected outputs were not
regenerated to obtain these results.
