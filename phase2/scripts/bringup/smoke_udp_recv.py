#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""UDP telemetry smoke receiver for T-RECAP Phase 2.

File class: [1] hand-written bring-up utility.

The script listens for Revision G telemetry datagrams, validates each datagram
against the generated packet contract, optionally writes a portable binary
capture, and reports packet counts and sequence gaps. It is a PC-side bring-up
tool; it is not a dashboard and not a correctness signoff artifact.

Example:

  scripts/bringup/smoke_udp_recv.py --bind 0.0.0.0 --port 5005 \
    --seconds 10 --capture artifacts/telemetry_captures/status_only/packets.bin
"""
from __future__ import annotations

import argparse
import json
import socket
import struct
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from types import ModuleType
from typing import Any

CAPTURE_MAGIC = b"TRCPUDP1"
CAPTURE_RECORD_STRUCT = struct.Struct("<QHHI")  # recv_time_ns, src_port, addr_len, datagram_len
DEFAULT_PORT = 5005
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

    def parse_header(self, datagram: bytes) -> Header | None:
        if len(datagram) < int(self.gen.TELEMETRY_HEADER_BYTES):
            return None
        fields = self.header_struct.unpack_from(datagram, 0)
        return Header(*fields)

    def validate_datagram(self, datagram: bytes, *, ddr_record: bool = False) -> PacketValidation:
        errors: list[str] = []
        warnings: list[str] = []
        decoded: dict[str, Any] = {}
        header = self.parse_header(datagram)
        if header is None:
            return PacketValidation(False, "UNKNOWN", None, ["datagram shorter than telemetry header"])

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

        expected_wire_len = int(self.gen.TELEMETRY_HEADER_BYTES) + header.payload_bytes
        if not ddr_record and len(datagram) != expected_wire_len:
            errors.append(
                f"UDP datagram length {len(datagram)} != header+payload {expected_wire_len}"
            )
        if expected_wire_len > int(self.gen.UDP_NO_FRAGMENT_PAYLOAD_MAX_BYTES):
            errors.append(f"record exceeds UDP no-fragment bound: {expected_wire_len}")
        if len(datagram) < expected_wire_len:
            errors.append("truncated datagram/record")

        payload = datagram[int(self.gen.TELEMETRY_HEADER_BYTES) : expected_wire_len]
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
                errors.append(
                    f"{packet_name} payload_bytes {header.payload_bytes} != expected {expected}"
                )
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
                decoded.update(
                    {
                        "sample_base": sample_base,
                        "nsamp": nsamp,
                        "channels": channels,
                        "stride": stride,
                    }
                )
                if sample_base != header.timestamp:
                    errors.append("WAVE timestamp does not equal sample_base")
                if channels != 3:
                    errors.append(f"WAVE channels {channels} != 3")
                if nsamp < 1 or nsamp > int(self.payload_rules["WAVE"]["nsamp_max"]):
                    errors.append(f"WAVE nsamp {nsamp} outside legal range")
                if stride < 1:
                    errors.append("WAVE stride must be >= 1")
                if reserved != 0:
                    errors.append("WAVE reserved field is nonzero")
                if header.payload_bytes != 16 + 6 * nsamp:
                    errors.append("WAVE payload_bytes does not equal 16 + 6*nsamp")
            elif packet_name == "SPEC129":
                off = self.payload_offsets["SPEC129"]
                frame_idx = struct.unpack_from("<Q", payload, off["frame_idx"])[0]
                nbin = struct.unpack_from("<H", payload, off["nbin"])[0]
                spec_shift = struct.unpack_from("<H", payload, off["spec_shift"])[0]
                decoded.update({"frame_idx": frame_idx, "nbin": nbin, "spec_shift": spec_shift})
                if frame_idx != header.timestamp:
                    errors.append("SPEC129 timestamp does not equal frame_idx")
                if nbin != 129:
                    errors.append(f"SPEC129 nbin {nbin} != 129")
                last_mask_byte = payload[off["mask_bits"] + 16]
                if last_mask_byte & 0xFE:
                    errors.append("SPEC129 unused mask bits are nonzero")
            elif packet_name == "SPEC64":
                off = self.payload_offsets["SPEC64"]
                frame_idx = struct.unpack_from("<Q", payload, off["frame_idx"])[0]
                nbin = struct.unpack_from("<H", payload, off["nbin"])[0]
                spec_shift = struct.unpack_from("<H", payload, off["spec_shift"])[0]
                decoded.update({"frame_idx": frame_idx, "nbin": nbin, "spec_shift": spec_shift})
                if frame_idx != header.timestamp:
                    errors.append("SPEC64 timestamp does not equal frame_idx")
                if nbin != 64:
                    errors.append(f"SPEC64 nbin {nbin} != 64")
            elif packet_name == "METRICS":
                aggregate = bool(header.flags & self.agg_metrics_mask)
                per_frame = bool(header.flags & self.per_frame_metrics_mask)
                decoded.update({"aggregate_metrics": aggregate, "per_frame_metrics": per_frame})
                if aggregate == per_frame:
                    errors.append("METRICS requires exactly one of aggregate/per_frame flags")
                if header.flags & self.payload_scaled_mask:
                    errors.append("METRICS payload_scaled must be zero in Revision G")
            elif packet_name == "STATUS":
                off = self.payload_offsets["STATUS"]
                sample_count = struct.unpack_from("<Q", payload, off["sample_count"])[0]
                frame_count = struct.unpack_from("<Q", payload, off["frame_count"])[0]
                dma_drop = struct.unpack_from("<I", payload, off["dma_drop_count"])[0]
                packet_fifo_drop = struct.unpack_from(
                    "<I", payload, off["packet_fifo_drop_count"]
                )[0]
                reserved = struct.unpack_from("<I", payload, off["reserved"])[0]
                decoded.update(
                    {
                        "sample_count": sample_count,
                        "frame_count": frame_count,
                        "dma_drop_count": dma_drop,
                        "packet_fifo_drop_count": packet_fifo_drop,
                    }
                )
                if not (header.flags & self.status_diag_mask) and sample_count != header.timestamp:
                    errors.append("STATUS timestamp does not equal sample_count")
                if reserved != 0:
                    errors.append("STATUS reserved field is nonzero")
            elif packet_name == "WRAP":
                if not ddr_record:
                    errors.append("WRAP record was forwarded over UDP; Revision G says it is not forwarded")
        except struct.error as exc:
            errors.append(f"payload decode failed: {exc}")


class CaptureWriter:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.f = self.path.open("wb")
        self.f.write(CAPTURE_MAGIC)

    def write(self, recv_time_ns: int, addr: tuple[str, int], datagram: bytes) -> None:
        host, port = addr
        host_b = host.encode("ascii", errors="replace")
        self.f.write(CAPTURE_RECORD_STRUCT.pack(recv_time_ns, port, len(host_b), len(datagram)))
        self.f.write(host_b)
        self.f.write(datagram)

    def close(self) -> None:
        self.f.close()


@dataclass
class ReceiveSummary:
    ok: bool = True
    packets_total: int = 0
    packets_valid: int = 0
    packets_invalid: int = 0
    bytes_total: int = 0
    sequence_gap_events: int = 0
    sequence_missing_estimate: int = 0
    by_type: dict[str, int] = field(default_factory=dict)
    invalid_reasons: dict[str, int] = field(default_factory=dict)
    first_seq: int | None = None
    last_seq: int | None = None
    first_sender: str | None = None
    started_unix_s: float = 0.0
    ended_unix_s: float = 0.0

    def add_invalid_reason(self, reason: str) -> None:
        self.invalid_reasons[reason] = self.invalid_reasons.get(reason, 0) + 1


def update_sequence(summary: ReceiveSummary, seq: int) -> None:
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
        # Treat forward gaps less than half the sequence space as missing packets.
        if delta < 0x80000000:
            summary.sequence_missing_estimate += delta
    summary.last_seq = seq


def default_summary_out(repo_root: Path) -> Path:
    stamp = time.strftime("%Y%m%d_%H%M%S")
    return repo_root / RUNS_DIR / f"udp_recv_smoke_{stamp}.json"


def receive(args: argparse.Namespace, repo_root: Path, gen: ModuleType) -> ReceiveSummary:
    validator = TelemetryValidator(gen)
    summary = ReceiveSummary(started_unix_s=time.time())
    capture = CaptureWriter(Path(args.capture)) if args.capture else None

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind((args.bind, args.port))
        sock.settimeout(args.socket_timeout)
        deadline = None if args.seconds <= 0 else time.monotonic() + args.seconds
        print(f"listening on {args.bind}:{args.port}")
        while True:
            if args.count > 0 and summary.packets_total >= args.count:
                break
            if deadline is not None and time.monotonic() >= deadline:
                break
            try:
                datagram, addr = sock.recvfrom(args.max_datagram_bytes)
            except socket.timeout:
                continue
            except KeyboardInterrupt:
                print("interrupted")
                break

            recv_time_ns = time.time_ns()
            host, port = addr[0], int(addr[1])
            if summary.first_sender is None:
                summary.first_sender = f"{host}:{port}"
            if args.expected_source and host != args.expected_source:
                summary.packets_total += 1
                summary.packets_invalid += 1
                summary.add_invalid_reason(f"unexpected source {host}")
                continue

            summary.packets_total += 1
            summary.bytes_total += len(datagram)
            validation = validator.validate_datagram(datagram)
            summary.by_type[validation.packet_name] = summary.by_type.get(validation.packet_name, 0) + 1
            if validation.ok:
                summary.packets_valid += 1
                if validation.participates_in_sequence and validation.header is not None:
                    update_sequence(summary, validation.header.seq)
                if args.verbose:
                    hdr = validation.header
                    assert hdr is not None
                    print(
                        f"valid {validation.packet_name:<8} seq={hdr.seq:<10} "
                        f"ts={hdr.timestamp:<10} payload={hdr.payload_bytes:<4} from={host}:{port}"
                    )
            else:
                summary.packets_invalid += 1
                for reason in validation.errors:
                    summary.add_invalid_reason(reason)
                if args.verbose:
                    print(f"invalid from={host}:{port}: {validation.errors}")

            if capture:
                capture.write(recv_time_ns, (host, port), datagram)
    finally:
        summary.ended_unix_s = time.time()
        sock.close()
        if capture:
            capture.close()

    if summary.packets_valid == 0:
        summary.ok = False
    if summary.packets_invalid and not args.allow_invalid:
        summary.ok = False
    if args.require_status and summary.by_type.get("STATUS", 0) == 0:
        summary.ok = False
        summary.add_invalid_reason("required STATUS packet not observed")
    return summary


def summary_to_dict(summary: ReceiveSummary, args: argparse.Namespace) -> dict[str, Any]:
    return {
        "ok": summary.ok,
        "bind": args.bind,
        "port": args.port,
        "duration_s": round(summary.ended_unix_s - summary.started_unix_s, 6),
        "packets_total": summary.packets_total,
        "packets_valid": summary.packets_valid,
        "packets_invalid": summary.packets_invalid,
        "bytes_total": summary.bytes_total,
        "by_type": dict(sorted(summary.by_type.items())),
        "invalid_reasons": dict(sorted(summary.invalid_reasons.items())),
        "sequence_gap_events": summary.sequence_gap_events,
        "sequence_missing_estimate": summary.sequence_missing_estimate,
        "first_seq": summary.first_seq,
        "last_seq": summary.last_seq,
        "first_sender": summary.first_sender,
        "capture": args.capture,
    }


def print_summary(payload: dict[str, Any]) -> None:
    print("UDP smoke summary")
    print(f"  status: {'PASS' if payload['ok'] else 'FAIL'}")
    print(f"  packets: total={payload['packets_total']} valid={payload['packets_valid']} invalid={payload['packets_invalid']}")
    print(f"  by_type: {payload['by_type']}")
    print(f"  sequence_gap_events: {payload['sequence_gap_events']}")
    if payload["invalid_reasons"]:
        print("  invalid_reasons:")
        for reason, count in payload["invalid_reasons"].items():
            print(f"    {count:5d}  {reason}")
    if payload.get("capture"):
        print(f"  capture: {payload['capture']}")


def build_argparser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="T-RECAP UDP telemetry smoke receiver")
    ap.add_argument("--bind", default="0.0.0.0", help="UDP bind address")
    ap.add_argument("--port", type=int, default=DEFAULT_PORT, help="Telemetry UDP port")
    ap.add_argument("--count", type=int, default=10, help="Stop after N datagrams; 0 means no count limit")
    ap.add_argument("--seconds", type=float, default=10.0, help="Stop after seconds; 0 means no time limit")
    ap.add_argument("--socket-timeout", type=float, default=0.25, help="Receive timeout used for polling")
    ap.add_argument("--max-datagram-bytes", type=int, default=2048, help="Maximum UDP receive size")
    ap.add_argument("--expected-source", default=None, help="Only accept datagrams from this IP")
    ap.add_argument("--capture", default=None, help="Write framed binary capture file")
    ap.add_argument("--json-out", default=None, help="Write JSON summary; default runs/bringup/udp_recv_smoke_*.json")
    ap.add_argument("--no-json", action="store_true", help="Do not write JSON summary")
    ap.add_argument("--allow-invalid", action="store_true", help="Exit PASS even if invalid packets were seen")
    ap.add_argument("--require-status", action="store_true", help="Fail if no valid STATUS packet was observed")
    ap.add_argument("--verbose", action="store_true", help="Print one line per received packet")
    return ap


def main(argv: list[str] | None = None) -> int:
    repo_root = repo_root_from(Path(__file__).parent)
    gen = load_generated_packet(repo_root)
    args = build_argparser().parse_args(argv)
    if args.count <= 0 and args.seconds <= 0:
        print("ERROR: refusing infinite run without --count or --seconds", file=sys.stderr)
        return 2
    summary = receive(args, repo_root, gen)
    payload = summary_to_dict(summary, args)
    print_summary(payload)
    if not args.no_json:
        out = Path(args.json_out) if args.json_out else default_summary_out(repo_root)
        if not out.is_absolute():
            out = repo_root / out
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(f"  json_out: {out}")
    return 0 if summary.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
