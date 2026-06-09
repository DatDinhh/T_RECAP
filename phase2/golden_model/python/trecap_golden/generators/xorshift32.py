# SPDX-License-Identifier: MIT
"""Uniform-noise xorshift32 input-vector generator."""

from __future__ import annotations

from trecap_golden.generated import trecap_config as cfg

from .constant import GeneratorError, coerce_int, satn, validate_ns


def _update(state: int) -> int:
    state ^= (state << 13) & 0xFFFFFFFF
    state ^= state >> 17
    state ^= (state << 5) & 0xFFFFFFFF
    return state & 0xFFFFFFFF


def generate(
    ns: int,
    *,
    seed: int | str,
    B: int | str | None = None,
    bit_width: int | str | None = None,
    width: int = cfg.N,
) -> tuple[int, ...]:
    """Generate centered uniform noise using the frozen xorshift32 recurrence."""

    checked_ns = validate_ns(ns)
    state = coerce_int(seed, name="seed") & 0xFFFFFFFF
    if state == 0:
        raise GeneratorError("xorshift32 seed must be nonzero after 32-bit masking")
    raw_b = B if B is not None else bit_width
    if raw_b is None:
        raw_b = width
    b = coerce_int(raw_b, name="B")
    if b <= 0 or b > 32:
        raise GeneratorError("xorshift32 B must satisfy 1 <= B <= 32")
    mask = 0xFFFFFFFF if b == 32 else (1 << b) - 1
    offset = 1 << (b - 1)
    out: list[int] = []
    for _ in range(checked_ns):
        state = _update(state)
        out.append(satn((state & mask) - offset, width))
    return tuple(out)


__all__ = ["generate"]
