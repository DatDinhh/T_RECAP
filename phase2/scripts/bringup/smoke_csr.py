#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Smoke-test the T-RECAP Phase 2 HPS-to-FPGA CSR bridge.

File class: [1] hand-written bring-up utility.

The default behavior is read-only: read ID, VERSION, status, packet-enable, and
transport counters using generated CSR offsets. Optional flags can pulse snapshot
registers or perform reversible write/readback checks on noncritical controls.
This tool never enables telemetry, changes source mode, or changes THR2 unless a
future explicit option is added.
"""
from __future__ import annotations

import argparse
import dataclasses
import importlib.util
import json
import mmap
import struct
import sys
import time
from pathlib import Path
from types import ModuleType
from typing import Any, Mapping, Protocol, Sequence

DEFAULT_GENERATED_PACKET = Path("sw/pc_dashboard/generated/trecap_packet.py")
DEFAULT_HPS_CONFIG = Path("sw/hps/config/trecap_hps_config.json")


def repo_root_from(path: Path) -> Path:
    p = path.resolve()
    if p.is_file():
        p = p.parent
    for cand in (p, *p.parents):
        if (cand / DEFAULT_GENERATED_PACKET).is_file():
            return cand
    raise RuntimeError("could not find T_RECAP_Phase2 repo root")


def parse_int(value: Any, default: int | None = None) -> int:
    if value is None:
        if default is None:
            raise ValueError("missing integer value")
        return default
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        return int(value.replace("_", ""), 0)
    raise TypeError(f"unsupported integer value: {value!r}")


def load_generated_packet(root: Path, override: Path | None) -> ModuleType:
    path = override or (root / DEFAULT_GENERATED_PACKET)
    if not path.is_file():
        raise FileNotFoundError(f"generated constants missing: {path}; run make gen-headers")
    spec = importlib.util.spec_from_file_location("trecap_generated_packet_for_csr", str(path))
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not import generated constants: {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def load_config(path: Path) -> dict[str, Any]:
    if not path.exists() or path.name == ".gitkeep":
        return {}
    text = path.read_text(encoding="utf-8").strip()
    return json.loads(text) if text else {}


class Mmio(Protocol):
    def read32(self, offset: int) -> int: ...
    def write32(self, offset: int, value: int) -> None: ...
    def close(self) -> None: ...


class DevMemMmio:
    def __init__(self, devmem: Path, base_phys: int, span: int) -> None:
        self.devmem = devmem
        self.base_phys = base_phys
        self.span = span
        page = mmap.PAGESIZE
        self.page_base = base_phys & ~(page - 1)
        self.page_off = base_phys - self.page_base
        self.map_len = self.page_off + span
        self.fd = devmem.open("r+b", buffering=0)
        self.mm = mmap.mmap(self.fd.fileno(), self.map_len, flags=mmap.MAP_SHARED, prot=mmap.PROT_READ | mmap.PROT_WRITE, offset=self.page_base)

    def read32(self, offset: int) -> int:
        return struct.unpack_from("<I", self.mm, self.page_off + offset)[0]

    def write32(self, offset: int, value: int) -> None:
        struct.pack_into("<I", self.mm, self.page_off + offset, value & 0xFFFFFFFF)
        self.mm.flush()

    def close(self) -> None:
        self.mm.close()
        self.fd.close()


class FileMmio:
    def __init__(self, path: Path, span: int, *, init_expected: "CsrConstants | None") -> None:
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            path.write_bytes(b"\x00" * span)
        elif path.stat().st_size < span:
            with path.open("ab") as f:
                f.write(b"\x00" * (span - path.stat().st_size))
        self.fd = path.open("r+b", buffering=0)
        self.mm = mmap.mmap(self.fd.fileno(), span)
        if init_expected:
            self.write32(init_expected.offsets["ID"], init_expected.id_value)
            self.write32(init_expected.offsets["VERSION"], init_expected.version_value)
            self.write32(init_expected.offsets["WAVE_DECIM"], 1)

    def read32(self, offset: int) -> int:
        return struct.unpack_from("<I", self.mm, offset)[0]

    def write32(self, offset: int, value: int) -> None:
        struct.pack_into("<I", self.mm, offset, value & 0xFFFFFFFF)
        self.mm.flush()

    def close(self) -> None:
        self.mm.close()
        self.fd.close()


@dataclasses.dataclass(frozen=True)
class CsrConstants:
    id_value: int
    version_major: int
    version_minor: int
    version_value: int
    offsets: dict[str, int]
    bits: dict[str, dict[str, tuple[int, int]]]


@dataclasses.dataclass
class Result:
    ok: bool = True
    backend: str = ""
    csr_base_phys: str = ""
    csr_span_bytes: int = 0
    registers: dict[str, str] = dataclasses.field(default_factory=dict)
    decoded: dict[str, Any] = dataclasses.field(default_factory=dict)
    warnings: list[str] = dataclasses.field(default_factory=list)
    errors: list[str] = dataclasses.field(default_factory=list)


def constants_from_module(mod: ModuleType) -> CsrConstants:
    major = int(mod.TRANSPORT_VERSION_MAJOR)
    minor = int(mod.TRANSPORT_VERSION_MINOR)
    return CsrConstants(
        id_value=int(mod.TELEMETRY_MAGIC),
        version_major=major,
        version_minor=minor,
        version_value=(major << 16) | minor,
        offsets={str(k): int(v) for k, v in dict(mod.CSR_OFFSETS).items()},
        bits={str(r): {str(k): tuple(v) for k, v in dict(fields).items()} for r, fields in dict(mod.CSR_BITS).items()},
    )


def mask_range(pair: tuple[int, int]) -> int:
    lo, hi = int(pair[0]), int(pair[1])
    return ((1 << (hi - lo + 1)) - 1) << lo


def decode_bits(value: int, fields: Mapping[str, tuple[int, int]]) -> dict[str, int]:
    decoded: dict[str, int] = {}
    for name, pair in fields.items():
        lo, _hi = int(pair[0]), int(pair[1])
        decoded[name] = (value & mask_range(pair)) >> lo
    return decoded


def read_reg(mmio: Mmio, const: CsrConstants, name: str, result: Result) -> int:
    value = mmio.read32(const.offsets[name])
    result.registers[name] = f"0x{value:08x}"
    return value


def write_reg(mmio: Mmio, const: CsrConstants, name: str, value: int, result: Result) -> None:
    mmio.write32(const.offsets[name], value)
    result.registers[f"write_{name}"] = f"0x{value & 0xFFFFFFFF:08x}"


def read_u64(mmio: Mmio, const: CsrConstants, lo_name: str, hi_name: str, result: Result, label: str) -> int:
    lo = read_reg(mmio, const, lo_name, result)
    hi = read_reg(mmio, const, hi_name, result)
    value = lo | (hi << 32)
    result.decoded[label] = value
    return value


def perform_smoke(mmio: Mmio, const: CsrConstants, result: Result, *, snapshot: bool, exercise_safe_writes: bool, clear_sticky_mask: int | None) -> None:
    id_value = read_reg(mmio, const, "ID", result)
    version = read_reg(mmio, const, "VERSION", result)
    major, minor = (version >> 16) & 0xFFFF, version & 0xFFFF
    result.decoded["version_major"] = major
    result.decoded["version_minor"] = minor
    if id_value != const.id_value:
        result.errors.append(f"ID mismatch: got 0x{id_value:08x}, expected 0x{const.id_value:08x}")
    if major != const.version_major:
        result.errors.append(f"VERSION major mismatch: got {major}, expected {const.version_major}")
    if minor != const.version_minor:
        result.warnings.append(f"VERSION minor mismatch: got {minor}, expected {const.version_minor}")

    for name in [
        "CONTROL", "STATUS", "PACKET_ENABLE", "WAVE_DECIM", "SPEC_MODE", "SPEC_SHIFT",
        "DMA_DROP_COUNT", "DMA_PACKET_COUNT", "DMA_STATUS", "OVERFLOW_FLAGS",
        "CSR_COMMAND_REJECT_COUNT", "PACKET_FIFO_DROP_COUNT",
    ]:
        read_reg(mmio, const, name, result)

    for name in ["STATUS", "DMA_STATUS", "OVERFLOW_FLAGS"]:
        value = int(result.registers[name], 16)
        result.decoded[f"{name}_bits"] = decode_bits(value, const.bits.get(name, {}))
    if int(result.registers["OVERFLOW_FLAGS"], 16) != 0:
        result.warnings.append(f"OVERFLOW_FLAGS nonzero: {result.registers['OVERFLOW_FLAGS']}")

    if snapshot:
        write_reg(mmio, const, "RING_WR_SNAPSHOT", 1, result)
        time.sleep(0.001)
        read_u64(mmio, const, "RING_WR_LO_SNAP", "RING_WR_HI_SNAP", result, "ring_wr_snapshot")
        write_reg(mmio, const, "CORE_COUNT_SNAPSHOT", 1, result)
        time.sleep(0.001)
        read_u64(mmio, const, "FRAME_COUNT_SNAP_LO", "FRAME_COUNT_SNAP_HI", result, "frame_count_snapshot")
        read_u64(mmio, const, "SAMPLE_COUNT_SNAP_LO", "SAMPLE_COUNT_SNAP_HI", result, "sample_count_snapshot")

    if exercise_safe_writes:
        for name in ["WAVE_DECIM", "SPEC_SHIFT"]:
            value = read_reg(mmio, const, name, result)
            write_reg(mmio, const, name, value, result)
            after = read_reg(mmio, const, name, result)
            if after != value:
                result.errors.append(f"{name} write/readback mismatch: wrote 0x{value:08x}, read 0x{after:08x}")

    if clear_sticky_mask is not None:
        write_reg(mmio, const, "CLEAR_STICKY_FLAGS", clear_sticky_mask, result)
        time.sleep(0.001)
        read_reg(mmio, const, "OVERFLOW_FLAGS", result)

    result.ok = not result.errors


def result_dict(result: Result) -> dict[str, Any]:
    return dataclasses.asdict(result)


def build_argparser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="Smoke-test T-RECAP HPS-to-FPGA CSR access")
    ap.add_argument("--root", type=Path, default=None, help="Repository root. Default inferred.")
    ap.add_argument("--generated-packet", type=Path, default=None, help="Override generated trecap_packet.py path")
    ap.add_argument("--config", type=Path, default=None, help="HPS runtime config JSON")
    ap.add_argument("--csr-base-phys", type=lambda s: int(s, 0), default=None, help="CSR physical base for /dev/mem")
    ap.add_argument("--csr-span", type=lambda s: int(s, 0), default=None, help="CSR span bytes; default config or 4096")
    ap.add_argument("--devmem", type=Path, default=Path("/dev/mem"), help="Device memory path")
    ap.add_argument("--mock-mmio", type=Path, default=None, help="Use a regular file as mock MMIO")
    ap.add_argument("--init-mock", action="store_true", help="Initialize mock with expected ID/VERSION")
    ap.add_argument("--snapshot", action="store_true", help="Pulse RING_WR_SNAPSHOT and CORE_COUNT_SNAPSHOT")
    ap.add_argument("--exercise-safe-writes", action="store_true", help="Write current WAVE_DECIM/SPEC_SHIFT values back and verify")
    ap.add_argument("--clear-sticky-mask", type=lambda s: int(s, 0), default=None, help="Explicit W1C mask for CLEAR_STICKY_FLAGS")
    ap.add_argument("--json", type=Path, default=None, help="Write result JSON")
    ap.add_argument("--quiet", action="store_true", help="Suppress stdout on pass")
    return ap


def main(argv: Sequence[str] | None = None) -> int:
    args = build_argparser().parse_args(argv)
    try:
        root = args.root.resolve() if args.root else repo_root_from(Path(__file__).parent)
        mod = load_generated_packet(root, args.generated_packet)
        const = constants_from_module(mod)
        config = load_config(args.config or (root / DEFAULT_HPS_CONFIG))
        csr_base = args.csr_base_phys
        if csr_base is None:
            csr_base = parse_int(config.get("csr_base_phys"), default=0 if args.mock_mmio else None)
        csr_span = args.csr_span if args.csr_span is not None else parse_int(config.get("csr_span_bytes"), default=4096)
        result = Result(
            backend="mock-mmio" if args.mock_mmio else "devmem",
            csr_base_phys=f"0x{int(csr_base):08x}" if csr_base is not None else "",
            csr_span_bytes=int(csr_span),
        )
        mmio: Mmio | None = None
        try:
            if args.mock_mmio:
                mmio = FileMmio(args.mock_mmio, int(csr_span), init_expected=const if args.init_mock else None)
            else:
                if csr_base is None:
                    raise ValueError("CSR base required: pass --csr-base-phys or configure sw/hps/config/trecap_hps_config.json")
                mmio = DevMemMmio(args.devmem, int(csr_base), int(csr_span))
            perform_smoke(
                mmio,
                const,
                result,
                snapshot=args.snapshot,
                exercise_safe_writes=args.exercise_safe_writes,
                clear_sticky_mask=args.clear_sticky_mask,
            )
        finally:
            if mmio is not None:
                mmio.close()
        payload = result_dict(result)
        if args.json:
            args.json.parent.mkdir(parents=True, exist_ok=True)
            args.json.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        if not args.quiet or not result.ok:
            print(json.dumps(payload, indent=2, sort_keys=True))
            print("[smoke_csr] " + ("PASS" if result.ok else "FAIL"))
        return 0 if result.ok else 1
    except (OSError, RuntimeError, ValueError, FileNotFoundError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
