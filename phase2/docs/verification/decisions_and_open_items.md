# Verification decisions and open items

Status: design decisions with execution in progress. The [first campaign](../results/verification_baseline_20260915.md)
records scoped tool/reference/core evidence and newly discovered defects. Open items block
only the claims that depend on them. Unaffected environment work can proceed.

## Settled architecture decisions

| ID | Decision | Reason and consequence |
| --- | --- | --- |
| D-01 | Native SystemVerilog drivers/monitors, Python orchestration and independent integer checks, file/event C++ reference adapter | Reuses the current interfaces without requiring UVM, DPI or a particular paid simulator. Qualify actual simulator capabilities before implementation depends on them. |
| D-02 | One shared transaction schema, independent numeric and protocol scoreboards | A wrong output, frame index or captured threshold must not redefine the expected result. Smaller DUT cuts reuse these contracts. |
| D-03 | Qualify the software reference before using it as an exact-output authority | Historical names and matching RTL/reference outputs alone do not demonstrate independence or correctness. |
| D-04 | Preserve frozen coefficient/vector bytes; new run artifacts are isolated | A mismatch is investigated, never resolved by automatically regenerating expected files. |
| D-05 | Track reset, source, metric and transport lifetimes separately | A source restart does not automatically rewind a published DDR ring. Metric clear does not imply datapath clear. |
| D-06 | Separate internal metric commit from public output acceptance | Backpressure can delay delivery after accounting; each owner needs its own event ledger. |
| D-07 | Separate core correctness, system transport, board operation and performance/energy gates | Lossy telemetry, a fitted design or fewer retained bins cannot establish all of these claims. |
| D-08 | Keep verification instrumentation outside production behavior | Passive binds, approved probes and test fixtures can expose ownership; they cannot change a production algorithm to make a test pass. |

## Open items and closure evidence

Each item needs a recorded disposition with the applicable requirement, source
revision, rationale, owner/reviewer and resulting test expectation. A documented
implementation behavior is not automatically the intended specification.

| ID | Observation or decision needed | Required disposition and affected gate |
| --- | --- | --- |
| O-01 | The installed simulator command interface is a candidate; version, license, four-state behavior, assertions and exit handling are unqualified. | Complete the positive/failing feature probes in [coverage and signoff](coverage_and_signoff.md). Blocks execution claims for unqualified capabilities, not documentation or source review. |
| O-02 | The public C++ batch model uses one threshold for a finite run. Dynamic frame-owned thresholds and source/metric epochs need an adapter. | Qualify the frame/ring adapter against independent geometry and static-batch special cases. Blocks dynamic numerical equivalence. |
| O-03 | The exported vector manifest currently lists three cases. Configuration names or legacy golden_frozen labels do not establish the full specification suite. | Audit per-case inputs, coefficients, configuration, intermediate results and output counts; plan the missing specification classes. Preserve historical entries. Blocks full core-suite acceptance. |
| O-04 | The near-threshold name ends in thr64, while its raw THR2 is 4096. The quality-bounds manifest has a global THR2=0 and needs per-vector provenance reconciliation. | Resolve which exact input/configuration/output each bound covers. Do not infer the raw threshold from a filename, reuse unexplained zero-error limits or invent new tolerances. Blocks quality-bound acceptance for unresolved cases. |
| O-05 | Direct MAG2 metric clear can coincide with input acceptance. Its input ready is not gated by clear; later accepted-bin assignments can overwrite accumulator clears using pre-edge values. Frame tracking also survives metric clear. | Define intended precedence and whether each spectral statistic is frame-owned or clear-owned. Check direct CORE injection separately from SOURCE integration's qualified clear application. Blocks a universal arbitrary-cycle spectral-clear claim. |
| O-06 | Cross-owner reset/clear collisions, independent async-FIFO-side resets and late DDR responses after transport clear need explicit supported/illegal policies. | Produce a per-owner precedence/cancellation table and assumptions. Known local pointer-controller precedence does not settle every cross-owner collision. Blocks the corresponding collision/recovery verdicts. |
| O-07 | The board wrapper's local write response establishes bridge acceptance. Physical DDR ordering and CPU visibility are a separate boundary. | State the BFM assumption and retain vendor/platform plus board ordering/visibility evidence before claiming physical publication correctness. |
| O-08 | Revision-G telemetry does not carry a source epoch identifier. Sequence alone cannot correlate every record across source transitions. | Use simulation sideband metadata or a known bounded host capture session; record unproven correlations. A future ABI change requires a separate design decision. |
| O-09 | Older interface prose disagrees with current profile cadence and the zero effective DSP rate in manual/faulted live-source states. | Reconcile the authoritative profile/contract before freezing expectations. Derive cadence from selected parameters; do not hard-code stale rates. |
| O-10 | Historical benches and aggregate targets have different scopes; some rely on private memories, fixed run locations or architecture models. | Admit each actual test top, fixture, checker and completion rule individually. A Step number or PASS token cannot stand in for native RTL coverage. |
| O-11 | Internal arithmetic overflow is rejected by parts of the C++ reference, while some RTL operators saturate and flag. Some wide counter states are impractical to reach through normal runs. | Define the qualified no-internal-overflow domain, separate robustness expectations, and justify boundary fixtures or unreachable exclusions. Blocks indiscriminate equivalence and coverage claims. |
| O-12 | Complete board evidence must include the required waveform, frame, metric and bin data; normal telemetry can decimate or drop it. | Choose and document a complete deterministic capture procedure and independently check its counts. If the current transport cannot deliver required evidence, design that capability separately before board signoff. |
| O-13 | Software host tests cannot establish deployed ARM/Linux reservation, mapping, grant ownership or cleanup. | Qualify Linux host execution and separately retain deployed kernel/DTB/module identity and runtime evidence. Blocks platform and full-system board claims. |

The relevant implementation boundaries are the
[MAG2/mask block](../../rtl/core/trecap_mag2_mask.sv),
[delay/error block](../../rtl/core/trecap_delay_error_metrics.sv),
[source/core integration](../../rtl/top/trecap_source_core_integration.sv),
[vector manifest](../../artifacts/test_vectors/test_vectors.json), and
[quality bounds](../../artifacts/manifests/quality_bounds.json). The remaining
protocol authorities are linked in [system and interfaces](system_and_interfaces.md).

## Implementation sequence after design review

The [execution plan](execution_plan.md) assigns readiness, dependencies and exit criteria to this sequence. Open collision policies do not block unrelated static numerical campaigns.

1. Resolve the policies needed by the first core campaign and qualify the
   simulator, runner, transaction format and failing checker probes.
2. Qualify primitive arithmetic, coefficient provenance, the independent integer
   oracle and public C++ reference. Audit the finite-vector evidence.
3. Implement reusable leaf/transform/core agents and scoreboards. Close static
   finite replay, exact tail geometry and metric/output accounting before adding
   dynamic thresholds, source epochs and legal stress.
4. Add source/control, telemetry, DDR and software environments. Reuse the core
   oracle while introducing layer-specific loss and publication ledgers.
5. Close physical CDC/timing and deterministic BRAM board evidence for the
   selected baseline. Qualify live audio separately; ADC remains optional.
6. Begin the [benchmark plan](../evaluation/benchmark_plan.md) with the qualified
   baseline. Any zero-aware IFFT change needs equivalence against that baseline
   and separate performance/energy evidence.

The [requirements matrix](requirements_matrix.md) retains the complete planned
scope. Selected cases now have executed evidence; unresolved policies, historical
provenance, unexecuted campaigns and board gates remain open.
