#!/usr/bin/env python3
"""Cycle-level control model for the C0 input-ring admission fix.

This script is an executable architectural check, not an RTL simulator. The
SystemVerilog test under sim/tb is the implementation-level regression.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re

REPO_ROOT = Path(__file__).resolve().parents[2]
CORE_PACKAGE = REPO_ROOT / "rtl/include/generated/trecap_core_pkg.sv"


def generated_unsigned_constant(name: str) -> int:
    """Read a decimal unsigned localparam from the generated RTL contract."""

    package_text = CORE_PACKAGE.read_text(encoding="utf-8")
    match = re.search(
        rf"\blocalparam\s+int\s+unsigned\s+{re.escape(name)}\s*=\s*(\d+)\s*;",
        package_text,
    )
    if match is None:
        raise RuntimeError(f"missing decimal generated constant {name} in {CORE_PACKAGE}")
    return int(match.group(1))


L = generated_unsigned_constant("T_FFT_L")
H = generated_unsigned_constant("T_HOP_H")
TARGET_SAMPLES = 6 * H
EXPECTED_FRAMES = TARGET_SAMPLES // H
MAX_CYCLES = 20_000


@dataclass
class Result:
    cycles: int
    accepted_samples: int
    due_frames: int
    accepted_frame_requests: int
    completed_frames: int
    completed_frame_beats: int
    dropped_frames: int
    accepts_while_ring_reserved: int
    max_post_boundary_lookahead: int
    directed_frame_stall_cycles: int
    triggers: list[int]


def downstream_ready(cycle: int) -> bool:
    """Match the prolonged and periodic stalls in the SV regression."""

    return not (180 <= cycle < 900) and (cycle % 5) != 0


def run_model(*, conservative_gate: bool) -> Result:
    source_idx = 0

    ring_accept_pulse = False
    ring_accept_idx = 0
    ring_active = False
    ring_out_valid = False
    ring_out_last = False
    ring_offset = 0

    scheduler_valid = False
    scheduler_frame_idx = 0
    scheduler_trigger_idx = 0
    scheduler_accepted_samples = 0
    scheduler_generated_frames = 0

    due_frames = 0
    accepted_frame_requests = 0
    completed_frames = 0
    completed_frame_beats = 0
    dropped_frames = 0
    accepts_while_ring_reserved = 0
    awaiting_frame_request = False
    post_boundary_lookahead = 0
    max_post_boundary_lookahead = 0
    directed_frame_stall_cycles = 0
    triggers: list[int] = []

    for cycle in range(MAX_CYCLES):
        frame_req_ready = not ring_active and not ring_out_valid
        frame_req_accept = scheduler_valid and frame_req_ready
        frame_sample_ready = downstream_ready(cycle)
        frame_sample_accept = ring_out_valid and frame_sample_ready
        if 180 <= cycle < 900 and ring_out_valid and not frame_sample_ready:
            directed_frame_stall_cycles += 1
        load_next_beat = ring_active and (
            not ring_out_valid or frame_sample_ready
        )

        ring_reserved = scheduler_valid or ring_active or ring_out_valid
        sample_ready = (not ring_reserved) if conservative_gate else True
        source_valid = source_idx < TARGET_SAMPLES
        source_accept = source_valid and sample_ready

        if source_accept and ring_reserved:
            accepts_while_ring_reserved += 1
        if source_accept:
            if ((source_idx + 1) % H) == 0:
                awaiting_frame_request = True
                post_boundary_lookahead = 0
            elif awaiting_frame_request:
                post_boundary_lookahead += 1
                max_post_boundary_lookahead = max(
                    max_post_boundary_lookahead,
                    post_boundary_lookahead,
                )

        next_sample_count = scheduler_accepted_samples + 1
        frame_due = ring_accept_pulse and (next_sample_count % H) == 0

        next_scheduler_valid = scheduler_valid
        next_scheduler_frame_idx = scheduler_frame_idx
        next_scheduler_trigger_idx = scheduler_trigger_idx
        next_scheduler_accepted_samples = scheduler_accepted_samples
        next_scheduler_generated_frames = scheduler_generated_frames

        if ring_accept_pulse:
            next_scheduler_accepted_samples = next_sample_count

        if frame_req_accept:
            accepted_frame_requests += 1
            triggers.append(scheduler_trigger_idx)
            next_scheduler_valid = False
            awaiting_frame_request = False

        if frame_due:
            due_frames += 1
            if scheduler_valid and not frame_req_ready:
                dropped_frames += 1
            else:
                next_scheduler_valid = True
                next_scheduler_frame_idx = scheduler_generated_frames
                next_scheduler_trigger_idx = ring_accept_idx
                next_scheduler_generated_frames = scheduler_generated_frames + 1

        next_ring_active = ring_active
        next_ring_out_valid = ring_out_valid
        next_ring_out_last = ring_out_last
        next_ring_offset = ring_offset

        if frame_sample_accept and not load_next_beat:
            next_ring_out_valid = False
            next_ring_out_last = False

        if frame_req_accept:
            next_ring_active = True
            next_ring_offset = 0

        if load_next_beat:
            next_ring_out_valid = True
            next_ring_out_last = ring_offset == (L - 1)
            if ring_offset == (L - 1):
                next_ring_active = False
                next_ring_offset = 0
            else:
                next_ring_offset = ring_offset + 1

        if frame_sample_accept:
            completed_frame_beats += 1
            if ring_out_last:
                completed_frames += 1

        next_ring_accept_pulse = source_accept
        next_ring_accept_idx = source_idx if source_accept else ring_accept_idx
        next_source_idx = source_idx + 1 if source_accept else source_idx

        source_idx = next_source_idx
        ring_accept_pulse = next_ring_accept_pulse
        ring_accept_idx = next_ring_accept_idx
        ring_active = next_ring_active
        ring_out_valid = next_ring_out_valid
        ring_out_last = next_ring_out_last
        ring_offset = next_ring_offset
        scheduler_valid = next_scheduler_valid
        scheduler_frame_idx = next_scheduler_frame_idx
        scheduler_trigger_idx = next_scheduler_trigger_idx
        scheduler_accepted_samples = next_scheduler_accepted_samples
        scheduler_generated_frames = next_scheduler_generated_frames

        drained = (
            source_idx == TARGET_SAMPLES
            and not ring_accept_pulse
            and not scheduler_valid
            and not ring_active
            and not ring_out_valid
        )
        if drained:
            return Result(
                cycles=cycle + 1,
                accepted_samples=source_idx,
                due_frames=due_frames,
                accepted_frame_requests=accepted_frame_requests,
                completed_frames=completed_frames,
                completed_frame_beats=completed_frame_beats,
                dropped_frames=dropped_frames,
                accepts_while_ring_reserved=accepts_while_ring_reserved,
                max_post_boundary_lookahead=max_post_boundary_lookahead,
                directed_frame_stall_cycles=directed_frame_stall_cycles,
                triggers=triggers,
            )

    raise RuntimeError("C0 flow-control model watchdog expired")


def main() -> int:
    legacy = run_model(conservative_gate=False)
    fixed = run_model(conservative_gate=True)

    def require(condition: bool, message: str) -> None:
        if not condition:
            raise RuntimeError(message)

    expected_triggers = [((frame + 1) * H) - 1 for frame in range(EXPECTED_FRAMES)]

    require(legacy.accepted_samples == TARGET_SAMPLES, "legacy source did not drain")
    require(legacy.due_frames == EXPECTED_FRAMES, "legacy due-frame count drifted")
    require(legacy.dropped_frames >= 1, "legacy model no longer reproduces frame loss")
    require(
        legacy.accepted_frame_requests < legacy.due_frames,
        "legacy model unexpectedly conserved frame requests",
    )
    require(
        legacy.accepts_while_ring_reserved > 0,
        "legacy model did not write while the ring was reserved",
    )

    require(fixed.accepted_samples == TARGET_SAMPLES, "fixed source did not drain")
    require(fixed.due_frames == EXPECTED_FRAMES, "fixed due-frame count mismatch")
    require(
        fixed.accepted_frame_requests == EXPECTED_FRAMES,
        "fixed request count mismatch",
    )
    require(fixed.completed_frames == EXPECTED_FRAMES, "fixed frame count mismatch")
    require(
        fixed.completed_frame_beats == EXPECTED_FRAMES * L,
        "fixed frame-beat count mismatch",
    )
    require(fixed.dropped_frames == 0, "fixed model dropped a frame")
    require(
        fixed.accepts_while_ring_reserved == 0,
        "fixed model accepted a sample while the ring was reserved",
    )
    require(
        fixed.max_post_boundary_lookahead == 1,
        "fixed model did not enforce/exercise the one-sample look-ahead bound",
    )
    require(
        fixed.directed_frame_stall_cycles == 720,
        "fixed model did not overlap all directed stall clocks with a valid frame beat",
    )
    require(fixed.triggers == expected_triggers, "fixed trigger sequence mismatch")

    print(
        "LEGACY_FAIL "
        f"due={legacy.due_frames} accepted_frames={legacy.accepted_frame_requests} "
        f"dropped={legacy.dropped_frames} reserved_accepts="
        f"{legacy.accepts_while_ring_reserved}"
    )
    print(
        "FIXED_PASS "
        f"samples={fixed.accepted_samples} frames={fixed.accepted_frame_requests} "
        f"beats={fixed.completed_frame_beats} triggers={fixed.triggers} "
        f"lookahead={fixed.max_post_boundary_lookahead} cycles={fixed.cycles}"
    )
    print(
        "C0_FLOW_CONTROL_MODEL_PASS "
        f"samples={fixed.accepted_samples} frames={fixed.accepted_frame_requests} "
        f"beats={fixed.completed_frame_beats}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
