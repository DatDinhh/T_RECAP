from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
import zipfile


REPO_ROOT = Path(__file__).resolve().parents[1]
REFERENCE_PYTHON = REPO_ROOT / "sw" / "reference_model" / "python"
if str(REFERENCE_PYTHON) not in sys.path:
    sys.path.insert(0, str(REFERENCE_PYTHON))

from trecap_golden.artifacts.checker import (  # noqa: E402
    CheckReport,
    check_reference_import_manifest,
)


class ReferenceHashChainTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.repo = Path(self.temporary.name) / "repo"
        self.reference_root = self.repo / "sw" / "reference_model"
        shutil.copytree(
            REPO_ROOT / "sw" / "reference_model",
            self.reference_root,
            ignore=shutil.ignore_patterns(
                ".pytest_cache",
                ".ruff_cache",
                ".venv",
                "__pycache__",
                "build",
                "out",
                "runs",
                "*.pyc",
                "*.pyo",
            ),
        )

        self.manifest_path = (
            self.repo / "artifacts" / "manifests" / "reference_import_manifest.json"
        )
        self.manifest_path.parent.mkdir(parents=True)
        shutil.copyfile(
            REPO_ROOT / "artifacts" / "manifests" / "reference_import_manifest.json",
            self.manifest_path,
        )
        self.schema_dir = self.repo / "spec" / "schemas"
        self.schema_dir.mkdir(parents=True)
        shutil.copyfile(
            REPO_ROOT / "spec" / "schemas" / "reference_import_manifest.schema.json",
            self.schema_dir / "reference_import_manifest.schema.json",
        )
        promotion_map = self.repo / "config" / "reference_import_promotions.json"
        promotion_map.parent.mkdir(parents=True)
        shutil.copyfile(
            REPO_ROOT / "config" / "reference_import_promotions.json",
            promotion_map,
        )

        manifest = self._manifest()
        for record in manifest["promoted_root_files"]:
            destination = self.repo.joinpath(*Path(record["path"]).parts)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(
                REPO_ROOT.joinpath(*Path(record["path"]).parts),
                destination,
            )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _manifest(self) -> dict[str, object]:
        return json.loads(self.manifest_path.read_text(encoding="ascii"))

    def _write_manifest_copies(self, value: dict[str, object]) -> None:
        payload = (
            json.dumps(
                value,
                allow_nan=False,
                ensure_ascii=True,
                separators=(",", ":"),
                sort_keys=True,
            )
            + "\n"
        )
        self.manifest_path.write_text(payload, encoding="ascii", newline="\n")
        (self.reference_root / "import_manifest.json").write_text(
            payload,
            encoding="ascii",
            newline="\n",
        )

    @staticmethod
    def _tree_digest(records: list[dict[str, object]]) -> str:
        digest = hashlib.sha256()
        digest.update(b"TRECAP_REFERENCE_IMPORT_TREE_V1\0")
        for record in sorted(records, key=lambda item: str(item["path"])):
            path_bytes = str(record["path"]).encode("utf-8")
            digest.update(len(path_bytes).to_bytes(4, "big"))
            digest.update(path_bytes)
            digest.update(int(record["size_bytes"]).to_bytes(8, "big"))
            digest.update(bytes.fromhex(str(record["sha256"])))
        return digest.hexdigest()

    @staticmethod
    def _canonical_json_hash(value: object) -> str:
        payload = (
            json.dumps(
                value,
                allow_nan=False,
                ensure_ascii=True,
                separators=(",", ":"),
                sort_keys=True,
            )
            + "\n"
        ).encode("ascii")
        return hashlib.sha256(payload).hexdigest()

    def _check(
        self,
        *,
        require_verified_source: bool = False,
        source_archive: Path | None = None,
    ) -> CheckReport:
        report = CheckReport(self.repo / "artifacts")
        return check_reference_import_manifest(
            self.repo,
            self.manifest_path,
            schemas_dir=self.schema_dir,
            require_verified_source=require_verified_source,
            source_archive=source_archive,
            report=report,
        )

    def test_current_proxy_chain_passes(self) -> None:
        report = self._check()
        self.assertTrue(report.ok, report.to_dict())
        self.assertEqual(report.checked["imported_files"], 214)
        self.assertEqual(report.checked["promoted_files"], 39)

    def test_signoff_gate_rejects_unverified_proxy(self) -> None:
        report = self._check(require_verified_source=True)
        self.assertFalse(report.ok)
        self.assertIn("source_provenance", {issue.check for issue in report.issues})

    def test_corrupt_imported_file_is_rejected(self) -> None:
        target = self.reference_root / "README.md"
        target.write_bytes(target.read_bytes() + b"\ncorrupt")
        report = self._check()
        self.assertFalse(report.ok)
        self.assertTrue(
            any(
                issue.check.endswith(".sha256") or issue.check == "complete imported inventory"
                for issue in report.issues
            )
        )

    def test_missing_imported_file_is_rejected(self) -> None:
        (self.reference_root / "LICENSE").unlink()
        report = self._check()
        self.assertFalse(report.ok)
        self.assertIn("imported_file", {issue.check for issue in report.issues})

    def test_symlinked_promotion_is_rejected(self) -> None:
        destination = self.repo / "artifacts" / "coefficients" / "window_qw.memh"
        destination.unlink()
        destination.symlink_to(
            self.reference_root / "artifacts" / "coefficients" / "window_qw.memh"
        )
        report = self._check()
        self.assertFalse(report.ok)
        self.assertIn("promotion_destination", {issue.check for issue in report.issues})

    def test_tampered_promotion_map_is_rejected(self) -> None:
        path = self.repo / "config" / "reference_import_promotions.json"
        value = json.loads(path.read_text(encoding="utf-8"))
        value["promotions"][0]["destination_path"] = (
            "artifacts/coefficients/not-the-manifest.json"
        )
        path.write_text(json.dumps(value) + "\n", encoding="utf-8", newline="\n")
        report = self._check()
        self.assertFalse(report.ok)
        self.assertIn("promotion_map_sha256", {issue.check for issue in report.issues})

    def test_duplicate_json_key_is_rejected(self) -> None:
        payload = self.manifest_path.read_text(encoding="ascii")
        tampered = payload.replace(
            '{"excluded_member_count":0,',
            '{"excluded_member_count":0,"excluded_member_count":0,',
            1,
        )
        self.manifest_path.write_text(tampered, encoding="ascii", newline="\n")
        (self.reference_root / "import_manifest.json").write_text(
            tampered,
            encoding="ascii",
            newline="\n",
        )
        report = self._check()
        self.assertFalse(report.ok)
        self.assertIn("strict_json", {issue.check for issue in report.issues})

    def test_fabricated_excluded_proxy_record_is_rejected(self) -> None:
        manifest = self._manifest()
        excluded = manifest["excluded_members"]
        self.assertIsInstance(excluded, list)
        excluded.append(
            {
                "archive_member": None,
                "archive_member_raw": None,
                "class": "[0]",
                "crc32": None,
                "origin": "embedded_proxy",
                "path": "sw/reference_model/fabricated.pyc",
                "reason": "excluded_suffix:.pyc",
                "sha256": hashlib.sha256(b"fabricated").hexdigest(),
                "size_bytes": len(b"fabricated"),
            }
        )
        manifest["excluded_member_count"] = len(excluded)
        self._write_manifest_copies(manifest)

        report = self._check()

        self.assertFalse(report.ok)
        self.assertIn(
            "complete excluded inventory",
            {issue.check for issue in report.issues},
        )

    def test_promotion_map_schema_is_checked_after_hash_match(self) -> None:
        map_path = self.repo / "config" / "reference_import_promotions.json"
        promotion_map = json.loads(map_path.read_text(encoding="utf-8"))
        promotion_map["schema"] = "forged_schema"
        promotion_map["unexpected"] = True
        map_path.write_text(
            json.dumps(promotion_map, sort_keys=True) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        manifest = self._manifest()
        manifest["promotion_map_sha256"] = self._canonical_json_hash(promotion_map)
        self._write_manifest_copies(manifest)

        report = self._check()

        self.assertFalse(report.ok)
        self.assertIn("promotion_map", {issue.check for issue in report.issues})

    def test_proxy_casefold_collision_is_rejected(self) -> None:
        source = self.reference_root / "README.md"
        collision = self.reference_root / "README.MD"
        collision.write_bytes(source.read_bytes())
        manifest = self._manifest()
        imported = manifest["imported_reference_files"]
        self.assertIsInstance(imported, list)
        payload = collision.read_bytes()
        imported.append(
            {
                "archive_member": None,
                "archive_member_raw": None,
                "class": "[0]",
                "crc32": None,
                "origin": "embedded_proxy",
                "path": "sw/reference_model/README.MD",
                "sha256": hashlib.sha256(payload).hexdigest(),
                "size_bytes": len(payload),
            }
        )
        manifest["imported_reference_file_count"] = len(imported)
        manifest["imported_tree_sha256"] = self._tree_digest(imported)
        self._write_manifest_copies(manifest)

        report = self._check()

        self.assertFalse(report.ok)
        self.assertIn(
            "imported_inventory_collision",
            {issue.check for issue in report.issues},
        )

    def test_proxy_file_size_cap_is_checked_before_hashing(self) -> None:
        oversized = self.reference_root / "oversized.bin"
        with oversized.open("wb") as stream:
            stream.truncate(128 * 1024 * 1024 + 1)

        report = self._check()

        self.assertFalse(report.ok)
        self.assertIn(
            "imported_inventory_caps",
            {issue.check for issue in report.issues},
        )

    def test_excluded_file_cannot_be_promoted(self) -> None:
        payload = b"excluded bytecode"
        excluded_path = self.reference_root / "loose.pyc"
        excluded_path.write_bytes(payload)
        destination = (
            self.repo / "artifacts" / "reference_outputs" / "excluded-copy.pyc"
        )
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(payload)

        map_path = self.repo / "config" / "reference_import_promotions.json"
        promotion_map = json.loads(map_path.read_text(encoding="utf-8"))
        promotion_map["promotions"].append(
            {
                "source_path": "loose.pyc",
                "destination_path": (
                    "artifacts/reference_outputs/excluded-copy.pyc"
                ),
            }
        )
        map_path.write_text(
            json.dumps(promotion_map, sort_keys=True) + "\n",
            encoding="utf-8",
            newline="\n",
        )

        manifest = self._manifest()
        excluded = manifest["excluded_members"]
        promoted = manifest["promoted_root_files"]
        self.assertIsInstance(excluded, list)
        self.assertIsInstance(promoted, list)
        file_hash = hashlib.sha256(payload).hexdigest()
        excluded.append(
            {
                "archive_member": None,
                "archive_member_raw": None,
                "class": "[0]",
                "crc32": None,
                "origin": "embedded_proxy",
                "path": "sw/reference_model/loose.pyc",
                "reason": "excluded_suffix:.pyc",
                "sha256": file_hash,
                "size_bytes": len(payload),
            }
        )
        promoted.append(
            {
                "class": "[0]",
                "operation": "verbatim_copy",
                "path": "artifacts/reference_outputs/excluded-copy.pyc",
                "sha256": file_hash,
                "size_bytes": len(payload),
                "source_path": "sw/reference_model/loose.pyc",
            }
        )
        manifest["excluded_member_count"] = len(excluded)
        manifest["promoted_root_file_count"] = len(promoted)
        manifest["promoted_tree_sha256"] = self._tree_digest(promoted)
        manifest["promotion_map_sha256"] = self._canonical_json_hash(promotion_map)
        self._write_manifest_copies(manifest)

        report = self._check()

        self.assertFalse(report.ok)
        self.assertTrue(
            any(
                issue.check == "promotion_source"
                and "not in imported inventory" in issue.message
                for issue in report.issues
            )
        )


class VerifiedSourceGateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.archive = self.root / "reference.zip"
        self.repo = self.root / "stage"
        self.promotion_map = self.root / "promotions.json"
        self.promotion_map.write_text(
            '{"promotions":[],"schema":'
            '"trecap_phase2_reference_promotion_map_v1"}\n',
            encoding="ascii",
            newline="\n",
        )
        with zipfile.ZipFile(
            self.archive,
            "w",
            compression=zipfile.ZIP_DEFLATED,
        ) as archive:
            archive.writestr("trecap-golden/data.txt", b"source payload")
        expected = hashlib.sha256(self.archive.read_bytes()).hexdigest()
        result = subprocess.run(
            [
                sys.executable,
                str(REPO_ROOT / "scripts" / "reference_import.py"),
                "stage",
                "--archive",
                str(self.archive),
                "--expected-sha256",
                expected,
                "--output",
                str(self.repo),
                "--promotion-map",
                str(self.promotion_map),
            ],
            check=False,
            text=True,
            capture_output=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.schema_dir = self.repo / "spec" / "schemas"
        self.schema_dir.mkdir(parents=True)
        shutil.copyfile(
            REPO_ROOT
            / "spec"
            / "schemas"
            / "reference_import_manifest.schema.json",
            self.schema_dir / "reference_import_manifest.schema.json",
        )
        map_copy = self.repo / "config" / "reference_import_promotions.json"
        map_copy.parent.mkdir(parents=True)
        shutil.copyfile(self.promotion_map, map_copy)
        self.manifest_path = (
            self.repo
            / "artifacts"
            / "manifests"
            / "reference_import_manifest.json"
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _manifest(self) -> dict[str, object]:
        return json.loads(self.manifest_path.read_text(encoding="ascii"))

    def _write_manifest_copies(self, value: dict[str, object]) -> None:
        payload = (
            json.dumps(
                value,
                allow_nan=False,
                ensure_ascii=True,
                separators=(",", ":"),
                sort_keys=True,
            )
            + "\n"
        )
        self.manifest_path.write_text(payload, encoding="ascii", newline="\n")
        (self.repo / "sw" / "reference_model" / "import_manifest.json").write_text(
            payload,
            encoding="ascii",
            newline="\n",
        )

    def _check(self, archive: Path | None = None) -> CheckReport:
        return check_reference_import_manifest(
            self.repo,
            self.manifest_path,
            schemas_dir=self.schema_dir,
            require_verified_source=True,
            source_archive=archive or self.archive,
        )

    def test_valid_staged_zip_passes_source_gate(self) -> None:
        report = self._check()
        self.assertTrue(report.ok, report.to_dict())

    def test_expected_source_hash_mismatch_is_rejected(self) -> None:
        manifest = self._manifest()
        manifest["source"]["expected_sha256"] = "0" * 64
        self._write_manifest_copies(manifest)

        report = self._check()

        self.assertFalse(report.ok)
        self.assertIn(
            "source.expected_sha256",
            {issue.check for issue in report.issues},
        )

    def test_non_zip_payload_is_rejected(self) -> None:
        bogus = self.root / "bogus.zip"
        bogus.write_bytes(b"not a zip archive")
        manifest = self._manifest()
        digest = hashlib.sha256(bogus.read_bytes()).hexdigest()
        manifest["source"]["archive_name"] = bogus.name
        manifest["source"]["archive_sha256"] = digest
        manifest["source"]["expected_sha256"] = digest
        manifest["source"]["archive_size_bytes"] = bogus.stat().st_size
        self._write_manifest_copies(manifest)

        report = self._check(bogus)

        self.assertFalse(report.ok)
        self.assertIn("source_archive_zip", {issue.check for issue in report.issues})

    def test_symlink_source_archive_is_rejected(self) -> None:
        symlink = self.root / "source-link.zip"
        try:
            symlink.symlink_to(self.archive)
        except OSError as exc:
            self.skipTest(f"symlink creation is unavailable: {exc}")

        report = self._check(symlink)

        self.assertFalse(report.ok)
        self.assertIn("source_archive", {issue.check for issue in report.issues})

    def test_zip_symlink_member_is_rejected(self) -> None:
        symlink_zip = self.root / "symlink-member.zip"
        member = zipfile.ZipInfo("trecap-golden/data.txt")
        member.create_system = 3
        member.external_attr = (stat.S_IFLNK | 0o777) << 16
        member.compress_type = zipfile.ZIP_STORED
        with zipfile.ZipFile(symlink_zip, "w") as archive:
            archive.writestr(member, b"source payload")
        manifest = self._manifest()
        digest = hashlib.sha256(symlink_zip.read_bytes()).hexdigest()
        manifest["source"]["archive_name"] = symlink_zip.name
        manifest["source"]["archive_sha256"] = digest
        manifest["source"]["expected_sha256"] = digest
        manifest["source"]["archive_size_bytes"] = symlink_zip.stat().st_size
        self._write_manifest_copies(manifest)

        report = self._check(symlink_zip)

        self.assertFalse(report.ok)
        self.assertIn("source_archive_zip", {issue.check for issue in report.issues})


if __name__ == "__main__":
    unittest.main()
