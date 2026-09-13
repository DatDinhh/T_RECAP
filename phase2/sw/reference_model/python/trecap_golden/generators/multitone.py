# SPDX-License-Identifier: MIT
"""Multitone sine-sum input-vector generator."""

from __future__ import annotations

import math
from collections.abc import Sequence
from decimal import Decimal
from typing import Any, Mapping

from trecap_golden.generated import trecap_config as cfg

from .constant import GeneratorError, coerce_int, parse_phase_decimal, qcoef, satn, validate_frequency, validate_ns


def _tone_fields(tone: Mapping[str, Any], *, tone_index: int) -> tuple[int, int, int, float]:
    if "amplitude" not in tone:
        raise GeneratorError(f"tone[{tone_index}] missing amplitude")
    amp = coerce_int(tone["amplitude"], name=f"tone[{tone_index}].amplitude")
    if "f_num" not in tone or "f_den" not in tone:
        raise GeneratorError(f"tone[{tone_index}] must include f_num and f_den")
    f_num, f_den = validate_frequency(tone["f_num"], tone["f_den"], name=f"tone[{tone_index}]")
    phase = float(parse_phase_decimal(tone.get("phase_rad", "0")))
    return amp, f_num, f_den, phase


def generate(
    ns: int,
    *,
    tones: Sequence[Mapping[str, Any]],
    width: int = cfg.N,
) -> tuple[int, ...]:
    """Generate ``multitone_sine_sum``.

    The real-valued sum is formed first for each sample, then ``qcoef(..., 0)``
    and ``satN`` are applied once to the final sum.  This intentionally rejects
    per-tone integer rounding before summation.
    """

    checked_ns = validate_ns(ns)
    if not isinstance(tones, Sequence) or isinstance(tones, (str, bytes)):
        raise GeneratorError("tones must be a sequence of tone objects")
    parsed = tuple(_tone_fields(tone, tone_index=i) for i, tone in enumerate(tones))
    if not parsed:
        raise GeneratorError("multitone_sine_sum requires at least one tone")
    out: list[int] = []
    for n in range(checked_ns):
        total = 0.0
        for amp, f_num, f_den, phase in parsed:
            total += amp * math.sin((2.0 * math.pi * f_num * n / f_den) + phase)
        out.append(satn(qcoef(total, 0), width))
    return tuple(out)


__all__ = ["generate"]
