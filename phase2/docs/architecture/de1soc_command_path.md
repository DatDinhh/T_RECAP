# DE1-SoC PC command path

File class: `[1]` hand-written architecture documentation.

This document defines architecture implementation Step 14. The machine-readable
authority is `config/boards/de1soc_command_path.json`; its schema is
`spec/schemas/de1soc_command_path.schema.json`, and its source gate is
`scripts/check_command_path.py`.

## Scope and authority

The reverse path is an architecture path, not a dashboard convenience:

```text
PC command client
  -> UDP request
  -> HPS command server
  -> HPS command bridge
  -> generated CSR access
  -> lightweight HPS-to-FPGA bridge
  -> Avalon-MM CSR adapter
  -> FPGA CSR bank
  -> source/core/telemetry/replay owner
```

The integrated PDF freezes command protocol version 1: one exact 28-byte
request, seven command types `0x0001` through `0x0007`, and no generic command
result. Step 14 does not reinterpret that protocol. It defines an explicit
version-2 extension with the same request layout, seven additional commands,
and one exact 32-byte command result.

The generated CSR contract is minor version 1.8. Existing offsets `0x000`
through `0x088` retain their meanings. Step 14 appends three registers at
`0x08C`, `0x090`, and `0x094`.

## Request versions

Both versions use the exact packed little-endian request:

| Offset | Field | Type | Rule |
| ---: | --- | --- | --- |
| 0 | `magic` | `uint32` | `0x54524343` |
| 4 | `version` | `uint16` | `1` or `2` |
| 6 | `cmd_type` | `uint16` | Generated command type |
| 8 | `seq` | `uint32` | PC command sequence |
| 12 | `arg0` | `uint32` | Command-specific |
| 16 | `arg1` | `uint32` | Command-specific |
| 20 | `arg2` | `uint32` | Command-specific |
| 24 | `crc32` | `uint32` | Must be zero; CRC remains disabled |

The datagram length is exactly 28 bytes. C structure padding or a longer UDP
payload is not accepted.

### Exact version-1 baseline

| Code | Command |
| ---: | --- |
| `0x0001` | `SET_THR2` |
| `0x0002` | `CLEAR_METRICS` |
| `0x0003` | `SET_SOURCE_MODE` |
| `0x0004` | `SET_PACKET_ENABLE` |
| `0x0005` | `SET_WAVE_DECIM` |
| `0x0006` | `SET_SPEC_SHIFT` |
| `0x0007` | `PING` |

Version 1 has no generic result packet. `PING` returns diagnostic STATUS only.
This behavior remains exact Revision G behavior.

### Version-2 extension

Version 2 accepts the seven version-1 types and adds:

| Code | Command | Arguments | Required behavior |
| ---: | --- | --- | --- |
| `0x0008` | `SET_SPEC_MODE` | `arg0=0..2`, others zero | Write and verify the generated spectrum mode. |
| `0x0009` | `SET_TELEMETRY_ENABLE` | `arg0=0` or `1`, others zero | Disable immediately through the safe control API, or enable only after lifecycle admission and readback. |
| `0x000A` | `CONFIGURE_DDR_RING` | all zero | Configure only the locally validated reserved-DDR geometry. Network-supplied addresses are forbidden. |
| `0x000B` | `RESET_TRANSPORT` | all zero | Disable, reset, and put the HPS/FPGA transport into the reset-complete lifecycle state. |
| `0x000C` | `CLEAR_COUNTERS` | all zero | Clear the exact Step-14 FPGA and HPS transport-counter set without resetting unrelated state. |
| `0x000D` | `START_BRAM_REPLAY` | all zero | Issue the generated replay request and report the FPGA owner's accept or reject result. |
| `0x000E` | `READ_STATUS_VERSION` | all zero | Return raw `STATUS` and raw `VERSION` as `NOOP`, even when identity/version is incompatible; only read failure is `FAILED`. |

Version-2 `PING` ignores all three arguments. Every valid PING emits one fresh
diagnostic STATUS with telemetry `seq=0`. It emits no command result, performs
no CSR access, and neither consults nor changes the version-2 sequence ledger or
result cache.

## Version-2 command result

Every non-PING version-2 command produces one exact packed little-endian
32-byte result to the validated request source address and port:

| Offset | Field | Type | Rule |
| ---: | --- | --- | --- |
| 0 | `magic` | `uint32` | `0x54524352` |
| 4 | `version` | `uint16` | `2` |
| 6 | `cmd_type` | `uint16` | Echo accepted request type |
| 8 | `seq` | `uint32` | Echo accepted request sequence |
| 12 | `disposition` | `uint32` | Generated disposition |
| 16 | `reject_reason` | `uint32` | Generated reject reason |
| 20 | `fpga_status` | `uint32` | Raw `STATUS` CSR snapshot in the original result |
| 24 | `csr_version` | `uint32` | Raw `VERSION` CSR snapshot in the original result |
| 28 | `crc32` | `uint32` | Must be zero |

Dispositions are `APPLIED=0`, `NOOP=1`, `REJECTED=2`, and `FAILED=3`.

Reject reasons preserve the version-1 values and append Step-14 reasons:

| Code | Name | Meaning |
| ---: | --- | --- |
| 0 | `NONE` | No rejection. |
| 1 | `BAD_SOURCE` | Source address or port is not the bound peer. |
| 2 | `BAD_LENGTH` | Request is not exactly 28 bytes. |
| 3 | `BAD_MAGIC` | Request magic differs. |
| 4 | `BAD_VERSION` | Command protocol version is unsupported. |
| 5 | `BAD_CRC` | Disabled CRC field is nonzero. |
| 6 | `UNSUPPORTED_TYPE` | Command type is not legal for the selected version. |
| 7 | `RANGE` | A ranged argument is illegal. |
| 8 | `RESERVED_ARGUMENT` | A required-zero argument is nonzero. |
| 9 | `CSR` | CSR rejected the operation or readback. |
| 10 | `IO` | Local I/O operation failed. |
| 11 | `UNSAFE_STATE` | Lifecycle or replay admission condition is not met. |
| 12 | `SEQUENCE_STALE` | Sequence is older or RFC1982-ambiguous. |
| 13 | `SEQUENCE_CONFLICT` | Same sequence carries different request bytes. |
| 14 | `TIMEOUT` | Bounded commit, transition, or replay-result wait expired. |
| 15 | `RESET_REQUIRED` | Fail-closed recovery requires transport reset. |
| 16 | `VERSION_MISMATCH` | FPGA ID/VERSION is not the generated 1.8 contract. |

An applied result is not emitted until all command-specific CSR writes and
required readbacks have succeeded. A UDP result-send failure does not authorize
reapplying the command. An identical retry resends the cached snapshot bytes;
it does not perform a fresh read.

Every command except PING and `READ_STATUS_VERSION` must verify generated FPGA
ID and CSR VERSION 1.8 before it can return `NOOP` or `APPLIED`. PING performs no
CSR access. `READ_STATUS_VERSION` is the deliberate diagnostic exception: it
returns the raw STATUS/VERSION snapshot as `NOOP` even when ID or VERSION is
incompatible, so the PC can diagnose a stale image. Only inability to complete
the reads produces `FAILED`.

## Trusted peer and session binding

The canonical direct-link configuration is:

```text
HPS command listener       192.168.10.2:5006
trusted PC command source  192.168.10.1:5007
```

The production HPS listener binds the runtime `hps_static_ip`,
`192.168.10.2:5006`; it does not bind a wildcard interface. Responses use that
same bound command socket. Production matching uses both IPv4 address and
nonzero UDP source port. A
configured IP match with an arbitrary source port is insufficient.

A deliberately unbound direct-link lab mode may learn a peer only from the
first fully valid PING. It then pins both the observed IPv4 address and its
nonzero UDP port. This learning mode must be explicit; it is not a production
fallback. The protocol is neither authenticated nor encrypted and must not be
exposed to an untrusted network.

Binding `0.0.0.0:5006` is permitted only as an explicit lab/test override. It
is never the canonical production default.

## At-most-once and RFC1982 sequence rules

The HPS command bridge owns a bounded result cache and a 32-bit RFC1982 serial
ledger for every version-2 non-PING command, including
`READ_STATUS_VERSION`.

```text
same seq + byte-identical request  -> resend byte-identical cached result
same seq + different request       -> reject SEQUENCE_CONFLICT
newer RFC1982 seq                   -> execute once and cache result
older or half-range-ambiguous seq   -> reject SEQUENCE_STALE
```

An identical readback retry returns the cached snapshot rather than silently
substituting newer CSR values. Mutation safety is the primary purpose, but the
sequence rule is uniform for every non-PING version-2 request.

The ledger scope is the current HPS process and bound-peer session. It starts
empty when the server starts or when an explicitly unbound lab session binds a
new peer through its first valid PING. PING otherwise has no ledger effect.

## Command ownership

The command server owns byte parsing, version/type/argument validation, peer
validation, and result/status encoding and transmission. The live streamer
routes every accepted non-PING v1/v2 command through the command bridge. That
bridge owns generated-CSR execution, lifecycle, safe mutation, replay,
sequence-ledger, cache, timeout, and result readback behavior.

Lifecycle commands must not be passed through the old direct
`command_apply_to_csr()` helper as unrelated independent writes. They modify
HPS ring-reader state and FPGA state as one ordered transaction.
The compatibility helper is not used by the live streamer path.

The streamer services at most 64 command datagrams per outer-loop pass. The
socket remains nonblocking and ring consumption must receive service between
bounded command batches.

## Transport lifecycle

The mutation lifecycle is:

```text
RESET_TRANSPORT
  -> CONFIGURE_DDR_RING
  -> SET_TELEMETRY_ENABLE 1
```

`CONFIGURE_DDR_RING` has all-zero network arguments. The command bridge obtains
FPGA and HPS ring addresses, size, and guard bytes only from the already
validated local runtime configuration and live reserved-memory admission. The
network never selects a physical address.

Enable requires all of the following:

- generated FPGA ID and CSR VERSION 1.8 verified;
- transport reset completed;
- pinned ring configuration committed and reported configured;
- consumer pointer `Rd=0` committed;
- producer pointer snapshot `W=0` verified;
- no malformed latch or reset-required state;
- writer and telemetry control readback match the requested levels.

If any write, commit, poll, or readback fails, the bridge attempts
`CONTROL=0`, reads STATUS, and claims the hardware is disabled only when both
telemetry and writer controls read back zero. If MMIO or readback cannot prove
that condition, software locks `RESET_REQUIRED`, reports hardware disable as
unverified, and requires an operator or transport reset. It never turns a
software lock into a claim about unreachable hardware state.

HPS-local configuration and restored-enable state commit only after both the
configuration/apply readback and the safe control-restore readback succeed.

`SET_TELEMETRY_ENABLE 0` is allowed as a safe disable. Enabling does not perform
an implicit reset or ring reconfiguration.

RESET is not a replay abort. After the ring reset, the bridge rejects RESET if
`REPLAY_STATUS` has reserved bits set or reports `pending`, `replay_active`,
`replay_path_busy`, or `e2e_busy`. It then requires both controls off,
`writer_busy=0`, both commit-pending indicators clear,
`source_transition_busy=0`, and `transport_epoch_idle=1`. A healthy replay
state (`rearm_required=0`) causes no `REPLAY_CONTROL` write. Only a quiescent
failed epoch may receive one `REPLAY_CONTROL.rearm` pulse; readback must preserve
`result_epoch` and clear pending/active/busy, retained accept/reject, error, and
`rearm_required`. Any timeout, MMIO error, reserved-bit violation, epoch change,
or stuck bit returns `FAILED` and retains the software `RESET_REQUIRED` lock.

## Safe control mutations

`SET_SOURCE_MODE`, `SET_PACKET_ENABLE`, `SET_WAVE_DECIM`, `SET_SPEC_MODE`, and
`SET_SPEC_SHIFT` are disabled/idle mutations in both command versions. The HPS
bridge must snapshot the requested enable state, disable telemetry and the ring
writer, verify both controls read back disabled, verify
`STATUS.transport_epoch_idle=1`, and verify no replay is active, busy, or
pending. Only then may it write the generated CSR or issue the generated shadow
commit.

For source mode, the bridge writes `SOURCE_MODE_SHADOW`, pulses
`SOURCE_MODE_COMMIT`, waits for pending to clear, and verifies
`STATUS.actual_source_mode`. For every listed control it verifies the requested
readback before restoring the prior enable state; restore itself also requires
verified readback. Any failed write, timeout, readback mismatch, or unsafe replay
state triggers the same `CONTROL=0` attempt and verification. If disable cannot
be read back, software locks `RESET_REQUIRED` and reports hardware disable as
unverified; HPS-local state does not commit. Direct live CSR writes for these mutations are rejected, including when
the request uses the otherwise unchanged version-1 wire contract.

## Counter-clear ownership

`CLEAR_COUNTERS` clears:

- FPGA `DMA_DROP_COUNT` and `DMA_PACKET_COUNT`;
- FPGA `PACKET_FIFO_DROP_COUNT`;
- FPGA `CSR_COMMAND_REJECT_COUNT`;
- the defined HPS UDP/ring/command transport counters.

It preserves:

- sticky `OVERFLOW_FLAGS`;
- producer `W` and consumer `Rd`;
- telemetry sequence;
- core sample/frame counters;
- trusted-peer binding;
- version-2 sequence ledger and cached results.

Sticky flags remain owned by `CLEAR_STICKY_FLAGS`; core metrics remain owned by
the existing `CLEAR_METRICS` command. Counter clear is not a transport reset.

## CSR minor-1.8 extension

| Offset | Register | Access | Meaning |
| ---: | --- | --- | --- |
| `0x08C` | `COUNTER_CLEAR` | W1P | Bit 0 `transport_counters` clears the exact FPGA transport-counter set. |
| `0x090` | `REPLAY_CONTROL` | W1P | Bit 0 `start`; bit 1 `rearm`. |
| `0x094` | `REPLAY_STATUS` | R | Replay request/result and path state. |

`REPLAY_STATUS` is:

| Bits | Field |
| ---: | --- |
| 0 | `pending` |
| 1 | `last_accept` |
| 2 | `last_reject` |
| 3 | `start_ready` |
| 4 | `replay_active` |
| 5 | `replay_path_busy` |
| 6 | `replay_path_done` |
| 7 | `e2e_busy` |
| 8 | `e2e_done` |
| 9 | `error` |
| 10 | `rearm_required` |
| 15:11 | reserved, read zero |
| 31:16 | `result_epoch` |

`STATUS` also assigns `actual_source_mode` to bits 11:10,
`transport_epoch_idle` to bit 12, and `source_transition_busy` to bit 13. The
existing `source_commit_pending` bit is asserted when a source commit is
pending or requested source mode differs from actual source mode.

## BRAM replay command

`START_BRAM_REPLAY` pulses `REPLAY_CONTROL.start`. The raw request reaches the
replay admission owner even when `start_ready=0`, so a denied command produces
an observable rejection instead of disappearing behind HPS gating.

Before that START write, an already `pending` CSR replay result rejects the
command without another control write. If a prior failed epoch reports
`rearm_required`, the bridge first requires replay/transport quiescence, pulses
REARM once, preserves `result_epoch`, and verifies that pending, active/busy,
retained accept/reject, error, and rearm-required state all clear. Live replay
state is never aborted by this preparation. A stuck bit, epoch change, timeout,
or MMIO failure fails closed and no START is issued.

The CSR bank holds mutually exclusive `last_accept` and `last_reject`, clears
`pending` on owner feedback, and increments `result_epoch` for each completed
CSR-originated start result. Board-key starts must not complete or overwrite a
pending CSR command result. `REPLAY_CONTROL.rearm` uses the same replay-clear
owner as the documented local rearm input; it does not clear transport
counters.

The HPS bridge snapshots the initial `result_epoch`, issues one start pulse,
waits for a bounded epoch change and pending clear, then reports accept or
reject. A timeout is not treated as acceptance.

## Required source and host gates

```bash
python3 scripts/check_command_path.py
python3 scripts/check_command_path.py --force-fallback-schema
python3 sim/check_step14_command_rtl.py
make hps-step14-test
make dashboard-step14-test
make step14-source
```

The HPS host test must cover exact parsing/results, peer IP and port, v1
preservation, version-2 ranges, RFC1982 duplicate/stale/conflict cases,
RESET-to-CONFIGURE-to-ENABLE ordering, injected CSR failure/readback mismatch,
counter preservation, replay accept/reject/timeout, cached readback replay, and
the 64-command fairness budget. The dependency-free PC test must cover every
generated request builder and exact result parsing.

## Evidence boundary

The checked-in contract, source checker, structural/model RTL checker, directed
`sim/tb/tb_trecap_step14_command_csr.sv` plus its filelist, HPS test source, and
PC test source are implementation artifacts. They are not native RTL-simulation
or live evidence.

This snapshot does not claim:

- a real PC-to-HPS UDP exchange;
- HPS Linux `/dev/mem` CSR or DDR mapping;
- traversal of the generated lightweight bridge;
- command application or replay on FPGA hardware;
- accepted native RTL simulation;
- Platform Designer generation;
- Quartus compile, TimeQuest closure, or a generated `.sof`;
- physical DE1-SoC behavior.

Those claims remain pending until their dedicated tool-produced and hardware
evidence is captured and accepted.
