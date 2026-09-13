# SPDX-License-Identifier: MIT
"""Canonical ``.memh`` encoding for T-RECAP golden artifacts.

The Phase 2 artifact contract uses one logical integer per line, fixed-width
lowercase hexadecimal, LF-only line endings, and signed two's-complement decode
when the artifact is signed.  This module is intentionally independent of the
command-line tools so tests, release scripts, and notebooks can all use the same
canonical parser.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

from trecap_golden.generated import trecap_config as cfg

_LINE_RE = re.compile(r"^[0-9a-f]+$")


class MemhError(ValueError):
    """Raised when a memory file violates the canonical artifact contract."""


@dataclass(frozen=True, slots=True)
class MemhContract:
    """Declared interpretation of one memh artifact."""

    width_bits: int
    signed: bool
    rows: int | None = None
    kind: str | None = None

    @property
    def hex_digits(self) -> int:
        """Number of hex digits required on each canonical line."""

        return hex_digits(self.width_bits)


@dataclass(frozen=True, slots=True)
class MemhReadResult:
    """Parsed memh values and the contract used to parse them."""

    path: Path
    contract: MemhContract
    values: tuple[int, ...]

    @property
    def rows(self) -> int:
        return len(self.values)

    def canonical_text(self) -> str:
        return canonical_text(self.values, self.contract)

    def canonical_bytes(self) -> bytes:
        return canonical_bytes(self.values, self.contract)


def hex_digits(width_bits: int) -> int:
    """Return fixed-width hexadecimal digit count for ``width_bits`` bits."""

    if not isinstance(width_bits, int):
        raise TypeError("width_bits must be an int")
    if width_bits <= 0:
        raise MemhError("memh width must be positive")
    return (width_bits + 3) // 4


def signed_bounds(width_bits: int) -> tuple[int, int]:
    """Return inclusive signed two's-complement bounds for ``width_bits``."""

    if width_bits <= 0:
        raise MemhError("signed width must be positive")
    return (-(1 << (width_bits - 1)), (1 << (width_bits - 1)) - 1)


def unsigned_bound(width_bits: int) -> int:
    """Return one-past-maximum unsigned value for ``width_bits``."""

    if width_bits <= 0:
        raise MemhError("unsigned width must be positive")
    return 1 << width_bits


def encode_value(value: int, contract: MemhContract) -> str:
    """Encode one integer as a canonical memh line without the trailing LF."""

    if not isinstance(value, int):
        raise TypeError(f"memh value must be int, got {type(value).__name__}")
    if contract.signed:
        lo, hi = signed_bounds(contract.width_bits)
        if value < lo or value > hi:
            raise MemhError(f"signed value {value} does not fit in {contract.width_bits} bits")
        encoded = value & ((1 << contract.width_bits) - 1)
    else:
        if value < 0 or value >= unsigned_bound(contract.width_bits):
            raise MemhError(f"unsigned value {value} does not fit in {contract.width_bits} bits")
        encoded = value
    return f"{encoded:0{contract.hex_digits}x}"


def decode_token(token: str, contract: MemhContract, *, line_number: int | None = None) -> int:
    """Decode one canonical token into an integer."""

    prefix = "memh line" if line_number is None else f"memh line {line_number}"
    if not _LINE_RE.fullmatch(token):
        raise MemhError(f"{prefix}: noncanonical token {token!r}; expected lowercase hex only")
    if len(token) != contract.hex_digits:
        raise MemhError(
            f"{prefix}: expected {contract.hex_digits} hex digits for {contract.width_bits} bits, "
            f"got {len(token)}"
        )
    raw = int(token, 16)
    if raw >= (1 << contract.width_bits):
        raise MemhError(f"{prefix}: token {token!r} exceeds {contract.width_bits}-bit range")
    if contract.signed and raw & (1 << (contract.width_bits - 1)):
        return raw - (1 << contract.width_bits)
    return raw


def canonical_text(values: Iterable[int], contract: MemhContract) -> str:
    """Serialize integer values to canonical memh text."""

    seq = tuple(int(value) for value in values)
    if contract.rows is not None and len(seq) != contract.rows:
        raise MemhError(f"expected {contract.rows} rows, got {len(seq)}")
    return "".join(f"{encode_value(value, contract)}\n" for value in seq)


def canonical_bytes(values: Iterable[int], contract: MemhContract) -> bytes:
    """Serialize integer values to canonical ASCII bytes."""

    return canonical_text(values, contract).encode("ascii")


def parse_text(text: str, contract: MemhContract, *, path: str | Path | None = None) -> tuple[int, ...]:
    """Parse canonical memh text.

    The parser is strict: no blank lines, no CRLF, and the final value must be
    terminated by LF.  An empty file is permitted only when the declared row
    count is ``0`` or unspecified.
    """

    label = f"{path}: " if path is not None else ""
    if "\r" in text:
        raise MemhError(f"{label}CRLF or carriage return is not canonical memh")
    if text and not text.endswith("\n"):
        raise MemhError(f"{label}canonical memh must end every value with LF")
    lines = text.splitlines()
    if any(line == "" for line in lines):
        raise MemhError(f"{label}blank lines are not canonical memh")
    values = tuple(decode_token(line, contract, line_number=i) for i, line in enumerate(lines, start=1))
    if contract.rows is not None and len(values) != contract.rows:
        raise MemhError(f"{label}expected {contract.rows} rows, got {len(values)}")
    # Force a round-trip check so over-wide hex and noncanonical padding cannot slip through.
    if text != canonical_text(values, MemhContract(contract.width_bits, contract.signed, len(values), contract.kind)):
        raise MemhError(f"{label}memh is not in canonical serialization")
    return values


def read_memh(path: str | Path, contract: MemhContract) -> MemhReadResult:
    """Read and validate a canonical memh file."""

    p = Path(path)
    try:
        raw = p.read_bytes()
    except FileNotFoundError as exc:
        raise MemhError(f"missing memh file: {p}") from exc
    try:
        text = raw.decode("ascii")
    except UnicodeDecodeError as exc:
        raise MemhError(f"{p}: memh must be ASCII") from exc
    values = parse_text(text, contract, path=p)
    return MemhReadResult(path=p, contract=contract, values=values)


def write_memh(path: str | Path, values: Iterable[int], contract: MemhContract) -> None:
    """Write values using canonical memh serialization."""

    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(canonical_bytes(values, contract))


def validate_memh_file(path: str | Path, contract: MemhContract) -> None:
    """Raise ``MemhError`` if ``path`` violates ``contract``."""

    read_memh(path, contract)


def contract_for_kind(kind: str, *, rows: int | None = None) -> MemhContract:
    """Return the baseline contract for a known T-RECAP memh kind."""

    normalized = kind.strip().lower().replace("-", "_")
    if normalized in {"sample", "stream", "x", "x_in", "y", "y_out"}:
        return MemhContract(cfg.N, True, rows, normalized)
    if normalized in {"window", "window_qw"}:
        return MemhContract(cfg.W_Qw, False, rows if rows is not None else cfg.L, "window_qw")
    if normalized in {"twiddle", "twiddle_re", "twiddle_im", "twiddle_inv_re", "twiddle_inv_im"}:
        return MemhContract(cfg.W_tw, True, rows if rows is not None else cfg.L, normalized)
    raise MemhError(f"unknown memh kind: {kind!r}")


def infer_contract(path: str | Path, *, rows: int | None = None) -> MemhContract:
    """Infer a T-RECAP memh contract from a standard artifact file name."""

    p = Path(path)
    name = p.name
    stem = p.stem
    if name in {"x_in.memh", "y_out.memh"}:
        return contract_for_kind(stem, rows=rows)
    if name == "window_qw.memh":
        return contract_for_kind("window_qw", rows=rows)
    if name.startswith("twiddle") and name.endswith(".memh"):
        return contract_for_kind(stem, rows=rows)
    raise MemhError(f"cannot infer memh contract for {p}; pass an explicit MemhContract")


def numeric_summary(values: Sequence[int]) -> dict[str, int | str | None]:
    """Return deterministic integer summary fields for inspection tools/tests."""

    if not values:
        return {
            "rows": 0,
            "min": None,
            "max": None,
            "sum": "0",
            "sum_abs": "0",
            "sum_sq": "0",
            "zero_count": 0,
            "positive_count": 0,
            "negative_count": 0,
            "max_abs": 0,
        }
    return {
        "rows": len(values),
        "min": min(values),
        "max": max(values),
        "sum": str(sum(values)),
        "sum_abs": str(sum(abs(value) for value in values)),
        "sum_sq": str(sum(value * value for value in values)),
        "zero_count": sum(1 for value in values if value == 0),
        "positive_count": sum(1 for value in values if value > 0),
        "negative_count": sum(1 for value in values if value < 0),
        "max_abs": max(abs(value) for value in values),
    }


__all__ = [
    "MemhContract",
    "MemhError",
    "MemhReadResult",
    "canonical_bytes",
    "canonical_text",
    "contract_for_kind",
    "decode_token",
    "encode_value",
    "hex_digits",
    "infer_contract",
    "numeric_summary",
    "parse_text",
    "read_memh",
    "signed_bounds",
    "unsigned_bound",
    "validate_memh_file",
    "write_memh",
]
