#!/usr/bin/env python3
"""Post-check a finite core replay capture without trusting simulator PASS text.

The caller must qualify and pin the supplied oracle separately. This checker
compares immutable capture files to that oracle and independently checks event
ownership, full-tail geometry and metric arithmetic. It does not run a model or
simulator and does not infer campaign signoff from a passing comparison.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import platform
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

FRAME = ("frame_idx", "unique_bins", "unique_suppressed_bins", "eligible_unique_bins",
         "eligible_suppressed_bins", "eligible_kept_mag2", "eligible_total_mag2")
BIN = ("frame_idx", "bin_idx", "real", "imag", "mag2", "eligible", "pre_mask", "mask")
IFFT = ("frame_idx", "offset", "re", "im")
SOURCE = ("cycle", "sample_idx", "data", "phase")
ACCEPT = ("cycle", "sample_idx", "y_out")
COMMIT = ("cycle", "sample_idx", "x_delayed", "y_out", "error_i16")
LIFECYCLE = ("cycle", "event", "source_count", "output_count")
GROUPS = {"suppression_totals": FRAME[1:5], "spectral_totals": FRAME[5:],
          "time_domain_errors": ("sum_abs_err", "sum_sq_err", "max_abs_err", "error_sample_count")}
SIGNED = {"real", "imag", "re", "im", "data", "y_out", "x_delayed", "error_i16"}


class CaptureError(ValueError):
    def __init__(self, code: str, file: str, detail: str):
        self.code, self.file, self.detail = code, file, detail
        super().__init__(f"{code}: {file}: {detail}")


def need(condition: bool, code: str, file: str, detail: str) -> None:
    if not condition:
        raise CaptureError(code, file, detail)


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def number(text: Any, file: str, signed: bool = False) -> int:
    pattern = r"(?:0|-?[1-9][0-9]*)" if signed else r"(?:0|[1-9][0-9]*)"
    need(isinstance(text, str) and re.fullmatch(pattern, text) is not None,
         "INTEGER_ENCODING", file, "expected canonical decimal integer, no X/Z/float conversion")
    return int(text)


def natural(value: Any, file: str, minimum: int = 0) -> int:
    need(type(value) is int and value >= minimum, "JSON_INTEGER", file, "expected nonnegative JSON integer")
    return value


def strict_json(data: bytes, file: str) -> dict[str, Any]:
    def pairs(items):
        result = {}
        for key, value in items:
            need(key not in result, "JSON_DUPLICATE_KEY", file, key)
            result[key] = value
        return result
    def noninteger(value):
        raise CaptureError("JSON_NONINTEGER", file, value)
    try:
        result = json.loads(data.decode("utf-8"), object_pairs_hook=pairs,
                            parse_constant=noninteger, parse_float=noninteger)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise CaptureError("JSON_SYNTAX", file, type(exc).__name__) from exc
    need(isinstance(result, dict), "JSON_OBJECT", file, "expected object")
    return result


class Check:
    def __init__(self, capture: Path, oracle: Path, x_path: Path):
        self.roots = {"capture": capture.resolve(), "oracle": oracle.resolve()}
        self.x_path = x_path.resolve()
        self.identities: dict[str, dict[str, Any]] = {}
        self.paths: dict[str, Path] = {}
        self.checks: list[str] = []

    def read(self, area: str, name: str = "") -> bytes:
        label = f"{area}/{name}" if name else area
        path = self.x_path if area == "input" else self.roots[area] / name
        try:
            need(path.is_file(), "MISSING_FILE", label, "required evidence file is missing")
            if area != "input":
                need(path.resolve().parent == self.roots[area], "UNSAFE_PATH", label, "evidence file escapes supplied directory")
            data = path.read_bytes()
        except OSError as exc:
            raise CaptureError("UNREADABLE_FILE", label, type(exc).__name__) from exc
        need(bool(data), "EMPTY_FILE", label, "required evidence file is empty")
        identity = {"file": label, "size_bytes": len(data), "sha256": digest(data)}
        need(label not in self.identities or identity == self.identities[label],
             "INPUT_CHANGED", label, "evidence changed between reads")
        self.identities[label], self.paths[label] = identity, path
        return data

    def json(self, area: str, name: str) -> dict[str, Any]:
        return strict_json(self.read(area, name), f"{area}/{name}")

    def memh(self, area: str, name: str = "", rows: int | None = None) -> list[int]:
        data, label = self.read(area, name), f"{area}/{name}"
        need(re.fullmatch(rb"(?:[0-9a-f]{3}\n)+", data) is not None,
             "MEMH_ENCODING", label, "expected signed12 fixed-width lowercase hexadecimal with LF")
        raw = [int(line, 16) for line in data.splitlines()]
        if rows is not None:
            need(len(raw) == rows, "ROW_COUNT", label, f"expected {rows}, found {len(raw)}")
        return [v - 4096 if v >= 2048 else v for v in raw]

    def csv(self, area: str, name: str, header: tuple[str, ...], count: int,
            text_fields: tuple[str, ...] = ()) -> list[dict[str, Any]]:
        label = f"{area}/{name}"
        data = self.read(area, name)
        need(data.endswith(b"\n") and b"\r" not in data, "CSV_ENCODING", label, "expected complete LF rows")
        try:
            rows = list(csv.reader(io.StringIO(data.decode("ascii"), newline=""), strict=True))
        except (UnicodeError, csv.Error) as exc:
            raise CaptureError("CSV_ENCODING", label, type(exc).__name__) from exc
        need(bool(rows) and tuple(rows[0]) == header, "CSV_HEADER", label, "header differs")
        need(len(rows) == count + 1, "ROW_COUNT", label, f"expected {count}, found {len(rows)-1}")
        parsed = []
        for row in rows[1:]:
            need(len(row) == len(header), "CSV_COLUMNS", label, "column count differs")
            parsed.append({k: v if k in text_fields else number(v, label, signed=k in SIGNED)
                           for k, v in zip(header, row)})
        # Reject alternate CSV spellings that hide truncation or X/Z values.
        canonical = ",".join(header) + "\n" + "".join(",".join(str(row[k]) for k in header) + "\n" for row in parsed)
        need(data == canonical.encode("ascii"), "CSV_CANONICAL", label, "noncanonical field quoting/spacing")
        return parsed

    @staticmethod
    def match(actual: list[Any], expected: list[Any], file: str) -> None:
        need(len(actual) == len(expected), "ROW_COUNT", file, "actual/expected row counts differ")
        for index, (left, right) in enumerate(zip(actual, expected)):
            need(left == right, "VALUE_MISMATCH", file, f"row {index}: actual={left!s}; expected={right!s}")

    @staticmethod
    def chronology(rows: list[dict[str, Any]], file: str) -> None:
        need(all(row["sample_idx"] == index for index, row in enumerate(rows)),
             "INDEX_SEQUENCE", file, "indices must start at zero and advance exactly once")
        need(all(0 < row["cycle"] < (1 << 64) for row in rows) and
             all(left["cycle"] < right["cycle"] for left, right in zip(rows, rows[1:])),
             "CYCLE_ORDER", file, "accepted events require strictly increasing positive cycles")

    @staticmethod
    def metrics(value: dict[str, Any], file: str) -> dict[str, int]:
        result = {}
        for group, fields in GROUPS.items():
            need(isinstance(value[group], dict) and set(value[group]) == set(fields),
                 "METRIC_FIELDS", file, f"exact {group} field set required")
            result.update({key: number(value[group][key], file) for key in fields})
        return result

    def run(self) -> dict[str, Any]:
        expected_metrics = self.json("oracle", "metrics.json")
        observed = self.json("capture", "metrics_observed.json")
        need(expected_metrics["schema"] == "trecap_reference_qualification_numeric_metrics_v1",
             "SCHEMA_ID", "oracle/metrics.json", "unrecognized qualified-oracle numeric format")
        need(observed["schema"] == "trecap_phase2_rtl_metrics_observed_v1",
             "SCHEMA_ID", "capture/metrics_observed.json", "unrecognized RTL capture format")
        # Both frozen inputs (<case>/x_in.memh) and supplemental inputs
        # (<case>/input/x_in.memh) use the qualified <case>/oracle layout.
        need(observed["vector_name"] == self.roots["oracle"].parent.name,
             "VECTOR_IDENTITY", "capture/metrics_observed.json", "vector_name differs from qualified oracle case directory")
        geometry = expected_metrics["geometry"]
        need(set(geometry) == {"Ns", "Nframes", "tau_last", "Ny"}, "GEOMETRY_FIELDS", "oracle/metrics.json", "unexpected geometry")
        ns, frames, tau, ny = [natural(geometry[k], "oracle/metrics.json", 1) for k in ("Ns", "Nframes", "tau_last", "Ny")]
        need(frames == (ns + 254) // 128 and tau == frames * 128 and ny == tau + 384,
             "FULL_TAIL_GEOMETRY", "oracle/metrics.json", "Rev-J full-tail geometry differs")
        x = self.memh("input", rows=ns)
        expected_y = self.memh("oracle", "y_out.memh", ny)
        y = self.memh("capture", "y_out.memh", ny)
        self.match(y, expected_y, "capture/y_out.memh")
        expected_frames = self.csv("oracle", "frame_stats.csv", FRAME, frames)
        frame_rows = self.csv("capture", "frame_stats.csv", FRAME, frames)
        self.match(frame_rows, expected_frames, "capture/frame_stats.csv")
        expected_bins = self.csv("oracle", "bin_stats.csv", BIN, frames * 129)
        bin_rows = self.csv("capture", "bin_stats.csv", BIN, frames * 129)
        self.match(bin_rows, expected_bins, "capture/bin_stats.csv")
        need([r["frame_idx"] for r in frame_rows] == list(range(frames)), "FRAME_INDEX", "capture/frame_stats.csv", "frame indices differ")
        need([(r["frame_idx"], r["bin_idx"]) for r in bin_rows] == [(f, k) for f in range(frames) for k in range(129)],
             "BIN_INDEX", "capture/bin_stats.csv", "frame/bin ordering differs")
        self.checks += ["exact_y", "exact_frame_statistics", "exact_unique_bin_statistics", "full_tail_geometry"]

        # Recalculate row-derived totals independently of both stored metric JSON files.
        for frame, stats in enumerate(frame_rows):
            bins = bin_rows[frame * 129:(frame + 1) * 129]
            need(all(b[k] in (0, 1) for b in bins for k in ("eligible", "pre_mask", "mask")),
                 "BIN_FLAGS", "capture/bin_stats.csv", "flag outside 0/1")
            need(all(b["mag2"] == b["real"] ** 2 + b["imag"] ** 2 for b in bins),
                 "BIN_MAGNITUDE", "capture/bin_stats.csv", "magnitude does not equal squared components")
            weights = [1] + [2] * 127 + [1]
            derived = [129, sum(b["mask"] for b in bins), sum(b["eligible"] for b in bins),
                       sum(b["eligible"] * b["mask"] for b in bins),
                       sum(w * b["eligible"] * (1-b["mask"]) * b["mag2"] for w, b in zip(weights, bins)),
                       sum(w * b["eligible"] * b["mag2"] for w, b in zip(weights, bins))]
            need([stats[k] for k in FRAME[1:]] == derived, "FRAME_BIN_TOTAL", "capture/frame_stats.csv", f"frame {frame} differs from bins")
        errors = [(x[i-384] if 0 <= i-384 < ns else 0) - sample for i, sample in enumerate(y)]
        calculated = {k: sum(row[k] for row in frame_rows) for k in FRAME[1:]}
        calculated.update(sum_abs_err=sum(abs(e) for e in errors), sum_sq_err=sum(e*e for e in errors),
                          max_abs_err=max(abs(e) for e in errors), error_sample_count=ny)
        for value, file in ((expected_metrics, "oracle/metrics.json"), (observed, "capture/metrics_observed.json")):
            need(self.metrics(value, file) == calculated, "METRIC_VALUE", file, "ten metrics differ from exact row-derived totals")
        need(isinstance(observed["internal_metrics"], dict) and set(observed["internal_metrics"]) == set(GROUPS["time_domain_errors"]),
             "METRIC_FIELDS", "capture/metrics_observed.json", "internal metric fields differ")
        need({k: number(v, "capture/metrics_observed.json") for k, v in observed["internal_metrics"].items()} ==
             {k: calculated[k] for k in GROUPS["time_domain_errors"]}, "INTERNAL_METRICS", "capture/metrics_observed.json", "RTL accumulator values differ")
        wanted_counts = {"y_rows": ny, "frame_rows": frames, "bin_rows": frames * 129, "done_pulses": 1}
        need(set(observed["counts"]) == set(wanted_counts) and all(type(observed["counts"][k]) is int and observed["counts"][k] == v for k, v in wanted_counts.items()),
             "COMPLETION_COUNTS", "capture/metrics_observed.json", "capture completion cardinalities differ")
        wanted_status = {"completion_error_sticky": 0, "core_overflow_flags": "0", "metric_overflow_sticky": 0,
                         "protocol_error_sticky": 0, "saturation_sticky": 0, "top_overflow_flags": "0"}
        need(set(observed["status"]) == set(wanted_status) and all(type(observed["status"][k]) is type(v) and observed["status"][k] == v for k, v in wanted_status.items()),
             "ERROR_STATUS", "capture/metrics_observed.json", "missing/nonzero/unknown error status")
        self.checks += ["ten_exact_metrics", "internal_error_accumulators", "frame_bin_metric_consistency", "completion_status"]

        source = self.csv("capture", "source_accepts.csv", SOURCE, ny, ("phase",))
        accepts = self.csv("capture", "y_accepts.csv", ACCEPT, ny)
        commits = self.csv("capture", "sample_commits.csv", COMMIT, ny)
        for rows, file in ((source, "source_accepts.csv"), (accepts, "y_accepts.csv"), (commits, "sample_commits.csv")):
            self.chronology(rows, "capture/" + file)
        for i, (src, accepted, committed) in enumerate(zip(source, accepts, commits)):
            phase = "input" if i < ns else "analysis_flush" if i < tau else "tail_drain"
            need(src["data"] == (x[i] if i < ns else 0) and src["phase"] == phase,
                 "SOURCE_VALUE_PHASE", "capture/source_accepts.csv", f"source row {i} differs")
            delayed = x[i-384] if 0 <= i-384 < ns else 0
            need(accepted["y_out"] == y[i], "ACCEPT_VALUE", "capture/y_accepts.csv", f"accepted y row {i} differs")
            need([committed[k] for k in ("x_delayed", "y_out", "error_i16")] == [delayed, y[i], errors[i]],
                 "COMMIT_VALUE", "capture/sample_commits.csv", f"metric commit row {i} differs")
            need(committed["cycle"] < accepted["cycle"], "COMMIT_ACCEPT_ORDER", "capture/sample_commits.csv", f"row {i}: metric commit must precede public y acceptance")
            if 0 <= i-384 < ns:
                need(source[i-384]["cycle"] < committed["cycle"], "DELAYED_SOURCE_ORDER", "capture/sample_commits.csv", f"row {i}: delayed input not yet accepted")
        events = self.csv("capture", "lifecycle.csv", LIFECYCLE, 2, ("event",))
        start, done = events
        need(start["event"] == "start" and done["event"] == "done", "LIFECYCLE_EVENTS", "capture/lifecycle.csv", "exactly one start followed by one done required")
        need(start["source_count"] == start["output_count"] == 0 and done["source_count"] == done["output_count"] == ny,
             "LIFECYCLE_COUNTS", "capture/lifecycle.csv", "start/done counts differ")
        need(0 < start["cycle"] < min(source[0]["cycle"], accepts[0]["cycle"], commits[0]["cycle"]) and
             done["cycle"] > max(source[-1]["cycle"], accepts[-1]["cycle"], commits[-1]["cycle"]),
             "LIFECYCLE_ORDER", "capture/lifecycle.csv", "completion precedes final acceptance or activity precedes start")
        self.checks += ["source_handshake_sequence", "public_y_handshake_sequence", "metric_commit_sequence", "one_epoch_completion_order"]

        has_oracle_ifft = (self.roots["oracle"] / "ifft_output.csv").exists()
        has_capture_ifft = (self.roots["capture"] / "ifft_samples.csv").exists()
        residual: dict[str, Any] = {"status": "NOT_PROVIDED", "exact_complex_comparison": False}
        if has_oracle_ifft or has_capture_ifft:
            oracle_ifft = self.csv("oracle", "ifft_output.csv", IFFT, frames * 256)
            capture_ifft = self.csv("capture", "ifft_samples.csv", IFFT, frames * 256)
            self.match(capture_ifft, oracle_ifft, "capture/ifft_samples.csv")
            need([(r["frame_idx"], r["offset"]) for r in capture_ifft] == [(f, k) for f in range(frames) for k in range(256)],
                 "IFFT_INDEX", "capture/ifft_samples.csv", "frame/offset sequence differs")
            need(all(-(1 << 35) <= r[k] < (1 << 35) for r in capture_ifft for k in ("re", "im")),
                 "IFFT_WIDTH", "capture/ifft_samples.csv", "outside signed36")
            residual = {"status": "PASS", "exact_complex_comparison": True, "rows": frames * 256,
                        "nonzero_imag_rows": sum(r["im"] != 0 for r in capture_ifft),
                        "max_abs_imag": str(max(abs(r["im"]) for r in capture_ifft))}
            self.checks.append("exact_complex_ifft_including_legitimate_residuals")
        if "ifft_residual_summary" in observed:
            summary = observed["ifft_residual_summary"]
            need(residual["exact_complex_comparison"] and set(summary) == {"rows", "nonzero_imag_rows", "max_abs_imag"},
                 "IFFT_SUMMARY", "capture/metrics_observed.json", "summary without exact complex evidence or unknown fields")
            need(natural(summary["rows"], "capture/metrics_observed.json") == residual["rows"] and
                 natural(summary["nonzero_imag_rows"], "capture/metrics_observed.json") == residual["nonzero_imag_rows"] and
                 number(summary["max_abs_imag"], "capture/metrics_observed.json") == int(residual["max_abs_imag"]),
                 "IFFT_SUMMARY", "capture/metrics_observed.json", "residual summary differs from raw samples")
        for label, identity in self.identities.items():
            try:
                data = self.paths[label].read_bytes()
            except OSError as exc:
                raise CaptureError("INPUT_CHANGED", label, type(exc).__name__) from exc
            need(len(data) == identity["size_bytes"] and digest(data) == identity["sha256"],
                 "INPUT_CHANGED", label, "evidence changed during check")
        return {"vector_name": observed["vector_name"], "geometry": geometry, "counts": wanted_counts,
                "metrics": {k: str(v) for k, v in calculated.items()}, "ifft_residual": residual,
                "event_summary": {"source_rows": ny, "input_rows": ns, "analysis_flush_rows": tau-ns,
                                  "tail_drain_rows": 384, "sample_commit_rows": ny, "y_accept_rows": ny,
                                  "start_cycle": str(start["cycle"]), "done_cycle": str(done["cycle"]),
                                  "last_y_accept_cycle": str(accepts[-1]["cycle"]),
                                  "minimum_commit_to_accept_cycles": str(min(a["cycle"]-c["cycle"] for a, c in zip(accepts, commits)))}}


def check_capture(capture: Path, oracle: Path, x_path: Path) -> dict[str, Any]:
    """Return a result; never modify raw captures, oracle files or the input."""
    checker = Check(capture, oracle, x_path)
    report: dict[str, Any] = {"schema": "trecap_core_capture_check_v1", "outcome": "FAIL",
        "created_utc": datetime.now(timezone.utc).isoformat(), "python_version": platform.python_version(),
        "checker_sha256": digest(Path(__file__).read_bytes()), "oracle_qualification_established_here": False,
        "scope": "One finite replay epoch versus the supplied oracle; exact integer files and recorded ownership events",
        "limitations": ["Caller must qualify and pin oracle inputs and tool/run provenance separately.",
                        "Event files do not independently prove unrecorded idle cycles, stall stability or absence of transient X/Z.",
                        "No board, CDC, dynamic clear/control, malformed traffic, full-suite or energy signoff."]}
    try:
        report.update(checker.run())
        report["outcome"] = "PASS"
    except (CaptureError, KeyError, TypeError, ValueError, OSError, OverflowError) as exc:
        report["errors"] = [{"code": exc.code, "file": exc.file, "detail": exc.detail}] if isinstance(exc, CaptureError) else [
            {"code": "MALFORMED_EVIDENCE", "file": "", "detail": type(exc).__name__}]
    report["checks_completed"] = checker.checks
    report["input_identities"] = sorted(checker.identities.values(), key=lambda r: r["file"])
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--capture", type=Path, required=True)
    parser.add_argument("--oracle", type=Path, required=True)
    parser.add_argument("--x", type=Path, required=True, help="Input x_in.memh; qualified oracle must use <vector-name>/oracle layout")
    parser.add_argument("--output", type=Path, required=True, help="New report file; existing files are never overwritten")
    args = parser.parse_args()
    output = args.output.resolve()
    for raw_root in (args.capture.resolve(), args.oracle.resolve(), args.x.resolve().parent):
        if output == raw_root or raw_root in output.parents:
            parser.error("report must be outside raw capture, oracle and input directories")
    if output.exists():
        parser.error("report exists; use a new evidence path")
    result = check_capture(args.capture, args.oracle, args.x)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(result, stream, indent=2, sort_keys=True, ensure_ascii=True, allow_nan=False)
        stream.write("\n")
    print(json.dumps({"outcome": result["outcome"], "errors": result.get("errors", []),
                      "checks_completed": result["checks_completed"], "ifft_residual": result.get("ifft_residual")}, ensure_ascii=True))
    return 0 if result["outcome"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
