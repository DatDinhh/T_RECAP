# Phase 1 history

We preserve the earlier Haar-transform proof of concept under `legacy/phase1/`. It explains the project's starting point and remains separate from the current Phase 2 implementation.

| Phase 1 | Phase 2 |
| --- | --- |
| Two-sample Haar transform | 256-point STFT/WOLA |
| Non-overlapping sample pairs | 128-sample hop with overlap |
| Threshold on detail magnitude | Threshold `THR2` in full-width magnitude-squared domain |
| Exact zero-threshold reconstruction | Quantized windows, twiddles, FFT/IFFT and WOLA |
| Earlier self-contained board demonstration | DE1-SoC FPGA, HPS DDR/Ethernet and PC dashboard |

Phase 1 files must not appear in active Phase 2 filelists or supply current constants, interfaces, delay rules, or reference outputs. Current software lives at `sw/reference_model/`; current expected outputs live at `artifacts/reference_outputs/`.

The historical tree groups RTL, testbench files, software, tools, artifacts, and reports into their respective subdirectories. Existing names such as `golden_model/` are retained within that history and do not give the current Phase 2 source a different authority status.
