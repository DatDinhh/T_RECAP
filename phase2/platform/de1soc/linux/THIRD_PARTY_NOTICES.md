# Third-party source notices

## DE1-SoC board device tree

The board description in socfpga_cyclone5_trecap.dts is adapted from:

- Project: U-Boot.
- Release: v2025.01.
- Original path: arch/arm/dts/socfpga_cyclone5_de1_soc.dts.
- Upstream source: [U-Boot v2025.01 DE1-SoC DTS](https://github.com/u-boot/u-boot/blob/v2025.01/arch/arm/dts/socfpga_cyclone5_de1_soc.dts).
- Retained notice: Copyright Altera Corporation (C) 2015.
- License: GPL-2.0+, meaning GPL version 2 or any later version.

The adaptation retains its SPDX license identifier and copyright in the source.
Our changes rename the board model, use Linux's Cyclone V include hierarchy,
remove the U-Boot-specific peripheral clock initialization override, and add
the static T-RECAP reserved-memory/platform includes. The upstream license
continues to apply to the adapted board DTS; the repository's general MIT
license does not replace it.

The full GPL version 2 text is available in
[U-Boot's GPL-2.0 license text](https://github.com/u-boot/u-boot/blob/v2025.01/Licenses/gpl-2.0.txt).

## External Linux source dependency

The build recipe downloads Linux 6.12.109 from the
[Linux kernel archives](https://cdn.kernel.org/pub/linux/kernel/v6.x/).
The kernel source tree is an external build dependency and is not vendored in
this project. Retain its COPYING and LICENSES files with any redistributed
kernel source; individual kernel files carry their own license identifiers.

Our local DTS include files, staging script, driver Makefile, and shared
userspace header carry their own SPDX notices. The platform driver carries
SPDX-License-Identifier: MIT and declares MODULE_LICENSE("Dual MIT/GPL") for
kernel integration.
