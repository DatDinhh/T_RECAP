# DE1-SoC BRAM replay path

> **Step 11 status:** `source_implemented_pending_rtl_compile_functional_verification_platform_designer_generation_quartus_timing_and_hardware_evidence`

Step 11 closes the checked-in source hierarchy from deterministic BRAM input through the
mathematical core, real telemetry taps, the HPS bridge, and the DDR writer. The machine-readable
authority is `config/boards/de1soc_bram_replay_path.json`; its schema is
`spec/schemas/de1soc_bram_replay_path.schema.json`. The source-only gate is
`scripts/check_bram_replay_path.py`.

This milestone does **not** claim that RTL compiled, that the regression passed, that Platform
Designer generated successfully, that Quartus compiled or closed timing, or that a DE1-SoC wrote
records into HPS DDR. Those evidence fields remain false until the corresponding tools and
hardware actually run.

## Two integration boundaries

Step 11 deliberately has two compositions:

| Boundary | Module | Purpose |
| --- | --- | --- |
| Pin-agnostic | `trecap_bram_replay_system_top` | Direct RTL regression/capture boundary with CSR, Avalon-MM DDR, `y`, replay status, and transport status ports. |
| Physical board | `de1_soc_trecap_top` | DE1-SoC clocks, reset, HPS pins, Platform Designer wrapper, LEDs, audio, ADC, source/core, telemetry, and DDR wiring. |

Each composition owns one `trecap_source_core_integration` and one
`trecap_de1soc_full_top`. The only mathematical core is inside the source/core owner. The
standalone `trecap_core_telemetry_top` must not be added to either hierarchy because that would
instantiate a second mathematical core.

The pin-agnostic top sets `RESET_SOURCE_MODE=TSRC_BRAM_REPLAY`, but it does not fabricate a
hardware profile-lock bit. Runtime source selection remains the generated CSR contract:

```text
ctrl.source_mode + source_mode_apply_pulse
  -> trecap_source_core_integration
  -> trecap_source_mux
```

The Step-11 profile and reset default select BRAM replay. A replay start is accepted only while
BRAM mode is actually active and the source/core path is safe. A later valid CSR source-mode
commit remains legal; it is not silently ignored or locally rejected by an invented lock.

## Replay admission and STATUS correlation

An explicit replay request remains visible to the source/core owner on `replay_start_i`. It is
not hidden behind a top-level busy gate. A separate `replay_start_admit_i` qualifies acceptance:
the composition requires a configured STATUS-only transport, `transport_epoch_idle_o` (writer
idle and no queued FIFO record), and no E2E epoch already in flight. The source owner also
requires active BRAM mode and a safe idle datapath. A denied explicit request therefore produces
`replay_start_reject_pulse_o` evidence instead of disappearing.

An accepted start asserts `external_telemetry_flush_i` to discard only uncommitted
packetizer/FIFO state and starts a fresh correlated E2E epoch. It must not assert
`external_transport_clear_i`: committed producer, consumer, and sequence state must not rewind.
In the pin-agnostic top, explicit clear or `enable_i=0` is the replay/core/E2E abort and rearm and
may perform the coordinated transport clear. The frozen HPS `TELEMETRY_SOFT_RESET` command remains
transport-only; it is not silently widened into a replay rearm. On the board, dedicated debounced
`KEY[3]` clears only source/core/E2E state. It must not pulse `external_telemetry_flush_i` while a
writer record might be in flight; telemetry, FIFO, writer, and committed ring state are preserved.
The next accepted replay—already gated by `transport_epoch_idle_o`—performs the safe telemetry-only
flush. `KEY[2]` retains its existing ADC manual-request role.

Periodic `status_tick_i` requests are suppressed while replay is busy. The successful
`replay_path_done_pulse_o` injects the replay-correlated post-core STATUS request, so an unrelated
pre-run or periodic STATUS record cannot satisfy Step-11 completion.

## End-to-end data paths

The algorithm path is:

```text
x_in.memh
  -> trecap_bram_replay_source
  -> trecap_source_mux
  -> trecap_core_top
  -> public y valid/ready sink
```

The observation and transport path is:

```text
real core sample/frame/bin taps and counters
  -> trecap_de1soc_full_top
  -> trecap_telemetry_top
  -> packet scheduler and packet FIFO
  -> trecap_hps_bridge_top
  -> trecap_ddr_ring_writer
  -> Avalon-MM write master
  -> platform_designer_wrapper
  -> generated F2SDRAM bridge
  -> HPS DDR3
```

These are real `trecap_core_top` taps. A board-local synthetic tap generator is forbidden.
Telemetry is a valid-only observer. Packet-FIFO, DDR-writer, HPS, and Platform Designer
backpressure may stall or drop transport records according to their own contracts, but none of
those ready signals may drive source/core readiness or the mathematical `y` path.

The pin-agnostic top leaves `y_ready_i` under the test/capture sink's control. The physical board
ties `y_ready_i` to one so optional telemetry or audio monitoring cannot stall the core.

## Three completion levels

The three completion signals are intentionally different:

| Signal | Meaning | Allowed to declare full Step-11 PASS? |
| --- | --- | --- |
| `replay_done_o` / `replay_source_done_o` | The final BRAM/zero-flush source token was accepted. A final WOLA or public `y` beat may still be pending. | No. |
| `replay_path_done_o` | The source is done, the source/core/`y` path is quiescent, all exact geometry counters match, accepted `y` indices were contiguous, and no replay/core fault exists. Its scope stops at the mathematical core output. | No; this proves only the BRAM-to-core subpath. |
| `replay_e2e_done_o` | Core-path completion was followed by a new STATUS record normal-committed through telemetry and the DDR writer, with producer/DMA advance, writer idle, and no path/transport fault or drop. | Yes; this is the Step-11 end-to-end authority, after a functional gate observes it. |

`p_replay_exact_completion` in `trecap_source_core_integration` is the core-path completion monitor.
It starts an epoch only on an accepted replay start and independently counts public output
handshakes:

```text
accepted_y = y_valid_o && y_ready_i
```

Every accepted output must have `y_sample_idx_o` equal to the current accepted-output count. A
skipped, repeated, or out-of-order index sets `replay_completion_error_sticky_o`.

For a finite stream:

```text
Nframes  = floor((Ns + L - 2) / H)
tau_last = Nframes * H
Ny       = tau_last + G + L
D        = G + L
```

Exact completion requires all of the following at the same quiescent replay epoch:

```text
replay_done_o                              == 1
replay_core_output_accept_count_o          == Ny
replay_output_accept_count_o               == Ny
wola_output_count                          == Ny
core_sample_count_o                        == tau_last
core_frame_count_o                         == Nframes
core_error_sample_count_o                  == Ny
replay-epoch metric-commit count           == Ny
replay_active/source_valid/core_busy/y_valid == 0
replay/core/build fault set                 == 0
```

`replay_path_done_o` is a retained level; `replay_path_done_pulse_o` marks the successful
transition. If the source becomes quiescent with a bad count or fault, the monitor sets a sticky
completion error and deliberately keeps the epoch busy until clear or reset. That fail-closed
behavior prevents an incomplete run from becoming PASS or silently restarting.

The reusable `trecap_bram_replay_e2e_supervisor`, instantiated as
`u_replay_e2e_supervisor` by `trecap_bram_replay_system_top`, owns the stronger transport
supervision. Its sequential block is `p_replay_e2e_completion`. On the cycle after an accepted
start flushes uncommitted telemetry state it records the drop-counter baselines. When `replay_path_done_o`
establishes the exact core result, it snapshots the post-core producer pointer and DMA packet
count. Fault and transport-clear inputs are latched both on the accepted-start edge and during that
following baseline-capture cycle; there is no one-cycle baseline blind window. It then requires
all of the following:

```text
one new STATUS record for the completed replay epoch
one new normal DDR-ring commit after core-path completion
producer_ptr_o advanced from the post-core baseline
dma_packet_count_o advanced from the post-core baseline
writer_busy_o == 0
packet_fifo_drop_count_o == 0
dma_drop_count_o == 0
no replay/core/build/telemetry/DDR fault
```

A source-done event, core-path-done without a later STATUS commit, WRAP instead of normal commit,
unchanged producer/DMA state, a busy writer, any drop, or any replay/core/transport fault cannot
assert `replay_e2e_done_o`. `replay_e2e_done_pulse_o` marks the successful transition;
`replay_e2e_error_sticky_o` records a failed epoch. Like the core-path monitor, a failed E2E epoch
stays busy until clear or reset so failure cannot decay into PASS.

The DDR write master serializes every single-beat write through an explicit response wait and does
not report record completion until every beat, including the final beat, receives a successful
local response. On the physical DE1-SoC
boundary, the generated HPS F2SDRAM interface exposes `waitrequest` but no downstream response
channel. `platform_designer_wrapper` therefore returns exactly one registered local `OKAY` after a
legal beat crosses that bridge-acceptance boundary, or `SLVERR` when its 64-to-32-bit range guard
rejects the beat. This prevents a late local range error from following producer-pointer commit,
but it is not proof of physical-DRAM completion or downstream DRAM health. Hardware DDR/HPS capture
remains a separate required evidence gate.

`replay_e2e_done_o` is retained historical terminal evidence for the correlated replay and STATUS
epoch; it is not a live global-transport-health signal. Because the write master serializes local
responses, terminal success has no response outstanding for any Avalon-MM beat belonging to that
STATUS record. A later unrelated periodic transport fault is reported through the normal transport
fault and status channels and does not retroactively revoke the completed replay epoch. A new
accepted replay epoch, or the defined source/core clear/rearm, clears and invalidates the retained
epoch result as specified above.

A denied extra start remains visible through command-reject telemetry but does not corrupt an
already accepted epoch; only data-integrity and transport faults block its E2E result.

## Board profile: zero vector

`config/profiles/de1soc_bram_replay.json` remains the first board profile:

| Field | Required value |
| --- | --- |
| Vector | `zero_Ns4096_thr0` |
| Input | `artifacts/test_vectors/zero_Ns4096_thr0/x_in.memh` |
| `Ns` | 4096 |
| `Nframes` | 33 |
| `tau_last` | 4224 |
| `Ny` | 4608 |
| `THR2` | 0 |
| Telemetry | `telemetry_status_only` |
| DDR/UDP | Enabled by profile; runtime ring configuration is still required |
| Start | Debounced `KEY[1]` press |
| Abort/rearm | Dedicated debounced `KEY[3]`; source/core/E2E only, all transport state preserved |

Board-visible exact replay state is:

| Output | Binding |
| --- | --- |
| `LEDR[8]` | `replay_e2e_busy` |
| `LEDR[9]` | `replay_e2e_done` |
| `LEDR[7]` | Aggregate fault, including core-path and E2E completion errors |

The earlier source-only `replay_done` and core-only `replay_path_done` are not PASS LEDs. They
remain internal/SignalTap observability for diagnosing which layer stopped.

## RTL regression: impulse vector

The Step-11 regression source is separate from the boring zero-vector board profile:

| Field | Required value |
| --- | --- |
| Testbench | `sim/tb/tb_trecap_step11_bram_e2e.sv` |
| Filelist | `sim/filelists/step11_bram_e2e.f` |
| DUT | `trecap_bram_replay_system_top` |
| Vector | `impulse_Ns1024_thr0` |
| Input | `artifacts/test_vectors/impulse_Ns1024_thr0/x_in.memh` |
| Expected output | `artifacts/reference_outputs/impulse_Ns1024_thr0/y_out.memh` |
| `Ns` | 1024 |
| `Nframes` | 9 |
| `tau_last` | 1152 |
| `Ny` | 1536 |
| `THR2` | 0 |

The testbench must compare every accepted `y` sample and index, prove that source-done is not
treated as test completion, and observe exact core path-done. It must rely exclusively on
`replay_path_done_pulse_o` auto-injection for the post-completion STATUS request; a redundant
manual `status_tick_i` pulse after path-done is forbidden. The test then waits for
`replay_e2e_done_o` only after the normal DDR commit, producer/DMA advance, and writer-idle checks.
Its DDR model injects delayed `OKAY` responses on the positive epoch and a delayed `SLVERR` in a
negative epoch to prove that response failure cannot advance the producer or assert E2E done.
Merely compiling this testbench is not a functional result.
The contract records `regression_result_recorded=false` until a supported simulator produces a
real PASS log.

## Reference source and artifact status

The current software reference source is maintained under `sw/reference_model/`.
Its snapshot and the promoted root artifacts are recorded by the reference-import
manifests. The included integrated specification is identified in
[docs/specs/README.md](../specs/README.md).

The supplied reference source has been reconciled with the integrated tree.
Historical archive observations are not the active source identity and are not
an additional missing-input requirement. Keep provenance claims limited to the
source snapshot and artifacts actually recorded in the repository.

Zero and impulse development vectors help explain wiring, indexing, full-tail
behavior, and transport integration. Their existence is not a claim of full
algorithm coverage or hardware completion. A source reconciliation also does
not establish new simulation, synthesis, or board results.

## Source-only check

Run from the repository root:

```bash
python3 scripts/check_bram_replay_path.py
python3 scripts/check_bram_replay_path.py --force-fallback-schema
```

The second command forces the dependency-free schema validator even if `jsonschema` is installed.
The checker validates committed JSON, vector hashes/geometry, instance and port structure, the
core-path and E2E completion supervisors, board indicators, real tap/telemetry/HPS/DDR wiring, and Step-11
testbench/filelist intent.

It does not invoke a simulator, Platform Designer, Quartus, TimeQuest, or hardware. A PASS means
only that the checked-in source agrees with the frozen Step-11 source contract.

## Evidence still required

Before Step 11 can be called functionally complete, record separate evidence for:

1. RTL compilation of the Step-11 filelist.
2. A passing impulse regression with exact output, index, count, tap, telemetry, and DDR-request checks.
3. A passing zero-vector regression or board capture with the same exact-completion rules.
4. Platform Designer construction and HDL generation.
5. Full Quartus compilation and TimeQuest timing closure.
6. DE1-SoC replay with verified CSR configuration and loss-accounted HPS DDR capture.
7. A provenance-verified reference archive import before any algorithm/signoff claim.

Until those records exist, `rtl_compile`, `functional_verification`,
`platform_designer_generation`, `quartus_compile`, `timing_closure`, hardware replay/capture, and
`hardware_signoff` remain false by contract.

## Step-14 CSR command extension

Step 14 adds a remote request path without changing the Step-11 replay owner.
`START_BRAM_REPLAY` writes W1P `REPLAY_CONTROL.start`; the raw request reaches the
owner even when `start_ready=0`, allowing an observable accept or reject. The CSR
bank retains mutually exclusive `REPLAY_STATUS.last_accept`/`last_reject`, clears
`pending` on feedback, and increments `result_epoch` for each completed
CSR-originated request. A board-key replay cannot complete or overwrite a pending
CSR command result.

The HPS bridge snapshots the epoch, pulses start, then waits for pending clear
and an epoch change with a bounded timeout. `REPLAY_CONTROL.rearm` uses the same
replay-clear owner as the documented local rearm input and does not clear
transport counters. The Step-14 structural/model gate is:

```bash
python3 sim/check_step14_command_rtl.py
```

That Python gate checks source structure and an executable model only. It does
not compile or simulate SystemVerilog and is not replay hardware evidence.
