# Requirements traceability matrix

This is the requirement design matrix, not a coverage report. The [first
executed campaign](../results/verification_baseline_20260915.md) supplies partial
evidence for selected families; full requirement closure remains open. A row is
complete only when it links a qualified checker and every applicable mandatory
test instance to immutable evidence for the current source/configuration. A historical PASS, source hash or documentation
review alone cannot close a functional requirement.

## Authorities and checker identities

Core PDF section references use the printed section numbers of the
[integrated specification](../specs/README.md), not PDF viewer page numbers.
Executable fields come from the [shared contracts](../architecture/generated_contracts.md).
System rules are detailed in [interfaces](../architecture/interface_contracts.md),
[source health](../architecture/source_health.md),
[DDR ownership](../architecture/de1soc_ddr_ring_ownership.md),
[command handling](../architecture/de1soc_command_path.md),
[physical timing](../architecture/physical_timing.md), and their source RTL.
Known disagreements are recorded in [open items](decisions_and_open_items.md).

| Scoreboard ID | Responsibility |
| --- | --- |
| SB-ART | Independent artifact/schema/encoding/hash/provenance validation |
| SB-NUM | Independent integer qualification and exact C++/RTL numeric comparison |
| SB-GEO | Accepted stream, frame/window geometry, logical WOLA and completion |
| SB-MET | Independent time-error/spectral statistics by their actual commit epochs |
| SB-SRC | Raw-source normalization, admission, sequence and recovery |
| SB-CTL | Register/control predictor, request/application distinction and snapshots |
| SB-TEL | Independent packet byte/field/timestamp construction |
| SB-LOSS | Per-layer conservation and terminal-reason/counter projection |
| SB-DDR | Byte-addressed memory, bus responses, pointer and record publication |
| SB-SW | HPS/PC parsing, UDP and platform software contract checking |
| SB-CMD | Peer/session/sequence and command side-effect lifecycle |
| SB-EVID | Test inventory, enabled checks, coverage, watchdog and evidence validation |

Property IDs are defined in the [assertion catalog](assertion_catalog.md);
test-family IDs in the [test catalog](test_catalog.md). Additional requirement
rows can be introduced when a contract decision adds behavior, without reusing
an existing ID for a different meaning.

## Requirement-to-test mapping

| Requirement | Required behavior | Authority | Checker/property | Tests | Mandatory coverage focus |
| --- | --- | --- | --- | --- | --- |
| R-AUTH-01 | Versioned expected behavior and immutable inputs | PDF; generated contracts | SB-ART | T-REF-01, T-ENV-03 | All selected revisions, hashes, widths and artifact rows |
| R-REF-01 | Reference qualified independently before prediction | PDF 3-8; reference public APIs | SB-NUM, SB-ART | T-REF-02, T-REF-03, T-REF-05 | Primitive/frame/finite checks; dynamic adapter static-equivalence witness |
| R-REF-02 | All required vector classes admitted; no invented quality bounds | PDF 8.1-8.4 | SB-ART, SB-MET | T-REF-04, T-REF-06 | Every mandatory class and no-suppression bound |
| R-NUM-01 | Correct signed/unsigned coefficients and width schedule | PDF 3.3-3.5 | SB-NUM, P-NUM-03 | T-AR-02 | Window 0/unity; twiddle +/-unity; full input extrema |
| R-NUM-02 | Exact shifts, ties-away rounding and defined saturation | PDF 3.1-3.4 | SB-NUM, P-NUM-03 | T-AR-01, T-AR-03 | Sign x tie x shift x boundary |
| R-NUM-03 | Custom FFT/IFFT graph, normalization and ordering | PDF 4.2,4.6,6 | SB-NUM, P-CORE-02 | T-XF-01, T-XF-02, T-XF-04 | All bins/stages, direction, ROM axes, RAM phases |
| R-NUM-04 | Canonicalization precedes full-width mask decisions | PDF 4.3-4.5 | SB-NUM, P-NUM-01, P-NUM-02 | T-AR-04, T-AR-05 | Conjugate/self-conjugate x signed tie x threshold relation |
| R-NUM-05 | Correct final/preliminary mask, protection and weighted statistics | PDF 4.5,5,7.1 | SB-NUM, SB-MET, P-NUM-02 | T-AR-05, T-AR-06, T-C-01 | Eligible 128/unique 129; interior weight 2; endpoint weight 1 |
| R-NUM-06 | Exact synthesis, OLA and final output rounding | PDF 4.6,5 | SB-NUM, SB-GEO, P-CORE-06 | T-C-01, T-C-02 | Overlap phases, startup/tail and output saturation |
| R-NUM-07 | No unexpected overflow on normative vectors | PDF 3.1,3.4,8.4 AC14 | SB-NUM, P-NUM-03 | T-C-01, T-C-07 | Frozen headroom cases; separately classified stress flags |
| R-GEO-01 | Window-active finite geometry and pure drain | PDF 2.2-2.3,5; BRAM path | SB-GEO, P-CORE-03, P-CORE-05 | T-C-02 | Ns=1/2, H+1/H+2, L+1/L+2, long wraps |
| R-GEO-02 | Delayed reference and exact full-tail error metrics | PDF 5.1,7.2 | SB-GEO, SB-MET | T-C-01, T-C-08 | All Ny samples scored; startup reference and post-input tail zero extension |
| R-FLOW-01 | Atomic input acceptance and tagged history ownership | Core/source integration; storage schedule | SB-GEO, P-CORE-01, P-CORE-06 | T-C-03, T-C-06 | Full/empty and pointer reuse; delayed output pressure |
| R-FLOW-02 | Stable streams and no duplicated/missing work | Module APIs and core RTL | SB-GEO, P-OBS-01, P-RV-01, P-CORE-02 | T-XF-03, T-C-03 | First/middle/last stall; consecutive identical accepted values |
| R-FLOW-03 | Each frame owns its threshold snapshot | Core RTL; CSR commit contract | SB-CTL, SB-NUM, P-CORE-04 | T-C-04, T-CTL-02 | Commit timing x queue occupancy x old frame in flight |
| R-FLOW-04 | Correct internal metric commit versus public output acceptance | Delay/error block; core statistics contract | SB-MET, P-CORE-07, P-TEL-04 | T-C-08 | Clear x pending request/commit/held y; local MAG2 policy separate |
| R-FLOW-05 | Exact completion and no premature done | BRAM path; PDF 8.4 AC7/AC9/AC13 | SB-GEO, SB-DDR, P-CORE-08 | T-C-03, T-BRD-01 | Source/core/system completion distinctions; final y held |
| R-SRC-01 | Correct source normalization and mode selection | PDF 9; source-health policy | SB-SRC, P-SRC-01 | T-S-01 | Audio ties; ADC midscale/extrema; manual exclusion |
| R-SRC-02 | Coherent epoch change and defined recovery | Source-health and source integration | SB-SRC, P-SRC-01, P-SRC-02 | T-S-02 | Gap/duplicate/readiness loss; idempotent commit; settle |
| R-SRC-03 | Audio serialization, I2C and complete-frame transfer | Audio wrapper and bringup contract | SB-SRC, P-SRC-03, P-CDC-01 | T-S-03 | I2S L/R/edges, ACK/NACK, grant/lock, clock loss, FIFO pressure |
| R-SRC-04 | ADC protocol priming and mode behavior | ADC wrapper and source-health contract | SB-SRC, P-SRC-01 | T-S-04 | Channel/prime/abort/manual/continuous; first result |
| R-RST-01 | Reset and clear affect their specified owners | Clock/reset, source-health, local owner RTL | SB-GEO, SB-SRC, SB-DDR, P-CTRL-01 | T-C-05, T-CTL-03, T-DDR-05 | Each reset/clear x outstanding work; resolved collisions |
| R-CDC-01 | Functional CDC protocol and coordinated FIFO reset | CDC plan and active topology | SB-SRC, P-CDC-01, P-CDC-02 | T-S-05 | Clock phase/ratio x occupancy x reset sequence |
| R-CDC-02 | Structural CDC/RDC and fitted physical constraints | CDC plan; physical timing | Reviewed structural/STA evidence | T-PHY-01, T-PHY-02 | Every active crossing, clock and constrained path group |
| R-TEL-01 | Observer pressure cannot throttle admitted DSP work | PDF 13.3; source/telemetry composition | SB-GEO, P-TEL-01 | T-S-06 | Paired runs with matched source/control and aligned accepted start |
| R-TEL-02 | Packet fields, sizes, timestamps, endian/sign and flags | PDF 18-19; packet layouts | SB-TEL | T-TEL-01, T-SW-03 | All types/fields; SPEC64 buckets and SPEC129 masks; WAVE boundaries |
| R-TEL-03 | Atomic packet storage and specified arbitration | Packet FIFO RTL; interface contracts | SB-LOSS, P-TEL-02, P-TEL-03 | T-TEL-02, T-TEL-03 | Priority x occupancy x simultaneous pop/admit |
| R-TEL-04 | Loss accounting respects stage and counter semantics | Source health; packet FIFO; HPS transport | SB-LOSS, P-SRC-03, P-TEL-03 | T-TEL-05, T-SW-01 | Every terminal reason; no exact-count assumption for coalesced audio events |
| R-TEL-05 | Coherent metric/status snapshots and effective profile cadence | Core statistics; profiles; CSR map | SB-MET, SB-CTL, SB-TEL, P-TEL-04 | T-TEL-04 | Applied clear vs raw request; profile-derived period/enables |
| R-CTL-01 | Valid CSR accesses and rejection without alias/side effects | CSR map; Avalon CSR adapter | SB-CTL, P-CSR-01, P-CSR-03 | T-CTL-01 | Every implemented access class and defined invalid request |
| R-CTL-02 | Atomic shadow/commit, snapshots and owner permissions | PDF 16; command extension | SB-CTL, P-CSR-02, P-CTRL-01 | T-CTL-02, T-CTL-03 | All multiword values; safe application; local collision precedence |
| R-DDR-01 | Ring alignment, range and wrap-aware free-space admission | PDF 17-19; DDR ownership | SB-DDR, P-DDR-05 | T-DDR-01, T-DDR-02 | Exact end; guard; required extent +/-64; invalid range |
| R-DDR-02 | Accepted bus writes complete under the declared backend | Avalon master; board wrapper | SB-DDR, P-DDR-01, P-DDR-02 | T-DDR-03, T-DDR-06 | Generic responses versus local acceptance; all beat fault positions |
| R-DDR-03 | Record-level atomic publication and pointer ownership | PDF 17,19; ring-pointer RTL | SB-DDR, P-DDR-03, P-DDR-04 | T-DDR-02, T-DDR-04 | WRAP separate from normal; seq wrap; torn snapshot/illegal Rd |
| R-DDR-04 | Reset/reconfigure cannot publish stale or wrong-epoch work | DDR ownership; local owner RTL | SB-DDR, P-CTRL-01 | T-DDR-05 | Outstanding response and post-WRAP reset; late-response decision |
| R-SW-01 | HPS consumes committed records and forwards correct bytes | PDF 20-23; HPS transport | SB-SW, SB-DDR | T-SW-01 | Malformed extents, WRAP/padding, UDP failure and Rd-commit outcomes |
| R-SW-02 | Command retries are at most once in the specified session | Command version 2 contract | SB-CMD, P-CMD-01 | T-SW-02 | Duplicate/conflict/stale/wrap/half-range x peer/session/cache |
| R-SW-03 | PC decoder and playback obey the wire contract | PDF 24; packet layouts; dashboard guide | SB-SW, SB-TEL | T-SW-03 | Every type, size, sign, flag, gap/reorder and capture mode |
| R-PLAT-01 | Kernel reservation/mapping and codec-grant ownership | Linux baseline; platform grant | Kernel tests plus board evidence | T-SW-04, T-BRD-01 | Exclusive owner; mmap/ioctl bounds; revoke/cleanup readback |
| R-PLAT-02 | Model substitution limits and real DDR visibility explicit | Platform wrapper; DDR ownership | Assumption inventory plus physical evidence | T-PHY-03, T-DDR-06, T-BRD-01 | Every vendor boundary; posted-write visibility not inferred from OKAY |
| R-BOARD-01 | BRAM hardware matches mandatory artifacts before live demo | PDF 8.4 AC13; BRAM path | SB-NUM, SB-MET, complete capture | T-BRD-01 | All required vectors/artifact fields; no required observation lost |
| R-BOARD-02 | Live-source claims carry separate physical evidence | LINE-IN/ADC bringup | Measured interface and source-health results | T-BRD-02, T-BRD-03 | Only selected live profiles; ADC remains optional |
| R-ENV-01 | Checkers run, reject intentional defects and preserve evidence | This verification architecture | SB-EVID, P-OBS-01 | T-ENV-01, T-ENV-02, T-ENV-03 | Enabled/triggered checks, four-state behavior, both watchdogs |
| R-ENV-02 | Conditional progress is stated and tested without vacuity | Module interfaces; scenario assumptions | SB-EVID, P-LIVE-01 | T-C-03, T-S-02, T-DDR-03 | Fairness satisfied/violated partitions; no unconditional clock-return assumption |
| R-EXT-01 | Future zero-aware RTL preserves baseline arithmetic | Optional benchmark extension | SB-NUM plus operation counts | T-EXT-01 | Identical input/THR2; zero opportunities per stage |
| R-EXT-02 | Activity traces and electrical measurements have separate scope | Benchmark plan | SB-EVID and measurement methodology | T-EXT-02 | Workload, trace interval, mapping and uncertainty; no proxy-as-energy claim |

## Core Revision J acceptance mapping

The PDF uses historical golden-model terminology. This design requires
qualification of the maintained reference model before using that authority.
The explicit mapping below prevents a y-only comparison from claiming complete
core signoff.

| PDF criterion | Obligation | Requirements | Tests |
| --- | --- | --- | --- |
| AC1 | Required generator/vector artifacts | R-AUTH-01, R-REF-01, R-REF-02 | T-REF-01, T-REF-06 |
| AC2 | Canonical coefficient identity | R-AUTH-01, R-NUM-01 | T-REF-01, T-AR-02 |
| AC3 | Frozen input/output hashes | R-AUTH-01 | T-REF-01 |
| AC4 | Exact artifact row counts | R-AUTH-01, R-GEO-01 | T-REF-01, T-C-02 |
| AC5 | Legal unsigned 56-bit THR2 | R-NUM-04, R-CTL-01 | T-AR-05, T-CTL-01 |
| AC6 | THR2=0 keeps all eligible bins | R-NUM-05 | T-AR-05, T-C-01 |
| AC7 | Full-tail length and flush | R-GEO-01, R-FLOW-05 | T-C-02, T-C-03 |
| AC8 | Qualified no-suppression quality bounds | R-REF-02, R-GEO-02 | T-REF-04 |
| AC9 | Every RTL output sample matches | R-NUM-06, R-FLOW-02 | T-C-01 |
| AC10 | Every frame-stat row matches | R-NUM-05 | T-C-01 |
| AC11 | Every mandatory metric field matches | R-GEO-02, R-FLOW-04 | T-C-01, T-C-08 |
| AC12 | Required per-bin fields match | R-NUM-04, R-NUM-05 | T-C-01 |
| AC13 | Complete BRAM board match before live use | R-BOARD-01 | T-BRD-01 |
| AC14 | No unexpected overflow/wrap on frozen set | R-NUM-07 | T-C-01 |

## Evidence and waiver rules

Expand each family into named test instances and coverage bins before execution.
For each requirement record the applicable profile/cut, case IDs, checker and
source hashes, run IDs, raw pass/fail result, bin hits, unresolved issues,
exclusions and reviewer disposition. Code coverage is additional evidence,
not a replacement for this mapping.

Baseline, live-source, board, and future optimization scopes are explicit.
An optional ADC test omitted from a BRAM-only milestone does not count as an
ADC pass. A missing mandatory board capture blocks AC13 even if all simulation
criteria pass. Contract ambiguity is BLOCKED_CONTRACT pending a decision, not a waiver
that marks incorrect behavior correct.

The acceptance procedure is defined in
[coverage and signoff](coverage_and_signoff.md).
