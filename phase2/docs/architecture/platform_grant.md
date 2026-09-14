# Platform codec-bus grant

HPS_GPIO48 controls the DE1-SoC codec I2C mux: physical low selects the FPGA,
physical high selects HPS. It remains a dedicated HPS GPIO in the frozen Platform
Designer preset. The HPS hard-pin conduit is not a general FPGA input. The board
therefore receives a driver-owned CSR grant, after Linux establishes and reads
back the physical GPIO state. No loan-I/O configuration or pinmux change is used.

The source contract is `spec/generated/csr_map.json`; `scripts/gen_headers.py`
emits its RTL, C, and Python constants. Existing CSR offsets and packet formats
are unchanged. Both new words fit inside the existing 4096-byte CSR aperture.

| Register | Offset | Access / reset | Meaning |
| --- | --- | --- | --- |
| `PLATFORM_CONTROL` | 0x184 | R/W / 0 | Bit 0, `codec_fpga_grant`: the platform driver owns GPIO48 low and permits FPGA codec initialization. Bits 31:1 are reserved and nonzero writes are rejected. |
| `PLATFORM_CAPABILITY` | 0x188 | R / 0x50470100 | `PG`, ABI 1. The kernel requires an exact match before using the grant. |

The grant is an ordinary level in the 50 MHz fabric domain. Only fabric hard reset
clears it automatically. Transport soft reset, external transport clear, metric
clear, source clear/rearm, and sticky-error clears preserve it. Grant writes are
accepted during an external transport clear, so physical ownership can always be
revoked independently of ring recovery. A grant read returns the current level.

## Driver sequence

`platform/de1soc/linux/driver/trecap_platform.c` owns the following sequence:

1. Validate the reserved ring and require the platform device's MMIO resource to
   be exactly physical 0xff200000 with span 0x1000. Map it as kernel device memory.
2. Require the expected CSR ID and platform capability. Clear `PLATFORM_CONTROL`
   and read back zero before acquiring the physical mux.
3. Exclusively acquire `codec-mux-gpios` as output low. The static DT names
   `portb` offset 19, active-high logical selection: this is HPS_GPIO48, without
   relying on global Linux GPIO numbers. Require GPIO readback zero.
4. Write bit 0 of `PLATFORM_CONTROL` and require the same value on readback.
5. Register the exclusive, read-only `/dev/trecap-ring` device. A probe failure
   after GPIO acquisition executes managed cleanup.

Managed cleanup and platform shutdown clear the CSR grant and complete a readback
before driving GPIO48 high. The FPGA initializer releases its open-drain outputs
when the grant falls. FPGA configuration, fabric clocks, and bridges must remain
available until this callback finishes; bridge teardown follows platform shutdown.
The managed action runs before the GPIO descriptor and CSR mapping are released.
Stopping the platform oneshot service alone does not unload the module.

The static node is `/trecap-platform@ff200000`, with the MMIO `reg`, reserved-memory
phandle, and GPIO descriptor. The Linux staging script includes both the ring UAPI
and generated CSR header when staging the external module. Kernel constants come
from the same CSR generator as RTL and HPS userspace.

## Readiness and recovery

The board combines the grant with supported/locked audio PLL status and successful
codec initialization. Grant loss immediately removes audio readiness and disables
codec initialization. If audio is running, the source supervisor records a
readiness-loss fault, ends that DSP epoch, and stops admission. Restoring the grant
can restart codec initialization but does not automatically resume a faulted DSP
epoch. After fixing the platform condition, use the existing operator interface:

```bash
sudo python3 sw/hps/scripts/source_health.py --rearm
sudo python3 sw/hps/scripts/source_health.py --watch --interval 1
```

A hard FPGA reset clears the grant even if Linux retains its GPIO descriptor.
The supported static-boot lifecycle therefore boots the matching FPGA, handoff,
kernel, DTB, and module together after reconfiguration/reset. It does not promise
hot reconfiguration or automatic restoration by an already-probed driver.

`PLATFORM_CONTROL` is kernel-owned by the software contract. Privileged userspace
still has the existing CSR `/dev/mem` path under the selected Linux configuration;
this CSR is not a hardware access-control boundary. The streamer, source-health
utility, and UDP command dispatcher do not write it. Other privileged tools must
respect its owner. The driver reports its GPIO ownership/readback, not an independent
FPGA observation of the dedicated HPS pin or an electrical measurement of the mux.

See [source health](source_health.md) for fault and rearm behavior and the
[Linux build/boot recipe](../../platform/de1soc/linux/README.md) for deployment.
This source implementation has not been exercised by a Linux kernel/module build
or a live-board grant transfer in this work.
