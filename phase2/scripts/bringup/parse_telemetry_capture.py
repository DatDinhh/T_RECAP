#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Offline parser for T-RECAP Phase 2 telemetry captures.

File class: [1] hand-written bring-up utility.

Supported input formats:
  - udp-framed: packets.bin written by smoke_udp_recv.py.
  - udp-raw-stream: one or more header+payload datagrams concatenated.
  - ddr-ring: a raw DDR ring dump with 64-byte-aligned records and WRAP records.

This parser validates headers and payload sizes using generated constants. It is
for transport bring-up and capture triage; it is not a core correctness signoff
checker.
"""
from __future__ import annotations

import argparse
import csv
import json
import struct
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from types import ModuleType
from typing import Any, Iterable

CAPTURE_MAGIC = b"TRCPUDP1"
CAPTURE_RECORD_STRUCT = struct.Struct("<QHHI")
RUNS_DIR = "runs/bringup"


def repo_root_from(path: Path) -> Path:
    candidates = [path.resolve(), *path.resolve().parents]
    for cand in candidates:
        if (cand / "spec/generated").is_dir() and (
            cand / "sw/pc_dashboard/generated/trecap_packet.py"
        ).is_file():
            return cand
    raise SystemExit("ERROR: could not find T_RECAP_Phase2 repo root")


def load_generated_packet(repo_root: Path) -> ModuleType:
    import importlib.util

    generated_path = repo_root / "sw/pc_dashboard/generated/trecap_packet.py"
    spec = importlib.util.spec_from_file_location("trecap_generated_packet", generated_path)
    if spec is None or spec.loader is None:
        raise SystemExit(f"ERROR: could not import generated constants: {generated_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def mask_from_bits(pair: tuple[int, int] | list[int]) -> int:
    lo, hi = int(pair[0]), int(pair[1])
    return ((1 << (hi - lo + 1)) - 1) << lo


def align_up(value: int, align: int) -> int:
    return (value + align - 1) & ~(align - 1)


def parse_int_auto(value: str | int | None) -> int | None:
    if value is None or isinstance(value, int):
        return value
    return int(value, 0)


@dataclass
class Header:
    magic: int
    version: int
    header_bytes: int
    packet_type: int
    flags: int
    seq: int
    timestamp: int
    payload_bytes: int
    header_crc: int


@dataclass
class PacketValidation:
    ok: bool
    packet_name: str
    header: Header | None
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    decoded: dict[str, Any] = field(default_factory=dict)
    participates_in_sequence: bool = False
    wire_len: int = 0
    ddr_len: int = 0


@dataclass
class ParsedRecord:
    index: int
    offset: int
    source: str
    packet_name: str
    ok: bool
    seq: int | None
    timestamp: int | None
    payload_bytes: int | None
    wire_len: int
    ddr_len: int
    errors: list[str]
    decoded: dict[str, Any] = field(default_factory=dict)
    recv_time_ns: int | None = None
    src_addr: str | None = None
    src_port: int | None = None


class TelemetryValidator:
    def __init__(self, gen: ModuleType) -> None:
        self.gen = gen
        self.header_struct = gen.TELEMETRY_HEADER_STRUCT
        self.packet_names = gen.PACKET_TYPE_NAMES
        self.packet_types = gen.PACKET_TYPES
        self.payload_rules = gen.PAYLOAD_RULES
        self.payload_offsets = gen.PAYLOAD_OFFSETS
        self.flags = gen.COMMON_FLAG_BITS
        self.flag_masks = {name: mask_from_bits(pair) for name, pair in self.flags.items()}
        self.reserved_flag_mask = self.flag_masks.get("reserved_15_6", 0xFFC0)
        self.crc_flag_mask = self.flag_masks.get("crc_enabled", 0x0010)
        self.status_diag_mask = self.flag_masks.get("status_diagnostic", 0x0020)
        self.payload_scaled_mask = self.flag_masks.get("payload_scaled", 0x0002)
        self.agg_metrics_mask = self.flag_masks.get("aggregate_metrics", 0x0004)
        self.per_frame_metrics_mask = self.flag_masks.get("per_frame_metrics", 0x0008)

    def parse_header(self, data: bytes) -> Header | None:
        if len(data) < int(self.gen.TELEMETRY_HEADER_BYTES):
            return None
        return Header(*self.header_struct.unpack_from(data, 0))

    def validate_record(
        self,
        data: bytes,
        *,
        ddr_record: bool = False,
        ddr_offset: int = 0,
        ring_size: int | None = None,
        check_padding: bool = False,
    ) -> PacketValidation:
        errors: list[str] = []
        warnings: list[str] = []
        decoded: dict[str, Any] = {}
        header = self.parse_header(data)
        if header is None:
            return PacketValidation(False, "UNKNOWN", None, ["record shorter than header"])

        packet_name = self.packet_names.get(header.packet_type, "UNKNOWN")
        if header.magic != int(self.gen.TELEMETRY_MAGIC):
            errors.append(f"bad magic 0x{header.magic:08x}")
        if header.version != int(self.gen.TELEMETRY_HEADER_VERSION):
            errors.append(f"unsupported header version {header.version}")
        if header.header_bytes != int(self.gen.TELEMETRY_HEADER_BYTES):
            errors.append(f"bad header_bytes {header.header_bytes}")
        if packet_name == "UNKNOWN":
            errors.append(f"unknown packet type 0x{header.packet_type:04x}")
        if header.flags & self.reserved_flag_mask:
            errors.append(f"reserved flags set 0x{header.flags & self.reserved_flag_mask:04x}")
        if header.flags & self.crc_flag_mask:
            errors.append("crc_enabled flag set in Revision G")
        if header.header_crc != 0:
            errors.append(f"nonzero header_crc 0x{header.header_crc:08x}")

        status_diag = bool(header.flags & self.status_diag_mask)
        if status_diag and packet_name != "STATUS":
            errors.append("status_diagnostic flag set on non-STATUS packet")

        wire_len = int(self.gen.TELEMETRY_HEADER_BYTES) + header.payload_bytes
        if wire_len > int(self.gen.UDP_NO_FRAGMENT_PAYLOAD_MAX_BYTES):
            errors.append(f"record exceeds UDP no-fragment bound: {wire_len}")
        if len(data) < wire_len:
            errors.append(f"truncated record: have {len(data)}, need {wire_len}")

        ddr_len = align_up(wire_len, int(self.gen.DDR_RECORD_ALIGNMENT_BYTES))
        if packet_name == "WRAP" and ddr_record:
            if ring_size is None:
                errors.append("WRAP in DDR capture requires --ring-size")
            else:
                off = ddr_offset & (ring_size - 1)
                ddr_len = ring_size - off if off != 0 else ring_size
        elif packet_name == "WRAP" and not ddr_record:
            errors.append("WRAP appears in UDP capture; WRAP is a DDR ring-control record")

        if ddr_record and packet_name != "WRAP" and check_padding and len(data) >= ddr_len:
            padding = data[wire_len:ddr_len]
            if any(padding):
                errors.append("DDR record padding is nonzero")

        payload = data[int(self.gen.TELEMETRY_HEADER_BYTES) : wire_len]
        if packet_name != "UNKNOWN":
            self._validate_payload(packet_name, header, payload, errors, warnings, decoded, ddr_record)

        participates = packet_name not in {"WRAP", "UNKNOWN"} and not (
            packet_name == "STATUS" and status_diag
        )
        return PacketValidation(
            ok=not errors,
            packet_name=packet_name,
            header=header,
            errors=errors,
            warnings=warnings,
            decoded=decoded,
            participates_in_sequence=participates,
            wire_len=wire_len,
            ddr_len=ddr_len,
        )

    def _validate_payload(
        self,
        packet_name: str,
        header: Header,
        payload: bytes,
        errors: list[str],
        warnings: list[str],
        decoded: dict[str, Any],
        ddr_record: bool,
    ) -> None:
        rule = self.payload_rules.get(packet_name, {"kind": "undefined"})
        kind = rule.get("kind")
        if kind == "exact":
            expected = int(rule.get("bytes", -1))
            if header.payload_bytes != expected:
                errors.append(f"{packet_name} payload_bytes {header.payload_bytes} != {expected}")
        elif kind == "variable" and packet_name == "WAVE":
            if header.payload_bytes < int(rule["min_bytes"]) or header.payload_bytes > int(rule["max_bytes"]):
                errors.append(f"WAVE payload_bytes {header.payload_bytes} outside legal range")
        elif kind == "undefined_in_revision_g":
            errors.append(f"{packet_name} is reserved-disabled in Revision G")
        else:
            errors.append(f"{packet_name} has unsupported payload rule {kind}")

        if len(payload) < header.payload_bytes:
            return
        try:
            if packet_name == "WAVE":
                off = self.payload_offsets["WAVE"]
                sample_base = struct.unpack_from("<Q", payload, off["sample_base"])[0]
                nsamp = struct.unpack_from("<H", payload, off["nsamp"])[0]
                channels = struct.unpack_from("<H", payload, off["channels"])[0]
                stride = struct.unpack_from("<H", payload, off["stride"])[0]
                reserved = struct.unpack_from("<H", payload, off["reserved"])[0]
                decoded.update({"sample_base": sample_base, "nsamp": nsamp, "channels": channels, "stride": stride})
                if sample_base != header.timestamp:
                    errors.append("WAVE timestamp != sample_base")
                if channels != 3:
                    errors.append(f"WAVE channels {channels} != 3")
                if nsamp < 1 or nsamp > int(self.payload_rules["WAVE"]["nsamp_max"]):
                    errors.append(f"WAVE nsamp {nsamp} outside legal range")
                if stride < 1:
                    errors.append("WAVE stride must be >= 1")
                if reserved != 0:
                    errors.append("WAVE reserved field nonzero")
                if header.payload_bytes != 16 + 6 * nsamp:
                    errors.append("WAVE payload size expression mismatch")
            elif packet_name == "SPEC129":
                off = self.payload_offsets["SPEC129"]
                frame_idx = struct.unpack_from("<Q", payload, off["frame_idx"])[0]
                nbin = struct.unpack_from("<H", payload, off["nbin"])[0]
                spec_shift = struct.unpack_from("<H", payload, off["spec_shift"])[0]
                decoded.update({"frame_idx": frame_idx, "nbin": nbin, "spec_shift": spec_shift})
                if frame_idx != header.timestamp:
                    errors.append("SPEC129 timestamp != frame_idx")
                if nbin != 129:
                    errors.append(f"SPEC129 nbin {nbin} != 129")
                if payload[self.payload_offsets["SPEC129"]["mask_bits"] + 16] & 0xFE:
                    errors.append("SPEC129 unused mask bits nonzero")
            elif packet_name == "SPEC64":
                off = self.payload_offsets["SPEC64"]
                frame_idx = struct.unpack_from("<Q", payload, off["frame_idx"])[0]
                nbin = struct.unpack_from("<H", payload, off["nbin"])[0]
                spec_shift = struct.unpack_from("<H", payload, off["spec_shift"])[0]
                decoded.update({"frame_idx": frame_idx, "nbin": nbin, "spec_shift": spec_shift})
                if frame_idx != header.timestamp:
                    errors.append("SPEC64 timestamp != frame_idx")
                if nbin != 64:
                    errors.append(f"SPEC64 nbin {nbin} != 64")
            elif packet_name == "METRICS":
                aggregate = bool(header.flags & self.agg_metrics_mask)
                per_frame = bool(header.flags & self.per_frame_metrics_mask)
                decoded.update({"aggregate_metrics": aggregate, "per_frame_metrics": per_frame})
                if aggregate == per_frame:
                    errors.append("METRICS requires exactly one aggregate/per_frame flag")
                if header.flags & self.payload_scaled_mask:
                    errors.append("METRICS payload_scaled must be zero")
            elif packet_name == "STATUS":
                off = self.payload_offsets["STATUS"]
                sample_count = struct.unpack_from("<Q", payload, off["sample_count"])[0]
                frame_count = struct.unpack_from("<Q", payload, off["frame_count"])[0]
                source_mode = struct.unpack_from("<I", payload, off["source_mode"])[0]
                packet_enable = struct.unpack_from("<I", payload, off["packet_enable"])[0]
                dma_drop = struct.unpack_from("<I", payload, off["dma_drop_count"])[0]
                packet_fifo_drop = struct.unpack_from("<I", payload, off["packet_fifo_drop_count"])[0]
                reserved = struct.unpack_from("<I", payload, off["reserved"])[0]
                decoded.update(
                    {
                        "sample_count": sample_count,
                        "frame_count": frame_count,
                        "source_mode": source_mode,
                        "packet_enable": packet_enable,
                        "dma_drop_count": dma_drop,
                        "packet_fifo_drop_count": packet_fifo_drop,
                    }
                )
                if not (header.flags & self.status_diag_mask) and sample_count != header.timestamp:
                    errors.append("STATUS timestamp != sample_count")
                if reserved != 0:
                    errors.append("STATUS reserved field nonzero")
            elif packet_name == "WRAP":
                if header.payload_bytes != 0:
                    errors.append("WRAP payload_bytes must be zero")
        except (struct.error, IndexError) as exc:
            errors.append(f"payload decode failed: {exc}")


@dataclass
class ParseSummary:
    ok: bool = True
    input: str = ""
    format: str = ""
    records_total: int = 0
    records_valid: int = 0
    records_invalid: int = 0
    bytes_total: int = 0
    by_type: dict[str, int] = field(default_factory=dict)
    invalid_reasons: dict[str, int] = field(default_factory=dict)
    sequence_gap_events: int = 0
    sequence_missing_estimate: int = 0
    first_seq: int | None = None
    last_seq: int | None = None

    def add_reason(self, reason: str) -> None:
        self.invalid_reasons[reason] = self.invalid_reasons.get(reason, 0) + 1


def update_sequence(summary: ParseSummary, seq: int) -> None:
    seq &= 0xFFFFFFFF
    if summary.first_seq is None:
        summary.first_seq = seq
        summary.last_seq = seq
        return
    assert summary.last_seq is not None
    expected = (summary.last_seq + 1) & 0xFFFFFFFF
    if seq != expected:
        delta = (seq - expected) & 0xFFFFFFFF
        summary.sequence_gap_events += 1
        if delta < 0x80000000:
            summary.sequence_missing_estimate += delta
    summary.last_seq = seq


def detect_format(data: bytes, args: argparse.Namespace, gen: ModuleType) -> str:
    if args.format != "auto":
        return args.format
    if data.startswith(CAPTURE_MAGIC):
        return "udp-framed"
    if len(data) >= int(gen.TELEMETRY_HEADER_BYTES):
        magic = struct.unpack_from("<I", data, 0)[0]
        if magic == int(gen.TELEMETRY_MAGIC):
            return "ddr-ring" if args.ring_size else "udp-raw-stream"
    raise SystemExit("ERROR: could not auto-detect capture format; pass --format explicitly")


def record_from_validation(
    index: int,
    offset: int,
    source: str,
    validation: PacketValidation,
    recv_time_ns: int | None = None,
    src_addr: str | None = None,
    src_port: int | None = None,
) -> ParsedRecord:
    hdr = validation.header
    return ParsedRecord(
        index=index,
        offset=offset,
        source=source,
        packet_name=validation.packet_name,
        ok=validation.ok,
        seq=None if hdr is None else hdr.seq,
        timestamp=None if hdr is None else hdr.timestamp,
        payload_bytes=None if hdr is None else hdr.payload_bytes,
        wire_len=validation.wire_len,
        ddr_len=validation.ddr_len,
        errors=validation.errors,
        decoded=validation.decoded,
        recv_time_ns=recv_time_ns,
        src_addr=src_addr,
        src_port=src_port,
    )


def parse_udp_framed(data: bytes, validator: TelemetryValidator, max_records: int) -> Iterable[ParsedRecord]:
    pos = len(CAPTURE_MAGIC)
    idx = 0
    while pos < len(data):
        if max_records and idx >= max_records:
            break
        if pos + CAPTURE_RECORD_STRUCT.size > len(data):
            dummy = PacketValidation(False, "UNKNOWN", None, ["truncated capture record header"])
            yield record_from_validation(idx, pos, "udp-framed", dummy)
            break
        recv_time_ns, src_port, addr_len, datagram_len = CAPTURE_RECORD_STRUCT.unpack_from(data, pos)
        rec_off = pos
        pos += CAPTURE_RECORD_STRUCT.size
        if pos + addr_len + datagram_len > len(data):
            dummy = PacketValidation(False, "UNKNOWN", None, ["truncated capture record body"])
            yield record_from_validation(idx, rec_off, "udp-framed", dummy, recv_time_ns)
            break
        addr = data[pos : pos + addr_len].decode("ascii", errors="replace")
        pos += addr_len
        datagram = data[pos : pos + datagram_len]
        pos += datagram_len
        validation = validator.validate_record(datagram, ddr_record=False)
        yield record_from_validation(idx, rec_off, "udp-framed", validation, recv_time_ns, addr, src_port)
        idx += 1


def parse_udp_raw_stream(data: bytes, validator: TelemetryValidator, gen: ModuleType, max_records: int) -> Iterable[ParsedRecord]:
    pos = 0
    idx = 0
    while pos < len(data):
        if max_records and idx >= max_records:
            break
        if len(data) - pos < int(gen.TELEMETRY_HEADER_BYTES):
            dummy = PacketValidation(False, "UNKNOWN", None, ["trailing bytes shorter than header"])
            yield record_from_validation(idx, pos, "udp-raw-stream", dummy)
            break
        header = validator.parse_header(data[pos:])
        if header is None:
            dummy = PacketValidation(False, "UNKNOWN", None, ["could not parse header"])
            yield record_from_validation(idx, pos, "udp-raw-stream", dummy)
            break
        wire_len = int(gen.TELEMETRY_HEADER_BYTES) + header.payload_bytes
        chunk = data[pos : pos + wire_len]
        validation = validator.validate_record(chunk, ddr_record=False)
        yield record_from_validation(idx, pos, "udp-raw-stream", validation)
        pos += max(wire_len, int(gen.TELEMETRY_HEADER_BYTES))
        idx += 1


def parse_ddr_ring(data: bytes, validator: TelemetryValidator, gen: ModuleType, args: argparse.Namespace) -> Iterable[ParsedRecord]:
    ring_size = parse_int_auto(args.ring_size)
    if ring_size is None:
        raise SystemExit("ERROR: --ring-size is required for --format ddr-ring")
    if ring_size <= 0 or (ring_size & (ring_size - 1)) != 0:
        raise SystemExit("ERROR: --ring-size must be a positive power of two")
    pos = parse_int_auto(args.start_offset) or 0
    idx = 0
    while pos < len(data):
        if args.max_records and idx >= args.max_records:
            break
        if len(data) - pos < int(gen.TELEMETRY_HEADER_BYTES):
            break
        if all(b == 0 for b in data[pos : min(len(data), pos + int(gen.TELEMETRY_HEADER_BYTES))]):
            # Unused ring tail or uncommitted space. Stop instead of byte-scanning.
            break
        validation = validator.validate_record(
            data[pos:],
            ddr_record=True,
            ddr_offset=pos,
            ring_size=ring_size,
            check_padding=args.check_padding,
        )
        yield record_from_validation(idx, pos, "ddr-ring", validation)
        step = validation.ddr_len or int(gen.TELEMETRY_HEADER_BYTES)
        if step <= 0:
            step = int(gen.TELEMETRY_HEADER_BYTES)
        pos += step
        idx += 1


def update_summary(summary: ParseSummary, record: ParsedRecord, validation_participates: bool) -> None:
    summary.records_total += 1
    summary.by_type[record.packet_name] = summary.by_type.get(record.packet_name, 0) + 1
    if record.ok:
        summary.records_valid += 1
        if validation_participates and record.seq is not None:
            update_sequence(summary, record.seq)
    else:
        summary.records_invalid += 1
        for reason in record.errors:
            summary.add_reason(reason)


def parse_records(data: bytes, fmt: str, validator: TelemetryValidator, gen: ModuleType, args: argparse.Namespace) -> tuple[ParseSummary, list[ParsedRecord]]:
    summary = ParseSummary(input=str(args.input), format=fmt, bytes_total=len(data))
    records: list[ParsedRecord] = []
    if fmt == "udp-framed":
        iterator = parse_udp_framed(data, validator, args.max_records)
    elif fmt == "udp-raw-stream":
        iterator = parse_udp_raw_stream(data, validator, gen, args.max_records)
    elif fmt == "ddr-ring":
        iterator = parse_ddr_ring(data, validator, gen, args)
    else:
        raise SystemExit(f"ERROR: unsupported format: {fmt}")

    # Re-validate for participates flag. This avoids storing validator internals in ParsedRecord.
    for record in iterator:
        records.append(record)
        participates = False
        if record.seq is not None and record.packet_name not in {"WRAP", "UNKNOWN"}:
            # Diagnostic STATUS has seq ignored. Detect from decoded/flags by re-reading header.
            participates = True
        update_summary(summary, record, participates)

    if summary.records_invalid and args.strict:
        summary.ok = False
    if summary.records_valid == 0:
        summary.ok = False
    return summary, records


def write_jsonl(path: Path, records: list[ParsedRecord]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r.__dict__, sort_keys=True) + "\n")


def write_csv(path: Path, records: list[ParsedRecord]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "index",
                "offset",
                "source",
                "packet_name",
                "ok",
                "seq",
                "timestamp",
                "payload_bytes",
                "wire_len",
                "ddr_len",
                "errors",
                "src_addr",
                "src_port",
            ],
        )
        writer.writeheader()
        for r in records:
            writer.writerow(
                {
                    "index": r.index,
                    "offset": r.offset,
                    "source": r.source,
                    "packet_name": r.packet_name,
                    "ok": r.ok,
                    "seq": r.seq,
                    "timestamp": r.timestamp,
                    "payload_bytes": r.payload_bytes,
                    "wire_len": r.wire_len,
                    "ddr_len": r.ddr_len,
                    "errors": "; ".join(r.errors),
                    "src_addr": r.src_addr,
                    "src_port": r.src_port,
                }
            )


def summary_to_dict(summary: ParseSummary) -> dict[str, Any]:
    return {
        "ok": summary.ok,
        "input": summary.input,
        "format": summary.format,
        "records_total": summary.records_total,
        "records_valid": summary.records_valid,
        "records_invalid": summary.records_invalid,
        "bytes_total": summary.bytes_total,
        "by_type": dict(sorted(summary.by_type.items())),
        "invalid_reasons": dict(sorted(summary.invalid_reasons.items())),
        "sequence_gap_events": summary.sequence_gap_events,
        "sequence_missing_estimate": summary.sequence_missing_estimate,
        "first_seq": summary.first_seq,
        "last_seq": summary.last_seq,
    }


def default_summary_out(repo_root: Path) -> Path:
    stamp = time.strftime("%Y%m%d_%H%M%S")
    return repo_root / RUNS_DIR / f"telemetry_capture_parse_{stamp}.json"


def print_summary(payload: dict[str, Any]) -> None:
    print("Telemetry capture parse summary")
    print(f"  status: {'PASS' if payload['ok'] else 'FAIL'}")
    print(f"  input: {payload['input']}")
    print(f"  format: {payload['format']}")
    print(f"  records: total={payload['records_total']} valid={payload['records_valid']} invalid={payload['records_invalid']}")
    print(f"  by_type: {payload['by_type']}")
    print(f"  sequence_gap_events: {payload['sequence_gap_events']}")
    if payload["invalid_reasons"]:
        print("  invalid_reasons:")
        for reason, count in payload["invalid_reasons"].items():
            print(f"    {count:5d}  {reason}")


def build_argparser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="Parse and validate T-RECAP telemetry captures")
    ap.add_argument("--input", required=True, help="Capture file path")
    ap.add_argument("--format", choices=["auto", "udp-framed", "udp-raw-stream", "ddr-ring"], default="auto")
    ap.add_argument("--ring-size", default=None, help="Ring size in bytes for DDR ring captures")
    ap.add_argument("--start-offset", default="0", help="Start offset for DDR ring parsing")
    ap.add_argument("--max-records", type=int, default=0, help="Maximum records to parse; 0 = all")
    ap.add_argument("--check-padding", action="store_true", help="Validate DDR 64-byte padding is zero")
    ap.add_argument("--strict", action="store_true", help="Exit fail if any invalid records are found")
    ap.add_argument("--json-out", default=None, help="Write summary JSON; default runs/bringup/telemetry_capture_parse_*.json")
    ap.add_argument("--jsonl-out", default=None, help="Write one decoded record per JSONL line")
    ap.add_argument("--csv-out", default=None, help="Write flat record CSV")
    ap.add_argument("--no-json", action="store_true", help="Do not write summary JSON")
    return ap


def main(argv: list[str] | None = None) -> int:
    repo_root = repo_root_from(Path(__file__).parent)
    gen = load_generated_packet(repo_root)
    args = build_argparser().parse_args(argv)
    input_path = Path(args.input)
    if not input_path.is_absolute():
        input_path = repo_root / input_path
    if not input_path.exists():
        print(f"ERROR: input capture not found: {input_path}", file=sys.stderr)
        return 2
    data = input_path.read_bytes()
    args.input = str(input_path)
    fmt = detect_format(data, args, gen)
    validator = TelemetryValidator(gen)
    summary, records = parse_records(data, fmt, validator, gen, args)
    payload = summary_to_dict(summary)
    print_summary(payload)

    if not args.no_json:
        out = Path(args.json_out) if args.json_out else default_summary_out(repo_root)
        if not out.is_absolute():
            out = repo_root / out
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(f"  json_out: {out}")
    if args.jsonl_out:
        out = Path(args.jsonl_out)
        if not out.is_absolute():
            out = repo_root / out
        write_jsonl(out, records)
        print(f"  jsonl_out: {out}")
    if args.csv_out:
        out = Path(args.csv_out)
        if not out.is_absolute():
            out = repo_root / out
        write_csv(out, records)
        print(f"  csv_out: {out}")
    return 0 if summary.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
