# SPDX-License-Identifier: MIT
# U-Boot v2025.01, Cyclone V / DE1-SoC, static boot only.
# Build this text with mkimage -A arm -O linux -T script -C none.
# Required deployment variables:
#   trecap_rbf_file          FAT path to this build's full Cyclone V RBF.
#   trecap_handoff_ready=1   Operator assertion that the running SPL/preloader
#                           uses this RBF's generated HPS/DDR handoff, including
#                           the 64-bit bidirectional f2h_sdram0_data port.
# Optional variables default to MMC0 FAT partition1 and ext4 root partition2.
# No flash writes, saved environment writes, or guessed bridge MMIO operations.

setenv trecap_fatal 'echo "T-RECAP boot halted. Correct the image/handoff or failed load."; bridge disable; while true; do sleep 1; done'

if test "${trecap_handoff_ready}" != "1"; then
    echo "Set trecap_handoff_ready=1 only for a matching generated SPL/preloader handoff."
    run trecap_fatal
fi
if test -z "${trecap_rbf_file}"; then
    echo "trecap_rbf_file must select the matching full Cyclone V RBF."
    run trecap_fatal
fi

if test -z "${trecap_mmc}"; then setenv trecap_mmc 0; fi
if test -z "${trecap_bootpart}"; then setenv trecap_bootpart 1; fi
if test -z "${trecap_root}"; then setenv trecap_root /dev/mmcblk0p2; fi
if test -z "${trecap_rootfstype}"; then setenv trecap_rootfstype ext4; fi
if test -z "${trecap_kernel_file}"; then setenv trecap_kernel_file zImage-6.12.109-trecap; fi
if test -z "${trecap_fdt_file}"; then setenv trecap_fdt_file socfpga_cyclone5_trecap.dtb; fi

# Nonoverlapping load regions below 160 MiB, outside the 0x3e000000 ring.
# The script itself must be loaded at 0x02100000, at most 64 KiB.
setenv trecap_kernel_addr 0x01000000
setenv trecap_kernel_max 0x01000000
setenv trecap_fdt_addr 0x02000000
setenv trecap_fdt_max 0x00100000
setenv trecap_rbf_addr 0x08000000
setenv trecap_rbf_max 0x02000000
# Keep boot-time FDT relocation below 512 MiB, away from the reserved ring.
setenv bootm_low 0x00000000
setenv bootm_size 0x20000000
setenv fdt_high 0x20000000

if bridge disable; then
    echo "FPGA-facing bridges disabled."
else
    run trecap_fatal
fi
if mmc dev ${trecap_mmc}; then
    if mmc rescan; then
        echo "Boot MMC available."
    else
        run trecap_fatal
    fi
else
    run trecap_fatal
fi

# fatsize guards every destination before any file bytes are written there.
if fatsize mmc ${trecap_mmc}:${trecap_bootpart} ${trecap_rbf_file}; then
    if itest.l ${filesize} -gt 0 && itest.l ${filesize} -le ${trecap_rbf_max}; then
        setenv trecap_expected_size ${filesize}
    else
        run trecap_fatal
    fi
else
    run trecap_fatal
fi
if fatload mmc ${trecap_mmc}:${trecap_bootpart} ${trecap_rbf_addr} ${trecap_rbf_file} ${trecap_expected_size}; then
    if itest.l ${filesize} -ne ${trecap_expected_size}; then run trecap_fatal; fi
else
    run trecap_fatal
fi
if fpga load 0 ${trecap_rbf_addr} ${filesize}; then
    echo "Full FPGA image loaded."
else
    run trecap_fatal
fi

# Gen5 bridge enable restores cached SPL handoff[3] to fpgaport_rst.
# It cannot manufacture the correct port configuration from a stock zero handoff.
if bridge enable; then
    echo "Bridges restored using the running SPL/preloader handoff."
else
    run trecap_fatal
fi

if fatsize mmc ${trecap_mmc}:${trecap_bootpart} ${trecap_kernel_file}; then
    if itest.l ${filesize} -gt 0 && itest.l ${filesize} -le ${trecap_kernel_max}; then
        setenv trecap_expected_size ${filesize}
    else
        run trecap_fatal
    fi
else
    run trecap_fatal
fi
if fatload mmc ${trecap_mmc}:${trecap_bootpart} ${trecap_kernel_addr} ${trecap_kernel_file} ${trecap_expected_size}; then
    if itest.l ${filesize} -ne ${trecap_expected_size}; then run trecap_fatal; fi
else
    run trecap_fatal
fi

if fatsize mmc ${trecap_mmc}:${trecap_bootpart} ${trecap_fdt_file}; then
    if itest.l ${filesize} -gt 0 && itest.l ${filesize} -le ${trecap_fdt_max}; then
        setenv trecap_expected_size ${filesize}
    else
        run trecap_fatal
    fi
else
    run trecap_fatal
fi
if fatload mmc ${trecap_mmc}:${trecap_bootpart} ${trecap_fdt_addr} ${trecap_fdt_file} ${trecap_expected_size}; then
    if itest.l ${filesize} -ne ${trecap_expected_size}; then run trecap_fatal; fi
else
    run trecap_fatal
fi
if fdt addr ${trecap_fdt_addr}; then
    echo "Static T-RECAP DTB selected."
else
    run trecap_fatal
fi

setenv bootargs "console=ttyS0,115200 root=${trecap_root} rootfstype=${trecap_rootfstype} rootwait rw ${trecap_extra_bootargs}"
bootz ${trecap_kernel_addr} - ${trecap_fdt_addr}
# A successful bootz does not return. Any return must keep Linux stopped.
run trecap_fatal
