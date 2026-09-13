# DE1-SoC DDR ring ownership and Linux reservation

## Status and evidence boundary

Step 12 implements the hand-written ownership contract, one canonical Linux
reserved-memory source, fail-closed source validation, and a directed RTL test
source.  It does **not** claim that a board BSP includes the fragment, that the
selected DTB was compiled or inspected, that Linux booted with the reservation,
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

The values must agree in all four source views:

- `platform/de1soc/address_map/hps_bridge_regions.json`;
- `platform/de1soc/qsys/hps_config.tcl`;
- `sw/hps/config/trecap_hps_config.json`;
- `platform/de1soc/linux/trecap_reserved_memory.dtsi`.

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

## BSP and DTB integration

The `.dtsi` must be included by the board `.dts` that actually produces the DTB
selected by U-Boot.  The active board source and installed DTB name depend on
the Linux/BSP image and are intentionally not guessed by this repository.

Integration procedure:

1. Identify the active board model, compatible string, and bootloader-selected
   DTB from the target image.
2. Include `trecap_reserved_memory.dtsi` in that board source.  If the board
   already owns `/reserved-memory`, merge the T-RECAP child into that node while
   retaining the same one-cell address and size geometry.
3. Build DTBs with the matching kernel/BSP toolchain.
4. Inspect the new DTB before deployment and keep the previous DTB as a boot
   fallback.
5. Select the new DTB, reboot, and capture live-tree and `/proc/iomem` evidence.

A runtime configfs overlay is too late: reserved memory must be described in the
FDT consumed during early Linux boot.  A bootloader-applied overlay is only
acceptable if it is applied to the FDT before entering Linux and its final
flattened tree is inspected; the canonical checked-in source remains this
fragment.

Example offline inspection of the compiled board DTB:

```sh
fdtget -tx active-board.dtb /reserved-memory/trecap-ring@3e000000 reg
fdtget -p active-board.dtb /reserved-memory/trecap-ring@3e000000
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
