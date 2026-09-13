# SPDX-License-Identifier: MIT
"""Constant-vector generator and shared generator arithmetic helpers.

The public generator package intentionally mirrors the Phase 2 Revision J
``test_vectors.json`` generator vocabulary.  It does not implement STFT/WOLA;
that remains the C++ golden model.  These helpers only construct frozen
``x_in.memh`` sample streams under the sample-scale arithmetic contract.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Iterable

from trecap_golden.generated import trecap_config as cfg


class GeneratorError(ValueError):
    """Raised when generator parameters violate the frozen contract."""


def validate_ns(ns: int) -> int:
    """Validate and return a nonempty Revision J input-vector length."""

    if not isinstance(ns, int):
        raise TypeError(f"Ns must be an int, got {type(ns).__name__}")
    if ns <= 0:
        raise GeneratorError("Revision J signoff vectors require Ns > 0")
    return ns


def validate_sample_width(width: int = cfg.N) -> int:
    """Validate a signed sample width."""

    if not isinstance(width, int):
        raise TypeError(f"sample width must be an int, got {type(width).__name__}")
    if width <= 0:
        raise GeneratorError("sample width must be positive")
    return width


def signed_bounds(width: int = cfg.N) -> tuple[int, int]:
    """Return inclusive two's-complement signed sample bounds."""

    checked = validate_sample_width(width)
    return (-(1 << (checked - 1)), (1 << (checked - 1)) - 1)


def satn(value: int, width: int = cfg.N) -> int:
    """Saturate ``value`` to a signed ``width``-bit sample."""

    if not isinstance(value, int):
        raise TypeError(f"sample value must be an int, got {type(value).__name__}")
    lo, hi = signed_bounds(width)
    if value < lo:
        return lo
    if value > hi:
        return hi
    return value


def coerce_int(value: int | str, *, name: str) -> int:
    """Parse an integer parameter without accepting bools as integers."""

    if isinstance(value, bool):
        raise GeneratorError(f"{name} must be an integer, not bool")
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise GeneratorError(f"{name} must be an integer, got {value!r}") from exc


def parse_phase_decimal(value: int | float | str | Decimal = "0") -> Decimal:
    """Parse a phase-radian parameter as an exact decimal token first.

    The trigonometric evaluation still uses Python's math library for the
    frozen generator implementation.  This function prevents legacy ``a/b``
    strings or malformed floating text from entering signoff configs.
    """

    text = str(value)
    if "/" in text:
        raise GeneratorError("phase_rad must be a decimal string, not a fraction string")
    try:
        return Decimal(text)
    except InvalidOperation as exc:
        raise GeneratorError(f"invalid decimal phase_rad: {value!r}") from exc


def qcoef(value: float, frac_bits: int = 0) -> int:
    """Quantize using round-to-nearest ties-away-from-zero.

    This is the generator-side scalar equivalent of ``qcoef(c, F)``.  It is
    deliberately implemented without Python's language-default ``round()``.
    """

    if frac_bits < 0:
        raise GeneratorError("frac_bits must be nonnegative")
    if value == 0.0:
        return 0
    sign = 1 if value > 0 else -1
    return sign * int(abs(float(value)) * float(1 << frac_bits) + 0.5)


def validate_frequency(f_num: int, f_den: int, *, name: str = "frequency") -> tuple[int, int]:
    """Validate an exact rational normalized frequency ``f_num/f_den``."""

    numerator = coerce_int(f_num, name=f"{name}.f_num")
    denominator = coerce_int(f_den, name=f"{name}.f_den")
    if denominator <= 0:
        raise GeneratorError(f"{name}.f_den must be positive")
    return numerator, denominator


def frequency_from_parameters(parameters: dict[str, object], *, exact_bin: bool = False) -> tuple[int, int]:
    """Return ``(f_num, f_den)`` from generator parameters.

    Exact-bin generators use ``bin`` or ``k`` and force the denominator to the
    frozen FFT length ``L``.  General sine/cosine generators require explicit
    ``f_num`` and ``f_den`` integer fields.
    """

    if exact_bin or "bin" in parameters or "k" in parameters:
        k = coerce_int(parameters.get("bin", parameters.get("k", 0)), name="bin")
        if k < 0 or k > cfg.L // 2:
            raise GeneratorError(f"exact-bin index must satisfy 0 <= k <= L/2, got {k}")
        return k, cfg.L
    if "f_num" not in parameters or "f_den" not in parameters:
        raise GeneratorError("frequency parameters must include f_num and f_den")
    return validate_frequency(parameters["f_num"], parameters["f_den"])


def ensure_samples(values: Iterable[int], *, width: int = cfg.N) -> tuple[int, ...]:
    """Return a tuple after verifying every value is in signed sample range."""

    lo, hi = signed_bounds(width)
    out = tuple(int(v) for v in values)
    for idx, value in enumerate(out):
        if value < lo or value > hi:
            raise GeneratorError(f"sample[{idx}]={value} exceeds signed {width}-bit range")
    return out


def generate(ns: int, value: int = 0, *, width: int = cfg.N) -> tuple[int, ...]:
    """Generate ``x[n] = satN(value)`` for ``0 <= n < Ns``."""

    checked_ns = validate_ns(ns)
    sample = satn(coerce_int(value, name="value"), width)
    return (sample,) * checked_ns


__all__ = [
    "GeneratorError",
    "coerce_int",
    "ensure_samples",
    "frequency_from_parameters",
    "generate",
    "parse_phase_decimal",
    "qcoef",
    "satn",
    "signed_bounds",
    "validate_frequency",
    "validate_ns",
    "validate_sample_width",
]
