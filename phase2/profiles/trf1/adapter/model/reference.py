"""Independent finite-file I/Q golden model using full convolution.

No FPGA, transport, or simulation access. The algorithm intentionally does not
duplicate the RTL's polyphase schedule or history implementation.
"""
from __future__ import annotations

import numpy as np
from scipy.signal import firwin, resample_poly

UPSAMPLE = 4
TAPS = 81
DELAY = 40
COEFF_FRAC = 16


def prototype() -> np.ndarray:
    return 4.0 * firwin(TAPS, 0.25, window=("kaiser", 8.6))


def coefficients() -> np.ndarray:
    return np.rint(prototype() * (1 << COEFF_FRAC)).astype(np.int64)


def validate_pairs(pairs) -> np.ndarray:
    pairs = np.asarray(pairs)
    if pairs.ndim != 2 or pairs.shape[1] != 2 or len(pairs) == 0:
        raise ValueError("Expected nonempty (N,2) CU8 input")
    if pairs.dtype.kind not in "iu" or np.any(pairs < 0) or np.any(pairs > 255):
        raise ValueError("Input components must be integers between 0 and 255")
    return pairs.astype(np.int64)


def round_away(values, shift: int) -> np.ndarray:
    """Nearest integer with signed half ties away from zero."""
    values = np.asarray(values, dtype=np.int64)
    if not isinstance(shift, int) or shift < 1 or shift > 62:
        raise ValueError("Invalid right shift")
    magnitude = np.abs(values)
    result = (magnitude + (1 << (shift - 1))) >> shift
    return np.where(values < 0, -result, result)


def accumulate(pairs, taps=None) -> np.ndarray:
    """Return centered, mixed, unrounded integer FIR sums."""
    pairs = validate_pairs(pairs)
    taps = coefficients() if taps is None else np.asarray(taps, dtype=np.int64)
    if taps.shape != (TAPS,):
        raise ValueError("Expected 81 coefficients")
    signed = 2 * pairs - 255
    inserted = np.zeros((UPSAMPLE * len(pairs), 2), dtype=np.int64)
    inserted[::UPSAMPLE] = signed
    channels = [np.convolve(inserted[:, lane], taps, mode="full")
                [DELAY:DELAY + UPSAMPLE * len(pairs)] for lane in range(2)]
    phase = np.arange(UPSAMPLE * len(pairs)) % 4
    mixed = np.where(phase % 2 == 0, channels[0], channels[1])
    return np.where((phase == 1) | (phase == 2), -mixed, mixed)


def convert(pairs, gain_shift: int = 2) -> dict:
    if not isinstance(gain_shift, int) or gain_shift not in range(4):
        raise ValueError("gain_shift must be an integer from 0 to 3")
    acc = accumulate(pairs)
    rounded = round_away(acc, COEFF_FRAC - gain_shift)
    clipped = (rounded < -2048) | (rounded > 2047)
    return {"samples": np.clip(rounded, -2048, 2047).astype(np.int16),
            "clipped": clipped, "rounded": rounded, "accumulators": acc}


def float_reference(pairs, gain_shift: int = 2) -> np.ndarray:
    p = validate_pairs(pairs)
    z = ((p[:, 0] - 127.5) + 1j * (p[:, 1] - 127.5)) / 128.0
    interp = resample_poly(z, 4, 1, window=("kaiser", 8.6), padtype="constant")
    oscillator = np.resize(np.array([1, 1j, -1, -1j]), len(interp))
    return np.real(interp * oscillator) * (256 << gain_shift)
