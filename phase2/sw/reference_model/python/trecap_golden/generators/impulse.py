# SPDX-License-Identifier: MIT
"""Impulse input-vector generator."""

from __future__ import annotations

from trecap_golden.generated import trecap_config as cfg

from .constant import GeneratorError, coerce_int, satn, validate_ns


def generate(
    ns: int,
    *,
    index: int | str | None = None,
    n0: int | str | None = None,
    amplitude: int | str | None = None,
    A: int | str | None = None,
    width: int = cfg.N,
) -> tuple[int, ...]:
    """Generate an impulse: ``satN(amplitude)`` at ``index`` and zero elsewhere."""

    checked_ns = validate_ns(ns)
    raw_index = index if index is not None else n0
    if raw_index is None:
        raw_index = 0
    idx = coerce_int(raw_index, name="index")
    if idx < 0 or idx >= checked_ns:
        raise GeneratorError(f"impulse index must satisfy 0 <= index < Ns, got {idx}")
    raw_amp = amplitude if amplitude is not None else A
    if raw_amp is None:
        raw_amp = 0
    amp = satn(coerce_int(raw_amp, name="amplitude"), width)
    return tuple(amp if n == idx else 0 for n in range(checked_ns))


__all__ = ["generate"]
