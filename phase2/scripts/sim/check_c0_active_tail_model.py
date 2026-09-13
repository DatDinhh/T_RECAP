#!/usr/bin/env python3
"""Dependency-free contract model for C0 active-frame/tail separation.

This checks finite-stream geometry and token conservation. It is not an HDL
simulation and is intentionally reported as architectural evidence only.
"""

from __future__ import annotations

from dataclasses import dataclass

L = 256
H = 128
G = 128
D = L + G


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


@dataclass(frozen=True)
class Geometry:
    ns: int
    frames: int
    tau_last: int
    ny: int

    @property
    def analysis_flush(self) -> int:
        return self.tau_last - self.ns

    @property
    def drain(self) -> int:
        return self.ny - self.tau_last


def geometry(ns: int) -> Geometry:
    if ns <= 0:
        raise ValueError("Revision J requires Ns > 0")
    frames = (ns + L - 2) // H
    tau_last = frames * H
    return Geometry(ns=ns, frames=frames, tau_last=tau_last, ny=tau_last + D)


def legacy_frame_count(g: Geometry) -> int:
    """Every Ny tick reaches the old modulo-H scheduler."""

    return g.ny // H


def fixed_schedule(g: Geometry) -> tuple[list[int], list[int]]:
    """Return active trigger indices and pure-drain token indices."""

    triggers = [((frame + 1) * H) - 1 for frame in range(g.frames)]
    drain_indices = list(range(g.tau_last, g.ny))
    return triggers, drain_indices


def check(ns: int) -> None:
    g = geometry(ns)
    triggers, drain_indices = fixed_schedule(g)

    require(len(triggers) == g.frames, f"Ns={ns}: frame count mismatch")
    require(triggers[-1] == g.tau_last - 1, f"Ns={ns}: final trigger mismatch")
    require(len(drain_indices) == D, f"Ns={ns}: drain length mismatch")
    require(drain_indices[0] == g.tau_last, f"Ns={ns}: drain start mismatch")
    require(drain_indices[-1] == g.ny - 1, f"Ns={ns}: drain end mismatch")
    require(g.analysis_flush >= 0, f"Ns={ns}: negative analysis flush")
    require(g.drain == D, f"Ns={ns}: delay/drain mismatch")
    require((g.frames * H) + g.drain == g.ny, f"Ns={ns}: Ny conservation mismatch")

    legacy_frames = legacy_frame_count(g)
    require(
        legacy_frames == g.frames + (D // H),
        f"Ns={ns}: legacy-frame delta mismatch",
    )

    print(
        "ACTIVE_TAIL_MODEL_PASS "
        f"Ns={g.ns} frames={g.frames} tau_last={g.tau_last} "
        f"analysis_flush={g.analysis_flush} drain={g.drain} Ny={g.ny} "
        f"legacy_dummy_frames={legacy_frames - g.frames}"
    )


def main() -> int:
    for ns in (1, 2, 17, 248, 1024, 4096):
        check(ns)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
