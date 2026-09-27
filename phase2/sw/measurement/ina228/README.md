# INA228 initial instrument bringup

This program checks USB/I2C communication and streams instrument readings. It is not a calibrated energy benchmark and does not establish FPGA energy savings.

For synchronized board experiments, install `device_code_sync.py` as `code.py` and use the [measurement protocol](MEASUREMENT_PROTOCOL.md) with the [FPGA campaign guide](../../../docs/bringup/fpga_measurement.md). The [25 September result](../../../docs/results/board_power_20260925/README.md) records the first completed campaign. The original bringup script below remains useful for basic communication checks.

## Install and start

Use the plain Adafruit Feather RP2040 running CircuitPython. Copy `device_code.py` to its CIRCUITPY drive as `code.py`. Install Adafruit INA228 2.0.5 and the matching CircuitPython `adafruit_bus_device` and `adafruit_register` dependencies in `lib/`. Open the Feather's actual USB serial console; its COM number depends on the computer. Ctrl-C stops the program.

The STEMMA QT connector uses SCL/SDA and `board.STEMMA_I2C()`. If its pull-ups are missing during startup, or address 0x40 is absent, the program prints a `#` JSON waiting message every two seconds. After successful I2C construction it reuses that bus instead of deinitializing the cached board object. I/O errors cause explicit error metadata and a retry; a recovered sensor begins a new announced session. Unexpected runtime errors are not hidden.

## Capture on Windows

From the project root, select the Feather's current COM port and run:

```powershell
.\sw\measurement\ina228\capture.ps1 -Port COM7 -OutputDirectory .\runs\measurement\my_run -Seconds 10 -Restart
```

COM7 is an example, not a fixed assignment. The script checks that the selected port belongs to a Feather RP2040 before sending control bytes. Close other serial consoles first. `-Restart` stops and restarts `code.py`, resetting the instrument session; it does not control the DE1-SoC. The capture produces a raw serial log, JSON-lines metadata and a separate CSV for each session. Startup consumes part of a timed capture, so use sample timestamps for the recorded span.

The validated setup used CircuitPython 10.3.1, INA228 2.0.5, Register 1.13.0 and BusDevice 5.2.17. Source archives can retain an automatic placeholder in their module `__version__`; the downloaded release tags and archive hashes in the run manifest identify the installed sources.
## Wiring boundary

Switch off and disconnect the DE1-SoC supply and Feather USB before changing wiring. The Feather supplies the INA228 logic through STEMMA QT; do not connect 12 V to the Feather or to the INA228 logic VIN, SDA or SCL pins.

For high-side sensing, put the INA228 shunt in series with the board supply positive lead: adapter positive to VIN+, VIN- to the DE1-SoC positive input. The adapter negative and board negative remain connected, and the INA228 ground needs the same reference. Check actual terminal labels and polarity before applying power. VBUS is a separate measurement input and must be connected; the two current terminals and STEMMA alone do not wire it. The board's VBUS-to-VIN+ jumper is open by default.

Record the actual VBUS sense location. If VBUS senses the adapter/VIN+ side, reported power includes shunt loss and downstream wiring loss. Sensing a different point changes that boundary. The USB-powered Feather's consumption is outside this board-supply measurement. A lit DE1-SoC does not prove that the measurement wiring is correct.

## Configuration and data

The program explicitly selects the stock 0.015-ohm shunt, 10 A calibration range, wide +/-163.84 mV ADC range, 16-sample averaging, 280 us bus conversion and 280 us shunt conversion. `CONT_BUS_SHUNT` performs continuous conversions without temperature. Averaged results update nominally every 8.96 ms (about 111.6 Hz); hardware energy accumulation uses underlying conversions. The requested serial rate is 10 Hz, with missed deadlines reported. These rates are configuration-derived, not measured timing guarantees.

Lines beginning with `#` contain JSON provenance, session boundaries or diagnostics. A CSV header appears once per session. The first thirteen columns are:

```text
seq,t_start_s,t_end_s,bus_voltage_V,shunt_voltage_V,current_A,power_W,energy_J,energy_since_start_J,math_overflow,energy_overflow,memory_ok,conversion_ready
```

Four further columns are `math_overflow_latched`, `energy_overflow_latched`, `memory_error_latched`, and `accumulation_valid`. The three raw fault columns retain each diagnostic snapshot. Latched faults invalidate the remainder of that accumulated-energy session; decreasing energy also invalidates it and emits a reason. Invalid records remain visible instead of being replaced by zero. `accumulation_valid=1` only means these limited diagnostic checks have passed; it does not certify accuracy or wiring.

At each explicit session start, the program waits 50 ms, resets accumulators once, and records a baseline energy and its read interval. Sequence numbers, timestamps and energy deltas restart only with a new `session_start` message and header. Never concatenate those sessions as one continuous energy integral. `energy_since_start_J` is the hardware energy reading minus that session's baseline, not an integral of sparse serial power samples.

The ADC operates continuously. Voltage, shunt, current, power and energy are separate I2C reads, with `t_start_s` and `t_end_s` covering their read window. They are not an atomic snapshot or simultaneous analog measurements. Flags are read once before energy because reading energy clears its overflow indication; a conversion can still occur during the sequence. `conversion_ready=0` is retained as a freshness indicator and is not itself a sensor error.

Current is signed and is not converted to its absolute value. Power and energy are unsigned device results. Negative current needs interpretation of wiring/direction; positive power alone does not establish correct direction. `memory_ok=1` means the trim-memory checksum is healthy. The Adafruit example's raw averaging/conversion getters are enum indices; metadata here uses decoded physical settings.

Initial acceptance means recognizing the expected sensor, obtaining plausible voltage/current, healthy diagnostics and increasing energy under load. True calibration, uncertainty characterization, coherent acquisition and matched FPGA workload experiments remain separate tasks. Printing more decimal places does not establish that precision.

## Sources

- [Feather RP2040 CircuitPython installation](https://learn.adafruit.com/adafruit-feather-rp2040-pico/circuitpython)
- [INA228 wiring and CircuitPython setup](https://learn.adafruit.com/adafruit-ina228-i2c-power-monitor/circuitpython-and-python)
- [INA228 pinout and VBUS jumper](https://learn.adafruit.com/adafruit-ina228-i2c-power-monitor/pinouts)
- [Adafruit INA228 driver](https://github.com/adafruit/Adafruit_CircuitPython_INA228/blob/2.0.5/adafruit_ina228.py)
- [TI INA228 datasheet](https://www.ti.com/lit/ds/symlink/ina228.pdf)

