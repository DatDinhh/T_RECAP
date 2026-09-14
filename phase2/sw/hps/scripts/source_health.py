#!/usr/bin/env python3
"""Read the coherent FPGA source-health page, or explicitly rearm a live source.

Run on the DE1-SoC HPS after loading the matching FPGA image. This tool maps only
CSR device memory; it neither maps DDR nor changes telemetry/ring configuration.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from ctypes import c_uint32
import importlib.util
import json
import mmap
import os
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[3]
CAPABILITY_ABI1 = 0x53480100  # SOURCE_HEALTH_CAPABILITY ABI identity, not an offset.
SOURCE_NAMES = {0: "bram_replay", 1: "adc_live", 2: "audio_wrapper", 3: "diagnostic"}


def load_contract():
    path = ROOT / "sw/pc_dashboard/generated/trecap_packet.py"
    spec = importlib.util.spec_from_file_location("trecap_generated_source_health", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load generated CSR constants: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def integer(value):
    return int(value, 0) if isinstance(value, str) else int(value)


class SourceHealth:
    def __init__(self, registers, generated):
        self.registers = registers
        self.offsets = generated.CSR_OFFSETS
        self.bits = generated.CSR_BITS
        capability = self.read("CAPABILITY")
        if capability != CAPABILITY_ABI1:
            raise RuntimeError(f"source-health ABI unavailable: capability=0x{capability:08x}")

    def read_register(self, name):
        # Native aligned 32-bit MMIO access: byte stores from a byte packer would
        # violate the Avalon adapter's full-word byte-enable contract.
        return c_uint32.from_buffer(self.registers, self.offsets[name]).value

    def read(self, name):
        return self.read_register(f"SOURCE_HEALTH_{name}")

    def command(self, field):
        bit = self.bits["SOURCE_HEALTH_CONTROL"][field][0]
        c_uint32.from_buffer(self.registers,
                             self.offsets["SOURCE_HEALTH_CONTROL"]).value = 1 << bit
        self.read("CONTROL")  # Ordered device read completes the posted CSR write.

    def fields(self, register, value):
        result = {}
        for field, (lo, hi) in self.bits[f"SOURCE_HEALTH_{register}"].items():
            if not field.startswith("reserved"):
                result[field] = (value >> lo) & ((1 << (hi - lo + 1)) - 1)
        return result

    def snapshot(self):
        self.command("snapshot")
        status = self.fields("STATUS", self.read("STATUS"))
        fault_bits = self.fields("FAULT", self.read("FAULT"))
        counters = {}
        for name in self.offsets:
            if name.startswith("SOURCE_HEALTH_") and name.endswith("_LO"):
                stem = name[len("SOURCE_HEALTH_"):-3]
                counters[stem.lower()] = self.read(stem + "_LO") | (self.read(stem + "_HI") << 32)
        return {
            "source": SOURCE_NAMES.get(status["source_mode"], "unknown"),
            "status": status,
            "faults": [name for name, asserted in fault_bits.items() if asserted],
            "nominal_rate_hz": self.read("RATE"),
            "counters": counters,
        }

    def rearm(self, timeout):
        before = self.snapshot()
        if not before["status"]["present"] or not before["status"]["live"]:
            raise RuntimeError("rearm requires ADC_LIVE or AUDIO_WRAPPER as the actual source")
        epoch = before["counters"]["epoch"]
        if epoch == (1 << 64) - 1:
            raise RuntimeError("source epoch is saturated; use board reset to start a new lifetime")
        rejects = self.read_register("CSR_COMMAND_REJECT_COUNT")
        self.command("rearm")
        deadline = time.monotonic() + timeout
        while True:
            after = self.snapshot()
            if self.read_register("CSR_COMMAND_REJECT_COUNT") != rejects:
                raise RuntimeError("CSR reject occurred during rearm; retry after other control activity stops")
            if after["source"] != before["source"]:
                raise RuntimeError("selected source changed during rearm; inspect the new source first")
            if after["counters"]["epoch"] != epoch:
                after["rearm_acknowledged"] = True
                after["previous_epoch"] = epoch
                return after
            if time.monotonic() >= deadline:
                raise RuntimeError("rearm was not acknowledged; inspect source commit/transition state")
            time.sleep(0.01)


@contextmanager
def csr_mapping(config, lock_path):
    # All users of this snapshot bank must serialize snapshot+read transactions.
    import fcntl
    base = integer(config["csr_base_phys"])
    span = integer(config["csr_span_bytes"])
    if base < 0 or base % mmap.PAGESIZE or span < 512 or span % 4:
        raise ValueError("CSR mapping requires a page-aligned physical base and >=512 aligned bytes")
    with open(lock_path, "a", encoding="utf-8") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        fd = os.open("/dev/mem", os.O_RDWR | os.O_SYNC)
        try:
            with mmap.mmap(fd, span, flags=mmap.MAP_SHARED,
                           prot=mmap.PROT_READ | mmap.PROT_WRITE, offset=base) as registers:
                yield registers
        finally:
            os.close(fd)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path,
                        default=ROOT / "sw/hps/config/trecap_hps_config.json")
    parser.add_argument("--rearm", action="store_true",
                        help="invalidate the selected live epoch and restart after stop acknowledgement")
    parser.add_argument("--watch", action="store_true", help="print snapshots until interrupted")
    parser.add_argument("--interval", type=float, default=1.0, help="watch interval in seconds")
    parser.add_argument("--timeout", type=float, default=1.0, help="rearm acknowledgement timeout")
    parser.add_argument("--lock", type=Path, default=Path("/run/lock/trecap-source-health.lock"))
    args = parser.parse_args(argv)
    if args.interval <= 0 or args.timeout <= 0:
        parser.error("interval and timeout must be positive")
    if sys.platform != "linux" or sys.byteorder != "little":
        parser.error("this operator tool requires the little-endian DE1-SoC Linux HPS")
    try:
        generated = load_contract()
        config = json.loads(args.config.read_text(encoding="utf-8"))
        rearm = args.rearm
        while True:
            with csr_mapping(config, args.lock) as registers:
                health = SourceHealth(registers, generated)
                result = health.rearm(args.timeout) if rearm else health.snapshot()
            rearm = False
            print(json.dumps(result, sort_keys=True), flush=True)
            if not args.watch:
                return 3 if result["status"]["fault"] else 0
            time.sleep(args.interval)
    except KeyboardInterrupt:
        return 0
    except (OSError, ValueError, RuntimeError, KeyError) as exc:
        print(f"source-health: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
