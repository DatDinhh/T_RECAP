# SPDX-License-Identifier: MIT
"""Frozen input-vector generators for T-RECAP Phase 2 artifacts.

This package implements only the ``x_in.memh`` generator layer.  It is not a
second STFT/WOLA golden model.  The supported names match the Revision J
``test_vectors.json`` vocabulary and are dispatched by :func:`generate_samples`.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Final

from . import constant, cosine, impulse, multitone, sine, step, xorshift32
from .constant import GeneratorError, qcoef, satn, signed_bounds

SUPPORTED_GENERATORS: Final[tuple[str, ...]] = (
    "constant",
    "impulse",
    "step",
    "sine",
    "exact_bin_sine",
    "cosine",
    "exact_bin_cosine",
    "multitone_sine_sum",
    "uniform_noise_xorshift32",
)


def _parameters(parameters: Mapping[str, Any] | None) -> dict[str, Any]:
    if parameters is None:
        return {}
    if not isinstance(parameters, Mapping):
        raise GeneratorError("generator parameters must be a mapping")
    return dict(parameters)


def generate_samples(
    generator: str,
    ns: int,
    parameters: Mapping[str, Any] | None = None,
    *,
    sample_width: int = 12,
) -> tuple[int, ...]:
    """Generate a signed sample vector by frozen generator name.

    Parameters are the exact ``parameters`` object from one vector entry in
    ``test_vectors.json``.  The output is a tuple of signed integers already
    clipped by ``satN``.
    """

    name = generator.strip()
    p = _parameters(parameters)
    if name == "constant":
        return constant.generate(ns, value=p.get("value", 0), width=sample_width)
    if name == "impulse":
        return impulse.generate(
            ns,
            index=p.get("index"),
            n0=p.get("n0"),
            amplitude=p.get("amplitude"),
            A=p.get("A"),
            width=sample_width,
        )
    if name == "step":
        return step.generate(
            ns,
            index=p.get("index"),
            n0=p.get("n0"),
            amplitude=p.get("amplitude"),
            A=p.get("A"),
            width=sample_width,
        )
    if name == "sine":
        return sine.generate(
            ns,
            amplitude=p["amplitude"],
            f_num=p.get("f_num"),
            f_den=p.get("f_den"),
            phase_rad=p.get("phase_rad", "0"),
            width=sample_width,
        )
    if name == "exact_bin_sine":
        return sine.generate_exact_bin(
            ns,
            amplitude=p["amplitude"],
            bin=p.get("bin"),
            k=p.get("k"),
            phase_rad=p.get("phase_rad", "0"),
            width=sample_width,
        )
    if name == "cosine":
        return cosine.generate(
            ns,
            amplitude=p["amplitude"],
            f_num=p.get("f_num"),
            f_den=p.get("f_den"),
            phase_rad=p.get("phase_rad", "0"),
            width=sample_width,
        )
    if name == "exact_bin_cosine":
        return cosine.generate_exact_bin(
            ns,
            amplitude=p["amplitude"],
            bin=p.get("bin"),
            k=p.get("k"),
            phase_rad=p.get("phase_rad", "0"),
            width=sample_width,
        )
    if name == "multitone_sine_sum":
        return multitone.generate(ns, tones=p.get("tones", ()), width=sample_width)
    if name == "uniform_noise_xorshift32":
        return xorshift32.generate(
            ns,
            seed=p["seed"],
            B=p.get("B"),
            bit_width=p.get("bit_width"),
            width=sample_width,
        )
    supported = ", ".join(SUPPORTED_GENERATORS)
    raise GeneratorError(f"unsupported generator {name!r}; supported: {supported}")


__all__ = [
    "GeneratorError",
    "SUPPORTED_GENERATORS",
    "constant",
    "cosine",
    "generate_samples",
    "impulse",
    "multitone",
    "qcoef",
    "satn",
    "signed_bounds",
    "sine",
    "step",
    "xorshift32",
]
