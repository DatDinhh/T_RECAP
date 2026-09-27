# Board measurement procedure

This capture compares threshold settings in one FPGA bitstream. Both settings use the same input, FFT/IFFT schedule, clocks, epoch count, and output checking. The result describes the energy and reconstruction-quality tradeoff between operating points. It does not isolate a zero-aware arithmetic implementation or establish calibrated instrument accuracy.

The INA228 measures the assembled board's DC supply. With VBUS connected upstream of the shunt, measured power includes the shunt and downstream wiring loss. The Feather's USB supply is outside this boundary. Record actual wiring, peripherals, board switch state, bitstream hash, and nominal FPGA clock with every campaign.

## Capture

The logger and capture sources are `sw/measurement/ina228/device_code_sync.py` and `sw/measurement/ina228/capture_sync.ps1`. The offline analyzer is `scripts/measurement/analyze_board_measurement.py`. Install the device source on CIRCUITPY as `code.py`. The [FPGA measurement guide](../../../docs/bringup/fpga_measurement.md) describes the image and integrated campaign runner. The device config remains stock 15 mΩ, 10 A calibration scaling, wide shunt range, 16 averages, 280 µs bus and shunt conversion times, and continuous bus/shunt mode. This is a scaling configuration, not a calibration against a reference instrument.

`capture_sync.ps1 -Port COM7 -OutputDirectory <new-directory> -Seconds 600 -Restart`

Choose the port from the connected Feather rather than assuming COM7 on another computer. The host preserves raw serial output, the original 17-column CSV, metadata, host receipt timestamps, and clock-sync exchanges. Each new device measurement session starts a separate CSV. A campaign must remain in one session; never join cumulative energy across a device reset or I2C recovery.

Every approximately two seconds, the host sends `SYNC token`. The Feather records its session-relative timestamp after receiving the command, then replies in a JSON metadata line. The host records global Windows QPC ticks before sending and after receiving. Thus the device timestamp occurred inside that host-time bracket, without assuming zero USB latency. Row receipt times alone are not synchronization points.

Use a host QPC clock for launch and completion events. If the JTAG process records UTC milliseconds, preserve UTC/QPC anchor brackets before and after the campaign and account for timestamp quantization and any anchor disagreement before conversion. Never equate capture `started_utc` with the device's energy-session epoch.

## Workload and timing

The completed campaign used 16,384 epochs per trial (28.881068 nominal seconds) and six pairs arranged as three ABBA blocks. Future comparisons should retain at least five pairs and an alternating or randomized AB/BA order. Keep the FPGA image and all board peripherals unchanged. Warm up first, preserve several seconds of idle capture before and after each batch, and record output mismatches and actual work counters. All outputs must match the reference selected for that threshold. Preserve unsuccessful trials rather than silently replacing them in the source record.

The analysis accepts a JSON manifest:

```json
{
  "qpc_frequency": 10000000,
  "trials": [
    {
      "trial_id": "pair01_A",
      "pair_id": "01",
      "condition": "threshold_0",
      "threshold2": 0,
      "launch_before_qpc": 123456000000,
      "launch_after_qpc": 123457000000,
      "completion_before_qpc": 123740000000,
      "completion_after_qpc": 123750000000,
      "cycles": 1444003840,
      "clock_hz": 50000000,
      "epochs": 16384,
      "inputs_per_epoch": 1024,
      "outputs_per_epoch": 1536,
      "frames_per_epoch": 9,
      "mismatch_count": 0,
      "completed": true
    }
  ]
}
```

These numbers illustrate schema only and are not a measurement. Use actual counter values. Optional `input_count`, `output_count`, and `frame_count` fields are checked against epoch totals. `completion_before_qpc` must be a defensible lower bound on completion, such as the time before the last probe transaction that returned busy. The beginning of a final transaction that already returns done is not a lower bound. Omit that field if no busy observation exists. The completion upper bound is the time after receiving done. Launch timestamps bracket the command that causes the FPGA start event, with an explicit clock-domain crossing allowance.

Probe word 11 contains retained fault flags. Bit 12 means unexpected core activity or a core fault after a successful batch had completed. It revokes DONE, preserves batch counts, and requires a new accepted command to clear the evidence. Reject any trial/campaign that reports this flag, including a snapshot taken during the idle interval after completion.

## Analysis

```text
python analyze_board_measurement.py --csv <session.csv> --sync <sync.jsonl> --trials <trials.json> --out <new-analysis-directory>
```

The helper rejects diagnostic faults, energy resets, inconsistent timing, unsuccessful output checking, and missing boundary coverage. It retains CSV sequence-gap counts. The analysis manifest records hashes of all inputs.

The clock calculation intersects request/reply bounds while allowing a stated relative clock-rate error. Defaults are 1,000 ppm for the Feather relative to host and 1,000 ppm for the nominal FPGA clock, a 20 ms sensor effective-time guard, and a 1 µs start-crossing allowance. These are exposed engineering assumptions, not verified oscillator or sensor specifications. Rerun with wider assumptions to check sensitivity. They do not account for shunt tolerance, gain/offset error, temperature, or absolute calibration.

Each energy read has an effective time interval from `t_start_s - guard` through `t_end_s`. For a possible batch boundary, the preceding energy read and following energy read enclose the accumulator value because accumulated energy is nondecreasing. Subtract endpoint intervals to obtain conditional batch-energy bounds. An interpolated central estimate is labeled separately. Exact fabric cycle counts tighten host launch/polling brackets; converting cycles to seconds uses the nominal clock and stated tolerance.

The primary stable-load comparison uses only the guaranteed active interior, after trimming another 0.5 s at both ends. It reports hardware accumulator difference divided by the interior read-to-read time, with timing bounds. Multiplying this power by batch duration is an estimate; it must not be described as a directly measured boundary-to-boundary energy value. Whole-board joules per input sample uses all 1,024 input samples per epoch; output and frame denominators are separate.

Paired statistics use candidate minus baseline, so a negative difference means lower measured energy or power. The optional 95% Student-t interval describes repeatability across pairs under its statistical assumptions. It does not include the instrument's systematic uncertainty. A small difference within timing bounds, drift, or repeatability is inconclusive. Report threshold quality metrics alongside any difference; do not call thresholding alone a verified compute-skipping optimization.

Outputs are `measurement_analysis.json`, a power timeline, and trial-comparison plots in PNG/PDF. The helper never programs the FPGA or accesses a serial port.
