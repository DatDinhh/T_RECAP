# Raw CU8 host client

`trf1_client.c` is the exact client used in the recorded physical RF campaign. It sends raw CU8 pairs and drains reconstructed Y and TSP1. Its numerical signal processing workload is zero. It performs transport, identity, range, progress and fault checks.

## Offline verification

On Linux with GCC:

```sh
bash build_offline.sh /absolute/path/to/fresh-output
```

The script compiles with warnings as errors and undefined-behavior sanitization. It runs 28 register-mock cases, 11 file-boundary cases and four numeric parser cases. These operations do not open `/dev/mem` or communicate with a board.

Set `CC` to select a native C compiler. If `ARM_CC` and `QEMU_ARM` are available, the script also produces a static Cortex-A9 client and repeats the register tests under emulation:

```sh
ARM_CC=arm-linux-gnueabihf-gcc QEMU_ARM=qemu-arm bash build_offline.sh /absolute/path/to/another-fresh-output
```

## Hardware boundary

The client supports a separate explicit `--execute-hardware` mode. Use it only after the correct FPGA image, Linux boot, clocks, reset and bridges have been qualified. It requires the expected SOURCE_ID and current boot identity and refuses mismatched geometry.

Hardware runs need an external process watchdog because a blocked physical MMIO transaction cannot be interrupted by an in-process timeout. The original controller uses a 45-second client deadline with a 50-second outer watchdog. No offline command in this guide enables physical execution.

The client creates separate `.tsp1`, `.y.i32le` and `.json` results. `CAPTURED_PENDING_PC_VALIDATION` means the transaction completed but its signal outputs still require independent laptop verification. Cycle counts include host stalls and are not isolated arithmetic latency.
