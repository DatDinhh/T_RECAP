# Assertion and protocol-property catalog

These properties are implementation-neutral design obligations. They may be
implemented as qualified immediate/concurrent assertions, procedural monitors,
or temporal scoreboards. This document contains no SVA implementation and does
not assume that the current simulator supports every concurrent assertion form.

Each property implementation records its bound instance, clock/sampling phase,
enable condition, reset/cancellation scope, positive activation count, failure
count and coverage witness. A property compiled away, never activated or
unsupported by a backend is not verified. Predicate and consequence must be
checked independently; do not bind only to a DUT-computed error flag.

## Safety and conditional progress

| Property ID | Boundary | Required behavior | Assumptions and exceptions | Test families |
| --- | --- | --- | --- | --- |
| P-OBS-01 | All active interfaces | After reset/recovery qualification, required control signals and payload accepted or advertised as valid are known; unused RAM and invalid payload may remain unknown. | Four-state monitor; reset/ownership masks explicit | T-ENV-01, T-XF-04, T-S-05 |
| P-RV-01 | Each ready/valid producer | Valid and all meaningful payload/identity/last fields remain stable while stalled, until acceptance or a contract-defined cancellation. | Sample at the owning edge; reset/clear cancellation documented per interface | T-XF-03, T-C-03, T-DDR-03 |
| P-CORE-01 | Core input fork | Every accepted input reaches input history and delayed-reference history exactly once on the specified atomic admission. | No independently inferred acceptance from struct validity | T-C-03, T-C-06 |
| P-CORE-02 | Frame/bin/output boundaries | Identities are contiguous and unique within their epoch; missing, repeated, swapped or stale items are detected. | Independent expected counts and epoch ledger | T-XF-01, T-XF-02, T-C-01 |
| P-CORE-03 | Frame scheduling | Positive hop boundaries create exactly the permitted frames; no extra frame arises beyond tau_last. | Finite mode uses window-active geometry; continuous mode has no automatic tail | T-C-02 |
| P-CORE-04 | Frame configuration queue | Every admitted frame retains its own full 56-bit THR2; queue count/ownership and simultaneous push/pop are valid. | Predict threshold application independently of DUT bin output | T-C-04 |
| P-CORE-05 | Finite drain | Active input and pure drain are mutually exclusive; drain advances WOLA but creates no FFT frame or bin statistics. | Count active ticks, drain ticks and accepted y separately | T-C-02, T-C-03 |
| P-CORE-06 | RAM/history/WOLA ownership | Reads use owned/tagged data, writes do not overwrite unread state, and each WOLA output slot is consumed and cleared in the specified order. | Allow documented zero extension; do not initialize all RAM in the harness | T-XF-04, T-C-06 |
| P-CORE-07 | Delay/error metric commit | Each logical reconstruction commits once to its metric epoch; each non-cancelled committed y is eventually accepted once. | Public acceptance may occur after metric commit; liveness needs ready fairness | T-C-08 |
| P-CORE-08 | Replay completion | No core-path done before exact cardinalities and final public y acceptance; no system done before its additional publication conditions. | Source done, core done and system done are different events | T-C-03, T-BRD-01 |
| P-NUM-01 | Canonical/mask path | DC and Nyquist imaginary components are zero at canonicalization; conjugate pairing and mask mirroring follow the qualified numeric domain. | Do not extend this to universal zero IFFT imaginary residual | T-AR-04, T-AR-05 |
| P-NUM-02 | Mask/statistics | Full-width unsigned comparison keeps equality; THR2=0 suppresses no eligible bins; protected bins are retained and excluded from eligible sums. | Exact pre-mask/final-mask distinction and endpoint weights | T-AR-05, T-TEL-01 |
| P-NUM-03 | Arithmetic/status | No internal overflow or silent wrap is accepted on the frozen signoff set; stress failures follow a separately declared flag policy. | Does not invent RTL/ref equivalence outside the qualified domain | T-AR-01, T-C-07 |
| P-SRC-01 | Source lifecycle | No core admission from the wrong epoch during switch, fault, waiting-stop or settle; readiness owns re-entry. | Manual ADC diagnostics do not enter DSP | T-S-01, T-S-02 |
| P-SRC-02 | Live sequence checking | An offending sequence-gap/duplicate event is blocked and causes the specified fault/recovery before later admission. | Raw sequence differs from accepted sample index | T-S-02 |
| P-SRC-03 | Live drop accounting | Transferred overflow/drop events and loss/fault flags match their documented counter semantics. | Coalesced audio CDC events are not exact physical lost-sample counts | T-S-03, T-TEL-05 |
| P-CDC-01 | Async FIFO | No accepted write when full or read when empty; complete payload order and pointer ownership persist across legal clock relations. | Only supported coordinated reset sequence; do not claim analog metastability proof | T-S-05, T-PHY-01 |
| P-CDC-02 | Reset domains | Fabric reset release is canonical; audio edge domains release through their own defined synchronization; no stale valid work survives scoped reset. | Structural RDC evidence supplements functional checks | T-S-05, T-PHY-01 |
| P-TEL-01 | Core/observer boundary | Changing observer/DDR pressure cannot alter core processing traces for identical admitted source/control schedules. | Paired runs aligned after accepted replay start; initial transport admission may differ | T-S-06 |
| P-TEL-02 | Packet selection | Selected records finish through last unless a documented transport reset cancels them; discontinuity abandons partial unselected collection only as specified. | No guessed source epoch reconstructed from UDP seq | T-TEL-03 |
| P-TEL-03 | Packet storage | Each FIFO capture/resident record owns exactly one payload slot until delivery/drop/cancellation; protected head is not evicted or overwritten. Pre-FIFO candidates need not own FIFO slots. | Model oldest eligible lowest-priority eviction and simultaneous dequeue/admit | T-TEL-02, T-TEL-05 |
| P-TEL-04 | Metric snapshots | Core and telemetry share the same applied metric-clear boundary; snapshots remain internally coherent. | Raw request and applied pulse differ; owner-specific accumulator precedence must be resolved under O-05 | T-C-08, T-TEL-04 |
| P-CSR-01 | CSR bus | Every accepted request, including a rejected transfer, has exactly one specified response. A stalled request has no repeated side effects; a later acceptance is a new transaction. | Full byte address, alignment, byteenable and burst rules | T-CTL-01 |
| P-CSR-02 | CSR ownership | Shadow words are applied atomically; snapshot halves stay coherent; read-only and pointer owners are respected. | Same-clock atomicity is not mislabeled CDC | T-CTL-02, T-DDR-04 |
| P-CSR-03 | Rejected access | A locally rejected request produces no forbidden physical write or state change; independent rejection owners are counted correctly. | Per-owner simultaneous-event precedence reviewed | T-CTL-01, T-CTL-03 |
| P-DDR-01 | Avalon write request | Address, data, byteenable and control remain stable while waitrequest is asserted. | Reset cancellation and valid timing per interface profile | T-DDR-03 |
| P-DDR-02 | Write responses | Responses correspond one-for-one to accepted outstanding writes under the chosen backend contract. | Generic delayed-response and local board-acceptance modes are distinct | T-DDR-03, T-DDR-06 |
| P-DDR-03 | Record publication | W advances only after the completion condition for that record; a failed normal record is not published. | A previously committed WRAP stays published; no blanket rollback | T-DDR-02, T-DDR-03 |
| P-DDR-04 | Pointers and sequence | W is FPGA-owned; Rd changes only by legal commit; sequence increments for normal records, not WRAP. | 64-bit absolute pointer bounds and seq32 wrap use their own contracts | T-DDR-04 |
| P-DDR-05 | Ring space and range | Admission requires tail-plus-normal bytes to fit usable free space, which already subtracts the guard; requests remain within the configured/reserved range. | Test exact-end fit and free-space boundary separately | T-DDR-01, T-DDR-02 |
| P-CMD-01 | Host commands | A valid retransmission returns the defined cached result without repeating side effects; conflicts/stale/session violations follow the protocol. | Peer/session/sequence key and wrap/half-range semantics | T-SW-02 |
| P-CTRL-01 | Reset/clear scope | Each reset or clear affects only its documented owners, preserving unrelated core, metric, source or transport state. | Cross-owner collisions require a reviewed priority table | T-C-05, T-CTL-03, T-DDR-05 |
| P-LIVE-01 | Conditional progress | Under declared bounded stalls/responses, returning clocks and valid source pacing, accepted work completes within the derived bound. | Permanent BCLK stop or permanent sink stall cannot imply unconditional completion | T-C-03, T-S-02, T-DDR-03 |

## Binding and reset policy

Maintain an instance-to-property registry in the future environment. Every
ready/valid link needs its own P-RV-01 binding, including metadata and last fields.
Specialize properties where an interface permits cancellation or has valid-only
semantics; do not apply one generic stream assertion to all ports.

A legal reset abort records exactly which outstanding identities were cancelled.
It does not erase unrelated checker failures. During initialization, knownness
requirements follow valid/ownership and scrub readiness, not an arbitrary delay
that could hide a stale-memory read. A property disabled by an assumption records
that assumption and its activation count.

For a local fault test, verify both the fault indication and the prohibited side
effects: no extra output acceptance, no wrong-epoch sample, no publication of a
failed normal record, or no repeated command application as applicable.
An illegal stimulus with unspecified behavior is a contract question, not an
excuse to invent an expected response.

## Formal use

Bounded formal checks are optional supplements for small control/ownership
blocks: FIFO occupancy, atomic forks, snapshots, queue ownership and pointer
rules. Record the harness, reset reachability, assumptions, depth, proof status
and vacuity checks. A bounded proof covers its stated bound; an inconclusive run
is not PASS. Do not claim a full FFT or analog CDC proof from these local checks.

The [coverage/signoff contract](coverage_and_signoff.md) controls simulator
qualification and evidence. Exact arithmetic/output comparisons remain required
even when every protocol property passes.
