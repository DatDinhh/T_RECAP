#!/usr/bin/env python3
"""Fault witnesses for reference-evidence admission; all data below is synthetic."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO/"scripts/verification"))
from core_replay import selected_vectors, verify_reference

VECTOR = "impulse_Ns1024_thr0"
FILES = ("y_out.memh", "frame_stats.csv", "bin_stats.csv", "metrics.json",
         "ifft_output.csv", "trecap_artifact_expectations_pkg.sv")


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class AdmissionWitnesses(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="trecap-admission-")
        self.root = Path(self.temp.name).resolve()
        self.evidence = self.root/"runs/verification/reference"
        self.oracle = self.evidence/VECTOR/"oracle"
        self.oracle.mkdir(parents=True)
        self.source = self.root/"reference_source.txt"
        self.source.write_text("synthetic source\n", encoding="ascii")
        for name in FILES:
            (self.oracle/name).write_text("synthetic "+name+"\n", encoding="ascii")
        self.input = self.root/"artifacts/test_vectors"/VECTOR/"x_in.memh"
        self.input.parent.mkdir(parents=True)
        self.input.write_bytes(b"fff\n")
        self.identities = {"reference_source.txt": sha(self.source),
                           self.input.relative_to(self.root).as_posix(): sha(self.input)}
        self.identity_path = self.evidence/"input_identities.json"
        self.identity_path.write_text(json.dumps(self.identities), encoding="ascii")
        self.report = {
            "status": "PASS_BOUNDED_BASELINE", "input_identity_unchanged": True,
            "input_identities_sha256": sha(self.identity_path),
            "qualification_sources": dict(self.identities),
            "checks": [{"name": VECTOR, "status": "PASS",
                        "oracle_artifact_sha256": {name:sha(self.oracle/name) for name in FILES}}],
        }
        self.write_report()

    def tearDown(self):
        self.temp.cleanup()

    def write_report(self):
        (self.evidence/"report.json").write_text(json.dumps(self.report), encoding="ascii")

    def reject(self):
        with self.assertRaises((ValueError, FileNotFoundError)):
            verify_reference(self.root, self.evidence, [VECTOR])

    def boundary_fixture(self):
        self.input = self.evidence/VECTOR/"input/x_in.memh"
        self.input.parent.mkdir()
        self.input.write_bytes(b"fff\n")
        self.report["status"] = "PASS_BOUNDED_BOUNDARY_VECTORS"
        self.report["campaign"] = "short_length_boundaries"
        self.report["default_vectors"] = [VECTOR]
        check = self.report["checks"][0]
        check["configuration"] = {"Ns": 1, "frames": 1, "Ny": 512, "THR2": 4096}
        check["input_artifact"] = {"path": self.input.relative_to(self.root).as_posix(),
                                   "sha256": sha(self.input), "rows": 1,
                                   "width_bits": 12, "signed": True}
        self.identities[check["input_artifact"]["path"]] = sha(self.input)
        self.identity_path.write_text(json.dumps(self.identities), encoding="ascii")
        self.report["input_identities_sha256"] = sha(self.identity_path)
        (self.oracle/"metrics.json").write_text(json.dumps({"geometry": {
            "Ns": 1, "Nframes": 1, "tau_last": 128, "Ny": 512}}), encoding="ascii")
        check["oracle_artifact_sha256"]["metrics.json"] = sha(self.oracle/"metrics.json")
        package = self.oracle/"trecap_artifact_expectations_pkg.sv"
        package.write_text('localparam string TEXP_VECTOR_NAME = "'+VECTOR+'";\n'+
            "localparam int unsigned TEXP_NS = 1;\n"+
            "localparam int unsigned TEXP_NY = 512;\n"+
            "localparam int unsigned TEXP_FRAMES = 1;\n"+
            "localparam int unsigned TEXP_UNIQUE_BINS = 129;\n"+
            "localparam int unsigned TEXP_BIN_ROWS = 129;\n"+
            "localparam logic [55:0] TEXP_THR2 = 56'd4096;\n", encoding="ascii")
        check["oracle_artifact_sha256"][package.name] = sha(package)
        self.write_report()
        return check

    def test_boundary_fixture(self):
        self.boundary_fixture()
        self.assertEqual(verify_reference(self.root,self.evidence,[VECTOR])["status"],
                         "PASS_BOUNDED_BOUNDARY_VECTORS")
        self.assertEqual(selected_vectors(self.report,None),[VECTOR])

    def test_boundary_input_changed(self):
        self.boundary_fixture()
        self.input.write_bytes(b"001\n")
        self.reject()

    def test_boundary_missing_input_metadata(self):
        check=self.boundary_fixture()
        del check["input_artifact"]
        self.write_report()
        self.reject()

    def test_boundary_path_outside_case(self):
        check=self.boundary_fixture()
        check["input_artifact"]["path"]="reference_source.txt"
        self.write_report()
        self.reject()

    def test_boundary_absolute_path(self):
        check=self.boundary_fixture()
        check["input_artifact"]["path"]=str(self.input)
        self.write_report()
        self.reject()

    def test_boundary_zero_length(self):
        check=self.boundary_fixture()
        check["configuration"]["Ns"]=0
        self.write_report()
        self.reject()

    def test_boundary_wrong_frame_count(self):
        check=self.boundary_fixture()
        check["configuration"]["frames"]=2
        self.write_report()
        self.reject()

    def test_boundary_wrong_sample_encoding(self):
        check=self.boundary_fixture()
        check["input_artifact"]["signed"]=False
        self.write_report()
        self.reject()

    def test_boundary_wrong_threshold_range(self):
        check=self.boundary_fixture()
        check["configuration"]["THR2"]=1<<56
        self.write_report()
        self.reject()

    def test_boundary_oracle_geometry_disagrees(self):
        check=self.boundary_fixture()
        (self.oracle/"metrics.json").write_text(json.dumps({"geometry": {
            "Ns": 2, "Nframes": 2, "tau_last": 256, "Ny": 640}}), encoding="ascii")
        check["oracle_artifact_sha256"]["metrics.json"]=sha(self.oracle/"metrics.json")
        self.write_report()
        self.reject()

    def test_boundary_input_hash_not_manifest_bound(self):
        check=self.boundary_fixture()
        del self.identities[check["input_artifact"]["path"]]
        self.identity_path.write_text(json.dumps(self.identities),encoding="ascii")
        self.report["input_identities_sha256"]=sha(self.identity_path)
        self.write_report()
        self.reject()

    def test_boundary_noncanonical_input_even_if_rehashed(self):
        check=self.boundary_fixture()
        self.input.write_bytes(b"FFF\n")
        check["input_artifact"]["sha256"]=sha(self.input)
        self.identities[check["input_artifact"]["path"]]=sha(self.input)
        self.identity_path.write_text(json.dumps(self.identities),encoding="ascii")
        self.report["input_identities_sha256"]=sha(self.identity_path)
        self.write_report()
        self.reject()

    def test_boundary_decimal_string_threshold(self):
        check=self.boundary_fixture()
        check["configuration"]["THR2"]="4096"
        self.write_report()
        self.assertEqual(verify_reference(self.root,self.evidence,[VECTOR])["status"],
                         "PASS_BOUNDED_BOUNDARY_VECTORS")

    def test_boundary_noncanonical_threshold(self):
        check=self.boundary_fixture()
        for value in ("04096", "4.096e3", True, 4096.0):
            with self.subTest(value=value):
                check["configuration"]["THR2"]=value
                self.write_report()
                self.reject()

    def test_boundary_valid_but_mismatched_threshold(self):
        check=self.boundary_fixture()
        check["configuration"]["THR2"]=0
        self.write_report()
        self.reject()

    def test_boundary_package_wrong_name_even_if_rehashed(self):
        check=self.boundary_fixture()
        package=self.oracle/"trecap_artifact_expectations_pkg.sv"
        package.write_text(package.read_text(encoding="ascii").replace(VECTOR,"other_case"),encoding="ascii")
        check["oracle_artifact_sha256"][package.name]=sha(package)
        self.write_report()
        self.reject()

    def test_duplicate_case_with_mixed_status(self):
        self.report["checks"].append({"name":VECTOR,"status":"FAIL"})
        self.write_report()
        self.reject()

    def test_reject_duplicate_selection(self):
        with self.assertRaises(ValueError):
            selected_vectors({},[VECTOR,VECTOR])

    def test_reject_path_selection(self):
        for name in ("../outside","a/b","a\\b",""):
            with self.subTest(name=name), self.assertRaises(ValueError):
                selected_vectors({},[name])

    def test_reject_empty_selection(self):
        with self.assertRaises(ValueError):
            selected_vectors({},[])

    def test_valid_fixture(self):
        self.assertEqual(verify_reference(self.root,self.evidence,[VECTOR])["status"],
                         "PASS_BOUNDED_BASELINE")

    def test_identity_manifest_changed(self):
        self.identity_path.write_text("{}", encoding="ascii")
        self.reject()

    def test_empty_identity_even_if_rehashed(self):
        self.identity_path.write_text("{}", encoding="ascii")
        self.report["input_identities_sha256"] = sha(self.identity_path)
        self.write_report()
        self.reject()

    def test_source_changed(self):
        self.source.write_text("changed\n", encoding="ascii")
        self.reject()

    def test_qualification_source_disagrees(self):
        self.report["qualification_sources"]["reference_source.txt"] = "0"*64
        self.write_report()
        self.reject()

    def test_unpinned_expectations(self):
        self.report["checks"][0]["oracle_artifact_sha256"] = {}
        self.write_report()
        self.reject()

    def test_changed_expected_file(self):
        (self.oracle/"y_out.memh").write_text("001\n", encoding="ascii")
        self.reject()

    def test_missing_expected_file(self):
        (self.oracle/"ifft_output.csv").unlink()
        self.reject()

    def test_failed_reference(self):
        self.report["status"] = "FAIL"
        self.write_report()
        self.reject()

    def test_changed_input_during_qualification(self):
        self.report["input_identity_unchanged"] = False
        self.write_report()
        self.reject()

    def test_duplicate_vector_qualification(self):
        self.report["checks"] *= 2
        self.write_report()
        self.reject()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence",type=Path,required=True)
    args = parser.parse_args()
    path = args.evidence.resolve()
    path.relative_to((REPO/"runs/verification").resolve())
    path.parent.mkdir(parents=True,exist_ok=True)
    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(AdmissionWitnesses))
    report = {"scope":"synthetic reference-admission fault witnesses",
              "tests_run":result.testsRun,"failures":len(result.failures),
              "errors":len(result.errors),"outcome":"PASS" if result.wasSuccessful() else "FAIL",
              "test_source_sha256":sha(Path(__file__)),
              "runner_source_sha256":sha(REPO/"scripts/verification/core_replay.py")}
    with path.open("x",encoding="utf-8",newline="\n") as stream:
        json.dump(report,stream,indent=2);stream.write("\n")
    return 0 if result.wasSuccessful() else 1


if __name__=="__main__":
    raise SystemExit(main())
