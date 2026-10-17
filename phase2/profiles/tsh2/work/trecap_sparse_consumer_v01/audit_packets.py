"""Independent Python byte-level check of native C++ admission packet dumps."""
from __future__ import annotations
import argparse
import csv
import hashlib
import json
from pathlib import Path
import struct

MASK64 = (1 << 64) - 1


def fnv(data: bytes) -> int:
    value = 14695981039346656037
    for byte in data:
        value = ((value ^ byte) * 1099511628211) & MASK64
    return value


def record(frame: int, threshold: int, values: list[int], keep: list[bool], sparse: bool) -> bytes:
    if sparse:
        payload = b"".join(struct.pack("<Q", (v << 8) | k)
                           for k, v in enumerate(values) if keep[k])
        count = sum(keep)
    else:
        payload = b"".join((v if keep[k] else 0).to_bytes(7, "little")
                           for k, v in enumerate(values))
        count = 129
    header = struct.pack("<IHHIIQQHHI", 0x31505354, 1, int(sparse),
                         0x00010001, len(payload), frame, threshold, count, 1, 0)
    padding = b"\0" * (-(48 + len(payload)) % 8)
    return header + struct.pack("<Q", fnv(header + payload + padding)) + payload + padding


def features_from_record(packet: bytes, sparse: bool) -> list[int]:
    count = int.from_bytes(packet[32:34], "little")
    pairs = []
    if sparse:
        for i in range(count):
            word = int.from_bytes(packet[48 + 8*i:56 + 8*i], "little")
            pairs.append((word & 255, word >> 8))
    else:
        pairs = [(k, int.from_bytes(packet[48+7*k:55+7*k], "little")) for k in range(129)]
    out = [0] * 16
    for k, value in pairs:
        out[16*k//129] += value * (1 if k in (0, 128) else 2)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cases", type=Path, required=True)
    ap.add_argument("--packets", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    results = []
    for case in csv.DictReader(args.cases.open(encoding="utf-8-sig"), delimiter="\t"):
        grouped = {}
        for row in csv.DictReader(Path(case["bin_stats"]).open(encoding="utf-8-sig")):
            grouped.setdefault(int(row["frame_idx"]), []).append(row)
        expected = list(csv.DictReader(Path(case["expected_features"]).open(encoding="utf-8-sig")))
        assert len(expected) == len(grouped), case["case_id"]
        for sparse, label in ((False, "dense"), (True, "sparse")):
            file = args.packets / f"{case['case_id']}_{label}.bin"
            actual = file.read_bytes()
            offset = 0
            for frame, rows in sorted(grouped.items()):
                assert [int(r["bin_idx"]) for r in rows] == list(range(129))
                values = [int(r["mag2"]) for r in rows]
                assert all(0 <= v < 1 << 56 for v in values)
                keep = [not int(r["mask"]) for r in rows]
                assert keep[0]
                threshold = int(case["threshold"])
                assert all(keep[k] == (k == 0 or v >= threshold) for k, v in enumerate(values))
                gold = record(frame, threshold, values, keep, sparse)
                chunk = actual[offset:offset+len(gold)]
                assert chunk == gold, (case["case_id"], label, frame, "wire bytes")
                computed = features_from_record(chunk, sparse)
                oracle = [int(expected[frame][f"band{k}"]) for k in range(16)]
                assert computed == oracle, (case["case_id"], label, frame, "features")
                offset += len(gold)
            assert offset == len(actual), (case["case_id"], label, "extra data")
            results.append({"case_id": case["case_id"], "mode": label,
                            "frames": len(grouped), "bytes": len(actual),
                            "sha256": hashlib.sha256(actual).hexdigest()})
    report = {"all_pass": True, "scope": "Independent construction of every native admission packet byte and feature; timing repetitions not replayed here",
              "case_count": len(results)//2, "packet_count": sum(r["frames"] for r in results),
              "checked_bytes": sum(r["bytes"] for r in results), "files": results,
              "auditor_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2)+"\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "files"}))


if __name__ == "__main__":
    main()
