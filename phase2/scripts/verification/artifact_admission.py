#!/usr/bin/env python3
"""Read-only V0 admission of the declared Rev-J artifact snapshot.

This checks bytes, encoding, declarations and local promotion provenance. It does
not execute the reference model, establish coefficient mathematics, validate RTL,
or authenticate the historical source archive. Quality bounds and suite coverage
are reported separately from admission of the artifacts that actually exist.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import platform
import re
import sys
import unicodedata
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any

BASE = {"N": 12, "L": 256, "P": 8, "H": 128, "F": 15, "G": 128,
        "D": 384, "PROTECT_DC": 1, "PROTECT_NYQ": 0, "THR2": "0"}
WIDTHS = {"W_Qw": 16, "W_can": 28, "W_can_pre": 29, "W_fft": 28,
          "W_fft_pre": 29, "W_ifft": 36, "W_mag2": 56, "W_ola": 37,
          "W_tw": 17, "W_u": 27, "W_z": 36}
CONTRACT = {"fft_mode": "custom_radix2_dit_bitrev_in_natural_out",
            "rounding_mode": "round_nearest_ties_away_from_zero",
            "tail_policy": "full_tail", "threshold_mapping": "raw_thr2"}
ENCODING = "fixed_width_lowercase_hex_lf"
HASH_RULE = "logical_integer_vector_fixed_width_hex_lf"
COEFFICIENTS = ("window_qw", "twiddle_re", "twiddle_im", "twiddle_inv_re", "twiddle_inv_im")
MANIFEST_PATHS = {
    "core_config_sha256": "artifacts/manifests/core_config_snapshot.json",
    "coeff_manifest_sha256": "artifacts/coefficients/coeff_manifest.json",
    "test_vectors_sha256": "artifacts/test_vectors/test_vectors.json",
    "quality_bounds_sha256": "artifacts/manifests/quality_bounds.json",
    "artifact_index_sha256": "artifacts/manifests/artifact_index.json",
}


class AdmissionError(ValueError):
    def __init__(self, code: str, path: str, detail: str):
        self.code, self.path, self.detail = code, path, detail
        super().__init__(f"{code}: {path}: {detail}")


def require(condition: bool, code: str, path: str, detail: str) -> None:
    if not condition:
        raise AdmissionError(code, path, detail)


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical_json(data: Any) -> bytes:
    return (json.dumps(data, sort_keys=True, separators=(",", ":"),
                       ensure_ascii=True, allow_nan=False) + "\n").encode("ascii")


def strict_json(data: bytes, path: str) -> Any:
    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in items:
            require(key not in result, "JSON_DUPLICATE_KEY", path, key)
            result[key] = value
        return result
    def bad_number(value: str) -> None:
        raise AdmissionError("JSON_NONFINITE", path, value)
    def bad_float(value: str) -> None:
        raise AdmissionError("JSON_FLOAT", path, "integer/string artifact contract rejects " + value)
    try:
        return json.loads(data.decode("utf-8"), object_pairs_hook=pairs, parse_constant=bad_number, parse_float=bad_float)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise AdmissionError("JSON_ENCODING", path, str(exc)) from exc


def portable_path(relative: str) -> str:
    require(isinstance(relative, str) and bool(relative), "UNSAFE_PATH", str(relative), "empty/non-string path")
    parts = relative.split("/")
    require(not PurePosixPath(relative).is_absolute() and "\\" not in relative
            and ":" not in relative and all(p not in ("", ".", "..") for p in parts)
            and relative == unicodedata.normalize("NFC", relative)
            and not any(ord(c) < 32 for c in relative),
            "UNSAFE_PATH", relative, "expected a portable repository-relative path")
    return relative


def decimal_string(value: Any, path: str, signed: bool = False) -> int:
    pattern = r"(?:0|-?[1-9][0-9]*)" if signed else r"(?:0|[1-9][0-9]*)"
    require(isinstance(value, str) and re.fullmatch(pattern, value) is not None,
            "DECIMAL_ENCODING", path, "expected canonical decimal string (no float conversion)")
    return int(value)


def integer(value: Any, path: str, minimum: int = 0) -> int:
    require(type(value) is int and value >= minimum, "INTEGER_TYPE", path, "expected bounded nonnegative JSON integer")
    return value


def inspect_memh(data: bytes, *, path: str, rows: int, width: int, signed: bool,
                 expected_sha: str | None = None, canonical_sha: str | None = None) -> list[int]:
    integer(rows, path, 1)
    integer(width, path, 1)
    require(width <= 64 and type(signed) is bool, "MEMH_FORMAT", path, "unsupported width/signed declaration")
    digits = (width + 3) // 4
    require(len(data) == rows * (digits + 1), "MEMH_LENGTH", path,
            f"expected {rows} rows of {digits} hex digits and LF; got {len(data)} bytes")
    require(re.fullmatch(rb"(?:[0-9a-f]{" + str(digits).encode() + rb"}\n){" + str(rows).encode() + rb"}", data) is not None,
            "MEMH_ENCODING", path, "only fixed-width lowercase hexadecimal followed by LF is accepted")
    raw = [int(line, 16) for line in data.splitlines()]
    require(all(v < (1 << width) for v in raw), "MEMH_UNUSED_BITS", path, "nonzero unused high bits")
    values = [v - (1 << width) if signed and v & (1 << (width - 1)) else v for v in raw]
    canonical = b"".join(f"{v & ((1 << width) - 1):0{digits}x}\n".encode("ascii") for v in values)
    if expected_sha is not None:
        require(sha256(data) == expected_sha, "HASH_MISMATCH", path, "raw SHA-256 differs")
    if canonical_sha is not None:
        require(sha256(canonical) == canonical_sha, "CANONICAL_HASH_MISMATCH", path, "logical-vector SHA-256 differs")
    return values


def tree_hash(records: list[dict[str, Any]]) -> str:
    digest = hashlib.sha256(b"TRECAP_REFERENCE_IMPORT_TREE_V1\0")
    for entry in sorted(records, key=lambda v: v["path"]):
        encoded = portable_path(entry["path"]).encode("utf-8")
        digest.update(len(encoded).to_bytes(4, "big"))
        digest.update(encoded)
        digest.update(integer(entry["size_bytes"], entry["path"]).to_bytes(8, "big"))
        require(re.fullmatch(r"[0-9a-f]{64}", entry["sha256"]) is not None,
                "HASH_ENCODING", entry["path"], "expected lowercase SHA-256")
        digest.update(bytes.fromhex(entry["sha256"]))
    return digest.hexdigest()


class Audit:
    def __init__(self, root: Path):
        self.root = root.resolve(strict=True)
        self.evidence: dict[str, dict[str, Any]] = {}
        self.vector_results: list[dict[str, Any]] = []
        self.quality_issues: list[dict[str, Any]] = []
        self.provenance: dict[str, Any] = {}

    def read(self, relative: str, expected: str | None = None, size: int | None = None) -> bytes:
        relative = portable_path(relative)
        path = self.root / relative
        try:
            resolved = path.resolve(strict=True)
            resolved.relative_to(self.root)
            require(path.is_file(), "MISSING_FILE", relative, "not a regular file")
            data = path.read_bytes()
        except (FileNotFoundError, NotADirectoryError) as exc:
            raise AdmissionError("MISSING_FILE", relative, "required file is absent") from exc
        except ValueError as exc:
            if isinstance(exc, AdmissionError):
                raise
            raise AdmissionError("UNSAFE_PATH", relative, "resolved path escapes repository") from exc
        except OSError as exc:
            raise AdmissionError("UNREADABLE_FILE", relative, type(exc).__name__) from exc
        if expected is not None:
            require(isinstance(expected, str) and re.fullmatch(r"[0-9a-f]{64}", expected) is not None,
                    "HASH_ENCODING", relative, "expected lowercase SHA-256")
            require(sha256(data) == expected, "HASH_MISMATCH", relative, "raw SHA-256 differs")
        if size is not None:
            require(len(data) == integer(size, relative), "SIZE_MISMATCH", relative, "byte count differs")
        record = {"path": relative, "size_bytes": len(data), "sha256": sha256(data)}
        require(relative not in self.evidence or self.evidence[relative] == record,
                "INPUT_CHANGED_DURING_AUDIT", relative, "repeated read changed")
        self.evidence[relative] = record
        return data

    def json(self, path: str, schema: str | None = None) -> dict[str, Any]:
        result = strict_json(self.read(path), path)
        require(isinstance(result, dict), "JSON_OBJECT", path, "expected object")
        if schema:
            require(result.get("schema") == schema, "SCHEMA_ID", path, f"expected {schema}")
        return result

    def memh(self, path: str, rows: int, width: int, signed: bool, expected: str, canonical: str | None = None) -> list[int]:
        return inspect_memh(self.read(path), path=path, rows=rows, width=width, signed=signed,
                            expected_sha=expected, canonical_sha=canonical)

    def declarations(self, manifest: dict[str, Any]) -> set[str]:
        seen: set[str] = set()
        for item in manifest["artifacts"]:
            path = portable_path(item["path"])
            require(path.casefold() not in seen, "DUPLICATE_PATH", path, "duplicate/case-colliding artifact")
            seen.add(path.casefold())
            require(item["required"] is True, "ARTIFACT_REQUIRED", path, "this snapshot admits required entries only")
            data = self.read(path, item["sha256"])
            kind = item["artifact_type"]
            if kind == "memh":
                inspect_memh(data, path=path, rows=item["rows"], width=item["width_bits"], signed=item["signed"],
                             expected_sha=item["sha256"], canonical_sha=item["canonical_sha256"])
            elif kind == "json":
                strict_json(data, path)
            else:
                require(kind == "csv", "ARTIFACT_TYPE", path, f"unsupported type {kind}")
        return seen

    def csv(self, path: str, header: list[str], count: int) -> list[dict[str, int]]:
        data = self.read(path)
        require(data.endswith(b"\n") and b"\r" not in data, "CSV_ENCODING", path, "expected LF-delimited rows")
        try:
            rows = list(csv.reader(io.StringIO(data.decode("ascii"), newline="")))
        except (UnicodeError, csv.Error) as exc:
            raise AdmissionError("CSV_ENCODING", path, str(exc)) from exc
        require(bool(rows) and rows[0] == header, "CSV_HEADER", path, "header differs from artifact contract")
        require(len(rows) == count + 1, "CSV_ROWS", path, "data row count differs")
        result = []
        for row in rows[1:]:
            require(len(row) == len(header), "CSV_COLUMNS", path, "column count differs")
            result.append({key: decimal_string(value, path, signed=key in ("real", "imag")) for key, value in zip(header, row)})
        return result

    def run(self, required_generators: list[str]) -> dict[str, Any]:
        core = self.json("spec/generated/core_config.json", "trecap_phase2_core_config_v1")
        require(canonical_json(core["configuration"]) == canonical_json(BASE) and canonical_json(core["widths"]) == canonical_json(WIDTHS) and core["contract"] == CONTRACT,
                "CORE_CONFIG", "spec/generated/core_config.json", "unsupported Rev-J baseline")
        require(self.json(MANIFEST_PATHS["core_config_sha256"]) == core, "CONFIG_SNAPSHOT", MANIFEST_PATHS["core_config_sha256"], "snapshot differs")
        require(self.json("spec/generated/width_config.json")["widths"] == WIDTHS,
                "WIDTH_CONFIG", "spec/generated/width_config.json", "width declarations differ")
        contract = self.json("spec/generated/artifact_contract.json", "trecap_phase2_artifact_contract_v1")
        require(contract["artifact_contract"] == core["artifact_contract"], "ARTIFACT_CONTRACT", "spec/generated/artifact_contract.json", "generated views differ")
        require(core["artifact_contract"]["memh_encoding"] == ENCODING and core["artifact_contract"]["hash_rule"] == HASH_RULE,
                "ARTIFACT_CONTRACT", "spec/generated/core_config.json", "unsupported encoding/hash rule")
        index = self.json("artifacts/manifests/artifact_index.json", "trecap_phase2_artifact_index_v1")
        release = self.json("artifacts/manifests/frozen_release_manifest.json", "trecap_phase2_frozen_release_manifest_v1")
        indexed, frozen = self.declarations(index), self.declarations(release)
        require(frozen == indexed | {"artifacts/manifests/artifact_index.json"}, "MANIFEST_SET", "artifacts/manifests/frozen_release_manifest.json", "artifact sets differ")
        for key, path in MANIFEST_PATHS.items():
            self.read(path, release["manifest_hashes"][key])
            if key != "artifact_index_sha256":
                self.read(path, index[key])
        coeff = self.json("artifacts/coefficients/coeff_manifest.json", "trecap_phase2_coeff_manifest_v1")
        require(canonical_json(coeff["configuration"]) == canonical_json(BASE) and canonical_json(coeff["widths"]) == canonical_json(WIDTHS),
                "COEFFICIENT_CONFIG", "artifacts/coefficients/coeff_manifest.json", "baseline differs")
        require(set(coeff["coefficients"]) == set(COEFFICIENTS), "COEFFICIENT_SET", "artifacts/coefficients/coeff_manifest.json", "five tables required")
        for name in COEFFICIENTS:
            item = coeff["coefficients"][name]
            expected = {"file": name + ".memh", "rows": 256, "width_bits": 16 if name == "window_qw" else 17,
                        "signed": name != "window_qw", "q_format": "Q0.15_unsigned_endpoint_one" if name == "window_qw" else "Q1.15_signed_endpoint_one"}
            require(all(item[k] == v and type(item[k]) is type(v) for k, v in expected.items())
                    and contract["coefficient_memh"][name] == expected,
                    "COEFFICIENT_FORMAT", name, "table format differs from Rev-J")
            require(coeff["hashes"][name + "_sha256"] == item["sha256"] and coeff["artifact_rows"][name] == 256,
                    "COEFFICIENT_DECLARATION", name, "duplicate table declarations differ")
            self.memh("artifacts/coefficients/" + item["file"], 256, item["width_bits"], item["signed"], item["sha256"], item["canonical_sha256"])
        vector_manifest = self.json("artifacts/test_vectors/test_vectors.json", "trecap_phase2_test_vectors_v1")
        vectors = vector_manifest["vectors"]
        require(bool(vectors), "VECTOR_SET", "artifacts/test_vectors/test_vectors.json", "empty suite")
        names: set[str] = set()
        quality = self.json("artifacts/manifests/quality_bounds.json", "trecap_phase2_quality_bounds_v1")
        require(quality["hashes"] == coeff["hashes"], "QUALITY_TABLE_HASH", "artifacts/manifests/quality_bounds.json", "table identities differ")
        expected_paths = {MANIFEST_PATHS[k] for k in ("core_config_sha256", "coeff_manifest_sha256", "test_vectors_sha256", "quality_bounds_sha256")}
        expected_paths |= {"artifacts/coefficients/" + n + ".memh" for n in COEFFICIENTS}
        for vector in vectors:
            name = vector["name"]
            require(isinstance(name, str) and re.fullmatch(r"[a-zA-Z0-9_-]+", name) is not None and name.casefold() not in names,
                    "VECTOR_NAME", str(name), "invalid/duplicate vector name")
            names.add(name.casefold())
            paths = {"config": f"artifacts/test_vectors/{name}/config.json", "x_in": f"artifacts/test_vectors/{name}/x_in.memh",
                     **{k: f"artifacts/reference_outputs/{name}/{k}.{ 'memh' if k == 'y_out' else 'json' if k == 'metrics' else 'csv'}"
                        for k in ("y_out", "metrics", "frame_stats")}}
            if vector.get("requires_bin_stats", False):
                paths["bin_stats"] = f"artifacts/reference_outputs/{name}/bin_stats.csv"
            expected_paths.update(paths.values())
            for key, path in paths.items():
                self.read(path, vector[key + "_sha256"])
            cfg = self.json(paths["config"], "trecap_phase2_vector_config_v1")
            metrics = self.json(paths["metrics"], "trecap_phase2_metrics_v1")
            ns = integer(vector["Ns"], paths["config"], 1)
            frames = (ns + BASE["L"] - 2) // BASE["H"]
            ny = frames * BASE["H"] + BASE["G"] + BASE["L"]
            threshold = decimal_string(vector["THR2"], paths["config"])
            require(threshold < (1 << WIDTHS["W_mag2"]), "THRESHOLD_RANGE", paths["config"], "THR2 exceeds unsigned mag2")
            config = {**BASE, "Ns": ns, "Ny": ny, "frames": frames, "THR2": vector["THR2"],
                      "PROTECT_DC": vector["PROTECT_DC"], "PROTECT_NYQ": vector["PROTECT_NYQ"]}
            require(all(type(config[k]) is int and config[k] in (0, 1) for k in ("PROTECT_DC", "PROTECT_NYQ")), "PROTECTION_FLAG", paths["config"], "flag outside 0/1")
            require(canonical_json(cfg["configuration"]) == canonical_json(config) and canonical_json(cfg["widths"]) == canonical_json(WIDTHS) and cfg["hashes"] == coeff["hashes"],
                    "VECTOR_CONFIG", paths["config"], "geometry, widths, threshold or coefficient hashes differ")
            require(all(cfg["contract"].get(k) == v for k, v in {**CONTRACT, "memh_encoding": ENCODING, "hash_rule": HASH_RULE}.items())
                    and vector["tail_policy"] == "full_tail" and vector["rounding"] == CONTRACT["rounding_mode"],
                    "VECTOR_CONTRACT", paths["config"], "tail/arithmetic/encoding declaration differs")
            streams = {k + "_sha256": vector[k + "_sha256"] for k in ("x_in", "y_out")}
            require(cfg["stream_hashes"] == streams and cfg["vector_name"] == name, "VECTOR_IDENTITY", paths["config"], "stream/name mismatch")
            for key in ("vector_name", "configuration", "contract", "widths", "hashes", "stream_hashes"):
                require(metrics[key] == cfg[key], "METRICS_CONFIG", paths["metrics"], f"{key} differs from vector")
            rows = {**{n: 256 for n in COEFFICIENTS}, "x_in": ns, "y_out": ny, "frame_stats_data_rows": frames}
            if "bin_stats" in paths:
                rows["bin_stats_data_rows"] = frames * 129
            require(cfg["artifact_rows"] == rows, "VECTOR_ROWS", paths["config"], "full-tail artifact counts differ")
            x = self.memh(paths["x_in"], ns, 12, True, streams["x_in_sha256"])
            y = self.memh(paths["y_out"], ny, 12, True, streams["y_out_sha256"])
            frame_rows = self.csv(paths["frame_stats"], contract["frame_stats_header"], frames)
            require([f["frame_idx"] for f in frame_rows] == list(range(frames)), "FRAME_INDEX", paths["frame_stats"], "indices not contiguous")
            for f in frame_rows:
                require(f["unique_bins"] == 129 and 0 <= f["unique_suppressed_bins"] <= 129
                        and f["eligible_unique_bins"] == 129 - config["PROTECT_DC"] - config["PROTECT_NYQ"]
                        and 0 <= f["eligible_suppressed_bins"] <= f["eligible_unique_bins"]
                        and f["eligible_kept_mag2"] <= f["eligible_total_mag2"], "FRAME_BOUNDS", paths["frame_stats"], "counter bounds inconsistent")
            for section, keys in (("suppression_totals", contract["frame_stats_header"][1:5]), ("spectral_totals", contract["frame_stats_header"][5:])):
                require(set(metrics[section]) == set(keys), "METRICS_FIELDS", paths["metrics"], f"{section} fields differ")
                for key in keys:
                    require(decimal_string(metrics[section][key], paths["metrics"]) == sum(f[key] for f in frame_rows),
                            "METRICS_TOTAL", paths["metrics"], f"{key} differs from frame rows")
            if "bin_stats" in paths:
                bins = self.csv(paths["bin_stats"], contract["bin_stats_header"], frames * 129)
                require([(b["frame_idx"], b["bin_idx"]) for b in bins] == [(f, k) for f in range(frames) for k in range(129)],
                        "BIN_INDEX", paths["bin_stats"], "frame/bin ordering differs")
                require(all(b[k] in (0, 1) for b in bins for k in ("eligible", "pre_mask", "mask")), "BIN_FLAGS", paths["bin_stats"], "flags outside 0/1")
            errors = [sample - (x[i - BASE["D"]] if 0 <= i - BASE["D"] < ns else 0) for i, sample in enumerate(y)]
            observed = {"sum_abs_err": str(sum(abs(e) for e in errors)), "sum_sq_err": str(sum(e * e for e in errors)),
                        "max_abs_err": str(max(abs(e) for e in errors)), "error_sample_count": str(ny)}
            require(metrics["time_domain_errors"] == observed, "STORED_ERROR_SUMMARY", paths["metrics"], "stored y versus delayed x disagrees with metrics")
            bound = quality["bounds"].get(name)
            if bound is None:
                self.quality_issues.append({"code": "QUALITY_BOUND_MISSING", "vector": name})
            else:
                require(all(bound[k] == streams[k] for k in streams), "QUALITY_STREAM_HASH", name, "bound stream identities differ")
                for key in ("max_abs_err", "sum_sq_err", "error_sample_count"):
                    decimal_string(bound[key], name)
                require(bound["error_sample_count"] == str(ny), "QUALITY_SAMPLE_COUNT", name, "bound sample domain differs")
                if any(quality["configuration"].get(k) != config[k] for k in BASE):
                    self.quality_issues.append({"code": "QUALITY_CONFIG_AMBIGUOUS", "vector": name,
                                                "bounds_configuration": quality["configuration"],
                                                "vector_configuration": {k: config[k] for k in BASE}})
                if any(int(observed[k]) > int(bound[k]) for k in ("max_abs_err", "sum_sq_err")):
                    self.quality_issues.append({"code": "QUALITY_STORED_BOUND_EXCEEDED", "vector": name})
            self.vector_results.append({"name": name, "generator": vector["generator"], "Ns": ns, "Ny": ny, "frames": frames,
                                        "THR2": vector["THR2"], "bin_statistics_present": "bin_stats" in paths,
                                        "stored_stream_error_summary": observed, "artifact_admission": "PASS"})
        require(indexed == {p.casefold() for p in expected_paths}, "MANIFEST_SET", "artifacts/manifests/artifact_index.json", "declared artifact set omits/adds vector/table data")
        self.audit_import()
        self.provenance["generator_source_identity"] = self.generator_identity(coeff, vector_manifest)
        # A final identity pass detects changes between the first and last reads.
        for record in list(self.evidence.values()):
            self.read(record["path"], record["sha256"], record["size_bytes"])
        generators = sorted({v["generator"] for v in self.vector_results})
        missing = sorted(set(required_generators) - set(generators))
        return {"artifact_admission": {"status": "PASS", "declared_vector_count": len(vectors), "coefficient_count": 5},
                "local_provenance": self.provenance,
                "quality_bound_admission": {"status": "BLOCKED_CONTRACT" if self.quality_issues else "METADATA_CONSISTENT_NOT_QUALIFIED",
                                            "issues": self.quality_issues,
                                            "numerical_oracle_qualified": False, "acceptance_limits_approved": False},
                "suite_coverage": {"status": "INCOMPLETE" if missing else "DECLARED_SET_ONLY", "present_generators": generators,
                                   "requested_generators": sorted(set(required_generators)), "missing_generators": missing,
                                   "normative_suite_completeness_claimed": False},
                "vectors": self.vector_results}

    def generator_identity(self, coefficients: dict[str, Any], vectors: dict[str, Any]) -> dict[str, Any]:
        records = []
        for tool, manifest in (("gen_coeffs.py", coefficients), ("gen_vectors.py", vectors)):
            paths = ["sw/reference_model/tools/" + tool, "sw/reference_model/tools/_trecap_tool_common.py"]
            if tool == "gen_vectors.py":
                paths += [p.relative_to(self.root).as_posix() for p in
                          (self.root / "sw/reference_model/python/trecap_golden/generators").glob("*.py")]
            digest = hashlib.sha256()
            for path in sorted(paths):
                digest.update(PurePosixPath(path).name.encode("utf-8"))
                digest.update(b"\0")
                digest.update(self.read(path))
                digest.update(b"\0")
            recorded = manifest["generator_source_sha256"]
            require(isinstance(recorded, str) and re.fullmatch(r"[0-9a-f]{64}", recorded) is not None,
                    "HASH_ENCODING", tool, "invalid generator source hash")
            records.append({"tool": "sw/reference_model/tools/" + tool,
                            "declared_sha256": recorded, "current_recipe_sha256": digest.hexdigest(),
                            "status": "MATCH" if recorded == digest.hexdigest() else "SOURCE_IDENTITY_MISMATCH",
                            "source_paths": sorted(paths)})
        return {"status": "MATCH_RECORDED_RECIPE" if all(r["status"] == "MATCH" for r in records)
                else "HISTORICAL_GENERATOR_IDENTITY_UNRESOLVED",
                "records": records,
                "recipe": "Sorted source paths; basename UTF-8, NUL, raw bytes, NUL per file; same declared legacy recipe",
                "dependency_closure_qualified": False, "regeneration_executed": False}

    def audit_import(self) -> None:
        path = "artifacts/manifests/reference_import_manifest.json"
        raw = self.read(path)
        manifest = self.json(path, "trecap_phase2_reference_import_manifest_v3")
        require(raw == canonical_json(manifest), "IMPORT_SERIALIZATION", path, "not canonical compact ASCII JSON with LF")
        require(self.read("sw/reference_model/import_manifest.json") == raw, "IMPORT_MANIFEST_COPY", path, "embedded import manifest differs")
        require(manifest["reference_root"] == "sw/reference_model", "IMPORT_ROOT", path, "unexpected reference root")
        for entries_key, count_key, tree_key in (("imported_reference_files", "imported_reference_file_count", "imported_tree_sha256"),
                                                  ("promoted_root_files", "promoted_root_file_count", "promoted_tree_sha256")):
            entries = manifest[entries_key]
            require(len(entries) == manifest[count_key] and len({e["path"].casefold() for e in entries}) == len(entries),
                    "IMPORT_COUNT", path, "record count/uniqueness differs")
            require(tree_hash(entries) == manifest[tree_key], "IMPORT_TREE_HASH", path, "declared tree hash differs")
            for entry in entries:
                self.read(entry["path"], entry["sha256"], entry["size_bytes"])
        promotions = self.json("config/reference_import_promotions.json")
        require(sha256(canonical_json(promotions)) == manifest["promotion_map_sha256"], "PROMOTION_MAP_HASH", path, "promotion map differs")
        expected = {(e["destination_path"], "sw/reference_model/" + e["source_path"]) for e in promotions["promotions"]}
        actual = {(e["path"], e["source_path"]) for e in manifest["promoted_root_files"]}
        require(actual == expected and len(expected) == len(promotions["promotions"]), "PROMOTION_MAP_SET", path, "promotion pairs differ")
        for entry in manifest["promoted_root_files"]:
            require(entry["operation"] == "verbatim_copy", "PROMOTION_OPERATION", entry["path"], "unsupported promotion operation")
            require(self.read(entry["path"]) == self.read(entry["source_path"]), "PROMOTION_BYTES", entry["path"], "root and embedded bytes differ")
        self.provenance = {"status": "PASS_LOCAL_SNAPSHOT", "imported_file_count": manifest["imported_reference_file_count"],
                           "promoted_file_count": manifest["promoted_root_file_count"],
                           "imported_tree_sha256": manifest["imported_tree_sha256"], "promoted_tree_sha256": manifest["promoted_tree_sha256"],
                           "historical_provenance_status": manifest["provenance_status"],
                           "historical_source": manifest["source"], "archive_authenticity_qualified": False,
                           "historical_acceptance_flags_promoted": False}


def audit_repository(root: Path, required_generators: list[str] | None = None) -> dict[str, Any]:
    audit = Audit(root)
    report: dict[str, Any] = {"schema": "trecap_verification_artifact_admission_v1", "campaign": "V0",
                              "created_utc": datetime.now(timezone.utc).isoformat(), "python_version": platform.python_version(),
                              "scope": "Declared frozen bytes, exact encoding, metadata consistency and local promotion provenance; no model/RTL execution",
                              "numeric_policy": "Arbitrary-precision integers; wide totals and thresholds remain decimal strings",
                              "checker_sha256": sha256(Path(__file__).read_bytes()),
                              "limitations": ["Repository manifests are local trust anchors, not authenticated external signatures.",
                                              "Historical golden/frozen labels and acceptance flags are not current verification results.",
                                              "No coefficient mathematics, reference algorithm, RTL, board, power or energy signoff.",
                                              "Structural field checks are implemented here; a complete JSON Schema validation is not claimed."]}
    try:
        report.update(audit.run(required_generators or []))
        report["outcome"] = "PASS_ARTIFACT_ADMISSION_ONLY"
    except (AdmissionError, KeyError, TypeError, OSError, ValueError, OverflowError) as exc:
        error = {"code": exc.code, "path": exc.path, "detail": exc.detail} if isinstance(exc, AdmissionError) else {
            "code": "MALFORMED_OR_UNREADABLE_INPUT", "path": "", "detail": type(exc).__name__ + ": " + str(exc)}
        report.update(outcome="FAIL", artifact_admission={"status": "FAIL"}, errors=[error])
    report["evidence"] = sorted(audit.evidence.values(), key=lambda e: e["path"])
    report["evidence_count"] = len(audit.evidence)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--output", type=Path, required=True, help="New report path under the repository runs/verification directory")
    parser.add_argument("--require-generator", action="append", default=[], help="Report missing requested suite classes separately from corrupt artifacts")
    args = parser.parse_args()
    root = args.repo_root.resolve(strict=True)
    output = args.output.resolve()
    try:
        output.relative_to(root / "runs" / "verification")
    except ValueError:
        parser.error("--output must be under --repo-root/runs/verification; source artifacts are read-only")
    report = audit_repository(root, args.require_generator)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(report, stream, indent=2, sort_keys=True, ensure_ascii=True, allow_nan=False)
        stream.write("\n")
    print(json.dumps({"outcome": report["outcome"], "artifact_admission": report["artifact_admission"],
                      "quality_bound_admission": report.get("quality_bound_admission", {}).get("status"),
                      "evidence_count": report["evidence_count"], "errors": report.get("errors", [])}, ensure_ascii=True))
    return 0 if report["outcome"] == "PASS_ARTIFACT_ADMISSION_ONLY" else 1


if __name__ == "__main__":
    raise SystemExit(main())
