#!/usr/bin/env python3
"""Dependency-free Step-12 DDR-ring ownership and boundary model.

This is an architecture model, not RTL execution.  It exhausts small aligned
rings so the directed SystemVerilog regression has an independent oracle for
WRAP/free-space arithmetic, pointer ownership, and deterministic re-arm.
"""

from __future__ import annotations

from dataclasses import dataclass


ALIGN = 64
GUARD = 64


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def aligned(value: int) -> bool:
    return value >= 0 and value % ALIGN == 0


def power_of_two(value: int) -> bool:
    return value > 0 and value & (value - 1) == 0


@dataclass(frozen=True)
class Schedule:
    legal: bool
    fits: bool
    needs_wrap: bool
    offset: int
    tail: int
    normal_bytes: int
    required_bytes: int
    free_bytes: int
    wrap_address: int
    normal_address: int


def schedule(*, base: int, ring_size: int, guard: int, wr: int, rd: int, length: int) -> Schedule:
    configured = (
        aligned(base)
        and power_of_two(ring_size)
        and aligned(ring_size)
        and aligned(guard)
        and ALIGN <= guard < ring_size
    )
    pointers_valid = configured and rd <= wr and wr - rd <= ring_size
    length_legal = pointers_valid and aligned(length) and ALIGN <= length <= ring_size
    offset = wr & (ring_size - 1) if configured else 0
    tail = ring_size - offset if configured else 0
    needs_wrap = length_legal and offset + length > ring_size
    required = (tail + length if needs_wrap else length) if length_legal else 0
    free = max(ring_size - (wr - rd) - guard, 0) if pointers_valid else 0
    fits = length_legal and free >= required
    return Schedule(
        legal=length_legal,
        fits=fits,
        needs_wrap=needs_wrap,
        offset=offset,
        tail=tail,
        normal_bytes=length,
        required_bytes=required,
        free_bytes=free,
        wrap_address=base + offset,
        normal_address=base if needs_wrap else base + offset,
    )


@dataclass
class RingState:
    base: int = 0
    size: int = 0
    guard: int = GUARD
    wr: int = 0
    rd: int = 0
    sequence: int = 0
    configured: bool = False
    rd_epoch_valid: bool = False
    telemetry_enable: bool = False
    writer_enable: bool = False
    busy: bool = False

    def hard_reset(self) -> None:
        self.base = 0
        self.size = 0
        self.wr = 0
        self.rd = 0
        self.sequence = 0
        self.configured = False
        self.rd_epoch_valid = False
        self.telemetry_enable = False
        self.writer_enable = False
        self.busy = False

    def soft_reset_transport(self) -> None:
        """Reset FPGA-owned transport state without writing HPS-owned Rd storage."""
        self.base = 0
        self.size = 0
        self.wr = 0
        self.sequence = 0
        self.configured = False
        self.rd_epoch_valid = False
        self.telemetry_enable = False
        self.writer_enable = False
        self.busy = False

    @property
    def effective_rd(self) -> int:
        """Expose a safe reset value until HPS establishes this config epoch."""
        return self.rd if self.configured and self.rd_epoch_valid else 0

    def write_config_shadow_allowed(self) -> bool:
        return not self.telemetry_enable and not self.writer_enable and not self.busy

    def commit_config(self, base: int, size: int) -> bool:
        legal = (
            self.write_config_shadow_allowed()
            and aligned(base)
            and power_of_two(size)
            and size >= 4 * ALIGN
            and aligned(size)
        )
        if not legal:
            return False
        self.base = base
        self.size = size
        self.wr = 0
        self.sequence = 0
        self.configured = True
        self.rd_epoch_valid = False
        return True

    def commit_rd(self, value: int) -> bool:
        legal = (
            self.configured
            and aligned(value)
            and (
                (not self.rd_epoch_valid and value == 0)
                or (
                    self.rd_epoch_valid
                    and self.rd <= value <= self.wr
                    and self.wr - value <= self.size
                )
            )
        )
        if legal:
            self.rd = value
            self.rd_epoch_valid = True
        return legal

    def enable(self) -> bool:
        legal = self.configured and self.rd_epoch_valid and self.rd <= self.wr
        if legal:
            self.writer_enable = True
            self.telemetry_enable = True
        return legal

    def current_schedule(self, length: int) -> Schedule:
        return schedule(
            base=self.base,
            ring_size=self.size,
            guard=self.guard,
            wr=self.wr,
            rd=self.effective_rd,
            length=length,
        )

    def commit_wrap(self, planned: Schedule, responses_ok: bool = True) -> bool:
        legal = (
            self.configured
            and self.rd_epoch_valid
            and planned.fits
            and planned.needs_wrap
            and planned.tail == self.size - (self.wr & (self.size - 1))
            and responses_ok
        )
        if legal:
            self.wr += planned.tail
        return legal

    def commit_normal(self, length: int, responses_ok: bool = True) -> bool:
        planned = self.current_schedule(length)
        legal = (
            self.configured
            and self.rd_epoch_valid
            and planned.fits
            and not planned.needs_wrap
            and responses_ok
        )
        if legal:
            self.wr += length
            self.sequence = (self.sequence + 1) & 0xFFFF_FFFF
        return legal


def exhaust_schedule_space() -> tuple[int, int, int, int]:
    cases = 0
    wrap_cases = 0
    exact_end_cases = 0
    no_space_cases = 0
    base = 0x1000_0000

    for ring_size in (256, 512, 1024):
        for wr in range(0, 4 * ring_size + 1, ALIGN):
            rd_min = max(0, wr - ring_size)
            for rd in range(rd_min, wr + 1, ALIGN):
                for length in range(ALIGN, ring_size + 1, ALIGN):
                    got = schedule(
                        base=base,
                        ring_size=ring_size,
                        guard=GUARD,
                        wr=wr,
                        rd=rd,
                        length=length,
                    )
                    cases += 1
                    offset = wr % ring_size
                    tail = ring_size - offset
                    crosses = offset + length > ring_size
                    expected_required = tail + length if crosses else length
                    expected_free = max(ring_size - (wr - rd) - GUARD, 0)

                    require(got.legal, "aligned exhaustive schedule unexpectedly illegal")
                    require(got.offset == offset, "offset mismatch")
                    require(got.tail == tail, "tail mismatch")
                    require(got.needs_wrap == crosses, "WRAP decision mismatch")
                    require(got.required_bytes == expected_required, "required-byte mismatch")
                    require(got.free_bytes == expected_free, "free-byte mismatch")
                    require(got.fits == (expected_free >= expected_required), "fit decision mismatch")

                    segments = (
                        ((offset, tail), (0, length)) if crosses else ((offset, length),)
                    )
                    require(sum(segment[1] for segment in segments) == expected_required,
                            "physical segment length mismatch")
                    for segment_offset, segment_length in segments:
                        require(0 <= segment_offset < ring_size, "segment offset outside ring")
                        require(segment_offset + segment_length <= ring_size,
                                "physical segment crosses ring end")

                    if crosses:
                        wrap_cases += 1
                        require(got.wrap_address == base + offset, "WRAP address mismatch")
                        require(got.normal_address == base, "post-WRAP normal address mismatch")
                    else:
                        require(got.normal_address == base + offset, "normal address mismatch")
                    if offset + length == ring_size:
                        exact_end_cases += 1
                        require(not got.needs_wrap, "exact-end record incorrectly requires WRAP")
                    if expected_free < expected_required:
                        no_space_cases += 1
                        require(not got.fits, "insufficient free space accepted")

    return cases, wrap_cases, exact_end_cases, no_space_cases


def exhaust_ownership_space() -> int:
    """Exhaust legal/illegal HPS Rd commits over small absolute-pointer states."""
    cases = 0
    base = 0x1000_0000

    for ring_size in (256, 512, 1024):
        for wr in range(0, 2 * ring_size + 1, ALIGN):
            rd_min = max(0, wr - ring_size)
            for stored_rd in range(rd_min, wr + 1, ALIGN):
                for candidate in range(0, wr + ALIGN + 1):
                    state = RingState(
                        base=base,
                        size=ring_size,
                        wr=wr,
                        rd=stored_rd,
                        configured=True,
                        rd_epoch_valid=True,
                    )
                    expected = (
                        aligned(candidate)
                        and stored_rd <= candidate <= wr
                        and wr - candidate <= ring_size
                    )
                    accepted = state.commit_rd(candidate)
                    require(accepted == expected, "steady-epoch Rd ownership decision mismatch")
                    require(state.wr == wr, "HPS Rd commit changed FPGA-owned W")
                    require(
                        state.rd == (candidate if expected else stored_rd),
                        "rejected Rd changed HPS-owned storage",
                    )
                    cases += 1

                # Stale storage from an earlier epoch must not impose a rewind rule on
                # the mandatory new-epoch Rd=0 initialization. No other first value is legal.
                for candidate in range(0, ALIGN + 1):
                    state = RingState(
                        base=base,
                        size=ring_size,
                        wr=0,
                        rd=stored_rd,
                        configured=True,
                        rd_epoch_valid=False,
                    )
                    accepted = state.commit_rd(candidate)
                    require(accepted == (candidate == 0), "new-epoch Rd=0 exception mismatch")
                    require(state.wr == 0, "new-epoch HPS Rd commit changed FPGA-owned W")
                    require(
                        state.rd == (0 if candidate == 0 else stored_rd),
                        "new-epoch rejected Rd changed HPS-owned storage",
                    )
                    cases += 1

    return cases


def check_directed_thresholds_and_ownership() -> None:
    base = 0x1000_0000

    exact = schedule(base=base, ring_size=512, guard=GUARD, wr=384, rd=64, length=128)
    require(exact.fits and not exact.needs_wrap and exact.normal_address == base + 384,
            "exact-end directed case failed")

    crossing_exact_free = schedule(
        base=base, ring_size=512, guard=GUARD, wr=448, rd=192, length=128
    )
    require(crossing_exact_free.needs_wrap, "crossing case did not request WRAP")
    require(crossing_exact_free.tail == 64, "crossing tail must be 64 bytes")
    require(crossing_exact_free.required_bytes == 192, "crossing must reserve tail + normal")
    require(crossing_exact_free.free_bytes == 192 and crossing_exact_free.fits,
            "exact-free crossing should fit")

    crossing_short = schedule(
        base=base, ring_size=512, guard=GUARD, wr=448, rd=128, length=128
    )
    require(crossing_short.free_bytes == 128, "directed short-free setup mismatch")
    require(crossing_short.required_bytes == 192 and not crossing_short.fits,
            "tail+normal insufficient-space case was accepted")

    state = RingState()
    state.hard_reset()
    require(not state.enable(), "writer enabled before ring configuration and Rd=0 commit")
    require(state.commit_config(base, 512), "legal config rejected")
    require(not state.enable(), "writer enabled before explicit Rd epoch commit")
    require(state.commit_rd(0), "explicit Rd=0 commit rejected")
    require(state.enable(), "writer enable rejected after config and Rd=0")

    first = state.current_schedule(128)
    require(state.commit_normal(128), "first normal commit rejected")
    require(state.wr == 128 and state.sequence == 1, "normal commit did not own W/sequence")
    require(not state.commit_rd(65), "unaligned Rd accepted")
    require(not state.commit_rd(192), "Rd greater than W accepted")
    require(state.commit_rd(64), "aligned forward Rd rejected")
    require(not state.commit_rd(0), "Rd rewind accepted")
    before = (state.wr, state.sequence)
    require(not state.commit_normal(128, responses_ok=False), "failed response committed W")
    require((state.wr, state.sequence) == before, "failed response changed W/sequence")

    require(state.commit_normal(128), "directed wrap setup normal 1 rejected")
    require(state.commit_rd(192), "directed wrap setup Rd rejected")
    require(state.commit_normal(128), "directed wrap setup normal 2 rejected")
    require(state.commit_normal(64), "directed wrap setup normal 3 rejected")
    crossing = state.current_schedule(128)
    require(crossing.needs_wrap and crossing.fits, "directed failed-WRAP setup mismatch")
    before = (state.wr, state.rd, state.sequence)
    require(not state.commit_wrap(crossing, responses_ok=False), "failed WRAP response committed W")
    require((state.wr, state.rd, state.sequence) == before,
            "failed WRAP response changed pointer/sequence ownership")

    state.busy = True
    state.telemetry_enable = False
    state.writer_enable = False
    require(not state.write_config_shadow_allowed(), "config shadow change allowed while busy")
    require(not state.commit_config(base + 0x1000, 512), "config commit allowed while busy")

    state.busy = False
    stored_rd = state.rd
    state.soft_reset_transport()
    require(state.rd == stored_rd, "transport reset wrote HPS-owned Rd storage")
    require(state.effective_rd == 0, "invalid Rd epoch did not expose safe zero")
    require(state.commit_config(base, 512), "post-reset config rejected")
    require(state.rd == stored_rd, "config commit wrote HPS-owned Rd storage")
    require(not state.commit_rd(64), "first Rd commit in a new epoch was not exactly zero")
    require(state.commit_rd(0), "new-epoch explicit Rd=0 exception was rejected")


def deterministic_trace(state: RingState) -> tuple[tuple[str, int, int, int], ...]:
    trace: list[tuple[str, int, int, int]] = []
    require(state.commit_config(0x1000_0000, 512), "trace config rejected")
    trace.append(("config", state.wr, state.effective_rd, state.sequence))
    require(state.commit_rd(0), "trace Rd=0 rejected")
    require(state.enable(), "trace enable rejected")
    for _ in range(3):
        require(state.commit_normal(128), "trace normal rejected")
        trace.append(("normal", state.wr, state.effective_rd, state.sequence))
    require(state.commit_rd(192), "trace forward Rd rejected")
    trace.append(("rd", state.wr, state.effective_rd, state.sequence))
    require(state.commit_normal(64), "trace 64-byte normal rejected")
    trace.append(("normal64", state.wr, state.effective_rd, state.sequence))
    crossing = state.current_schedule(128)
    require(crossing.needs_wrap and crossing.fits, "trace crossing schedule mismatch")
    sequence_before_wrap = state.sequence
    require(state.commit_wrap(crossing), "trace WRAP commit rejected")
    trace.append(("wrap", state.wr, state.effective_rd, state.sequence))
    require(state.sequence == sequence_before_wrap, "WRAP consumed a sequence number")
    require(state.commit_normal(128), "trace post-WRAP normal rejected")
    trace.append(("normal", state.wr, state.effective_rd, state.sequence))
    return tuple(trace)


def main() -> int:
    cases, wraps, exact_ends, no_space = exhaust_schedule_space()
    ownership_cases = exhaust_ownership_space()
    check_directed_thresholds_and_ownership()
    state = RingState()
    state.hard_reset()
    first = deterministic_trace(state)
    require(state.rd == 192, "directed trace did not establish a nonzero HPS-owned Rd")
    stored_rd = state.rd
    state.soft_reset_transport()
    require(state.rd == stored_rd, "transport reset changed stored HPS-owned Rd")
    require(
        (state.configured, state.rd_epoch_valid, state.wr, state.effective_rd, state.sequence)
        == (False, False, 0, 0, 0),
        "transport reset did not invalidate config/pointers",
    )
    second = deterministic_trace(state)
    require(first == second, "reconfigure + Rd=0 second trace is not deterministic")
    print(
        "STEP12_DDR_RING_MODEL_PASS "
        f"cases={cases} wrap_cases={wraps} exact_end_cases={exact_ends} "
        f"no_space_cases={no_space} ownership_cases={ownership_cases} "
        f"deterministic_events={len(first)}"
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"STEP12_DDR_RING_MODEL_FAIL: {exc}")
        raise
