# Verification execution plan

Status: implementation and execution in progress. The [first campaign](../results/verification_baseline_20260915.md)
and [finite-boundary campaign](../results/verification_boundaries_20260915.md)
record partial V0-V3 evidence; later gates and complete coverage remain open.
This is the main execution roadmap for the [verification design](README.md). The architecture and catalogs
define the detailed environments and checks; this document defines their order.

## Is the specification sufficient?

**Yes, it is sufficient to begin reference qualification, numerical unit checks,
and fixed-threshold core verification.** It is not yet sufficient to assign an
unambiguous expected result to every reset/clear collision or to claim complete
physical-board behavior.

The [integrated specification](../specs/README.md) defines arithmetic, coefficients,
transform scaling, masking, finite-stream geometry, artifacts and AC1-AC14.
[Generated contracts](../architecture/generated_contracts.md) define the shared
constants and layouts. Later architecture/interface documents describe explicit
extensions and integration behavior. Source disagreements require a recorded
decision; current RTL alone is not the expected-result authority.

Specification readiness, environment readiness and completed verification are
different states. A well-defined requirement can be ready to implement while
its test remains NOT_RUN and its simulator remains unqualified.

| Campaign | Specification readiness | Remaining dependency |
| --- | --- | --- |
| Primitive rounding, coefficients, transform scaling and mask rules | Sufficient to begin | Implement and qualify independent checkers and the selected execution tools |
| Static finite reference and core replay | Sufficient to begin within the specified arithmetic domain | Audit artifacts, qualify the reference, implement core agents and exact comparisons |
| Dynamic per-frame thresholds | Frame ownership is defined | Build and qualify the frame-aware reference adapter; the static batch API is insufficient |
| Arbitrary-cycle MAG2 metric clear and cross-owner reset collisions | Partial: affected policies remain open | Resolve O-05/O-06 before freezing those expected outcomes |
| Logical telemetry, CSR and DDR cases | Sufficient for documented behaviors under explicit model assumptions | Reconcile affected profile prose; resolve reset/late-response cases separately |
| Full physical board acceptance | Logical requirements exist; physical evidence is absent | Programmable image, deployed software, complete capture and DDR/CPU visibility evidence |

The [open-item register](decisions_and_open_items.md) mixes several kinds of work.
O-05/O-06 and parts of O-09 are contract decisions. Simulator qualification,
reference adapters, vector admission and board captures are implementation or
evidence tasks; their presence does not mean the arithmetic specification is
missing. Resolve each item before its dependent claim, not before every campaign.

## Ordered milestones

The owners below are verification work areas, not claims that corresponding
implementation files already exist. Each milestone records the selected
revision, profiles, test instances, checkers, assumptions and retained evidence.

| Milestone | Work and test families | Deliverable / exit criterion | Dependency |
| --- | --- | --- | --- |
| V0 - Environment and artifact admission | T-ENV-01..03; T-REF-01 and T-REF-06 admission inventory. Check simulator features, enabled diagnostics, exact trace transport, failure handling and immutable input identities. | A runner that distinguishes expected failures from infrastructure failures; approved input inventory with unresolved provenance visible. No PASS from an empty or stale capture. | Can start from the current design/spec. Artifact review can proceed alongside tool qualification. |
| V1 - Qualified numerical reference | T-REF-02..04; independent primitive/transform anchors and finite-stream geometry. Review the applicable quality-bound provenance. | Independently supported arithmetic and reference outputs for admitted vectors. Output equivalence and quality-bound acceptance remain separate results. | V0 capabilities required by the selected checks. |
| V2 - Arithmetic and transform RTL | T-AR-01..06 and T-XF-01..04, with qualified expected values, legal handshakes and local storage ownership. | Exact results, ordering/counts and declared flags pass for the selected legal domain; mandatory boundary bins have evidence. | Qualified simulator/checkers and the relevant V1 oracle scope. |
| V3 - First complete core replay | T-C-01, T-C-02 and the static portion of T-C-08. Then add T-C-03 backpressure. | One nonzero frozen input produces every expected y, bin/frame statistic and metric through the full tail, with no unexplained extra/missing work. | V1 oracle and the constituent V2 behaviors; retain the full-core comparison even when leaf tests pass. |
| V4 - Core stress, configuration and recovery | T-REF-05, T-C-04..08 and source/control cases. Qualify the dynamic adapter and add queued thresholds, history wraps, clear, reset and source epochs. | Independent configuration/epoch accounting and coverage for each supported scenario; ambiguous collision cases remain BLOCKED_CONTRACT until resolved. | V3 baseline; O-05/O-06 only for affected cases. Unaffected cases proceed independently. |
| V5 - Logical system and software | Telemetry, loss, DDR, CSR and HPS/PC families in the test catalog. Check noninterference after accepted replay start, publication and command lifecycle. | Exact record/transaction accounting and matched core results under explicit backend assumptions; software evidence names its host/platform scope. | Qualified reusable core environment for integration; leaf protocol/software work can proceed in parallel earlier. |
| V6 - Physical implementation and board | T-PHY-01..03 and T-BRD-01; qualify LINE-IN separately with T-BRD-02. ADC T-BRD-03 remains optional. | Matched image/software, timing/CDC review, complete deterministic capture and the required board evidence for AC13. | Applicable logical signoff, programmable image, platform readiness and capture capability. |

The catalogs specify individual cases within these families. Partial membership
never implies that an entire family passed. Regression tiers such as smoke,
block and core group executable cases; they do not replace the milestone gates.

## First core scenario

The first executed numerical integration baseline uses the existing nonzero
`impulse_Ns1024_thr0` input from the
[vector manifest](../../artifacts/test_vectors/test_vectors.json), after V0/V1
admission. This is a small diagnostic baseline, not the complete normative suite.

| Field | Baseline value or rule |
| --- | --- |
| Source | Deterministic normalized replay at the CORE cut; SOURCE/SYSTEM reuse follows |
| Configuration | Signed 12-bit samples, L=256, H=128, F=15, G=128, D=384; fixed THR2=0 |
| Initialization | Documented reset and readiness, including WOLA scrub completion |
| Real input count | Ns=1024, with input bytes and coefficient identities recorded |
| Geometry | Nframes=9, tau_last=1152, Ny=1536 |
| Driver phases | 1152 active input/zero-extension tokens, then 384 WOLA-only drain tokens |
| Initial sink/control conditions | Sink ready; no mid-run clear, source switch or threshold update |
| Numerical expectation | Qualified exact y and intermediate/statistical expectations; THR2=0 does not imply perfect reconstruction |
| Completion | All 1536 outputs accepted; exact required frame/bin/metric counts; no unexpected status or unexplained queued/extra work |

Use the distinct metric-commit and public-output-acceptance events even with an
initially ready sink. The executed stalled variant holds the last output and
other transfers without changing the input integers or expected mathematics.
A pass in this static scenario does not establish arbitrary-cycle clear or
dynamic-threshold behavior.

## What happens next

The short-length matrix has now passed: 20 input lengths, two fixed thresholds
and static/stalled sinks produced 80 passing native cases through the full tail.
The four original baseline cases also passed with the expanded harness.

The next increment should cover long records across repeated history wraps and
remaining arithmetic/transform boundary cases with qualified expectations, then
qualify the dynamic-threshold reference adapter before V4 configuration tests.
Contract review of O-05/O-06 and quality-bound provenance work can proceed
alongside these checks; affected cases remain blocked until their policies are
resolved.

Executed increments include tool/artifact qualification, bounded reference and
rounding checks, four baseline cases and the 80-case short-length matrix. The
remaining planned campaigns are NOT_RUN unless their own evidence says otherwise. See the
[runner instructions](../../scripts/verification/README.md) and linked results
for exact membership; V0-V3 are not blanket signoff labels.

Performance and electrical energy evaluation follow a trustworthy baseline
under the [benchmark plan](../evaluation/benchmark_plan.md). Verification
coverage and masked-bin counts do not establish acceleration or energy savings.
