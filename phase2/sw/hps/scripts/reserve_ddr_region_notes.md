# Reserved DDR region for the T-RECAP HPS streamer

File class: `[1]` hand-written HPS bring-up documentation.

## Evidence boundary

The repository contains the canonical reservation source, but it does not know
which board DTS or DTB is selected by a particular SD-card image. Presence of
the `.dtsi` in a source archive is not Linux boot or runtime evidence. Do not
run live telemetry until the fragment is integrated into the active board DTB
and the live system checks below pass.

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

1. On the target image, identify the board model/compatible string and the DTB
   selected by U-Boot. Do not infer the name from this repository.
2. Include `trecap_reserved_memory.dtsi` from the matching board `.dts`. If
   that board already declares `/reserved-memory`, merge only the T-RECAP child
   while preserving the same one-cell address/size encoding.
3. Build DTBs with the kernel/BSP toolchain for that exact image.
4. Inspect the output DTB before installation:

   ```sh
   fdtget -tx active-board.dtb /reserved-memory/trecap-ring@3e000000 reg
   fdtget -p active-board.dtb /reserved-memory/trecap-ring@3e000000
   ```

   `reg` must be `3e000000 02000000`. The property list must contain `no-map`
   and must not contain `reusable`.
5. Keep the old DTB as a recovery entry, install the inspected DTB, select it in
   the bootloader, and reboot.

The reservation must be present in the FDT before Linux starts. A configfs
overlay applied after boot cannot reserve pages that Linux may already use.

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

The HPS reader must see committed FPGA writes through a non-cacheable, strongly
ordered, DMA-coherent, or explicitly cache-invalidated mapping. The controlled
bring-up path uses a read-only, synchronous `/dev/mem` mapping; kernel policy may
still prohibit it. If strict devmem or cache attributes cannot be proved, use a
kernel driver rather than weakening the reservation.

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
3. Configure the direct-link static IP.
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
| `/dev/mem` map rejected | strict devmem or permissions | kernel configuration and driver path |
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
