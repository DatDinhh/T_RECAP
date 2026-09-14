# Reserved DDR region for the T-RECAP HPS streamer

File class: `[1]` hand-written HPS bring-up documentation.

## Evidence boundary

The selected source baseline supplies `socfpga_cyclone5_trecap.dts`, its static
reservation/platform includes, and the Linux 6.12.109 platform driver. The
installed boot image must select the matching built DTB. Source presence is not
Linux boot or runtime evidence; live telemetry requires the actual reservation
and driver device described below.

## Frozen interval

```text
ring_base_hps_phys       = 0x000000003e000000
ring_base_fpga           = 0x000000003e000000
ring_size_bytes          = 0x02000000 = 33554432 = 32 MiB
ring_end_exclusive       = 0x0000000040000000
ring_guard_bytes         = 64
ring_alignment_bytes     = 64
```

The ring therefore occupies `[0x3e000000, 0x40000000)`. `RING_BASE` is the
FPGA-visible physical address, not a userspace virtual pointer returned by
`mmap()`.

## Official reservation mechanism

The static `reserved-memory` node in
`platform/de1soc/linux/trecap_reserved_memory.dtsi` is the one official
mechanism:

```dts
/ {
	reserved-memory {
		#address-cells = <1>;
		#size-cells = <1>;
		ranges;

		trecap_telemetry_ring: trecap-ring@3e000000 {
			reg = <0x3e000000 0x02000000>;
			no-map;
		};
	};
};
```

`no-map` is mandatory. Do not add `reusable`, a shared-pool compatible, a CMA
default marker, or an allocation range. The FPGA owns the write side of this
fixed carveout; Linux must neither allocate it as ordinary RAM nor manage it as
a reusable pool.

The former kernel memory-limit workaround is retired and must not be kept as a
second boot-time alternative. One explicit DT reservation avoids hidden
bootloader state and gives the final FDT one auditable source of truth.

## Integrate into the active board DTB

Follow [the Linux build/install recipe](../../../platform/de1soc/linux/README.md)
to stage the static board DTS, build the matching kernel/DTB/module, and install
the application and services. The board DTS includes `trecap_platform.dtsi` and
its reservation; the platform node references that exact region and gives the
driver ownership of GPIO48 codec selection.

Select `socfpga_cyclone5_trecap.dtb` in the board boot flow and retain a recovery
boot entry. The reservation must be in the FDT before Linux starts. A configfs
overlay applied after boot cannot reserve pages Linux may already use. The
compatible FPGA image and bridges must also be established before CSR access.
Start `trecap_platform.service` before the streamer; it creates `/dev/trecap-ring`
and holds the FPGA codec-bus grant. The driver validates the platform CSR ABI,
acquires GPIO48 output-low with readback, then asserts `PLATFORM_CONTROL`; cleanup
revokes that grant before returning the GPIO high. See
[platform_grant.md](../../../docs/architecture/platform_grant.md). No userspace
GPIO48 export is required.
The source baseline uses static boot, without driver hot-unbind or live DT node
removal while a ring mapping exists.

## Verify the live system

Run as a privileged user on the booted HPS:

```sh
node=/sys/firmware/devicetree/base/reserved-memory/trecap-ring@3e000000
test -d "$node"
test -e "$node/no-map"
xxd -p "$node/reg"
cat /proc/iomem
dmesg | grep -i -E 'reserved|3e000000|40000000'
```

The live `reg` bytes must be `3e00000002000000`. The ring must be inside the
board's real DDR geometry and must not overlap a `System RAM` allocator entry in
`/proc/iomem`. If the live tree, boot log, or I/O memory map is missing,
unreadable, masked, or contradictory, stop. That is an unproven reservation,
not a pass.

## Cache/coherency rule

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
commit, and whole-record rules in the ownership contract still apply. CSR access remains the existing
read/write `/dev/mem` device mapping.

Repeated sequences, stale headers, or impossible payload sizes after apparently
successful FPGA writes are reasons to stop and inspect mapping attributes.

## Source consistency check

From the repository root:

```sh
python3 scripts/check_ddr_ring_ownership.py
make -C sw/hps check-config
```

These commands cross-check source files. They do not compile the active DTB,
boot Linux, run the directed RTL test, invoke Quartus, or test hardware.

## Safe bring-up order

```text
1. Integrate and inspect the reservation in the active board DTB.
2. Boot Linux and capture live-tree, /proc/iomem, and boot-log evidence.
3. Load the matching platform driver, confirm /dev/trecap-ring, and configure the direct-link static IP.
4. Build the HPS streamer and run its non-live config check.
5. Start STATUS-only streaming.
6. Enable WAVE, METRICS, and spectra only after STATUS is stable.
```

Never write a Linux virtual address into `RING_BASE`. Never start the live
streamer when ordinary `System RAM` intersects the ring. Do not treat PC
dashboard output as bit-accurate core signoff, and do not expose the
unauthenticated command UDP port beyond an isolated lab network.

## Failure triage

| Symptom | Likely cause | First check |
| --- | --- | --- |
| Immediate HPS crash or filesystem corruption | Linux still owns ring pages | live DT node and `/proc/iomem` |
| Repeated or stale records | wrong cache attributes | mapping policy or kernel driver |
| Malformed record near ring end | WRAP/boundary or cache fault | `W`/`Rd`, WRAP tail, mapping policy |
| Ring open rejected | missing driver, access denied, or another consumer | platform service, `/dev/trecap-ring`, and existing streamer |
| Ring ioctl/mmap rejected | ABI, geometry, flags, or map permissions mismatch | matching driver/application build and runtime JSON |
| CSR `/dev/mem` map rejected | strict devmem or raw-I/O permissions | selected kernel configuration and CSR service permissions |
| No UDP telemetry | network/interface mismatch | static IP, peer, firewall, UDP port |

## Acceptance questions

Before live telemetry, the operator must be able to answer from captured
evidence:

- Which compiled DTB is active?
- Does its T-RECAP node reserve exactly `[0x3e000000, 0x40000000)` with
  `no-map`?
- Does the live tree match that DTB?
- Does `/proc/iomem` exclude the interval from ordinary `System RAM`?
- Is `0x3e000000` the FPGA-visible address written to `RING_BASE` and the HPS
  physical address mapped by the reader?
- Are the HPS mapping/cache attributes correct for FPGA-produced DDR data?
