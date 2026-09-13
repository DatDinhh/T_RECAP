#!/usr/bin/env python3
"""Fail-closed, byte-preserving importer for the Phase 2 reference model.

File class: [1] hand-written repository infrastructure.

Two workflows are intentionally separate:

``stage``
    Import a complete ZIP whose SHA-256 was supplied independently.  Every
    archive member is preflighted and CRC-read before a fresh staging tree is
    created.  Included payload bytes are copied verbatim.

``refresh-proxy``
    Describe and verify an already-embedded reference tree.  The resulting
    manifest explicitly says that no source archive was verified.  This mode
    cannot upgrade a proxy into source-verified provenance.

The tool uses only the Python standard library so that provenance checks do
not become optional when a third-party package is unavailable.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
import ntpath
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import sys
import tempfile
import unicodedata
import zipfile
from typing import Any, BinaryIO, Iterable, Sequence


MANIFEST_SCHEMA = "trecap_phase2_reference_import_manifest_v3"
PROMOTION_MAP_SCHEMA = "trecap_phase2_reference_promotion_map_v1"
POLICY_VERSION = "trecap_phase2_reference_import_policy_v1"
PROJECT = "T_RECAP_Phase2"
REFERENCE_ROOT = PurePosixPath("sw/reference_model")
INTERNAL_MANIFEST = REFERENCE_ROOT / "import_manifest.json"
ROOT_MANIFEST = PurePosixPath("artifacts/manifests/reference_import_manifest.json")
GENERATED_MANIFEST_PATHS = (INTERNAL_MANIFEST, ROOT_MANIFEST)

DEFAULT_ARCHIVE_ROOT = "trecap-golden"
DEFAULT_EXCLUDED_DIRECTORIES = (
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "build",
    "legacy",
    "out",
    "runs",
)
DEFAULT_EXCLUDED_EXACT = (
    "spec/normative/T_RECAP_Phase2_Integrated_RevJ_RevG.pdf",
)
DEFAULT_EXCLUDED_SUFFIXES = (".pyc", ".pyo")

DEFAULT_MAX_ENTRIES = 20_000
DEFAULT_MAX_FILE_BYTES = 128 * 1024 * 1024
DEFAULT_MAX_TOTAL_BYTES = 1024 * 1024 * 1024
# Frozen all-zero memh/CSV artifacts are legitimately very compressible.  The
# absolute and total expanded-size caps remain the primary bomb bound.
DEFAULT_MAX_COMPRESSION_RATIO = 1000.0
MAX_MEMBER_NAME_BYTES = 4096
MAX_PATH_COMPONENT_BYTES = 255

SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")
WINDOWS_DRIVE_RE = re.compile(r"^[A-Za-z]:")
WINDOWS_FORBIDDEN = frozenset('<>:"|?*')
WINDOWS_RESERVED = frozenset(
    {"CON", "PRN", "AUX", "NUL"}
    | {f"COM{index}" for index in range(1, 10)}
    | {f"LPT{index}" for index in range(1, 10)}
)
SUPPORTED_COMPRESSION = frozenset({zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED})
COPY_CHUNK_BYTES = 1024 * 1024


class ReferenceImportError(RuntimeError):
    """A fail-closed import or provenance validation failure."""


@dataclass(frozen=True)
class ResourceCaps:
    max_entries: int
    max_file_bytes: int
    max_total_bytes: int
    max_compression_ratio: float

    def validate(self) -> None:
        if self.max_entries <= 0:
            raise ReferenceImportError("max_entries must be positive")
        if self.max_file_bytes <= 0:
            raise ReferenceImportError("max_file_bytes must be positive")
        if self.max_total_bytes <= 0:
            raise ReferenceImportError("max_total_bytes must be positive")
        if self.max_compression_ratio <= 0.0:
            raise ReferenceImportError("max_compression_ratio must be positive")

    def as_manifest(self) -> dict[str, int | str]:
        return {
            "max_compression_ratio": format(self.max_compression_ratio, ".17g"),
            "max_entries": self.max_entries,
            "max_file_bytes": self.max_file_bytes,
            "max_total_bytes": self.max_total_bytes,
        }


@dataclass(frozen=True)
class ArchiveEntry:
    info: zipfile.ZipInfo
    raw_name: str
    canonical_member: str
    reference_relative: str | None
    staged_relative: str | None
    exclusion_reason: str | None
    is_directory: bool
    sha256: str | None


@dataclass(frozen=True)
class Promotion:
    source_relative: str
    destination: str


def _reject_duplicate_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ReferenceImportError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_nonfinite_json(token: str) -> None:
    raise ReferenceImportError(f"non-finite JSON constant is forbidden: {token}")


def _read_json_object(path: Path) -> dict[str, Any]:
    try:
        raw = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise ReferenceImportError(f"cannot read UTF-8 JSON {path}: {exc}") from exc
    try:
        value = json.loads(
            raw,
            object_pairs_hook=_reject_duplicate_object,
            parse_constant=_reject_nonfinite_json,
        )
    except json.JSONDecodeError as exc:
        raise ReferenceImportError(f"invalid JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ReferenceImportError(f"{path}: top-level JSON value must be an object")
    return value


def _canonical_json(value: Any) -> bytes:
    try:
        text = json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
    except (TypeError, ValueError) as exc:
        raise ReferenceImportError(f"cannot serialize canonical manifest: {exc}") from exc
    return (text + "\n").encode("ascii")


def _sha256_stream(stream: BinaryIO) -> str:
    digest = hashlib.sha256()
    while True:
        chunk = stream.read(COPY_CHUNK_BYTES)
        if not chunk:
            return digest.hexdigest()
        digest.update(chunk)


def _sha256_file(path: Path) -> str:
    try:
        with path.open("rb") as stream:
            return _sha256_stream(stream)
    except OSError as exc:
        raise ReferenceImportError(f"cannot hash {path}: {exc}") from exc


def _parse_expected_sha256(value: str) -> str:
    if SHA256_RE.fullmatch(value) is None:
        raise ReferenceImportError("expected SHA-256 must contain exactly 64 hexadecimal digits")
    return value.lower()


def _contains_control(value: str) -> bool:
    return any(
        ord(character) < 32
        or ord(character) == 127
        or unicodedata.category(character) in {"Cc", "Cf"}
        for character in value
    )


def _validate_component(component: str, *, label: str) -> str:
    if component in {"", ".", ".."}:
        raise ReferenceImportError(f"{label}: empty/dot/traversal component is forbidden")
    if _contains_control(component):
        raise ReferenceImportError(f"{label}: control characters are forbidden")
    if component.endswith((" ", ".")):
        raise ReferenceImportError(f"{label}: trailing dot/space is not portable")
    if any(character in WINDOWS_FORBIDDEN for character in component):
        raise ReferenceImportError(f"{label}: Windows-forbidden path character")
    normalized = unicodedata.normalize("NFC", component)
    if len(normalized.encode("utf-8")) > MAX_PATH_COMPONENT_BYTES:
        raise ReferenceImportError(f"{label}: path component is too long")
    reserved_stem = normalized.split(".", maxsplit=1)[0].upper()
    if reserved_stem in WINDOWS_RESERVED:
        raise ReferenceImportError(f"{label}: Windows-reserved name {reserved_stem!r}")
    return normalized


def _canonical_archive_name(raw_name: str) -> tuple[str, bool]:
    if "\x00" in raw_name:
        raise ReferenceImportError("ZIP member contains NUL")
    if _contains_control(raw_name):
        raise ReferenceImportError(f"ZIP member {raw_name!r} contains control characters")
    if len(raw_name.encode("utf-8")) > MAX_MEMBER_NAME_BYTES:
        raise ReferenceImportError("ZIP member name is too long")

    slash_name = raw_name.replace("\\", "/")
    if slash_name.startswith("/") or slash_name.startswith("//"):
        raise ReferenceImportError(f"ZIP member is absolute/UNC: {raw_name!r}")
    drive, _tail = ntpath.splitdrive(slash_name)
    if drive or WINDOWS_DRIVE_RE.match(slash_name):
        raise ReferenceImportError(f"ZIP member is drive-qualified: {raw_name!r}")

    is_directory = slash_name.endswith("/")
    without_trailing = slash_name[:-1] if is_directory else slash_name
    if without_trailing.endswith("/"):
        raise ReferenceImportError(f"ZIP member has repeated trailing separators: {raw_name!r}")
    raw_parts = without_trailing.split("/")
    canonical_parts = [
        _validate_component(part, label=f"ZIP member {raw_name!r}") for part in raw_parts
    ]
    canonical = "/".join(canonical_parts)
    return canonical, is_directory


def _canonical_repo_relative(value: str, *, label: str) -> str:
    if not isinstance(value, str):
        raise ReferenceImportError(f"{label}: path must be a string")
    if "\\" in value:
        raise ReferenceImportError(f"{label}: use canonical '/' separators")
    canonical, is_directory = _canonical_archive_name(value)
    if is_directory:
        raise ReferenceImportError(f"{label}: expected a file path")
    if canonical != value:
        raise ReferenceImportError(f"{label}: path must already be Unicode-NFC canonical")
    return canonical


def _path_collision_key(path: str) -> str:
    return unicodedata.normalize("NFC", path).casefold()


def _exclusion_reason(relative: str) -> str | None:
    parts = PurePosixPath(relative).parts
    for component in parts:
        if component in DEFAULT_EXCLUDED_DIRECTORIES:
            return f"excluded_directory:{component}"
    if relative in DEFAULT_EXCLUDED_EXACT:
        return f"excluded_exact:{relative}"
    suffix = PurePosixPath(relative).suffix
    if suffix in DEFAULT_EXCLUDED_SUFFIXES:
        return f"excluded_suffix:{suffix}"
    return None


def _validate_archive_type(info: zipfile.ZipInfo, directory_from_name: bool) -> bool:
    if info.flag_bits & 0x1:
        raise ReferenceImportError(f"encrypted ZIP member is forbidden: {info.filename!r}")
    if info.compress_type not in SUPPORTED_COMPRESSION:
        raise ReferenceImportError(
            f"unsupported compression method {info.compress_type}: {info.filename!r}"
        )

    unix_mode = (info.external_attr >> 16) & 0xFFFF
    unix_type = stat.S_IFMT(unix_mode)
    dos_directory = bool(info.external_attr & 0x10)
    is_directory = directory_from_name or info.is_dir() or dos_directory

    if unix_type == stat.S_IFLNK:
        raise ReferenceImportError(f"ZIP symlink is forbidden: {info.filename!r}")
    if unix_type not in {0, stat.S_IFREG, stat.S_IFDIR}:
        raise ReferenceImportError(f"ZIP special file is forbidden: {info.filename!r}")
    if unix_type == stat.S_IFDIR and not is_directory:
        raise ReferenceImportError(f"ZIP file/directory type mismatch: {info.filename!r}")
    if unix_type == stat.S_IFREG and is_directory:
        raise ReferenceImportError(f"ZIP directory/regular type mismatch: {info.filename!r}")
    if is_directory and (info.file_size != 0 or info.compress_size != 0):
        raise ReferenceImportError(f"ZIP directory has a payload: {info.filename!r}")
    return is_directory


def _check_resource_limits(
    info: zipfile.ZipInfo,
    *,
    caps: ResourceCaps,
    total_uncompressed: int,
) -> int:
    if info.file_size < 0 or info.compress_size < 0:
        raise ReferenceImportError(f"negative ZIP size: {info.filename!r}")
    if info.file_size > caps.max_file_bytes:
        raise ReferenceImportError(
            f"ZIP member exceeds max_file_bytes: {info.filename!r}"
        )
    new_total = total_uncompressed + info.file_size
    if new_total > caps.max_total_bytes:
        raise ReferenceImportError("ZIP exceeds max_total_bytes")
    if info.file_size:
        if info.compress_size == 0:
            raise ReferenceImportError(
                f"nonempty ZIP member has zero compressed size: {info.filename!r}"
            )
        ratio = info.file_size / info.compress_size
        if ratio > caps.max_compression_ratio:
            raise ReferenceImportError(
                f"ZIP member exceeds max_compression_ratio: {info.filename!r}"
            )
    return new_total


def _read_zip_member_hash(zf: zipfile.ZipFile, info: zipfile.ZipInfo) -> str:
    digest = hashlib.sha256()
    observed = 0
    try:
        with zf.open(info, "r") as stream:
            while True:
                chunk = stream.read(COPY_CHUNK_BYTES)
                if not chunk:
                    break
                observed += len(chunk)
                digest.update(chunk)
    except (OSError, RuntimeError, NotImplementedError, zipfile.BadZipFile) as exc:
        raise ReferenceImportError(f"cannot CRC-read ZIP member {info.filename!r}: {exc}") from exc
    if observed != info.file_size:
        raise ReferenceImportError(
            f"ZIP size mismatch for {info.filename!r}: {observed} != {info.file_size}"
        )
    return digest.hexdigest()


def _preflight_zip(
    zf: zipfile.ZipFile,
    *,
    archive_root: str,
    caps: ResourceCaps,
) -> tuple[list[ArchiveEntry], list[ArchiveEntry]]:
    infos = zf.infolist()
    if not infos:
        raise ReferenceImportError("ZIP archive is empty")
    if len(infos) > caps.max_entries:
        raise ReferenceImportError("ZIP exceeds max_entries")

    canonical_root = _canonical_repo_relative(archive_root, label="archive root")
    if "/" in canonical_root:
        raise ReferenceImportError("archive root must be exactly one path component")
    exact_seen: dict[str, str] = {}
    portable_seen: dict[str, str] = {}
    header_offsets: set[int] = set()
    file_members: list[str] = []
    included: list[ArchiveEntry] = []
    excluded: list[ArchiveEntry] = []
    total_uncompressed = 0
    saw_root = False

    preflight_rows: list[
        tuple[zipfile.ZipInfo, str, str, bool, str | None, str | None]
    ] = []

    for info in infos:
        raw_name = getattr(info, "orig_filename", info.filename)
        canonical_member, directory_from_name = _canonical_archive_name(raw_name)
        is_directory = _validate_archive_type(info, directory_from_name)

        if info.header_offset in header_offsets:
            raise ReferenceImportError(f"duplicate ZIP local-header offset: {raw_name!r}")
        header_offsets.add(info.header_offset)

        if canonical_member in exact_seen:
            raise ReferenceImportError(
                "ZIP separator/NFC duplicate: "
                f"{exact_seen[canonical_member]!r} and {raw_name!r}"
            )
        exact_seen[canonical_member] = raw_name
        portable_key = _path_collision_key(canonical_member)
        if portable_key in portable_seen:
            raise ReferenceImportError(
                "ZIP casefold/Unicode collision: "
                f"{portable_seen[portable_key]!r} and {raw_name!r}"
            )
        portable_seen[portable_key] = raw_name

        member_parts = PurePosixPath(canonical_member).parts
        if not member_parts or member_parts[0] != canonical_root:
            raise ReferenceImportError(
                f"ZIP member is outside required root {canonical_root!r}: {raw_name!r}"
            )
        if len(member_parts) == 1:
            if not is_directory:
                raise ReferenceImportError("archive root entry must be a directory")
            saw_root = True
            preflight_rows.append((info, raw_name, canonical_member, True, None, None))
            continue

        relative = PurePosixPath(*member_parts[1:]).as_posix()
        if relative == "import_manifest.json" or relative.startswith(
            "import_manifest.json/"
        ):
            raise ReferenceImportError(
                "source archive contains reserved generated import_manifest.json"
            )
        reason = _exclusion_reason(relative)
        staged = (REFERENCE_ROOT / relative).as_posix() if reason is None else None
        if not is_directory:
            total_uncompressed = _check_resource_limits(
                info,
                caps=caps,
                total_uncompressed=total_uncompressed,
            )
            file_members.append(canonical_member)
        preflight_rows.append(
            (info, raw_name, canonical_member, is_directory, staged, reason)
        )

    # A root directory entry is optional in ordinary ZIPs, but at least one
    # child must establish the unique root.
    if not saw_root and not any(
        PurePosixPath(row[2]).parts[0] == canonical_root for row in preflight_rows
    ):
        raise ReferenceImportError(f"ZIP does not contain archive root {canonical_root!r}")

    sorted_files = sorted(file_members)
    for previous, current in zip(sorted_files, sorted_files[1:]):
        if current.startswith(previous + "/"):
            raise ReferenceImportError(
                f"ZIP file/directory prefix conflict: {previous!r} and {current!r}"
            )
    portable_files = sorted(
        (_path_collision_key(member), member) for member in file_members
    )
    for (previous_key, previous), (current_key, current) in zip(
        portable_files, portable_files[1:]
    ):
        if current_key.startswith(previous_key + "/"):
            raise ReferenceImportError(
                "ZIP portable file/directory prefix conflict: "
                f"{previous!r} and {current!r}"
            )

    # CRC-read all files, including excluded noise, before creating output.
    for info, raw_name, canonical_member, is_directory, staged, reason in preflight_rows:
        payload_hash = None if is_directory else _read_zip_member_hash(zf, info)
        entry = ArchiveEntry(
            info=info,
            raw_name=raw_name,
            canonical_member=canonical_member,
            reference_relative=(
                None
                if len(PurePosixPath(canonical_member).parts) == 1
                else PurePosixPath(*PurePosixPath(canonical_member).parts[1:]).as_posix()
            ),
            staged_relative=staged,
            exclusion_reason=reason,
            is_directory=is_directory,
            sha256=payload_hash,
        )
        if is_directory:
            continue
        if reason is None:
            included.append(entry)
        else:
            excluded.append(entry)

    if not included:
        raise ReferenceImportError("ZIP contains no included reference files")
    included.sort(key=lambda item: item.staged_relative or "")
    excluded.sort(key=lambda item: item.canonical_member)
    return included, excluded


def _load_promotion_map(path: Path) -> tuple[list[Promotion], str]:
    value = _read_json_object(path)
    expected_keys = {"schema", "promotions"}
    if set(value) != expected_keys:
        raise ReferenceImportError(
            f"{path}: promotion-map keys must be {sorted(expected_keys)}"
        )
    if value["schema"] != PROMOTION_MAP_SCHEMA:
        raise ReferenceImportError(f"{path}: promotion-map schema mismatch")
    rows = value["promotions"]
    if not isinstance(rows, list):
        raise ReferenceImportError(f"{path}: promotions must be an array")

    promotions: list[Promotion] = []
    destination_seen: dict[str, str] = {}
    portable_seen: dict[str, str] = {}
    for index, row in enumerate(rows):
        if not isinstance(row, dict) or set(row) != {"source_path", "destination_path"}:
            raise ReferenceImportError(
                f"{path}: promotions[{index}] must contain source_path/destination_path"
            )
        source = _canonical_repo_relative(
            row["source_path"], label=f"{path}: promotions[{index}].source_path"
        )
        destination = _canonical_repo_relative(
            row["destination_path"],
            label=f"{path}: promotions[{index}].destination_path",
        )
        if PurePosixPath(destination).parts[0] not in {"artifacts", "spec"}:
            raise ReferenceImportError(
                f"{path}: promotion destination must be under artifacts/ or spec/"
            )
        if len(PurePosixPath(destination).parts) < 2:
            raise ReferenceImportError(
                f"{path}: promotion destination cannot replace a managed root"
            )
        if destination == ROOT_MANIFEST.as_posix():
            raise ReferenceImportError(
                f"{path}: promotion destination is reserved for generated provenance"
            )
        if destination in destination_seen:
            raise ReferenceImportError(
                f"{path}: duplicate promotion destination {destination!r}"
            )
        portable_key = _path_collision_key(destination)
        if portable_key in portable_seen:
            raise ReferenceImportError(
                f"{path}: portable promotion collision between "
                f"{portable_seen[portable_key]!r} and {destination!r}"
            )
        destination_seen[destination] = source
        portable_seen[portable_key] = destination
        promotions.append(Promotion(source, destination))

    promotions.sort(key=lambda item: item.destination)
    portable_destinations = sorted(
        [
            (_path_collision_key(item.destination), item.destination)
            for item in promotions
        ]
        + [
            (
                _path_collision_key(ROOT_MANIFEST.as_posix()),
                ROOT_MANIFEST.as_posix(),
            )
        ]
    )
    for (previous_key, previous), (current_key, current) in zip(
        portable_destinations, portable_destinations[1:]
    ):
        if current_key.startswith(previous_key + "/"):
            raise ReferenceImportError(
                f"{path}: promotion file/directory prefix conflict between "
                f"{previous!r} and {current!r}"
            )
    canonical_map = {
        "promotions": [
            {
                "destination_path": item.destination,
                "source_path": item.source_relative,
            }
            for item in promotions
        ],
        "schema": PROMOTION_MAP_SCHEMA,
    }
    return promotions, hashlib.sha256(_canonical_json(canonical_map)).hexdigest()


def _tree_digest(records: Sequence[dict[str, Any]]) -> str:
    digest = hashlib.sha256()
    digest.update(b"TRECAP_REFERENCE_IMPORT_TREE_V1\0")
    for record in sorted(records, key=lambda item: item["path"]):
        path_bytes = record["path"].encode("utf-8")
        digest.update(len(path_bytes).to_bytes(4, "big"))
        digest.update(path_bytes)
        digest.update(record["size_bytes"].to_bytes(8, "big"))
        digest.update(bytes.fromhex(record["sha256"]))
    return digest.hexdigest()


def _policy_manifest(
    caps: ResourceCaps, *, archive_validation: str
) -> dict[str, Any]:
    return {
        "archive_validation": archive_validation,
        "excluded_directories": sorted(DEFAULT_EXCLUDED_DIRECTORIES),
        "excluded_exact": sorted(DEFAULT_EXCLUDED_EXACT),
        "excluded_suffixes": sorted(DEFAULT_EXCLUDED_SUFFIXES),
        "generated_manifest_paths": sorted(
            path.as_posix() for path in GENERATED_MANIFEST_PATHS
        ),
        "manifest_serialization": "canonical-json-sort-keys-compact-ascii-lf-v1",
        "path_policy": "portable-nfc-casefold-collision-free-v1",
        "payload_policy": "verbatim_bytes_no_newline_or_json_normalization",
        "policy_version": POLICY_VERSION,
        "resource_caps": caps.as_manifest(),
    }


def _file_record_from_archive(entry: ArchiveEntry, *, excluded: bool) -> dict[str, Any]:
    if entry.sha256 is None:
        raise ReferenceImportError("internal error: file record has no payload hash")
    path = (
        (REFERENCE_ROOT / entry.reference_relative).as_posix()
        if excluded and entry.reference_relative is not None
        else entry.staged_relative
    )
    if path is None:
        raise ReferenceImportError("internal error: missing staged path")
    return {
        "archive_member": entry.canonical_member,
        "archive_member_raw": entry.raw_name,
        "class": "[0]",
        "crc32": f"{entry.info.CRC:08x}",
        "origin": "source_archive",
        "path": path,
        "sha256": entry.sha256,
        "size_bytes": entry.info.file_size,
    }


def _promotion_records(
    promotions: Sequence[Promotion],
    imported_by_relative: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for promotion in promotions:
        source_record = imported_by_relative.get(promotion.source_relative)
        if source_record is None:
            raise ReferenceImportError(
                f"promotion source was not imported: {promotion.source_relative}"
            )
        result.append(
            {
                "class": "[0]",
                "operation": "verbatim_copy",
                "path": promotion.destination,
                "sha256": source_record["sha256"],
                "size_bytes": source_record["size_bytes"],
                "source_path": source_record["path"],
            }
        )
    return result


def _build_manifest(
    *,
    provenance_status: str,
    source: dict[str, Any],
    caps: ResourceCaps,
    promotion_map_sha256: str,
    imported_records: list[dict[str, Any]],
    excluded_records: list[dict[str, Any]],
    promoted_records: list[dict[str, Any]],
) -> dict[str, Any]:
    imported_records.sort(key=lambda item: item["path"])
    excluded_records.sort(key=lambda item: item["path"])
    promoted_records.sort(key=lambda item: item["path"])
    return {
        "excluded_member_count": len(excluded_records),
        "excluded_members": excluded_records,
        "file_class": "[2] generated import manifest",
        "import_policy": _policy_manifest(
            caps,
            archive_validation=(
                "complete-central-directory-and-full-member-crc"
                if source["kind"] == "zip"
                else "not_applicable_embedded_proxy"
            ),
        ),
        "imported_reference_file_count": len(imported_records),
        "imported_reference_files": imported_records,
        "imported_tree_sha256": _tree_digest(imported_records),
        "project": PROJECT,
        "promoted_root_file_count": len(promoted_records),
        "promoted_root_files": promoted_records,
        "promoted_tree_sha256": _tree_digest(promoted_records),
        "promotion_map_sha256": promotion_map_sha256,
        "provenance_status": provenance_status,
        "reference_root": REFERENCE_ROOT.as_posix(),
        "schema": MANIFEST_SCHEMA,
        "source": source,
    }


def _safe_output_path(root: Path, relative: str) -> Path:
    canonical = _canonical_repo_relative(relative, label="output path")
    target = root.joinpath(*PurePosixPath(canonical).parts)
    root_resolved = root.resolve()
    try:
        target.resolve(strict=False).relative_to(root_resolved)
    except ValueError as exc:
        raise ReferenceImportError(f"output escapes staging root: {relative}") from exc
    return target


def _extract_archive_entry(
    zf: zipfile.ZipFile,
    entry: ArchiveEntry,
    destination: Path,
) -> None:
    if destination.exists() or destination.is_symlink():
        raise ReferenceImportError(f"refusing to overwrite staged file {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256()
    observed = 0
    try:
        with zf.open(entry.info, "r") as source, destination.open("xb") as output:
            while True:
                chunk = source.read(COPY_CHUNK_BYTES)
                if not chunk:
                    break
                output.write(chunk)
                observed += len(chunk)
                digest.update(chunk)
    except (OSError, RuntimeError, zipfile.BadZipFile) as exc:
        raise ReferenceImportError(
            f"cannot extract ZIP member {entry.raw_name!r}: {exc}"
        ) from exc
    os.chmod(destination, 0o644)
    if observed != entry.info.file_size or digest.hexdigest() != entry.sha256:
        raise ReferenceImportError(
            f"ZIP payload changed between preflight and extraction: {entry.raw_name!r}"
        )


def _write_new_file(path: Path, payload: bytes) -> None:
    if path.exists() or path.is_symlink():
        raise ReferenceImportError(f"refusing to overwrite {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("xb") as stream:
            stream.write(payload)
        os.chmod(path, 0o644)
    except OSError as exc:
        raise ReferenceImportError(f"cannot write {path}: {exc}") from exc


def _materialize_promotions(
    stage_root: Path,
    promotions: Sequence[Promotion],
    imported_by_relative: dict[str, dict[str, Any]],
) -> None:
    for promotion in promotions:
        source_record = imported_by_relative[promotion.source_relative]
        source_path = _safe_output_path(stage_root, source_record["path"])
        destination = _safe_output_path(stage_root, promotion.destination)
        if destination.exists() or destination.is_symlink():
            raise ReferenceImportError(f"refusing to overwrite promotion {destination}")
        destination.parent.mkdir(parents=True, exist_ok=True)
        try:
            shutil.copyfile(source_path, destination, follow_symlinks=False)
            os.chmod(destination, 0o644)
        except OSError as exc:
            raise ReferenceImportError(
                f"cannot materialize promotion {promotion.destination}: {exc}"
            ) from exc
        if (
            destination.stat().st_size != source_record["size_bytes"]
            or _sha256_file(destination) != source_record["sha256"]
        ):
            raise ReferenceImportError(
                f"promotion is not a verbatim copy: {promotion.destination}"
            )


def _stage(args: argparse.Namespace) -> None:
    archive = Path(args.archive)
    output = Path(args.output)
    expected_sha256 = _parse_expected_sha256(args.expected_sha256)
    caps = _caps_from_args(args)
    promotions, promotion_map_sha256 = _load_promotion_map(Path(args.promotion_map))

    if output.exists() or output.is_symlink():
        raise ReferenceImportError(f"stage output must not already exist: {output}")
    if not output.name:
        raise ReferenceImportError("stage output must name a fresh directory")

    try:
        archive_stat = archive.lstat()
    except OSError as exc:
        raise ReferenceImportError(f"cannot stat source archive {archive}: {exc}") from exc
    if stat.S_ISLNK(archive_stat.st_mode) or not stat.S_ISREG(archive_stat.st_mode):
        raise ReferenceImportError("source archive must be a non-symlink regular file")

    temporary: Path | None = None
    with archive.open("rb") as archive_stream:
        opened_stat = os.fstat(archive_stream.fileno())
        actual_sha256 = _sha256_stream(archive_stream)
        if actual_sha256 != expected_sha256:
            raise ReferenceImportError(
                f"source archive SHA-256 mismatch: {actual_sha256} != {expected_sha256}"
            )
        archive_stream.seek(0)
        try:
            zf_context = zipfile.ZipFile(archive_stream, "r")
        except zipfile.BadZipFile as exc:
            raise ReferenceImportError(f"incomplete/invalid ZIP archive: {exc}") from exc

        with zf_context as zf:
            included, excluded = _preflight_zip(
                zf,
                archive_root=args.archive_root,
                caps=caps,
            )

            imported_records = [
                _file_record_from_archive(entry, excluded=False) for entry in included
            ]
            excluded_records = [
                {
                    **_file_record_from_archive(entry, excluded=True),
                    "reason": entry.exclusion_reason,
                }
                for entry in excluded
            ]
            imported_by_relative = {
                PurePosixPath(record["path"])
                .relative_to(REFERENCE_ROOT)
                .as_posix(): record
                for record in imported_records
            }
            promoted_records = _promotion_records(promotions, imported_by_relative)
            manifest = _build_manifest(
                provenance_status="verified_source_archive",
                source={
                    "archive_name": archive.name,
                    "archive_root": args.archive_root,
                    "archive_sha256": actual_sha256,
                    "archive_size_bytes": opened_stat.st_size,
                    "expected_sha256": expected_sha256,
                    "kind": "zip",
                    "verified": True,
                },
                caps=caps,
                promotion_map_sha256=promotion_map_sha256,
                imported_records=imported_records,
                excluded_records=excluded_records,
                promoted_records=promoted_records,
            )
            manifest_bytes = _canonical_json(manifest)

            output_parent = output.parent
            output_parent.mkdir(parents=True, exist_ok=True)
            temporary = Path(
                tempfile.mkdtemp(prefix=f".{output.name}.tmp-", dir=output_parent)
            )
            try:
                for entry in included:
                    if entry.staged_relative is None:
                        raise ReferenceImportError(
                            "internal error: included ZIP member has no staged path"
                        )
                    destination = _safe_output_path(temporary, entry.staged_relative)
                    _extract_archive_entry(zf, entry, destination)
                _materialize_promotions(temporary, promotions, imported_by_relative)
                _write_new_file(
                    _safe_output_path(temporary, INTERNAL_MANIFEST.as_posix()),
                    manifest_bytes,
                )
                _write_new_file(
                    _safe_output_path(temporary, ROOT_MANIFEST.as_posix()),
                    manifest_bytes,
                )

                # Re-hash the same open file descriptor immediately before
                # publication to catch in-place source mutation.
                archive_stream.seek(0)
                final_archive_sha256 = _sha256_stream(archive_stream)
                final_stat = os.fstat(archive_stream.fileno())
                if (
                    final_archive_sha256 != actual_sha256
                    or final_stat.st_size != opened_stat.st_size
                    or final_stat.st_ino != opened_stat.st_ino
                    or final_stat.st_dev != opened_stat.st_dev
                ):
                    raise ReferenceImportError("source archive changed during import")
                if output.exists() or output.is_symlink():
                    raise ReferenceImportError(
                        f"stage output appeared during import: {output}"
                    )
                os.replace(temporary, output)
                temporary = None
            finally:
                if temporary is not None:
                    shutil.rmtree(temporary, ignore_errors=True)

    print(
        "REFERENCE_IMPORT_STAGE_PASS "
        f"files={len(included)} excluded={len(excluded)} "
        f"promotions={len(promotions)} tree_sha256={manifest['imported_tree_sha256']}"
    )


def _hash_proxy_file(path: Path) -> tuple[int, str]:
    try:
        before = path.lstat()
    except OSError as exc:
        raise ReferenceImportError(f"cannot lstat proxy file {path}: {exc}") from exc
    if stat.S_ISLNK(before.st_mode) or not stat.S_ISREG(before.st_mode):
        raise ReferenceImportError(f"proxy special/symlink file is forbidden: {path}")
    try:
        with path.open("rb") as stream:
            opened = os.fstat(stream.fileno())
            digest = _sha256_stream(stream)
            after = os.fstat(stream.fileno())
    except OSError as exc:
        raise ReferenceImportError(f"cannot hash proxy file {path}: {exc}") from exc
    identity_before = (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
    identity_opened = (opened.st_dev, opened.st_ino, opened.st_size, opened.st_mtime_ns)
    identity_after = (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
    if identity_before != identity_opened or identity_opened != identity_after:
        raise ReferenceImportError(f"proxy file changed while hashing: {path}")
    return before.st_size, digest


def _scan_proxy_tree(
    reference_dir: Path,
    *,
    caps: ResourceCaps,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    try:
        root_stat = reference_dir.lstat()
    except OSError as exc:
        raise ReferenceImportError(f"cannot stat proxy reference root: {exc}") from exc
    if stat.S_ISLNK(root_stat.st_mode) or not stat.S_ISDIR(root_stat.st_mode):
        raise ReferenceImportError("proxy reference root must be a non-symlink directory")

    files: list[tuple[str, Path, str | None]] = []
    exact_seen: dict[str, str] = {}
    portable_seen: dict[str, str] = {}
    stack = [reference_dir]
    entry_count = 0

    while stack:
        directory = stack.pop()
        try:
            children = sorted(os.scandir(directory), key=lambda item: item.name)
        except OSError as exc:
            raise ReferenceImportError(f"cannot scan proxy directory {directory}: {exc}") from exc
        for child in children:
            entry_count += 1
            if entry_count > caps.max_entries:
                raise ReferenceImportError("proxy tree exceeds max_entries")
            child_path = Path(child.path)
            relative_raw = child_path.relative_to(reference_dir).as_posix()
            relative = _canonical_repo_relative(
                relative_raw, label=f"proxy path {relative_raw!r}"
            )
            if relative in exact_seen:
                raise ReferenceImportError(f"duplicate proxy path {relative!r}")
            exact_seen[relative] = relative_raw
            portable_key = _path_collision_key(relative)
            if portable_key in portable_seen:
                raise ReferenceImportError(
                    f"proxy casefold/Unicode collision: "
                    f"{portable_seen[portable_key]!r} and {relative!r}"
                )
            portable_seen[portable_key] = relative

            try:
                mode = child.stat(follow_symlinks=False).st_mode
            except OSError as exc:
                raise ReferenceImportError(f"cannot lstat proxy path {child_path}: {exc}") from exc
            if stat.S_ISLNK(mode):
                raise ReferenceImportError(f"proxy symlink is forbidden: {child_path}")
            if relative == "import_manifest.json":
                if not stat.S_ISREG(mode):
                    raise ReferenceImportError(
                        "reserved proxy import_manifest.json must be a regular file"
                    )
                continue
            if relative.startswith("import_manifest.json/"):
                raise ReferenceImportError(
                    "proxy tree conflicts with reserved import_manifest.json"
                )
            if stat.S_ISDIR(mode):
                stack.append(child_path)
                continue
            if not stat.S_ISREG(mode):
                raise ReferenceImportError(f"proxy special file is forbidden: {child_path}")
            files.append((relative, child_path, _exclusion_reason(relative)))

    total_bytes = 0
    imported: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    for relative, path, reason in sorted(files):
        size_bytes, file_hash = _hash_proxy_file(path)
        if size_bytes > caps.max_file_bytes:
            raise ReferenceImportError(f"proxy file exceeds max_file_bytes: {relative}")
        total_bytes += size_bytes
        if total_bytes > caps.max_total_bytes:
            raise ReferenceImportError("proxy tree exceeds max_total_bytes")
        record: dict[str, Any] = {
            "archive_member": None,
            "archive_member_raw": None,
            "class": "[0]",
            "crc32": None,
            "origin": "embedded_proxy",
            "path": (REFERENCE_ROOT / relative).as_posix(),
            "sha256": file_hash,
            "size_bytes": size_bytes,
        }
        if reason is None:
            imported.append(record)
        else:
            record["reason"] = reason
            excluded.append(record)
    if not imported:
        raise ReferenceImportError("proxy tree contains no included reference files")
    return imported, excluded


def _verify_proxy_promotions(
    repo_root: Path,
    promotions: Sequence[Promotion],
    imported_by_relative: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    records = _promotion_records(promotions, imported_by_relative)
    for record in records:
        destination = repo_root.joinpath(*PurePosixPath(record["path"]).parts)
        size_bytes, file_hash = _hash_proxy_file(destination)
        if size_bytes != record["size_bytes"] or file_hash != record["sha256"]:
            raise ReferenceImportError(
                f"proxy promotion is missing or not byte-identical: {record['path']}"
            )
    return records


def _reverify_proxy_snapshot(
    repo_root: Path,
    records: Iterable[dict[str, Any]],
) -> None:
    for record in records:
        path = repo_root.joinpath(*PurePosixPath(record["path"]).parts)
        size_bytes, file_hash = _hash_proxy_file(path)
        if size_bytes != record["size_bytes"] or file_hash != record["sha256"]:
            raise ReferenceImportError(
                f"proxy snapshot changed before manifest publication: {record['path']}"
            )


def _write_manifest_outputs(
    repo_root: Path,
    outputs: Iterable[str],
    payload: bytes,
    *,
    replace: bool,
) -> None:
    resolved_root = repo_root.resolve()
    targets: list[Path] = []
    seen: set[Path] = set()
    for raw_output in outputs:
        candidate = Path(raw_output)
        target = candidate if candidate.is_absolute() else repo_root / candidate
        target = target.resolve(strict=False)
        try:
            relative = target.relative_to(resolved_root)
        except ValueError as exc:
            raise ReferenceImportError(
                f"manifest output must remain under repo root: {target}"
            ) from exc
        relative_posix = relative.as_posix()
        if relative_posix.startswith(REFERENCE_ROOT.as_posix() + "/") and (
            relative_posix != INTERNAL_MANIFEST.as_posix()
        ):
            raise ReferenceImportError(
                "the only generated manifest allowed inside the reference tree is "
                f"{INTERNAL_MANIFEST.as_posix()}"
            )
        if target in seen:
            raise ReferenceImportError(f"duplicate manifest output: {target}")
        seen.add(target)
        if target.is_symlink() or (target.exists() and not replace):
            raise ReferenceImportError(
                f"manifest output exists; use --replace-manifests explicitly: {target}"
            )
        if target.exists() and not target.is_file():
            raise ReferenceImportError(f"manifest output is not a regular file: {target}")
        targets.append(target)

    temporary_files: list[tuple[Path, Path]] = []
    try:
        for target in targets:
            target.parent.mkdir(parents=True, exist_ok=True)
            fd, temporary_name = tempfile.mkstemp(
                prefix=f".{target.name}.tmp-", dir=target.parent
            )
            temporary = Path(temporary_name)
            try:
                with os.fdopen(fd, "wb") as stream:
                    stream.write(payload)
                os.chmod(temporary, 0o644)
            except BaseException:
                temporary.unlink(missing_ok=True)
                raise
            temporary_files.append((temporary, target))
        for temporary, target in temporary_files:
            os.replace(temporary, target)
    finally:
        for temporary, _target in temporary_files:
            temporary.unlink(missing_ok=True)


def _refresh_proxy(args: argparse.Namespace) -> None:
    repo_root = Path(args.repo_root)
    caps = _caps_from_args(args)
    promotions, promotion_map_sha256 = _load_promotion_map(Path(args.promotion_map))
    reference_dir = repo_root.joinpath(*REFERENCE_ROOT.parts)
    imported_records, excluded_records = _scan_proxy_tree(reference_dir, caps=caps)
    imported_by_relative = {
        PurePosixPath(record["path"]).relative_to(REFERENCE_ROOT).as_posix(): record
        for record in imported_records
    }
    promoted_records = _verify_proxy_promotions(
        repo_root, promotions, imported_by_relative
    )
    manifest = _build_manifest(
        provenance_status="embedded_proxy_unverified_source_archive",
        source={
            "kind": "embedded_proxy",
            "proxy_id": args.proxy_id,
            "verified": False,
        },
        caps=caps,
        promotion_map_sha256=promotion_map_sha256,
        imported_records=imported_records,
        excluded_records=excluded_records,
        promoted_records=promoted_records,
    )
    payload = _canonical_json(manifest)
    _reverify_proxy_snapshot(
        repo_root,
        [
            *imported_records,
            *excluded_records,
            *promoted_records,
        ],
    )
    _write_manifest_outputs(
        repo_root,
        args.output_manifest,
        payload,
        replace=args.replace_manifests,
    )
    print(
        "REFERENCE_IMPORT_PROXY_PASS "
        f"files={len(imported_records)} excluded={len(excluded_records)} "
        f"promotions={len(promotions)} tree_sha256={manifest['imported_tree_sha256']} "
        "source_archive_verified=false"
    )


def _caps_from_args(args: argparse.Namespace) -> ResourceCaps:
    caps = ResourceCaps(
        max_entries=args.max_entries,
        max_file_bytes=args.max_file_bytes,
        max_total_bytes=args.max_total_bytes,
        max_compression_ratio=args.max_compression_ratio,
    )
    caps.validate()
    return caps


def _add_resource_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--max-entries", type=int, default=DEFAULT_MAX_ENTRIES)
    parser.add_argument("--max-file-bytes", type=int, default=DEFAULT_MAX_FILE_BYTES)
    parser.add_argument("--max-total-bytes", type=int, default=DEFAULT_MAX_TOTAL_BYTES)
    parser.add_argument(
        "--max-compression-ratio",
        type=float,
        default=DEFAULT_MAX_COMPRESSION_RATIO,
    )


def _argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Fail-closed Phase 2 reference import/provenance tool"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    stage = subparsers.add_parser(
        "stage",
        help="import a complete, independently hash-pinned ZIP into a fresh tree",
    )
    stage.add_argument("--archive", required=True)
    stage.add_argument(
        "--expected-sha256",
        required=True,
        help="independently supplied SHA-256; never inferred from the archive",
    )
    stage.add_argument("--output", required=True, help="fresh staging directory")
    stage.add_argument(
        "--promotion-map",
        required=True,
        help=(
            "v1 JSON map: source_path is relative to sw/reference_model; "
            "destination_path is repository-relative"
        ),
    )
    stage.add_argument("--archive-root", default=DEFAULT_ARCHIVE_ROOT)
    _add_resource_arguments(stage)
    stage.set_defaults(handler=_stage)

    proxy = subparsers.add_parser(
        "refresh-proxy",
        help="build a v3 manifest without claiming source-archive verification",
    )
    proxy.add_argument("--repo-root", required=True)
    proxy.add_argument(
        "--promotion-map",
        required=True,
        help=(
            "v1 JSON map: source_path is relative to sw/reference_model; "
            "destination_path is repository-relative"
        ),
    )
    proxy.add_argument(
        "--proxy-id",
        required=True,
        help="stable caller-supplied identity for the embedded proxy",
    )
    proxy.add_argument(
        "--output-manifest",
        action="append",
        required=True,
        help="repo-relative output; repeat to write byte-identical manifest copies",
    )
    proxy.add_argument(
        "--replace-manifests",
        action="store_true",
        help="explicitly permit replacement of existing regular manifest files",
    )
    _add_resource_arguments(proxy)
    proxy.set_defaults(handler=_refresh_proxy)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _argument_parser()
    args = parser.parse_args(argv)
    try:
        args.handler(args)
    except (
        ReferenceImportError,
        OSError,
        RuntimeError,
        zipfile.BadZipFile,
    ) as exc:
        print(f"REFERENCE_IMPORT_ERROR: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
