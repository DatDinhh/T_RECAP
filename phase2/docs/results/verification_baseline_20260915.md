# First executed verification campaign

Date: 2026-09-15. **Selected software and RTL baseline campaigns passed.**
This is partial verification evidence, not full-core, system or board signoff.
The [machine-readable result](verification_baseline_20260915.json) records the
executed cases, source/input identities, exact counts and remaining limitations.

## Results

| Area | Executed result | Scope |
| --- | --- | --- |
| Simulator and runner | 15 qualification cases passed | ModelSim Intel FPGA Starter Edition 2020.1; four-state behavior, scheduling, exact integer files, assertions/errors/fatal, completion and watchdog handling |
| Artifact admission | 264 file identities checked; three vectors admitted as local bytes | Five coefficient tables and local imported/promoted snapshots; historical generation and quality acceptance remain separate |
| Artifact checker | 31 tests passed | Deliberate corruption, malformed encoding, missing/truncated files, metadata and provenance rejection |
| Reference qualification | 16,540 primitive comparisons, transform/mask anchors and both selected vectors passed | Independent Python integer oracle versus public C++ APIs; eight existing C++ tests are supplementary evidence |
| Reference checker | 13 rejection witnesses passed | Corrupted numerical records, missing/duplicated data and malformed transcripts |
| RTL rounding | 33,132 primitive comparisons passed | 8,283 signed 64-bit inputs, signed 12-bit result, shifts 0/1/4/15; package helpers checked on the same inputs |
| Core replay | Four positive cases passed | Two fixed-threshold vectors, each static and stalled, with complete captures |
| Native output checker | Wrong expected y was rejected | One deliberately corrupted native-core expectation |
| Capture checker | 38 tests passed | Mutations of a real positive capture; originals preserved |
| Reference admission | 11 tests passed | Changed manifests, source identities, expected outputs and missing/failed qualification are rejected |

The RTL rounding campaign also checks sign, magnitude, large arithmetic shift,
and rounded/saturated package-helper results. Separate corrupted expectations
demonstrate rejection by the primitive and helper comparison paths. This does
not qualify every width or every public helper input.

## Exact core scope

The tested DUT is the finite BRAM/core replay composition, with no DDR, HPS,
audio or ADC system in the simulation. The source accepts one finite epoch,
including zero extension and pure WOLA drain. The simulator compiles production
RTL without SYNTHESIS.

| Input vector | Raw THR2 | Static | Stalled | Output / frame / unique-bin / complex-IFFT counts per case |
| --- | ---: | --- | --- | --- |
| impulse_Ns1024_thr0 | 0 | PASS | PASS | 1536 / 9 / 1161 / 2304 |
| near_threshold_multitone_Ns1024_thr64 | 4096 | PASS | PASS | 1536 / 9 / 1161 / 2304 |

Each positive case has 1024 real samples, 128 analysis zero-extension tokens
and 384 pure drain tokens. All ten aggregate metrics match. Public output
acceptance, internal metric commit, source acceptance and completion have
separate checked records. Completion follows the final accepted output and
1024 quiet cycles expose extra transactions.

Stalled cases use a deterministic LFSR and a final-output hold of at least
37 cycles; 40 final stalled cycles were observed because ordinary readiness
extended the hold. Exact numerical results are unchanged. Native logs contain
no unexpected errors or fatal diagnostics in the four positive cases.

The reference campaign checks six intermediate numerical boundaries per
vector: analysis window, FFT, canonical spectrum, masked spectrum, IFFT and
synthesis window. The native core campaign directly compares every complex
IFFT sample, canonical bin tap, frame statistic and output sample. These are
different observation scopes; passing the integration does not replace every
planned transform-unit test.

Both selected outputs have zero aggregate reconstruction error against the
delayed input in these runs. This is a result for those exact inputs and
thresholds, not a general perfect-reconstruction claim or acceptance of every
historical quality bound.

## Defects found and corrected

### VF-001: negative rounded shifts

The RTL compared signed values with the unbased literal zero. That relational
expression became unsigned, so the negative branch was skipped. A minimal
witness was -1 shifted by one: the DUT returned 0 instead of -1. In the first
FFT frame, a negative butterfly difference that should have produced -999424
instead saturated to +134217727.

[round_sat.sv](../../rtl/common/round_sat.sv) and the
[shared math helpers](../../rtl/include/trecap_math_pkg.sv) now compare against an
explicitly signed zero. Independent unit cases include negative ties, neighbors,
clipping limits and signed 64-bit extrema. Full replay passed after the fix.

### VF-002: valid IFFT residual prevented completion

Fixed-point IFFT rounding can leave a nonzero imaginary component. The
specification, section 4.6 equation 4.21 and Algorithm 3, synthesizes the real
component. WOLA nevertheless raised its protocol flag for the imaginary
residual; the replay wrapper interpreted that flag as a fatal completion fault.

The [WOLA correction](../../rtl/core/trecap_synthesis_wola.sv) removes only that
residual-driven protocol assignment. Malformed token, drain and lifecycle
checks remain active. Both IFFT components compare exactly with the qualified
oracle: impulse contains 120 nonzero imaginary samples with maximum magnitude
605; near-threshold contains 2226 with maximum magnitude 295. Their existence
is independently verified, not blindly ignored.

### VF-003: stale delayed-history assertion

During output stalls, the delay/error block can retain a validated one-cycle
RAM response until the pending y commits. Its simulation assertion required the
RAM tag to be valid again on the commit cycle, ignoring that retained response.

The [assertion correction](../../rtl/core/trecap_delay_error_metrics.sv) accepts
either the retained validated response or the current correctly tagged response.
The datapath is unchanged. Both stalled cases now pass with strict diagnostic
scanning and independent delayed-x/error/output checks.

Failed runs were retained before the fixes. Expected-error tests are identified
as such; their failures are not mixed with unexpected production failures.

## Remaining work and interpretation

The first campaign contributes partial evidence to V0-V3 in the
[execution plan](../verification/execution_plan.md). It does not close all
59 test families, 46 requirements or AC1-AC14.

- The C++ public rounding API returns zero for three tested shift-63 inputs whose
  correct results are -1 or +1. Those executable findings remain open outside
  the selected baseline shift domain; full V1 qualification is false.
- The near-threshold quality-bound metadata has THR2=0 while the vector uses
  4096. Historical coefficient/vector generator fingerprints also differ from
  current source fingerprints. Current bytes are internally admitted; historical
  provenance and quality acceptance remain unresolved.
- Dynamic thresholds/metric clears, reset/source transitions, the complete
  normative signal suite, remaining arithmetic/transform units and broader
  constrained-random coverage remain to be implemented and executed.
- Native telemetry/DDR/HPS/PC integration, physical CDC/STA closure and board
  capture are separate campaigns. The prior fitted timing/resource report
  predates these RTL fixes and must not be presented as a fit of the corrected
  source.
- No acceleration benchmark or electrical energy measurement was performed.

The next verification increment should add the short-length/full-tail boundary
matrix and further transform/arithmetic cases, then dynamic frame-owned
thresholds with a qualified adapter. Clear-policy decisions can proceed
alongside those tests.

A supplementary production-board source elaboration with pyslang 11.0.0
completed with zero errors and 322 non-error diagnostics. The external vendor
modules remain system and altera_pll. This source-only check uses SYNTHESIS;
the functional ModelSim campaigns above do not. It does not replace a new
Quartus fit or execute vendor IP.

## Reproduction and evidence

[Running the campaigns](../../scripts/verification/README.md) provides the
commands and input dependencies. Run directories are immutable local evidence
under runs/verification; new attempts use new directories. The public JSON
records their relative identities and SHA-256 values, plus source and capture
hashes. Raw simulator paths, machine configuration, libraries and logs stay out
of the public source tree.

The native runner pins the accepted environment and reference reports, validates
all emitted oracle files, stages exact ROM bytes, and rechecks those identities
after execution. Its result requires both native checks and independent capture
checks. No frozen coefficients, input vectors or reference outputs were
regenerated to obtain a pass.
