#!/usr/bin/env python3
"""Fail-closed preparation and post-checking for the Cut-C0 RTL scoreboard.

The SystemVerilog testbench compares live RTL events against frozen stream and
CSV artifacts.  This tool handles the parts that are deliberately kept out of
the simulator: strict JSON parsing, duplicate-key rejection, canonical file
format checks, SHA-256 provenance, cross-artifact consistency, and final
byte-for-byte capture comparison.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import tempfile
from pathlib import Path, PurePosixPath
from typing import Any, Iterable


FRAME_HEADER = (
    "frame_idx,unique_bins,unique_suppressed_bins,eligible_unique_bins,"
    "eligible_suppressed_bins,eligible_kept_mag2,eligible_total_mag2"
)
BIN_HEADER = "frame_idx,bin_idx,real,imag,mag2,eligible,pre_mask,mask"

METRICS_TOP_KEYS = {
    "schema",
    "vector_name",
    "configuration",
    "contract",
    "widths",
    "hashes",
    "stream_hashes",
    "suppression_totals",
    "spectral_totals",
    "time_domain_errors",
}
CONFIG_KEYS = {
    "N",
    "L",
    "P",
    "H",
    "F",
    "G",
    "D",
    "Ns",
    "Ny",
    "frames",
    "THR2",
    "PROTECT_DC",
    "PROTECT_NYQ",
}
CONTRACT_KEYS = {
    "fft_mode",
    "rounding_mode",
    "tail_policy",
    "threshold_mapping",
    "memh_encoding",
    "hash_rule",
}
WIDTH_KEYS = {
    "W_Qw",
    "W_tw",
    "W_u",
    "W_fft",
    "W_fft_pre",
    "W_can_pre",
    "W_can",
    "W_mag2",
    "W_ifft",
    "W_z",
    "W_ola",
}
HASH_KEYS = {
    "window_qw_sha256",
    "twiddle_re_sha256",
    "twiddle_im_sha256",
    "twiddle_inv_re_sha256",
    "twiddle_inv_im_sha256",
}
SUPPRESSION_KEYS = {
    "unique_bins",
    "unique_suppressed_bins",
    "eligible_unique_bins",
    "eligible_suppressed_bins",
}
SPECTRAL_KEYS = {"eligible_kept_mag2", "eligible_total_mag2"}
TIME_KEYS = {"sum_abs_err", "sum_sq_err", "max_abs_err", "error_sample_count"}

UNSIGNED_DECIMAL = re.compile(r"^(0|[1-9][0-9]*)$")
SIGNED_DECIMAL = re.compile(r"^-?(0|[1-9][0-9]*)$")
LOWER_HEX_64 = re.compile(r"^[0-9a-f]{64}$")
REFERENCE_IMPORT_MANIFEST_SHA256 = (
    "baf53cb537e8024370a41ee4d078c7de25272a8d7339eb2dbffabb165d8b9bef"
)
REFERENCE_PROXY_ID = "phase2-revJ-v69-lf-derived-embedded-proxy"


class ContractError(RuntimeError):
    """Raised when any frozen or observed artifact violates its contract."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ContractError(message)


def exact_keys(value: Any, expected: set[str], label: str) -> dict[str, Any]:
    require(isinstance(value, dict), f"{label}: expected JSON object")
    actual = set(value)
    require(
        actual == expected,
        f"{label}: key mismatch; missing={sorted(expected - actual)} "
        f"extra={sorted(actual - expected)}",
    )
    return value


def no_duplicate_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ContractError(f"JSON duplicate key: {key}")
        result[key] = value
    return result


def reject_nonfinite_json(token: str) -> None:
    raise ContractError(f"JSON non-finite numeric constant is forbidden: {token}")


def read_json(path: Path) -> dict[str, Any]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ContractError(f"cannot read JSON {path}: {exc}") from exc
    try:
        value = json.loads(
            text,
            object_pairs_hook=no_duplicate_object,
            parse_constant=reject_nonfinite_json,
        )
    except (json.JSONDecodeError, UnicodeError) as exc:
        raise ContractError(f"invalid JSON {path}: {exc}") from exc
    require(isinstance(value, dict), f"{path}: top-level JSON value must be an object")
    return value


def canonical_ascii_lines(path: Path, *, exact_header: str | None = None) -> list[str]:
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise ContractError(f"cannot read artifact {path}: {exc}") from exc
    require(data, f"{path}: file is empty")
    require(not data.startswith(b"\xef\xbb\xbf"), f"{path}: UTF-8 BOM is forbidden")
    require(data.endswith(b"\n"), f"{path}: final LF is required")
    require(b"\r" not in data, f"{path}: CR/CRLF is not canonical")
    try:
        text = data.decode("ascii")
    except UnicodeDecodeError as exc:
        raise ContractError(f"{path}: artifact must be ASCII") from exc
    lines = text[:-1].split("\n")
    require(all(line != "" for line in lines), f"{path}: blank lines are forbidden")
    if exact_header is not None:
        require(lines[0] == exact_header, f"{path}: exact header mismatch")
    return lines


def decimal(value: Any, label: str, *, signed: bool = False) -> int:
    require(isinstance(value, str), f"{label}: expected quoted decimal string")
    pattern = SIGNED_DECIMAL if signed else UNSIGNED_DECIMAL
    require(pattern.fullmatch(value) is not None, f"{label}: non-canonical decimal {value!r}")
    return int(value, 10)


def integer(value: Any, label: str, *, minimum: int | None = None) -> int:
    require(isinstance(value, int) and not isinstance(value, bool), f"{label}: expected integer")
    if minimum is not None:
        require(value >= minimum, f"{label}: value {value} is below {minimum}")
    return value


def sha256_bytes(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as exc:
        raise ContractError(f"cannot hash {path}: {exc}") from exc


def verified_repo_file(repo: Path, relative: Any, label: str) -> Path:
    require(isinstance(relative, str) and relative, f"{label}: invalid path")
    require(
        "\\" not in relative and "\x00" not in relative,
        f"{label}: backslash/NUL is forbidden",
    )
    pure = PurePosixPath(relative)
    require(
        not pure.is_absolute()
        and pure.parts
        and all(part not in {"", ".", ".."} for part in pure.parts),
        f"{label}: unsafe repository-relative path {relative!r}",
    )
    require(
        pure.as_posix() == relative,
        f"{label}: path is not canonical POSIX form: {relative!r}",
    )
    current = repo
    for part in pure.parts:
        current = current / part
        require(not current.is_symlink(), f"{label}: symlink is forbidden: {relative}")
    require(current.is_file(), f"{label}: missing regular file: {relative}")
    try:
        current.resolve(strict=True).relative_to(repo.resolve(strict=True))
    except (OSError, ValueError) as exc:
        raise ContractError(f"{label}: path escapes repository: {relative}: {exc}") from exc
    return current


def import_tree_sha256(records: list[dict[str, Any]]) -> str:
    digest = hashlib.sha256()
    digest.update(b"TRECAP_REFERENCE_IMPORT_TREE_V1\0")
    for record in sorted(records, key=lambda item: item["path"]):
        path_bytes = record["path"].encode("utf-8")
        digest.update(len(path_bytes).to_bytes(4, "big"))
        digest.update(path_bytes)
        digest.update(record["size_bytes"].to_bytes(8, "big"))
        digest.update(bytes.fromhex(record["sha256"]))
    return digest.hexdigest()


def canonical_json_sha256(path: Path) -> str:
    value = read_json(path)
    payload = (
        json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("ascii")
        + b"\n"
    )
    return hashlib.sha256(payload).hexdigest()


def verify_generated_manifest(repo: Path) -> None:
    path = repo / "spec" / "generated" / "gen_manifest.json"
    manifest = read_json(path)
    require(
        manifest.get("schema") == "trecap_phase2_gen_manifest_v1",
        f"{path}: schema mismatch",
    )
    for section in ("source_files", "output_files"):
        entries = manifest.get(section)
        require(isinstance(entries, list) and entries, f"{path}:{section} must be nonempty")
        seen: set[str] = set()
        for ordinal, entry in enumerate(entries):
            require(isinstance(entry, dict), f"{path}:{section}[{ordinal}] must be an object")
            require(
                set(entry) == {"path", "sha256"},
                f"{path}:{section}[{ordinal}] key mismatch",
            )
            relative = entry["path"]
            expected_hash = entry["sha256"]
            require(isinstance(relative, str), f"{path}:{section}[{ordinal}].path")
            relative_path = Path(relative)
            require(
                not relative_path.is_absolute() and ".." not in relative_path.parts,
                f"{path}:{section}[{ordinal}] unsafe path",
            )
            require(relative not in seen, f"{path}:{section} duplicate path {relative}")
            seen.add(relative)
            require(
                isinstance(expected_hash, str)
                and LOWER_HEX_64.fullmatch(expected_hash) is not None,
                f"{path}:{section}[{ordinal}] invalid SHA-256",
            )
            require(
                sha256_bytes(repo / relative_path) == expected_hash,
                f"{path}:{section}[{ordinal}] hash mismatch for {relative}",
            )


def verify_reference_import_manifest(repo: Path) -> dict[str, str]:
    path = repo / "artifacts" / "manifests" / "reference_import_manifest.json"
    require(
        sha256_bytes(path) == REFERENCE_IMPORT_MANIFEST_SHA256,
        f"{path}: import manifest is not the pinned v69 authority",
    )
    manifest = read_json(path)
    exact_keys(
        manifest,
        {
            "excluded_member_count",
            "excluded_members",
            "file_class",
            "import_policy",
            "imported_reference_file_count",
            "imported_reference_files",
            "imported_tree_sha256",
            "project",
            "promoted_root_file_count",
            "promoted_root_files",
            "promoted_tree_sha256",
            "promotion_map_sha256",
            "provenance_status",
            "reference_root",
            "schema",
            "source",
        },
        f"{path}:top",
    )
    require(
        manifest.get("schema") == "trecap_phase2_reference_import_manifest_v3",
        f"{path}: schema mismatch",
    )
    require(manifest["project"] == "T_RECAP_Phase2", f"{path}: project mismatch")
    require(manifest["reference_root"] == "sw/reference_model", f"{path}: reference root mismatch")
    require(
        manifest["provenance_status"]
        == "embedded_proxy_unverified_source_archive",
        f"{path}: this derivative must not claim verified source-archive provenance",
    )
    require(
        manifest["source"]
        == {
            "kind": "embedded_proxy",
            "proxy_id": REFERENCE_PROXY_ID,
            "verified": False,
        },
        f"{path}: embedded-proxy source record mismatch",
    )
    internal_manifest = repo / "sw" / "reference_model" / "import_manifest.json"
    require(
        path.read_bytes() == internal_manifest.read_bytes(),
        f"{path}: internal import manifest is not byte-identical",
    )
    require(
        manifest["excluded_member_count"] == 0
        and manifest["excluded_members"] == [],
        f"{path}: release package must not carry excluded cache/build members",
    )

    promotion_map_path = repo / "config" / "reference_import_promotions.json"
    promotion_map = read_json(promotion_map_path)
    exact_keys(promotion_map, {"schema", "promotions"}, f"{promotion_map_path}:top")
    require(
        promotion_map["schema"] == "trecap_phase2_reference_promotion_map_v1",
        f"{promotion_map_path}: schema mismatch",
    )
    require(
        canonical_json_sha256(promotion_map_path) == manifest["promotion_map_sha256"],
        f"{path}: promotion-map hash mismatch",
    )

    imported = manifest.get("imported_reference_files")
    imported_count = manifest.get("imported_reference_file_count")
    require(isinstance(imported, list), f"{path}: imported_reference_files must be an array")
    require(
        isinstance(imported_count, int)
        and not isinstance(imported_count, bool)
        and imported_count == len(imported),
        f"{path}: imported reference file count mismatch",
    )
    imported_by_path: dict[str, dict[str, Any]] = {}
    for ordinal, entry in enumerate(imported):
        require(isinstance(entry, dict), f"{path}:imported_reference_files[{ordinal}]")
        require(
            set(entry)
            == {
                "archive_member",
                "archive_member_raw",
                "class",
                "crc32",
                "origin",
                "path",
                "sha256",
                "size_bytes",
            },
            f"{path}:imported_reference_files[{ordinal}] key mismatch",
        )
        relative = entry["path"]
        require(relative not in imported_by_path, f"{path}: duplicate imported path {relative}")
        require(
            entry["archive_member"] is None
            and entry["archive_member_raw"] is None
            and entry["crc32"] is None
            and entry["origin"] == "embedded_proxy"
            and entry["class"] == "[0]",
            f"{path}:{relative}: proxy metadata mismatch",
        )
        require(
            isinstance(entry["sha256"], str)
            and LOWER_HEX_64.fullmatch(entry["sha256"]) is not None,
            f"{path}:{relative}: invalid SHA-256",
        )
        require(
            isinstance(entry["size_bytes"], int)
            and not isinstance(entry["size_bytes"], bool)
            and entry["size_bytes"] >= 0,
            f"{path}:{relative}: invalid size",
        )
        imported_path = verified_repo_file(repo, relative, f"{path}:{relative}")
        require(
            imported_path.stat().st_size == entry["size_bytes"],
            f"{path}:{relative}: size mismatch",
        )
        require(
            sha256_bytes(imported_path) == entry["sha256"],
            f"{path}:{relative}: hash mismatch",
        )
        imported_by_path[relative] = entry
    reference_root = repo / "sw" / "reference_model"
    expected_imported = {
        item.relative_to(repo).as_posix()
        for item in reference_root.rglob("*")
        if item.is_file()
        and not item.is_symlink()
        and item.name != "import_manifest.json"
        and not any(
            part
            in {
                ".pytest_cache",
                ".ruff_cache",
                ".venv",
                "__pycache__",
                "build",
                "legacy",
                "out",
                "runs",
            }
            for part in item.relative_to(reference_root).parts
        )
    }
    require(
        set(imported_by_path) == expected_imported,
        f"{path}: incomplete embedded reference inventory",
    )
    require(
        import_tree_sha256(imported) == manifest["imported_tree_sha256"],
        f"{path}: imported tree digest mismatch",
    )

    entries = manifest.get("promoted_root_files")
    declared_count = manifest.get("promoted_root_file_count")
    require(isinstance(entries, list), f"{path}: promoted_root_files must be an array")
    require(
        isinstance(declared_count, int)
        and not isinstance(declared_count, bool)
        and declared_count == len(entries),
        f"{path}: promoted root file count mismatch",
    )
    result: dict[str, str] = {}
    observed_map: set[tuple[str, str]] = set()
    for ordinal, entry in enumerate(entries):
        require(isinstance(entry, dict), f"{path}:promoted_root_files[{ordinal}]")
        require(
            set(entry)
            == {"class", "operation", "path", "sha256", "size_bytes", "source_path"},
            f"{path}:promoted_root_files[{ordinal}] key mismatch",
        )
        relative = entry["path"]
        source_relative = entry["source_path"]
        expected_hash = entry["sha256"]
        expected_size = entry["size_bytes"]
        require(entry["class"] == "[0]", f"{path}:{relative}: class mismatch")
        require(entry["operation"] == "verbatim_copy", f"{path}:{relative}: operation mismatch")
        require(relative not in result, f"{path}: duplicate promoted path {relative}")
        require(
            isinstance(expected_hash, str)
            and LOWER_HEX_64.fullmatch(expected_hash) is not None,
            f"{path}:{relative} invalid SHA-256",
        )
        require(
            isinstance(expected_size, int)
            and not isinstance(expected_size, bool)
            and expected_size >= 0,
            f"{path}:{relative} invalid size",
        )
        source_path = verified_repo_file(repo, source_relative, f"{path}:{source_relative}")
        promoted_path = verified_repo_file(repo, relative, f"{path}:{relative}")
        actual_size = promoted_path.stat().st_size
        require(actual_size == expected_size, f"{path}:{relative} size mismatch")
        require(sha256_bytes(promoted_path) == expected_hash, f"{path}:{relative} hash mismatch")
        require(sha256_bytes(source_path) == expected_hash, f"{path}:{relative} source mismatch")
        require(
            source_relative in imported_by_path
            and imported_by_path[source_relative]["sha256"] == expected_hash,
            f"{path}:{relative} is not authenticated by the imported tree",
        )
        observed_map.add((source_relative.removeprefix("sw/reference_model/"), relative))
        result[relative] = expected_hash
    mapped = promotion_map["promotions"]
    require(isinstance(mapped, list), f"{promotion_map_path}: promotions must be an array")
    expected_map = {
        (row["source_path"], row["destination_path"])
        for row in mapped
        if isinstance(row, dict)
        and set(row) == {"source_path", "destination_path"}
    }
    require(len(expected_map) == len(mapped), f"{promotion_map_path}: invalid/duplicate row")
    require(observed_map == expected_map, f"{path}: incomplete promotion inventory")
    require(
        import_tree_sha256(entries) == manifest["promoted_tree_sha256"],
        f"{path}: promoted tree digest mismatch",
    )
    return result


def compile_input_hashes(repo: Path) -> dict[str, str]:
    filelists = (
        "filelists/rtl_core_plus_fft.f",
        "sim/filelists/c0_mag2_width.f",
        "sim/filelists/c0_v67_regression.f",
        "sim/filelists/c0_golden.f",
        "sim/filelists/c0_delay_history.f",
    )
    result: dict[str, str] = {}
    source_paths: set[str] = set()
    for relative in filelists:
        path = repo / relative
        try:
            data = path.read_bytes()
        except OSError as exc:
            raise ContractError(f"cannot read compile filelist {path}: {exc}") from exc
        require(data.endswith(b"\n"), f"{path}: final LF is required")
        require(b"\r" not in data, f"{path}: CR/CRLF is not canonical")
        try:
            lines = data.decode("ascii").splitlines()
        except UnicodeDecodeError as exc:
            raise ContractError(f"{path}: filelist must be ASCII") from exc
        result[f"filelist:{relative}"] = sha256_bytes(path)
        for line in lines:
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or stripped.startswith("+incdir+"):
                continue
            source_path = Path(stripped)
            require(
                not source_path.is_absolute() and ".." not in source_path.parts,
                f"{path}: unsafe source path {stripped}",
            )
            source_paths.add(stripped)
    for relative in sorted(source_paths):
        result[f"compile:{relative}"] = sha256_bytes(repo / relative)
    for relative in (
        "scripts/sim/trecap_artifact_scoreboard.py",
        "scripts/sim/check_c0_flow_control_model.py",
        "scripts/sim/check_c0_active_tail_model.py",
        "scripts/sim/check_c0_exact_completion_model.py",
        "scripts/sim/check_c0_delay_history_model.py",
        "scripts/sim/check_c0_native_runner_closure.py",
        "scripts/windows/run_c0_golden_v70.ps1",
    ):
        result[f"tool:{relative}"] = sha256_bytes(repo / relative)
    return result


def parse_memh(path: Path, *, width: int, rows: int) -> tuple[list[int], str]:
    lines = canonical_ascii_lines(path)
    digits = (width + 3) // 4
    pattern = re.compile(rf"^[0-9a-f]{{{digits}}}$")
    require(len(lines) == rows, f"{path}: rows={len(lines)} expected={rows}")
    values: list[int] = []
    mask = (1 << width) - 1
    sign = 1 << (width - 1)
    for index, line in enumerate(lines):
        require(pattern.fullmatch(line) is not None, f"{path}:{index + 1}: invalid memh row")
        raw = int(line, 16)
        require((raw & ~mask) == 0, f"{path}:{index + 1}: value exceeds {width} bits")
        values.append(raw - (1 << width) if raw & sign else raw)
    return values, sha256_bytes(path)


def parse_unsigned_cell(text: str, label: str) -> int:
    require(UNSIGNED_DECIMAL.fullmatch(text) is not None, f"{label}: invalid unsigned decimal")
    return int(text, 10)


def parse_signed_cell(text: str, label: str) -> int:
    require(SIGNED_DECIMAL.fullmatch(text) is not None, f"{label}: invalid signed decimal")
    return int(text, 10)


def parse_frame_stats(path: Path, *, rows: int) -> list[dict[str, int]]:
    lines = canonical_ascii_lines(path, exact_header=FRAME_HEADER)
    data_lines = lines[1:]
    require(len(data_lines) == rows, f"{path}: data rows={len(data_lines)} expected={rows}")
    names = FRAME_HEADER.split(",")
    result: list[dict[str, int]] = []
    for row_index, line in enumerate(data_lines):
        cells = line.split(",")
        require(len(cells) == len(names), f"{path}:{row_index + 2}: expected seven cells")
        row = {
            name: parse_unsigned_cell(cell, f"{path}:{row_index + 2}:{name}")
            for name, cell in zip(names, cells, strict=True)
        }
        require(row["frame_idx"] == row_index, f"{path}:{row_index + 2}: frame order mismatch")
        require(row["eligible_unique_bins"] <= row["unique_bins"], f"{path}:{row_index + 2}: eligibility count overflow")
        require(row["unique_suppressed_bins"] <= row["unique_bins"], f"{path}:{row_index + 2}: suppression count overflow")
        require(
            row["eligible_suppressed_bins"] <= row["eligible_unique_bins"],
            f"{path}:{row_index + 2}: eligible suppression count overflow",
        )
        require(
            row["eligible_kept_mag2"] <= row["eligible_total_mag2"],
            f"{path}:{row_index + 2}: kept energy exceeds total",
        )
        result.append(row)
    return result


def parse_bin_stats(
    path: Path,
    *,
    frames: int,
    unique_bins: int,
    can_width: int,
    thr2: int,
    protect_dc: int,
    protect_nyq: int,
) -> list[dict[str, int]]:
    lines = canonical_ascii_lines(path, exact_header=BIN_HEADER)
    expected_rows = frames * unique_bins
    data_lines = lines[1:]
    require(
        len(data_lines) == expected_rows,
        f"{path}: data rows={len(data_lines)} expected={expected_rows}",
    )
    names = BIN_HEADER.split(",")
    signed_names = {"real", "imag"}
    result: list[dict[str, int]] = []
    lower = -(1 << (can_width - 1))
    upper = (1 << (can_width - 1)) - 1
    for ordinal, line in enumerate(data_lines):
        cells = line.split(",")
        require(len(cells) == len(names), f"{path}:{ordinal + 2}: expected eight cells")
        row: dict[str, int] = {}
        for name, cell in zip(names, cells, strict=True):
            parser = parse_signed_cell if name in signed_names else parse_unsigned_cell
            row[name] = parser(cell, f"{path}:{ordinal + 2}:{name}")
        frame = ordinal // unique_bins
        bin_index = ordinal % unique_bins
        require(row["frame_idx"] == frame, f"{path}:{ordinal + 2}: frame order mismatch")
        require(row["bin_idx"] == bin_index, f"{path}:{ordinal + 2}: bin order mismatch")
        require(lower <= row["real"] <= upper, f"{path}:{ordinal + 2}: real exceeds W_can")
        require(lower <= row["imag"] <= upper, f"{path}:{ordinal + 2}: imag exceeds W_can")
        require(row["mag2"] == row["real"] ** 2 + row["imag"] ** 2, f"{path}:{ordinal + 2}: mag2 mismatch")
        if bin_index in {0, unique_bins - 1}:
            require(row["imag"] == 0, f"{path}:{ordinal + 2}: self-conjugate imag must be zero")
        protected = (bin_index == 0 and protect_dc == 1) or (
            bin_index == unique_bins - 1 and protect_nyq == 1
        )
        expected_eligible = 0 if protected else 1
        expected_pre_mask = int(row["mag2"] < thr2)
        expected_mask = expected_eligible & expected_pre_mask
        require(row["eligible"] == expected_eligible, f"{path}:{ordinal + 2}: eligibility mismatch")
        require(row["pre_mask"] == expected_pre_mask, f"{path}:{ordinal + 2}: pre_mask mismatch")
        require(row["mask"] == expected_mask, f"{path}:{ordinal + 2}: final mask mismatch")
        result.append(row)
    return result


def sum_frame_metrics(rows: Iterable[dict[str, int]]) -> dict[str, int]:
    rows_list = list(rows)
    return {
        key: sum(row[key] for row in rows_list)
        for key in sorted(SUPPRESSION_KEYS | SPECTRAL_KEYS)
    }


def frame_metrics_from_bins(
    rows: list[dict[str, int]], *, frames: int, unique_bins: int
) -> list[dict[str, int]]:
    result: list[dict[str, int]] = []
    for frame in range(frames):
        subset = rows[frame * unique_bins : (frame + 1) * unique_bins]
        result.append(
            {
                "frame_idx": frame,
                "unique_bins": len(subset),
                "unique_suppressed_bins": sum(row["mask"] for row in subset),
                "eligible_unique_bins": sum(row["eligible"] for row in subset),
                "eligible_suppressed_bins": sum(
                    row["eligible"] & row["mask"] for row in subset
                ),
                "eligible_kept_mag2": sum(
                    (1 if row["bin_idx"] in {0, unique_bins - 1} else 2)
                    * row["mag2"]
                    for row in subset
                    if row["eligible"] and not row["mask"]
                ),
                "eligible_total_mag2": sum(
                    (1 if row["bin_idx"] in {0, unique_bins - 1} else 2)
                    * row["mag2"]
                    for row in subset
                    if row["eligible"]
                ),
            }
        )
    return result


def time_metrics(x_values: list[int], y_values: list[int], *, delay: int) -> dict[str, int]:
    errors: list[int] = []
    for index, y_value in enumerate(y_values):
        source_index = index - delay
        x_delayed = x_values[source_index] if 0 <= source_index < len(x_values) else 0
        errors.append(x_delayed - y_value)
    absolute = [abs(value) for value in errors]
    return {
        "sum_abs_err": sum(absolute),
        "sum_sq_err": sum(value * value for value in errors),
        "max_abs_err": max(absolute, default=0),
        "error_sample_count": len(errors),
    }


def first_line_difference(left: Path, right: Path) -> str:
    left_lines = left.read_bytes().splitlines()
    right_lines = right.read_bytes().splitlines()
    for index, (lhs, rhs) in enumerate(zip(left_lines, right_lines, strict=False), start=1):
        if lhs != rhs:
            return f"line {index}: observed={lhs!r} golden={rhs!r}"
    return f"line count observed={len(left_lines)} golden={len(right_lines)}"


def validate_case(repo: Path, vector: str, *, require_bin_stats: bool) -> dict[str, Any]:
    verify_generated_manifest(repo)
    promoted_hashes = verify_reference_import_manifest(repo)
    vector_dir = repo / "artifacts" / "test_vectors" / vector
    golden_dir = repo / "artifacts" / "reference_outputs" / vector
    config_path = vector_dir / "config.json"
    metrics_path = golden_dir / "metrics.json"
    x_path = vector_dir / "x_in.memh"
    y_path = golden_dir / "y_out.memh"
    frame_path = golden_dir / "frame_stats.csv"
    bin_path = golden_dir / "bin_stats.csv"

    config = read_json(config_path)
    metrics = read_json(metrics_path)
    exact_keys(metrics, METRICS_TOP_KEYS, f"{metrics_path}:top")
    require(metrics["schema"] == "trecap_phase2_metrics_v1", f"{metrics_path}: schema mismatch")
    require(metrics["vector_name"] == vector, f"{metrics_path}: vector_name mismatch")

    require(config.get("schema") == "trecap_phase2_vector_config_v1", f"{config_path}: schema mismatch")
    require(config.get("vector_name") == vector, f"{config_path}: vector_name mismatch")
    require(set(config) == {
        "schema",
        "vector_name",
        "configuration",
        "contract",
        "widths",
        "hashes",
        "stream_hashes",
        "artifact_rows",
    }, f"{config_path}: top-level key mismatch")

    configuration = exact_keys(metrics["configuration"], CONFIG_KEYS, "metrics.configuration")
    exact_keys(config["configuration"], CONFIG_KEYS, "config.configuration")
    require(configuration == config["configuration"], "config/metrics configuration mismatch")
    contract = exact_keys(metrics["contract"], CONTRACT_KEYS, "metrics.contract")
    exact_keys(config["contract"], CONTRACT_KEYS, "config.contract")
    require(contract == config["contract"], "config/metrics contract mismatch")
    widths = exact_keys(metrics["widths"], WIDTH_KEYS, "metrics.widths")
    exact_keys(config["widths"], WIDTH_KEYS, "config.widths")
    require(widths == config["widths"], "config/metrics width mismatch")
    hashes = exact_keys(metrics["hashes"], HASH_KEYS, "metrics.hashes")
    exact_keys(config["hashes"], HASH_KEYS, "config.hashes")
    require(hashes == config["hashes"], "config/metrics coefficient hash mismatch")
    stream_hashes = exact_keys(
        metrics["stream_hashes"], {"x_in_sha256", "y_out_sha256"}, "metrics.stream_hashes"
    )
    exact_keys(config["stream_hashes"], {"x_in_sha256", "y_out_sha256"}, "config.stream_hashes")
    require(stream_hashes == config["stream_hashes"], "config/metrics stream hash mismatch")

    require(contract["tail_policy"] == "full_tail", "only full_tail is accepted by this C0 scoreboard")
    require(contract["threshold_mapping"] == "raw_thr2", "threshold must be raw_thr2")
    require(contract["memh_encoding"] == "fixed_width_lowercase_hex_lf", "memh contract mismatch")
    require(contract["hash_rule"] == "logical_integer_vector_fixed_width_hex_lf", "hash contract mismatch")

    # Lock the vector contract to the generated RTL configuration.  A mutually
    # consistent config/metrics pair is not sufficient if it targets different
    # widths or arithmetic semantics than the package being simulated.
    rtl_config_path = repo / "spec" / "generated" / "core_config.json"
    rtl_config = read_json(rtl_config_path)
    require(
        rtl_config.get("schema") == "trecap_phase2_core_config_v1",
        f"{rtl_config_path}: schema mismatch",
    )
    rtl_configuration = rtl_config.get("configuration")
    rtl_widths = rtl_config.get("widths")
    rtl_contract = rtl_config.get("contract")
    require(isinstance(rtl_configuration, dict), f"{rtl_config_path}: missing configuration")
    require(isinstance(rtl_widths, dict), f"{rtl_config_path}: missing widths")
    require(isinstance(rtl_contract, dict), f"{rtl_config_path}: missing contract")
    for key in ("N", "L", "P", "H", "F", "G", "D", "PROTECT_DC", "PROTECT_NYQ"):
        require(
            configuration[key] == rtl_configuration.get(key),
            f"vector configuration.{key} does not match generated RTL",
        )
    require(widths == rtl_widths, "vector widths do not match generated RTL")
    for key in ("fft_mode", "rounding_mode", "tail_policy", "threshold_mapping"):
        require(
            contract[key] == rtl_contract.get(key),
            f"vector contract.{key} does not match generated RTL",
        )
    artifact_contract = rtl_config.get("artifact_contract")
    require(isinstance(artifact_contract, dict), f"{rtl_config_path}: missing artifact contract")
    require(
        contract["memh_encoding"] == artifact_contract.get("memh_encoding"),
        "vector memh encoding does not match generated RTL artifact contract",
    )
    require(
        contract["hash_rule"] == artifact_contract.get("hash_rule"),
        "vector hash rule does not match generated RTL artifact contract",
    )

    n = integer(configuration["N"], "N", minimum=1)
    l_value = integer(configuration["L"], "L", minimum=1)
    h_value = integer(configuration["H"], "H", minimum=1)
    g_value = integer(configuration["G"], "G", minimum=0)
    d_value = integer(configuration["D"], "D", minimum=1)
    ns = integer(configuration["Ns"], "Ns", minimum=1)
    ny = integer(configuration["Ny"], "Ny", minimum=1)
    frames = integer(configuration["frames"], "frames", minimum=1)
    protect_dc = integer(configuration["PROTECT_DC"], "PROTECT_DC", minimum=0)
    protect_nyq = integer(configuration["PROTECT_NYQ"], "PROTECT_NYQ", minimum=0)
    require(protect_dc in {0, 1} and protect_nyq in {0, 1}, "protection flags must be 0/1")
    thr2 = decimal(configuration["THR2"], "configuration.THR2")
    mag2_width = integer(widths["W_mag2"], "W_mag2", minimum=1)
    can_width = integer(widths["W_can"], "W_can", minimum=1)
    require(0 <= thr2 < (1 << mag2_width), "THR2 exceeds W_mag2")
    expected_frames = (ns + l_value - 2) // h_value
    tau_last = expected_frames * h_value
    require(frames == expected_frames, "finite-stream frame geometry mismatch")
    require(d_value == g_value + l_value, "D must equal G+L")
    require(ny == tau_last + d_value, "full-tail Ny geometry mismatch")
    require(l_value % 2 == 0, "L must be even")
    unique_bins = (l_value // 2) + 1
    require(ns < (1 << 31) and ny < (1 << 31), "SV static stream array bound is too large")
    require(frames < (1 << 31), "SV static frame array bound is too large")

    artifact_rows = exact_keys(
        config["artifact_rows"],
        {
            "window_qw",
            "twiddle_re",
            "twiddle_im",
            "twiddle_inv_re",
            "twiddle_inv_im",
            "x_in",
            "y_out",
            "frame_stats_data_rows",
        }
        | ({"bin_stats_data_rows"} if "bin_stats_data_rows" in config["artifact_rows"] else set()),
        "config.artifact_rows",
    )
    require(integer(artifact_rows["x_in"], "artifact_rows.x_in") == ns, "x row declaration mismatch")
    require(integer(artifact_rows["y_out"], "artifact_rows.y_out") == ny, "y row declaration mismatch")
    require(
        integer(artifact_rows["frame_stats_data_rows"], "artifact_rows.frame_stats_data_rows")
        == frames,
        "frame row declaration mismatch",
    )
    has_bin_stats = "bin_stats_data_rows" in artifact_rows
    require(not require_bin_stats or has_bin_stats, f"{vector}: bin_stats is required for this test")
    if has_bin_stats:
        require(
            integer(artifact_rows["bin_stats_data_rows"], "artifact_rows.bin_stats_data_rows")
            == frames * unique_bins,
            "bin row declaration mismatch",
        )
        require(bin_path.is_file(), f"{bin_path}: declared bin_stats is missing")
    else:
        require(not bin_path.exists(), f"{bin_path}: undeclared bin_stats is present")

    x_values, x_hash = parse_memh(x_path, width=n, rows=ns)
    y_values, y_hash = parse_memh(y_path, width=n, rows=ny)
    require(LOWER_HEX_64.fullmatch(stream_hashes["x_in_sha256"]) is not None, "invalid x hash")
    require(LOWER_HEX_64.fullmatch(stream_hashes["y_out_sha256"]) is not None, "invalid y hash")
    require(x_hash == stream_hashes["x_in_sha256"], "x_in SHA-256 mismatch")
    require(y_hash == stream_hashes["y_out_sha256"], "y_out SHA-256 mismatch")

    coefficient_specs = {
        "window_qw": {
            "file": "window_qw.memh",
            "width": integer(widths["W_Qw"], "W_Qw", minimum=1),
            "signed": False,
            "q_format": "Q0.15_unsigned_endpoint_one",
        },
        "twiddle_re": {
            "file": "twiddle_re.memh",
            "width": integer(widths["W_tw"], "W_tw", minimum=1),
            "signed": True,
            "q_format": "Q1.15_signed_endpoint_one",
        },
        "twiddle_im": {
            "file": "twiddle_im.memh",
            "width": integer(widths["W_tw"], "W_tw", minimum=1),
            "signed": True,
            "q_format": "Q1.15_signed_endpoint_one",
        },
        "twiddle_inv_re": {
            "file": "twiddle_inv_re.memh",
            "width": integer(widths["W_tw"], "W_tw", minimum=1),
            "signed": True,
            "q_format": "Q1.15_signed_endpoint_one",
        },
        "twiddle_inv_im": {
            "file": "twiddle_inv_im.memh",
            "width": integer(widths["W_tw"], "W_tw", minimum=1),
            "signed": True,
            "q_format": "Q1.15_signed_endpoint_one",
        },
    }
    coefficient_dir = repo / "artifacts" / "coefficients"
    coeff_manifest_path = coefficient_dir / "coeff_manifest.json"
    coeff_manifest = read_json(coeff_manifest_path)
    exact_keys(
        coeff_manifest,
        {
            "schema",
            "spec_revision",
            "generator_version",
            "generator_source_sha256",
            "created_utc",
            "configuration",
            "contract",
            "widths",
            "coefficients",
            "hashes",
            "artifact_rows",
        },
        f"{coeff_manifest_path}:top",
    )
    require(
        coeff_manifest["schema"] == "trecap_phase2_coeff_manifest_v1",
        f"{coeff_manifest_path}: schema mismatch",
    )
    require(
        coeff_manifest["configuration"] == rtl_configuration,
        f"{coeff_manifest_path}: generated RTL configuration mismatch",
    )
    require(coeff_manifest["widths"] == widths, f"{coeff_manifest_path}: width mismatch")
    require(coeff_manifest["hashes"] == hashes, f"{coeff_manifest_path}: hash map mismatch")
    exact_keys(
        coeff_manifest["contract"],
        {"qcoef_rule", "memh_encoding", "hash_rule"},
        f"{coeff_manifest_path}:contract",
    )
    require(
        coeff_manifest["contract"]["qcoef_rule"] == contract["rounding_mode"],
        f"{coeff_manifest_path}: qcoef rounding mismatch",
    )
    require(
        coeff_manifest["contract"]["memh_encoding"] == contract["memh_encoding"],
        f"{coeff_manifest_path}: memh encoding mismatch",
    )
    require(
        coeff_manifest["contract"]["hash_rule"] == contract["hash_rule"],
        f"{coeff_manifest_path}: hash rule mismatch",
    )
    exact_keys(
        coeff_manifest["coefficients"],
        set(coefficient_specs),
        f"{coeff_manifest_path}:coefficients",
    )
    exact_keys(
        coeff_manifest["artifact_rows"],
        set(coefficient_specs),
        f"{coeff_manifest_path}:artifact_rows",
    )
    coefficient_hashes: dict[str, str] = {}
    for name, spec in coefficient_specs.items():
        key = f"{name}_sha256"
        expected_hash = hashes[key]
        require(
            isinstance(expected_hash, str)
            and LOWER_HEX_64.fullmatch(expected_hash) is not None,
            f"{key}: invalid SHA-256",
        )
        expected_rows = integer(artifact_rows[name], f"artifact_rows.{name}", minimum=1)
        require(
            expected_rows
            == integer(
                artifact_contract["coefficient_rows"][name],
                f"generated artifact_contract.coefficient_rows.{name}",
                minimum=1,
            ),
            f"{name}: generated coefficient row contract mismatch",
        )
        require(
            coeff_manifest["artifact_rows"][name] == expected_rows,
            f"{coeff_manifest_path}:{name} artifact row mismatch",
        )
        metadata = exact_keys(
            coeff_manifest["coefficients"][name],
            {
                "file",
                "rows",
                "width_bits",
                "signed",
                "q_format",
                "sha256",
                "canonical_sha256",
            },
            f"{coeff_manifest_path}:coefficients.{name}",
        )
        require(metadata["file"] == spec["file"], f"{coeff_manifest_path}:{name} file mismatch")
        require(metadata["rows"] == expected_rows, f"{coeff_manifest_path}:{name} rows mismatch")
        require(
            metadata["width_bits"] == spec["width"],
            f"{coeff_manifest_path}:{name} width mismatch",
        )
        require(
            metadata["signed"] is spec["signed"],
            f"{coeff_manifest_path}:{name} signedness mismatch",
        )
        require(
            metadata["q_format"] == spec["q_format"],
            f"{coeff_manifest_path}:{name} Q format mismatch",
        )
        require(
            metadata["sha256"] == expected_hash
            and metadata["canonical_sha256"] == expected_hash,
            f"{coeff_manifest_path}:{name} hash mismatch",
        )
        coefficient_path = coefficient_dir / spec["file"]
        _, actual_hash = parse_memh(
            coefficient_path,
            width=spec["width"],
            rows=expected_rows,
        )
        require(actual_hash == expected_hash, f"{spec['file']}: coefficient SHA-256 mismatch")
        promoted_relative = f"artifacts/coefficients/{spec['file']}"
        require(
            promoted_hashes.get(promoted_relative) == actual_hash,
            f"{promoted_relative}: import provenance mismatch",
        )
        coefficient_hashes[name] = actual_hash
    coeff_manifest_hash = sha256_bytes(coeff_manifest_path)
    require(
        promoted_hashes.get("artifacts/coefficients/coeff_manifest.json")
        == coeff_manifest_hash,
        "coeff_manifest import provenance mismatch",
    )

    frame_rows = parse_frame_stats(frame_path, rows=frames)
    for row in frame_rows:
        require(row["unique_bins"] == unique_bins, f"frame {row['frame_idx']}: unique bin count")
        for key in (
            "unique_bins",
            "unique_suppressed_bins",
            "eligible_unique_bins",
            "eligible_suppressed_bins",
        ):
            require(row[key] < (1 << 32), f"frame {row['frame_idx']}:{key} exceeds RTL field")
        for key in SPECTRAL_KEYS:
            # The portable SV loader uses %d into longint signed before
            # assigning the 64-bit RTL field.  Reject the unsupported unsigned
            # top half rather than accepting simulator-dependent parsing.
            require(
                row[key] < (1 << 63),
                f"frame {row['frame_idx']}:{key} exceeds portable CSV loader",
            )
    frame_totals = sum_frame_metrics(frame_rows)

    bin_rows: list[dict[str, int]] = []
    if has_bin_stats:
        bin_rows = parse_bin_stats(
            bin_path,
            frames=frames,
            unique_bins=unique_bins,
            can_width=can_width,
            thr2=thr2,
            protect_dc=protect_dc,
            protect_nyq=protect_nyq,
        )
        from_bins = frame_metrics_from_bins(bin_rows, frames=frames, unique_bins=unique_bins)
        require(from_bins == frame_rows, "bin_stats does not aggregate exactly to frame_stats")
        require(len(bin_rows) < (1 << 31), "SV static bin array bound is too large")
        for ordinal, row in enumerate(bin_rows):
            require(
                row["mag2"] < (1 << mag2_width),
                f"{bin_path}:{ordinal + 2}: mag2 exceeds W_mag2",
            )

    suppression_json = exact_keys(
        metrics["suppression_totals"], SUPPRESSION_KEYS, "metrics.suppression_totals"
    )
    spectral_json = exact_keys(
        metrics["spectral_totals"], SPECTRAL_KEYS, "metrics.spectral_totals"
    )
    time_json = exact_keys(metrics["time_domain_errors"], TIME_KEYS, "metrics.time_domain_errors")
    metric_totals = {
        key: decimal(value, f"metrics.{key}")
        for key, value in {**suppression_json, **spectral_json}.items()
    }
    require(metric_totals == frame_totals, "frame_stats aggregate does not match metrics.json")
    computed_time = time_metrics(x_values, y_values, delay=d_value)
    expected_time = {
        key: decimal(value, f"metrics.time_domain_errors.{key}") for key, value in time_json.items()
    }
    require(computed_time == expected_time, "x/y delayed error metrics do not match metrics.json")

    for key in SUPPRESSION_KEYS:
        require(metric_totals[key] < (1 << 64), f"metrics.{key} exceeds scoreboard width")
    for key in SPECTRAL_KEYS:
        require(metric_totals[key] < (1 << 128), f"metrics.{key} exceeds scoreboard width")
    require(expected_time["error_sample_count"] < (1 << 64), "error_sample_count exceeds RTL")
    require(expected_time["max_abs_err"] < (1 << 16), "max_abs_err exceeds RTL")
    for key in ("sum_abs_err", "sum_sq_err"):
        require(expected_time[key] < (1 << 64), f"{key} exceeds exposed RTL low counter")

    config_hash = sha256_bytes(config_path)
    metrics_hash = sha256_bytes(metrics_path)
    frame_hash = sha256_bytes(frame_path)
    bin_hash = sha256_bytes(bin_path) if has_bin_stats else None

    # The vector index is the frozen per-case provenance anchor.  The imported
    # release manifest has known line-ending provenance debt, so this check
    # intentionally validates its exact per-artifact declarations rather than
    # accepting stale artifacts/golden paths from the outer release index.
    vector_index_path = repo / "artifacts" / "test_vectors" / "test_vectors.json"
    vector_index = read_json(vector_index_path)
    require(
        vector_index.get("schema") == "trecap_phase2_test_vectors_v1",
        f"{vector_index_path}: schema mismatch",
    )
    entries = vector_index.get("vectors")
    require(isinstance(entries, list), f"{vector_index_path}: vectors must be an array")
    matches = [
        entry
        for entry in entries
        if isinstance(entry, dict) and entry.get("name") == vector
    ]
    require(len(matches) == 1, f"{vector_index_path}: expected one entry for {vector}")
    vector_entry = matches[0]
    require(vector_entry.get("lifecycle_status") == "golden_frozen", "vector is not frozen")
    require(vector_entry.get("Ns") == ns, "vector index Ns mismatch")
    require(vector_entry.get("THR2") == configuration["THR2"], "vector index THR2 mismatch")
    require(vector_entry.get("PROTECT_DC") == protect_dc, "vector index PROTECT_DC mismatch")
    require(vector_entry.get("PROTECT_NYQ") == protect_nyq, "vector index PROTECT_NYQ mismatch")
    require(vector_entry.get("tail_policy") == contract["tail_policy"], "vector tail policy mismatch")
    require(vector_entry.get("rounding") == contract["rounding_mode"], "vector rounding mismatch")
    declared_hashes = {
        "x_in_sha256": x_hash,
        "y_out_sha256": y_hash,
        "config_sha256": config_hash,
        "metrics_sha256": metrics_hash,
        "frame_stats_sha256": frame_hash,
    }
    if has_bin_stats:
        declared_hashes["bin_stats_sha256"] = bin_hash
        require(vector_entry.get("requires_bin_stats") is True, "bin_stats is not required by index")
    for key, actual_hash in declared_hashes.items():
        require(
            vector_entry.get(key) == actual_hash,
            f"{vector_index_path}:{vector}:{key} mismatch",
        )

    promoted_case_hashes = {
        f"artifacts/test_vectors/{vector}/config.json": config_hash,
        f"artifacts/test_vectors/{vector}/x_in.memh": x_hash,
        f"artifacts/reference_outputs/{vector}/y_out.memh": y_hash,
        f"artifacts/reference_outputs/{vector}/frame_stats.csv": frame_hash,
        f"artifacts/reference_outputs/{vector}/metrics.json": metrics_hash,
        "artifacts/test_vectors/test_vectors.json": sha256_bytes(vector_index_path),
    }
    if has_bin_stats:
        promoted_case_hashes[
            f"artifacts/reference_outputs/{vector}/bin_stats.csv"
        ] = bin_hash
    for relative, actual_hash in promoted_case_hashes.items():
        require(
            promoted_hashes.get(relative) == actual_hash,
            f"{relative}: required imported artifact provenance mismatch",
        )

    return {
        "repo": repo,
        "vector": vector,
        "configuration": configuration,
        "widths": widths,
        "artifact_rows": artifact_rows,
        "paths": {
            "config": config_path,
            "metrics": metrics_path,
            "x": x_path,
            "y": y_path,
            "frame": frame_path,
            "bin": bin_path if has_bin_stats else None,
        },
        "hashes": {
            "config": config_hash,
            "metrics": metrics_hash,
            "x": x_hash,
            "y": y_hash,
            "frame": frame_hash,
            "bin": bin_hash,
            "coeff_manifest": coeff_manifest_hash,
            **{
                f"coefficient_{name}": value
                for name, value in sorted(coefficient_hashes.items())
            },
            "test_vectors": sha256_bytes(vector_index_path),
            "reference_import_manifest": sha256_bytes(
                repo / "artifacts" / "manifests" / "reference_import_manifest.json"
            ),
            "generated_manifest": sha256_bytes(
                repo / "spec" / "generated" / "gen_manifest.json"
            ),
            "generated_core_config": sha256_bytes(rtl_config_path),
            "generated_core_pkg": sha256_bytes(
                repo / "rtl" / "include" / "generated" / "trecap_core_pkg.sv"
            ),
            "generated_iface_pkg": sha256_bytes(
                repo / "rtl" / "include" / "generated" / "trecap_iface_pkg.sv"
            ),
            **compile_input_hashes(repo),
        },
        "frame_rows": frame_rows,
        "bin_rows": bin_rows,
        "metrics_dynamic": {
            "suppression_totals": {
                key: frame_totals[key] for key in sorted(SUPPRESSION_KEYS)
            },
            "spectral_totals": {
                key: frame_totals[key] for key in sorted(SPECTRAL_KEYS)
            },
            "time_domain_errors": expected_time,
        },
        "unique_bins": unique_bins,
        "tau_last": tau_last,
    }


def sv_string(value: str) -> str:
    require(re.fullmatch(r"[A-Za-z0-9_.-]+", value) is not None, "unsafe SV string")
    return value


def render_header(case: dict[str, Any]) -> str:
    cfg = case["configuration"]
    rows = case["artifact_rows"]
    dynamic = case["metrics_dynamic"]
    suppression = dynamic["suppression_totals"]
    spectral = dynamic["spectral_totals"]
    time_values = dynamic["time_domain_errors"]
    lines = [
        "// Generated by scripts/sim/trecap_artifact_scoreboard.py prepare.",
        "// Do not hand-edit; the source artifacts and their SHA-256 values are authoritative.",
        "",
        "package trecap_artifact_expectations_pkg;",
        "  import trecap_core_pkg::*;",
        "",
        f'localparam string TEXP_VECTOR_NAME = "{sv_string(case["vector"])}";',
        f"localparam int unsigned TEXP_NS = {cfg['Ns']};",
        f"localparam int unsigned TEXP_NY = {cfg['Ny']};",
        f"localparam int unsigned TEXP_FRAMES = {cfg['frames']};",
        f"localparam int unsigned TEXP_UNIQUE_BINS = {case['unique_bins']};",
        f"localparam int unsigned TEXP_BIN_ROWS = {rows['bin_stats_data_rows']};",
        f"localparam logic [T_MAG2_W-1:0] TEXP_THR2 = T_MAG2_W'({cfg['THR2']});",
        f"localparam logic [63:0] TEXP_UNIQUE_BINS_TOTAL = 64'd{suppression['unique_bins']};",
        f"localparam logic [63:0] TEXP_UNIQUE_SUPPRESSED_TOTAL = 64'd{suppression['unique_suppressed_bins']};",
        f"localparam logic [63:0] TEXP_ELIGIBLE_UNIQUE_TOTAL = 64'd{suppression['eligible_unique_bins']};",
        f"localparam logic [63:0] TEXP_ELIGIBLE_SUPPRESSED_TOTAL = 64'd{suppression['eligible_suppressed_bins']};",
        f"localparam logic [127:0] TEXP_ELIGIBLE_KEPT_MAG2 = 128'd{spectral['eligible_kept_mag2']};",
        f"localparam logic [127:0] TEXP_ELIGIBLE_TOTAL_MAG2 = 128'd{spectral['eligible_total_mag2']};",
        f"localparam logic [127:0] TEXP_SUM_ABS_ERR = 128'd{time_values['sum_abs_err']};",
        f"localparam logic [127:0] TEXP_SUM_SQ_ERR = 128'd{time_values['sum_sq_err']};",
        f"localparam logic [15:0] TEXP_MAX_ABS_ERR = 16'd{time_values['max_abs_err']};",
        f"localparam logic [63:0] TEXP_ERROR_SAMPLE_COUNT = 64'd{time_values['error_sample_count']};",
        f'localparam string TEXP_X_SHA256 = "{case["hashes"]["x"]}";',
        f'localparam string TEXP_Y_SHA256 = "{case["hashes"]["y"]}";',
        f'localparam string TEXP_FRAME_SHA256 = "{case["hashes"]["frame"]}";',
        f'localparam string TEXP_BIN_SHA256 = "{case["hashes"]["bin"]}";',
        f'localparam string TEXP_METRICS_SHA256 = "{case["hashes"]["metrics"]}";',
        "",
        "endpackage : trecap_artifact_expectations_pkg",
        "",
    ]
    return "\n".join(lines)


def write_text_lf(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode("ascii"))


def expectation_manifest(case: dict[str, Any], header: bytes) -> dict[str, Any]:
    return {
        "schema": "trecap_c0_artifact_expectations_v1",
        "vector_name": case["vector"],
        "configuration": case["configuration"],
        "artifact_rows": case["artifact_rows"],
        "source_sha256": case["hashes"],
        "dynamic_metrics": case["metrics_dynamic"],
        "generated_header_sha256": hashlib.sha256(header).hexdigest(),
    }


def verify_snapshot(
    repo: Path,
    vector: str,
    header_path: Path,
    manifest_path: Path,
    *,
    emit_pass: bool = True,
) -> dict[str, Any]:
    case = validate_case(repo, vector, require_bin_stats=True)
    expected_header = render_header(case).encode("ascii")
    try:
        actual_header = header_path.read_bytes()
    except OSError as exc:
        raise ContractError(f"cannot read expectation package {header_path}: {exc}") from exc
    require(
        actual_header == expected_header,
        f"{header_path}: expectation package is stale or was modified after preflight",
    )

    expected_manifest = expectation_manifest(case, expected_header)
    actual_manifest = read_json(manifest_path)
    require(
        actual_manifest == expected_manifest,
        f"{manifest_path}: expectation snapshot is stale or was modified after preflight",
    )
    canonical_manifest = (
        json.dumps(expected_manifest, indent=2, sort_keys=True) + "\n"
    ).encode("ascii")
    try:
        actual_manifest_bytes = manifest_path.read_bytes()
    except OSError as exc:
        raise ContractError(f"cannot read expectation snapshot {manifest_path}: {exc}") from exc
    require(
        actual_manifest_bytes == canonical_manifest,
        f"{manifest_path}: expectation snapshot is not canonical",
    )
    if emit_pass:
        print(
            "C0_ARTIFACT_SNAPSHOT_PASS "
            f"vector={vector} sources={len(case['hashes'])}"
        )
    return case


def prepare(repo: Path, vector: str, header_path: Path, manifest_path: Path) -> dict[str, Any]:
    case = validate_case(repo, vector, require_bin_stats=True)
    header = render_header(case).encode("ascii")
    header_path.parent.mkdir(parents=True, exist_ok=True)
    header_path.write_bytes(header)
    manifest = expectation_manifest(case, header)
    write_text_lf(manifest_path, json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    print(
        "C0_ARTIFACT_PREFLIGHT_PASS "
        f"vector={vector} y={case['configuration']['Ny']} "
        f"frames={case['configuration']['frames']} bins={len(case['bin_rows'])}"
    )
    return case


def observed_metrics_from_case(case: dict[str, Any]) -> dict[str, Any]:
    dynamic = case["metrics_dynamic"]
    return {
        "schema": "trecap_phase2_rtl_metrics_observed_v1",
        "vector_name": case["vector"],
        "counts": {
            "y_rows": case["configuration"]["Ny"],
            "frame_rows": case["configuration"]["frames"],
            "bin_rows": len(case["bin_rows"]),
            "done_pulses": 1,
        },
        "suppression_totals": {
            key: str(value) for key, value in dynamic["suppression_totals"].items()
        },
        "spectral_totals": {
            key: str(value) for key, value in dynamic["spectral_totals"].items()
        },
        "time_domain_errors": {
            key: str(value) for key, value in dynamic["time_domain_errors"].items()
        },
        "internal_metrics": {
            "error_sample_count": str(dynamic["time_domain_errors"]["error_sample_count"]),
            "sum_abs_err": str(dynamic["time_domain_errors"]["sum_abs_err"]),
            "sum_sq_err": str(dynamic["time_domain_errors"]["sum_sq_err"]),
            "max_abs_err": str(dynamic["time_domain_errors"]["max_abs_err"]),
        },
        "status": {
            "core_overflow_flags": "0",
            "top_overflow_flags": "0",
            "saturation_sticky": 0,
            "protocol_error_sticky": 0,
            "completion_error_sticky": 0,
            "metric_overflow_sticky": 0,
        },
    }


def parse_observed_metrics(path: Path) -> dict[str, Any]:
    value = read_json(path)
    exact_keys(
        value,
        {
            "schema",
            "vector_name",
            "counts",
            "suppression_totals",
            "spectral_totals",
            "time_domain_errors",
            "internal_metrics",
            "status",
        },
        f"{path}:top",
    )
    require(
        value["schema"] == "trecap_phase2_rtl_metrics_observed_v1",
        f"{path}: schema mismatch",
    )
    exact_keys(value["counts"], {"y_rows", "frame_rows", "bin_rows", "done_pulses"}, "observed.counts")
    exact_keys(value["suppression_totals"], SUPPRESSION_KEYS, "observed.suppression_totals")
    exact_keys(value["spectral_totals"], SPECTRAL_KEYS, "observed.spectral_totals")
    exact_keys(value["time_domain_errors"], TIME_KEYS, "observed.time_domain_errors")
    exact_keys(
        value["internal_metrics"],
        {"error_sample_count", "sum_abs_err", "sum_sq_err", "max_abs_err"},
        "observed.internal_metrics",
    )
    exact_keys(
        value["status"],
        {
            "core_overflow_flags",
            "top_overflow_flags",
            "saturation_sticky",
            "protocol_error_sticky",
            "completion_error_sticky",
            "metric_overflow_sticky",
        },
        "observed.status",
    )
    return value


def compare(
    repo: Path,
    vector: str,
    capture_dir: Path,
    header_path: Path,
    manifest_path: Path,
) -> None:
    case = verify_snapshot(
        repo,
        vector,
        header_path,
        manifest_path,
        emit_pass=False,
    )
    paths = case["paths"]
    observed_y = capture_dir / "y_out.memh"
    observed_frame = capture_dir / "frame_stats.csv"
    observed_bin = capture_dir / "bin_stats.csv"
    observed_metrics_path = capture_dir / "metrics_observed.json"

    parse_memh(observed_y, width=case["configuration"]["N"], rows=case["configuration"]["Ny"])
    parse_frame_stats(observed_frame, rows=case["configuration"]["frames"])
    parse_bin_stats(
        observed_bin,
        frames=case["configuration"]["frames"],
        unique_bins=case["unique_bins"],
        can_width=case["widths"]["W_can"],
        thr2=int(case["configuration"]["THR2"]),
        protect_dc=case["configuration"]["PROTECT_DC"],
        protect_nyq=case["configuration"]["PROTECT_NYQ"],
    )
    for observed, golden, label in (
        (observed_y, paths["y"], "y_out.memh"),
        (observed_frame, paths["frame"], "frame_stats.csv"),
        (observed_bin, paths["bin"], "bin_stats.csv"),
    ):
        require(golden is not None, f"{label}: missing golden path")
        require(
            observed.read_bytes() == golden.read_bytes(),
            f"{label}: RTL capture differs: {first_line_difference(observed, golden)}",
        )

    observed_metrics = parse_observed_metrics(observed_metrics_path)
    require(observed_metrics["vector_name"] == vector, "observed metrics vector mismatch")
    expected_counts = {
        "y_rows": case["configuration"]["Ny"],
        "frame_rows": case["configuration"]["frames"],
        "bin_rows": len(case["bin_rows"]),
        "done_pulses": 1,
    }
    require(observed_metrics["counts"] == expected_counts, "observed event counts mismatch")
    for group in ("suppression_totals", "spectral_totals", "time_domain_errors"):
        expected = {
            key: str(value) for key, value in case["metrics_dynamic"][group].items()
        }
        require(observed_metrics[group] == expected, f"observed {group} mismatch")
    expected_internal = {
        "error_sample_count": str(
            case["metrics_dynamic"]["time_domain_errors"]["error_sample_count"]
        ),
        "sum_abs_err": str(case["metrics_dynamic"]["time_domain_errors"]["sum_abs_err"]),
        "sum_sq_err": str(case["metrics_dynamic"]["time_domain_errors"]["sum_sq_err"]),
        "max_abs_err": str(case["metrics_dynamic"]["time_domain_errors"]["max_abs_err"]),
    }
    require(observed_metrics["internal_metrics"] == expected_internal, "internal RTL metric mismatch")
    require(
        observed_metrics["status"]
        == {
            "core_overflow_flags": "0",
            "top_overflow_flags": "0",
            "saturation_sticky": 0,
            "protocol_error_sticky": 0,
            "completion_error_sticky": 0,
            "metric_overflow_sticky": 0,
        },
        "RTL status contains a signoff error",
    )
    print(
        "C0_ARTIFACT_POSTCHECK_PASS "
        f"vector={vector} y={expected_counts['y_rows']} "
        f"frames={expected_counts['frame_rows']} bins={expected_counts['bin_rows']}"
    )


def self_test(repo: Path, vector: str) -> None:
    case = validate_case(repo, vector, require_bin_stats=True)
    with tempfile.TemporaryDirectory(prefix="trecap-artifact-scoreboard-") as tmp:
        root = Path(tmp)
        header = root / "generated" / "trecap_artifact_expectations_pkg.sv"
        manifest = root / "generated" / "expectations.json"
        prepare(repo, vector, header, manifest)
        require(header.is_file() and manifest.is_file(), "self-test prepare did not emit files")
        verify_snapshot(repo, vector, header, manifest)

        capture = root / "capture"
        capture.mkdir()
        shutil.copyfile(case["paths"]["y"], capture / "y_out.memh")
        shutil.copyfile(case["paths"]["frame"], capture / "frame_stats.csv")
        shutil.copyfile(case["paths"]["bin"], capture / "bin_stats.csv")
        write_text_lf(
            capture / "metrics_observed.json",
            json.dumps(observed_metrics_from_case(case), indent=2) + "\n",
        )
        compare(repo, vector, capture, header, manifest)

        original_manifest = manifest.read_bytes()
        corrupt_snapshot = read_json(manifest)
        corrupt_snapshot["source_sha256"]["config"] = "0" * 64
        write_text_lf(
            manifest,
            json.dumps(corrupt_snapshot, indent=2, sort_keys=True) + "\n",
        )
        try:
            verify_snapshot(repo, vector, header, manifest)
        except ContractError:
            pass
        else:
            raise ContractError("self-test failed to reject a stale expectation snapshot")
        manifest.write_bytes(original_manifest)

        with (capture / "y_out.memh").open("ab") as stream:
            stream.write(b"000\n")
        try:
            compare(repo, vector, capture, header, manifest)
        except ContractError:
            pass
        else:
            raise ContractError("self-test failed to reject an extra y_out row")
        shutil.copyfile(case["paths"]["y"], capture / "y_out.memh")

        with (capture / "frame_stats.csv").open("ab") as stream:
            stream.write(case["paths"]["frame"].read_bytes().splitlines(keepends=True)[1])
        try:
            compare(repo, vector, capture, header, manifest)
        except ContractError:
            pass
        else:
            raise ContractError("self-test failed to reject an extra frame_stats row")
        shutil.copyfile(case["paths"]["frame"], capture / "frame_stats.csv")

        bin_lines = case["paths"]["bin"].read_text(encoding="ascii").splitlines()
        first_bin = bin_lines[1].split(",")
        first_bin[6] = "1" if first_bin[6] == "0" else "0"
        bin_lines[1] = ",".join(first_bin)
        write_text_lf(capture / "bin_stats.csv", "\n".join(bin_lines) + "\n")
        try:
            compare(repo, vector, capture, header, manifest)
        except ContractError:
            pass
        else:
            raise ContractError("self-test failed to reject a corrupted bin_stats row")
        shutil.copyfile(case["paths"]["bin"], capture / "bin_stats.csv")

        corrupt_metrics = observed_metrics_from_case(case)
        corrupt_metrics["internal_metrics"]["max_abs_err"] = "1"
        write_text_lf(
            capture / "metrics_observed.json",
            json.dumps(corrupt_metrics, indent=2) + "\n",
        )
        try:
            compare(repo, vector, capture, header, manifest)
        except ContractError:
            pass
        else:
            raise ContractError("self-test failed to reject corrupted RTL metrics")

        duplicate_json = root / "duplicate.json"
        write_text_lf(duplicate_json, '{"a": 1, "a": 2}\n')
        try:
            read_json(duplicate_json)
        except ContractError:
            pass
        else:
            raise ContractError("self-test failed to reject a duplicate JSON key")

        nonfinite_json = root / "nonfinite.json"
        write_text_lf(nonfinite_json, '{"value": NaN}\n')
        try:
            read_json(nonfinite_json)
        except ContractError:
            pass
        else:
            raise ContractError("self-test failed to reject non-finite JSON")
    print("C0_ARTIFACT_TOOL_SELFTEST_PASS corruptions=7")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    for name in ("prepare", "verify", "compare", "self-test"):
        command = subparsers.add_parser(name)
        command.add_argument("--repo", type=Path, required=True)
        command.add_argument(
            "--vector",
            default="near_threshold_multitone_Ns1024_thr64",
        )
        if name == "prepare":
            command.add_argument("--header", type=Path, required=True)
            command.add_argument("--manifest", type=Path, required=True)
        elif name in {"verify", "compare"}:
            command.add_argument("--expectation-package", type=Path, required=True)
            command.add_argument("--expectation-manifest", type=Path, required=True)
            if name == "compare":
                command.add_argument("--capture-dir", type=Path, required=True)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    repo = args.repo.resolve()
    require(repo.is_dir(), f"repository does not exist: {repo}")
    if args.command == "prepare":
        prepare(repo, args.vector, args.header.resolve(), args.manifest.resolve())
    elif args.command == "verify":
        verify_snapshot(
            repo,
            args.vector,
            args.expectation_package.resolve(),
            args.expectation_manifest.resolve(),
        )
    elif args.command == "compare":
        compare(
            repo,
            args.vector,
            args.capture_dir.resolve(),
            args.expectation_package.resolve(),
            args.expectation_manifest.resolve(),
        )
    else:
        self_test(repo, args.vector)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ContractError as exc:
        raise SystemExit(f"C0_ARTIFACT_ERROR: {exc}") from exc
