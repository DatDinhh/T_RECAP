#!/usr/bin/env python3
"""Shared implementation helpers for the T-RECAP Phase 2 golden tools.

This module is intentionally local to tools/.  It keeps the command-line scripts
small while preserving one Python implementation of canonical memh encoding,
coefficient generation, vector generation, and artifact checks.
"""
from __future__ import annotations

import csv
import hashlib
import json
import math
import re
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable

_REPO_ROOT = Path(__file__).resolve().parents[1]
_PYTHON_DIR = _REPO_ROOT / "python"
if str(_PYTHON_DIR) not in sys.path:
    sys.path.insert(0, str(_PYTHON_DIR))

from trecap_golden.generators import GeneratorError as PackageGeneratorError
from trecap_golden.generators import generate_samples as package_generate_samples

N = 12
L = 256
P = 8
H = 128
F = 15
G = 128
D = L + G
PROTECT_DC = 1
PROTECT_NYQ = 0
W_QW = F + 1
W_TW = F + 2
W_U = N + F
W_FFT = W_U + 1
W_FFT_PRE = W_FFT + 1
W_CAN_PRE = W_FFT + 1
W_CAN = W_FFT
W_MAG2 = 2 * W_CAN
W_IFFT = W_CAN + P
W_Z = W_IFFT
W_OLA = W_Z + 1
UNIQUE_BINS = L // 2 + 1

SPEC_REVISION = "core_rev_j"
TELEMETRY_REVISION = "telemetry_rev_g"
GENERATOR_VERSION = "phase2_generators_revision_j"
VECTOR_BUNDLE_SCHEMA = "trecap_phase2_vector_bundle_v1"
GOLDEN_MODEL_VERSION = "trecap_golden_0.1.0"
ROUNDING_MODE = "round_nearest_ties_away_from_zero"
FFT_MODE = "custom_radix2_dit_bitrev_in_natural_out"
TAIL_POLICY = "full_tail"
MEMH_ENCODING = "fixed_width_lowercase_hex_lf"
HASH_RULE = "logical_integer_vector_fixed_width_hex_lf"
THRESHOLD_MAPPING = "raw_thr2"
ZERO_SHA256 = "0" * 64

FRAME_STATS_HEADER = [
    "frame_idx",
    "unique_bins",
    "unique_suppressed_bins",
    "eligible_unique_bins",
    "eligible_suppressed_bins",
    "eligible_kept_mag2",
    "eligible_total_mag2",
]
BIN_STATS_HEADER = ["frame_idx", "bin_idx", "real", "imag", "mag2", "eligible", "pre_mask", "mask"]


class ToolError(RuntimeError):
    """Controlled failure with a concise user-facing message."""


def utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def repo_root_from_tool(path: Path) -> Path:
    return path.resolve().parents[1]


def write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, sort_keys=False) + "\n", encoding="utf-8")


def read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ToolError(f"missing JSON file: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ToolError(f"invalid JSON in {path}: {exc}") from exc


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def hex_digits(width: int) -> int:
    if width <= 0 or width > 64:
        raise ToolError(f"unsupported memh width: {width}")
    return (width + 3) // 4


def signed_range(width: int) -> tuple[int, int]:
    return (-(1 << (width - 1)), (1 << (width - 1)) - 1)


def sat_signed(value: int, width: int = N) -> int:
    lo, hi = signed_range(width)
    return min(max(value, lo), hi)


def qcoef(value: float, frac_bits: int) -> int:
    if value == 0.0:
        return 0
    sign = 1 if value > 0 else -1
    return sign * int(abs(value) * float(1 << frac_bits) + 0.5)


def encode_unsigned_line(value: int, width: int) -> str:
    if value < 0 or value >= (1 << width):
        raise ToolError(f"unsigned memh value {value} does not fit in {width} bits")
    return f"{value:0{hex_digits(width)}x}"


def encode_signed_line(value: int, width: int) -> str:
    lo, hi = signed_range(width)
    if value < lo or value > hi:
        raise ToolError(f"signed memh value {value} does not fit in {width} bits")
    encoded = value & ((1 << width) - 1)
    return f"{encoded:0{hex_digits(width)}x}"


def decode_line(line: str, width: int, signed: bool) -> int:
    s = line.rstrip("\n")
    if not re.fullmatch(r"[0-9a-f]+", s):
        raise ToolError(f"noncanonical memh line: {s!r}")
    if len(s) != hex_digits(width):
        raise ToolError(f"memh line {s!r} has {len(s)} digits; expected {hex_digits(width)}")
    value = int(s, 16)
    if value >= (1 << width):
        raise ToolError(f"memh line {s!r} exceeds width {width}")
    if signed and (value & (1 << (width - 1))):
        value -= 1 << width
    return value


def canonical_memh(values: Iterable[int], width: int, signed: bool) -> str:
    enc = encode_signed_line if signed else encode_unsigned_line
    return "".join(enc(int(v), width) + "\n" for v in values)


def canonical_memh_hash(values: Iterable[int], width: int, signed: bool) -> str:
    return sha256_text(canonical_memh(values, width, signed))


def write_memh(path: Path, values: Iterable[int], width: int, signed: bool) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(canonical_memh(values, width, signed), encoding="ascii", newline="\n")


def read_memh(path: Path, width: int, signed: bool) -> list[int]:
    if not path.exists():
        raise ToolError(f"missing memh file: {path}")
    raw = path.read_bytes()
    if b"\r" in raw:
        raise ToolError(f"CRLF is not canonical memh: {path}")
    text = raw.decode("ascii")
    if text and not text.endswith("\n"):
        raise ToolError(f"memh file must end every value with LF: {path}")
    lines = text.splitlines()
    if any(line == "" for line in lines):
        raise ToolError(f"blank line found in memh file: {path}")
    return [decode_line(line, width, signed) for line in lines]


def full_tail_geometry(ns: int) -> dict[str, int]:
    if ns <= 0:
        raise ToolError("Revision J signoff vectors require Ns > 0")
    frames = (ns + L - 2) // H
    tau_last = frames * H
    ny = tau_last + G + L
    return {"Ns": ns, "Nframes": frames, "tau_last": tau_last, "Ny": ny}


def base_configuration(thr2: str | int = "0", ns: int | None = None) -> dict[str, Any]:
    cfg: dict[str, Any] = {
        "N": N,
        "L": L,
        "P": P,
        "H": H,
        "F": F,
        "G": G,
        "D": D,
        "THR2": str(thr2),
        "PROTECT_DC": PROTECT_DC,
        "PROTECT_NYQ": PROTECT_NYQ,
    }
    if ns is not None:
        geo = full_tail_geometry(ns)
        cfg.update({"Ns": geo["Ns"], "Ny": geo["Ny"], "frames": geo["Nframes"]})
    return cfg


def widths() -> dict[str, int]:
    return {
        "W_Qw": W_QW,
        "W_tw": W_TW,
        "W_u": W_U,
        "W_fft": W_FFT,
        "W_fft_pre": W_FFT_PRE,
        "W_can_pre": W_CAN_PRE,
        "W_can": W_CAN,
        "W_mag2": W_MAG2,
        "W_ifft": W_IFFT,
        "W_z": W_Z,
        "W_ola": W_OLA,
    }


def contract(include_hash_rule: bool = True) -> dict[str, str]:
    out = {
        "fft_mode": FFT_MODE,
        "rounding_mode": ROUNDING_MODE,
        "tail_policy": TAIL_POLICY,
        "threshold_mapping": THRESHOLD_MAPPING,
    }
    if include_hash_rule:
        out["memh_encoding"] = MEMH_ENCODING
        out["hash_rule"] = HASH_RULE
    return out


def coefficient_tables() -> dict[str, list[int]]:
    window: list[int] = []
    fwd_re: list[int] = []
    fwd_im: list[int] = []
    inv_re: list[int] = []
    inv_im: list[int] = []
    for i in range(L):
        hp = 0.5 - 0.5 * math.cos((2.0 * math.pi * i) / L)
        window.append(qcoef(math.sqrt(max(0.0, hp)), F))
        angle = (2.0 * math.pi * i) / L
        fwd_re.append(qcoef(math.cos(angle), F))
        fwd_im.append(qcoef(-math.sin(angle), F))
        inv_re.append(qcoef(math.cos(angle), F))
        inv_im.append(qcoef(math.sin(angle), F))
    return {
        "window_qw": window,
        "twiddle_re": fwd_re,
        "twiddle_im": fwd_im,
        "twiddle_inv_re": inv_re,
        "twiddle_inv_im": inv_im,
    }


def coefficient_hashes_from_tables(tables: dict[str, list[int]]) -> dict[str, str]:
    return {
        "window_qw_sha256": canonical_memh_hash(tables["window_qw"], W_QW, signed=False),
        "twiddle_re_sha256": canonical_memh_hash(tables["twiddle_re"], W_TW, signed=True),
        "twiddle_im_sha256": canonical_memh_hash(tables["twiddle_im"], W_TW, signed=True),
        "twiddle_inv_re_sha256": canonical_memh_hash(tables["twiddle_inv_re"], W_TW, signed=True),
        "twiddle_inv_im_sha256": canonical_memh_hash(tables["twiddle_inv_im"], W_TW, signed=True),
    }


def coefficient_hashes_from_artifacts(coeff_dir: Path) -> dict[str, str]:
    return {
        "window_qw_sha256": canonical_file_hash(coeff_dir / "window_qw.memh", W_QW, signed=False),
        "twiddle_re_sha256": canonical_file_hash(coeff_dir / "twiddle_re.memh", W_TW, signed=True),
        "twiddle_im_sha256": canonical_file_hash(coeff_dir / "twiddle_im.memh", W_TW, signed=True),
        "twiddle_inv_re_sha256": canonical_file_hash(coeff_dir / "twiddle_inv_re.memh", W_TW, signed=True),
        "twiddle_inv_im_sha256": canonical_file_hash(coeff_dir / "twiddle_inv_im.memh", W_TW, signed=True),
    }


def canonical_file_hash(path: Path, width: int, signed: bool) -> str:
    values = read_memh(path, width, signed)
    return canonical_memh_hash(values, width, signed)


def generated_source_hash(paths: Iterable[Path]) -> str:
    h = hashlib.sha256()
    for path in sorted(paths):
        h.update(path.name.encode("utf-8"))
        h.update(b"\0")
        h.update(path.read_bytes())
        h.update(b"\0")
    return h.hexdigest()


def validate_threshold(thr2: str | int) -> str:
    text = str(thr2)
    if not re.fullmatch(r"0|[1-9][0-9]*", text):
        raise ToolError(f"THR2 must be a canonical unsigned decimal string, got {text!r}")
    if int(text) >= (1 << W_MAG2):
        raise ToolError(f"THR2 out of W_mag2={W_MAG2} range: {text}")
    return text


def require_vector_name(name: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_\-]{0,95}", name):
        raise ToolError(f"invalid vector name: {name!r}")
    return name


@dataclass(frozen=True)
class VectorSpec:
    name: str
    ns: int
    generator: str
    parameters: dict[str, Any]
    thr2: str = "0"
    protect_dc: int = PROTECT_DC
    protect_nyq: int = PROTECT_NYQ
    tail_policy: str = TAIL_POLICY
    rounding: str = ROUNDING_MODE
    requires_bin_stats: bool = False
    description: str = ""


def default_vector_specs() -> list[VectorSpec]:
    return [
        VectorSpec(
            name="zero_Ns4096_thr0",
            ns=4096,
            generator="constant",
            parameters={"value": 0},
            description="Zero input, THR2=0, baseline smoke/signoff vector.",
        ),
        VectorSpec(
            name="impulse_Ns1024_thr0",
            ns=1024,
            generator="impulse",
            parameters={"index": 7, "amplitude": 1536},
            description="Impulse startup/flush/delay alignment vector.",
        ),
        VectorSpec(
            name="near_threshold_multitone_Ns1024_thr64",
            ns=1024,
            generator="multitone_sine_sum",
            parameters={
                "tones": [
                    {"amplitude": 512, "f_num": 16, "f_den": 256, "phase_rad": "0"},
                    {"amplitude": 128, "f_num": 23, "f_den": 256, "phase_rad": "0.5"},
                ]
            },
            thr2=str(64 * 64),
            requires_bin_stats=True,
            description="Near-threshold multitone with bin_stats enabled.",
        ),
    ]


def _vector_config_items_from_file(path: Path) -> list[dict[str, Any]]:
    """Load one reviewed vector-config file.

    A config file may contain a single legacy vector object or a reviewed
    ``trecap_phase2_vector_bundle_v1`` object with a ``vectors`` list. Suite
    files intentionally use ``vector_selection`` instead of ``vectors`` and are
    rejected here so a suite cannot be mistaken for generator input.
    """

    obj = read_json(path)
    if obj.get("schema") == "trecap_phase2_suite_config_v1" or "vector_selection" in obj:
        raise ToolError(f"{path} is a suite selector, not a vector-config bundle")
    if "vectors" not in obj:
        return [obj]

    if obj.get("schema") != VECTOR_BUNDLE_SCHEMA:
        raise ToolError(
            f"{path} has a vectors list but schema {obj.get('schema')!r}; "
            f"expected {VECTOR_BUNDLE_SCHEMA!r}"
        )
    if obj.get("bundle_name") != path.stem:
        raise ToolError(f"{path}: bundle_name must equal file stem {path.stem!r}")
    items = obj.get("vectors")
    if not isinstance(items, list) or not items:
        raise ToolError(f"{path} must contain a nonempty vectors list")
    return [dict(item) for item in items]


def load_vector_specs(configs: Path) -> list[VectorSpec]:
    """Load reviewed vector configs from one file or a directory."""

    paths: list[Path]
    if configs.is_file():
        paths = [configs]
    else:
        paths = sorted(configs.glob("*.json")) if configs.exists() else []
    if not paths:
        return default_vector_specs()
    specs: list[VectorSpec] = []
    source_by_name: dict[str, Path] = {}
    for path in paths:
        for item in _vector_config_items_from_file(path):
            spec = vector_spec_from_mapping(item)
            if spec.name in source_by_name:
                raise ToolError(
                    f"duplicate vector config {spec.name!r} in {path}; "
                    f"first seen in {source_by_name[spec.name]}"
                )
            source_by_name[spec.name] = path
            specs.append(spec)
    return specs

def vector_spec_from_mapping(item: dict[str, Any]) -> VectorSpec:
    name = require_vector_name(str(item["name"]))
    ns = int(item.get("Ns", item.get("ns")))
    if ns <= 0:
        raise ToolError(f"vector {name}: Ns must be positive")
    generator = str(item["generator"])
    params = dict(item.get("parameters", {}))
    return VectorSpec(
        name=name,
        ns=ns,
        generator=generator,
        parameters=params,
        thr2=validate_threshold(item.get("THR2", item.get("thr2", "0"))),
        protect_dc=int(item.get("PROTECT_DC", item.get("protect_dc", PROTECT_DC))),
        protect_nyq=int(item.get("PROTECT_NYQ", item.get("protect_nyq", PROTECT_NYQ))),
        tail_policy=str(item.get("tail_policy", TAIL_POLICY)),
        rounding=str(item.get("rounding", ROUNDING_MODE)),
        requires_bin_stats=bool(item.get("requires_bin_stats", False)),
        description=str(item.get("description", "")),
    )




def load_suite_vector_names(suite: Path) -> list[str]:
    """Return vector names selected by a suite config.

    Suite files deliberately use ``vector_selection`` instead of ``vectors`` so
    they cannot be mistaken for a vector-config bundle by ``load_vector_specs``.
    """

    obj = read_json(suite)
    if obj.get("schema") != "trecap_phase2_suite_config_v1":
        raise ToolError(f"suite {suite} has unsupported schema: {obj.get('schema')!r}")
    selection = obj.get("vector_selection")
    if not isinstance(selection, list) or not selection:
        raise ToolError(f"suite {suite} must contain a nonempty vector_selection list")
    names: list[str] = []
    for index, item in enumerate(selection):
        if not isinstance(item, dict) or "name" not in item:
            raise ToolError(f"suite {suite}: vector_selection[{index}] missing name")
        names.append(require_vector_name(str(item["name"])))
    seen: set[str] = set()
    duplicates: list[str] = []
    for name in names:
        if name in seen and name not in duplicates:
            duplicates.append(name)
        seen.add(name)
    if duplicates:
        raise ToolError(f"suite {suite} contains duplicate vector names: {', '.join(duplicates)}")
    return names


def filter_specs_by_suite(specs: list[VectorSpec], suite: Path) -> list[VectorSpec]:
    """Filter vector specs to the suite order, failing on dangling references."""

    wanted = load_suite_vector_names(suite)
    by_name = {spec.name: spec for spec in specs}
    missing = [name for name in wanted if name not in by_name]
    if missing:
        raise ToolError(f"suite {suite} references missing vector config(s): {', '.join(missing)}")
    return [by_name[name] for name in wanted]

def generate_vector(spec: VectorSpec) -> list[int]:
    """Generate samples through the public Python generator package.

    The command-line tools and importable Python package must not drift.  This
    wrapper preserves the existing ``VectorSpec`` interface while delegating the
    actual generator equations to ``trecap_golden.generators``.
    """

    try:
        return list(package_generate_samples(spec.generator, spec.ns, spec.parameters, sample_width=N))
    except (PackageGeneratorError, KeyError, TypeError, ValueError) as exc:
        raise ToolError(f"vector {spec.name}: {exc}") from exc

def vector_manifest_item(spec: VectorSpec, x_hash: str, y_hash: str = ZERO_SHA256) -> dict[str, Any]:
    out: dict[str, Any] = {
        "name": spec.name,
        "description": spec.description,
        "Ns": spec.ns,
        "generator": spec.generator,
        "parameters": spec.parameters,
        "THR2": spec.thr2,
        "PROTECT_DC": spec.protect_dc,
        "PROTECT_NYQ": spec.protect_nyq,
        "tail_policy": spec.tail_policy,
        "rounding": spec.rounding,
        "requires_bin_stats": spec.requires_bin_stats,
        "x_in_sha256": x_hash,
        "y_out_sha256": y_hash,
    }
    if not spec.requires_bin_stats:
        out.pop("requires_bin_stats")
    if not spec.description:
        out.pop("description")
    return out


def vector_config_draft(spec: VectorSpec, x_hash: str, coeff_hashes: dict[str, str]) -> dict[str, Any]:
    geo = full_tail_geometry(spec.ns)
    rows: dict[str, int] = {
        "window_qw": L,
        "twiddle_re": L,
        "twiddle_im": L,
        "twiddle_inv_re": L,
        "twiddle_inv_im": L,
        "x_in": spec.ns,
        "y_out": geo["Ny"],
        "frame_stats_data_rows": geo["Nframes"],
    }
    if spec.requires_bin_stats:
        rows["bin_stats_data_rows"] = geo["Nframes"] * UNIQUE_BINS
    return {
        "schema": "trecap_phase2_vector_config_v1",
        "vector_name": spec.name,
        "configuration": base_configuration(spec.thr2, spec.ns),
        "contract": contract(True),
        "widths": widths(),
        "hashes": coeff_hashes,
        "stream_hashes": {"x_in_sha256": x_hash, "y_out_sha256": ZERO_SHA256},
        "artifact_rows": rows,
        "generator": {
            "name": spec.generator,
            "parameters": spec.parameters,
            "generator_version": GENERATOR_VERSION,
            "status": "input_generated_y_pending",
        },
    }


def csv_row_count(path: Path, expected_header: list[str]) -> int:
    if not path.exists():
        raise ToolError(f"missing CSV file: {path}")
    raw = path.read_bytes()
    if b"\r" in raw:
        raise ToolError(f"CSV file uses CRLF, not canonical LF: {path}")
    rows = list(csv.reader(raw.decode("utf-8").splitlines()))
    if not rows:
        raise ToolError(f"CSV file is empty: {path}")
    if rows[0] != expected_header:
        raise ToolError(f"CSV header mismatch for {path}: got {rows[0]!r}")
    for idx, row in enumerate(rows[1:], start=2):
        if not row:
            raise ToolError(f"blank CSV row {idx} in {path}")
    return len(rows) - 1


def run_checked(argv: list[str]) -> None:
    import subprocess

    proc = subprocess.run(argv, text=True)
    if proc.returncode != 0:
        raise ToolError(f"command failed with exit code {proc.returncode}: {' '.join(argv)}")


def main_wrapper(fn: Any) -> None:
    try:
        raise SystemExit(fn())
    except ToolError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
