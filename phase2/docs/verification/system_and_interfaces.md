# System and interface verification architecture

This document defines the verification environment for the implemented DE1-SoC system. It is a design plan, not a record of executed tests. Functional verification, structural CDC/RDC review, fitted timing, Linux deployment, and board measurements produce separate evidence. Existing directed benches are reusable starting points; their presence does not qualify the current RTL.

The contract sources are the [generated interface types](../../spec/generated/interface_types.json), [CSR map](../../spec/generated/csr_map.json), [packet layouts](../../spec/generated/packet_layouts.json), and the implementation-facing [interface contract](../architecture/interface_contracts.md). The active board uses one 50 MHz fabric domain. Audio serialization introduces BCLK domains; CSR atomicity inside the fabric is not itself a clock crossing.

## Environment boundaries and agents

Use the same transaction vocabulary at progressively wider boundaries. Unit environments isolate adapters, FIFOs, CSR access and record construction. A logical system environment joins the real source/core and telemetry/HPS RTL while modeling physical sources and memory. A board-shell environment exercises the actual wrapper ports and generated-IP interface assumptions. Host environments exercise the real C consumer and Python parser against controlled memory, MMIO and network services. Each result identifies its DUT boundary and every substituted component.

| Agent or BFM | Required behavior |
| --- | --- |
| Normalized source | Offer signed 12-bit samples with 64-bit indices; retain complete payload through stalls; distinguish offered from accepted transactions. |
| Raw live source | Emit stereo 16-bit audio or unsigned 12-bit ADC samples independently of core ready. Inject sequence gaps, duplicates, readiness loss, wrapper drops and protocol faults. |
| WM8731 peripheral | Model open-drain I2C ACK/NACK and codec-master I2S, distinguish left/right channels, preserve the one-bit I2S delay, and support partial frames, clock stoppage and restart. |
| LTC2308 peripheral | Observe CONVST, SCLK and DIN; model next-conversion channel configuration, DOUT publication delay, priming/discard, abort and recovery. Manual conversions remain distinct from periodic acquisition. |
| Clock/reset | Control fabric clock, BCLK, PLL lock, HPS reset and board controls independently; vary release phase and exercise both BCLK edges. |
| CSR master | Drive the complete Avalon request bundle, hold it during waitrequest, inject invalid accesses and pair every accepted request with its response. |
| DDR slave/memory | Maintain byte-addressed memory, apply byte enables, inject bounded stalls and response errors, and expose committed and uncommitted extents separately. |
| HPS/network | Control CSR readback, memory visibility, UDP outcomes, peer sessions, retries and malformed data while exercising production consumer/dispatcher code. |
| Linux platform | Check reservation, ioctl/mmap admission, exclusive consumer ownership and GPIO grant lifecycle with a kernel-capable environment or board. |

The [audio wrapper](../../rtl/platform/de1soc/audio_codec_wrapper.sv) owns the RX 8-by-96-bit FIFO and optional TX 512-by-33-bit FIFO. TX FIFO reads occur on rising BCLK; the serializer launches on falling BCLK. The [audio adapter](../../rtl/sources/trecap_audio_adapter.sv) owns normalization and one pending sample, not the CDC FIFO. Preserve this distinction in monitors and coverage.

Use separate DDR BFM modes. The generic writer mode returns delayed explicit OKAY/SLVERR responses. The actual board-wrapper mode returns one registered local response after acceptance or range rejection. Responses occur after request acceptance, not on that same edge. Neither mode proves physical DDR completion. Generated vendor IP must be named as modeled or simulated, never silently replaced by a stub and reported as exercised.

## Transaction identities and reset scope

Monitors attach verification-only identities without changing the product protocol. Use fabric-reset generation, source epoch, metric epoch and transport epoch as separate dimensions. Raw source sequence is not accepted DSP sample index. Frame identity includes source epoch, frame index, trigger sample index and the captured THR2 version. Candidate records receive a monitor-owned identity before FIFO admission; DDR publication adds absolute record start and the writer-owned normal sequence. Commands use bound-peer session plus command sequence.

| Operation | State affected | State that must remain separately accounted |
| --- | --- | --- |
| Fabric hard reset | Fabric state, lifetime health counters, pointers and CSR codec grant restart; local BCLK reset releases follow their own edges. | Physical GPIO ownership remains a Linux responsibility; memory bytes are not assumed erased. |
| Source change, source fault or rearm | Selected-source admission and DSP history/observation epoch follow the discontinuity protocol. | Committed DDR records, ring pointers and transport sequence are not rewound. Health lifetime counters survive. |
| Board datapath/replay abort | Source/core/replay work is invalidated through the board-owned clear. | Transport is not truncated merely because KEY[3] aborted replay. |
| Applied metrics clear | Core error metrics and telemetry eligible-bin aggregates clear together at the qualified boundary. | Source selection, ring pointers and source-health lifetime counters remain distinct. |
| Telemetry soft reset | Formatter/FIFO/writer state and transport epoch are cleared; ring configuration and consumer-epoch admission must be rebuilt. | Core arithmetic and kernel grant survive. Stored Rd is not silently rewritten; HPS must explicitly commit zero. |
| Replay telemetry flush | Uncommitted formatter/FIFO material is abandoned at the admitted replay boundary. | Committed producer/consumer pointers and sequence remain intact. |
| Ring reconfiguration | Producer/sequence restart and consumer epoch becomes invalid. | HPS owns the required new Rd=0 commit. |
| Sticky/counter clear | Only the named owner's documented flags or counters clear. | Do not treat a diagnostic clear as source rearm or transport reset. |

This table defines scope, not a universal ordering for simultaneous operations. Record each accepted request, applied event and reset separately. For counters, document width, saturation or wrap, reset owner and clear owner before writing conservation checks. See [source health](../architecture/source_health.md), [clock/reset plan](../architecture/clock_reset_plan.md), and [ring ownership](../architecture/de1soc_ddr_ring_ownership.md).

## Sources, continuity and recovery

The source scoreboard independently normalizes observed peripheral samples. Audio selects the configured channel, rounds a four-bit right shift and saturates to signed 12 bits. ADC subtracts midscale 2048 under the board profile; DC blocking is disabled. Compare wrapper-delivered, adapter-admitted and core-accepted events independently. An accepted stream is the numerical oracle input, while a separate continuity checker prevents dropped physical samples from being hidden by consecutive DSP indices.

For periodic live sources, check stop acknowledgement, 4096 fabric clocks of settling, readiness/first-sample acquisition, then running. Startup permits one second after settling; running silence is bounded by 4096 clocks, or 81.92 us. The first sample establishes sequence; subsequent raw sequence increments modulo 2^64. A detected gap blocks its offending event. Fault cause bits, epoch increment, discontinuity and stopped admission must agree. Explicit rearm does not itself prove that acquisition resumed.

BCLK loss can prevent capture-stop acknowledgement. Liveness therefore assumes the external clock returns; a stopped source must not falsely resume to satisfy a timeout. ADC readiness excludes manual mode. SW[7]=1 plus KEY[2] produces raw diagnostic conversions without STFT/WOLA admission or a nonzero periodic DSP rate. Channel changes require ADC source re-entry; verify priming and first-result discard around that transition.

Audio overflow events crossing the pulse synchronizer can coalesce. The fabric-observed overflow counter is not an exact physical lost-sample count. Check accepted CDC events, explicit drops and eventual sequence/watchdog fault separately. The RX FIFO drains while deselected; no old partial stereo frame may become the first valid sample of a new epoch. Optional LINE-OUT is best effort: a full monitor FIFO cannot throttle core y, and epoch/flush handling must prevent stale output. These policies come from [source integration](../../rtl/top/trecap_source_core_integration.sv) and [source-health semantics](../architecture/source_health.md).

Finite replay adds independent ledgers for analysis input, tail tokens, frames, output samples and metric commits. Route indices below tau_last through analysis and the remaining D tokens through WOLA drain only. For the default 4096-sample vector, expect 33 frames, 4608 outputs and 384 tail tokens. Source-done, core-path-done, DDR end-to-end completion and PC receipt are different milestones. Stall the final public output after upstream completion to expose premature done logic.

## Independent observation and record conservation

Layer scoreboards at raw source delivery, normalized acceptance, mathematical taps, formatter candidates, FIFO admission/output, Avalon writes, producer publication and HPS consumption. Monitors observe handshakes and public events; expected values must not be copied from DUT counters or internal arithmetic. Generated layout constants may be shared, but expected record bytes and parser decisions should come from independently implemented rules.

The telemetry scoreboard checks WAVE decimation and triples, SPEC64 bucket maxima, SPEC129 bins/masks, timestamps and coherent STATUS/METRICS snapshots. A raw metric-clear request is not a new metric epoch until the source/core owner applies it. Source discontinuity abandons partial collections while a selected record completes atomically; invalid metadata fields need not be zero when valid is low.

The FIFO model preserves whole-record order and protects the output head through RAM latency and stalls. On full admission, evict the oldest resident among the lowest eligible priorities below the incoming priority, excluding the protected head. Otherwise drop the incoming record. Exercise coincident head completion and admission, malformed drain and slot reuse. Never infer pre-writer loss from UDP sequence: sequence allocation belongs to the DDR publication layer.

Every candidate ends as delivered, resident, evicted, incoming-dropped, malformed-drained, epoch-abandoned or reset-discarded. Extend the ledger with DMA rejection and UDP send failure. At positive-run completion, require empty expected queues and no unexplained transactions. Counters support this ledger; they do not replace it. Relevant owners are [packet FIFO](../../rtl/telemetry/trecap_packet_fifo.sv) and [telemetry top](../../rtl/telemetry/trecap_telemetry_top.sv).

## CSR, DDR publication and software boundaries

The CSR agent checks 21-bit byte addresses before the 12-bit leaf decode: legal aperture 0x000000..0x000fff, four-byte alignment, byteenable 0xf and burstcount one. Reject out-of-window requests with DECODEERROR; malformed accesses and leaf failures use SLVERR. Rejected reads return one zero-data response; accepted writes produce one write response. A malformed simultaneous read/write request produces one read SLVERR response, not separate read and write responses. No locally rejected request reaches the leaf. Bus acceptance and safe-boundary command application remain separate events. Check shadow/commit atomicity and stable multiword snapshots through intervening activity. See the [CSR adapter](../../rtl/hps_bridge/trecap_avmm_csr_adapter.sv).

The memory scoreboard reconstructs exact little-endian 32-byte headers, payload and zero padding. Normal length is align64(32+payload_bytes), calculated without narrow overflow. A record cannot cross the physical ring end; exact-end placement needs no WRAP. Admission reserves required normal length plus physical tail when wrapping. For valid pointers, usable free space is ring size minus (W-Rd) minus the guard; the RTL free-bytes value already excludes that guard. W is FPGA-owned; Rd is HPS-owned and must be aligned, monotonic within its valid epoch and no greater than W.

WRAP and the following normal record are separate publications. Successful WRAP advances W by the physical tail to the next origin without consuming a normal sequence. If the subsequent normal record fails, that WRAP stays published: W is not rolled back. If WRAP itself fails before publication, it does not advance W. Partial bytes beyond committed W are not readable records. A normal publication increments sequence only after its writes and pointer advance succeed. Check errors on first, middle and final beats and between WRAP and normal publication using the [writer](../../rtl/hps_bridge/trecap_ddr_ring_writer.sv) and [pointer controller](../../rtl/hps_bridge/trecap_ring_pointer_ctrl.sv).

At the board boundary, legal local OKAY proves generated-bridge acceptance; SLVERR prevents out-of-range forwarding. Physical ordering and ARM visibility require separate evidence. The HPS consumer must read only committed extents, validate header/body bounds before dereferencing, omit WRAP and DDR padding, and leave DDR unchanged while patching an outgoing STATUS copy. A failed UDP attempt still consumes the record after successful Rd commit. Conversely, UDP success followed by Rd-commit failure cannot be undone; software must stop without falsely advancing local accounting. Malformed data latches once until the complete recovery sequence.

Command checks cover bound peer, RFC1982 sequence order, conflicting duplicates and byte-identical cached results without repeated application. Include pending commit timeout and failed readback, not just register writes. Kernel checks cover exact reserved-memory identity, read-only exclusive noncached mapping, ABI validation and GPIO48 ownership. Grant assertion follows acquired-low readback; revocation/readback precedes GPIO-high cleanup. Userspace RAM tests do not prove these kernel properties. See [HPS transport](../architecture/de1soc_hps_transport.md), [commands](../architecture/de1soc_command_path.md), and [platform grant](../architecture/platform_grant.md).

## Noninterference, coverage and evidence

Compare core traces under identical accepted source/control histories but contrasting packet FIFO and DDR pressure. Require identical numerical output and core metrics. Keep startup conditions explicit: board replay admission intentionally requires ready transport, so this is not an unconditional assertion that replay starts independently of transport. Subsequent congestion must not enter core ready. Optional audio monitoring and PC disconnection are separate perturbations.

Mandatory coverage crosses are:

- Source mode, fault/reset class, readiness phase and pending sample/frame/output.
- ADC channel, manual/continuous mode, priming and abort phase; audio channel pattern, BCLK phase, FIFO occupancy and grant/lock loss.
- THR2 commit or metric-clear application, queued frame ownership and downstream stall.
- Incoming/resident priority, protected head, full FIFO and simultaneous pop/admit.
- Payload boundary at 4/8/64 bytes, ring tail, guard/free-space boundary and normal/WRAP kind.
- First/middle/final write error, publication state and reset/reconfiguration request.
- Command sequence wrap/conflict, cache state, peer session and readback outcome; UDP attempt outcome crossed with Rd-commit outcome.
- Finite lengths near hop/frame boundaries, multiple memory wraps and a stalled final output.

Classify safety checks separately from liveness requiring bounded response, consumption or clock-return assumptions. Positive completion requires exact counts, drained scoreboards and a quiet interval. Functional clock-phase variation cannot demonstrate metastability safety. Structural CDC/RDC review must inspect synchronizers, reset release and reconvergence. Fitted STA independently checks clock coverage, setup/hold/recovery/removal and the [physical route allocations](../architecture/physical_timing.md). Analog timing assumptions, actual clock rates, DDR visibility, Linux lifecycle and energy remain board-measurement obligations.

## Unresolved policy and contract alignment

Before freezing expected outcomes, resolve simultaneous operations spanning different reset/clear owners; local RTL precedence is not a universal system policy. Define supported versus illegal independent FIFO-side resets and late bus responses after transport clear. Retain the current distinction between source epoch and packet sequence: Revision-G packets cannot independently reconstruct source epochs. Document physical F2SDRAM visibility assumptions rather than converting acceptance into completion. Align older interface prose with zero-rate manual/faulted live sources and profile-specific synthesized telemetry cadence. Finally, define counter/epoch exhaustion scenarios and explicit coverage exclusions for unreachable deployment limits.
