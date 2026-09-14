#!/usr/bin/env python3
"""Generate T-RECAP Phase 2 RTL filelists and Quartus include.

File class: [1] hand-written generator script.

The generated filelists are R1 infrastructure outputs. They are deterministic and
layered. Expected files are emitted as active entries by default so compile targets
fail when a required implementation file is still missing. Use --comment-missing
only for early documentation snapshots.
"""
from __future__ import annotations

import argparse
import hashlib
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence

GENERATOR_VERSION = "r1.4.1"
GENERATOR_PATH = "scripts/gen_filelists.py"

FILELIST_OUTPUTS = [
    "filelists/rtl_core.f",
    "filelists/rtl_core_plus_fft.f",
    "filelists/rtl_telemetry.f",
    "filelists/rtl_core_telemetry.f",
    "filelists/rtl_hps_bridge.f",
    "filelists/rtl_bram_replay_system.f",
    "filelists/rtl_de1soc_full.f",
    "filelists/quartus_de1soc.qsf.inc",
]

INCDIRS = [
    "rtl/include",
    "rtl/include/generated",
    "rtl/interfaces",
]

GENERATED_PKGS = [
    "rtl/include/generated/trecap_core_pkg.sv",
    "rtl/include/generated/trecap_csr_pkg.sv",
    "rtl/include/generated/trecap_packet_pkg.sv",
    "rtl/include/generated/trecap_iface_pkg.sv",
]

HAND_PKGS = [
    "rtl/include/trecap_math_pkg.sv",
    "rtl/include/trecap_build_pkg.sv",
]

COMMON = [
    "rtl/common/round_sat.sv",
    "rtl/common/reset_sync.sv",
    "rtl/common/sync_pulse.sv",
    "rtl/common/sync_bus_snapshot.sv",
    "rtl/common/skid_buffer.sv",
    "rtl/common/simple_dual_port_ram.sv",
    "rtl/common/true_dual_port_ram.sv",
    "rtl/common/sync_fifo.sv",
    "rtl/common/async_fifo.sv",
]

INTERFACES = [
    "rtl/interfaces/trecap_sample_if.sv",
    "rtl/interfaces/trecap_frame_if.sv",
    "rtl/interfaces/trecap_core_tap_if.sv",
    "rtl/interfaces/trecap_record_if.sv",
    "rtl/interfaces/trecap_csr_if.sv",
    "rtl/interfaces/trecap_avmm_if.sv",
]

SOURCES = [
    "rtl/sources/trecap_bram_replay_source.sv",
    "rtl/sources/trecap_diagnostic_source.sv",
    "rtl/sources/trecap_source_mux.sv",
    "rtl/sources/trecap_audio_adapter.sv",
    "rtl/sources/trecap_adc_adapter.sv",
]

CORE = [
    "rtl/core/trecap_input_ring.sv",
    "rtl/core/trecap_frame_scheduler.sv",
    "rtl/core/window_rom.sv",
    "rtl/core/trecap_analysis_window.sv",
    "rtl/core/trecap_hermitian_canonicalizer.sv",
    "rtl/core/trecap_mag2_mask.sv",
    "rtl/core/trecap_spectrum_mask_builder.sv",
    "rtl/core/trecap_synthesis_wola.sv",
    "rtl/core/trecap_delay_error_metrics.sv",
    "rtl/core/trecap_core_top.sv",
]

FFT = [
    "rtl/fft/complex_mul_q.sv",
    "rtl/fft/bit_reverse_addr.sv",
    "rtl/fft/twiddle_rom.sv",
    "rtl/fft/trecap_fft_stage.sv",
    "rtl/fft/trecap_fft256.sv",
    "rtl/fft/trecap_ifft256.sv",
]

TELEMETRY = [
    "rtl/telemetry/trecap_packet_scheduler.sv",
    "rtl/telemetry/trecap_wave_packetizer.sv",
    "rtl/telemetry/trecap_spec_packetizer.sv",
    "rtl/telemetry/trecap_metrics_packetizer.sv",
    "rtl/telemetry/trecap_status_packetizer.sv",
    "rtl/telemetry/trecap_priority_dropper.sv",
    "rtl/telemetry/trecap_packet_fifo.sv",
    "rtl/telemetry/trecap_telemetry_top.sv",
]

HPS_BRIDGE = [
    "rtl/hps_bridge/trecap_csr_shadow_commit.sv",
    "rtl/hps_bridge/trecap_avmm_csr_adapter.sv",
    "rtl/hps_bridge/trecap_csr_bank.sv",
    "rtl/hps_bridge/trecap_ring_pointer_ctrl.sv",
    "rtl/hps_bridge/trecap_ddr_record_builder.sv",
    "rtl/hps_bridge/trecap_avmm_write_master.sv",
    "rtl/hps_bridge/trecap_ddr_ring_writer.sv",
    "rtl/hps_bridge/trecap_hps_bridge_top.sv",
]

PLATFORM_DE1SOC = [
    "rtl/platform/de1soc/platform_designer_wrapper.sv",
    "rtl/platform/de1soc/clock_reset_ctrl.sv",
    "rtl/platform/de1soc/audio_pll_wrapper.sv",
    "rtl/platform/de1soc/audio_codec_i2c_init.sv",
    "rtl/platform/de1soc/audio_codec_wrapper.sv",
    "rtl/platform/de1soc/adc_wrapper.sv",
]

BOARD_DE1SOC = [
    "rtl/platform/de1soc/de1_soc_trecap_top.sv",
]

TOP_CORE = [
    "rtl/top/trecap_core_only_top.sv",
    "rtl/top/trecap_core_bram_replay_top.sv",
]

TOP_SOURCE_CORE = [
    "rtl/top/trecap_source_core_integration.sv",
]

TOP_TELEM = [
    "rtl/top/trecap_core_telemetry_top.sv",
]

TOP_FULL = [
    "rtl/top/trecap_de1soc_full_top.sv",
]

TOP_REPLAY_E2E = [
    "rtl/top/trecap_bram_replay_e2e_supervisor.sv",
]

TOP_STEP11 = [
    "rtl/top/trecap_bram_replay_system_top.sv",
]


@dataclass(frozen=True)
class Filelist:
    output: str
    title: str
    files: List[str]


def repo_root_from_script() -> Path:
    return Path(__file__).resolve().parents[1]


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def relpath(root: Path, path: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def unique(seq: Iterable[str]) -> List[str]:
    out: List[str] = []
    seen: set[str] = set()
    for item in seq:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out


def header(title: str) -> str:
    return "\n".join(
        [
            "# AUTO-GENERATED - DO NOT EDIT",
            f"# Generator: {GENERATOR_PATH}",
            f"# Generator version: {GENERATOR_VERSION}",
            f"# Filelist: {title}",
            "# Expected source files are active entries by default; compile targets fail if missing.",
            "",
        ]
    )


def render_f(root: Path, fl: Filelist, strict: bool, comment_missing: bool) -> str:
    lines = [header(fl.title)]
    for incdir in INCDIRS:
        if (root / incdir).is_dir():
            lines.append(f"+incdir+{incdir}")
        else:
            lines.append(f"# MISSING_INCDIR: +incdir+{incdir}")
            if strict:
                raise FileNotFoundError(f"missing include directory: {incdir}")
    lines.append("")
    for rel in unique(fl.files):
        path = root / rel
        if path.is_file() or not comment_missing:
            lines.append(rel)
        else:
            lines.append(f"# MISSING: {rel}")
        if strict and not path.is_file():
            raise FileNotFoundError(f"missing expected RTL file for {fl.output}: {rel}")
    return "\n".join(lines).rstrip() + "\n"


def render_qsf(root: Path, files: Sequence[str], strict: bool, comment_missing: bool) -> str:
    lines = [
        "# AUTO-GENERATED - DO NOT EDIT",
        f"# Generator: {GENERATOR_PATH}",
        f"# Generator version: {GENERATOR_VERSION}",
        "# Include this from the DE1-SoC Quartus project after project-specific QSF settings.",
        "# Resolve relative to this include, independent of the Quartus project directory.",
        "set trecap_filelist_root [file normalize [file join [file dirname [info script]] ..]]",
        "",
    ]
    for rel in unique(files):
        exists = (root / rel).is_file()
        if exists or not comment_missing:
            lines.append(f"set_global_assignment -name SYSTEMVERILOG_FILE [file join $trecap_filelist_root {{{rel}}}]")
        else:
            lines.append(f"# MISSING: set_global_assignment -name SYSTEMVERILOG_FILE [file join $trecap_filelist_root {{{rel}}}]")
        if strict and not exists:
            raise FileNotFoundError(f"missing expected Quartus source: {rel}")
    return "\n".join(lines).rstrip() + "\n"


def build_filelists() -> List[Filelist]:
    pkgs = GENERATED_PKGS + HAND_PKGS
    core_base = pkgs + COMMON + INTERFACES + SOURCES + CORE + TOP_CORE + TOP_SOURCE_CORE
    core_plus_fft = pkgs + COMMON + INTERFACES + SOURCES + FFT + CORE + TOP_CORE + TOP_SOURCE_CORE
    # Keep the telemetry-only closure independent of the mathematical core. The standalone
    # core+telemetry composition owns a real trecap_core_top, so it receives a separate filelist
    # with the complete FFT/core closure and the composition top exactly once.
    telemetry = pkgs + COMMON + INTERFACES + TELEMETRY
    core_telemetry = pkgs + COMMON + INTERFACES + FFT + CORE + TELEMETRY + TOP_TELEM
    hps_bridge = pkgs + COMMON + INTERFACES + HPS_BRIDGE
    bram_replay_system = (pkgs + COMMON + INTERFACES + SOURCES + FFT + CORE + TELEMETRY +
                          HPS_BRIDGE + TOP_SOURCE_CORE + TOP_FULL + TOP_REPLAY_E2E + TOP_STEP11)
    # The Step-9 physical-board path owns one core through trecap_source_core_integration and
    # feeds real valid-only taps into trecap_de1soc_full_top. Platform Designer, audio, ADC,
    # source/core, telemetry/HPS, and physical-board owners all occur once in dependency order.
    # Do not add TOP_TELEM: that standalone composition owns a second core. Generated `system`
    # HDL remains vendor/QIP-owned rather than being copied into this hand-written closure.
    full = (pkgs + COMMON + INTERFACES + SOURCES + FFT + CORE + TELEMETRY + HPS_BRIDGE +
            TOP_SOURCE_CORE + TOP_FULL + TOP_REPLAY_E2E + PLATFORM_DE1SOC + BOARD_DE1SOC)
    return [
        Filelist("filelists/rtl_core.f", "core skeleton without standalone FFT file ownership", core_base),
        Filelist("filelists/rtl_core_plus_fft.f", "core-first Cut C0 compile order including FFT/IFFT", core_plus_fft),
        Filelist("filelists/rtl_telemetry.f", "telemetry-only packetizers and packet FIFO", telemetry),
        Filelist(
            "filelists/rtl_core_telemetry.f",
            "standalone normalized-source core plus non-stalling telemetry composition",
            core_telemetry,
        ),
        Filelist("filelists/rtl_hps_bridge.f", "CSR, pointer control, record builder, and DDR ring writer", hps_bridge),
        Filelist(
            "filelists/rtl_bram_replay_system.f",
            "Step-11 BRAM replay through exact core completion and HPS-visible DDR transport",
            bram_replay_system,
        ),
        Filelist(
            "filelists/rtl_de1soc_full.f",
            "full DE1-SoC real board-top integration compile order",
            full,
        ),
    ]


def write_outputs(root: Path, texts: Dict[str, str], check: bool) -> int:
    failures: List[str] = []
    for rel, text in texts.items():
        if not text.endswith("\n"):
            raise RuntimeError(f"internal error: {rel} missing final newline")
        path = (root / rel).resolve()
        path.relative_to(root.resolve())
        if check:
            if not path.exists():
                failures.append(f"missing generated file: {rel}")
            elif path.read_text(encoding="utf-8") != text:
                failures.append(f"generated drift: {rel}")
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8", newline="\n")
    if failures:
        for item in failures:
            print(item, file=sys.stderr)
        return 1
    return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Generate T-RECAP Phase 2 SystemVerilog filelists.")
    parser.add_argument("--root", default=None, help="Repository root. Default: parent of this script directory.")
    parser.add_argument("--strict", action="store_true", help="Fail during filelist generation if any expected source file is missing.")
    parser.add_argument("--comment-missing", action="store_true", help="Comment out missing expected files instead of emitting active entries. Do not use for C0/T0 gates.")
    parser.add_argument("--check", action="store_true", help="Do not write; fail if generated outputs differ from checked-in files.")
    parser.add_argument("--quiet", action="store_true", help="Reduce progress messages.")
    args = parser.parse_args(argv)

    root = Path(args.root).resolve() if args.root else repo_root_from_script()
    if not (root / "Makefile").exists():
        raise SystemExit(f"ERROR: repository root does not look valid: {root}")

    filelists = build_filelists()
    texts: Dict[str, str] = {}
    for fl in filelists:
        texts[fl.output] = render_f(root, fl, args.strict, args.comment_missing)
    # Match rtl_de1soc_full.f at the hand-written Quartus boundary. The standalone core+telemetry
    # top is absent because the hierarchy already has a source-owned core; generated Platform
    # Designer products enter through their QIP rather than this include.
    full_files = (GENERATED_PKGS + HAND_PKGS + COMMON + INTERFACES + SOURCES + FFT + CORE +
                  TELEMETRY + HPS_BRIDGE + TOP_SOURCE_CORE + TOP_FULL + TOP_REPLAY_E2E +
                  PLATFORM_DE1SOC + BOARD_DE1SOC)
    texts["filelists/quartus_de1soc.qsf.inc"] = render_qsf(root, full_files, args.strict, args.comment_missing)

    rc = write_outputs(root, texts, args.check)
    if rc == 0 and not args.quiet:
        mode = "checked" if args.check else "generated"
        for rel, text in texts.items():
            print(f"{mode}: {rel} sha256={sha256_text(text)}")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
