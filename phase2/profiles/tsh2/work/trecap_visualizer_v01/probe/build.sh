#!/usr/bin/env bash
set -euo pipefail
ulimit -c 0
src=$(cd -- "$(dirname -- "$0")" && pwd)
out=${1:?fresh absolute output directory}
test ! -e "$out"
mkdir -p "$out/tmp"
export TMPDIR="$out/tmp"
deps=${TSH2_ARM_DEPS:?set TSH2_ARM_DEPS to the externally provided cross-toolchain root}
export PATH="$deps/usr/bin:$PATH" LD_LIBRARY_PATH="$deps/usr/lib/x86_64-linux-gnu${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
flags=(-std=c11 -O2 -Wall -Wextra -Werror -fno-lto)
gcc "${flags[@]}" -fsanitize=undefined -fno-sanitize-recover=all "$src/tsh2_probe.c" -o "$out/tsh2_probe.host"
"$out/tsh2_probe.host" --self-test > "$out/native_mock.json"
arm-linux-gnueabihf-gcc-13 --version > "$out/compiler.txt"
printf '%s\n' "${flags[@]}" -static -mcpu=cortex-a9 -mfpu=neon -mfloat-abi=hard > "$out/flags.txt"
arm-linux-gnueabihf-gcc-13 "${flags[@]}" -static -mcpu=cortex-a9 -mfpu=neon -mfloat-abi=hard "$src/tsh2_probe.c" -o "$out/tsh2_probe.arm"
qemu-arm "$out/tsh2_probe.arm" --self-test > "$out/arm_mock.json"
arm-linux-gnueabihf-readelf -h -l -A -d "$out/tsh2_probe.arm" > "$out/elf.txt"
sha256sum "$src/tsh2_probe.c" "$src/build.sh" "$out/tsh2_probe.arm" > "$out/sha256.txt"
printf '%s\n' PASS_TSH2_READ_ONLY_PROBE_BUILD_MOCKS
