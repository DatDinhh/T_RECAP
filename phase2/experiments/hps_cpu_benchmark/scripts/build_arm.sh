#!/bin/sh
# SPDX-License-Identifier: MIT
# Build only. This script does not transfer files, boot, or access a board.
set -eu

package_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
output_dir=${1:-"$package_root/build/arm"}
compiler=${ARM_CXX:-arm-linux-gnueabihf-g++}
readelf_tool=${ARM_READELF:-arm-linux-gnueabihf-readelf}

if [ -e "$output_dir" ]; then
    printf '%s\n' 'Choose a fresh build directory; existing output is preserved.' >&2
    exit 1
fi
command -v "$compiler" >/dev/null 2>&1 || {
    printf 'Compiler not found: %s\n' "$compiler" >&2
    exit 1
}
mkdir -p -- "$output_dir"
output_dir=$(CDPATH= cd -- "$output_dir" && pwd)

# Match the measured scalar-source build policy. Each source is a separate
# translation unit; the opaque consumer must not be folded into the kernel.
set -- -std=c++17 -O3 -Wall -Wextra -Wpedantic -static \
    -mcpu=cortex-a9 -mfpu=neon -mfloat-abi=hard -fno-lto \
    "$package_root/src/main.cpp" "$package_root/src/kernel.cpp" \
    "$package_root/src/consumer.cpp" -o "$output_dir/trecap_cpu_arm"

"$compiler" --version > "$output_dir/compiler_version.txt"
printf '%s\n' "$compiler" "$@" > "$output_dir/compiler_argv.txt"
"$compiler" "$@" > "$output_dir/build.log" 2>&1
if command -v "$readelf_tool" >/dev/null 2>&1; then
    "$readelf_tool" -h -l -A "$output_dir/trecap_cpu_arm" > "$output_dir/elf.txt"
else
    printf '%s\n' 'readelf unavailable; independently inspect the ARM ELF/ABI before execution.' \
        > "$output_dir/elf_review_required.txt"
fi
if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$output_dir/trecap_cpu_arm" "$package_root/src/main.cpp" \
        "$package_root/src/kernel.cpp" "$package_root/src/kernel.hpp" \
        "$package_root/src/consumer.cpp" > "$output_dir/build_sha256.txt"
fi
printf 'Built %s\n' "$output_dir/trecap_cpu_arm"
