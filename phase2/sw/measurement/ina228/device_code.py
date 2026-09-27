# SPDX-License-Identifier: MIT
"""Initial INA228 instrument bringup; not a calibrated energy benchmark."""

import json
import sys
import time

import board
import adafruit_ina228


ADDRESS = 0x40
SHUNT_OHMS = 0.015
MAX_CURRENT_A = 10.0
LOG_PERIOD_NS = 100_000_000
RETRY_SECONDS = 2.0
SETTLE_SECONDS = 0.05
PROGRAM_VERSION = "ina228-lab-bringup-1"

HEADER = (
    "seq,t_start_s,t_end_s,bus_voltage_V,shunt_voltage_V,current_A,"
    "power_W,energy_J,energy_since_start_J,math_overflow,energy_overflow,"
    "memory_ok,conversion_ready,math_overflow_latched,energy_overflow_latched,"
    "memory_error_latched,accumulation_valid"
)

CONFIG = {
    "program": PROGRAM_VERSION,
    "scope": "initial instrument bringup; no accuracy calibration or energy-saving claim",
    "board_id": getattr(board, "board_id", "unknown"),
    "circuitpython": sys.version,
    "driver_module": "adafruit_ina228",
    "driver_version": getattr(adafruit_ina228, "__version__", "unknown"),
    "expected_driver_version": "2.0.5",
    "i2c": "board.STEMMA_I2C(); plain Feather RP2040 SCL/SDA",
    "address": "0x40",
    "shunt_ohms": SHUNT_OHMS,
    "max_current_A": MAX_CURRENT_A,
    "adc_range": 0,
    "shunt_range_mV": 163.84,
    "averaging_samples": 16,
    "bus_conversion_us": 280,
    "shunt_conversion_us": 280,
    "mode": "CONT_BUS_SHUNT",
    "temperature_enabled": False,
    "nominal_result_period_ms": 8.96,
    "nominal_result_rate_Hz": 1_000_000.0 / (16 * (280 + 280)),
    "requested_log_rate_Hz": 10,
    "energy": "hardware accumulator; delta from an explicit per-session baseline",
    "timestamps": "seconds from midpoint of session baseline-energy read",
    "measurement_reads": "separate I2C transactions, not an atomic snapshot",
    "fault_columns": "raw flags plus session-latched accumulated-data validity",
    "current_direction": "signed; negative readings are retained",
    "voltage_sense_point": "not detected in software; record actual VBUS wiring",
}


def emit(event, **fields):
    fields["event"] = event
    print("# " + json.dumps(fields))


def scan_addresses(i2c):
    lock_deadline = time.monotonic_ns() + 250_000_000
    while not i2c.try_lock():
        if time.monotonic_ns() >= lock_deadline:
            raise OSError("I2C bus lock timeout")
        time.sleep(0.001)
    try:
        return i2c.scan()
    finally:
        i2c.unlock()


def configure(i2c):
    sensor = adafruit_ina228.INA228(i2c, address=ADDRESS)
    sensor.mode = adafruit_ina228.Mode.SHUTDOWN
    sensor.adc_range = 0
    sensor.set_calibration(SHUNT_OHMS, MAX_CURRENT_A)
    sensor.averaging_count = adafruit_ina228.AveragingCount.COUNT_16
    sensor.bus_voltage_conv_time = adafruit_ina228.ConversionTime.TIME_280_US
    sensor.shunt_voltage_conv_time = adafruit_ina228.ConversionTime.TIME_280_US
    sensor.mode = adafruit_ina228.Mode.CONT_BUS_SHUNT
    return sensor


def run_session(sensor, session_index):
    # Ignore startup conversions; reset once per explicitly announced session.
    time.sleep(SETTLE_SECONDS)
    sensor.reset_accumulators()
    baseline_start_ns = time.monotonic_ns()
    initial_flags = sensor.alert_flags  # Before energy, which clears ENERGYOF.
    energy_baseline = sensor.energy
    baseline_end_ns = time.monotonic_ns()
    epoch_ns = (baseline_start_ns + baseline_end_ns) // 2

    math_latched = bool(initial_flags["MATHOF"])
    energy_latched = bool(initial_flags["ENERGYOF"])
    memory_latched = not bool(initial_flags["MEMSTAT"])
    discontinuity_latched = False
    previous_energy = energy_baseline
    already_reported = set()

    emit(
        "session_start",
        session_index=session_index,
        configuration=CONFIG,
        device_id_hex="0x{:03x}".format(sensor.device_id),
        accumulators_reset_once=True,
        baseline_energy_J=energy_baseline,
        baseline_read_start_ns=baseline_start_ns,
        baseline_read_end_ns=baseline_end_ns,
        epoch_monotonic_ns=epoch_ns,
        initial_flags=initial_flags,
        note="New session: sequence, timestamps and energy baseline restart here.",
    )
    print(HEADER)

    seq = 0
    next_log_ns = time.monotonic_ns()
    while True:
        now_ns = time.monotonic_ns()
        if now_ns < next_log_ns:
            time.sleep((next_log_ns - now_ns) / 1_000_000_000.0)

        start_ns = time.monotonic_ns()
        # A diagnostic read also clears CNVRF. Do not separately poll
        # conversion_ready and then expect this snapshot to retain that event.
        flags = sensor.alert_flags
        voltage = sensor.bus_voltage
        shunt_voltage = sensor.shunt_voltage
        current = sensor.current
        power = sensor.power
        energy = sensor.energy
        end_ns = time.monotonic_ns()

        math_raw = bool(flags["MATHOF"])
        energy_raw = bool(flags["ENERGYOF"])
        memory_ok = bool(flags["MEMSTAT"])
        ready = bool(flags["CNVRF"])
        math_latched = math_latched or math_raw
        energy_latched = energy_latched or energy_raw
        memory_latched = memory_latched or not memory_ok
        if energy < previous_energy:
            discontinuity_latched = True
        previous_energy = energy

        faults = (
            ("math_overflow", math_latched),
            ("energy_overflow", energy_latched),
            ("trim_memory_check_failed", memory_latched),
            ("energy_counter_decreased", discontinuity_latched),
        )
        for reason, active in faults:
            if active and reason not in already_reported:
                emit(
                    "accumulation_invalid",
                    session_index=session_index,
                    seq=seq,
                    reason=reason,
                    action="Retaining raw readings; do not use this session as valid accumulated energy.",
                )
                already_reported.add(reason)

        valid = not (
            math_latched or energy_latched or memory_latched or discontinuity_latched
        )
        values = [
            str(seq),
            "{:.6f}".format((start_ns - epoch_ns) / 1_000_000_000.0),
            "{:.6f}".format((end_ns - epoch_ns) / 1_000_000_000.0),
            "{:.6f}".format(voltage),
            "{:.9f}".format(shunt_voltage),
            "{:.7f}".format(current),
            "{:.7f}".format(power),
            "{:.6f}".format(energy),
            "{:.6f}".format(energy - energy_baseline),
            str(int(math_raw)),
            str(int(energy_raw)),
            str(int(memory_ok)),
            str(int(ready)),
            str(int(math_latched)),
            str(int(energy_latched)),
            str(int(memory_latched)),
            str(int(valid)),
        ]
        print(",".join(values))
        seq += 1
        next_log_ns += LOG_PERIOD_NS
        finished_ns = time.monotonic_ns()
        if next_log_ns <= finished_ns:
            missed = (finished_ns - next_log_ns) // LOG_PERIOD_NS + 1
            emit("log_deadline_missed", session_index=session_index, missed_slots=missed)
            next_log_ns += missed * LOG_PERIOD_NS


def main():
    emit("logger_start", configuration=CONFIG)
    i2c = None
    session_index = 0
    stage = "i2c_initialization"
    while True:
        try:
            if i2c is None:
                stage = "i2c_initialization"
                try:
                    i2c = board.STEMMA_I2C()
                except RuntimeError as exc:
                    if "No pull up found on SDA or SCL" not in str(exc):
                        raise
                    emit(
                        "sensor_wait",
                        stage=stage,
                        error=str(exc),
                        retry_seconds=RETRY_SECONDS,
                        note="Connect the INA228 STEMMA QT cable, then wait for retry.",
                    )
                    time.sleep(RETRY_SECONDS)
                    continue
                # Retain this singleton after successful construction. Do not
                # deinitialize it and then request the same cached object again.

            stage = "address_scan"
            addresses = scan_addresses(i2c)
            if ADDRESS not in addresses:
                emit(
                    "sensor_wait",
                    expected_address="0x40",
                    detected_addresses=["0x{:02x}".format(a) for a in addresses],
                    retry_seconds=RETRY_SECONDS,
                )
                time.sleep(RETRY_SECONDS)
                continue

            stage = "sensor_configuration"
            sensor = configure(i2c)
            session_index += 1
            stage = "session_sampling"
            run_session(sensor, session_index)
        except OSError as exc:
            emit(
                "io_error",
                session_index=session_index,
                stage=stage,
                error=str(exc),
                retry_seconds=RETRY_SECONDS,
                note="No CSV row fabricated. Recovery starts a new announced energy session.",
            )
            time.sleep(RETRY_SECONDS)
        # KeyboardInterrupt and unexpected RuntimeError intentionally propagate.


main()
