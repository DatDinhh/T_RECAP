#!/usr/bin/env python3
"""Dependency-free model checks for the v70 delayed-x history contract.

This is architectural/model evidence, not an HDL simulation. The native
SystemVerilog regression remains authoritative for RTL behavior.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field


L = 256
H = 128
G = 128
D = L + G
DEPTH = 1024
MASK64 = (1 << 64) - 1


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def x_value(index: int) -> int:
    return ((index * 37 + 11) % 3001) - 1500


def y_value(index: int) -> int:
    return ((index * 19 + 7) % 2801) - 1400


@dataclass
class DelayHistory:
    depth: int = DEPTH
    delay: int = D
    history: deque[tuple[int, int]] = field(default_factory=deque)
    next_x: int = 0
    next_y: int = 0
    next_retire: int = 0
    metric_count: int = 0
    sum_abs_lo: int = 0
    sum_sq_lo: int = 0
    max_abs: int = 0
    metric_overflow: bool = False
    fail_stop: bool = False

    @property
    def busy(self) -> bool:
        return bool(self.history) or self.fail_stop

    @property
    def x_ready(self) -> bool:
        return not self.fail_stop and len(self.history) < self.depth

    def push_x(self, index: int, sample: int) -> bool:
        if self.fail_stop:
            return False
        if index != self.next_x or self.next_x == MASK64:
            self.fail_stop = True
            return False
        if len(self.history) == self.depth:
            return False
        self.history.append((index, sample))
        self.next_x += 1
        return True

    def take_y(self, index: int, sample: int) -> bool:
        if self.fail_stop:
            return False
        if index != self.next_y or self.next_y == MASK64:
            self.fail_stop = True
            return False

        delayed = 0
        if index >= self.delay:
            xref = index - self.delay
            if not self.history:
                if xref < self.next_x:
                    self.fail_stop = True
                return False
            head_index, delayed = self.history[0]
            if head_index != xref or self.next_retire != xref:
                self.fail_stop = True
                return False
            self.history.popleft()
            self.next_retire += 1

        error = delayed - sample
        absolute = abs(error)
        square = absolute * absolute
        abs_extended = self.sum_abs_lo + absolute
        sq_extended = self.sum_sq_lo + square
        self.sum_abs_lo = abs_extended & MASK64
        self.sum_sq_lo = sq_extended & MASK64
        self.metric_overflow |= abs_extended > MASK64 or sq_extended > MASK64
        self.max_abs = max(self.max_abs, absolute)
        self.metric_count += 1
        self.next_y += 1
        return True

    def clear_sticky(self) -> None:
        # Generic sticky clear cannot make truncated metrics or a lost alignment
        # trustworthy. These conditions deliberately remain asserted.
        pass

    def clear_metrics(self) -> None:
        self.metric_count = 0
        self.sum_abs_lo = 0
        self.sum_sq_lo = 0
        self.max_abs = 0
        self.metric_overflow = False

    def clear(self) -> None:
        self.history.clear()
        self.next_x = 0
        self.next_y = 0
        self.next_retire = 0
        self.metric_count = 0
        self.sum_abs_lo = 0
        self.sum_sq_lo = 0
        self.max_abs = 0
        self.metric_overflow = False
        self.fail_stop = False

    def check_invariant(self) -> None:
        consumed = max(self.next_y - self.delay, 0)
        require(
            self.next_retire == consumed,
            f"retire mismatch: got {self.next_retire}, expected {consumed}",
        )
        require(
            len(self.history) == self.next_x - self.next_retire,
            "occupancy does not equal accepted-x minus retired-x",
        )
        require(0 <= len(self.history) <= self.depth, "occupancy outside depth")


def demonstrate_legacy_alias() -> None:
    slots: dict[int, tuple[int, int]] = {}
    slots[0 % D] = (0, -2048)
    slots[D % D] = (D, 123)
    tag, sample = slots[0]
    require(tag == D and sample == 123, "legacy modulo-D alias was not reproduced")
    require((tag, sample) != (0, -2048), "legacy implementation unexpectedly preserved x[0]")


def check_startup_and_extremes() -> None:
    model = DelayHistory()
    for index in range(D):
        require(model.take_y(index, 0), f"startup y[{index}] was rejected")
    require(not model.take_y(D, 2047), "y[D] accepted before x[0]")
    require(not model.fail_stop, "normal producer lag raised a hard fault")
    require(model.push_x(0, -2048), "x[0] was rejected")
    require(model.take_y(D, 2047), "y[D] was not accepted after x[0]")
    require(model.sum_abs_lo == 4095, "extreme sum_abs mismatch")
    require(model.sum_sq_lo == 16_769_025, "extreme sum_sq mismatch")
    require(model.max_abs == 4095, "extreme max_abs mismatch")
    require(model.metric_count == D + 1, "extreme metric count mismatch")
    require(not model.history, "x[0] was not retired")
    model.check_invariant()


def drive_stream(model: DelayHistory, x_samples: int) -> tuple[int, int, int]:
    y_samples = x_samples + D
    next_x = 0
    next_y = 0
    expected_abs = 0
    expected_sq = 0
    expected_max = 0
    saw_full = False
    saw_full_stall = False

    # Model a long output stall by filling history before allowing y to move.
    while next_x < min(x_samples, model.depth):
        require(model.push_x(next_x, x_value(next_x)), "history fill rejected legal x")
        next_x += 1
    require(len(model.history) == model.depth, "history did not become full")
    saw_full = True
    require(not model.push_x(next_x, x_value(next_x)), "full history accepted an overwrite")
    saw_full_stall = True

    while next_y < y_samples:
        accepted = model.take_y(next_y, y_value(next_y))
        if accepted:
            delayed = 0 if next_y < D else x_value(next_y - D)
            error = delayed - y_value(next_y)
            absolute = abs(error)
            expected_abs = (expected_abs + absolute) & MASK64
            expected_sq = (expected_sq + absolute * absolute) & MASK64
            expected_max = max(expected_max, absolute)
            next_y += 1

        # No same-cycle credit is assumed at full. Push only after the prior
        # retirement made storage visible as non-full.
        if next_x < x_samples and model.x_ready:
            require(model.push_x(next_x, x_value(next_x)), "legal wrapped x was rejected")
            next_x += 1

        require(
            accepted or next_x < x_samples,
            "stream deadlocked without a future x sample",
        )
        model.check_invariant()

    require(next_x == x_samples, "not all x samples were accepted")
    require(model.metric_count == y_samples, "not all y samples were measured")
    require(not model.history, "final history was not empty")
    require(model.sum_abs_lo == expected_abs, "nonzero sum_abs mismatch")
    require(model.sum_sq_lo == expected_sq, "nonzero sum_sq mismatch")
    require(model.max_abs == expected_max, "nonzero max_abs mismatch")
    require(not model.metric_overflow, "unexpected metric overflow")
    require(not model.fail_stop, "legal stream entered fail-stop")
    require(saw_full and saw_full_stall, "full/backpressure coverage was not reached")
    return expected_abs, expected_sq, expected_max


def check_wrap_full_and_restart() -> None:
    model = DelayHistory()
    drive_stream(model, 2304)
    require(model.next_x > 2 * model.depth, "test did not cross two write-pointer wraps")
    model.clear()
    require(not model.busy and not model.history, "clear did not empty history")
    require(model.next_x == 0 and model.next_y == 0, "clear did not reset indices")
    drive_stream(model, 1152)
    require(model.metric_count == 1536, "Revision-J C0 metric count mismatch")


def check_fail_stop_and_metric_wrap() -> None:
    model = DelayHistory()
    require(not model.push_x(1, 7), "bad initial x index was accepted")
    require(model.fail_stop and model.busy, "bad index did not fail-stop")
    model.clear_sticky()
    require(model.fail_stop and model.busy, "sticky clear hid fail-stop")
    model.clear()
    require(model.push_x(0, 7), "clear did not recover index zero")

    metric = DelayHistory()
    metric.sum_abs_lo = MASK64 - 2
    metric.sum_sq_lo = MASK64 - 10
    metric.history.append((0, 5))
    metric.next_x = 1
    require(metric.take_y(0, 0), "startup metric sample failed")
    # y[0] uses zero extension, so inject a direct legal addend through y=-5.
    require(metric.take_y(1, -5), "metric overflow sample failed")
    require(metric.sum_abs_lo == 2, "sum_abs low word did not wrap")
    require(metric.metric_overflow, "metric overflow was not latched")
    metric.clear_sticky()
    require(metric.metric_overflow, "sticky clear erased truncated metric status")
    metric.clear_metrics()
    require(
        metric.sum_abs_lo == 0
        and metric.sum_sq_lo == 0
        and not metric.metric_overflow,
        "metric clear did not start a trustworthy metric epoch",
    )


def main() -> int:
    demonstrate_legacy_alias()
    check_startup_and_extremes()
    check_wrap_full_and_restart()
    check_fail_stop_and_metric_wrap()
    print(
        "C0_DELAY_HISTORY_MODEL_PASS "
        "depth=1024 D=384 wraps_gt=2 stress_x=2304 finite_x=1152 finite_y=1536"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
