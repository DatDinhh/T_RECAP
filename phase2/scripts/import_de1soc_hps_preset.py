#!/usr/bin/env python3
"""Import and freeze the DE1-SoC HPS parameter preset used by Platform Designer.

The input is the official Terasic DE1-SoC Rev-H GHRD ``soc_system.qsys`` from
the Quartus 20.1 System CD.  The importer verifies the exact upstream Qsys
file, extracts every ``hps_0`` parameter, applies the T-RECAP 64-bit
FPGA-to-HPS SDRAM overlay, and emits deterministic checked-in artifacts.

This script is the provenance boundary.  ``platform_designer.tcl`` consumes
the emitted TSV; it never guesses HPS parameter names.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import tempfile
import xml.etree.ElementTree as ET


UPSTREAM_QSYS_SHA256 = "e289b9955e64e51fe5a8dc4c4f3f0a82d62eb1741774ae46e989e186504eaf5c"
UPSTREAM_ARCHIVE_SHA256 = "e9743031e4574effd776100f8ad0874581f3234ef8ce21e2e8e1b4ab10ca088d"
EXPECTED_PARAMETER_COUNT = 520
EXPECTED_COMPONENT_KIND = "altera_hps"
EXPECTED_COMPONENT_VERSION = "20.1"

# These 44 parameters are serialized by Quartus 20.1 but are intentionally not
# written through set_instance_parameter_value. They are system-information,
# clock-frequency readback, INI/debug state, or other tool-derived values. The
# official 20.1 Cyclone-V GHRD construction script sets the other 476 names and
# omits exactly this set. The full 520-row snapshot remains hashed/provenanced.
READBACK_ONLY_PARAMETERS = {
    "AUTO_DEVICE_SPEEDGRADE",
    "EMAC0_PTP",
    "EMAC1_PTP",
    "F2H_AXI_CLOCK_FREQ",
    "F2H_SDRAM0_CLOCK_FREQ",
    "F2H_SDRAM1_CLOCK_FREQ",
    "F2H_SDRAM2_CLOCK_FREQ",
    "F2H_SDRAM3_CLOCK_FREQ",
    "F2H_SDRAM4_CLOCK_FREQ",
    "F2H_SDRAM5_CLOCK_FREQ",
    "F2SCLK_PERIPHCLK_FREQ",
    "F2SCLK_SDRAMCLK_FREQ",
    "FIX_READ_LATENCY",
    "FPGA_PERIPHERAL_INPUT_CLOCK_FREQ_EMAC0_RX_CLK_IN",
    "FPGA_PERIPHERAL_INPUT_CLOCK_FREQ_EMAC0_TX_CLK_IN",
    "FPGA_PERIPHERAL_INPUT_CLOCK_FREQ_EMAC1_RX_CLK_IN",
    "FPGA_PERIPHERAL_INPUT_CLOCK_FREQ_EMAC1_TX_CLK_IN",
    "FPGA_PERIPHERAL_INPUT_CLOCK_FREQ_EMAC_PTP_REF_CLOCK",
    "FPGA_PERIPHERAL_INPUT_CLOCK_FREQ_I2C0_SCL_IN",
    "FPGA_PERIPHERAL_INPUT_CLOCK_FREQ_I2C1_SCL_IN",
    "FPGA_PERIPHERAL_INPUT_CLOCK_FREQ_I2C2_SCL_IN",
    "FPGA_PERIPHERAL_INPUT_CLOCK_FREQ_I2C3_SCL_IN",
    "FPGA_PERIPHERAL_INPUT_CLOCK_FREQ_SPIS0_SCLK_IN",
    "FPGA_PERIPHERAL_INPUT_CLOCK_FREQ_SPIS1_SCLK_IN",
    "FPGA_PERIPHERAL_INPUT_CLOCK_FREQ_USB0_CLK_IN",
    "FPGA_PERIPHERAL_INPUT_CLOCK_FREQ_USB1_CLK_IN",
    "H2F_AXI_CLOCK_FREQ",
    "H2F_CTI_CLOCK_FREQ",
    "H2F_DEBUG_APB_CLOCK_FREQ",
    "H2F_LW_AXI_CLOCK_FREQ",
    "H2F_TPIU_CLOCK_IN_FREQ",
    "S2FCLK_USER2CLK",
    "SYS_INFO_DEVICE_FAMILY",
    "TPIUFPGA_alt",
    "device_name",
    "quartus_ini_hps_emif_pll",
    "quartus_ini_hps_ip_enable_all_peripheral_fpga_interfaces",
    "quartus_ini_hps_ip_enable_bsel_csel",
    "quartus_ini_hps_ip_enable_emac0_peripheral_fpga_interface",
    "quartus_ini_hps_ip_enable_low_speed_serial_fpga_interfaces",
    "quartus_ini_hps_ip_enable_test_interface",
    "quartus_ini_hps_ip_f2sdram_bonding_out",
    "quartus_ini_hps_ip_fast_f2sdram_sim_model",
    "quartus_ini_hps_ip_suppress_sdram_synth",
}

OVERLAY = {
    "F2SDRAM_Type": "Avalon-MM Bidirectional",
    "F2SDRAM_Width": "64",
}

REQUIRED_EFFECTIVE_PARAMETERS = {
    "EMAC1_Mode": "RGMII",
    "EMAC1_PinMuxing": "HPS I/O Set 0",
    "F2SDRAM_Type": "Avalon-MM Bidirectional",
    "F2SDRAM_Width": "64",
    "HARD_EMIF": "true",
    "HHP_HPS": "true",
    "LWH2F_Enable": "true",
    "MPU_EVENTS_Enable": "false",
    "SDIO_Mode": "4-bit Data",
    "SDIO_PinMuxing": "HPS I/O Set 0",
    "UART0_Mode": "No Flow Control",
    "UART0_PinMuxing": "HPS I/O Set 0",
    "USB1_Mode": "SDR",
    "USB1_PinMuxing": "HPS I/O Set 0",
}


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical_parameter_bytes(parameters: dict[str, str]) -> bytes:
    """Return the documented canonical representation used for snapshot hashes."""

    return "".join(f"{name}={parameters[name]}\n" for name in sorted(parameters)).encode(
        "utf-8"
    )


def canonical_application_bytes(parameters: dict[str, str]) -> bytes:
    return "".join(
        f"{name}={'readback_only' if name in READBACK_ONLY_PARAMETERS else 'set'}\n"
        for name in sorted(parameters)
    ).encode("utf-8")


def extract_hps_parameters(qsys_path: Path) -> tuple[dict[str, str], dict[str, str]]:
    raw = qsys_path.read_bytes()
    actual_sha = sha256_bytes(raw)
    if actual_sha != UPSTREAM_QSYS_SHA256:
        raise ValueError(
            f"unexpected upstream Qsys SHA-256: {actual_sha}; "
            f"expected {UPSTREAM_QSYS_SHA256}"
        )

    root = ET.fromstring(raw)
    candidates = [module for module in root.findall(".//module") if module.get("name") == "hps_0"]
    if len(candidates) != 1:
        raise ValueError(f"expected exactly one hps_0 module; found {len(candidates)}")

    module = candidates[0]
    module_info = {
        "name": module.get("name", ""),
        "kind": module.get("kind", ""),
        "version": module.get("version", ""),
    }
    if module_info["kind"] != EXPECTED_COMPONENT_KIND:
        raise ValueError(f"unexpected HPS kind: {module_info['kind']!r}")
    if module_info["version"] != EXPECTED_COMPONENT_VERSION:
        raise ValueError(f"unexpected HPS component version: {module_info['version']!r}")

    parameters: dict[str, str] = {}
    for element in module.findall("./parameter"):
        name = element.get("name")
        if not name:
            raise ValueError("hps_0 contains a parameter without a name")
        if name in parameters:
            raise ValueError(f"duplicate hps_0 parameter: {name}")
        value_attr = element.get("value")
        value = value_attr if value_attr is not None else (element.text or "").strip()
        if any(char in name or char in value for char in ("\t", "\r", "\n")):
            raise ValueError(f"parameter {name!r} cannot be represented in the TSV snapshot")
        parameters[name] = value

    if len(parameters) != EXPECTED_PARAMETER_COUNT:
        raise ValueError(
            f"unexpected HPS parameter count: {len(parameters)}; "
            f"expected {EXPECTED_PARAMETER_COUNT}"
        )
    return parameters, module_info


def render_tsv(
    parameters: dict[str, str], base_hash: str, effective_hash: str, application_hash: str
) -> bytes:
    lines = [
        "# SPDX-License-Identifier: MIT",
        "# AUTO-GENERATED - DO NOT EDIT.",
        "# Generator: scripts/import_de1soc_hps_preset.py",
        "# Source: official Terasic DE1-SoC Rev-H Quartus 20.1 GHRD soc_system.qsys",
        f"# upstream_qsys_sha256={UPSTREAM_QSYS_SHA256}",
        f"# base_parameter_sha256={base_hash}",
        f"# effective_parameter_sha256={effective_hash}",
        f"# parameter_count={len(parameters)}",
        f"# applied_parameter_count={len(parameters) - len(READBACK_ONLY_PARAMETERS)}",
        f"# readback_only_parameter_count={len(READBACK_ONLY_PARAMETERS)}",
        f"# application_mode_sha256={application_hash}",
        "# Canonical hash input: UTF-8, parameters sorted by name, one name=value\\n per row.",
        "# Columns: parameter_name<TAB>value<TAB>application_mode(set|readback_only).",
    ]
    lines.extend(
        f"{name}\t{parameters[name]}\t"
        f"{'readback_only' if name in READBACK_ONLY_PARAMETERS else 'set'}"
        for name in sorted(parameters)
    )
    return ("\n".join(lines) + "\n").encode("utf-8")


def render_manifest(
    module_info: dict[str, str],
    base: dict[str, str],
    effective: dict[str, str],
    base_hash: str,
    effective_hash: str,
    application_hash: str,
) -> bytes:
    overlays = [
        {
            "parameter": name,
            "upstream_value": base[name],
            "effective_value": effective[name],
            "reason": (
                "T-RECAP DDR writer is frozen at a 64-bit Avalon-MM bidirectional "
                "FPGA-to-HPS SDRAM interface"
            ),
        }
        for name in sorted(OVERLAY)
    ]
    manifest = {
        "schema": "trecap_de1soc_hps_preset_manifest_v1",
        "file_class": "[2] generated vendor-derived configuration snapshot - do not edit",
        "profile_id": "terasic_de1soc_revh_qp20_1_trecap_f2sdram64",
        "contract_stage": "step2_platform_designer_hps_source_frozen",
        "board": {
            "vendor": "Terasic",
            "model": "DE1-SoC",
            "source_revision": "H",
            "physical_board_revision_status": "unverified_requires_board_label_confirmation",
            "assumption": (
                "The pinned vendor Rev-H GHRD is Quartus-20.1-compatible. The physical "
                "board revision is an independent, unverified fact; a Rev-F/G board "
                "requires a separately reviewed preset."
            ),
            "device_family": "Cyclone V",
            "device_part": "5CSEMA5F31C6",
        },
        "toolchain": {
            "quartus_release": "20.1",
            "platform_designer_qsys_api_package": "16.0",
            "hps_component": module_info,
            "note": (
                "The qsys Tcl API package version and the altera_hps component "
                "version are separate version domains."
            ),
        },
        "provenance": {
            "system_cd_url": (
                "https://download.terasic.com/downloads/cd-rom/de1-soc/"
                "DE1-SoC_v.6.0.0_HWrevH_SystemCD.zip"
            ),
            "system_cd_sha256": UPSTREAM_ARCHIVE_SHA256,
            "member_path": "Demonstrations/SOC_FPGA/de1_soc_GHRD/soc_system.qsys",
            "member_sha256": UPSTREAM_QSYS_SHA256,
            "cross_reference": (
                "https://raw.githubusercontent.com/altera-opensource/ghrd-socfpga/"
                "ACDS-20.3pro-20.1std/cv_soc_devkit_ghrd/create_ghrd_qsys.tcl"
            ),
            "cross_reference_sha256": (
                "b7fc8e80bf5e04599895cff7211ff9a9d07cda1f6f3213312c7b3f8c811aba4b"
            ),
        },
        "snapshot": {
            "canonicalization": "UTF-8; sort by parameter name; name=value\\n per row",
            "parameter_count": len(effective),
            "upstream_parameter_sha256": base_hash,
            "effective_parameter_sha256": effective_hash,
            "overlay": overlays,
            "application": {
                "set_parameter_count": len(effective) - len(READBACK_ONLY_PARAMETERS),
                "readback_only_parameter_count": len(READBACK_ONLY_PARAMETERS),
                "application_mode_sha256": application_hash,
                "readback_only_parameters": sorted(READBACK_ONLY_PARAMETERS),
                "policy": (
                    "Apply only rows marked set. Rows marked readback_only are frozen "
                    "upstream observations for provenance; Platform Designer derives them "
                    "from the selected device, INI state, and connected clocks. Capture their "
                    "tool-normalized values in the next integration step."
                ),
            },
        },
        "required_interfaces": {
            "clock_source_parameters": {
                "clockFrequency": "50000000",
                "clockFrequencyKnown": "true",
                "resetSynchronousEdges": "NONE",
            },
            "exports": {
                "hps_io": {
                    "internal": "hps_0.hps_io",
                    "kind": "conduit",
                    "serialized_direction": "end",
                    "qsys_tcl_role": "end",
                },
                "memory": {
                    "internal": "hps_0.memory",
                    "kind": "conduit",
                    "serialized_direction": "end",
                    "qsys_tcl_role": "end",
                },
                "trecap_csr_lw_master": {
                    "internal": "hps_0.h2f_lw_axi_master",
                    "kind": "avalon",
                    "serialized_direction": "start",
                    "qsys_tcl_role": "master",
                },
                "trecap_f2h_sdram0": {
                    "internal": "hps_0.f2h_sdram0_data",
                    "kind": "avalon",
                    "serialized_direction": "end",
                    "qsys_tcl_role": "slave",
                },
                "h2f_reset": {
                    "internal": "hps_0.h2f_reset",
                    "kind": "reset",
                    "serialized_direction": "start",
                    "qsys_tcl_role": "source",
                },
                "clk_50": {
                    "internal": "clk_0.clk_in",
                    "kind": "clock",
                    "serialized_direction": "end",
                    "qsys_tcl_role": "sink",
                },
                "reset_n": {
                    "internal": "clk_0.clk_in_reset",
                    "kind": "reset",
                    "serialized_direction": "end",
                    "qsys_tcl_role": "sink",
                },
            },
            "clock_connections": [
                {"source": "clk_0.clk", "sink": "hps_0.f2h_sdram0_clock"},
                {"source": "clk_0.clk", "sink": "hps_0.h2f_axi_clock"},
                {"source": "clk_0.clk", "sink": "hps_0.f2h_axi_clock"},
                {"source": "clk_0.clk", "sink": "hps_0.h2f_lw_axi_clock"},
            ],
        },
        "address_status": (
            "source_frozen_pending_sopcinfo_linux_reservation_and_board_revision_signoff"
        ),
        "required_effective_parameters": REQUIRED_EFFECTIVE_PARAMETERS,
    }
    return (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode("utf-8")


def atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as handle:
        handle.write(data)
        temp_name = handle.name
    os.replace(temp_name, path)


def check_or_write(path: Path, expected: bytes, check: bool) -> None:
    if check:
        if not path.is_file():
            raise ValueError(f"generated artifact is missing: {path}")
        if path.read_bytes() != expected:
            raise ValueError(f"generated artifact drift: {path}")
        return
    atomic_write(path, expected)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vendor-qsys", type=Path, required=True)
    parser.add_argument(
        "--preset-tsv",
        type=Path,
        default=Path("platform/de1soc/qsys/presets/terasic_de1soc_revh_qp20_1_hps.tsv"),
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=Path(
            "platform/de1soc/qsys/presets/terasic_de1soc_revh_qp20_1_hps_manifest.json"
        ),
    )
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    base, module_info = extract_hps_parameters(args.vendor_qsys)
    base_hash = sha256_bytes(canonical_parameter_bytes(base))
    effective = dict(base)
    effective.update(OVERLAY)
    effective_hash = sha256_bytes(canonical_parameter_bytes(effective))
    application_hash = sha256_bytes(canonical_application_bytes(effective))

    unknown_readbacks = READBACK_ONLY_PARAMETERS - set(effective)
    if unknown_readbacks:
        raise ValueError(f"readback-only classification contains unknown names: {unknown_readbacks}")
    if len(effective) - len(READBACK_ONLY_PARAMETERS) != 476:
        raise ValueError("expected exactly 476 settable and 44 readback-only HPS parameters")
    for overlay_name in OVERLAY:
        if overlay_name in READBACK_ONLY_PARAMETERS:
            raise ValueError(f"project overlay cannot be readback-only: {overlay_name}")

    for name, expected in REQUIRED_EFFECTIVE_PARAMETERS.items():
        actual = effective.get(name)
        if actual != expected:
            raise ValueError(f"required effective parameter {name}={expected!r}; got {actual!r}")

    check_or_write(
        args.preset_tsv,
        render_tsv(effective, base_hash, effective_hash, application_hash),
        args.check,
    )
    check_or_write(
        args.manifest,
        render_manifest(module_info, base, effective, base_hash, effective_hash, application_hash),
        args.check,
    )
    action = "verified" if args.check else "wrote"
    print(
        f"import_de1soc_hps_preset: {action} {len(effective)} parameters; "
        f"effective_sha256={effective_hash}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
