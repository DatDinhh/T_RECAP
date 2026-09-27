"""Deliberate corruptions of a supplied positive core capture.

Run after a successful native capture with --capture, --oracle, --x and a new
--evidence report path. Mutations affect temporary copies only. Passing these
checks qualifies the rejection behavior exercised here, not the RTL campaign.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import shutil
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CHECKER = ROOT / "scripts/verification/core_capture_check.py"
SPEC = importlib.util.spec_from_file_location("core_capture_check_under_test", CHECKER)
assert SPEC and SPEC.loader
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


class CaptureMutationTests(unittest.TestCase):
    capture = oracle = x_path = None
    events: list[dict] = []

    @classmethod
    def setUpClass(cls):
        if cls.capture is None:
            raise unittest.SkipTest("Supply a complete positive native capture through this script's CLI")
        cls.baseline = module.check_capture(cls.capture, cls.oracle, cls.x_path)
        if cls.baseline["outcome"] != "PASS":
            raise AssertionError("Positive capture prerequisite failed: " + json.dumps(cls.baseline.get("errors")))
        if not cls.baseline["ifft_residual"]["exact_complex_comparison"]:
            raise AssertionError("Mutation corpus requires admitted complex IFFT evidence")
        cls.source_hashes = {}
        for identity in cls.baseline["input_identities"]:
            label = identity["file"]
            if label == "input":
                path = cls.x_path
            else:
                area, name = label.split("/", 1)
                path = (cls.capture if area == "capture" else cls.oracle) / name
            cls.source_hashes[path] = identity["sha256"]

    @classmethod
    def tearDownClass(cls):
        for path, expected in cls.source_hashes.items():
            if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
                raise AssertionError("Original input/capture/oracle changed during fault injection")

    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="trecap-core-capture-")
        self.addCleanup(temp.cleanup)
        self.work = Path(temp.name)
        self.copy = self.work / "capture"
        self.copy.mkdir()
        for identity in self.baseline["input_identities"]:
            if identity["file"].startswith("capture/"):
                name = identity["file"].split("/", 1)[1]
                shutil.copyfile(self.capture / name, self.copy / name)

    def reject(self, expected: str, target: str, mutation: str):
        report = module.check_capture(self.copy, self.oracle, self.x_path)
        self.assertEqual(report["outcome"], "FAIL")
        self.assertEqual(report["errors"][0]["code"], expected)
        self.events.append({"test": self.id().rsplit(".", 1)[-1], "target": target,
                            "mutation": mutation, "expected_outcome": "FAIL", "observed_outcome": "FAIL",
                            "error_code": expected})

    def edit_csv(self, name: str, row: int, column: int, value: str):
        path = self.copy / name
        lines = path.read_text(encoding="ascii").splitlines()
        fields = lines[row + 1].split(",")
        fields[column] = value
        lines[row + 1] = ",".join(fields)
        path.write_text("\n".join(lines) + "\n", encoding="ascii", newline="\n")

    def increment_csv(self, name: str, row: int, column: int):
        value = int((self.copy / name).read_text().splitlines()[row + 1].split(",")[column])
        self.edit_csv(name, row, column, str(value + 1))

    def edit_oracle_geometry(self, geometry):
        # Change a disposable expected-metadata copy only. These are rejection
        # probes, never simulated captures or supplemental numerical oracles.
        original = self.oracle
        copied = self.work / "expected" / original.parent.name / "oracle"
        copied.mkdir(parents=True, exist_ok=True)
        for identity in self.baseline["input_identities"]:
            if identity["file"].startswith("oracle/"):
                name = identity["file"].split("/", 1)[1]
                shutil.copyfile(original / name, copied / name)
        path = copied / "metrics.json"
        value = json.loads(path.read_text())
        value["geometry"] = geometry
        path.write_text(json.dumps(value, indent=2) + "\n", encoding="ascii", newline="\n")
        self.oracle = copied

    def edit_json(self, change):
        path = self.copy / "metrics_observed.json"
        value = json.loads(path.read_text())
        change(value)
        path.write_text(json.dumps(value, indent=2) + "\n", encoding="ascii", newline="\n")

    def test_positive_capture(self):
        self.assertEqual(module.check_capture(self.copy, self.oracle, self.x_path)["outcome"], "PASS")
        self.assertFalse(self.baseline["oracle_qualification_established_here"])

    def test_missing_each_required_capture(self):
        for identity in self.baseline["input_identities"]:
            if identity["file"].startswith("capture/"):
                name = identity["file"].split("/", 1)[1]
                path = self.copy / name
                original = path.read_bytes()
                with self.subTest(file=name):
                    path.unlink()
                    try:
                        self.reject("MISSING_FILE", name, "missing required capture")
                    finally:
                        path.write_bytes(original)

    def test_truncated_y_rejected(self):
        path = self.copy / "y_out.memh"
        path.write_bytes(path.read_bytes()[:-4])
        self.reject("ROW_COUNT", path.name, "remove final output row")

    def test_changed_y_rejected(self):
        path = self.copy / "y_out.memh"
        data = path.read_bytes()
        path.write_bytes((b"1" if data[:1] != b"1" else b"0") + data[1:])
        self.reject("VALUE_MISMATCH", path.name, "change one sample nibble")

    def test_y_x_unknown_rejected(self):
        path = self.copy / "y_out.memh"
        path.write_bytes(b"xxx\n" + path.read_bytes()[4:])
        self.reject("MEMH_ENCODING", path.name, "unknown output sample")

    def test_y_missing_final_lf_rejected(self):
        path = self.copy / "y_out.memh"
        path.write_bytes(path.read_bytes()[:-1])
        self.reject("MEMH_ENCODING", path.name, "unterminated output sample")

    def test_extra_y_rejected(self):
        path = self.copy / "y_out.memh"
        path.write_bytes(path.read_bytes() + b"000\n")
        self.reject("ROW_COUNT", path.name, "append output sample")

    def test_frame_value_rejected(self):
        self.edit_csv("frame_stats.csv", 0, 1, "128")
        self.reject("VALUE_MISMATCH", "frame_stats.csv", "change unique bin count")

    def test_frame_truncation_rejected(self):
        path = self.copy / "frame_stats.csv"
        path.write_bytes(b"\n".join(path.read_bytes().splitlines()[:-1]) + b"\n")
        self.reject("ROW_COUNT", path.name, "remove complete final frame")

    def test_bin_value_rejected(self):
        self.increment_csv("bin_stats.csv", 0, 2)
        self.reject("VALUE_MISMATCH", "bin_stats.csv", "change canonical real component")

    def test_bin_duplicate_rejected(self):
        path = self.copy / "bin_stats.csv"
        lines = path.read_bytes().splitlines(keepends=True)
        lines[2] = lines[1]
        path.write_bytes(b"".join(lines))
        self.reject("VALUE_MISMATCH", path.name, "duplicate row without changing cardinality")

    def test_bin_wrong_header_rejected(self):
        path = self.copy / "bin_stats.csv"
        path.write_bytes(path.read_bytes().replace(b"pre_mask", b"premask", 1))
        self.reject("CSV_HEADER", path.name, "rename required column")

    def test_ifft_residual_summary_matches_raw(self):
        rows = (self.copy / "ifft_samples.csv").read_text().splitlines()[1:]
        values = [int(row.split(",")[3]) for row in rows]
        self.assertEqual(self.baseline["ifft_residual"]["nonzero_imag_rows"], sum(v != 0 for v in values))
        self.assertEqual(int(self.baseline["ifft_residual"]["max_abs_imag"]), max(abs(v) for v in values))
        self.assertTrue(self.baseline["ifft_residual"]["exact_complex_comparison"])

    def test_ifft_imaginary_value_change_rejected(self):
        path = self.copy / "ifft_samples.csv"
        lines = path.read_text().splitlines()
        index = next((i for i, line in enumerate(lines[1:]) if int(line.split(",")[3]) != 0), None)
        if index is None:
            self.edit_csv(path.name, 0, 3, "1")
            mutation = "inject imaginary residual into exactly real oracle output"
        else:
            self.edit_csv(path.name, index, 3, "0")
            mutation = "erase legitimate imaginary residual"
        self.reject("VALUE_MISMATCH", path.name, mutation)

    def test_ifft_truncation_rejected(self):
        path = self.copy / "ifft_samples.csv"
        path.write_bytes(b"\n".join(path.read_bytes().splitlines()[:-1]) + b"\n")
        self.reject("ROW_COUNT", path.name, "remove final complex sample")

    def test_metrics_one_unit_change_rejected(self):
        self.edit_json(lambda m: m["spectral_totals"].__setitem__("eligible_total_mag2", str(int(m["spectral_totals"]["eligible_total_mag2"]) + 1)))
        self.reject("METRIC_VALUE", "metrics_observed.json", "one-unit integer total mismatch")

    def test_metrics_wide_integer_not_float(self):
        self.assertEqual(module.number("18446744073709551615", "probe"), 18446744073709551615)
        self.edit_json(lambda m: m["spectral_totals"].__setitem__("eligible_total_mag2", 18446744073709551615))
        self.reject("INTEGER_ENCODING", "metrics_observed.json", "numeric JSON replaces decimal string")

    def test_missing_one_of_ten_metrics_rejected(self):
        self.edit_json(lambda m: m["time_domain_errors"].pop("sum_sq_err"))
        self.reject("METRIC_FIELDS", "metrics_observed.json", "omit metric")

    def test_internal_metrics_rejected(self):
        self.edit_json(lambda m: m["internal_metrics"].__setitem__("sum_abs_err", str(int(m["internal_metrics"]["sum_abs_err"]) + 1)))
        self.reject("INTERNAL_METRICS", "metrics_observed.json", "internal accumulator mismatch")

    def test_count_mismatch_rejected(self):
        self.edit_json(lambda m: m["counts"].__setitem__("done_pulses", 2))
        self.reject("COMPLETION_COUNTS", "metrics_observed.json", "duplicate done count")

    def test_protocol_error_rejected(self):
        self.edit_json(lambda m: m["status"].__setitem__("protocol_error_sticky", 1))
        self.reject("ERROR_STATUS", "metrics_observed.json", "nonzero protocol fault")

    def test_source_wrong_value_rejected(self):
        lines = (self.copy / "source_accepts.csv").read_text().splitlines()
        old = int(lines[1].split(",")[2])
        self.edit_csv("source_accepts.csv", 0, 2, str(old+1))
        self.reject("SOURCE_VALUE_PHASE", "source_accepts.csv", "changed accepted input value")

    def test_source_wrong_phase_rejected(self):
        self.edit_csv("source_accepts.csv", self.baseline["geometry"]["Ns"], 3, "input")
        self.reject("SOURCE_VALUE_PHASE", "source_accepts.csv", "mislabel zero analysis flush")

    def test_source_reordered_indices_rejected(self):
        self.edit_csv("source_accepts.csv", 1, 1, "0")
        self.reject("INDEX_SEQUENCE", "source_accepts.csv", "duplicate accepted source index")

    def test_source_cycle_reordering_rejected(self):
        first = (self.copy / "source_accepts.csv").read_text().splitlines()[1].split(",")[0]
        self.edit_csv("source_accepts.csv", 1, 0, first)
        self.reject("CYCLE_ORDER", "source_accepts.csv", "two accepted inputs in same cycle")

    def test_y_accept_wrong_value_rejected(self):
        self.increment_csv("y_accepts.csv", 0, 2)
        self.reject("ACCEPT_VALUE", "y_accepts.csv", "handshake value differs from output stream")

    def test_sample_commit_wrong_error_rejected(self):
        self.increment_csv("sample_commits.csv", 0, 4)
        self.reject("COMMIT_VALUE", "sample_commits.csv", "delayed error differs")

    def test_commit_and_accept_same_edge_rejected(self):
        accepted_cycle = (self.copy / "y_accepts.csv").read_text().splitlines()[1].split(",")[0]
        self.edit_csv("sample_commits.csv", 0, 0, accepted_cycle)
        self.reject("COMMIT_ACCEPT_ORDER", "sample_commits.csv", "same-edge consumption of new registered output")

    def test_source_or_commit_truncation_rejected(self):
        for name in ("source_accepts.csv", "sample_commits.csv", "y_accepts.csv"):
            path = self.copy / name
            original = path.read_bytes()
            with self.subTest(file=name):
                path.write_bytes(b"\n".join(original.splitlines()[:-1]) + b"\n")
                try:
                    self.reject("ROW_COUNT", name, "remove last accepted event")
                finally:
                    path.write_bytes(original)

    def test_lifecycle_missing_done_rejected(self):
        path = self.copy / "lifecycle.csv"
        path.write_bytes(b"\n".join(path.read_bytes().splitlines()[:-1]) + b"\n")
        self.reject("ROW_COUNT", path.name, "omit completion event")

    def test_lifecycle_early_done_rejected(self):
        last_y = (self.copy / "y_accepts.csv").read_text().splitlines()[-1].split(",")[0]
        self.edit_csv("lifecycle.csv", 1, 0, last_y)
        self.reject("LIFECYCLE_ORDER", "lifecycle.csv", "done on final acceptance edge")

    def test_lifecycle_wrong_count_rejected(self):
        self.edit_csv("lifecycle.csv", 1, 2, "1")
        self.reject("LIFECYCLE_COUNTS", "lifecycle.csv", "false final source count")

    def test_lifecycle_duplicate_start_rejected(self):
        self.edit_csv("lifecycle.csv", 1, 1, "start")
        self.reject("LIFECYCLE_EVENTS", "lifecycle.csv", "replace done with second start")

    def test_unknown_csv_integer_rejected(self):
        self.edit_csv("sample_commits.csv", 0, 2, "x")
        self.reject("INTEGER_ENCODING", "sample_commits.csv", "unknown delayed sample")

    def test_json_duplicate_key_rejected(self):
        path = self.copy / "metrics_observed.json"
        data = path.read_text()
        path.write_text(data.replace('"counts": {', '"counts": {}, "counts": {', 1), encoding="ascii", newline="\n")
        self.reject("JSON_DUPLICATE_KEY", path.name, "conflicting duplicated member")

    def test_json_truncation_rejected(self):
        path = self.copy / "metrics_observed.json"
        path.write_bytes(path.read_bytes()[:-3])
        self.reject("JSON_SYNTAX", path.name, "truncate completion JSON")

    def test_json_nonfinite_rejected(self):
        path = self.copy / "metrics_observed.json"
        data = path.read_text()
        path.write_text(data.replace('"done_pulses": 1', '"done_pulses": NaN', 1), encoding="ascii", newline="\n")
        self.reject("JSON_NONINTEGER", path.name, "nonfinite completion count")

    def test_optional_residual_summary_cross_checked(self):
        residual = self.baseline["ifft_residual"]
        self.edit_json(lambda m: m.__setitem__("ifft_residual_summary", {k: residual[k] for k in ("rows", "nonzero_imag_rows", "max_abs_imag")}))
        self.assertEqual(module.check_capture(self.copy, self.oracle, self.x_path)["outcome"], "PASS")
        self.edit_json(lambda m: m["ifft_residual_summary"].__setitem__("max_abs_imag", str(int(residual["max_abs_imag"]) + 1)))
        self.reject("IFFT_SUMMARY", "metrics_observed.json", "summary disagrees with exact residual magnitude")


    def test_supplemental_input_subdirectory_admits(self):
        path = self.work / self.baseline["vector_name"] / "input" / "x_in.memh"
        path.parent.mkdir(parents=True)
        shutil.copyfile(self.x_path, path)
        self.assertEqual(module.check_capture(self.copy, self.oracle, path)["outcome"], "PASS")

    def test_vector_identity_still_rejected(self):
        self.edit_json(lambda m: m.__setitem__("vector_name", "unrelated_vector"))
        self.reject("VECTOR_IDENTITY", "metrics_observed.json", "substitute case name")

    def test_nonpositive_geometry_rejected(self):
        geometry = dict(self.baseline["geometry"], Ns=0)
        self.edit_oracle_geometry(geometry)
        self.reject("JSON_INTEGER", "oracle/metrics.json", "empty input is outside Rev-J finite signoff")

    def test_zero_window_edge_phantom_frame_rejected(self):
        # At Ns=1 raw overlap would include a frame at tau=256, but its
        # sole input lands on Qw[0]=0. It must not create statistics.
        self.edit_oracle_geometry({"Ns": 1, "Nframes": 2, "tau_last": 256, "Ny": 640})
        self.reject("FULL_TAIL_GEOMETRY", "oracle/metrics.json", "phantom zero-window edge frame at Ns=1")

    def test_hop_plus_two_missing_frame_rejected(self):
        # Ns=130 includes an active third frame (tau=384). Ns=129 does not.
        self.edit_oracle_geometry({"Ns": 130, "Nframes": 2, "tau_last": 256, "Ny": 640})
        self.reject("FULL_TAIL_GEOMETRY", "oracle/metrics.json", "omit new active frame at H+2")

    def test_length_plus_two_missing_frame_rejected(self):
        self.edit_oracle_geometry({"Ns": 258, "Nframes": 3, "tau_last": 384, "Ny": 768})
        self.reject("FULL_TAIL_GEOMETRY", "oracle/metrics.json", "omit new active frame at L+2")

    def test_fixed_delay_truncate_is_not_full_tail(self):
        geometry = dict(self.baseline["geometry"])
        geometry["Ny"] = geometry["Ns"] + 384
        self.edit_oracle_geometry(geometry)
        self.reject("FULL_TAIL_GEOMETRY", "oracle/metrics.json", "substitute optional fixed-delay truncated output extent")

    def test_last_analysis_flush_cannot_be_drain(self):
        self.edit_csv("source_accepts.csv", self.baseline["geometry"]["tau_last"] - 1, 3, "tail_drain")
        self.reject("SOURCE_VALUE_PHASE", "source_accepts.csv", "premature switch to WOLA-only drain")

    def test_first_drain_cannot_trigger_analysis(self):
        self.edit_csv("source_accepts.csv", self.baseline["geometry"]["tau_last"], 3, "analysis_flush")
        self.reject("SOURCE_VALUE_PHASE", "source_accepts.csv", "drain token misclassified as analysis input")

    def test_delayed_input_domain_edges_rejected(self):
        path = self.copy / "sample_commits.csv"
        original = path.read_bytes()
        ns = self.baseline["geometry"]["Ns"]
        for index in sorted({383, 384, ns + 383, ns + 384}):
            with self.subTest(sample_idx=index):
                self.increment_csv(path.name, index, 2)
                try:
                    self.reject("COMMIT_VALUE", path.name, f"wrong delayed input at sample {index}")
                finally:
                    path.write_bytes(original)

    def test_fixed_delay_capture_truncation_rejected(self):
        count = self.baseline["geometry"]["Ns"] + 384
        for name, has_header in (("y_out.memh", False), ("y_accepts.csv", True),
                                 ("sample_commits.csv", True), ("source_accepts.csv", True)):
            path = self.copy / name
            lines = path.read_bytes().splitlines(keepends=True)
            path.write_bytes(b"".join(lines[:count + int(has_header)]))
        self.reject("ROW_COUNT", "y_out.memh", "all event streams stop at Ns+D instead of full Ny")


class EvidenceResult(unittest.TextTestResult):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.cases = []

    def addSuccess(self, test):
        super().addSuccess(test)
        self.cases.append({"test": test.id().split(".")[-1], "outcome": "PASS"})

    def addFailure(self, test, err):
        super().addFailure(test, err)
        self.cases.append({"test": test.id().split(".")[-1], "outcome": "FAIL"})

    def addError(self, test, err):
        super().addError(test, err)
        self.cases.append({"test": test.id().split(".")[-1], "outcome": "ERROR"})


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--capture", type=Path, required=True)
    parser.add_argument("--oracle", type=Path, required=True)
    parser.add_argument("--x", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    args = parser.parse_args()
    evidence = args.evidence.resolve()
    for source in (args.capture.resolve(), args.oracle.resolve(), args.x.resolve().parent):
        if evidence == source or source in evidence.parents:
            parser.error("evidence must be outside original capture/oracle/input directories")
    if evidence.exists():
        parser.error("evidence already exists; use a new path")
    CaptureMutationTests.capture, CaptureMutationTests.oracle, CaptureMutationTests.x_path = args.capture.resolve(), args.oracle.resolve(), args.x.resolve()
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(CaptureMutationTests)
    result = unittest.TextTestRunner(verbosity=2, resultclass=EvidenceResult).run(suite)
    report = {"schema": "trecap_core_capture_mutation_v1", "created_utc": datetime.now(timezone.utc).isoformat(),
              "outcome": "PASS" if result.wasSuccessful() and result.testsRun > 0 else "FAIL",
              "tests_run": result.testsRun, "failure_count": len(result.failures), "error_count": len(result.errors),
              "test_source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              "checker_sha256": hashlib.sha256(CHECKER.read_bytes()).hexdigest(),
              "positive_fixture": getattr(CaptureMutationTests, "baseline", {}),
              "geometry_scope": "Real supplied corpus only; altered expected geometry entries are rejection probes, not additional RTL runs",
              "case_results": result.cases, "expected_negative_observations": CaptureMutationTests.events,
              "scope": "Post-checker rejection of deliberate mutations to copies of one supplied positive corpus; no additional RTL campaign"}
    evidence.parent.mkdir(parents=True, exist_ok=True)
    with evidence.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(report, stream, indent=2, sort_keys=True, ensure_ascii=True, allow_nan=False)
        stream.write("\n")
    return 0 if report["outcome"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
