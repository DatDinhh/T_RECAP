#!/usr/bin/env python3
"""Dependency-free Step-17 DE1-SoC LTC2308 architecture model.

The model independently checks the frozen SPI timing budget, all eight channel
commands, previous-conversion pipeline/priming, straight-binary sample format,
ADC_DOUT synchronizer latency, exact 100-kS/s cadence, fail-closed parameter
handling, source-adapter buffering/counters, source-mux isolation, telemetry
sample-rate selection, wrapper/drop-counter saturation, and sticky diagnostics.

It is an executable architecture oracle, not native RTL execution, Quartus or
TimeQuest evidence, post-fit I/O timing, analog characterization, live ADC
evidence, or hardware signoff.
"""

from __future__ import annotations

from dataclasses import dataclass


FABRIC_CLOCK_HZ = 50_000_000
FABRIC_PERIOD_NS = 20
ADC_SAMPLE_RATE_HZ = 100_000
NON_ADC_SAMPLE_RATE_HZ = 48_000
SCLK_HALF_DIV = 10
SCLK_HZ = 2_500_000
ADC_BITS = 12
COMMAND_BITS = 6
DOUT_SYNC_STAGES = 2
CONVST_PULSE_CYCLES = 2
CONVERSION_WAIT_CYCLES = 80
ACQUISITION_GUARD_CYCLES = 12
REENTRY_RECOVERY_CYCLES = (
    CONVST_PULSE_CYCLES + CONVERSION_WAIT_CYCLES + SCLK_HALF_DIV
)
DROP_COUNT_W = 32
UINT64_MAX = (1 << 64) - 1
DROP_COUNT_MAX = (1 << DROP_COUNT_W) - 1

CHANNEL_COMMANDS = (0x22, 0x32, 0x26, 0x36, 0x2A, 0x3A, 0x2E, 0x3E)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def sat_inc64(value: int) -> int:
    require(0 <= value <= UINT64_MAX, "counter escaped unsigned 64-bit range")
    return value if value == UINT64_MAX else value + 1


def wrap_inc64(value: int) -> int:
    require(0 <= value <= UINT64_MAX, "counter escaped unsigned 64-bit range")
    return (value + 1) & UINT64_MAX


def sat_inc_width(value: int, width: int) -> int:
    require(width > 0, "counter width must be positive")
    maximum = (1 << width) - 1
    require(0 <= value <= maximum, "counter escaped declared width")
    return value if value == maximum else value + 1


def ltc2308_command(channel: int) -> int:
    """Return {S/D,O/S,S1,S0,UNI,SLP} for single-ended/unipolar/awake."""

    require(0 <= channel < 8, "LTC2308 channel must be 0..7")
    return (
        (1 << 5)
        | ((channel & 0b001) << 4)
        | ((channel & 0b100) << 1)
        | ((channel & 0b010) << 1)
        | (1 << 1)
    )


def command_supported(command: int) -> bool:
    """Freeze single-ended, unipolar, awake commands only."""

    return 0 <= command < (1 << COMMAND_BITS) and (command & 0b100011) == 0b100010


def din_frame(command: int) -> tuple[int, ...]:
    """Six command bits followed by zero through the twelve-clock result frame."""

    require(command_supported(command), "unsupported LTC2308 input command")
    return bits_msb_first(command, COMMAND_BITS) + (0,) * (ADC_BITS - COMMAND_BITS)


def bits_msb_first(value: int, width: int) -> tuple[int, ...]:
    require(width > 0 and 0 <= value < (1 << width), "value does not fit bit width")
    return tuple((value >> shift) & 1 for shift in range(width - 1, -1, -1))


def decode_msb_first(bits: tuple[int, ...]) -> int:
    value = 0
    for bit in bits:
        require(bit in (0, 1), "serial symbol is not binary")
        value = (value << 1) | bit
    return value


def protocol_supported(
    *,
    clock_hz: int = FABRIC_CLOCK_HZ,
    sample_rate_hz: int = ADC_SAMPLE_RATE_HZ,
    sclk_half_div: int = SCLK_HALF_DIV,
    adc_bits: int = ADC_BITS,
    command_bits: int = COMMAND_BITS,
    dout_sync_stages: int = DOUT_SYNC_STAGES,
    convst_cycles: int = CONVST_PULSE_CYCLES,
    conversion_wait_cycles: int = CONVERSION_WAIT_CYCLES,
    acquisition_guard_cycles: int = ACQUISITION_GUARD_CYCLES,
    default_command: int = CHANNEL_COMMANDS[0],
) -> bool:
    if min(clock_hz, sample_rate_hz, sclk_half_div, convst_cycles, conversion_wait_cycles, acquisition_guard_cycles) <= 0:
        return False
    if adc_bits != 12 or command_bits != 6 or dout_sync_stages < 2:
        return False
    if not command_supported(default_command):
        return False
    if sclk_half_div < dout_sync_stages + 1 or sample_rate_hz >= clock_hz:
        return False

    convst_high_scaled = convst_cycles * 1_000_000_000
    if not clock_hz * 20 <= convst_high_scaled <= clock_hz * 40:
        return False
    first_sclk_cycles = convst_cycles + conversion_wait_cycles + sclk_half_div
    if first_sclk_cycles * 1_000_000_000 < clock_hz * 1_600:
        return False
    if clock_hz > sclk_half_div * 80_000_000:
        return False
    acquisition_from_seventh = (((adc_bits - 7) * 2) + 1) * sclk_half_div + acquisition_guard_cycles
    if acquisition_from_seventh * 1_000_000_000 < clock_hz * 240:
        return False
    transaction_cycles = (
        convst_cycles
        + conversion_wait_cycles
        + 2 * adc_bits * sclk_half_div
        + acquisition_guard_cycles
    )
    return transaction_cycles < clock_hz // sample_rate_hz


@dataclass
class ProtocolResult:
    published: bool
    raw_sample: int | None
    shifted_command: int | None
    pins_idle: bool


@dataclass
class AdcProtocolModel:
    supported: bool = True
    enabled: bool = False
    busy: bool = False
    configured_command: int | None = None
    sample_count: int = 0
    request_overrun_sticky: bool = False
    protocol_error_sticky: bool = False
    reentry_recovery_remaining: int = 0
    reentry_ready: bool = False

    def set_enabled(self, enabled: bool) -> None:
        entering = enabled and not self.enabled
        self.enabled = enabled
        if not enabled:
            self.busy = False
            self.configured_command = None
            self.reentry_recovery_remaining = 0
            self.reentry_ready = False
        elif entering:
            self.reentry_recovery_remaining = REENTRY_RECOVERY_CYCLES
            self.reentry_ready = False

    def elapse_reentry_recovery(self, cycles: int) -> None:
        require(cycles >= 0, "negative recovery interval")
        if not self.enabled or self.reentry_ready:
            return
        self.reentry_recovery_remaining = max(
            0, self.reentry_recovery_remaining - cycles
        )
        self.reentry_ready = self.reentry_recovery_remaining == 0

    def request_while_busy(self) -> None:
        if self.enabled and self.supported and self.busy:
            self.request_overrun_sticky = True

    def transact(self, requested_command: int, previous_result: int) -> ProtocolResult:
        require(0 <= requested_command < (1 << COMMAND_BITS), "command width mismatch")
        require(0 <= previous_result < (1 << ADC_BITS), "sample width mismatch")
        if not self.supported:
            if self.enabled:
                self.protocol_error_sticky = True
            return ProtocolResult(False, None, None, True)
        if not self.enabled:
            return ProtocolResult(False, None, None, True)
        command_ok = command_supported(requested_command)
        if not command_ok:
            # Command classification is independent of recovery/busy rejection: one attempt may
            # legitimately set both the protocol and overrun sticky diagnostics.
            self.protocol_error_sticky = True
        if not self.reentry_ready:
            self.request_overrun_sticky = True
            return ProtocolResult(False, None, None, True)
        if self.busy:
            self.request_overrun_sticky = True
            return ProtocolResult(False, None, None, False)
        if not command_ok:
            return ProtocolResult(False, None, None, True)

        self.busy = True
        eligible = self.configured_command == requested_command
        shifted = requested_command
        self.configured_command = requested_command
        self.busy = False
        if not eligible:
            return ProtocolResult(False, None, shifted, True)
        self.sample_count = sat_inc64(self.sample_count)
        return ProtocolResult(True, previous_result, shifted, True)

    def abort(self) -> None:
        self.busy = False
        self.configured_command = None
        self.reentry_recovery_remaining = REENTRY_RECOVERY_CYCLES
        self.reentry_ready = False

    def illegal_state_fault(self) -> None:
        """Model the RTL default-state abort, including mandatory recovery re-arm."""

        require(self.enabled and self.supported, "illegal-state fault requires an active wrapper")
        self.busy = False
        self.configured_command = None
        self.reentry_recovery_remaining = REENTRY_RECOVERY_CYCLES
        self.reentry_ready = False
        self.protocol_error_sticky = True

    def clear_sticky(self) -> None:
        self.request_overrun_sticky = False
        self.protocol_error_sticky = False


@dataclass
class AdapterModel:
    pending: int | None = None
    dropped_count: int = 0
    overflow_sticky: bool = False
    samples_seen: int = 0
    samples_admitted: int = 0
    samples_accepted: int = 0

    def submit(self, raw: int, *, enabled: bool, core_ready: bool) -> int | None:
        require(0 <= raw < (1 << ADC_BITS), "adapter input width mismatch")
        self.samples_seen = wrap_inc64(self.samples_seen)
        emitted = None
        if self.pending is not None and core_ready:
            emitted = self.pending
            self.pending = None
            self.samples_accepted = wrap_inc64(self.samples_accepted)
        if not enabled or self.pending is not None:
            self.dropped_count = sat_inc_width(self.dropped_count, DROP_COUNT_W)
            self.overflow_sticky = self.overflow_sticky or enabled
            return emitted
        self.pending = raw - (1 << (ADC_BITS - 1))
        self.samples_admitted = wrap_inc64(self.samples_admitted)
        return emitted

    def tick(self, *, core_ready: bool) -> int | None:
        if self.pending is None or not core_ready:
            return None
        value = self.pending
        self.pending = None
        self.samples_accepted = wrap_inc64(self.samples_accepted)
        return value


def synchronize_dout_bit(bit: int, *, stages: int, stable_cycles: int) -> int:
    require(bit in (0, 1), "DOUT bit is not binary")
    require(stages >= 2, "DOUT synchronizer must contain at least two stages")
    chain = [1 - bit] * stages
    for _ in range(stable_cycles):
        chain = [bit] + chain[:-1]
    return chain[-1]


def mux_select(mode: str, values: dict[str, int | None]) -> tuple[int | None, dict[str, bool]]:
    require(mode in values, "unknown source mode")
    ready = {name: name == mode for name in values}
    return values[mode], ready


def telemetry_rate(mode: str) -> int:
    return ADC_SAMPLE_RATE_HZ if mode == "adc_live" else NON_ADC_SAMPLE_RATE_HZ


def check_timing() -> None:
    require(protocol_supported(), "frozen LTC2308 timing is unsupported")
    require(FABRIC_CLOCK_HZ // (2 * SCLK_HALF_DIV) == SCLK_HZ, "SCLK rate mismatch")
    require(CONVST_PULSE_CYCLES * FABRIC_PERIOD_NS == 40, "CONVST pulse mismatch")
    require(
        (CONVST_PULSE_CYCLES + CONVERSION_WAIT_CYCLES + SCLK_HALF_DIV)
        * FABRIC_PERIOD_NS
        == 1840,
        "CONVST-to-first-SCLK timing mismatch",
    )
    acquisition_cycles = (((ADC_BITS - 7) * 2) + 1) * SCLK_HALF_DIV + ACQUISITION_GUARD_CYCLES
    require(acquisition_cycles == 122, "seventh-rise acquisition cycle count mismatch")
    require(acquisition_cycles * FABRIC_PERIOD_NS == 2440, "acquisition time mismatch")
    transaction_cycles = (
        CONVST_PULSE_CYCLES
        + CONVERSION_WAIT_CYCLES
        + 2 * ADC_BITS * SCLK_HALF_DIV
        + ACQUISITION_GUARD_CYCLES
    )
    require(transaction_cycles == 334, "transaction cycle count mismatch")
    require(transaction_cycles * FABRIC_PERIOD_NS == 6680, "transaction time mismatch")
    require(REENTRY_RECOVERY_CYCLES == 92, "re-entry recovery interval mismatch")
    require(
        REENTRY_RECOVERY_CYCLES * FABRIC_PERIOD_NS == 1840,
        "re-entry recovery time mismatch",
    )
    require(FABRIC_CLOCK_HZ // ADC_SAMPLE_RATE_HZ == 500, "sample cadence mismatch")
    require(transaction_cycles < 500, "transaction does not fit 100-kS/s cadence")

    negative_cases = (
        {"dout_sync_stages": 1},
        {"sclk_half_div": 2},
        {"convst_cycles": 0},
        {"convst_cycles": 3},
        {"conversion_wait_cycles": 1},
        {"adc_bits": 11},
        {"command_bits": 5},
        {"default_command": 0x23},
        {"sample_rate_hz": 10_000_000},
    )
    for override in negative_cases:
        require(not protocol_supported(**override), f"bad configuration did not fail closed: {override}")


def check_commands_and_serial() -> None:
    for channel, expected in enumerate(CHANNEL_COMMANDS):
        command = ltc2308_command(channel)
        require(command == expected, f"channel {channel} command mismatch")
        bits = bits_msb_first(command, COMMAND_BITS)
        require(decode_msb_first(bits) == command, f"channel {channel} serial round trip failed")
        require(bits[0] == 1, "S/D is not single-ended")
        require(bits[4] == 1, "UNI is not unipolar")
        require(bits[5] == 0, "SLP is not awake")
        require(
            din_frame(command) == bits + (0,) * 6,
            f"channel {channel} DIN frame mismatch",
        )

    for raw in (0x000, 0x001, 0x5A5, 0x800, 0xFFE, 0xFFF):
        require(decode_msb_first(bits_msb_first(raw, ADC_BITS)) == raw, "result serial round trip failed")


def check_pipeline_and_faults() -> None:
    model = AdcProtocolModel(supported=True)
    model.set_enabled(True)
    ch0 = ltc2308_command(0)
    ch1 = ltc2308_command(1)

    early = model.transact(ch0, 0x000)
    require(not early.published and early.pins_idle, "re-entry recovery emitted traffic")
    require(model.request_overrun_sticky, "recovery request did not set sticky fault")
    model.clear_sticky()
    model.elapse_reentry_recovery(REENTRY_RECOVERY_CYCLES - 1)
    require(
        not model.transact(ch0, 0x001).published,
        "request one cycle before recovery completion was admitted",
    )
    model.clear_sticky()
    model.elapse_reentry_recovery(1)

    first = model.transact(ch0, 0x111)
    require(not first.published, "first old-configuration result was published")
    second = model.transact(ch0, 0x222)
    require(second.published and second.raw_sample == 0x222, "primed channel-0 result missing")
    changed = model.transact(ch1, 0x333)
    require(not changed.published, "old channel-0 result was mislabeled as channel 1")
    next_ch1 = model.transact(ch1, 0x444)
    require(next_ch1.published and next_ch1.raw_sample == 0x444, "primed channel-1 result missing")
    require(model.sample_count == 2, "published sample counter mismatch")

    model.abort()
    require(not model.transact(ch1, 0x555).published, "post-abort recovery admitted early")
    require(model.request_overrun_sticky, "post-abort recovery rejection was not sticky")
    model.clear_sticky()
    model.elapse_reentry_recovery(REENTRY_RECOVERY_CYCLES)
    require(not model.transact(ch1, 0x556).published, "post-abort result was not re-primed")
    require(model.transact(ch1, 0x666).published, "post-abort primed result missing")
    model.set_enabled(False)
    require(not model.transact(ch1, 0x777).published, "disabled ADC published a result")
    model.set_enabled(True)
    model.elapse_reentry_recovery(REENTRY_RECOVERY_CYCLES)
    model.busy = True
    model.request_while_busy()
    require(model.request_overrun_sticky, "busy request did not set overrun sticky")
    lifetime = model.sample_count
    model.clear_sticky()
    require(not model.request_overrun_sticky, "sticky clear failed")
    require(model.sample_count == lifetime, "sticky clear erased lifetime sample count")

    model.sample_count = UINT64_MAX - 1
    model.busy = False
    model.configured_command = ch1
    require(model.transact(ch1, 0x123).published, "counter saturation transaction failed")
    require(model.transact(ch1, 0x124).published, "saturated transaction failed")
    require(model.sample_count == UINT64_MAX, "sample count did not saturate")

    unsupported = AdcProtocolModel(supported=False, enabled=True)
    failed = unsupported.transact(ch0, 0xABC)
    require(not failed.published and failed.pins_idle, "unsupported config emitted traffic/sample")
    require(unsupported.protocol_error_sticky, "unsupported config did not set protocol fault")

    invalid_command = AdcProtocolModel(supported=True)
    invalid_command.set_enabled(True)
    invalid_command.elapse_reentry_recovery(REENTRY_RECOVERY_CYCLES)
    failed = invalid_command.transact(0x23, 0x111)
    require(not failed.published and failed.pins_idle, "sleep command emitted traffic/sample")
    require(invalid_command.protocol_error_sticky, "invalid command did not set protocol fault")

    invalid_during_recovery = AdcProtocolModel(supported=True)
    invalid_during_recovery.set_enabled(True)
    failed = invalid_during_recovery.transact(0x23, 0x112)
    require(not failed.published and failed.pins_idle, "recovery invalid command emitted traffic")
    require(
        invalid_during_recovery.request_overrun_sticky
        and invalid_during_recovery.protocol_error_sticky,
        "recovery invalid command did not set both overrun and protocol faults",
    )

    invalid_while_busy = AdcProtocolModel(supported=True)
    invalid_while_busy.set_enabled(True)
    invalid_while_busy.elapse_reentry_recovery(REENTRY_RECOVERY_CYCLES)
    invalid_while_busy.busy = True
    failed = invalid_while_busy.transact(0x23, 0x113)
    require(not failed.published, "busy invalid command published a sample")
    require(
        invalid_while_busy.request_overrun_sticky
        and invalid_while_busy.protocol_error_sticky,
        "busy invalid command did not set both overrun and protocol faults",
    )

    illegal_state = AdcProtocolModel(supported=True)
    illegal_state.set_enabled(True)
    illegal_state.elapse_reentry_recovery(REENTRY_RECOVERY_CYCLES)
    illegal_state.configured_command = ch0
    illegal_state.busy = True
    illegal_state.illegal_state_fault()
    require(illegal_state.protocol_error_sticky, "illegal state did not set protocol fault")
    require(
        not illegal_state.reentry_ready and illegal_state.configured_command is None,
        "illegal state did not invalidate configuration and re-arm recovery",
    )
    failed = illegal_state.transact(ch0, 0x114)
    require(not failed.published, "illegal-state recovery admitted a request early")
    require(illegal_state.request_overrun_sticky, "illegal-state recovery rejection was not sticky")


def check_cdc() -> None:
    require(SCLK_HALF_DIV >= DOUT_SYNC_STAGES + 1, "DOUT synchronizer has no half-cycle margin")
    pattern = bits_msb_first(0xA5B, ADC_BITS)
    captured = tuple(
        synchronize_dout_bit(bit, stages=DOUT_SYNC_STAGES, stable_cycles=SCLK_HALF_DIV)
        for bit in pattern
    )
    require(captured == pattern, "synchronized DOUT pattern changed")
    require(decode_msb_first(captured) == 0xA5B, "synchronized sample assembly mismatch")


def check_sample_format() -> int:
    previous = -2048
    cases = 0
    for raw in range(1 << ADC_BITS):
        centered = raw - 2048
        require(-2048 <= centered <= 2047, "centered sample escaped signed 12-bit range")
        require(centered >= previous, "straight-binary centering is not monotonic")
        require((centered + 2048) == raw, "centering is not reversible")
        previous = centered
        cases += 1
    require(0 - 2048 == -2048, "zero-code endpoint mismatch")
    require(2048 - 2048 == 0, "midscale zero mismatch")
    require(4095 - 2048 == 2047, "full-scale endpoint mismatch")
    return cases


def check_adapter_mux_and_metadata() -> None:
    adapter = AdapterModel()
    require(adapter.submit(2048, enabled=True, core_ready=False) is None, "first adapter submit emitted early")
    require(adapter.pending == 0, "midscale did not center to zero")
    require(adapter.submit(4095, enabled=True, core_ready=False) is None, "full adapter did not drop")
    require(adapter.dropped_count == 1 and adapter.overflow_sticky, "adapter drop fault mismatch")
    require(adapter.tick(core_ready=True) == 0, "adapter pending sample mismatch")
    require(adapter.submit(0, enabled=False, core_ready=True) is None, "disabled adapter emitted")
    adapter.dropped_count = DROP_COUNT_MAX - 1
    adapter.submit(1, enabled=False, core_ready=True)
    adapter.submit(1, enabled=False, core_ready=True)
    require(adapter.dropped_count == DROP_COUNT_MAX, "32-bit adapter drop count did not saturate")

    values = {"bram_replay": 11, "adc_live": 22, "audio_wrapper": 33, "diagnostic_source": 44}
    adc_value, ready = mux_select("adc_live", values)
    require(adc_value == 22, "ADC mux value mismatch")
    require(ready == {"bram_replay": False, "adc_live": True, "audio_wrapper": False, "diagnostic_source": False}, "ADC mux ready isolation mismatch")
    bram_value, ready = mux_select("bram_replay", values)
    require(bram_value == 11 and ready["bram_replay"] and not ready["adc_live"], "ADC path blocked BRAM replay")

    require(telemetry_rate("adc_live") == 100_000, "ADC telemetry rate mismatch")
    for mode in ("bram_replay", "audio_wrapper", "diagnostic_source"):
        require(telemetry_rate(mode) == 48_000, f"non-ADC telemetry rate mismatch for {mode}")


def main() -> int:
    check_timing()
    check_commands_and_serial()
    check_pipeline_and_faults()
    check_cdc()
    sample_cases = check_sample_format()
    check_adapter_mux_and_metadata()
    print(
        "check_step17_adc_model: PASS "
        f"channels={len(CHANNEL_COMMANDS)} sample_format_cases={sample_cases} "
        f"rate={ADC_SAMPLE_RATE_HZ}Sps sclk={SCLK_HZ}Hz sync_stages={DOUT_SYNC_STAGES} "
        f"reentry_recovery_cycles={REENTRY_RECOVERY_CYCLES} drop_counter_bits={DROP_COUNT_W}"
    )
    print(
        "check_step17_adc_model: architecture model only; no native RTL simulation, "
        "Quartus/TimeQuest, post-fit timing, analog, live ADC, or hardware evidence"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
