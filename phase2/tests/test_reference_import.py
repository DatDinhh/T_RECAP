"""Directed fail-closed regressions for the Phase 2 reference importer.

File class: [1] hand-written verification infrastructure.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest
import zipfile


REPO_ROOT = Path(__file__).resolve().parents[1]
IMPORTER = REPO_ROOT / "scripts" / "reference_import.py"
PROMOTION_SCHEMA = "trecap_phase2_reference_promotion_map_v1"


class ReferenceImportTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.archive = self.root / "reference.zip"
        self.output = self.root / "stage"
        self.promotion_map = self.root / "promotions.json"
        self._write_promotion_map([])

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _write_promotion_map(
        self, promotions: list[tuple[str, str]]
    ) -> None:
        value = {
            "schema": PROMOTION_SCHEMA,
            "promotions": [
                {
                    "source_path": source,
                    "destination_path": destination,
                }
                for source, destination in promotions
            ],
        }
        self.promotion_map.write_text(
            json.dumps(value, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
        )

    def _write_zip(self, entries: list[tuple[str | zipfile.ZipInfo, bytes]]) -> None:
        with zipfile.ZipFile(
            self.archive, "w", compression=zipfile.ZIP_DEFLATED
        ) as archive:
            for name, payload in entries:
                archive.writestr(name, payload)

    def _archive_sha256(self) -> str:
        return hashlib.sha256(self.archive.read_bytes()).hexdigest()

    def _run_stage(
        self,
        *,
        expected_sha256: str | None = None,
        output: Path | None = None,
        optimized: bool = False,
    ) -> subprocess.CompletedProcess[str]:
        expected = expected_sha256 or self._archive_sha256()
        stage_output = output or self.output
        interpreter = [sys.executable]
        if optimized:
            interpreter.append("-O")
        return subprocess.run(
            interpreter
            + [
                str(IMPORTER),
                "stage",
                "--archive",
                str(self.archive),
                "--expected-sha256",
                expected,
                "--output",
                str(stage_output),
                "--promotion-map",
                str(self.promotion_map),
            ],
            check=False,
            cwd=self.root,
            text=True,
            capture_output=True,
        )

    def _assert_preflight_failure(self, result: subprocess.CompletedProcess[str]) -> None:
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertIn("REFERENCE_IMPORT_ERROR:", result.stderr)
        self.assertFalse(self.output.exists(), "failed import published partial output")
        self.assertFalse(
            list(self.root.glob(".stage.tmp-*")),
            "failed import left a temporary staging directory",
        )

    def test_stage_preserves_crlf_and_missing_final_newline_verbatim(self) -> None:
        crlf = b"first\r\nsecond\r\n"
        no_final_newline = b"\x00binary-like-payload\xff"
        self._write_zip(
            [
                ("trecap-golden/data/crlf.txt", crlf),
                ("trecap-golden/data/no-final.bin", no_final_newline),
            ]
        )
        self._write_promotion_map(
            [("data/crlf.txt", "artifacts/reference-copy/crlf.txt")]
        )

        result = self._run_stage()

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("REFERENCE_IMPORT_STAGE_PASS", result.stdout)
        self.assertEqual(
            (self.output / "sw/reference_model/data/crlf.txt").read_bytes(), crlf
        )
        self.assertEqual(
            (self.output / "sw/reference_model/data/no-final.bin").read_bytes(),
            no_final_newline,
        )
        self.assertEqual(
            (self.output / "artifacts/reference-copy/crlf.txt").read_bytes(), crlf
        )

        internal = self.output / "sw/reference_model/import_manifest.json"
        root = self.output / "artifacts/manifests/reference_import_manifest.json"
        self.assertEqual(internal.read_bytes(), root.read_bytes())
        manifest = json.loads(root.read_text(encoding="ascii"))
        self.assertEqual(
            manifest["provenance_status"], "verified_source_archive"
        )
        self.assertTrue(manifest["source"]["verified"])
        self.assertEqual(manifest["source"]["archive_sha256"], self._archive_sha256())
        self.assertEqual(manifest["imported_reference_file_count"], 2)
        self.assertNotIn(
            "sw/reference_model/import_manifest.json",
            {row["path"] for row in manifest["imported_reference_files"]},
        )
        records = {row["path"]: row for row in manifest["imported_reference_files"]}
        self.assertEqual(
            records["sw/reference_model/data/crlf.txt"]["sha256"],
            hashlib.sha256(crlf).hexdigest(),
        )
        self.assertEqual(
            records["sw/reference_model/data/no-final.bin"]["sha256"],
            hashlib.sha256(no_final_newline).hexdigest(),
        )

    def test_wrong_source_hash_fails_before_output(self) -> None:
        self._write_zip([("trecap-golden/file.txt", b"payload")])

        result = self._run_stage(expected_sha256="0" * 64, optimized=True)

        self._assert_preflight_failure(result)
        self.assertIn("SHA-256 mismatch", result.stderr)

    def test_same_inputs_produce_byte_identical_manifests(self) -> None:
        self._write_zip(
            [
                ("trecap-golden/a.txt", b"A\r\n"),
                ("trecap-golden/b.txt", b"B"),
            ]
        )
        second_output = self.root / "stage-second"

        first = self._run_stage()
        second = self._run_stage(output=second_output)

        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertEqual(second.returncode, 0, second.stderr)
        relative_manifest = Path("artifacts/manifests/reference_import_manifest.json")
        self.assertEqual(
            (self.output / relative_manifest).read_bytes(),
            (second_output / relative_manifest).read_bytes(),
        )

    def test_standalone_bytecode_suffix_is_excluded(self) -> None:
        self._write_zip(
            [
                ("trecap-golden/source.txt", b"included"),
                ("trecap-golden/loose.pyc", b"excluded-bytecode"),
            ]
        )

        result = self._run_stage()

        self.assertEqual(result.returncode, 0, result.stderr)
        manifest = json.loads(
            (
                self.output
                / "artifacts/manifests/reference_import_manifest.json"
            ).read_text(encoding="ascii")
        )
        self.assertEqual(manifest["excluded_member_count"], 1)
        excluded = manifest["excluded_members"][0]
        self.assertEqual(excluded["path"], "sw/reference_model/loose.pyc")
        self.assertEqual(excluded["reason"], "excluded_suffix:.pyc")
        self.assertFalse(
            (self.output / "sw/reference_model/loose.pyc").exists()
        )

    def test_path_traversal_is_rejected(self) -> None:
        self._write_zip([("trecap-golden/../escape.txt", b"escape")])

        result = self._run_stage()

        self._assert_preflight_failure(result)
        self.assertIn("traversal", result.stderr)
        self.assertFalse((self.root / "escape.txt").exists())

    def test_casefold_collision_is_rejected(self) -> None:
        self._write_zip(
            [
                ("trecap-golden/Data.txt", b"upper"),
                ("trecap-golden/data.txt", b"lower"),
            ]
        )

        result = self._run_stage()

        self._assert_preflight_failure(result)
        self.assertIn("casefold/Unicode collision", result.stderr)

    def test_nonportable_member_names_are_rejected(self) -> None:
        forbidden_names = [
            "C:\\outside.txt",
            "\\\\server\\share\\outside.txt",
            "trecap-golden/control-\x01.txt",
            "trecap-golden/trailing-dot.",
            "trecap-golden/NUL.txt",
        ]
        for name in forbidden_names:
            with self.subTest(name=repr(name)):
                self._write_zip([(name, b"payload")])
                result = self._run_stage()
                self._assert_preflight_failure(result)

    def test_separator_normalized_collision_is_rejected(self) -> None:
        self._write_zip(
            [
                ("trecap-golden/a/b.txt", b"slash"),
                ("trecap-golden\\a\\b.txt", b"backslash"),
            ]
        )

        result = self._run_stage()

        self._assert_preflight_failure(result)
        self.assertIn("separator/NFC duplicate", result.stderr)

    def test_zip_symlink_is_rejected(self) -> None:
        symlink = zipfile.ZipInfo("trecap-golden/link")
        symlink.create_system = 3
        symlink.external_attr = (stat.S_IFLNK | 0o777) << 16
        symlink.compress_type = zipfile.ZIP_STORED
        self._write_zip([(symlink, b"target")])

        result = self._run_stage()

        self._assert_preflight_failure(result)
        self.assertIn("symlink", result.stderr)

    def test_truncated_zip_is_rejected_without_partial_output(self) -> None:
        self._write_zip([("trecap-golden/file.txt", b"payload")])
        truncated = self.archive.read_bytes()[:-22]
        self.archive.write_bytes(truncated)

        result = self._run_stage(
            expected_sha256=hashlib.sha256(truncated).hexdigest()
        )

        self._assert_preflight_failure(result)
        self.assertIn("incomplete/invalid ZIP", result.stderr)

    def test_bad_member_crc_is_rejected_before_output(self) -> None:
        payload = b"unique-stored-payload-for-crc"
        with zipfile.ZipFile(
            self.archive, "w", compression=zipfile.ZIP_STORED
        ) as archive:
            archive.writestr("trecap-golden/file.txt", payload)
        damaged = bytearray(self.archive.read_bytes())
        payload_offset = damaged.find(payload)
        self.assertGreaterEqual(payload_offset, 0)
        damaged[payload_offset] ^= 0x01
        self.archive.write_bytes(damaged)

        result = self._run_stage(
            expected_sha256=hashlib.sha256(damaged).hexdigest()
        )

        self._assert_preflight_failure(result)
        self.assertIn("CRC-read", result.stderr)

    def test_refresh_proxy_never_claims_source_archive_verification(self) -> None:
        proxy_repo = self.root / "proxy-repo"
        reference_file = proxy_repo / "sw/reference_model/data/source.txt"
        promoted_file = proxy_repo / "artifacts/reference-copy/source.txt"
        reference_file.parent.mkdir(parents=True)
        promoted_file.parent.mkdir(parents=True)
        payload = b"embedded proxy bytes\r\n"
        reference_file.write_bytes(payload)
        promoted_file.write_bytes(payload)
        self._write_promotion_map(
            [("data/source.txt", "artifacts/reference-copy/source.txt")]
        )

        result = subprocess.run(
            [
                sys.executable,
                str(IMPORTER),
                "refresh-proxy",
                "--repo-root",
                str(proxy_repo),
                "--promotion-map",
                str(self.promotion_map),
                "--proxy-id",
                "unit-test-embedded-proxy",
                "--output-manifest",
                "sw/reference_model/import_manifest.json",
                "--output-manifest",
                "artifacts/manifests/reference_import_manifest.json",
            ],
            check=False,
            cwd=self.root,
            text=True,
            capture_output=True,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("source_archive_verified=false", result.stdout)
        internal = proxy_repo / "sw/reference_model/import_manifest.json"
        root = proxy_repo / "artifacts/manifests/reference_import_manifest.json"
        self.assertEqual(internal.read_bytes(), root.read_bytes())
        manifest = json.loads(root.read_text(encoding="ascii"))
        self.assertEqual(
            manifest["provenance_status"],
            "embedded_proxy_unverified_source_archive",
        )
        self.assertEqual(
            manifest["source"],
            {
                "kind": "embedded_proxy",
                "proxy_id": "unit-test-embedded-proxy",
                "verified": False,
            },
        )


if __name__ == "__main__":
    unittest.main()
