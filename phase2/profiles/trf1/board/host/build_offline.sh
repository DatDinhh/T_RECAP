#!/usr/bin/env bash
set -euo pipefail
ulimit -c 0
src=$(cd -- "$(dirname -- "$0")" && pwd)
out=${1:?fresh absolute output directory required}
case "$out" in /*) ;; *) printf '%s\n' 'Output must be absolute' >&2; exit 2;; esac
test ! -e "$out"
mkdir -p "$out/tmp"
export TMPDIR="$out/tmp"
cc=${CC:-gcc}
flags=(-std=c11 -O2 -Wall -Wextra -Werror -fno-lto)
"$cc" "${flags[@]}" -fsanitize=undefined -fno-sanitize-recover=all "$src/trf1_client.c" -o "$out/trf1_client.host"
"$out/trf1_client.host" --self-test > "$out/native_mock.json"
"$cc" "${flags[@]}" -fsanitize=undefined -fno-sanitize-recover=all "$src/test_input.c" -o "$out/test_input.host"
"$out/test_input.host" "$out/tmp" > "$out/input_tests.json"
if [[ -n ${ARM_CC:-} && -n ${QEMU_ARM:-} ]]; then
  "$ARM_CC" "${flags[@]}" -static -mcpu=cortex-a9 -mfpu=neon -mfloat-abi=hard "$src/trf1_client.c" -o "$out/trf1_client.arm"
  "$QEMU_ARM" "$out/trf1_client.arm" --self-test > "$out/arm_mock.json"
  cmp "$out/native_mock.json" "$out/arm_mock.json"
fi
sha256sum "$src/trf1_client.c" "$src/test_input.c" "$src/build_offline.sh" > "$out/source_sha256.txt"
printf '%s\n' PASS_TRF1_OFFLINE_CLIENT
