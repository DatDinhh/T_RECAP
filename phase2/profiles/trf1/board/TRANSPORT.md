# Recorded-file RF transport

The implemented RF trial uses a bounded file-transfer workflow. It is separate from the older audio TCP service and from the public recorded website.

```text
Laptop CU8 file
  -> bounded TCP archive upload
  -> HPS RAM file
  -> local ARM trf1_client
  -> lightweight HPS-to-FPGA bridge
  -> TRF1 raw-I/Q FIFO and hardware adapter
  -> existing numerical core
  -> Y and TSP1 FIFOs
  -> HPS RAM result files
  -> bounded TCP results-archive download
  -> laptop reference checks and visualization
```

The HPS client transports bytes and performs admission, count and fault checks. Interpolation, mixing, FFT, thresholding and IFFT/WOLA run in FPGA fabric. The client does not perform these DSP operations.

The capture controller [board_control.py](orchestration/board_control.py) and [capture.py](orchestration/capture.py) preserve the implemented transaction sequence. Their published version uses `TRECAP_RF_WORKSPACE` for the original qualified workspace and `TRECAP_PWSH` or `pwsh` from PATH for PowerShell. They still require the original UART runner, verified package, deployment receipts, RAM boot assets, fresh boot identity and physical ownership checks. They are source archives, not a self-contained board installer.

The controller admits the current boot, bridge and source identity before transfer. Payloads contain raw CU8 and ARM tools. Golden PCM, Y and TSP1 references stay on the laptop. The capture client verifies the TRF1 magic, ABI, SOURCE_ID and geometry before using MMIO.

Each bus word carries I in bits 7:0 and Q in bits 15:8. Bits 31:16 must be zero. Writes are bounded by FIFO space and remaining configured pairs. Output reads drain both waveform and spectral FIFOs during execution to prevent deadlock.

FPGA completion means production finished. It does not mean the HPS or laptop has received every output. The client must reconcile all input, RF-valid, core-input, Y, frame and TSP1 counts and drain both output queues before returning success.

No persistent RF network service, browser RF upload route, live receiver input or automatic profile switching is part of this implementation. The board must run the TRF1 image before this client is used. An audio TSH2 image rejects the RF identity checks.
