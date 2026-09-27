# Experimental IFFT zero-operand isolation

This package preserves the production source tree and supplies an explicit experimental overlay. It studies whether holding multiplier operands and product registers during exact-zero IFFT transactions can reduce switching while preserving the masked output and the fixed execution schedule.

The current evidence supports an implementation experiment, not a proven energy-saving claim. Source-level isolation and RTL activity do not establish physical DSP behavior, post-fit power, or whole-board energy savings. The [results report](../../docs/results/ifft_zero_isolation_20260925/README.md) owns the admitted simulation, synthesis, activity and measurement findings as they become available.

## Experiment boundary

The four datapath replacements add compile-time support parameters that default to `0`. With support disabled, runtime control is ignored and synthesis can remove the added datapath. The shared FFT butterfly retains this default. The candidate measurement top explicitly enables support and exposes protocol 2; mode 2 selects masked baseline and mode 3 selects masked isolation. Both use squared-magnitude threshold `100000000000`, the same input ROM and the same full-output reference ROM. The engine parameter itself defaults to `0`, preserving protocol 1 and rejecting mode 3 unless explicitly enabled.

An IFFT frame captures its isolation setting on the first accepted complex input. The isolated zero transaction produces the exact zero product and preserves subsequent rounding, saturation, addition/subtraction and valid/ready behavior. No butterfly, RAM operation, output sample or schedule state is skipped. **No runtime improvement is expected.** See [PROTOTYPE.md](PROTOTYPE.md) for the datapath and ownership details.

The B/C comparison uses one fitted image with runtime isolation disabled/enabled. Both conditions contain the added detector, muxes, held operands and control logic. It therefore cannot establish the net benefit after charging the additional hardware and implementation overhead relative to the original production image. That requires a separate controlled build comparison as well as timing, resource and electrical measurements.

The expected outputs and integer oracle are reference-model artifacts. Exact agreement is evidence for the tested contract, not a declaration that the model is a universally proven golden specification. Threshold-induced reconstruction error is held constant in the B/C comparison; changing the threshold is a separate quality tradeoff.

## Package contents and baseline ownership

[baseline_source_manifest.json](baseline_source_manifest.json) retains the original 160-file frozen source inventory and its SHA-256 hashes. [overlay_manifest.json](overlay_manifest.json) binds that manifest, each replacement's original baseline hash, all eight overlay files, and the packaged scripts, documentation and profile evidence. Six overlay files replace declared baseline files; two experimental host helpers are new. No compiled simulator libraries, FPGA images, local measurement captures or duplicate repository are distributed here.

| Overlay target | Purpose |
| --- | --- |
| `rtl/fft/trecap_fft_stage.sv` | Exact-zero multiplier-input/product-register isolation |
| `rtl/fft/trecap_ifft256.sv` | Frame-owned runtime selection |
| `rtl/core/trecap_core_top.sv` | Optional control propagation |
| `rtl/top/trecap_core_bram_replay_top.sv` | Optional replay interface propagation |
| `platform/de1soc/measurement/trecap_measurement_engine.sv` | Protocol-2 opt-in and mode-3 masked comparison |
| `platform/de1soc/measurement/trecap_measurement_top.sv` | Candidate image explicitly enables support |
| `platform/de1soc/measurement/jtag_zero_control.tcl` | Finite same-image B/C batch control |
| `scripts/measurement/run_zero_campaign.py` | Paired capture, clock mapping and admission checks |

The [profiling package](profiling/README.md) contains the independent iterative integer replay, deterministic inputs and portable numerical evidence. [verification](verification/README.md) contains bounded lockstep tests and a native ModelSim runner. [activity](activity/README.md) contains checked two-epoch RTL VCD acquisition. These sources do not change the production checkout.

## Create the experimental source tree

Use Python 3.9 or newer. Run this command from the package directory, substituting paths appropriate to the machine:

```text
python -B apply_overlay.py --repo BASELINE_REPOSITORY --output NEW_CANDIDATE_DIRECTORY
```

`BASELINE_REPOSITORY` is read only. Every file declared by the frozen baseline manifest must match exactly; a modified or incompatible source causes refusal before copying. The destination must not exist and must be outside the input repository and package. Only the declared source snapshot is copied, then the eight overlay files are applied. The installer verifies the resulting files and writes a portable `experiment_overlay_receipt.json`. It never invokes a build tool, serial port or JTAG command. Additional unrelated files in the input checkout are not copied. A partial failed destination is retained for inspection and cannot be reused.

The hash manifest identifies the baseline more precisely than a branch name. A later source revision must be reviewed and receive a new manifest; editing hashes to bypass a mismatch would remove that assurance.

Hash checks are byte exact, including line endings. The package's `.gitattributes` preserves its reviewed bytes across checkout. The baseline repository must likewise retain the line endings of the declared source snapshot; changing LF/CRLF is a source-identity change for this installer.

## Reproduce numerical and RTL checks

From the package directory:

```text
python -B profiling/profile_ifft_zeros.py --repo BASELINE_REPOSITORY --out NEW_PROFILE_DIRECTORY
python -B verification/verify_zero_host.py --candidate-repo NEW_CANDIDATE_DIRECTORY
python -B verification/run_verification.py --baseline-repo BASELINE_REPOSITORY --candidate-overlay overlay --candidate-repo NEW_CANDIDATE_DIRECTORY --simulator-dir MODELSIM_BIN --run-dir NEW_VERIFICATION_DIRECTORY --profile-csv profiling/results_01/frame_stage_counts.csv
python -B activity/run_power_capture.py --repo NEW_CANDIDATE_DIRECTORY --simulator-dir MODELSIM_BIN --run-dir NEW_ACTIVITY_DIRECTORY --testbench activity/power_capture_tb.sv
```

All output directories must be fresh. Numerical reproduction uses the standard library with `--no-plots`; generating profile figures requires Matplotlib. The verification and activity runners require native ModelSim executables. Their local evidence records include the actual tool/command paths used; those run directories are not part of this portable source package. RTL VCDs represent simulated signal activity and cannot be read directly as board power.

## Build and board acquisition

The candidate tree retains the frozen baseline's measurement build scripts. On Windows with Quartus Lite 20.1.1 and the Cyclone V device support installed:

```text
powershell -ExecutionPolicy Bypass -File NEW_CANDIDATE_DIRECTORY/platform/de1soc/measurement/build.ps1 -RepoRoot NEW_CANDIDATE_DIRECTORY -MeasurementDirectory NEW_CANDIDATE_DIRECTORY/platform/de1soc/measurement -BuildDirectory NEW_BUILD_DIRECTORY -QuartusRoot QUARTUS_ROOT
```

`QUARTUS_ROOT` is the directory containing `bin64`. Successful compile and timing-gate receipts must identify the image before it is programmed. This package does not automatically program the board.

After explicitly programming and admitting the candidate image, the experimental runner performs finite masked baseline/isolated batches using one continuous meter capture:

```text
python -B NEW_CANDIDATE_DIRECTORY/scripts/measurement/run_zero_campaign.py --repo NEW_CANDIDATE_DIRECTORY --run-dir NEW_CAMPAIGN_DIRECTORY --quartus-root QUARTUS_ROOT --hardware JTAG_HARDWARE_NAME --device JTAG_DEVICE_NAME --port METER_COM_PORT --program-manifest PROGRAM_RECEIPT_JSON
```

Unlike the preceding source and simulation commands, this command opens the selected meter serial port and launches FPGA batches through JTAG. Its defaults are six paired comparisons in ABBA order, 16,384 epochs per trial, with warmups and idle windows. Each admitted trial must have the expected full-output comparisons, fault-free counters, protocol/mode flags and identical elapsed cycle count. Clock-alignment bounds and meter calibration limits remain part of the measurement interpretation. Neither a statistically repeatable point difference nor a reduction in selected RTL transitions alone establishes a defensible electrical savings result.

## Completed evaluation

The [board experiment report](../../docs/results/ifft_zero_isolation_20260925/README.md) records the completed checks, fitted cost and paired electrical result. No distinguishable saving was found in this workload. The [report builder](study/publish_zero_report.py) and [template](study/report_template.md) preserve the publication workflow; complete admission also requires the retained local build/program and verification evidence.
