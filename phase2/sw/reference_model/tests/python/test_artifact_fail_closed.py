# SPDX-License-Identifier: MIT
"""Negative regressions for the fail-closed artifact and release checker."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from trecap_golden.artifacts.checker import CheckReport, check_artifact_tree
from trecap_golden.artifacts.csv_io import (
    BIN_STATS_HEADER,
    FRAME_STATS_HEADER,
    CsvArtifactError,
    read_bin_stats,
    read_frame_stats,
)

REFERENCE_ROOT = Path(__file__).resolve().parents[2]
ARCHITECTURE_ROOT = REFERENCE_ROOT.parents[1]
EMBEDDED_ARTIFACTS = REFERENCE_ROOT / "artifacts"
PROMOTED_ARTIFACTS = ARCHITECTURE_ROOT / "artifacts"
REFERENCE_SCHEMAS = REFERENCE_ROOT / "spec" / "schemas"
PROMOTED_SCHEMAS = ARCHITECTURE_ROOT / "spec" / "schemas"
CHECKER_CLI = REFERENCE_ROOT / "tools" / "artifact_check.py"
ZERO_SHA256 = "0" * 64
BIN_VECTOR = "near_threshold_multitone_Ns1024_thr64"
FRAME_STATS_HEADER_TEXT = ",".join(FRAME_STATS_HEADER)
BIN_STATS_HEADER_TEXT = ",".join(BIN_STATS_HEADER)
CANONICAL_FRAME_ROW = "0,129,0,128,0,9784442009068,9784442009068"
CANONICAL_BIN_ROW = "0,0,-1,0,1,0,0,0"
CANONICAL_FRAME_CSV = f"{FRAME_STATS_HEADER_TEXT}\n{CANONICAL_FRAME_ROW}\n".encode()


def _copy_artifacts(tmp_path: Path, source: Path = EMBEDDED_ARTIFACTS) -> Path:
    destination = tmp_path / "artifacts"
    shutil.copytree(source, destination, symlinks=True)
    return destination


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(value, indent=2, sort_keys=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _check(
    artifacts: Path,
    *,
    output_subdir: str = "golden",
    schemas: Path = REFERENCE_SCHEMAS,
) -> CheckReport:
    return check_artifact_tree(
        artifacts,
        schemas_dir=schemas,
        output_subdir=output_subdir,
        source_root=REFERENCE_ROOT,
        require_frozen=True,
    )


def _issue_text(report: CheckReport) -> str:
    return "\n".join(f"{issue.path} {issue.check} {issue.message}" for issue in report.issues)


def _assert_passes(report: CheckReport) -> None:
    assert report.ok, json.dumps(report.to_dict(), indent=2, sort_keys=True)


def _assert_fails(report: CheckReport, expected_text: str) -> None:
    assert not report.ok, "corrupted artifact tree unexpectedly passed"
    text = _issue_text(report)
    assert expected_text.lower() in text.lower(), text


def _find_entry(manifest: dict[str, Any], logical_path: str) -> dict[str, Any]:
    entries = manifest.get("artifacts")
    assert isinstance(entries, list)
    matches = [
        entry for entry in entries if isinstance(entry, dict) and entry.get("path") == logical_path
    ]
    assert len(matches) == 1
    return matches[0]


def test_csv_canonical_files_parse(tmp_path: Path) -> None:
    frame_path = tmp_path / "frame_stats.csv"
    bin_path = tmp_path / "bin_stats.csv"
    frame_path.write_bytes(CANONICAL_FRAME_CSV)
    bin_path.write_bytes(f"{BIN_STATS_HEADER_TEXT}\n{CANONICAL_BIN_ROW}\n".encode())

    frame_result = read_frame_stats(frame_path, expected_rows=1)
    bin_result = read_bin_stats(bin_path, expected_rows=1)

    assert frame_result.rows == (
        {
            "frame_idx": 0,
            "unique_bins": 129,
            "unique_suppressed_bins": 0,
            "eligible_unique_bins": 128,
            "eligible_suppressed_bins": 0,
            "eligible_kept_mag2": 9784442009068,
            "eligible_total_mag2": 9784442009068,
        },
    )
    assert bin_result.rows == (
        {
            "frame_idx": 0,
            "bin_idx": 0,
            "real": -1,
            "imag": 0,
            "mag2": 1,
            "eligible": 0,
            "pre_mask": 0,
            "mask": 0,
        },
    )


@pytest.mark.parametrize(
    ("row", "expected_text"),
    [
        (f"{CANONICAL_FRAME_ROW},0", "expected 7 cells, got 8"),
        (CANONICAL_FRAME_ROW.rsplit(",", 1)[0], "expected 7 cells, got 6"),
    ],
    ids=["extra-cell", "missing-cell"],
)
def test_csv_rejects_wrong_cell_count(
    tmp_path: Path,
    row: str,
    expected_text: str,
) -> None:
    path = tmp_path / "frame_stats.csv"
    path.write_bytes(f"{FRAME_STATS_HEADER_TEXT}\n{row}\n".encode())

    with pytest.raises(CsvArtifactError) as exc_info:
        read_frame_stats(path)

    assert expected_text in str(exc_info.value)


def test_csv_rejects_blank_physical_line(tmp_path: Path) -> None:
    path = tmp_path / "frame_stats.csv"
    path.write_bytes(f"{FRAME_STATS_HEADER_TEXT}\n\n{CANONICAL_FRAME_ROW}\n".encode())

    with pytest.raises(CsvArtifactError) as exc_info:
        read_frame_stats(path)

    assert "blank physical line" in str(exc_info.value)


@pytest.mark.parametrize(
    ("payload", "expected_text"),
    [
        (CANONICAL_FRAME_CSV.replace(b"\n", b"\r\n"), "CR/CRLF"),
        (b"\xef\xbb\xbf" + CANONICAL_FRAME_CSV, "BOM"),
        (CANONICAL_FRAME_CSV[:-1], "must end with LF"),
    ],
    ids=["crlf", "utf8-bom", "no-final-lf"],
)
def test_csv_rejects_noncanonical_bytes(
    tmp_path: Path,
    payload: bytes,
    expected_text: str,
) -> None:
    path = tmp_path / "frame_stats.csv"
    path.write_bytes(payload)

    with pytest.raises(CsvArtifactError) as exc_info:
        read_frame_stats(path)

    assert expected_text in str(exc_info.value)


@pytest.mark.parametrize("bad_integer", ["01", "+1", "-0"])
def test_csv_rejects_noncanonical_integer(
    tmp_path: Path,
    bad_integer: str,
) -> None:
    path = tmp_path / "bin_stats.csv"
    path.write_bytes(f"{BIN_STATS_HEADER_TEXT}\n0,0,{bad_integer},0,1,0,0,0\n".encode())

    with pytest.raises(CsvArtifactError) as exc_info:
        read_bin_stats(path)

    assert "not canonical signed decimal" in str(exc_info.value)


def test_csv_current_frozen_files_remain_valid() -> None:
    frame_path = EMBEDDED_ARTIFACTS / "golden" / BIN_VECTOR / "frame_stats.csv"
    bin_path = EMBEDDED_ARTIFACTS / "golden" / BIN_VECTOR / "bin_stats.csv"

    assert read_frame_stats(frame_path).data_rows == 9
    assert read_bin_stats(bin_path).data_rows == 1161


def test_embedded_frozen_artifact_tree_passes() -> None:
    _assert_passes(_check(EMBEDDED_ARTIFACTS))


def test_promoted_reference_outputs_tree_passes() -> None:
    _assert_passes(
        _check(
            PROMOTED_ARTIFACTS,
            output_subdir="reference_outputs",
            schemas=PROMOTED_SCHEMAS,
        )
    )


def test_direct_cli_fails_when_jsonschema_is_unavailable() -> None:
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    env.pop("PYTHONHOME", None)
    env["PYTHONNOUSERSITE"] = "1"
    result = subprocess.run(
        [
            sys.executable,
            "-S",
            str(CHECKER_CLI),
            "--artifacts",
            str(EMBEDDED_ARTIFACTS),
            "--schemas",
            str(REFERENCE_SCHEMAS),
            "--output-subdir",
            "golden",
            "--source-root",
            str(REFERENCE_ROOT),
        ],
        cwd=REFERENCE_ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    output = result.stdout + result.stderr
    assert result.returncode == 2, output
    assert "jsonschema is required" in output
    assert "artifact_check: OK" not in output


def test_missing_required_schema_fails(tmp_path: Path) -> None:
    artifacts = _copy_artifacts(tmp_path)
    schemas = tmp_path / "schemas"
    shutil.copytree(REFERENCE_SCHEMAS, schemas)
    (schemas / "artifact_index.schema.json").unlink()

    _assert_fails(
        _check(artifacts, schemas=schemas),
        "schema_required",
    )


def test_duplicate_json_key_fails(tmp_path: Path) -> None:
    artifacts = _copy_artifacts(tmp_path)
    metrics = artifacts / "golden" / "impulse_Ns1024_thr0" / "metrics.json"
    original = metrics.read_text(encoding="utf-8")
    corrupted = original.replace(
        '{\n  "schema":',
        '{\n  "schema": "trecap_invalid_duplicate",\n  "schema":',
        1,
    )
    assert corrupted != original
    metrics.write_text(corrupted, encoding="utf-8", newline="\n")

    _assert_fails(_check(artifacts), "duplicate JSON key")


@pytest.mark.parametrize(
    ("relative_path", "expected_text"),
    [
        ("manifests/core_config_snapshot.json", "core_config_snapshot.json"),
        ("manifests/artifact_index.json", "artifact_index.json"),
        ("manifests/frozen_release_manifest.json", "frozen_release_manifest.json"),
    ],
)
def test_missing_required_release_file_fails(
    tmp_path: Path,
    relative_path: str,
    expected_text: str,
) -> None:
    artifacts = _copy_artifacts(tmp_path)
    (artifacts / relative_path).unlink()

    _assert_fails(_check(artifacts), expected_text)


@pytest.mark.parametrize(
    "hash_field",
    [
        "metrics_sha256",
        "frame_stats_sha256",
        "bin_stats_sha256",
    ],
)
def test_corrupted_vector_raw_hash_fails(tmp_path: Path, hash_field: str) -> None:
    artifacts = _copy_artifacts(tmp_path)
    manifest_path = artifacts / "test_vectors" / "test_vectors.json"
    manifest = _read_json(manifest_path)
    entries = manifest.get("vectors")
    assert isinstance(entries, list)
    vector = next(
        entry for entry in entries if isinstance(entry, dict) and entry.get("name") == BIN_VECTOR
    )
    vector[hash_field] = ZERO_SHA256
    _write_json(manifest_path, manifest)

    _assert_fails(_check(artifacts), f"{BIN_VECTOR}.{hash_field}")


def test_corrupted_index_named_hash_fails(tmp_path: Path) -> None:
    artifacts = _copy_artifacts(tmp_path)
    index_path = artifacts / "manifests" / "artifact_index.json"
    index = _read_json(index_path)
    index["core_config_sha256"] = ZERO_SHA256
    _write_json(index_path, index)

    _assert_fails(_check(artifacts), "core_config_sha256")


def test_dangling_index_path_fails(tmp_path: Path) -> None:
    artifacts = _copy_artifacts(tmp_path)
    index_path = artifacts / "manifests" / "artifact_index.json"
    index = _read_json(index_path)
    entry = _find_entry(index, "artifacts/coefficients/coeff_manifest.json")
    entry["path"] = "artifacts/coefficients/missing.json"
    _write_json(index_path, index)

    _assert_fails(_check(artifacts), "missing indexed artifact")


def test_backslash_index_path_fails(tmp_path: Path) -> None:
    artifacts = _copy_artifacts(tmp_path)
    index_path = artifacts / "manifests" / "artifact_index.json"
    index = _read_json(index_path)
    entry = _find_entry(index, "artifacts/coefficients/coeff_manifest.json")
    entry["path"] = r"artifacts\coefficients\coeff_manifest.json"
    _write_json(index_path, index)

    _assert_fails(_check(artifacts), "backslash")


def test_symlink_index_path_fails(tmp_path: Path) -> None:
    artifacts = _copy_artifacts(tmp_path)
    symlink = artifacts / "linked_coeff_manifest.json"
    try:
        symlink.symlink_to("coefficients/coeff_manifest.json")
    except OSError as exc:
        pytest.skip(f"symlink creation is unavailable: {exc}")

    index_path = artifacts / "manifests" / "artifact_index.json"
    index = _read_json(index_path)
    entry = _find_entry(index, "artifacts/coefficients/coeff_manifest.json")
    entry["path"] = "artifacts/linked_coeff_manifest.json"
    _write_json(index_path, index)

    _assert_fails(_check(artifacts), "symlinks are forbidden")


def test_unindexed_symlink_fails(tmp_path: Path) -> None:
    artifacts = _copy_artifacts(tmp_path)
    symlink = artifacts / "untracked.json"
    try:
        symlink.symlink_to("coefficients/coeff_manifest.json")
    except OSError as exc:
        pytest.skip(f"symlink creation is unavailable: {exc}")

    _assert_fails(_check(artifacts), "symlinks are forbidden")


def test_release_manifest_symlink_fails(tmp_path: Path) -> None:
    artifacts = _copy_artifacts(tmp_path)
    release = artifacts / "manifests" / "frozen_release_manifest.json"
    authority = tmp_path / "release-authority.json"
    shutil.copyfile(release, authority)
    release.unlink()
    try:
        release.symlink_to(authority)
    except OSError as exc:
        pytest.skip(f"symlink creation is unavailable: {exc}")

    _assert_fails(_check(artifacts), "symlinks are forbidden")


def test_extra_unindexed_artifact_fails(tmp_path: Path) -> None:
    artifacts = _copy_artifacts(tmp_path)
    extra = artifacts / "coefficients" / "unindexed.json"
    _write_json(extra, {"schema": "unindexed_test_artifact"})

    _assert_fails(_check(artifacts), "complete artifact inventory")


def test_nonempty_gitkeep_fails(tmp_path: Path) -> None:
    artifacts = _copy_artifacts(tmp_path, PROMOTED_ARTIFACTS)
    (artifacts / "coefficients" / ".gitkeep").write_bytes(b"unauthenticated")

    _assert_fails(
        _check(
            artifacts,
            output_subdir="reference_outputs",
            schemas=PROMOTED_SCHEMAS,
        ),
        "exactly zero bytes",
    )


def test_artifact_tree_rejects_portable_directory_collision(
    tmp_path: Path,
) -> None:
    artifacts = _copy_artifacts(tmp_path)
    (artifacts / "Foo").mkdir()
    (artifacts / "foo").mkdir()

    _assert_fails(_check(artifacts), "portable path collision")


def test_artifact_tree_rejects_windows_reserved_directory(
    tmp_path: Path,
) -> None:
    artifacts = _copy_artifacts(tmp_path)
    (artifacts / "NUL").mkdir()

    _assert_fails(_check(artifacts), "Windows-reserved")


def test_self_consistent_unknown_json_artifact_fails(tmp_path: Path) -> None:
    artifacts = _copy_artifacts(tmp_path)
    evil_path = artifacts / "debug" / "evil.json"
    evil_path.parent.mkdir()
    evil_path.write_bytes(b"{this is not json\n")
    evil_sha256 = hashlib.sha256(evil_path.read_bytes()).hexdigest()
    evil_entry = {
        "path": "artifacts/debug/evil.json",
        "role": "debug",
        "artifact_type": "json",
        "sha256": evil_sha256,
        "canonicalized": False,
        "required": True,
        "producer": "forged test producer",
        "schema_ref": "unvalidated_json",
        "content_contract": "json_schema_validated",
    }

    index_path = artifacts / "manifests" / "artifact_index.json"
    release_path = artifacts / "manifests" / "frozen_release_manifest.json"
    index = _read_json(index_path)
    release = _read_json(release_path)
    index_entries = index.get("artifacts")
    release_entries = release.get("artifacts")
    assert isinstance(index_entries, list)
    assert isinstance(release_entries, list)
    index_entries.append(dict(evil_entry))
    release_entries.append(dict(evil_entry))
    _write_json(index_path, index)
    index_sha256 = hashlib.sha256(index_path.read_bytes()).hexdigest()
    manifest_hashes = release.get("manifest_hashes")
    assert isinstance(manifest_hashes, dict)
    manifest_hashes["artifact_index_sha256"] = index_sha256
    index_entry = _find_entry(release, "artifacts/manifests/artifact_index.json")
    index_entry["sha256"] = index_sha256
    _write_json(release_path, release)

    _assert_fails(_check(artifacts), "unknown JSON artifact path")


@pytest.mark.parametrize(
    "name",
    [
        "artifact_index.json",
        "frozen_release_manifest.json",
        "reference_import_manifest.json",
    ],
)
def test_release_basename_outside_manifest_directory_is_unindexed(
    tmp_path: Path,
    name: str,
) -> None:
    artifacts = _copy_artifacts(tmp_path)
    extra = artifacts / "coefficients" / name
    _write_json(extra, {"schema": "unindexed_release_basename"})

    _assert_fails(_check(artifacts), "complete artifact inventory")


def test_release_and_index_entry_set_mismatch_fails(tmp_path: Path) -> None:
    artifacts = _copy_artifacts(tmp_path)
    release_path = artifacts / "manifests" / "frozen_release_manifest.json"
    release = _read_json(release_path)
    entries = release.get("artifacts")
    assert isinstance(entries, list)
    assert len(entries) > 1
    entries.pop()
    _write_json(release_path, release)

    _assert_fails(_check(artifacts), "release/index entry set")


def test_release_and_index_metadata_mismatch_fails(tmp_path: Path) -> None:
    artifacts = _copy_artifacts(tmp_path)
    index_path = artifacts / "manifests" / "artifact_index.json"
    release_path = artifacts / "manifests" / "frozen_release_manifest.json"
    index = _read_json(index_path)
    release = _read_json(release_path)
    index["release_name"] = "forged_index_release_name"
    _write_json(index_path, index)
    index_sha256 = hashlib.sha256(index_path.read_bytes()).hexdigest()
    manifest_hashes = release.get("manifest_hashes")
    assert isinstance(manifest_hashes, dict)
    manifest_hashes["artifact_index_sha256"] = index_sha256
    index_entry = _find_entry(release, "artifacts/manifests/artifact_index.json")
    index_entry["sha256"] = index_sha256
    _write_json(release_path, release)

    _assert_fails(_check(artifacts), "metadata equality release_name")


def test_vector_manifest_configuration_mismatch_fails(tmp_path: Path) -> None:
    artifacts = _copy_artifacts(tmp_path)
    manifest_path = artifacts / "test_vectors" / "test_vectors.json"
    manifest = _read_json(manifest_path)
    vectors = manifest.get("vectors")
    assert isinstance(vectors, list)
    vector = next(
        entry
        for entry in vectors
        if isinstance(entry, dict)
        and entry.get("name") == "impulse_Ns1024_thr0"
    )
    vector["THR2"] = "1"
    _write_json(manifest_path, manifest)

    _assert_fails(
        _check(artifacts),
        "impulse_Ns1024_thr0.THR2/config",
    )


def test_promoted_tree_rejects_stale_golden_paths(tmp_path: Path) -> None:
    artifacts = _copy_artifacts(tmp_path, PROMOTED_ARTIFACTS)
    index_path = artifacts / "manifests" / "artifact_index.json"
    release_path = artifacts / "manifests" / "frozen_release_manifest.json"
    index = _read_json(index_path)
    release = _read_json(release_path)

    for manifest in (index, release):
        entries = manifest.get("artifacts")
        assert isinstance(entries, list)
        changed = 0
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            logical = entry.get("path")
            if isinstance(logical, str) and logical.startswith("artifacts/reference_outputs/"):
                entry["path"] = logical.replace(
                    "artifacts/reference_outputs/",
                    "artifacts/golden/",
                    1,
                )
                changed += 1
        assert changed == 10

    _write_json(index_path, index)
    index_sha256 = hashlib.sha256(index_path.read_bytes()).hexdigest()
    manifest_hashes = release.get("manifest_hashes")
    assert isinstance(manifest_hashes, dict)
    manifest_hashes["artifact_index_sha256"] = index_sha256
    index_entry = _find_entry(release, "artifacts/manifests/artifact_index.json")
    index_entry["sha256"] = index_sha256
    _write_json(release_path, release)

    _assert_fails(
        _check(
            artifacts,
            output_subdir="reference_outputs",
            schemas=PROMOTED_SCHEMAS,
        ),
        "artifacts/golden/",
    )
