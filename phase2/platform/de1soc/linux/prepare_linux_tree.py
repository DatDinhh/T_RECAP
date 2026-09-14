#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Stage T-RECAP source files into a Linux 6.12.109 build workspace.

This command copies source and registers one DTB target. It does not download,
configure, compile, install, or execute kernel or userspace code.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import re
import sys

KERNEL_VERSION = (6, 12, 109)
DTS_TARGET = "socfpga_cyclone5_trecap.dtb"
DTS_FILES = (
    "socfpga_cyclone5_trecap.dts",
    "trecap_platform.dtsi",
    "trecap_reserved_memory.dtsi",
)
MODULE_FILES = (
    "platform/de1soc/linux/driver/Makefile",
    "platform/de1soc/linux/driver/trecap_platform.c",
    "sw/hps/include/trecap_ring_device.h",
    "sw/hps/include/generated/trecap_csr.h",
)


def contained_path(base: Path, relative: str) -> Path:
    candidate = (base / relative).resolve()
    if not candidate.is_relative_to(base):
        raise ValueError(f"destination leaves the selected directory: {candidate}")
    return candidate


def prepare(kernel_tree: Path, module_stage: Path) -> list[Path]:
    repo = Path(__file__).resolve().parents[3]
    linux_sources = repo / "platform/de1soc/linux"
    kernel_tree = kernel_tree.resolve(strict=True)
    module_stage = module_stage.resolve()
    if any(char.isspace() for char in str(kernel_tree) + str(module_stage)):
        raise ValueError("kernel and module build paths must not contain whitespace")
    if module_stage == repo or repo.is_relative_to(module_stage):
        raise ValueError("select a dedicated module staging directory, not the repository or its parent")

    kernel_makefile = contained_path(kernel_tree, "Makefile")
    kernel_text = kernel_makefile.read_text(encoding="utf-8")
    version = []
    for name in ("VERSION", "PATCHLEVEL", "SUBLEVEL"):
        match = re.search(rf"^{name}\s*=\s*(\d+)\s*$", kernel_text, re.MULTILINE)
        if match is None:
            raise ValueError(f"kernel Makefile has no unambiguous {name}")
        version.append(int(match.group(1)))
    extra = re.search(r"^EXTRAVERSION\s*=(.*)$", kernel_text, re.MULTILINE)
    if tuple(version) != KERNEL_VERSION or (extra and extra.group(1).strip()):
        raise ValueError("this recipe requires an extracted Linux 6.12.109 source release")

    dts_dir = contained_path(kernel_tree, "arch/arm/boot/dts/intel/socfpga")
    if not (dts_dir / "socfpga_cyclone5.dtsi").is_file():
        raise ValueError(f"missing Cyclone V base include: {dts_dir}")
    dts_makefile = contained_path(kernel_tree, "arch/arm/boot/dts/intel/socfpga/Makefile")
    makefile_text = dts_makefile.read_bytes().decode("utf-8")
    active_makefile = "\n".join(line.split("#", 1)[0] for line in makefile_text.splitlines())

    # Read and resolve every source/destination before the first mutation.
    pending: list[tuple[Path, bytes]] = []
    for name in DTS_FILES:
        pending.append((contained_path(dts_dir, name), (linux_sources / name).read_bytes()))
    for relative in MODULE_FILES:
        pending.append((contained_path(module_stage, relative), (repo / relative).read_bytes()))
    if DTS_TARGET not in active_makefile.split():
        registration = f"dtb-$(CONFIG_ARCH_INTEL_SOCFPGA) += {DTS_TARGET}\n"
        new_makefile = makefile_text.rstrip("\r\n") + "\n\n# T-RECAP static board DTB\n" + registration
        pending.append((dts_makefile, new_makefile.encode("utf-8")))

    changed = []
    for destination, content in pending:
        if destination.is_file() and destination.read_bytes() == content:
            continue
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(content)
        changed.append(destination)
    return changed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kernel-tree", required=True, type=Path,
                        help="extracted Linux 6.12.109 source directory")
    parser.add_argument("--module-stage", required=True, type=Path,
                        help="dedicated directory preserving the driver/header repository layout")
    args = parser.parse_args()
    try:
        changed = prepare(args.kernel_tree, args.module_stage)
    except (OSError, UnicodeError, ValueError) as error:
        parser.exit(1, f"prepare_linux_tree: {error}\n")
    for path in changed:
        print(f"staged {path}")
    print(f"Source staging complete: {len(changed)} file(s) updated. No build or deployment was run.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
