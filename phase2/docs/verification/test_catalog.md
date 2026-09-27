# Verification test catalog

The families below define the planned scope. The [first campaign report](../results/verification_baseline_20260915.md)
records executed cases; a passing case does not close an entire family.
A family expands into named cases with concrete parameters, stimulus hashes,
checker IDs, coverage bins, expected outcome, and watchdog bounds.
The [requirements matrix](requirements_matrix.md) maps these families to claims.

## Scenario construction

Maintain four distinct partitions:

- Normative signoff: admitted frozen vectors, full-tail geometry and no unexpected
  internal overflow. All required exact artifacts are checked.
- Legal stress: valid interfaces with randomized timing, amplitudes, controls and
  workload. Numerical claims require the declared range/overflow policy.
- Defined negative: one documented invalid stimulus or injected environment fault
  and its specified rejection, fault flag or fail-stop response.
- Diagnostic: reduced models, optional parameters, white-box state fixtures or
  omitted vendor components. These never silently count as baseline evidence.

Keep data generation independent from timing generation. Freeze the actual input
integers; a tone name or floating frequency alone is not reproducible. For
threshold equality, inject constructed canonical operands at the mask-unit cut
and choose THR2 from the independent integer mag2 value. A random audio stream
cannot be assumed to hit an exact equality boundary.

Raw ADC/audio events continue on their physical schedule even when the core cannot
accept data. Normalized ready/valid source drivers instead hold pending payload
until acceptance. These are different agents, not a global ready signal wired
back to a physical source.

## Families

| Test ID | Boundary/purpose | Stimulus | Oracle/checker | Required observations |
| --- | --- | --- | --- | --- |
| T-ENV-01 | Tool qualification | Actual source closure, four-state values, file I/O, immediate assertion/error/fatal, visibility and failure exit paths | Known positive and deliberately failing probes; enabled checker inventory | Each required feature observed; unsupported feature blocks its dependent gate |
| T-ENV-02 | Checker qualification | Corrupt one value/index/count/threshold/record/terminal marker at a time | Named checker must detect its injected fault; unrelated failures remain failures | Every mandatory checker has a positive and a rejection witness |
| T-ENV-03 | Runner integrity | Missing/empty/truncated artifacts, absent tests, compile/license failure, host/simulation timeout, stale capture | Fail-closed result collector and immutable manifest | No success without all planned tops, checkers and artifacts |
| T-REF-01 | Artifact provenance | Frozen input/coefficient bytes, widths, canonical hashing, row counts and generator metadata | Independent artifact checker; AC1-AC5 | Every selected vector and artifact field; no silent promotion |
| T-REF-02 | Independent arithmetic | Signs, ties, extrema, exact products, qcoef and no-suppression masks | Specification-based arbitrary-integer calculations; hand-derived anchors | All sign/tie/boundary classes; independent of C++ helper implementation |
| T-REF-03 | Transform reference | DC, impulse, complex tones and basis inputs before windowing; stage scaling and twiddle axes | Exact anchors and integer transform checker; floating DFT only for diagnostic tolerance | Forward/inverse direction, axes, ordering and stage-rounding witnesses |
| T-REF-04 | Quality qualification | THR2=0 on each admitted nonzero vector; full-tail error against delayed input | Independent exact error sums and reviewed quality-bound identity | Each no-suppression vector has a valid bound; no guessed tolerances |
| T-REF-05 | Dynamic adapter | Two or more thresholds in flight, reset/source epochs, stream chunk boundaries, metric clear | Public frame/ring API adapter versus static batch special case and independent logical schedule | Static reduction agrees; dynamic ownership and cancellation checked |
| T-REF-06 | Normative suite admission | All required classes in PDF 8.1, declared generator/seed/phase/length/protection/tail policy | Manifest review and reference qualification | Missing classes block suite completion; historical names do not define parameters |
| T-AR-01 | Rounding and saturation | Positive/negative ties and neighbors, shift zero, extrema and one-step-outside range | Independent widened-integer expected value and overflow indication | Sign x tie relation x shift x range; no unsafe abs(min) |
| T-AR-02 | Coefficient and window widths | Qw zero/unity/maximum, twiddle +/-32768, signed 12-bit extrema | Exact product and explicit storage-width checks | Unsigned window versus signed twiddle interpretation |
| T-AR-03 | Butterfly arithmetic | Four full-width products, cancellation, axes, zero-B, stage scaling and saturation stress | Independent complex arithmetic with rounding only at specified cuts | Operand sign/zero x twiddle axis x forward/inverse x stall |
| T-AR-04 | Hermitian canonicalization | Asymmetric conjugate pairs, odd signed sums, DC/Nyquist imaginary input | Exact pair-average/difference and mirror rules | Every unique/mirror index class; rounding boundaries |
| T-AR-05 | Magnitude and mask | Full 56-bit squared sums, THR2=0/max, mag2 below/equal/above threshold, protected DC | Unsigned integer mask/statistics oracle; equality kept | Self-conjugate/interior x eligible x threshold relation x mask |
| T-AR-06 | Error/statistic arithmetic | Signed error extrema, weighted spectral sums, max and aggregate carries | Independent unbounded sums plus specified low-word/overflow projection | Count, carry, clear, wrap/saturate policy per counter |
| T-XF-01 | FFT frame | Zero, impulse, tones and random legal frame samples; back-to-back frames | Exact normalized custom FFT reference at every bin | All 256 bins and 8 stages; bit reversal; final beat |
| T-XF-02 | IFFT frame | Hermitian masks, axis coefficients, sparse/dense spectra and zero spectra | Exact unscaled IFFT reference including imaginary diagnostic | All bins; stage growth; no blanket imag==0 assertion |
| T-XF-03 | Frame protocol | Input/output bubbles; stalled first/middle/final beat; malformed index/last when defined | Frame identity/count/order and stable-payload monitors | Offset/bin boundary x last x stall x reset; specified errors only |
| T-XF-04 | Transform storage | Repeated transforms, RAM address reuse, pipeline stalls, clear during read/compute/write/output | Tagged frame scoreboard and RAM/port ownership assertions | Read latency, all butterfly phases, full stage transitions |
| T-C-01 | Static complete core | Every admitted frozen vector, matching coefficients and threshold, full-tail policy | y/bin/frame/metric scoreboards; AC6-AC12 and AC14 | No mismatch, exact counts, no unexpected overflow |
| T-C-02 | Finite geometry | Ns=1,2 and neighborhoods of H,L,D; long records crossing memory wraps | Independent active-frame set and Ny formula; emit-before-add WOLA | Include H+2 and L+2 transitions; no phantom zero-window edge frame |
| T-C-03 | Core flow control | Gapped inputs, output stalls including final y, queued frames and metadata full | Accepted trace invariant under legal stalls; stability and completion checker | Empty/one/full metadata queue; simultaneous push/pop; final output hold |
| T-C-04 | Frame-owned threshold | Shadow writes, commit before/on/after admission, multiple in-flight thresholds | Independent control model and per-frame oracle; old/new edge policy reviewed | Commit x queue occupancy x canonical output stall |
| T-C-05 | Core reset and clear | Hard reset, datapath clear, sticky clear and applied metric clear at pipeline boundaries | Reset-scope ledger and corresponding checker restart/cancellation | Each clear type x idle/input/transform/WOLA/output-held |
| T-C-06 | Tagged histories | More than two wraps of 512-entry input history and 1024-entry delayed history; output lag | Independent absolute-index history and core-local backpressure checker | Occupancy boundaries, tag match/miss, no unread overwrite |
| T-C-07 | Fault handling | Defined malformed indices/tail geometry; arithmetic out-of-contract stress; history fault | Expected owning fault flag/fail-stop; no invented numeric pass after overflow | One fault class at a time then scoped combinations; recovery |
| T-C-08 | Metric commit boundary | Hold public y while a completed sample commits internally; clear around commit | Separate metric-commit/output-accept ledgers, exact epoch totals | Pending/read/commit/output-held x clear; no double count |
| T-S-01 | Source normalization | Distinct source patterns, audio 16-to-12-bit ties, ADC 0/2048/4095, manual ADC | Independent adapter math and accepted sample stream | All selected modes; sign/channel/order; manual path excluded from DSP |
| T-S-02 | Epoch and recovery | Source switch, idempotent request, gaps/duplicates, readiness/grant loss and rearm | Source lifecycle model, first cause latch, explicit cancellation | Fault x source x first/running x pending work;4096-cycle settle |
| T-S-03 | Audio peripheral | I2C ACK/NACK, left/right-distinct I2S, partial frame, BCLK stop/return, FIFO pressure | WM8731 BFM, complete-frame sequence and CDC-event accounting | Word/edge alignment; enable/grant/lock x RX/TX occupancy; TX only enabled profile |
| T-S-04 | ADC peripheral | Command/channel priming, first conversion, delayed DOUT, abort, manual/continuous request | LTC2308 BFM and source adapter checker | Channel x prime/valid x phase x re-entry; no assumed extra clock domain |
| T-S-05 | Clock/reset/FIFO | Independent audio clock phases, reset release at both edges, FIFO full/empty/wrap | Four-state monitors and specified coordinated-reset protocol | Clock ratio/phase x FIFO boundary x permitted reset class |
| T-S-06 | Core noninterference | Paired runs with identical admitted source/control but contrasting telemetry/DDR pressure | Cycle/transaction core traces match after aligned accepted start | No-pressure versus sustained-pressure; legal live-source cases; transport-start precondition explicit |
| T-CTL-01 | CSR bus adapter | Full byte address, alignment, byteenable, burst, read/write conflict, stalls | One accepted request/response and local-reject accounting | Every access class and defined invalid class; no truncated-address alias |
| T-CTL-02 | CSR state ownership | Shadow/commit, snapshots, read-only writes, protected fields and safe boundaries | Independent register/control predictor using source contract | All implemented CSR rows x access/commit class; unused bits |
| T-CTL-03 | Control collisions | Commit/clear/reset coincidences and simultaneous reject sources | Owner-local precedence tables; open policies resolved before expected verdict | Critical pairwise collisions; exactly counted independent rejects |
| T-TEL-01 | Packet content | Synthetic known sample/bin/frame taps; WAVE, SPEC64, SPEC129, METRICS, STATUS | Independent byte/payload oracle and decoder cross-check | All fields, endian/sign, timestamps, clipping, scaling and flags |
| T-TEL-02 | FIFO arbitration | All priorities, full queue, protected head, equal priority, simultaneous pop/admit | Whole-record/slot ownership model and terminal-reason ledger | Incoming/resident priority x occupancy x pop; oldest eligible eviction |
| T-TEL-03 | Partial and reset | Discontinuity, disable or soft reset during collection and selected record | Packet-boundary and reset-scope checker | Partial collection/queued/selected/stalled-last x control event |
| T-TEL-04 | Snapshots and cadence | Metric clear, changing counters, status/metrics cadence and packet enables | Profile-derived schedule and coherent snapshot oracle | Raw request versus applied clear; each profile's effective rates |
| T-TEL-05 | Loss accounting | Incoming drop, resident eviction, malformed drain, epoch abandonment, reset discard | Separate packet/tap/candidate terminal reasons and documented counter projections | Each loss cause; simultaneous causes; counter boundaries |
| T-DDR-01 | Record geometry | Payload lengths around word/64-byte limits; exact-end fit; range/alignment rejection | Independent byte-addressed memory and align64 extent calculation | Each payload type x alignment x physical tail |
| T-DDR-02 | WRAP/free space | Needed extent versus free bytes at -64/0/+64; WRAP then normal success/failure | Guard-aware reservation and independent WRAP publication ledger | Tail+normal admission; W retained after published WRAP; seq only normal |
| T-DDR-03 | Bus completion/error | Bounded waitrequest, delayed OKAY/SLVERR, error at first/middle/final beat | Outstanding-beat and publication scoreboard in generic-response mode | Every beat class x stall/error; unsupported response timing declared |
| T-DDR-04 | Ring ownership | Snapshot W, commit Rd, backward/unaligned/ahead Rd,64-bit carry, rearm | Absolute-pointer predictor and legal CSR ownership | Empty/full/guard boundary; torn-read resistance; seq wrap |
| T-DDR-05 | Transport lifecycle | Disable/reset/reconfiguration with queued or outstanding record/response | Transport-epoch ledger and explicit local precedence | Before accept/await response/before commit/after WRAP; late response policy |
| T-DDR-06 | Board-wrapper contract | Range legal/illegal writes through actual wrapper acceptance response | Registered local-response checker; declared memory-visibility assumption | Accept then next-cycle response; no claim of physical DDR completion |
| T-SW-01 | HPS record consumer | Malformed committed headers, WRAP, padding, short/invalid extent, failed UDP send or Rd commit | Real parser/consumer with independent backend and byte checks | All validation branches and send/commit outcomes |
| T-SW-02 | Command sessions | Retries, conflicting duplicates, stale/new/half-range/wrapped sequences, peer/session change | At-most-once side-effect ledger and exact result cache semantics | Every command state x sequence class x session x cache residency |
| T-SW-03 | Dashboard/protocol | Valid/invalid packets, sequence gaps/reorder/duplicates, capture replay, reserved bits | Independent fixtures and decoded-value expectations | All types/flags, exact lengths and allowed STATUS patches |
| T-SW-04 | Driver/platform | Exclusive owner, mmap/ioctl bounds, reservation, grant acquire/revoke and cleanup | Driver tests in qualified kernel context plus board evidence | Success/failure cleanup; readback; userspace mocks labeled separately |
| T-PHY-01 | CDC/RDC structure | Actual crossing inventory, resets, Gray pointers, reconvergence and false paths | Structural review/report with path-specific dispositions | Every crossing and reset domain; no simulation-as-metastability proof |
| T-PHY-02 | Fitted timing | Selected source/profile, generated clocks, external IO, Gray skew/payload paths | Per-corner STA, unconstrained-path and exception review | All required clock/path groups and physical corners |
| T-PHY-03 | Vendor-model boundary | Qualified PLL/HPS/DDR models or explicitly bounded wrapper substitution | Interface assumptions and observable functional checks | Identify each omitted/vendor block and resulting limit |
| T-BRD-01 | BRAM board qualification | Each required frozen vector under deterministic capture and full tail | Complete y/frame/metric/bin evidence required by spec AC13 | Exact capture counts; no dropped/decimated required data; DDR visibility evidence |
| T-BRD-02 | Live audio demonstration | Known line-level source after BRAM baseline passes | Measured source timing and captured waveform/source-health comparison | Separate live-source gate; no repeatability assumed from analog input |
| T-BRD-03 | Optional ADC demonstration | Known in-range analog signal and channel/manual behavior | Measured pin timing, normalization and source-health evidence | Optional profile only; board analog evidence explicit |
| T-EXT-01 | Future zero-aware IFFT | Only after baseline: original and modified datapaths at identical inputs/THR2 | Bit-exact equivalence plus real gated-operation counts | Zero-B per stage x original/optimized; no electrical saving inferred |
| T-EXT-02 | Future activity export | Qualified representative workload, stable interval, fixed trace scope | Run manifest, signal mapping and activity coverage review | Tool power estimate kept separate from measured board energy |

## Required combinations

Directed boundary cases run before constrained random stress. Mandatory crosses
include bin class x threshold relation x protection; frame configuration x queue
occupancy x stall; reset class x outstanding transaction class; packet priority x
FIFO occupancy x simultaneous pop; ring tail x free-space boundary x error beat;
and command sequence class x session x retry result.

Each cross has an explicit finite bin set and reachable combinations. Invalid
combinations are reviewed as illegal or out of scope rather than left as silent
holes. Random seeds supplement those bins; increasing seed count does not replace
a missing directed equality, final-beat stall, or reset collision.

For finite-stream lengths include 1, 2, H-2, H-1, H, H+1, H+2, L-2, L-1, L,
L+1, L+2 and supported longer lengths. H+2 and L+2 matter for the quantized
window's active-frame rule. Input zero-extension ticks and WOLA-only drain ticks
have separate driver phases and counters.

Saturation and 64-bit counter boundaries may need reviewed unit-level state
fixtures or genuinely supported parameter reductions. Record the initialized
state, its invariant checks, and why the target state is reachable. Such a
fixture checks local boundary behavior; it does not prove natural full-system
reachability or authorize modifying the production RTL. Do not assume a small FFT
parameter is supported by every generated baseline module.

Metric-clear scenarios T-C-05 and T-C-08 distinguish direct CORE injection from SOURCE-qualified application. For delay/error metrics, model blocked requests/commits and preserved pending data. For MAG2, cross clear with no accepted bin, first/interior/final accepted bin and frame tracking; accepted-bin updates can supersede accumulator clears in the current RTL. Resolve O-05 in [decisions and open items](decisions_and_open_items.md) before treating that behavior as the required policy. One shared clear timestamp does not imply identical reset semantics for every accumulator.

## Replay and failure reduction

A random failure retains all seed streams, the actual stimulus/event trace,
applied controls, accepted transaction ledger and first divergent boundary.
Minimize it by reducing data length, optional controls or stall schedule while
preserving the same failing checker. Keep the original run alongside the reduced
case and add the reduced scenario as a directed regression after the bug is fixed.

Tests expected to abort never satisfy positive completion requirements. Tests
expected to complete must drain all required scoreboards and pass the appropriate
core/system/board completion definition. The runner policies and evidence fields
are in [coverage and signoff](coverage_and_signoff.md).
