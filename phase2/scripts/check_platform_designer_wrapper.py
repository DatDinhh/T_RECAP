#!/usr/bin/env python3
"""Check the Step-6 Platform Designer wrapper source contract.

The default mode is a dependency-free source/structure gate.  It validates the
machine contract, schema identity, hand-written wrapper, board connection,
reset policy, Platform Designer bridge source, XML readability, documentation,
and filelists.  It deliberately does not require or claim generated Quartus
artifacts.

``--require-generated`` additionally requires generated ``system.v`` or
``system.sv``, ``system.qip``, and ``system.sopcinfo``; rejects the bootstrap
Qsys source; and validates every generated ``system`` port direction and width
against the frozen flattened ABI.  Even that mode is not compile, functional,
or hardware evidence.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys
import xml.etree.ElementTree as ET
from typing import Any, Mapping

try:
    import jsonschema  # type: ignore[import-not-found]
except ImportError:
    jsonschema = None


CONTRACT_REL = Path("platform/de1soc/address_map/platform_designer_wrapper.json")
SCHEMA_REL = Path("spec/schemas/platform_designer_wrapper.schema.json")
DOC_REL = Path("docs/architecture/platform_designer_wrapper.md")
WRAPPER_REL = Path("rtl/platform/de1soc/platform_designer_wrapper.sv")
BOARD_TOP_REL = Path("rtl/platform/de1soc/de1_soc_trecap_top.sv")
CLOCK_RESET_REL = Path("rtl/platform/de1soc/clock_reset_ctrl.sv")
LOGICAL_TOP_REL = Path("rtl/top/trecap_de1soc_full_top.sv")
DDR_RING_WRITER_REL = Path("rtl/hps_bridge/trecap_ddr_ring_writer.sv")
AVMM_WRITE_MASTER_REL = Path("rtl/hps_bridge/trecap_avmm_write_master.sv")
QUARTUS_BUILD_REL = Path("scripts/quartus/build_de1soc.sh")
QSYS_GENERATOR_REL = Path("platform/de1soc/qsys/platform_designer.tcl")
QSYS_CONFIG_REL = Path("platform/de1soc/qsys/hps_config.tcl")
QSYS_REL = Path("platform/de1soc/qsys/system.qsys")
QSYS_BLUEPRINT_REL = Path("platform/de1soc/qsys/system_blueprint.xml")
GENERATED_HDL_RELS = (
    Path("platform/de1soc/qsys/system/synthesis/system.v"),
    Path("platform/de1soc/qsys/system/synthesis/system.sv"),
)
QIP_REL = Path("platform/de1soc/qsys/system/synthesis/system.qip")
SOPCINFO_REL = Path("platform/de1soc/qsys/system.sopcinfo")
FILELIST_RELS = (
    Path("filelists/rtl_de1soc_full.f"),
    Path("filelists/quartus_de1soc.qsf.inc"),
    Path("scripts/gen_filelists.py"),
)

EXPECTED_SCHEMA = "trecap_phase2_de1soc_platform_designer_wrapper_v1"
EXPECTED_STAGE = "step6_platform_designer_wrapper_source_implemented"
EXPECTED_STATUS = (
    "source_implemented_pending_quartus_generation_compile_and_hardware_evidence"
)
EXPECTED_STATE: dict[str, object] = {
    "wrapper_source_implemented": True,
    "board_source_connected": True,
    "qsys_source_bridges_connected": True,
    "generated_system_present": False,
    "normalized_qsys": False,
    "quartus_compile": False,
    "functional_verification": False,
    "hardware_signoff": False,
}
EXPECTED_SOURCE_OWNERSHIP: dict[str, object] = {
    "wrapper_rtl": WRAPPER_REL.as_posix(),
    "board_top_rtl": BOARD_TOP_REL.as_posix(),
    "clock_reset_controller": CLOCK_RESET_REL.as_posix(),
    "logical_top_rtl": LOGICAL_TOP_REL.as_posix(),
    "ddr_ring_writer_rtl": DDR_RING_WRITER_REL.as_posix(),
    "qsys_generator": QSYS_GENERATOR_REL.as_posix(),
    "qsys_config": QSYS_CONFIG_REL.as_posix(),
    "qsys_source": QSYS_REL.as_posix(),
    "qsys_blueprint": QSYS_BLUEPRINT_REL.as_posix(),
    "generated_hdl_policy": (
        "quartus_generated_never_hand_edit_or_substitute_with_source_stub"
    ),
}
EXPECTED_CSR: dict[str, object] = {
    "export_name": "trecap_csr_lw_master",
    "internal_path": (
        "hps_0.h2f_lw_axi_master_to_trecap_csr_bridge.s0_to_"
        "trecap_csr_bridge.m0"
    ),
    "address_unit": "byte",
    "address_width_bits": 21,
    "data_width_bits": 32,
    "byteenable_width_bits": 4,
    "burstcount_width_bits": 1,
    "maximum_burst_beats": 1,
    "full_lightweight_aperture_preserved": True,
    "full_response_channel": True,
    "response_width_bits": 2,
    "response_signals": [
        "waitrequest",
        "readdata",
        "readdatavalid",
        "writeresponsevalid",
        "response",
    ],
}
EXPECTED_DDR: dict[str, object] = {
    "export_name": "trecap_f2h_sdram0",
    "internal_path": (
        "trecap_f2h_sdram_bridge.s0_to_trecap_f2h_sdram_bridge.m0_to_"
        "hps_0.f2h_sdram0_data"
    ),
    "address_unit": "byte",
    "repository_address_width_bits": 64,
    "repository_data_width_bits": 64,
    "repository_byteenable_width_bits": 8,
    "repository_burstcount_width_bits": 1,
    "wrapper_address_width_bits": 32,
    "platform_designer_data_width_bits": 64,
    "platform_designer_byteenable_width_bits": 8,
    "platform_designer_burstcount_width_bits": 1,
    "maximum_address_exclusive": "0x40000000",
    "legal_address_range": "[0x00000000,0x40000000)",
    "legal_write_waitrequest_source": "trecap_f2h_sdram0_waitrequest",
    "platform_designer_write_response_channel_present": False,
    "repository_local_response_generated": True,
    "repository_local_response_kind": "registered_bridge_acceptance_only",
    "repository_local_response_latency_cycles_after_acceptance": 1,
    "repository_local_legal_response": "OKAY",
    "repository_local_response_is_downstream_dram_completion": False,
    "read_command_tie": 0,
    "unused_read_outputs": [
        "trecap_f2h_sdram0_readdata",
        "trecap_f2h_sdram0_readdatavalid",
    ],
}
EXPECTED_INVALID_DDR: dict[str, object] = {
    "invalid_condition": (
        "avm_write_i_and_avm_address_i_greater_than_or_equal_to_"
        "0x0000000040000000"
    ),
    "waitrequest": 0,
    "writeresponsevalid": 1,
    "response": "SLVERR",
    "forward_write_to_platform_designer": False,
    "silent_truncation_permitted": False,
    "response_is_registered": True,
    "response_latency_cycles_after_acceptance": 1,
    "response_same_cycle_as_acceptance": False,
    "upstream_commit_guard": (
        "avmm_write_master_waits_for_final_success_response_before_ring_writer_commit"
    ),
}
EXPECTED_RESET: dict[str, object] = {
    "canonical_reset_owner": "clock_reset_ctrl",
    "board_reset_input": "KEY[0]",
    "board_reset_release_qualification_cycles": 1_000_000,
    "h2f_reset_input": "h2f_reset_n_i",
    "generated_system_reset_input": "reset_n_reset_n",
    "generated_system_reset_input_scope": "clk_0_reset_to_typed_avalon_bridges_only",
    "generated_h2f_reset_output": "h2f_reset_reset_n",
    "wrapper_bridge_reset_input": "bridge_reset_n_i",
    "wrapper_h2f_reset_output": "h2f_reset_n_o",
    "generated_system_reset_source": "rst_n_platform",
    "fabric_reset_combination": "qualified_KEY0_and_h2f_reset_n",
    "fabric_reset_output": "rst_n_platform",
    "wrapper_local_response_reset_source": "rst_n_platform",
    "synchronizer_module": "trecap_reset_sync",
    "clock_domain": "clk_fabric_from_CLOCK_50",
    "board_top_reset_synchronizer_permitted": False,
    "pseudo_domain_reset_outputs_permitted": False,
    "asynchronous_assertion": True,
    "synchronous_deassertion": True,
    "h2f_reset_reaches_generated_bridge_reset": True,
    "h2f_reset_reaches_hps_reset_input": False,
    "transaction_state_reset_coherent": True,
    "reset_feedback_loop_permitted": False,
}
EXPECTED_GRAPH: dict[str, object] = {
    "source_graph_authority": QSYS_GENERATOR_REL.as_posix(),
    "checked_in_qsys_state": "hand_written_bootstrap_not_normalized",
    "clock_source": "clk_0.clk",
    "bridge_reset_source": "clk_0.clk_reset",
    "csr_bridge": {
        "instance": "trecap_csr_bridge",
        "component_type": "altera_avalon_mm_bridge",
        "upstream": "hps_0.h2f_lw_axi_master",
        "slave_interface": "trecap_csr_bridge.s0",
        "exported_master_interface": "trecap_csr_bridge.m0",
        "address_units": "SYMBOLS",
        "address_width_bits": 21,
        "data_width_bits": 32,
        "symbol_width_bits": 8,
        "max_burst_size": 1,
        "max_pending_responses": 1,
        "use_auto_address_width": 0,
        "use_response": 1,
        "base_address": "0x00000000",
    },
    "ddr_bridge": {
        "instance": "trecap_f2h_sdram_bridge",
        "component_type": "altera_avalon_mm_bridge",
        "exported_slave_interface": "trecap_f2h_sdram_bridge.s0",
        "master_interface": "trecap_f2h_sdram_bridge.m0",
        "downstream": "hps_0.f2h_sdram0_data",
        "address_units": "SYMBOLS",
        "address_width_bits": 32,
        "data_width_bits": 64,
        "symbol_width_bits": 8,
        "max_burst_size": 1,
        "max_pending_responses": 1,
        "use_auto_address_width": 0,
        "use_response": 0,
        "base_address": "0x00000000",
    },
}
EXPECTED_GENERATED_META: dict[str, object] = {
    "module_name": "system",
    "instance_name": "u_platform_designer_system",
    "hdl_candidates": [path.as_posix() for path in GENERATED_HDL_RELS],
    "qip_file": QIP_REL.as_posix(),
    "sopcinfo_file": SOPCINFO_REL.as_posix(),
}
EXPECTED_INTEGRATION: dict[str, object] = {
    "wrapper_module": "platform_designer_wrapper",
    "board_top_module": "de1_soc_trecap_top",
    "board_wrapper_instance": "u_platform_designer_wrapper",
    "board_safe_idle_bus_stubs_permitted": False,
    "wrapper_system_compatibility_stub_permitted": False,
    "required_filelists": [path.as_posix() for path in FILELIST_RELS],
}
EXPECTED_EVIDENCE: dict[str, object] = {
    "source_checker": "scripts/check_platform_designer_wrapper.py",
    "human_document": DOC_REL.as_posix(),
    "schema_file": SCHEMA_REL.as_posix(),
    "default_checker_scope": "source_only",
    "generated_checker_option": "--require-generated",
    "generated_artifacts_are_local_build_products": True,
    "source_check_is_functional_verification": False,
    "source_check_is_quartus_compile_evidence": False,
    "source_check_is_hardware_signoff": False,
}
EXPECTED_RULES = [
    "Preserve every one of the 21 CSR byte-address bits and the complete Avalon response channel through the wrapper.",
    "Connect the HPS lightweight AXI manager to the exported CSR Avalon master only through trecap_csr_bridge.",
    "Connect the exported FPGA DDR Avalon slave to the HPS F2SDRAM agent only through trecap_f2h_sdram_bridge.",
    "Translate the repository 64-bit DDR byte address to the 32-bit Platform Designer byte address only after proving the address is below 0x40000000.",
    "Accept an invalid DDR write locally, return a registered SLVERR exactly one cycle later, and never forward that write to Platform Designer.",
    "Permit at most one outstanding repository write beat and block ring-writer done, producer advance, and DMA commit until the final beat receives a successful local response.",
    "For every accepted legal DDR write, propagate the generated waitrequest and return exactly one registered local OKAY as bridge-acceptance evidence only; never present it as downstream DRAM completion or error evidence.",
    "Drive the unused DDR read command low and do not fabricate a DDR read transaction.",
    "clock_reset_ctrl shall qualify KEY[0] high for 1000000 CLOCK_50 cycles, combine that qualified release with h2f_reset_n exactly once, and own canonical rst_n_platform.",
    "The board top shall consume clock_reset_ctrl.rst_n_platform_o directly and shall not instantiate a second platform-reset synchronizer or pseudo-domain resets.",
    "Use rst_n_platform to reset the wrapper-local response register, both typed Avalon bridges, and trecap_de1soc_full_top.",
    "Keep system.reset_n_reset_n scoped to clk_0 and the typed Avalon bridges; never connect it to an HPS reset sink.",
    "Instantiate the real generated module system with the complete frozen flattened ABI and no compatibility stub.",
    "Do not claim generated-system, normalized-Qsys, Quartus compile, functional verification, or hardware evidence from source checks.",
    "Require generated HDL, QIP, SOPCINFO, normalized Qsys, and exact generated module ports before the optional generated-artifact check can pass.",
]


def build_expected_abi() -> dict[str, dict[str, object]]:
    ports: dict[str, dict[str, object]] = {}

    def add(direction: str, width: int, *names: str) -> None:
        for name in names:
            if name in ports:
                raise RuntimeError(f"duplicate expected ABI port {name}")
            ports[name] = {"direction": direction, "width_bits": width}

    add(
        "input",
        1,
        "clk_50_clk",
        "reset_n_reset_n",
        "memory_oct_rzqin",
        "hps_io_hps_io_emac1_inst_RXD0",
        "hps_io_hps_io_emac1_inst_RXD1",
        "hps_io_hps_io_emac1_inst_RXD2",
        "hps_io_hps_io_emac1_inst_RXD3",
        "hps_io_hps_io_emac1_inst_RX_CTL",
        "hps_io_hps_io_emac1_inst_RX_CLK",
        "hps_io_hps_io_usb1_inst_CLK",
        "hps_io_hps_io_usb1_inst_DIR",
        "hps_io_hps_io_usb1_inst_NXT",
        "hps_io_hps_io_spim1_inst_MISO",
        "hps_io_hps_io_uart0_inst_RX",
        "trecap_csr_lw_master_readdatavalid",
        "trecap_csr_lw_master_waitrequest",
        "trecap_csr_lw_master_writeresponsevalid",
        "trecap_f2h_sdram0_read",
        "trecap_f2h_sdram0_write",
    )
    add("input", 2, "trecap_csr_lw_master_response")
    add("input", 8, "trecap_f2h_sdram0_byteenable")
    add("input", 1, "trecap_f2h_sdram0_burstcount")
    add(
        "input",
        32,
        "trecap_csr_lw_master_readdata",
        "trecap_f2h_sdram0_address",
    )
    add("input", 64, "trecap_f2h_sdram0_writedata")

    add(
        "output",
        1,
        "h2f_reset_reset_n",
        "memory_mem_ck",
        "memory_mem_ck_n",
        "memory_mem_cke",
        "memory_mem_cs_n",
        "memory_mem_ras_n",
        "memory_mem_cas_n",
        "memory_mem_we_n",
        "memory_mem_reset_n",
        "memory_mem_odt",
        "hps_io_hps_io_emac1_inst_TX_CLK",
        "hps_io_hps_io_emac1_inst_TXD0",
        "hps_io_hps_io_emac1_inst_TXD1",
        "hps_io_hps_io_emac1_inst_TXD2",
        "hps_io_hps_io_emac1_inst_TXD3",
        "hps_io_hps_io_emac1_inst_MDC",
        "hps_io_hps_io_emac1_inst_TX_CTL",
        "hps_io_hps_io_qspi_inst_SS0",
        "hps_io_hps_io_qspi_inst_CLK",
        "hps_io_hps_io_sdio_inst_CLK",
        "hps_io_hps_io_usb1_inst_STP",
        "hps_io_hps_io_spim1_inst_CLK",
        "hps_io_hps_io_spim1_inst_MOSI",
        "hps_io_hps_io_spim1_inst_SS0",
        "hps_io_hps_io_uart0_inst_TX",
        "trecap_csr_lw_master_burstcount",
        "trecap_csr_lw_master_read",
        "trecap_csr_lw_master_write",
        "trecap_f2h_sdram0_waitrequest",
        "trecap_f2h_sdram0_readdatavalid",
    )
    add("output", 3, "memory_mem_ba")
    add("output", 4, "memory_mem_dm", "trecap_csr_lw_master_byteenable")
    add("output", 15, "memory_mem_a")
    add("output", 21, "trecap_csr_lw_master_address")
    add("output", 32, "trecap_csr_lw_master_writedata")
    add("output", 64, "trecap_f2h_sdram0_readdata")

    add(
        "inout",
        1,
        "hps_io_hps_io_emac1_inst_MDIO",
        "hps_io_hps_io_qspi_inst_IO0",
        "hps_io_hps_io_qspi_inst_IO1",
        "hps_io_hps_io_qspi_inst_IO2",
        "hps_io_hps_io_qspi_inst_IO3",
        "hps_io_hps_io_sdio_inst_CMD",
        "hps_io_hps_io_sdio_inst_D0",
        "hps_io_hps_io_sdio_inst_D1",
        "hps_io_hps_io_sdio_inst_D2",
        "hps_io_hps_io_sdio_inst_D3",
        "hps_io_hps_io_usb1_inst_D0",
        "hps_io_hps_io_usb1_inst_D1",
        "hps_io_hps_io_usb1_inst_D2",
        "hps_io_hps_io_usb1_inst_D3",
        "hps_io_hps_io_usb1_inst_D4",
        "hps_io_hps_io_usb1_inst_D5",
        "hps_io_hps_io_usb1_inst_D6",
        "hps_io_hps_io_usb1_inst_D7",
        "hps_io_hps_io_i2c0_inst_SDA",
        "hps_io_hps_io_i2c0_inst_SCL",
        "hps_io_hps_io_i2c1_inst_SDA",
        "hps_io_hps_io_i2c1_inst_SCL",
        "hps_io_hps_io_gpio_inst_GPIO09",
        "hps_io_hps_io_gpio_inst_GPIO35",
        "hps_io_hps_io_gpio_inst_GPIO40",
        "hps_io_hps_io_gpio_inst_GPIO48",
        "hps_io_hps_io_gpio_inst_GPIO53",
        "hps_io_hps_io_gpio_inst_GPIO54",
        "hps_io_hps_io_gpio_inst_GPIO61",
    )
    add("inout", 4, "memory_mem_dqs", "memory_mem_dqs_n")
    add("inout", 32, "memory_mem_dq")

    if len(ports) != 94:
        raise RuntimeError(f"expected ABI inventory has {len(ports)} ports, not 94")
    return ports


EXPECTED_ABI = build_expected_abi()

EXPECTED_SYSTEM_BINDINGS: dict[str, str] = {
    "clk_50_clk": "clk_50_i",
    "reset_n_reset_n": "bridge_reset_n_i",
    "h2f_reset_reset_n": "h2f_reset_n_o",
    "trecap_csr_lw_master_address": "csr_avs_address_o",
    "trecap_csr_lw_master_burstcount": "csr_avs_burstcount_o",
    "trecap_csr_lw_master_byteenable": "csr_avs_byteenable_o",
    "trecap_csr_lw_master_read": "csr_avs_read_o",
    "trecap_csr_lw_master_readdata": "csr_avs_readdata_i",
    "trecap_csr_lw_master_readdatavalid": "csr_avs_readdatavalid_i",
    "trecap_csr_lw_master_response": "csr_avs_response_i",
    "trecap_csr_lw_master_waitrequest": "csr_avs_waitrequest_i",
    "trecap_csr_lw_master_write": "csr_avs_write_o",
    "trecap_csr_lw_master_writedata": "csr_avs_writedata_o",
    "trecap_csr_lw_master_writeresponsevalid": "csr_avs_writeresponsevalid_i",
    "trecap_f2h_sdram0_address": "pd_ddr_address",
    "trecap_f2h_sdram0_burstcount": "pd_ddr_burstcount",
    "trecap_f2h_sdram0_waitrequest": "pd_ddr_waitrequest",
    "trecap_f2h_sdram0_read": "1'b0",
    "trecap_f2h_sdram0_readdata": "pd_ddr_readdata_unused",
    "trecap_f2h_sdram0_readdatavalid": "pd_ddr_readdatavalid_unused",
    "trecap_f2h_sdram0_write": "pd_ddr_write",
    "trecap_f2h_sdram0_writedata": "avm_writedata_i",
    "trecap_f2h_sdram0_byteenable": "avm_byteenable_i",
}

EXPECTED_TCL_CONFIG: dict[str, str] = {
    "fabric_reset_bridge_internal": "clk_0.clk_reset",
    "h2f_lw_master_export_internal": "trecap_csr_bridge.m0",
    "f2h_sdram0_export_internal": "trecap_f2h_sdram_bridge.s0",
    "csr_bridge_instance": "trecap_csr_bridge",
    "csr_bridge_component_type": "altera_avalon_mm_bridge",
    "csr_bridge_slave_interface": "trecap_csr_bridge.s0",
    "csr_bridge_master_interface": "trecap_csr_bridge.m0",
    "csr_bridge_upstream_interface": "hps_0.h2f_lw_axi_master",
    "csr_bridge_connection_base_address": "0x00000000",
    "csr_bridge_address_units": "SYMBOLS",
    "csr_bridge_address_width": "21",
    "csr_bridge_data_width": "32",
    "csr_bridge_symbol_width": "8",
    "csr_bridge_max_burst_size": "1",
    "csr_bridge_max_pending_responses": "1",
    "csr_bridge_use_auto_address_width": "0",
    "csr_bridge_use_response": "1",
    "f2h_sdram_bridge_instance": "trecap_f2h_sdram_bridge",
    "f2h_sdram_bridge_component_type": "altera_avalon_mm_bridge",
    "f2h_sdram_bridge_slave_interface": "trecap_f2h_sdram_bridge.s0",
    "f2h_sdram_bridge_master_interface": "trecap_f2h_sdram_bridge.m0",
    "f2h_sdram_bridge_downstream_interface": "hps_0.f2h_sdram0_data",
    "f2h_sdram_bridge_connection_base_address": "0x00000000",
    "f2h_sdram_bridge_address_units": "SYMBOLS",
    "f2h_sdram_bridge_address_width": "32",
    "f2h_sdram_bridge_data_width": "64",
    "f2h_sdram_bridge_symbol_width": "8",
    "f2h_sdram_bridge_max_burst_size": "1",
    "f2h_sdram_bridge_max_pending_responses": "1",
    "f2h_sdram_bridge_use_auto_address_width": "0",
    "f2h_sdram_bridge_use_response": "0",
}


def add_error(errors: list[str], message: str) -> None:
    errors.append(message)


def read_bytes(root: Path, rel: Path, errors: list[str]) -> bytes:
    try:
        return (root / rel).read_bytes()
    except OSError as exc:
        add_error(errors, f"cannot read {rel}: {exc}")
        return b""


def read_text(root: Path, rel: Path, errors: list[str]) -> str:
    raw = read_bytes(root, rel, errors)
    if not raw:
        return ""
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        add_error(errors, f"{rel} is not UTF-8: {exc}")
        return ""


def load_json(root: Path, rel: Path, errors: list[str]) -> dict[str, Any]:
    text = read_text(root, rel, errors)
    if not text:
        return {}
    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        add_error(errors, f"cannot parse {rel}: {exc}")
        return {}
    if not isinstance(value, dict):
        add_error(errors, f"{rel} root must be a JSON object")
        return {}
    return value


def require_equal(
    errors: list[str], label: str, actual: object, expected: object
) -> None:
    if actual != expected:
        add_error(errors, f"{label}: expected {expected!r}, got {actual!r}")


def require_exact_mapping(
    errors: list[str], label: str, actual: object, expected: Mapping[str, object]
) -> None:
    if not isinstance(actual, Mapping):
        add_error(errors, f"{label} must be an object")
        return
    require_equal(errors, label, dict(actual), dict(expected))


def strip_sv_comments(text: str) -> str:
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
    return re.sub(r"//[^\n]*", "", text)


def compact(text: str) -> str:
    return re.sub(r"\s+", "", text)


def balanced_region(text: str, open_index: int) -> tuple[str, int] | None:
    if open_index < 0 or open_index >= len(text) or text[open_index] != "(":
        return None
    depth = 0
    for index in range(open_index, len(text)):
        char = text[index]
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                return text[open_index + 1 : index], index + 1
    return None


def extract_module_header(text: str, module_name: str) -> str | None:
    clean = strip_sv_comments(text)
    match = re.search(rf"\bmodule\s+{re.escape(module_name)}\b", clean)
    if not match:
        return None
    cursor = match.end()
    parameter_marker = re.match(r"\s*#\s*", clean[cursor:])
    if parameter_marker:
        cursor += parameter_marker.end()
        open_index = clean.find("(", cursor)
        region = balanced_region(clean, open_index)
        if region is None:
            return None
        _, cursor = region
    open_index = clean.find("(", cursor)
    region = balanced_region(clean, open_index)
    return None if region is None else region[0]


def parse_ansi_ports(header: str) -> dict[str, tuple[str, int | None]]:
    pattern = re.compile(
        r"\b(input|output|inout)\b\s*"
        r"(?:(?:wire|logic|reg|signed|unsigned)\s+)*"
        r"(?:\[\s*([^:\]]+)\s*:\s*([^\]]+)\s*\]\s*)?"
        r"([A-Za-z_][A-Za-z0-9_]*)"
    )
    ports: dict[str, tuple[str, int | None]] = {}
    for direction, msb_text, lsb_text, name in pattern.findall(header):
        width: int | None = 1
        if msb_text or lsb_text:
            try:
                msb = int(msb_text.strip(), 0)
                lsb = int(lsb_text.strip(), 0)
                width = abs(msb - lsb) + 1
            except ValueError:
                width = None
        ports[name] = (direction, width)
    return ports


def extract_instance_bindings(
    text: str, module_name: str, instance_name: str
) -> dict[str, str] | None:
    clean = strip_sv_comments(text)
    match = re.search(rf"\b{re.escape(instance_name)}\b\s*\(", clean)
    if not match:
        return None
    prefix = clean[max(0, match.start() - 800) : match.start()]
    if not re.search(rf"\b{re.escape(module_name)}\b", prefix):
        return None
    open_index = clean.find("(", match.start())
    region = balanced_region(clean, open_index)
    if region is None:
        return None
    body, _ = region
    bindings: dict[str, str] = {}
    for port_name, expression in re.findall(
        r"\.\s*([A-Za-z_][A-Za-z0-9_]*)\s*\(\s*([^()]*)\s*\)", body
    ):
        if port_name in bindings:
            return None
        bindings[port_name] = compact(expression)
    return bindings


def parse_xml(root: Path, rel: Path, errors: list[str]) -> None:
    path = root / rel
    try:
        ET.parse(path)
    except (OSError, ET.ParseError) as exc:
        add_error(errors, f"cannot parse XML {rel}: {exc}")


def check_contract_and_schema(
    contract: Mapping[str, Any], schema: Mapping[str, Any], errors: list[str]
) -> None:
    expected_keys = {
        "schema",
        "file_class",
        "project",
        "board",
        "contract_stage",
        "status",
        "implementation_state",
        "source_ownership",
        "csr_interface",
        "ddr_interface",
        "invalid_ddr_address_policy",
        "reset_policy",
        "platform_designer_graph",
        "generated_system_contract",
        "integration",
        "evidence_policy",
        "validation_rules",
    }
    require_equal(errors, "contract keys", set(contract), expected_keys)
    require_equal(errors, "contract schema", contract.get("schema"), EXPECTED_SCHEMA)
    require_equal(
        errors,
        "contract file_class",
        contract.get("file_class"),
        "[1] hand-written Step-6 interface contract",
    )
    require_equal(errors, "contract project", contract.get("project"), "T_RECAP_Phase2")
    require_equal(errors, "contract board", contract.get("board"), "de1soc")
    require_equal(errors, "contract stage", contract.get("contract_stage"), EXPECTED_STAGE)
    require_equal(errors, "contract status", contract.get("status"), EXPECTED_STATUS)
    require_exact_mapping(
        errors, "implementation_state", contract.get("implementation_state"), EXPECTED_STATE
    )
    require_exact_mapping(
        errors, "source_ownership", contract.get("source_ownership"), EXPECTED_SOURCE_OWNERSHIP
    )
    require_exact_mapping(errors, "csr_interface", contract.get("csr_interface"), EXPECTED_CSR)
    require_exact_mapping(errors, "ddr_interface", contract.get("ddr_interface"), EXPECTED_DDR)
    require_exact_mapping(
        errors,
        "invalid_ddr_address_policy",
        contract.get("invalid_ddr_address_policy"),
        EXPECTED_INVALID_DDR,
    )
    require_exact_mapping(errors, "reset_policy", contract.get("reset_policy"), EXPECTED_RESET)
    require_exact_mapping(
        errors, "platform_designer_graph", contract.get("platform_designer_graph"), EXPECTED_GRAPH
    )
    generated = contract.get("generated_system_contract")
    if not isinstance(generated, Mapping):
        add_error(errors, "generated_system_contract must be an object")
    else:
        require_equal(
            errors,
            "generated_system_contract keys",
            set(generated),
            set(EXPECTED_GENERATED_META) | {"expected_flattened_abi"},
        )
        for key, expected in EXPECTED_GENERATED_META.items():
            require_equal(errors, f"generated_system_contract.{key}", generated.get(key), expected)
        require_exact_mapping(
            errors,
            "generated_system_contract.expected_flattened_abi",
            generated.get("expected_flattened_abi"),
            EXPECTED_ABI,
        )
    require_exact_mapping(
        errors, "integration", contract.get("integration"), EXPECTED_INTEGRATION
    )
    require_exact_mapping(
        errors, "evidence_policy", contract.get("evidence_policy"), EXPECTED_EVIDENCE
    )
    require_equal(errors, "validation_rules", contract.get("validation_rules"), EXPECTED_RULES)

    require_equal(
        errors,
        "schema draft",
        schema.get("$schema"),
        "https://json-schema.org/draft/2020-12/schema",
    )
    require_equal(
        errors,
        "schema id",
        schema.get("$id"),
        "https://trecap.local/schemas/platform_designer_wrapper.schema.json",
    )
    properties = schema.get("properties")
    if not isinstance(properties, Mapping):
        add_error(errors, "schema properties must be an object")
    else:
        for name, expected in (
            ("schema", EXPECTED_SCHEMA),
            ("contract_stage", EXPECTED_STAGE),
            ("status", EXPECTED_STATUS),
        ):
            entry = properties.get(name)
            if not isinstance(entry, Mapping):
                add_error(errors, f"schema property {name} must be an object")
            else:
                require_equal(errors, f"schema const {name}", entry.get("const"), expected)


def check_wrapper(wrapper: str, errors: list[str]) -> None:
    clean = strip_sv_comments(wrapper)
    compressed = compact(clean)
    if re.search(r"\bmodule\s+system\b", clean):
        add_error(errors, f"{WRAPPER_REL} must not define a compatibility module system")
    if re.search(r"\b[A-Za-z0-9_]*_stub\b", clean):
        add_error(errors, f"{WRAPPER_REL} contains a forbidden stub identifier")

    for name, value in (
        ("CSR_ADDR_W", 21),
        ("CSR_DATA_W", 32),
        ("CSR_BYTEEN_W", 4),
        ("CSR_BURSTCOUNT_W", 1),
        ("AVMM_ADDR_W", 64),
        ("AVMM_DATA_W", 64),
        ("AVMM_BYTEEN_W", 8),
        ("AVMM_BURSTCOUNT_W", 1),
        ("PD_DDR_ADDR_W", 32),
        ("PD_DDR_BURSTCOUNT_W", 1),
    ):
        if not re.search(
            rf"parameter\s+int\s+unsigned\s+{name}\s*=\s*{value}\b", clean
        ):
            add_error(errors, f"{WRAPPER_REL} does not freeze parameter {name}={value}")

    required_compact = (
        "localparamlogic[1:0]AVMM_RESPONSE_OKAY=2'b00;",
        "localparamlogic[1:0]AVMM_RESPONSE_SLVERR=2'b10;",
        "localparamlogic[63:0]HPS_DDR_END_EXCLUSIVE=64'h0000_0000_4000_0000;",
        "assignddr_address_in_range=(avm_address_i<HPS_DDR_END_EXCLUSIVE);",
        "assignddr_address_reject=avm_write_i&&!ddr_address_in_range;",
        "assignpd_ddr_address=avm_address_i[31:0];",
        "assignpd_ddr_burstcount=avm_burstcount_i;",
        "assignpd_ddr_write=avm_write_i&&ddr_address_in_range;",
        "assignavm_waitrequest_o=ddr_address_reject?1'b0:pd_ddr_waitrequest;",
        "assignddr_write_accept=avm_write_i&&!avm_waitrequest_o;",
        "assignavm_writeresponsevalid_o=ddr_response_valid_q;",
        "assignavm_response_o=ddr_response_error_q?AVMM_RESPONSE_SLVERR:AVMM_RESPONSE_OKAY;",
        "always_ff@(posedgeclk_50_iornegedgebridge_reset_n_i)begin",
        "if(!bridge_reset_n_i)begin",
        "ddr_response_valid_q<=1'b0;",
        "ddr_response_error_q<=1'b0;",
        "ddr_response_valid_q<=ddr_write_accept;",
        "ddr_response_error_q<=ddr_write_accept&&ddr_address_reject;",
    )
    for token in required_compact:
        if token not in compressed:
            add_error(errors, f"{WRAPPER_REL} lacks required fail-closed token {token!r}")

    bindings = extract_instance_bindings(wrapper, "system", "u_platform_designer_system")
    if bindings is None:
        add_error(errors, f"{WRAPPER_REL} lacks a parseable system u_platform_designer_system")
        return
    require_equal(errors, "wrapper system port set", set(bindings), set(EXPECTED_ABI))
    for port, expression in EXPECTED_SYSTEM_BINDINGS.items():
        require_equal(errors, f"wrapper binding {port}", bindings.get(port), expression)


def check_board_top(wrapper: str, board: str, errors: list[str]) -> None:
    clean = strip_sv_comments(board)
    if re.search(r"\b[A-Za-z0-9_]*_stub\b", clean):
        add_error(errors, f"{BOARD_TOP_REL} contains a forbidden bus stub identifier")
    wrapper_header = extract_module_header(wrapper, "platform_designer_wrapper")
    if wrapper_header is None:
        add_error(errors, f"cannot parse platform_designer_wrapper module header")
        return
    wrapper_ports = set(parse_ansi_ports(wrapper_header))
    bindings = extract_instance_bindings(
        board, "platform_designer_wrapper", "u_platform_designer_wrapper"
    )
    if bindings is None:
        add_error(errors, f"{BOARD_TOP_REL} lacks a parseable wrapper instance")
        return
    require_equal(errors, "board wrapper port set", set(bindings), wrapper_ports)

    required_bindings = {
        "clk_50_i": "clk_fabric",
        "bridge_reset_n_i": "rst_n_platform",
        "h2f_reset_n_o": "h2f_reset_n",
        "csr_avs_address_o": "csr_avs_address",
        "csr_avs_read_o": "csr_avs_read",
        "csr_avs_write_o": "csr_avs_write",
        "csr_avs_writedata_o": "csr_avs_writedata",
        "csr_avs_byteenable_o": "csr_avs_byteenable",
        "csr_avs_burstcount_o": "csr_avs_burstcount",
        "csr_avs_waitrequest_i": "csr_avs_waitrequest",
        "csr_avs_readdata_i": "csr_avs_readdata",
        "csr_avs_readdatavalid_i": "csr_avs_readdatavalid",
        "csr_avs_writeresponsevalid_i": "csr_avs_writeresponsevalid",
        "csr_avs_response_i": "csr_avs_response",
        "avm_address_i": "avm_address",
        "avm_write_i": "avm_write",
        "avm_writedata_i": "avm_writedata",
        "avm_byteenable_i": "avm_byteenable",
        "avm_burstcount_i": "avm_burstcount",
        "avm_waitrequest_o": "avm_waitrequest",
        "avm_writeresponsevalid_o": "avm_writeresponsevalid",
        "avm_response_o": "avm_response",
    }
    for port, expression in required_bindings.items():
        require_equal(errors, f"board wrapper binding {port}", bindings.get(port), expression)

    clock_bindings = extract_instance_bindings(board, "clock_reset_ctrl", "u_clock_reset_ctrl")
    if clock_bindings is None:
        add_error(errors, f"{BOARD_TOP_REL} lacks a parseable clock_reset_ctrl instance")
    else:
        for port, expression in {
            "CLOCK_50": "CLOCK_50",
            "h2f_reset_n_i": "h2f_reset_n",
            "clk_fabric_o": "clk_fabric",
            "rst_n_platform_o": "rst_n_platform",
        }.items():
            require_equal(
                errors,
                f"board clock/reset binding {port}",
                clock_bindings.get(port),
                expression,
            )

    compressed = compact(clean)
    for token in (
        ".rst_n(rst_n_platform),.rst_n_sync_o(rst_n_sync_from_full_top)",
        ".SYNC_TOP_RESET_DEASSERTION(1'b0)",
    ):
        if token not in compressed:
            add_error(errors, f"{BOARD_TOP_REL} lacks reset-policy token {token!r}")
    for token in (
        "trecap_reset_sync",
        "u_platform_reset_sync",
        "reset_request_n",
        "clk_core",
        "clk_telemetry",
        "clk_hps_bridge",
        "rst_n_fabric",
        "rst_n_core",
        "rst_n_telemetry",
        "rst_n_hps_bridge",
    ):
        if token in clean:
            add_error(errors, f"{BOARD_TOP_REL} contains forbidden duplicate/pseudo reset token {token!r}")


def check_clock_reset_ctrl(source: str, errors: list[str]) -> None:
    clean = strip_sv_comments(source)
    compressed = compact(clean)
    required = (
        "parameterintunsignedBOARD_RESET_RELEASE_CYCLES=1_000_000",
        "parameterlongintunsignedFABRIC_CLK_HZ=50_000_000",
        "parameterlongintunsignedSAMPLE_TICK_HZ=48_000",
        "parameterlongintunsignedSTATUS_TICK_HZ=10",
        "parameterlongintunsignedMETRICS_TICK_HZ=30",
        "parameterlongintunsignedHEARTBEAT_TOGGLE_HZ=2",
        "assignclk_fabric_o=CLOCK_50;",
        "always_ff@(posedgeCLOCK_50ornegedgeKEY[0])begin",
        "assignplatform_async_rst_n=board_reset_release_qualified_n_q&h2f_reset_n_i;",
        "trecap_reset_sync#(.STAGES(RESET_SYNC_STAGES),.RELEASE_ON_NEGEDGE(1'b0))u_platform_reset_sync(",
        ".async_rst_n(platform_async_rst_n)",
        ".rst_n(rst_n_platform_o)",
        "assignsample_tick_sum={1'b0,sample_tick_accum_q}+SAMPLE_TICK_RATE;",
        "if(sample_tick_sum>=FABRIC_CLK_RATE)begin",
    )
    for token in required:
        if token not in compressed:
            add_error(errors, f"{CLOCK_RESET_REL} lacks canonical reset/rate token {token!r}")

    reset_sync_bindings = extract_instance_bindings(
        source, "trecap_reset_sync", "u_platform_reset_sync"
    )
    if reset_sync_bindings is None or compressed.count("trecap_reset_sync#(") != 1:
        add_error(
            errors,
            f"{CLOCK_RESET_REL} must own exactly one parseable u_platform_reset_sync instance",
        )

    for token in (
        "reset_request_n_o",
        "SAMPLE_TICK_DIV",
        "STATUS_TICK_DIV",
        "METRICS_TICK_DIV",
        "HEARTBEAT_DIV",
        "clk_core_o",
        "clk_telemetry_o",
        "clk_hps_bridge_o",
        "rst_n_fabric_o",
        "rst_n_core_o",
        "rst_n_telemetry_o",
        "rst_n_hps_bridge_o",
    ):
        if token in clean:
            add_error(errors, f"{CLOCK_RESET_REL} retains obsolete reset/divider token {token!r}")


def check_ddr_ring_writer(source: str, errors: list[str]) -> None:
    compressed = compact(strip_sv_comments(source))
    for token in (
        "assignavmm_response_error_now=avm_writeresponsevalid_i&&(avm_response_i!=2'b00);",
        "assignproducer_advance_valid=(state_q==WSTATE_COMMIT_REQ)&&!commit_sent_q&&!avmm_response_error_now&&!avmm_response_error_sticky;",
        "if(avmm_done_pulse&&!avmm_response_error_now)begin",
    ):
        if token not in compressed:
            add_error(
                errors,
                f"{DDR_RING_WRITER_REL} lacks rejected-write commit guard token {token!r}",
            )


def check_avmm_write_master(source: str, errors: list[str]) -> None:
    compressed = compact(strip_sv_comments(source))
    for token in (
        "MSTATE_WAIT_RESPONSE=2'd2",
        "assignresponse_success=CHECK_RESPONSES&&(state_q==MSTATE_WAIT_RESPONSE)&&avm_writeresponsevalid_i&&(avm_response_i==2'b00);",
        "assignresponse_unexpected=CHECK_RESPONSES&&avm_writeresponsevalid_i&&(state_q!=MSTATE_WAIT_RESPONSE);",
        "response_completes_record_q<=write_done_ok;",
        "state_q<=MSTATE_WAIT_RESPONSE;",
        "if(response_success)begin",
        "if(response_completes_record_q)beginwrite_done_pulse_o<=1'b1;",
    ):
        if token not in compressed:
            add_error(
                errors,
                f"{AVMM_WRITE_MASTER_REL} lacks response-serialized completion token {token!r}",
            )


def tcl_values(text: str, key: str) -> list[str]:
    return re.findall(rf"^\s*{re.escape(key)}\s+(\S+)\s*$", text, flags=re.MULTILINE)


def check_qsys_source(
    generator: str, config: str, qsys: str, root: Path, errors: list[str]
) -> None:
    for key, expected in EXPECTED_TCL_CONFIG.items():
        values = tcl_values(config, key)
        if expected not in values:
            add_error(
                errors,
                f"{QSYS_CONFIG_REL} lacks frozen pair {key} {expected}; observed {values}",
            )

    generator_compact = compact(generator)
    for token in (
        "setcsr_bridge[configure_avalon_mm_bridgecsr_bridge]",
        "setsdram_bridge[configure_avalon_mm_bridgef2h_sdram_bridge]",
        "add_connection_strict\"connectHPSlightweightAXImanagertotypedCSRbridge\"$csr_upstream$csr_slave",
        "add_connection_strict\"connecttypedFPGAwritebridgetoHPSSDRAMagent\"$sdram_master$sdram_downstream",
        "[::trecap_hps_config::geth2f_lw_master_export_internal]",
        "[::trecap_hps_config::getf2h_sdram0_export_internal]",
        "[::trecap_hps_config::getfabric_reset_bridge_internal]",
    ):
        if token not in generator_compact:
            add_error(errors, f"{QSYS_GENERATOR_REL} lacks bridge-graph token {token!r}")

    # The default source gate must work both before and after an intentional
    # Quartus normalization.  Only --require-generated requires the bootstrap
    # marker to be absent (enforced in check_generated below).  While the
    # checked-in bootstrap is present, pin its reset fanout explicitly so HPS
    # warm reset cannot leave Avalon transaction state alive.
    if "T_RECAP_BOOTSTRAP_QSYS_SOURCE=1" in qsys:
        for token in (
            '<connection source="clk_0.clk_reset" sink="trecap_csr_bridge.reset"',
            '<connection source="clk_0.clk_reset" sink="trecap_f2h_sdram_bridge.reset"',
        ):
            if token not in qsys:
                add_error(errors, f"{QSYS_REL} lacks coherent bridge-reset token {token!r}")
        if re.search(r'<connection\s+source="clk_0\.clk_reset"\s+sink="hps_0\.', qsys):
            add_error(
                errors,
                f"{QSYS_REL} must not feed the fabric bridge reset into an HPS reset sink",
            )
    parse_xml(root, QSYS_REL, errors)
    parse_xml(root, QSYS_BLUEPRINT_REL, errors)


def check_filelists(root: Path, errors: list[str]) -> None:
    needle = WRAPPER_REL.as_posix()
    for rel in FILELIST_RELS:
        text = read_text(root, rel, errors)
        if text and text.count(needle) != 1:
            add_error(
                errors,
                f"{rel} must contain {needle!r} exactly once; found {text.count(needle)}",
            )


def check_document(root: Path, errors: list[str]) -> None:
    text = read_text(root, DOC_REL, errors)
    for token in (
        EXPECTED_STATUS,
        "trecap_csr_bridge",
        "trecap_f2h_sdram_bridge",
        "[0x00000000,0x40000000)",
        "writeresponsevalid",
        "SLVERR",
        "asynchronous assertion",
        "synchronized deassertion",
        "u_platform_designer_system",
        "--require-generated",
        "generated_system_present = false",
        "hardware_signoff          = false",
    ):
        if token not in text:
            add_error(errors, f"{DOC_REL} lacks required contract text {token!r}")


def check_quartus_build_flow(source: str, errors: list[str]) -> None:
    source_gate = (
        'run_cmd "${PYTHON_BIN}" scripts/check_platform_designer_wrapper.py '
        '--quiet'
    )
    generation_block = 'if [[ ${SKIP_PLATFORM_GENERATE} -eq 0 ]]; then'
    evidence_block = 'wrapper_evidence_check=('

    source_pos = source.find(source_gate)
    generation_pos = source.find(generation_block)
    evidence_pos = source.find(evidence_block)
    if min(source_pos, generation_pos, evidence_pos) < 0:
        add_error(
            errors,
            f"{QUARTUS_BUILD_REL} lacks the frozen source/generate/evidence flow markers",
        )
        return
    if not source_pos < generation_pos < evidence_pos:
        add_error(
            errors,
            f"{QUARTUS_BUILD_REL} must run source gate, Platform Designer generation, "
            "then generated-ABI gate in that order",
        )
    if "--require-generated" in source[:generation_pos]:
        add_error(
            errors,
            f"{QUARTUS_BUILD_REL} must not require generated artifacts before generation",
        )
    evidence_tail = source[evidence_pos:]
    if "--require-generated" not in evidence_tail:
        add_error(
            errors,
            f"{QUARTUS_BUILD_REL} post-generation evidence gate lacks --require-generated",
        )


def check_generated(root: Path, qsys: str, errors: list[str]) -> None:
    present_hdl = [rel for rel in GENERATED_HDL_RELS if (root / rel).is_file()]
    if len(present_hdl) != 1:
        add_error(
            errors,
            "--require-generated requires exactly one generated HDL file: "
            + ", ".join(path.as_posix() for path in GENERATED_HDL_RELS)
            + f"; found {len(present_hdl)}",
        )
    for rel in (QIP_REL, SOPCINFO_REL):
        path = root / rel
        try:
            if not path.is_file() or path.stat().st_size == 0:
                add_error(errors, f"--require-generated requires nonempty {rel}")
        except OSError as exc:
            add_error(errors, f"cannot inspect generated artifact {rel}: {exc}")

    if "T_RECAP_BOOTSTRAP_QSYS_SOURCE=1" in qsys:
        add_error(
            errors,
            f"--require-generated rejects bootstrap {QSYS_REL}; run and review Quartus 20.1 normalization",
        )

    if (root / SOPCINFO_REL).is_file():
        parse_xml(root, SOPCINFO_REL, errors)

    if len(present_hdl) != 1:
        return
    rel = present_hdl[0]
    text = read_text(root, rel, errors)
    header = extract_module_header(text, "system")
    if header is None:
        add_error(errors, f"{rel} lacks a parseable module system header")
        return
    actual_ports = parse_ansi_ports(header)
    require_equal(errors, f"{rel} generated port set", set(actual_ports), set(EXPECTED_ABI))
    for name, definition in EXPECTED_ABI.items():
        expected = (str(definition["direction"]), int(definition["width_bits"]))
        require_equal(errors, f"{rel} port {name}", actual_ports.get(name), expected)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        "--repo-root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="repository root (default: parent of scripts/)",
    )
    parser.add_argument(
        "--require-generated",
        action="store_true",
        help="require Quartus-generated HDL/QIP/SOPCINFO and validate module system ABI",
    )
    parser.add_argument("--quiet", action="store_true", help="suppress success output")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = args.root.resolve()
    errors: list[str] = []

    contract = load_json(root, CONTRACT_REL, errors)
    schema = load_json(root, SCHEMA_REL, errors)
    check_contract_and_schema(contract, schema, errors)
    if contract and schema and jsonschema is not None:
        try:
            jsonschema.Draft202012Validator(schema).validate(contract)
        except jsonschema.ValidationError as exc:
            add_error(errors, f"schema validation failed: {exc.message}")
        except jsonschema.SchemaError as exc:
            add_error(errors, f"schema itself is invalid: {exc.message}")

    wrapper = read_text(root, WRAPPER_REL, errors)
    board = read_text(root, BOARD_TOP_REL, errors)
    clock_reset = read_text(root, CLOCK_RESET_REL, errors)
    logical_top = read_text(root, LOGICAL_TOP_REL, errors)
    ddr_ring_writer = read_text(root, DDR_RING_WRITER_REL, errors)
    avmm_write_master = read_text(root, AVMM_WRITE_MASTER_REL, errors)
    quartus_build = read_text(root, QUARTUS_BUILD_REL, errors)
    generator = read_text(root, QSYS_GENERATOR_REL, errors)
    config = read_text(root, QSYS_CONFIG_REL, errors)
    qsys = read_text(root, QSYS_REL, errors)

    if wrapper:
        check_wrapper(wrapper, errors)
    if wrapper and board:
        check_board_top(wrapper, board, errors)
    if clock_reset:
        check_clock_reset_ctrl(clock_reset, errors)
    if ddr_ring_writer:
        check_ddr_ring_writer(ddr_ring_writer, errors)
    if avmm_write_master:
        check_avmm_write_master(avmm_write_master, errors)
    if quartus_build:
        check_quartus_build_flow(quartus_build, errors)
    if logical_top:
        for token in (
            "input  logic [CSR_AVMM_ADDR_W-1:0]   csr_avs_address_i",
            "output logic [AVMM_ADDR_W-1:0]       avm_address_o",
            "input  logic                         avm_writeresponsevalid_i",
            "input  logic [1:0]                   avm_response_i",
        ):
            if token not in logical_top:
                add_error(errors, f"{LOGICAL_TOP_REL} lacks required bus-boundary token {token!r}")
    if generator and config and qsys:
        check_qsys_source(generator, config, qsys, root, errors)
    check_filelists(root, errors)
    check_document(root, errors)

    if args.require_generated:
        check_generated(root, qsys, errors)

    if errors:
        print("FAIL: Step-6 Platform Designer wrapper contract check", file=sys.stderr)
        for error in errors:
            print(f"  - {error}", file=sys.stderr)
        return 1

    if not args.quiet:
        scope = "source + generated ABI" if args.require_generated else "source-only"
        print(f"PASS: Step-6 Platform Designer wrapper {scope} contract")
        print(
            "Evidence boundary: no Quartus compile, functional verification, or hardware signoff is claimed."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
