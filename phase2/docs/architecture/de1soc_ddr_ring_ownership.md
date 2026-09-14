# DE1-SoC DDR ring ownership and Linux reservation

## Status and evidence boundary

Step 12 implements the hand-written ownership contract, one canonical Linux
reserved-memory source, fail-closed source validation, and a directed RTL test
source. The selected static board DTS now includes the reservation and platform
driver binding. Source implementation does **not** claim that the selected DTB
was compiled or inspected, that Linux booted with the reservation,
that the RTL simulation ran, or that Quartus or physical hardware passed.

Those evidence states remain false in
`config/boards/de1soc_ddr_ring_ownership.json` until tool- or board-produced
artifacts exist.

## Canonical physical interval

| Property | Frozen value |
| --- | --- |
| HPS physical base | `0x000000003e000000` |
| FPGA-visible base | `0x000000003e000000` |
| Size | `0x02000000` bytes / 32 MiB |
| End, exclusive | `0x0000000040000000` |
| Interval | `[0x3e000000, 0x40000000)` |
| Guard | 64 bytes |
| Record/pointer alignment | 64 bytes |
| Current natural alignment | 32 MiB |

The values must agree in the following source views:

- `platform/de1soc/address_map/hps_bridge_regions.json`;
- `platform/de1soc/qsys/hps_config.tcl`;
- `sw/hps/config/trecap_hps_config.json`;
- `platform/de1soc/linux/trecap_reserved_memory.dtsi`;
- the exact resource admission in `platform/de1soc/linux/driver/trecap_platform.c`.

Step 12 does not alter the Step-4 canonical address-map contract or its frozen
fingerprint.  It adds the concrete Linux reservation policy around those
already-frozen addresses.

## One official Linux reservation mechanism

The only official reservation mechanism is the static device-tree
`reserved-memory` node in
`platform/de1soc/linux/trecap_reserved_memory.dtsi`:

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

`no-map` keeps the interval out of the normal Linux linear mapping as well as
the normal page allocator.  The node deliberately has no `reusable` property
and is not a `shared-dma-pool`: Revision G uses a fixed raw carveout written by
the FPGA and read by the HPS, not a Linux-managed allocation pool.

A kernel memory-limit boot argument is not an active alternative.  Keeping two
reservation methods would make deployed state ambiguous and would allow a DTB
regression to be hidden by bootloader state.

## Pointer ownership

| State | Sole runtime owner | Transfer rule |
| --- | --- | --- |
| Producer pointer `W` | FPGA DDR ring writer | Advances only after every DDR write response for the WRAP or normal record succeeds. HPS can only request an atomic snapshot. |
| Consumer pointer `Rd` | HPS reader | Updates through `RING_RD_LO_SHADOW`, `RING_RD_HI_SHADOW`, then `RING_RD_COMMIT`. |

Both pointers are 64-bit absolute byte pointers.  For power-of-two ring size
`R`, `off(p) = p & (R - 1)` and valid state requires
`0 <= W - Rd <= R`.

An asynchronous hardware reset may initialize pointer storage.  During normal
operation, telemetry soft reset, external transport reset, and ring
reconfiguration invalidate the consumer epoch; they do not silently create a
new HPS consumer commit.  The first HPS commit in the new epoch must be the
aligned value zero.  Later commits must be 64-byte aligned, monotonic within
the epoch, not ahead of `W`, and leave at most `R` bytes used.  Write admission
requires a legal ring configuration and a valid consumer epoch.

This epoch rule is necessary because an unconditional monotonic check would
reject the required `Rd=0` initialization after a prior run, while silently
rewinding `Rd` in FPGA reset logic would violate HPS ownership.

## WRAP and boundary contract

For a normal record,

```text
Lrec  = align64(32 + payload_bytes)
o     = off(W)
Ttail = R - o
Ffree = R - (W - Rd) - guard
```

If `o + Lrec <= R`, the writer requires `Ffree >= Lrec`.  If
`o + Lrec > R`, it requires `Ffree >= Ttail + Lrec`; checking only the normal
record length is insufficient.

With sufficient space, the writer first emits packet type `0x007f` at the
physical tail.  Its payload length and sequence field are zero.  Its effective
DDR length is exactly `Ttail`, and every byte after the 32-byte header through
the ring end is zero.  Only after every tail write completes successfully may
the writer commit `W = W + Ttail`.  The normal record then starts at offset zero.
WRAP does not consume a PC-visible sequence number.

If the complete `Ttail + Lrec + guard` constraint is not satisfied, the normal
record is dropped and counted without changing `W`.

## Deterministic transport initialization

The required HPS-owned initialization sequence is:

1. Clear `CONTROL.telemetry_enable` and `CONTROL.ring_writer_enable`.
2. Wait, with a finite timeout, until the writer reports idle.
3. Pulse `CONTROL.telemetry_soft_reset` exactly once.
4. Write ring base and size.
5. Pulse `RING_CONFIG_COMMIT` while both enable levels remain clear.
6. Commit `Rd=0` through the HPS shadow/commit registers.
7. Atomically snapshot `W` and require `W=0`.
8. Enable the ring writer, then telemetry.

After the complete sequence, the writer is configured and idle with `W=0` and
sequence zero; the HPS consumer epoch is valid with `Rd=0`.  Enabling before
the explicit consumer commit is a contract violation.

## Ring mapping and consumer ownership

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

## BSP and DTB integration

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

The reservation must be present in the FDT consumed during early Linux boot.
The selected static board DTS already includes it. A runtime configfs overlay
cannot retroactively reserve pages that Linux may already use. An installed
image must select the built T-RECAP DTB; a source file alone is not boot evidence.

Example offline inspection of the compiled board DTB:

```sh
fdtget -tx socfpga_cyclone5_trecap.dtb /reserved-memory/trecap-ring@3e000000 reg
fdtget -p socfpga_cyclone5_trecap.dtb /reserved-memory/trecap-ring@3e000000
```

The first command must report cells `3e000000 02000000`; the property list must
contain `no-map` and must not contain `reusable`.

## Runtime verification

On the booted HPS Linux system, fail closed unless all of the following hold:

```sh
node=/sys/firmware/devicetree/base/reserved-memory/trecap-ring@3e000000
test -d "$node"
test -e "$node/no-map"
xxd -p "$node/reg"
cat /proc/iomem
dmesg | grep -i -E 'reserved|3e000000|40000000'
```

The live `reg` bytes must be `3e00000002000000`.  The interval must be within
the board's physical DDR but must not intersect a `System RAM` allocator range
in `/proc/iomem`.  Missing, masked, or unreadable proof is not a pass for a real
streamer launch.

The Step-12 source checker validates checked-in consistency only.  It never
turns these deployment commands into claimed boot, runtime, simulation, or
hardware evidence.
