# FPGA-only board power measurement

This target runs the maintained T-RECAP numerical core on the DE1-SoC without
booting HPS Linux. It supplies a deterministic nonzero BRAM record, checks every
output against an independently checked reference ROM, and exposes finite-batch
control and counters through JTAG. The normal HPS/DDR/Ethernet image and its
startup requirements remain the system-integration target.

## Workload and comparison

Each epoch processes the existing 1024-sample multitone record. It contains nine
STFT frames and emits all 1536 output samples, including startup and the full
tail. The input file is
`artifacts/test_vectors/near_threshold_multitone_Ns1024_thr64/x_in.memh`.
Its historical directory name does not select the threshold for this experiment.

| Operating point | Raw THR2 | Purpose |
| --- | ---: | --- |
| Dense | 0 | Retain all eligible bins |
| Masked | 100000000000 | Exercise spectral suppression on the identical input |

Both configurations run in the same placed-and-routed image. The FFT and IFFT
retain their complete schedules. This comparison measures the electrical and
reconstruction consequences of two threshold operating points; it does not
demonstrate a zero-skipping accelerator optimization. No ARM speedup is measured.

Replay is unpaced and accepts backpressure from the existing core. It is a
compute-load experiment, not a live 48 ksample/s audio demonstration. Useful
input counts exclude padding and output-tail samples. Every repeated record
starts a new finite stream, so its startup and tail overhead are included.

`scripts/measurement/prepare_vectors.py` runs the C++ reference executable and
the independent recursive integer oracle at both thresholds. It requires exact
agreement for all 1536 outputs before producing the two checker ROMs. The
artifact manifest records coefficients, input, oracle, executable and output
hashes. This is a bounded reference check on these two workloads.

## Measurement image

`platform/de1soc/measurement/` contains the standalone physical wrapper, finite
batch controller, Quartus project-generation script, constraints, timing gate,
and JTAG controller. The implementation imports `filelists/rtl_core_plus_fft.f`
and does not modify the production FFT, mask, IFFT or WOLA arithmetic.

The image uses CLOCK_50 at a nominal 50 MHz. KEY0 resets the image; release is
synchronized and a power-up delay also supplies reset. LEDR is held low across
all operating points so display changes do not create a load difference. The
fitted image reserves unused FPGA pins as tri-stated inputs with weak pull-ups;
the fitted report, rather than the shorthand project setting, defines this
electrical state. HPS transport, codec
capture and Ethernet are outside this target.

Two synchronous reference ROMs are read for each accepted output. The controller
checks output value and index, input/output/frame counts, canonical core
completion, and fault status before completing an epoch. The output checker,
JTAG logic and counters remain in the image during power measurements. Their
electrical cost is therefore included. The rolling diagnostic checksum is not
used as proof of output equality.

Mode and epoch count are staged first, allowed to settle, then accepted through
a separate start-toggle change. This avoids relying on atomic synchronization
of an asynchronous multibit bus. Parameters remain owned by that batch. A
snapshot toggle captures all 480 status bits together; the host waits for its
acknowledgement before interpreting the counters. The host rejects incomplete
batches, mismatches, faults, or unexpected counts.

## Physical boundary

The INA228 stock 15 milliohm shunt is in the positive 12 V input path. VIN+ is
connected to the adapter side, VIN- to the board-positive side, VBUS to VIN+,
and GND to the common negative return. Upstream sensing includes shunt and
downstream wiring losses in the reported DC-input energy. The USB-powered
Feather is outside that boundary. Adapter AC conversion losses are not measured.

The logger uses continuous bus/shunt conversion, 280 microseconds per channel,
16-sample averaging, and 10 Hz serial reporting. Energy comes from the INA228
hardware accumulator; it is not inferred by summing sparse power snapshots.
Diagnostic errors invalidate the session. A successful communication check or
consistent voltage/current reading is not independent accuracy calibration.

## Execution and evidence

1. Prepare and cross-check the two output ROMs.
2. Run `scripts/measurement/run_measurement_sim.py` to execute
   `sim/verification/measurement_engine_tb.sv`, including repetition,
   command ownership, snapshot, injected mismatch and fault recovery cases.
3. Build in a fresh directory with `platform/de1soc/measurement/build.ps1`.
   Provide the repository, measurement directory, build directory and actual
   Quartus installation explicitly. Check fitted pins, all fabric timing
   corners and the retained unconstrained/JTAG reports before programming.
4. Program the resulting `.sof` through JTAG at the FPGA chain position. This
   is volatile configuration; power cycling removes it.
5. Run the campaign with the synchronized logger and JTAG controller. Admit
   one epoch at each threshold, collect an initial idle interval, warm both
   modes, and execute repeated AB/BA pairs. Keep the same hardware connections.
6. Analyze the single meter session together with timing brackets, exact FPGA
   cycle/count snapshots and tool/source/image identities. Preserve rejected
   trials and errors rather than turning missing evidence into a pass.

The host and Feather exchange timestamped messages with measured request/reply
bounds. Host UTC-to-monotonic anchors align the Quartus Tcl events with those
messages. The analysis records clock-rate and sensor-timing assumptions, reports
energy bounds from accumulator samples bracketing each finite batch, and also
reports power in a guaranteed interior interval. Interpolated joules are labeled
as estimates. Statistical intervals across repeated pairs describe repeatability;
they do not include unknown instrument calibration error or establish a universal
energy-saving claim.

The authoritative result for a physical run is its retained source/image hashes,
programming log, on-board completion evidence, raw meter session, synchronization
records and analysis. Build success by itself is not a measurement result.

## Completed campaign and repeat execution

The [25 September 2026 report](../results/board_power_20260925/README.md) contains the first completed campaign: twelve trials, six paired comparisons, 301,989,888 checked outputs, zero mismatches and zero fault flags. It includes portable meter, synchronization and trial data for offline reanalysis. The full build, simulation and programming logs remain in `runs/measurement/20260925_fpga/`.

Run commands from the repository root. Set `python`, the Quartus installation, ModelSim directory, cable/device identifiers and serial port for the actual computer. Python 3.12 and matplotlib 3.11.2 were used for the recorded analysis; plotting dependencies are listed in `scripts/measurement/requirements.txt`. No instrument or JTAG access is needed for offline reanalysis.

The build and simulation runners require new output directories. A fresh build follows:

```powershell
$quartusRoot = 'D:/QuartusLite20.1.1/quartus' # example installation
$simulatorDir = 'D:/QuartusLite20.1.1/modelsim_ase/win32aloem'
python scripts/measurement/run_measurement_sim.py --repo . --simulator-dir $simulatorDir --run-dir runs/measurement/repeat/simulation
./platform/de1soc/measurement/build.ps1 -RepoRoot . -MeasurementDirectory ./platform/de1soc/measurement -BuildDirectory ./runs/measurement/repeat/build -QuartusRoot $quartusRoot
```

Review fitted pin assignments and all timing/crossing reports before programming a new image. Preserve its SOF hash, programming command and exit status in a run receipt. The recorded experiment's image and device selection are in its retained programming manifest. FPGA programming is a separate operation from the campaign runner; the runner does not reload the SOF.

Once the checked image is programmed and the synchronized logger is installed, the following invokes the complete finite campaign. Example identifiers match the recorded setup; discover them again if hardware or USB ports change.

```powershell
python scripts/measurement/run_campaign.py --repo . --run-dir runs/measurement/repeat/campaign --quartus-root $quartusRoot --hardware 'DE-SoC [USB-1]' --device '@2: 5CSE(BA5|MA5)/5CSTFD5D5/.. (0x02D120DD)' --port COM7 --program-manifest runs/measurement/repeat/program_manifest.json
```

The runner first checks one epoch at each threshold, records 20 seconds of idle, warms both conditions, executes three ABBA blocks with two-second gaps, then records 20 seconds of final idle. Every measured trial contains 16,384 epochs. It obtains a final coherent fault-free idle snapshot before stopping capture. The host owns the Feather serial port and JTAG for the run; close other clients before starting.

`campaign_manifest.json` must finish with `PASS_CAPTURE_AND_TRIAL_ADMISSION`. Its `analysis_argv` records the exact offline analyzer command, including the selected CSV, synchronization file, admitted trial file, and condition names. A capture pass establishes usable data and correct selected-workload execution; it does not establish an energy-saving conclusion. The analyzer writes a new directory and retains timing assumptions explicitly. `publication_report.py` packages the recorded campaign's checked evidence for publication; it deliberately checks the twelve-trial protocol and does not silently accept a different experiment design.

Programming is volatile. At the end of a successful campaign the core is idle, the cleanly closed capture files are retained, and the Feather remains ready to log again. Turning off DE1-SoC removes this FPGA configuration.
