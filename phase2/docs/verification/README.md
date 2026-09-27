# Verification design

This package defines the verification architecture for the current T-RECAP
implementation. It specifies the environments, evidence, and acceptance rules.
Implementation and execution have started: the [first campaign results](../results/verification_baseline_20260915.md)
record the qualified scope, passing cases, corrected defects and remaining work.
The [finite-boundary campaign](../results/verification_boundaries_20260915.md)
adds 80 passing native cases and a repeat of the four baseline cases.
The design documents alone do not establish signoff.

The implemented baseline includes a qualified arithmetic reference and a
self-checking core environment within the recorded scope. Transport, software, physical timing, and board
operation have separate gates. The proposed energy optimization remains outside
the baseline and starts only after the existing design has a trustworthy result.

The [execution plan](execution_plan.md) is the main roadmap: specification readiness, ordered milestones, dependencies and the first concrete core scenario.

## Reading order

| Document | Question it answers |
| --- | --- |
| [Execution plan](execution_plan.md) | What can start now, what comes next, and what completes each milestone |
| [Environment architecture](architecture.md) | What runs at each DUT boundary, how observations become transactions, and who owns each verdict |
| [Reference and core](reference_and_core.md) | How arithmetic, frames, masking, WOLA, dynamic thresholds, and metrics are checked |
| [System and interfaces](system_and_interfaces.md) | How sources, reset/CDC, packet loss, DDR, HPS, and commands are checked |
| [Test catalog](test_catalog.md) | Which directed and randomized scenarios must exist |
| [Assertion catalog](assertion_catalog.md) | Which properties apply at each boundary and under which assumptions |
| [Requirements matrix](requirements_matrix.md) | Which source requirement each checker and test establishes |
| [Coverage and signoff](coverage_and_signoff.md) | How tools, regressions, evidence, and coverage are qualified |
| [Decisions and open items](decisions_and_open_items.md) | Which assumptions are settled and which prevent specific claims |

## Design principles

- The integrated specification defines expected behavior. RTL is inspected to
  locate interfaces and risks; its output never defines its own expected result.
- Qualify the reference model with independent arithmetic checks before using it
  as the main exact-output predictor.
- Keep data correctness, temporal/protocol correctness, and physical evidence
  separate. Every required dimension must pass for the corresponding claim.
- Observe accepted transactions, preserve explicit epoch identities, and account
  for intentional loss at its owning layer.
- Prefer reusable native SystemVerilog agents and file/event contracts with
  Python/C++ analysis. UVM, DPI, and a paid simulator are not prerequisites.
- Unsupported simulator features, missing tests, absent evidence, and unresolved
  contract ambiguity do not become PASS.
- Use full-width integers and complete captures. Dashboard plots, decimated
  telemetry, hashes alone, and a simulator PASS banner cannot establish all core
  requirements.

## Relationship to existing material

The [specification index](../specs/README.md), [architecture](../architecture/architecture_design.md),
and [interface contracts](../architecture/interface_contracts.md) remain the design
authorities. The [existing simulation guide](../../sim/README.md) describes
historical benches that require admission review before reuse. The
[benchmark plan](../evaluation/benchmark_plan.md) consumes verification evidence;
speedup and electrical energy savings are later measurements.

The catalogs describe the full planned scope. Only cases linked to executed
evidence in the results report have a result; partial family coverage does not
close an entire requirement. [Runner instructions](../../scripts/verification/README.md)
provide the reproducible implementation entry point.
