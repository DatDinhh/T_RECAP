# Coverage, regression and sign-off

Status: acceptance policy. Executed results are recorded separately in the [first campaign report](../results/verification_baseline_20260915.md); this policy document itself establishes no pass or board result. We use the hierarchy in [architecture.md](architecture.md), the [requirements matrix](requirements_matrix.md), and the [test catalog](test_catalog.md) to connect each claim to reproducible evidence.

The planned baseline uses native SystemVerilog drivers and monitors, Python orchestration and independent integer checkers, and a file-based adapter to the public C++ reference APIs. UVM, DPI and cocotb are not prerequisites. The implementation and its checker must have separate observable responsibilities: stimulus drives transactions, monitors record what the DUT actually accepts or produces, and scoreboards compare those events with expected behavior.

## Tool and harness qualification

The ModelSim/Questa command interface used by the existing Windows runners is the primary simulator candidate. Its exact executable, version, edition, license availability and supported features remain qualification gates. A working Quartus Lite 20.1.1 synthesis installation does not qualify a simulator, assertion engine or coverage facility. Record the native Windows environment and executable identities without publishing machine-specific installation paths or license material.

Qualification must exercise the features the selected benches use:

| Area | Required qualification evidence |
| --- | --- |
| Compile closure | Correct package/file order, parameters, packed types, signed casts, memories, test top and all required monitors are present. |
| Scheduling | Clock edges, nonblocking assignments, reset ordering and declared time resolution behave as the driver/monitor contract requires. |
| Four-state behavior | Inject X/Z on required control and valid payload signals; the corresponding checker reports the intended failure. |
| Diagnostics | Deliberately failing immediate assertions, `$error` and `$fatal` propagate through the simulator and runner. |
| Observation | Required ports, taps and any approved internal objects remain observable with the actual optimization/access settings. |
| File protocol | Integer width, signedness, record framing, missing files and truncated traces are handled without silent conversion. |
| Termination | Normal completion, simulator failure, missing completion evidence and both watchdogs produce distinct recorded outcomes. |

Qualification includes positive controls and deliberate failures. A failing probe succeeds as a qualification test only when the expected checker and failure class fire; an unrelated compile error is not acceptable. Deliberately corrupt an output value, index and completion count to demonstrate scoreboard sensitivity. Requalify affected capabilities after changes to simulator version, compile options, runner, trace format or checker.

Functional simulation compiles the DUT **without `SYNTHESIS`**. The current [production elaborator](../../scripts/elaborate_rtl_sources.py) defines it and therefore excludes simulation-only checks. Keep that useful source check separate from simulation qualification. Audit existing simulation assertions against current contracts; resolve stale assumptions individually. Do not disable a class of assertions to obtain a passing run. Diagnostic suppressions need a documented meaning for the selected tool version and a narrow reviewed scope.

Use explicit functional counters and procedural monitors as the portable baseline. Concurrent assertions, covergroups, code coverage and coverage-database merging are optional capabilities until qualified. Record which checks were compiled, enabled and observed. A simulator accepting an assertion declaration does not prove that the assertion executed. An optional alternative simulator cannot close a requirement whose semantics it does not model; a two-state run cannot close X/Z requirements.

Native Windows can host the reference C++ and Python checks after compiler/dependency qualification. The HPS POSIX transport and sanitizer suites require a qualified Linux environment. WSL availability alone does not establish a working distribution, compiler, sanitizer or target kernel. Host-memory mocks and Linux host tests remain distinct from ARM deployment and kernel-driver evidence.

## Admission of historical assets

Existing tests are candidates for reuse, not inherited passes. Each receives an admission record identifying its purpose, requirements, current compile closure, oracle, assumptions, stimulus, completion rule and limitations. Review renamed ports, new RAM read latency, scrub/reset sequences, frame timing, hierarchy references and watchdog limits before execution.

The [v70 runner](../../scripts/windows/run_c0_golden_v70.ps1) supports one near-threshold vector and writes fixed run paths. Its PASS tokens cannot establish broader vector coverage. The [WOLA test](../../sim/tb/tb_trecap_wola_tail_drain.sv) directly initializes an internal coefficient memory; that fixture and its access requirements need explicit admission. Step 14 in the [Makefile](../../Makefile) retains Step 12 RTL simulation, while Step 16/17 add architecture models rather than native audio/ADC coverage. Catalog actual executed tops and checks, not just aggregate target names.

Preserve historical expectations and hashes. A verification run reads its selected immutable inputs and writes new expectations/captures into its run directory. It does not automatically execute coefficient/vector regeneration or promote new outputs to reference authority. Correcting a defective expectation requires a reviewed explanation and new provenance, not replacing it because the DUT disagreed.

## Regression tiers

These are proposed suite identities, not runtime promises. The catalog defines their exact membership before execution.

| Tier | Required scope |
| --- | --- |
| `smoke` | Qualified compile path, checker sensitivity controls and a small deterministic nonzero core case with exact completion. |
| `block` | Arithmetic boundaries, memories, handshakes, packet storage, CSR transactions, CDC protocols and source adapters in isolation. |
| `core` | Complete fixed-point pipeline, finite tails, threshold ownership, stalls, resets and source-independent numerical comparisons. |
| `system` | Telemetry/DDR/control composition, software parsing and lifecycle, source epochs and adverse interface behavior under documented models. |
| `release` | Frozen membership of applicable lower tiers, approved seed corpus, coverage closure, issue disposition and an immutable evidence summary for a named scope. |

A release run does not silently replace the qualification, board or energy gates below. Add new test membership deliberately; record excluded profiles and unsupported tools.

Every randomized run records the seed, generator algorithm/version and effective generated schedule or stimulus hash. Preserve failing seeds and minimized reproducers. Repeating a seed across different generators or simulator versions is not assumed to reproduce transactions. The deterministic suite covers mandatory boundaries; random exploration supplements it.

Declare clock periods, relative phases, reset timing, stimulus sampling edges and simulator precision. For asynchronous interfaces, vary legal phase/frequency relationships and resets; protocol simulation does not model analog metastability. Drive and sample at defined phases to avoid testbench races. Record backpressure schedules, maximum stall assumptions and fairness conditions. An indefinitely stalled interface may have no finite progress guarantee: verify stability and conservation there, and apply liveness bounds only when the environment satisfies their premises.

## Coverage and closure

The primary coverage model is requirement-based functional coverage. Each bin has an observable event, a counting rule, applicable configurations and a required completion condition. Useful dimensions include arithmetic boundaries, frame/sample positions, threshold cases, empty/full/wrap storage states, stall positions, reset phases, source modes, packet types and accepted/rejected control actions. The sibling core and system plans define the detailed bins.

Specify crosses that expose interactions, such as reset during a pending transaction or threshold commit while older frames remain active. Do not generate every Cartesian product without a reason. Coverage increments only when its monitor observes the event, not when the driver merely schedules it. A handshake event requires valid and ready both known and asserted. Ignore invalid payload values where the interface permits them; unknown required controls or valid payload are failures.

Track checker observability alongside stimulus coverage: activation count, antecedent/event count, comparison count, failures and relevant vacuity conditions. A never-triggered checker is not evidence of the property it was meant to test. Negative tests must identify the exact expected rejection/fault and demonstrate that unrelated state remains within its contract.

There is no blanket code-coverage percentage that substitutes for correctness. Optional line/branch/toggle reports help locate gaps but retain their instrumented scope and tool limitations. Closure requires every mandatory requirement to have accepted evidence and every unhit mandatory bin to be resolved through added stimulus, a corrected unreachable-bin definition, or an explicit scope decision. A waiver names the requirement, reason, supporting analysis, affected configurations, owner, reviewer and expiry/change trigger. Known violations cannot be waived into a claim that the requirement passed.

## Trace and evidence contracts

Trace schemas are versioned interfaces between monitors and checkers. Preserve integer values exactly; do not route 56-bit thresholds, 64-bit pointers/counters or wider metrics through floating-point JSON numbers. Use canonical decimal strings for large integer values, with explicit width and signedness, or width-qualified hexadecimal strings for raw bit patterns. Preserve X/Z as explicit four-state strings and reject them where the contract requires known data.

| Event field | Meaning |
| --- | --- |
| `schema_version`, `run_id`, `event_sequence` | Trace identity and deterministic ordering; sequence numbers must not silently restart. |
| `boundary`, `event_kind`, `direction` | Observed interface and whether the event is acceptance, output, control, fault or completion. |
| `monitor_id`, `clock_domain`, `time_ticks`, `tick_unit`, `local_cycle`, `sampling_phase` | Exact observation origin/time and pre-edge or post-update phase; no guessed ordering across unrelated clocks. |
| `reset_generation`, `source_epoch`, `metric_epoch`, `transport_epoch`, `accepted_sample_idx`, `frame_idx` | Include applicable named ownership coordinates from the architecture; absent fields are explicit, not zero substitutes. |
| `valid`, `ready`, `payload` | Observed protocol state and width/signedness-qualified fields. |
| `configuration_id` | Effective configuration or frame-owned threshold identity relevant to this event. |

Check headers, schema, ordering, counts, end markers and file hashes before accepting a trace. Empty, duplicated, truncated or missing captures fail admission even if a console PASS token exists. A final manifest records expected and observed event counts, completion state and outstanding transactions.

Each run uses a unique directory under ignored `runs/verification/`, with isolated simulator libraries and configuration. Do not reuse a shared `work` mapping or overwrite prior evidence. A run manifest contains:

| Field group | Required contents |
| --- | --- |
| Identity | Run ID, UTC start/end, suite/test IDs, selected requirement IDs and parent/retry relationship. |
| Source | Revision, dirty-state description, source/filelist/checker hashes, parameters, defines and selected top. |
| Inputs/oracles | Input, coefficient, configuration and expected-artifact hashes; reference/checker versions and generation provenance. |
| Tools | Simulator/compiler/Python identities, qualification record, options, OS and relevant dependency versions. |
| Stimulus | Seeds, effective clock/reset/stall assumptions and recorded stimulus identity. |
| Execution | Invoked stages, exit codes, watchdog bounds, expected diagnostics and classified outcome. |
| Results | Exact comparisons/counts, completion evidence, coverage records, issue/waiver references and all report/capture hashes. |

Keep raw logs and traces immutable after finalization. Publish sanitized summaries with repository-relative provenance and hashes; omit usernames, credentials and license data. Retry into a new run and link the failed predecessor. A changed source, checker or input creates a new evidence identity. Historical build JSON remains historical and is not rewritten by verification.

## Outcomes and watchdogs

Every test has a simulated-cycle/time deadline derived from its scenario and a separate host wall-clock limit. On timeout retain diagnostics and partial captures, terminate owned processes, and mark the result incomplete. Do not infer success from a simulator exiting zero or a PASS substring alone.

Record `PASS`, `FAIL_DUT`, `FAIL_ORACLE`, `FAIL_INFRASTRUCTURE`, `TIMEOUT`, `BLOCKED_CAPABILITY`, `BLOCKED_CONTRACT` or `NOT_RUN`, with the causal stage. An expected negative test is PASS only after its exact expected behavior is checked. Missing tests and unsupported features remain visible; they do not reduce a suite denominator silently. The release summary reports selected, executed, passed, failed, blocked and waived requirements separately.

## Sign-off gates

| Gate | Evidence required before the claim |
| --- | --- |
| Reference | Independent boundary arithmetic checks, coefficient/configuration identity, finite geometry and qualified reference adapter; matching model outputs alone are insufficient. |
| RTL core | Complete accepted output/count comparisons, full-tail and configuration ownership checks, protocol/reset evidence and closure of mandatory core requirements. |
| Logical system | Packet/DDR/CSR/source contracts and software lifecycle checked under explicit bus/peripheral models; model guarantees and omitted physical behavior are listed. |
| Physical implementation | Matched generated platform, fitted pins, timing/CDC evidence and reviewed assumptions for the exact image/profile. This does not prove functional correctness. |
| Board | Matched programmable image and deployed software, loss-accounted complete captures, repeatable replay, and separate live-source/driver/peripheral evidence for claimed capabilities. |

The [reference/core plan](reference_and_core.md) and [system/interface plan](system_and_interfaces.md) define gate-specific checks. The reference API's finite-run threshold model cannot alone predict midstream commits or source epochs; those require an event-aware adapter and independent ownership ledger.

Sign-off names the accepted revision, profile, requirements and remaining limitations, with review recorded in the requirements matrix. Board acceptance cannot be inferred from a logical memory model or the wrapper's local write-acceptance response. Acceleration and electrical energy results require the separate [benchmark plan](../evaluation/benchmark_plan.md); neither simulation coverage nor successful fitting establishes measured savings. Open qualification and scope decisions remain in [decisions_and_open_items.md](decisions_and_open_items.md).
