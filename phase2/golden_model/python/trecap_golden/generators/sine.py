# SPDX-License-Identifier: MIT
"""Sine and exact-bin sine input-vector generators."""

from __future__ import annotations

import math
from decimal import Decimal

from trecap_golden.generated import trecap_config as cfg

from .constant import (
    coerce_int,
    frequency_from_parameters,
    parse_phase_decimal,
    qcoef,
    satn,
    validate_ns,
)


def generate(
    ns: int,
    *,
    amplitude: int | str,
    f_num: int | str | None = None,
    f_den: int | str | None = None,
    phase_rad: int | float | str | Decimal = "0",
    bin: int | str | None = None,
    k: int | str | None = None,
    exact_bin: bool = False,
    width: int = cfg.N,
) -> tuple[int, ...]:
    """Generate ``satN(qcoef(A*sin(2*pi*f*n + phase), 0))``."""

    checked_ns = validate_ns(ns)
    params: dict[str, object] = {}
    if f_num is not None:
        params["f_num"] = f_num
    if f_den is not None:
        params["f_den"] = f_den
    if bin is not None:
        params["bin"] = bin
    if k is not None:
        params["k"] = k
    freq_num, freq_den = frequency_from_parameters(params, exact_bin=exact_bin)
    amp = coerce_int(amplitude, name="amplitude")
    phase = float(parse_phase_decimal(phase_rad))
    return tuple(
        satn(qcoef(amp * math.sin((2.0 * math.pi * freq_num * n / freq_den) + phase), 0), width)
        for n in range(checked_ns)
    )


def generate_exact_bin(
    ns: int,
    *,
    amplitude: int | str,
    bin: int | str | None = None,
    k: int | str | None = None,
    phase_rad: int | float | str | Decimal = "0",
    width: int = cfg.N,
) -> tuple[int, ...]:
    """Generate an exact-bin sine using ``f = k/L``."""

    return generate(
        ns,
        amplitude=amplitude,
        bin=bin,
        k=k,
        phase_rad=phase_rad,
        exact_bin=True,
        width=width,
    )


__all__ = ["generate", "generate_exact_bin"]
