#!/usr/bin/env python3
"""Dependency-free Step-16 DE1-SoC LINE-IN architecture model.

The model independently checks the frozen WM8731 control words and byte
encoding, bounded ACK retry behavior, audio-clock ratios, 16-bit I2S framing,
RX/TX FIFO fault semantics, stale-source-epoch prevention, saturating 64-bit
counters, and exhaustive signed 16-bit to signed 12-bit audio scaling.

It is an executable architecture oracle, not RTL execution, codec simulation,
PLL timing evidence, or board evidence.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from fractions import Fraction
from typing import Callable, Iterable


REF_CLK_HZ = 50_000_000
AUDIO_MCLK_HZ = 12_288_000
SAMPLE_RATE_HZ = 48_000
BCLK_HZ = 3_072_000
I2C_ADDRESS = 0x1A
I2C_BUS_HZ = 100_000
AUDIO_WIDTH = 16
CORE_WIDTH = 12
I2S_SLOT_BITS = 32
MAX_RETRIES = 3
UINT64_MAX = (1 << 64) - 1

REGISTER_SEQUENCE: tuple[tuple[int, int], ...] = (
    (15, 0x000),
    (9, 0x000),
    (0, 0x017),
    (1, 0x017),
    (2, 0x079),
    (3, 0x079),
    (4, 0x012),
    (5, 0x000),
    (6, 0x002),
    (7, 0x042),
    (8, 0x000),
    (9, 0x001),
)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def encode_control_word(register: int, value: int) -> int:
    require(0 <= register < 128, "WM8731 register index is not seven-bit")
    require(0 <= value < 512, "WM8731 register value is not nine-bit")
    return (register << 9) | value


def encode_i2c_transaction(register: int, value: int) -> tuple[int, int, int]:
    word = encode_control_word(register, value)
    return ((I2C_ADDRESS << 1) | 0, (word >> 8) & 0xFF, word & 0xFF)


@dataclass
class I2CResult:
    done: bool = False
    error: bool = False
    ack_error_count: int = 0
    retry_count: int = 0
    register_write_count: int = 0
    transactions: list[tuple[int, int, int]] = field(default_factory=list)


AckFunction = Callable[[int, int, int, int], bool]


def run_i2c_init(ack: AckFunction) -> I2CResult:
    """Run the frozen per-register retry policy against an ACK oracle.

    ``ack(register_index, attempt_index, byte_index, byte_value)`` returns true
    only when the corresponding address/control byte is acknowledged.
    """

    result = I2CResult()
    for register_index, (register, value) in enumerate(REGISTER_SEQUENCE):
        transaction = encode_i2c_transaction(register, value)
        accepted = False
        for attempt in range(MAX_RETRIES + 1):
            result.transactions.append(transaction)
            all_bytes_acked = True
            for byte_index, byte_value in enumerate(transaction):
                if not ack(register_index, attempt, byte_index, byte_value):
                    result.ack_error_count += 1
                    all_bytes_acked = False
                    break
            if all_bytes_acked:
                result.register_write_count += 1
                accepted = True
                break
            if attempt < MAX_RETRIES:
                result.retry_count += 1
        if not accepted:
            result.error = True
            return result
    result.done = True
    return result


def word_bits(value: int, width: int) -> tuple[int, ...]:
    encoded = value & ((1 << width) - 1)
    return tuple((encoded >> shift) & 1 for shift in range(width - 1, -1, -1))


def encode_i2s_slot(value: int) -> tuple[int, ...]:
    # One bit-clock delay follows the LRCK transition. The remaining slot bits
    # are don't-care/zero after the frozen 16-bit word.
    padding = I2S_SLOT_BITS - 1 - AUDIO_WIDTH
    require(padding >= 0, "I2S slot is narrower than delay plus audio word")
    return (0,) + word_bits(value, AUDIO_WIDTH) + (0,) * padding


def decode_i2s_slot(bits: Iterable[int]) -> int:
    slot = tuple(bits)
    require(len(slot) == I2S_SLOT_BITS, "I2S slot length mismatch")
    payload = slot[1 : 1 + AUDIO_WIDTH]
    encoded = 0
    for bit in payload:
        require(bit in (0, 1), "I2S bit is not binary")
        encoded = (encoded << 1) | bit
    sign_bit = 1 << (AUDIO_WIDTH - 1)
    return encoded - (1 << AUDIO_WIDTH) if encoded & sign_bit else encoded


def round_shift_ties_away_from_zero(value: int, shift: int) -> int:
    require(shift >= 0, "negative right shift")
    if shift == 0:
        return value
    rounded_magnitude = (abs(value) + (1 << (shift - 1))) >> shift
    return -rounded_magnitude if value < 0 else rounded_magnitude


def saturate_signed(value: int, width: int) -> int:
    minimum = -(1 << (width - 1))
    maximum = (1 << (width - 1)) - 1
    return min(max(value, minimum), maximum)


def audio16_to_core12(value: int) -> tuple[int, bool, bool]:
    require(-(1 << 15) <= value < (1 << 15), "input is outside signed 16-bit range")
    rounded = round_shift_ties_away_from_zero(value, AUDIO_WIDTH - CORE_WIDTH)
    minimum = -(1 << (CORE_WIDTH - 1))
    maximum = (1 << (CORE_WIDTH - 1)) - 1
    return saturate_signed(rounded, CORE_WIDTH), rounded > maximum, rounded < minimum


@dataclass
class SaturatingCounter64:
    value: int = 0

    def increment(self) -> None:
        if self.value < UINT64_MAX:
            self.value += 1

    def clear(self) -> None:
        self.value = 0


@dataclass
class AudioCdcModel:
    rx_depth: int = 4
    tx_depth: int = 4
    rx_fifo: deque[tuple[int, int]] = field(default_factory=deque)
    tx_fifo: deque[tuple[int, int]] = field(default_factory=deque)
    rx_overflow: SaturatingCounter64 = field(default_factory=SaturatingCounter64)
    tx_overflow: SaturatingCounter64 = field(default_factory=SaturatingCounter64)
    tx_underflow: SaturatingCounter64 = field(default_factory=SaturatingCounter64)
    tx_primed: bool = False

    def __post_init__(self) -> None:
        require(self.rx_depth >= 2, "RX FIFO depth must be at least two")
        require(self.tx_depth >= 2, "TX FIFO depth must be at least two")

    def receive_frame(self, frame: tuple[int, int], *, capture_enabled: bool) -> bool:
        if not capture_enabled:
            return False
        if len(self.rx_fifo) >= self.rx_depth:
            self.rx_overflow.increment()
            return False
        self.rx_fifo.append(frame)
        return True

    def fabric_rx_tick(self, *, capture_enabled: bool) -> tuple[int, int] | None:
        # The fabric side drains even while disabled. Disabled payloads are discarded,
        # preventing a frame from one source epoch from becoming the first frame of another.
        if not self.rx_fifo:
            return None
        frame = self.rx_fifo.popleft()
        return frame if capture_enabled else None

    def submit_lineout(self, frame: tuple[int, int], *, lineout_enabled: bool) -> bool:
        if not lineout_enabled:
            return False
        if len(self.tx_fifo) >= self.tx_depth:
            self.tx_overflow.increment()
            return False
        self.tx_fifo.append(frame)
        return True

    def dac_frame_boundary(self, *, lineout_enabled: bool) -> tuple[int, int]:
        if not lineout_enabled:
            self.tx_primed = False
            return (0, 0)
        if not self.tx_fifo:
            if self.tx_primed:
                self.tx_underflow.increment()
            return (0, 0)
        self.tx_primed = True
        return self.tx_fifo.popleft()

    def clear_counters(self) -> None:
        self.rx_overflow.clear()
        self.tx_overflow.clear()
        self.tx_underflow.clear()


def check_clock_contract() -> None:
    require(Fraction(AUDIO_MCLK_HZ, SAMPLE_RATE_HZ) == 256, "MCLK/Fs is not 256")
    require(Fraction(BCLK_HZ, SAMPLE_RATE_HZ) == 64, "BCLK/Fs is not 64")
    require(
        Fraction(AUDIO_MCLK_HZ, REF_CLK_HZ) == Fraction(768, 3125),
        "50 MHz to 12.288 MHz ratio drifted",
    )

    # Mirror the portable PLL wrapper's exact-average edge accumulator over one
    # complete rational denominator. There must be 1536 edges, or 768 MCLK cycles.
    phase = 0
    edges = 0
    edge_rate = 2 * AUDIO_MCLK_HZ
    for _ in range(3125):
        phase += edge_rate
        if phase >= REF_CLK_HZ:
            phase -= REF_CLK_HZ
            edges += 1
    require(edges == 1536, f"phase model produced {edges} edges instead of 1536")
    require(phase == 0, "phase model does not close after the rational period")


def check_codec_words_and_i2c() -> None:
    require(len(REGISTER_SEQUENCE) == 12, "codec register sequence length drifted")
    require(REGISTER_SEQUENCE[-1] == (9, 0x001), "codec ACTIVE write is not last")
    interface_value = dict(REGISTER_SEQUENCE)[7]
    sample_value = dict(REGISTER_SEQUENCE)[8]
    require(interface_value & 0b11 == 0b10, "codec interface is not I2S")
    require((interface_value >> 2) & 0b11 == 0, "codec word width is not 16-bit")
    require((interface_value >> 6) & 1 == 1, "codec is not serial-clock master")
    require(sample_value == 0, "codec 48 kHz normal-mode sampling register drifted")
    require(dict(REGISTER_SEQUENCE)[6] == 0x002, "codec microphone power-down policy drifted")
    require(encode_i2c_transaction(7, 0x042) == (0x34, 0x0E, 0x42), "I2S transaction encoding mismatch")
    require(encode_i2c_transaction(8, 0x000) == (0x34, 0x10, 0x00), "sampling transaction encoding mismatch")
    require(encode_i2c_transaction(9, 0x001) == (0x34, 0x12, 0x01), "ACTIVE transaction encoding mismatch")

    success = run_i2c_init(lambda _r, _a, _b, _v: True)
    require(success.done and not success.error, "all-ACK codec initialization did not finish")
    require(success.register_write_count == 12, "all-ACK write count mismatch")
    require(success.retry_count == 0 and success.ack_error_count == 0, "all-ACK counters changed")

    def transient_nack(register_index: int, attempt: int, byte_index: int, _value: int) -> bool:
        return not (register_index == 9 and attempt == 0 and byte_index == 1)

    retried = run_i2c_init(transient_nack)
    require(retried.done and not retried.error, "transient NACK did not recover")
    require(retried.retry_count == 1, "transient NACK retry count mismatch")
    require(retried.ack_error_count == 1, "transient NACK ACK-error count mismatch")
    require(retried.register_write_count == 12, "transient NACK lost a register write")

    failed = run_i2c_init(lambda register_index, _a, _b, _v: register_index != 4)
    require(not failed.done and failed.error, "persistent NACK did not fail closed")
    require(failed.retry_count == MAX_RETRIES, "persistent NACK retry bound mismatch")
    require(failed.ack_error_count == MAX_RETRIES + 1, "persistent NACK attempt count mismatch")
    require(failed.register_write_count == 4, "writes after persistent NACK were accepted")


def check_i2s() -> None:
    vectors = (-32768, -23131, -1, 0, 1, 23130, 32767)
    for value in vectors:
        slot = encode_i2s_slot(value)
        require(len(slot) == 32, "I2S slot is not 32 bits")
        require(slot[0] == 0, "I2S delay bit is not present")
        require(decode_i2s_slot(slot) == value, f"I2S round trip failed for {value}")
    require(
        encode_i2s_slot(-32768)[1:17] == word_bits(0x8000, 16),
        "I2S negative-full-scale bit order mismatch",
    )
    require(
        encode_i2s_slot(0x7FFF)[1:17] == word_bits(0x7FFF, 16),
        "I2S positive-full-scale bit order mismatch",
    )
    require(
        encode_i2s_slot(-0x5AA6)[1:17] == word_bits(0xA55A, 16),
        "I2S 0xA55A bit pattern mismatch",
    )
    require(
        encode_i2s_slot(0x5AA5)[1:17] == word_bits(0x5AA5, 16),
        "I2S 0x5AA5 bit pattern mismatch",
    )


def check_fifo_and_counters() -> None:
    model = AudioCdcModel(rx_depth=2, tx_depth=2)

    require(model.dac_frame_boundary(lineout_enabled=True) == (0, 0), "initial TX empty did not mute")
    require(model.tx_underflow.value == 0, "unprimed TX silence was counted as underflow")
    require(model.receive_frame((1, -1), capture_enabled=True), "RX first enqueue failed")
    require(model.receive_frame((2, -2), capture_enabled=True), "RX second enqueue failed")
    require(not model.receive_frame((3, -3), capture_enabled=True), "RX full enqueue succeeded")
    require(model.rx_overflow.value == 1, "RX overflow did not count exactly once")
    require(not model.receive_frame((4, -4), capture_enabled=False), "disabled RX was queued")
    require(model.rx_overflow.value == 1, "disabled RX changed overflow count")

    # Drain/discard the old source epoch, then prove the first new-epoch payload is new.
    require(model.fabric_rx_tick(capture_enabled=False) is None, "disabled RX leaked old frame")
    require(model.fabric_rx_tick(capture_enabled=False) is None, "disabled RX leaked old frame")
    new_frame = (100, -100)
    require(model.receive_frame(new_frame, capture_enabled=True), "new-epoch RX enqueue failed")
    require(model.fabric_rx_tick(capture_enabled=True) == new_frame, "stale RX frame crossed epoch")

    require(model.submit_lineout((10, 10), lineout_enabled=True), "TX first enqueue failed")
    require(model.submit_lineout((11, 11), lineout_enabled=True), "TX second enqueue failed")
    require(not model.submit_lineout((12, 12), lineout_enabled=True), "TX full enqueue succeeded")
    require(model.tx_overflow.value == 1, "TX overflow did not count exactly once")
    require(not model.submit_lineout((13, 13), lineout_enabled=False), "disabled TX was queued")
    require(model.tx_overflow.value == 1, "disabled TX changed overflow count")
    require(model.dac_frame_boundary(lineout_enabled=True) == (10, 10), "TX order mismatch")
    require(model.dac_frame_boundary(lineout_enabled=True) == (11, 11), "TX order mismatch")
    require(model.dac_frame_boundary(lineout_enabled=True) == (0, 0), "TX empty did not mute")
    require(model.tx_underflow.value == 1, "TX underflow did not count exactly once")
    require(model.dac_frame_boundary(lineout_enabled=False) == (0, 0), "disabled TX did not mute")
    require(model.tx_underflow.value == 1, "disabled TX changed underflow count")

    model.rx_overflow.value = UINT64_MAX - 1
    model.rx_overflow.increment()
    model.rx_overflow.increment()
    require(model.rx_overflow.value == UINT64_MAX, "64-bit counter did not saturate")
    model.clear_counters()
    require(
        (model.rx_overflow.value, model.tx_overflow.value, model.tx_underflow.value) == (0, 0, 0),
        "audio counter clear did not clear all three counters",
    )


def check_audio_scaling() -> int:
    cases = 0
    clipped_high = 0
    clipped_low = 0
    previous = -(1 << (CORE_WIDTH - 1))
    for value in range(-(1 << 15), 1 << 15):
        scaled, clip_hi, clip_lo = audio16_to_core12(value)
        require(-(1 << 11) <= scaled <= (1 << 11) - 1, "scaled sample escaped 12-bit range")
        require(scaled >= previous, "audio scale mapping is not monotonic")
        previous = scaled
        clipped_high += int(clip_hi)
        clipped_low += int(clip_lo)
        cases += 1
    require(cases == 65_536, "exhaustive audio scaling case count mismatch")
    require(clipped_high == 8, f"unexpected positive clipping population: {clipped_high}")
    require(clipped_low == 0, f"unexpected negative clipping population: {clipped_low}")
    require(audio16_to_core12(7)[0] == 0, "+7 rounding mismatch")
    require(audio16_to_core12(8)[0] == 1, "+8 tie-away rounding mismatch")
    require(audio16_to_core12(-7)[0] == 0, "-7 rounding mismatch")
    require(audio16_to_core12(-8)[0] == -1, "-8 tie-away rounding mismatch")
    require(audio16_to_core12(32759) == (2047, False, False), "positive boundary mismatch")
    require(audio16_to_core12(32760) == (2047, True, False), "positive clip boundary mismatch")
    require(audio16_to_core12(-32768) == (-2048, False, False), "negative full-scale mismatch")
    return cases


def main() -> int:
    check_clock_contract()
    check_codec_words_and_i2c()
    check_i2s()
    check_fifo_and_counters()
    scale_cases = check_audio_scaling()
    print(
        "check_step16_audio_model: PASS "
        f"(registers={len(REGISTER_SEQUENCE)}, scale_cases={scale_cases}, "
        "source/model-only; no RTL or hardware evidence)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
