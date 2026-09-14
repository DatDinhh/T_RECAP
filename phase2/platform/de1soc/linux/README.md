# DE1-SoC Linux source baseline

Our platform source targets **Linux 6.12.109**, ARMv7, the Linux
**socfpga_defconfig**, and a GNU **arm-linux-gnueabihf-** toolchain. This is our
selected source baseline, not a description of an OS already installed on a
board. The kernel, DTB, driver module, and HPS application must be deployed as
one matching build. The release is available from the
[Linux kernel archives](https://www.kernel.org/).

The static device tree reserves 32 MiB at HPS physical address 0x3e000000 with
no cached linear mapping. The platform driver exposes that aperture through
/dev/trecap-ring as a read-only, noncached, single-consumer mapping. It also
owns HPS_GPIO48 through its GPIO descriptor, requires output-low readback,
and then asserts the FPGA-visible PLATFORM_CONTROL grant. Probe checks the exact
0xff200000/0x1000 CSR resource, FPGA ID, and PLATFORM_CAPABILITY ABI first.
Cleanup revokes the CSR grant before returning the mux high to HPS. The dedicated
HPS pin is not read directly into FPGA fabric. HPS userspace retains /dev/mem
access for CSRs; the DDR ring uses the driver device. The complete ownership
sequence is in [platform_grant.md](../../../docs/architecture/platform_grant.md).

## Stage source and build

Run these commands manually on a Linux build host with Python 3.10 or later,
GNU make, an ARM hard-float cross compiler and binutils, the usual kernel build
dependencies (including flex, bison, bc, OpenSSL/libelf development headers and
kmod), curl, tar, and xz. Use a toolchain compatible with the target root
filesystem's C library. Keep the kernel build and module staging paths free
of whitespace.

Start in the repository root. The workspace paths below are examples that can
be changed together.

~~~sh
export TRECAP_REPO="$(pwd)"
export TRECAP_LINUX_WORK="$TRECAP_REPO/build/linux"
export CROSS_COMPILE=arm-linux-gnueabihf-
export ARCH=arm
mkdir -p "$TRECAP_LINUX_WORK"
curl --fail --location \
  https://cdn.kernel.org/pub/linux/kernel/v6.x/linux-6.12.109.tar.xz \
  --output "$TRECAP_LINUX_WORK/linux-6.12.109.tar.xz"
tar -xf "$TRECAP_LINUX_WORK/linux-6.12.109.tar.xz" \
  -C "$TRECAP_LINUX_WORK"
export TRECAP_KSRC="$TRECAP_LINUX_WORK/linux-6.12.109"
export TRECAP_KOUT="$TRECAP_LINUX_WORK/kernel-build"
export TRECAP_MODULE_STAGE="$TRECAP_LINUX_WORK/module-stage"

python3 "$TRECAP_REPO/platform/de1soc/linux/prepare_linux_tree.py" \
  --kernel-tree "$TRECAP_KSRC" \
  --module-stage "$TRECAP_MODULE_STAGE"
~~~

The staging script copies the board DTS and two local includes into
arch/arm/boot/dts/intel/socfpga and registers socfpga_cyclone5_trecap.dtb in that
directory's Makefile. Re-running it updates changed source without duplicating
the DTB target. It rejects another kernel version and does not download,
configure, build, or deploy anything itself. A fresh kernel extraction needs
staging again.

The external module is staged at
module-stage/platform/de1soc/linux/driver. Its shared UAPI header is staged at
module-stage/sw/hps/include/trecap_ring_device.h and its generated CSR constants
at module-stage/sw/hps/include/generated/trecap_csr.h, preserving the driver's
relative includes. This keeps module build products outside the repository's
source directories.

~~~sh
make -C "$TRECAP_KSRC" O="$TRECAP_KOUT" socfpga_defconfig
(
  cd "$TRECAP_KSRC"
  scripts/kconfig/merge_config.sh -m -O "$TRECAP_KOUT" \
  "$TRECAP_KOUT/.config" \
  "$TRECAP_REPO/platform/de1soc/linux/kernel_config.fragment"
)
"$TRECAP_KSRC/scripts/config" --file "$TRECAP_KOUT/.config" \
  --set-str LOCALVERSION "-trecap" --disable LOCALVERSION_AUTO
make -C "$TRECAP_KSRC" O="$TRECAP_KOUT" olddefconfig
make -C "$TRECAP_KSRC" O="$TRECAP_KOUT" -j"$(nproc)" zImage dtbs modules

export TRECAP_MODULE="$TRECAP_MODULE_STAGE/platform/de1soc/linux/driver"
make -C "$TRECAP_KOUT" M="$TRECAP_MODULE" -j"$(nproc)" modules

make -C "$TRECAP_REPO/sw/hps" \
  CROSS_COMPILE="$CROSS_COMPILE" \
  BUILD_DIR="$TRECAP_LINUX_WORK/hps" all
~~~

The exported ARCH and CROSS_COMPILE apply to every make invocation above.
Building the full kernel first supplies the configuration and module symbol
information required by the external module. We use the Linux 6.12-compatible
Kbuild -C/M interface described in the
[kernel module build documentation](https://docs.kernel.org/6.12/kbuild/modules.html).

Expected products are:

| Product | Path below the workspace |
| --- | --- |
| ARM kernel | kernel-build/arch/arm/boot/zImage |
| Static board DTB | kernel-build/arch/arm/boot/dts/intel/socfpga/socfpga_cyclone5_trecap.dtb |
| Platform module | module-stage/platform/de1soc/linux/driver/trecap_platform.ko |
| HPS application | hps/bin/trecap_udp_streamer |

## Assemble an offline installation

The following manual commands install into a staging directory. They do not
modify the build host's running kernel, load the module, or start a service.
The destination must be a prepared ARM Linux root filesystem when producing a
bootable image; an empty directory only collects project build products.

~~~sh
export TRECAP_ROOTFS="$TRECAP_LINUX_WORK/rootfs"
export TRECAP_KERNEL_RELEASE="$(make -s -C "$TRECAP_KOUT" kernelrelease)"
mkdir -p "$TRECAP_ROOTFS"

make -C "$TRECAP_KOUT" \
  INSTALL_MOD_PATH="$TRECAP_ROOTFS" modules_install
make -C "$TRECAP_KOUT" M="$TRECAP_MODULE" \
  INSTALL_MOD_PATH="$TRECAP_ROOTFS" modules_install
depmod -b "$TRECAP_ROOTFS" "$TRECAP_KERNEL_RELEASE"

install -D -m 0644 "$TRECAP_KOUT/arch/arm/boot/zImage" \
  "$TRECAP_ROOTFS/boot/zImage-$TRECAP_KERNEL_RELEASE"
install -D -m 0644 \
  "$TRECAP_KOUT/arch/arm/boot/dts/intel/socfpga/socfpga_cyclone5_trecap.dtb" \
  "$TRECAP_ROOTFS/boot/socfpga_cyclone5_trecap.dtb"
install -D -m 0755 "$TRECAP_LINUX_WORK/hps/bin/trecap_udp_streamer" \
  "$TRECAP_ROOTFS/usr/local/bin/trecap_udp_streamer"
install -D -m 0644 "$TRECAP_REPO/sw/hps/config/trecap_hps_config.json" \
  "$TRECAP_ROOTFS/etc/trecap/trecap_hps_config.json"
install -D -m 0644 "$TRECAP_REPO/sw/hps/systemd/trecap_platform.service" \
  "$TRECAP_ROOTFS/etc/systemd/system/trecap_platform.service"
install -D -m 0644 "$TRECAP_REPO/sw/hps/systemd/trecap_udp_streamer.service" \
  "$TRECAP_ROOTFS/etc/systemd/system/trecap_udp_streamer.service"
~~~

Set the board/PC addresses in the installed HPS JSON to the deployment network.
The streamer service retains its STATUS-only launch profile. Once the root
filesystem contains systemd and the intended boot configuration, these
optional manual commands create startup links **without starting services**:

~~~sh
systemctl --root="$TRECAP_ROOTFS" enable trecap_platform.service
systemctl --root="$TRECAP_ROOTFS" enable trecap_udp_streamer.service
~~~

Copy the prepared files through the board's existing root-filesystem and boot
image deployment process. Select the matching zImage and this DTB in that
process. The example /boot paths are installation destinations, not assumptions
about the bootloader's partition layout. This recipe does not flash a bootloader
or change a running board's boot environment.

## Selected boot policy

[boot.cmd](boot.cmd) is our **U-Boot v2025.01 Cyclone V** boot source template.
It boots from MMC device 0, FAT partition 1 by default, with an ext4 root filesystem
on /dev/mmcblk0p2. File and partition choices are deployment variables; no
bootloader flash operation or persistent environment write is part of the
template.

The ordered boot sequence is: disable bridges, load the selected full RBF from
FAT, program FPGA device 0, enable bridges from the SPL handoff, load zImage and
the static DTB, then boot Linux without an initrd. The root filesystem therefore
needs its storage/filesystem drivers built into the kernel. The script stops on
a missing required setting, failed command, oversized file, or short load. Its
failure path attempts to disable bridges and stays in a sleep loop instead of
booting a partial configuration; console recovery remains an operator action.

| Deployment variable | Default / required value |
| --- | --- |
| trecap_rbf_file | Required: FAT path to the full RBF produced by this project's selected FPGA build |
| trecap_handoff_ready | Required: 1 only when the running SPL/preloader contains that build's generated HPS/DDR handoff |
| trecap_mmc / trecap_bootpart | 0 / 1 |
| trecap_root / trecap_rootfstype | /dev/mmcblk0p2 / ext4 |
| trecap_kernel_file | zImage-6.12.109-trecap |
| trecap_fdt_file | socfpga_cyclone5_trecap.dtb |
| trecap_extra_bootargs | Optional additional kernel arguments |

Use filenames without whitespace. The selected full RBF, generated handoff, and
running SPL must all belong to the same hardware configuration. Setting
trecap_handoff_ready is an explicit deployment assertion, not an automatic
inspection of those artifacts. The template leaves it unset.

The script uses nonoverlapping staging regions within the board's 1 GiB DDR:

| Object | Address | Maximum stored size |
| --- | ---: | ---: |
| zImage | 0x01000000 | 16 MiB |
| DTB | 0x02000000 | 1 MiB |
| boot.scr itself | 0x02100000 | 64 KiB |
| Full RBF | 0x08000000 | 32 MiB |

Every image size is obtained before its load and must fit its region. These
regions avoid the reserved ring at 0x3e000000. FDT relocation is bounded below
0x20000000. The fixed staging layout assumes a normal DE1-SoC U-Boot relocation
and heap outside these ranges; a customized bootloader memory layout must retain
those reservations.

### SPL handoff and FPGA-to-SDRAM

For Cyclone V, U-Boot's bridge command enables the HPS-to-FPGA, lightweight
HPS-to-FPGA, and FPGA-to-HPS paths. Its Gen5 implementation also restores the
SDRAM controller's FPGA port-reset register from cached SPL handoff word 3.
Disabling the bridges clears that FPGA-to-SDRAM register.
See the tagged upstream
[bridge implementation](https://github.com/u-boot/u-boot/blob/v2025.01/arch/arm/mach-socfpga/misc_gen5.c#L220-L251)
and [command dispatcher](https://github.com/u-boot/u-boot/blob/v2025.01/arch/arm/mach-socfpga/misc.c#L184-L215).

Our platform uses **hps_0.f2h_sdram0_data**, an **Avalon-MM bidirectional,
64-bit port**. The generated handoff must enable that exact port's required
read/write resources. A generic nonzero mask is insufficient. U-Boot's stock
[DE1-SoC SDRAM configuration](https://github.com/u-boot/u-boot/blob/v2025.01/board/terasic/de1-soc/qts/sdram_config.h#L57)
sets CFG_HPS_SDR_CTRLCFG_FPGAPORTRST to zero; using it unchanged cannot provide
this project's FPGA-to-SDRAM path. The bridge command returns success after
restoring its cached values and does not establish that the handoff matches
the RBF.

The required board-specific inputs are the compiled Quartus project directory
containing its QPF and hps_isw_handoff tree, plus the generated SoC EDS
preloader BSP directory containing settings.bsp and generated headers.
U-Boot's tagged [qts-filter.sh](https://github.com/u-boot/u-boot/blob/v2025.01/arch/arm/mach-socfpga/qts-filter.sh#L200-L233)
accepts those inputs:

~~~sh
# Manual source-preparation command inside a U-Boot v2025.01 source checkout.
# Set these two paths to the matching generated hardware/BSP directories first.
arch/arm/mach-socfpga/qts-filter.sh cyclone5 \
  "$TRECAP_QUARTUS_PROJECT" "$TRECAP_PRELOADER_BSP" \
  board/terasic/de1-soc/qts
~~~

Build the DE1-SoC SPL/U-Boot from those generated headers using its
socfpga_de1_soc_defconfig and the ARM cross toolchain. This boot source requires
Hush parsing, MMC/FAT, fatsize/fatload, FPGA load, bridge, fdt, bootz, source,
itest, test, and sleep commands. The bootloader installation remains part of the
board's established SD/preloader deployment process. No guessed register write
in boot.cmd replaces SPL pinmux, clock setup, SDRAM geometry, DDR training, or
generation of the FPGA-to-SDRAM handoff. Linux's DTS cannot repair that earlier
initialization boundary.

### Package and invoke the source template

Create the script image on the build host with a U-Boot-compatible mkimage,
then place it beside the chosen RBF, zImage, and DTB on the selected FAT
partition:

~~~sh
mkimage -A arm -O linux -T script -C none \
  -n "T-RECAP DE1-SoC static boot" \
  -d "$TRECAP_REPO/platform/de1soc/linux/boot.cmd" \
  "$TRECAP_LINUX_WORK/boot.scr"
~~~

For an explicitly selected manual boot at the U-Boot console, set the required
deployment variables and any partition overrides first. Then load and source
only this script; do not chain an alternate Linux boot after a failure:

~~~text
fatload mmc 0:1 0x02100000 boot.scr 0x10000 && source 0x02100000
~~~

That example must use the same MMC/partition values as the script's deployment
settings. It does not save the environment. The final
[bootz command](https://docs.u-boot.org/en/v2025.01/usage/cmd/bootz.html) uses a
dash in the initrd position and the loaded static DTB address.

## Static boot lifecycle

The compatible FPGA image and required HPS-to-FPGA / FPGA-to-SDRAM bridge setup
belong to the board's boot flow and must be in place before the platform service
grants codec ownership and the streamer accesses CSRs. The Linux device tree
must be passed to the kernel at boot: loading an overlay after startup cannot
retroactively reserve this DDR aperture.

At startup, trecap_platform.service loads the matching module and establishes
/dev/trecap-ring before trecap_udp_streamer.service starts. The static platform
node is /trecap-platform@ff200000. The driver holds GPIO48 low and the fabric CSR
grant throughout that boot. The streamer opens the reserved ring through the
driver and keeps its handle for the mapping lifetime. Shutdown revokes the fabric
grant before returning GPIO48 high; FPGA clocks and bridges must remain available
until the driver's shutdown callback completes. A fabric hard reset clears the
grant and requires the matching static boot lifecycle to establish it again.

This baseline uses a static device tree and does not support hot-unbinding the
platform driver or removing its device-tree node while a mapping exists. Module
ownership keeps an active open/mapping from unloading the module. For a new
FPGA image or memory map, stop the application as part of the board shutdown
procedure and boot the matching FPGA/kernel/DTB combination again. Merely
stopping the platform oneshot service does not unload the driver or return the
codec bus to HPS.

The project currently provides source and build/deployment recipes. Kernel
compilation, installation, and board boot have not yet been demonstrated for
this platform baseline. Device-tree provenance is recorded in
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
