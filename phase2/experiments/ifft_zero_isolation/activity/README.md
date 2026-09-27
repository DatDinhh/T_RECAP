# Checked RTL activity capture

`run_power_capture.py` runs `power_capture_tb.sv` twice against an explicitly prepared candidate repository: mode 2 (masked baseline) and mode 3 (masked isolated). Each run completes two epochs, checks protocol/mode, every output through the measurement engine's reference ROM checker, counter totals and the expected 176,662 elapsed cycles, then emits a separate VCD.

From the experiment package directory:

```text
python -B activity/run_power_capture.py --repo CANDIDATE_REPOSITORY --simulator-dir MODELSIM_BIN --run-dir NEW_ACTIVITY_DIRECTORY --testbench activity/power_capture_tb.sv
```

The output directory must not exist. The runner uses the candidate repository's measurement simulation helper and records source hashes, commands, logs and VCD hashes. It performs no hardware access. Local run receipts contain the actual tool/source paths for diagnosis; this source package contains no machine-specific path or captured VCD.

These are RTL activity files. Mapping them to a fitted netlist, applying an activity interval and interpreting unmatched nodes are separate steps; a transition count is not a calibrated power measurement. Published admitted findings belong in the [experiment results report](../../../docs/results/ifft_zero_isolation_20260925/README.md).
