# DE1-SoC HPS transport implementation

## Status and evidence boundary

Step 13 completes the checked-in HPS transport source path from the frozen CSR
and reserved DDR interfaces to Revision-G UDP telemetry. The repository now has
a deterministic RAM-backed host test for the consumer and packetization logic.
That test does not prove an active DTB reservation, HPS CSR/device mappings,
physical Ethernet, systemd deployment, FPGA execution, Quartus compilation, or
board behavior. Those evidence fields remain false in
`config/boards/de1soc_hps_transport.json`.

## Runtime resource admission

Normal streaming uses the exact frozen windows:

| Resource | Contract |
| --- | --- |
| CSR | physical `0xff200000`, span 4096 bytes, read/write synchronous `/dev/mem` mapping |
| DDR ring | `[0x3e000000, 0x40000000)`, 32 MiB, exclusive read-only noncached `/dev/trecap-ring` mapping |
| Record alignment | 64 bytes |
| UDP maximum | 1200 bytes, including the 32-byte telemetry header |

Before live resource access, the binary fails closed unless the live device
tree contains `/reserved-memory/trecap-ring@3e000000` with exact big-endian
`reg=3e00000002000000`, has `no-map`, lacks `reusable`, and `/proc/iomem` is
readable, unmasked, and shows no `System RAM` overlap. Source presence of the
Step-12 `.dtsi` is not treated as live reservation evidence.

The ring reader opens `/dev/trecap-ring` with `O_RDONLY | O_CLOEXEC` and checks
`TRECAP_RING_GET_INFO` against the shared ABI in
`sw/hps/include/trecap_ring_device.h`: ABI version 1, exactly the read-only and
noncached flags, physical base `0x3e000000`, size `0x02000000`, and zero reserved
field. It then maps the complete aperture with `PROT_READ | MAP_SHARED` at file
offset zero. The driver rejects writable/executable, partial, private, or nonzero-
offset mappings and sets `pgprot_noncached`; userspace does not infer cache
attributes from `O_SYNC`. Cached ring mapping remains forbidden.

The device admits one open consumer. The reader retains its file descriptor until
after unmapping, so another process cannot acquire the ring during its lifetime.
The mapping does not grant ownership of FPGA producer state: `W`, `Rd`, reset,
commit, and whole-record rules below still apply. CSR access remains the existing
read/write `/dev/mem` device mapping.

Our selected source baseline is Linux 6.12.109 with the static
`socfpga_cyclone5_trecap.dtb`, the matching `trecap_platform.ko`, and HPS
application. The board DTS includes `trecap_platform.dtsi`, which includes the
canonical reservation and binds the platform driver. Build and offline-install
instructions are in [the Linux source baseline](../../platform/de1soc/linux/README.md).
The compatible FPGA image and bridge setup must be established by the boot flow
before the HPS application accesses CSRs.

`trecap_platform.service` loads the driver before `trecap_udp_streamer.service`.
The driver owns HPS_GPIO48 through `portb` offset 19. After output-low readback,
it asserts the FPGA-visible `PLATFORM_CONTROL` grant; teardown clears that CSR
before driving the GPIO high. It validates the exact CSR resource and platform
capability before acquisition. See [platform grant](platform_grant.md) for ordering and reset
semantics. No competing userspace GPIO owner is part of this design. Merely stopping the oneshot service does not unload the driver
or release that grant. This is a static-boot lifecycle: no live DT node removal
or driver hot-unbind while mapped. Use the matching FPGA/kernel/DTB combination
on the next boot when changing the image or address map.


## Reset, configure, and arm state machine

The reader state sequence is explicit:

1. `RESET_REQUIRED`: software requests both transport enables clear, verifies
   their STATUS readback before claiming hardware disabled, waits for writer
   drain, and pulses telemetry soft reset. If MMIO/readback cannot prove the
   clear, the software state remains locked and hardware disable is unverified.
2. `RECONFIG_REQUIRED`: ring base and size must be committed while disabled.
3. `RD0_REQUIRED`: HPS must commit `Rd=0`.
4. `ACTIVE`: HPS snapshots `W`, consumes records, and commits `Rd` after each
   consumed normal, oversized, or WRAP record.

Soft reset alone cannot clear a malformed latch into an active reader. Ring
reconfiguration and the explicit zero consumer commit are both required. The
streamer also requires a zero producer snapshot before enabling the writer and
then telemetry. Ring configuration must read back `ring_configured=1` with no
malformed-config flag, and every disable/enable transition must read back the
requested STATUS levels before it is treated as complete.

THR2 and source-mode shadow commits are not reported as active in an
HPS-synthesized diagnostic STATUS until their corresponding CSR pending bit
clears at the real safe boundary.

## Ring consumption and validation

Both `W` and `Rd` must be 64-byte aligned, `0 <= W-Rd <= R`, and at least one
complete 32-byte header must lie below the producer commit boundary before the
header is read. Record lengths are derived in 64-bit arithmetic before being
narrowed, preventing hostile `payload_bytes` values from wrapping.
An invalid atomic `W`/`Rd` snapshot is corruption or overrun, not an empty poll;
it immediately takes the same fail-closed malformed latch path.

Before forwarding, the reader checks:

- magic, header version, `header_bytes=32`, known packet type, and
  `header_crc=0`;
- reserved and packet-illegal flags;
- exact fixed payload lengths and bounded WAVE length;
- WAVE timestamp/sample-base agreement, `channels=3`, valid `nsamp`, positive
  stride, and zero reserved field;
- SPEC64 `nbin=64`, SPEC129 `nbin=129`, valid shift, and zero unused mask bits;
- METRICS timestamp agreement and exactly one of aggregate/per-frame flags;
- STATUS timestamp agreement and zero reserved field;
- committed-body and physical-tail bounds before any payload field is read.

The five normal types WAVE, SPEC64, SPEC129, METRICS, and STATUS are sent as one
UDP datagram containing exactly header plus payload. DDR alignment padding is
never sent. A complete record larger than 1200 bytes is counted, dropped without
fragmentation, then advances and commits `Rd`.

WRAP is never forwarded and never updates normal sequence accounting. It is
valid only away from offset zero, consumes exactly `R-off(Rd)`, has zero payload,
and requires every byte after its header through the physical ring end to be
zero. Its sequence must be zero or the previous committed normal sequence.

## Send and consumer-commit ordering

The canonical runtime requires nonblocking UDP so neither telemetry nor command
traffic can block ring service. The sender library also classifies a bounded
timeout defensively. Send failure, would-block, or timeout increments the
appropriate UDP error counter, drops that datagram, and still advances and
commits `Rd` so a disconnected dashboard cannot stall the core.

Command receive work is capped at 64 datagrams per main-loop pass. Even a flood
of rejected packets therefore yields back to the DDR consumer.

Local `Rd`, consumed-record counters, and sequence/forwarded accounting change
only after the CSR shadow/commit operation succeeds. The UDP attempt itself is
irreversible; a later consumer-commit failure stops the process without falsely
advancing local ring state.

FPGA-originated STATUS is copied and only its HPS-owned counter fields are
patched in the outgoing UDP buffer. The committed DDR record is never modified.

## Malformed policy

The canonical JSON, direct binary, launcher, and systemd policy is
**latch-and-stay-alive**:

1. The first malformed incident increments `malformed_record_count` exactly
   once.
2. Software enters `MALFORMED_LATCHED` before MMIO, then checks both the hardware
   disable and current-`Rd` recommit results.
3. The same bad `Rd` is not parsed, counted, or recommitted again.
4. The process remains available for diagnostic PING/STATUS; no byte-scanning
   recovery is allowed.
5. Streaming resumes only after soft reset, ring reconfiguration, `Rd=0`
   commit, zero-`W` verification, and the normal arm sequence.

`--stop-on-malformed` is an explicit debug override. It exits with code 3 after
the latch is established; the systemd unit prevents automatic restart for that
code so a restart cannot hide the incident.

## M0 dummy UDP counter

`--dummy-udp-counter` is a real UDP-only mode for Ethernet milestone M0. It
loads and validates the runtime JSON, opens only the UDP sender, and emits legal
diagnostic STATUS datagrams with `status_diagnostic=1`, `seq=0`, and monotonically
increasing timestamp/sample count. It does not inspect the active DT, map CSR or
DDR, or require root. `--once` sends one packet; `--max-records N` sends exactly
`N`; otherwise it runs until interrupted.

Example:

```sh
./trecap_udp_streamer \
  --config sw/hps/config/trecap_hps_config.json \
  --dummy-udp-counter
```

## Source and host gates

```sh
python3 scripts/check_hps_transport.py
make -C sw/hps WERROR=1 SANITIZE=1 test-step13-transport
bash -n sw/hps/scripts/run_udp_streamer.sh
```

The host test covers all five telemetry types, exact UDP lengths, WRAP, an
oversized record, hostile length arithmetic, malformed exactly-once latch and
full re-arm, masked/overlapping `/proc/iomem`, embedded-NUL config input,
identity-safe cleanup, negative STATUS readback, invalid producer pointers,
malformed-MMIO failure, command-flood budgeting, failed `Rd` commit, UDP
send/timeout failures, and three monotonic dummy diagnostic STATUS packets. Its
MMIO and UDP calls are RAM-backed or linker-wrapped, so passing it is
deliberately not HPS/Linux/network/hardware evidence.
