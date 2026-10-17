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
gcc "${flags[@]}" -fsanitize=undefined -fno-sanitize-recover=all "$src/service.c" -o "$out/service.host"
"$out/service.host" --mock > "$out/native_mock.jsonl"
arm-linux-gnueabihf-gcc-13 --version > "$out/compiler.txt"
printf '%s\n' "${flags[@]}" -static -mcpu=cortex-a9 -mfpu=neon -mfloat-abi=hard > "$out/flags.txt"
arm-linux-gnueabihf-gcc-13 "${flags[@]}" -static -mcpu=cortex-a9 -mfpu=neon -mfloat-abi=hard "$src/service.c" -o "$out/service.arm"
qemu-arm "$out/service.arm" --mock > "$out/arm_mock.jsonl"
arm-linux-gnueabihf-readelf -h -l -A -d "$out/service.arm" > "$out/elf.txt"
sha256sum "$src/service.c" "$src/build.sh" "$src/../../trecap_cpu_fpga_bench_v01/host02/tsh2_client.c" "$out/service.arm" > "$out/sha256.txt"
printf '%s\n' PASS_FINITE_SERVICE_BUILD_MOCKS
