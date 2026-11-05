# Historical RF board integration settings

These project-authored top-level files and constraints are byte-identical to the qualified RF `build02` snapshot. They show how `trecap_rf_board_adapter` connects to the existing HPS lightweight bridge and board clock/reset topology. The original top-level comment still names the earlier PCM ancestor. The instantiated RF adapter and the TRF1 identity define this fitted profile.

The project retained the filename `audio_hps` when it became an RF application. That filename is not a runtime audio capability. The QSF names the RF adapter and historical SOURCE_ID explicitly.

To reconstruct the original source layout, the non-vendor files under the adjacent [snapshot](../../snapshot) belong at the Quartus project root. The two top-level `.sv` files here belong in its `sources` folder. The `.qsf`, `.qpf`, `.sdc` and `.tcl` files belong at that root. The QSF additionally requires `legacy/platform/de1soc/qsys/system/synthesis/system.qip` and its generated Intel dependencies.

The public repository does not bundle that generated vendor closure or a ready-to-program image. Regenerate Platform Designer IP with the matching board preset and tool version, validate its HPS and DDR interface, and create a fresh source identity for a new build. Do not assert that a regenerated build has the historical SOURCE_ID merely because the project files contain it.

The original full build used Quartus Lite 20.1.1 for Cyclone V `5CSEMA5F31C6`, with a 50 MHz fabric clock. It occupied 7,196 ALMs, 48 M10K blocks and 36 DSP blocks. Historical evidence checked 18 clocks, four timing corners, 32 calibrated DDR categories, 127 HPS pins, 11 FPGA pins and 15 HPS handoff files. See [the verification report](../../../../docs/verification/rf_iq/README.md) for the bound receipts and limitations.

A new board build requires fresh compilation, timing, pin, handoff and runtime admission checks. The simulator verifies the application/core boundary but does not model the HPS processor, DDR controller, Ethernet or generated bridge.
