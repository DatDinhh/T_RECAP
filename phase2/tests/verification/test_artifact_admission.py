"""Fault-injection checks for V0 admission, using disposable copies only.

Run: python tests/verification/test_artifact_admission.py --evidence
     runs/verification/<run>/fault_injection.json
No artifact generator, model, simulator or hardware tool is invoked.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import platform
import shutil
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CHECKER_PATH = ROOT / "scripts/verification/artifact_admission.py"
SPEC = importlib.util.spec_from_file_location("artifact_admission_under_test", CHECKER_PATH)
assert SPEC and SPEC.loader
admission = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(admission)


class ArtifactFaultInjection(unittest.TestCase):
    events: list[dict] = []

    @classmethod
    def setUpClass(cls):
        cls.baseline = admission.audit_repository(ROOT)
        if cls.baseline["outcome"] != "PASS_ARTIFACT_ADMISSION_ONLY":
            raise AssertionError("Real source artifact fixture did not admit: " + json.dumps(cls.baseline.get("errors")))
        cls.source_identity = cls.baseline["evidence"]

    @classmethod
    def tearDownClass(cls):
        for record in cls.source_identity:
            data = (ROOT / record["path"]).read_bytes()
            if len(data) != record["size_bytes"] or hashlib.sha256(data).hexdigest() != record["sha256"]:
                raise AssertionError("Source artifact changed during tests: " + record["path"])

    def copy_snapshot(self) -> Path:
        temp = tempfile.TemporaryDirectory(prefix="trecap-v0-admission-")
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        for record in self.source_identity:
            target = root / record["path"]
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / record["path"], target)
        return root

    def reject_mutation(self, relative: str, mode: str, expected_code: str):
        root = self.copy_snapshot()
        path = root / relative
        if mode == "missing":
            path.unlink()
        elif mode == "truncated":
            path.write_bytes(path.read_bytes()[:-4])
        elif mode == "changed":
            original = path.read_bytes()
            path.write_bytes((b"1" if original[:1] != b"1" else b"0") + original[1:])
        elif mode == "empty":
            path.write_bytes(b"")
        else:
            self.fail("Unknown mutation")
        report = admission.audit_repository(root)
        self.assertEqual(report["outcome"], "FAIL")
        self.assertEqual(report["errors"][0]["code"], expected_code)
        self.events.append({"test": self.id().rsplit(".", 1)[-1], "mutation": mode, "target": relative,
                            "expected": "FAIL", "observed": report["outcome"], "error_code": expected_code})

    def reject_memh(self, data: bytes, rows: int, width: int, signed: bool, expected_code: str):
        # Supply the actual hash of the malformed bytes: a rehashed declaration
        # must not defeat the independent encoding/width/count checks.
        with self.assertRaises(admission.AdmissionError) as caught:
            admission.inspect_memh(data, path="fixture.memh", rows=rows, width=width, signed=signed,
                                   expected_sha=hashlib.sha256(data).hexdigest())
        self.assertEqual(caught.exception.code, expected_code)
        self.events.append({"test": self.id().rsplit(".", 1)[-1], "mutation": "rehashed malformed MEMH",
                            "expected": "FAIL", "observed": "FAIL", "error_code": expected_code})

    def test_current_declared_snapshot_admits(self):
        self.assertEqual(self.baseline["artifact_admission"], {"status": "PASS", "declared_vector_count": 3, "coefficient_count": 5})
        self.assertEqual(self.baseline["local_provenance"]["status"], "PASS_LOCAL_SNAPSHOT")
        self.assertFalse(self.baseline["local_provenance"]["archive_authenticity_qualified"])
        self.assertFalse(self.baseline["local_provenance"]["historical_acceptance_flags_promoted"])

    def test_quality_ambiguity_is_not_byte_corruption(self):
        quality = self.baseline["quality_bound_admission"]
        self.assertEqual(quality["status"], "BLOCKED_CONTRACT")
        self.assertEqual([(x["code"], x["vector"]) for x in quality["issues"]],
                         [("QUALITY_CONFIG_AMBIGUOUS", "near_threshold_multitone_Ns1024_thr64")])
        self.assertFalse(quality["numerical_oracle_qualified"])
        self.assertEqual(self.baseline["artifact_admission"]["status"], "PASS")

    def test_missing_requested_suite_class_is_separate(self):
        report = admission.audit_repository(ROOT, ["impulse", "white_noise"])
        self.assertEqual(report["artifact_admission"]["status"], "PASS")
        self.assertEqual(report["suite_coverage"]["status"], "INCOMPLETE")
        self.assertEqual(report["suite_coverage"]["missing_generators"], ["white_noise"])
        self.assertFalse(report["suite_coverage"]["normative_suite_completeness_claimed"])

    def test_coefficient_changed(self):
        self.reject_mutation("artifacts/coefficients/twiddle_im.memh", "changed", "HASH_MISMATCH")

    def test_coefficient_missing(self):
        self.reject_mutation("artifacts/coefficients/window_qw.memh", "missing", "MISSING_FILE")

    def test_coefficient_truncated(self):
        self.reject_mutation("artifacts/coefficients/twiddle_inv_im.memh", "truncated", "HASH_MISMATCH")

    def test_input_changed(self):
        self.reject_mutation("artifacts/test_vectors/impulse_Ns1024_thr0/x_in.memh", "changed", "HASH_MISMATCH")

    def test_input_missing(self):
        self.reject_mutation("artifacts/test_vectors/impulse_Ns1024_thr0/x_in.memh", "missing", "MISSING_FILE")

    def test_input_truncated(self):
        self.reject_mutation("artifacts/test_vectors/impulse_Ns1024_thr0/x_in.memh", "truncated", "HASH_MISMATCH")

    def test_output_changed(self):
        self.reject_mutation("artifacts/reference_outputs/impulse_Ns1024_thr0/y_out.memh", "changed", "HASH_MISMATCH")

    def test_output_missing(self):
        self.reject_mutation("artifacts/reference_outputs/impulse_Ns1024_thr0/y_out.memh", "missing", "MISSING_FILE")

    def test_output_truncated(self):
        self.reject_mutation("artifacts/reference_outputs/impulse_Ns1024_thr0/y_out.memh", "truncated", "HASH_MISMATCH")

    def test_empty_required_metrics(self):
        self.reject_mutation("artifacts/reference_outputs/impulse_Ns1024_thr0/metrics.json", "empty", "HASH_MISMATCH")

    def test_modified_vector_config(self):
        self.reject_mutation("artifacts/test_vectors/impulse_Ns1024_thr0/config.json", "changed", "HASH_MISMATCH")

    def test_modified_frame_statistics(self):
        self.reject_mutation("artifacts/reference_outputs/impulse_Ns1024_thr0/frame_stats.csv", "changed", "HASH_MISMATCH")

    def test_embedded_copy_drift_rejected(self):
        self.reject_mutation("sw/reference_model/artifacts/coefficients/window_qw.memh", "changed", "HASH_MISMATCH")

    def test_canonical_signed_endpoints(self):
        data = b"00000\n0ffff\n10000\n1ffff\n"
        actual = admission.inspect_memh(data, path="signed17.memh", rows=4, width=17, signed=True,
                                        expected_sha=hashlib.sha256(data).hexdigest(), canonical_sha=hashlib.sha256(data).hexdigest())
        self.assertEqual(actual, [0, 65535, -65536, -1])

    def test_canonical_unsigned_window_endpoint(self):
        self.assertEqual(admission.inspect_memh(b"0000\n8000\n", path="window.memh", rows=2, width=16, signed=False), [0, 32768])

    def test_rehashed_uppercase_rejected(self):
        self.reject_memh(b"ABC\n", 1, 12, True, "MEMH_ENCODING")

    def test_rehashed_crlf_rejected(self):
        self.reject_memh(b"123\r\n", 1, 12, True, "MEMH_LENGTH")

    def test_rehashed_missing_final_lf_rejected(self):
        self.reject_memh(b"123", 1, 12, True, "MEMH_LENGTH")

    def test_rehashed_unused_high_bits_rejected(self):
        self.reject_memh(b"20000\n", 1, 17, True, "MEMH_UNUSED_BITS")

    def test_rehashed_extra_row_rejected(self):
        self.reject_memh(b"000\n001\n", 1, 12, True, "MEMH_LENGTH")

    def test_canonical_hash_mismatch_rejected(self):
        with self.assertRaises(admission.AdmissionError) as caught:
            admission.inspect_memh(b"123\n", path="fixture.memh", rows=1, width=12, signed=True,
                                   canonical_sha="0" * 64)
        self.assertEqual(caught.exception.code, "CANONICAL_HASH_MISMATCH")

    def test_duplicate_json_key_rejected(self):
        with self.assertRaises(admission.AdmissionError) as caught:
            admission.strict_json(b'{"THR2":"0","THR2":"4096"}', "fixture.json")
        self.assertEqual(caught.exception.code, "JSON_DUPLICATE_KEY")

    def test_nonfinite_json_rejected(self):
        for value in (b"NaN", b"Infinity", b"-Infinity"):
            with self.subTest(value=value), self.assertRaises(admission.AdmissionError) as caught:
                admission.strict_json(b'{"value":' + value + b'}', "fixture.json")
            self.assertEqual(caught.exception.code, "JSON_NONFINITE")

    def test_json_floating_integer_and_overflow_rejected(self):
        for value in (b"12.0", b"1e309"):
            with self.subTest(value=value), self.assertRaises(admission.AdmissionError) as caught:
                admission.strict_json(b'{"N":' + value + b'}', "fixture.json")
            self.assertEqual(caught.exception.code, "JSON_FLOAT")

    def test_historical_generator_mismatch_is_not_current_byte_corruption(self):
        source = self.baseline["local_provenance"]["generator_source_identity"]
        self.assertEqual(source["status"], "HISTORICAL_GENERATOR_IDENTITY_UNRESOLVED")
        self.assertEqual(len(source["records"]), 2)
        self.assertTrue(all(r["status"] == "SOURCE_IDENTITY_MISMATCH" for r in source["records"]))
        self.assertFalse(source["dependency_closure_qualified"])
        self.assertFalse(source["regeneration_executed"])
        self.assertEqual(self.baseline["artifact_admission"]["status"], "PASS")

    def test_wide_decimal_preserved(self):
        wide = "18446744073709551615"
        self.assertEqual(admission.decimal_string(wide, "fixture"), 18446744073709551615)
        self.assertEqual(str(admission.decimal_string(wide, "fixture")), wide)
        for wrong in (float(wide), 18446744073709551615, "01", "+1", "1e3"):
            with self.subTest(wrong=wrong), self.assertRaises(admission.AdmissionError):
                admission.decimal_string(wrong, "fixture")

    def test_repository_escape_and_aliases_rejected(self):
        for path in ("../outside.memh", "/outside.memh", "D:/outside.memh", "a\\b", "a//b", "a/./b", "a/../b"):
            with self.subTest(path=path), self.assertRaises(admission.AdmissionError) as caught:
                admission.portable_path(path)
            self.assertEqual(caught.exception.code, "UNSAFE_PATH")

    def test_import_tree_order_is_deterministic(self):
        records = [{"path": "a", "size_bytes": 0, "sha256": hashlib.sha256(b"").hexdigest()},
                   {"path": "b", "size_bytes": 1, "sha256": hashlib.sha256(b"x").hexdigest()}]
        self.assertEqual(admission.tree_hash(records), admission.tree_hash(records[::-1]))
        changed = [dict(x) for x in records]
        changed[1]["path"] = "c"
        self.assertNotEqual(admission.tree_hash(records), admission.tree_hash(changed))


class EvidenceResult(unittest.TextTestResult):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.case_results = []

    def addSuccess(self, test):
        super().addSuccess(test)
        self.case_results.append({"test": test.id().split(".")[-1], "outcome": "PASS"})

    def addFailure(self, test, err):
        super().addFailure(test, err)
        self.case_results.append({"test": test.id().split(".")[-1], "outcome": "FAIL"})

    def addError(self, test, err):
        super().addError(test, err)
        self.case_results.append({"test": test.id().split(".")[-1], "outcome": "ERROR"})


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence", type=Path)
    args = parser.parse_args()
    if args.evidence:
        evidence = args.evidence.resolve()
        try:
            evidence.relative_to(ROOT / "runs" / "verification")
        except ValueError:
            parser.error("evidence must be under runs/verification")
        if evidence.exists():
            parser.error("evidence already exists; choose a new run path")
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(ArtifactFaultInjection)
    result = unittest.TextTestRunner(verbosity=2, resultclass=EvidenceResult).run(suite)
    if args.evidence:
        report = {"schema": "trecap_verification_artifact_fault_injection_v1", "campaign": "V0",
                  "created_utc": datetime.now(timezone.utc).isoformat(), "python_version": platform.python_version(),
                  "checker_sha256": hashlib.sha256(CHECKER_PATH.read_bytes()).hexdigest(),
                  "test_source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                  "outcome": "PASS" if result.wasSuccessful() else "FAIL", "tests_run": result.testsRun,
                  "failure_count": len(result.failures), "error_count": len(result.errors),
                  "case_results": result.case_results, "expected_negative_observations": ArtifactFaultInjection.events,
                  "input_identity": getattr(ArtifactFaultInjection, "source_identity", []),
                  "scope": "Admission checker fault injection on disposable copies; no reference/RTL correctness or suite signoff"}
        evidence.parent.mkdir(parents=True, exist_ok=True)
        with evidence.open("x", encoding="utf-8", newline="\n") as stream:
            json.dump(report, stream, indent=2, sort_keys=True, ensure_ascii=True, allow_nan=False)
            stream.write("\n")
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
