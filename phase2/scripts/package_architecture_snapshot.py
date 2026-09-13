#!/usr/bin/env python3
"""Create a deterministic source snapshot for architecture implementation handoff."""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import os
import re
import stat
import sys
import unicodedata
import zipfile
from pathlib import Path


ARCHIVE_TIMESTAMP = (1980, 1, 1, 0, 0, 0)
PACKAGE_MANIFEST_NAME = "ARCHITECTURE_SNAPSHOT_MANIFEST.json"

EXCLUDED_DIRECTORY_NAMES = {
    ".cache",
    ".dash_cache",
    ".eggs",
    ".git",
    ".idea",
    ".ip",
    ".ipynb_checkpoints",
    ".matplotlib",
    ".mplconfig",
    ".mypy_cache",
    ".nox",
    ".pytest_cache",
    ".qsys_edit",
    ".ruff_cache",
    ".streamlit",
    ".tox",
    ".venv",
    ".vscode",
    "adc_work",
    "audio_work",
    "CMakeFiles",
    "ENV",
    "Testing",
    "__pycache__",
    "build",
    "coverage",
    "db",
    "dist",
    "env",
    "htmlcov",
    "incremental_db",
    "obj_dir",
    "out",
    "output_files",
    "qdb",
    "node_modules",
    "rootfs_overlay",
    "runs",
    "sdcard_image",
    "test-results",
    "test_results",
    "venv",
    "verilator_build",
}
EXCLUDED_DIRECTORY_GLOBS = {
    "*.egg-info",
}
EXCLUDED_ROOT_DIRECTORY_GLOBS = {
    "build*",
    "cmake-build-*",
    "install*",
    "simulation",
    "work*",
}
EXCLUDED_SIM_DIRECTORY_GLOBS = {
    "adc_work",
    "audio_work",
    "work*",
}
EXCLUDED_REFERENCE_BUILD_DIRECTORY_GLOBS = {
    "build*",
}
EXCLUDED_SUFFIXES = {
    ".a",
    ".bak",
    ".dll",
    ".dtb",
    ".dtbo",
    ".dylib",
    ".ekp",
    ".exe",
    ".fst",
    ".gcda",
    ".gcno",
    ".ghw",
    ".ilk",
    ".img",
    ".jdi",
    ".jic",
    ".ko",
    ".lib",
    ".log",
    ".mti",
    ".mod",
    ".o",
    ".obj",
    ".orig",
    ".pcap",
    ".pcapng",
    ".pdb",
    ".pin",
    ".pof",
    ".profdata",
    ".profraw",
    ".pyd",
    ".pyc",
    ".pyo",
    ".qar",
    ".qarlog",
    ".qdf",
    ".qdz",
    ".qmsg",
    ".qws",
    ".rbf",
    ".rej",
    ".rpt",
    ".sld",
    ".smsg",
    ".so",
    ".sof",
    ".summary",
    ".swp",
    ".swo",
    ".temp",
    ".tmp",
    ".ucdb",
    ".vcd",
    ".vvp",
    ".vlt",
    ".vpd",
    ".vstf",
    ".wic",
    ".wlf",
    ".zip",
}
EXCLUDED_FILE_NAMES = {
    ".coverage",
    ".dash_cache",
    ".env",
    ".matplotlib",
    ".mplconfig",
    ".DS_Store",
    ".git",
    "CMakeCache.txt",
    "CTestTestfile.cmake",
    "DartConfiguration.tcl",
    "Module.symvers",
    "Thumbs.db",
    "cmake_install.cmake",
    "compile_commands.json",
    "coverage.xml",
    "core",
    "desktop.ini",
    "modelsim.ini",
    "modules.order",
    "simv",
    "transcript",
}
EXCLUDED_FILE_GLOBS = {
    ".coverage.*",
    ".env.*",
    "core.[0-9]*",
    "junit*.xml",
    "test-results*.xml",
    "vgcore.*",
}
EXCLUDED_FILE_ENDINGS = {
    "~",
    ".mod.c",
    ".tar.gz",
    ".tar.xz",
}
EXCLUDED_RELATIVE_PATHS = {
    PACKAGE_MANIFEST_NAME,
    "platform/de1soc/qsys/hps_pin_assignments.tcl",
    "platform/de1soc/qsys/system.qip",
    "platform/de1soc/qsys/system.sopcinfo",
    "platform/de1soc/qsys/system.step2_staging.qsys",
    "platform/de1soc/qsys/system.step3_staging.qsys",
}
EXCLUDED_RELATIVE_PREFIXES = {
    "artifacts/telemetry_captures/",
    "platform/de1soc/qsys/system/",
}
QSYS_GENERATED_DIRECTORY_NAMES = {
    "greybox_tmp",
    "simulation",
    "submodules",
    "synthesis",
    "testbench",
}
QSYS_GENERATED_SUFFIXES = {
    ".sopcinfo",
}
AUDIO_IP_ROOT_DIRECTORY_NAMES = {
    "audio_pll",
    "audio_pll_ip",
    "codec_audio_pll",
}
AUDIO_IP_GENERATED_DIRECTORY_NAMES = {
    ".qsys_edit",
    "db",
    "incremental_db",
    "output_files",
    "simulation",
    "synthesis",
}
AUDIO_IP_GENERATED_FILE_GLOBS = {
    "*_bb.v",
    "*_bb.vhd",
    "*_inst.v",
    "*_inst.vhd",
    "*_inst.vht",
    "*.bsf",
    "*.cmp",
    "*.ppf",
    "*.sip",
    "*.spd",
}
STRUCTURAL_EMPTY_DIRECTORIES = ["artifacts/telemetry_captures/", "runs/"]

STEP1_FILES = [
    "Makefile",
    "config/profiles/README.md",
    "config/profiles/baseline_core.json",
    "config/profiles/de1soc_bram_replay.json",
    "config/profiles/de1soc_linein_demo.json",
    "config/profiles/sim_core_only.json",
    "config/profiles/telemetry_full_demo.json",
    "config/profiles/telemetry_status_only.json",
    "scripts/check_profiles.py",
    "scripts/lint.sh",
    "scripts/lint_repo_layout.py",
    "scripts/quartus/build_de1soc.sh",
    "spec/schemas/runtime_profile.schema.json",
]

STEP2_FILES = [
    "Makefile",
    "platform/de1soc/address_map/address_map.md",
    "platform/de1soc/address_map/hps_bridge_regions.json",
    "platform/de1soc/generated_notes/generated_files_readme.md",
    "platform/de1soc/qsys/generate_system.sh",
    "platform/de1soc/qsys/hps_config.tcl",
    "platform/de1soc/qsys/platform_designer.tcl",
    "platform/de1soc/qsys/presets/README.md",
    "platform/de1soc/qsys/presets/terasic_de1soc_revh_qp20_1_hps.tsv",
    "platform/de1soc/qsys/presets/terasic_de1soc_revh_qp20_1_hps_manifest.json",
    "platform/de1soc/qsys/system.qsys",
    "run_platform_designer.ps1",
    "scripts/check_hps_platform.py",
    "scripts/import_de1soc_hps_preset.py",
    "scripts/lint.sh",
    "scripts/lint_repo_layout.py",
    "scripts/package_architecture_snapshot.py",
    "scripts/quartus/build_de1soc.sh",
]

STEP3_FILES = [
    ".gitignore",
    "Makefile",
    "ci/github/quartus_smoke.yml",
    "constraints/de1soc/de1soc.qsf",
    "platform/de1soc/address_map/address_map.md",
    "platform/de1soc/generated_notes/generated_files_readme.md",
    "platform/de1soc/qsys/generate_system.sh",
    "platform/de1soc/qsys/hps_config.tcl",
    "platform/de1soc/qsys/platform_designer.tcl",
    "platform/de1soc/qsys/presets/README.md",
    "platform/de1soc/qsys/system_blueprint.xml",
    "platform/de1soc/qsys/system.qsys",
    "run_platform_designer.ps1",
    "scripts/check_hps_platform.py",
    "scripts/lint_repo_layout.py",
    "scripts/package_architecture_snapshot.py",
    "scripts/quartus/build_de1soc.sh",
    "scripts/write_platform_generation_manifest.py",
]

STEP4_FILES = [
    "Makefile",
    "ci/github/check_generated.yml",
    "ci/github/quartus_smoke.yml",
    "docs/architecture/memory_map.md",
    "platform/de1soc/address_map/address_map.md",
    "platform/de1soc/address_map/hps_bridge_regions.json",
    "platform/de1soc/address_map/sopcinfo_location.md",
    "platform/de1soc/generated_notes/generated_files_readme.md",
    "platform/de1soc/qsys/generate_system.sh",
    "platform/de1soc/qsys/hps_config.tcl",
    "platform/de1soc/qsys/system.qsys",
    "platform/de1soc/qsys/system_blueprint.xml",
    "run_platform_designer.ps1",
    "scripts/address_map_contract.py",
    "scripts/check_address_map.py",
    "scripts/check_hps_platform.py",
    "scripts/freeze_address_map.py",
    "scripts/lint.sh",
    "scripts/package_architecture_snapshot.py",
    "scripts/quartus/build_de1soc.sh",
    "scripts/write_platform_generation_manifest.py",
    "spec/schemas/hps_bridge_regions.schema.json",
    "sw/hps/config/trecap_hps_config.json",
]

STEP5_FILES = [
    "Makefile",
    "ci/github/check_generated.yml",
    "ci/github/quartus_smoke.yml",
    "docs/architecture/architecture_implementation.md",
    "docs/architecture/avalon_mm_csr_adapter.md",
    "docs/architecture/interface_contracts.md",
    "docs/architecture/memory_map.md",
    "docs/architecture/module_api.md",
    "docs/architecture/module_inventory.md",
    "filelists/quartus_de1soc.qsf.inc",
    "filelists/rtl_de1soc_full.f",
    "filelists/rtl_hps_bridge.f",
    "platform/de1soc/address_map/address_map.md",
    "platform/de1soc/address_map/avalon_csr_adapter.json",
    "platform/de1soc/generated_notes/generated_files_readme.md",
    "platform/de1soc/qsys/generate_system.sh",
    "rtl/hps_bridge/trecap_avmm_csr_adapter.sv",
    "rtl/hps_bridge/trecap_csr_bank.sv",
    "rtl/hps_bridge/trecap_hps_bridge_top.sv",
    "rtl/platform/de1soc/de1_soc_trecap_top.sv",
    "rtl/top/trecap_de1soc_full_top.sv",
    "run_platform_designer.ps1",
    "scripts/check_csr_adapter.py",
    "scripts/gen_filelists.py",
    "scripts/lint.sh",
    "scripts/lint_repo_layout.py",
    "scripts/package_architecture_snapshot.py",
    "scripts/quartus/build_de1soc.sh",
    "spec/schemas/avalon_csr_adapter.schema.json",
]

STEP6_FILES = [
    "Makefile",
    "README.md",
    "ci/github/check_generated.yml",
    "ci/github/quartus_smoke.yml",
    "constraints/de1soc/de1soc.qsf",
    "constraints/de1soc/de1soc.sdc",
    "constraints/de1soc/clocks.sdc",
    "constraints/de1soc/pin_assignments.tcl",
    "docs/architecture/architecture_implementation.md",
    "docs/architecture/avalon_mm_csr_adapter.md",
    "docs/architecture/build_order.md",
    "docs/architecture/coding_style.md",
    "docs/architecture/clock_reset_plan.md",
    "docs/architecture/dependency_rules.md",
    "docs/architecture/interface_contracts.md",
    "docs/architecture/memory_map.md",
    "docs/architecture/module_api.md",
    "docs/architecture/module_inventory.md",
    "docs/architecture/repo_architecture.md",
    "docs/architecture/platform_designer_wrapper.md",
    "docs/architecture/source_core_integration.md",
    "docs/bringup/de1_soc_connections.md",
    "docs/bringup/quartus_programming.md",
    "filelists/quartus_de1soc.qsf.inc",
    "filelists/rtl_de1soc_full.f",
    "platform/de1soc/address_map/address_map.md",
    "platform/de1soc/address_map/avalon_csr_adapter.json",
    "platform/de1soc/address_map/hps_bridge_regions.json",
    "platform/de1soc/address_map/platform_designer_wrapper.json",
    "platform/de1soc/address_map/sopcinfo_location.md",
    "platform/de1soc/generated_notes/generated_files_readme.md",
    "platform/de1soc/qsys/generate_system.sh",
    "platform/de1soc/qsys/hps_config.tcl",
    "platform/de1soc/qsys/platform_designer.tcl",
    "platform/de1soc/qsys/system.qsys",
    "platform/de1soc/qsys/system_blueprint.xml",
    "rtl/platform/de1soc/clock_reset_ctrl.sv",
    "rtl/platform/de1soc/de1_soc_trecap_top.sv",
    "rtl/platform/de1soc/platform_designer_wrapper.sv",
    "rtl/hps_bridge/trecap_ddr_ring_writer.sv",
    "rtl/top/trecap_de1soc_full_top.sv",
    "run_platform_designer.ps1",
    "scripts/address_map_contract.py",
    "scripts/check_address_map.py",
    "scripts/check_csr_adapter.py",
    "scripts/check_hps_platform.py",
    "scripts/check_platform_designer_wrapper.py",
    "scripts/gen_filelists.py",
    "scripts/lint.sh",
    "scripts/lint_repo_layout.py",
    "scripts/package_architecture_snapshot.py",
    "scripts/quartus/build_de1soc.sh",
    "scripts/windows/modelsim_compile_windows.ps1",
    "spec/schemas/avalon_csr_adapter.schema.json",
    "spec/schemas/hps_bridge_regions.schema.json",
    "spec/schemas/platform_designer_wrapper.schema.json",
]

STEP7_FILES = [
    "Makefile",
    "README.md",
    "ci/github/check_generated.yml",
    "ci/github/quartus_smoke.yml",
    "config/boards/de1soc_source_core_integration.json",
    "constraints/de1soc/clocks.sdc",
    "constraints/de1soc/de1soc.sdc",
    "docs/architecture/architecture_implementation.md",
    "docs/architecture/build_order.md",
    "docs/architecture/cdc_plan.md",
    "docs/architecture/clock_reset_plan.md",
    "docs/architecture/dependency_rules.md",
    "docs/architecture/interface_contracts.md",
    "docs/architecture/module_api.md",
    "docs/architecture/module_inventory.md",
    "docs/architecture/repo_architecture.md",
    "docs/architecture/source_core_integration.md",
    "docs/bringup/audio_linein_bringup.md",
    "docs/bringup/de1_soc_connections.md",
    "docs/bringup/quartus_programming.md",
    "filelists/quartus_de1soc.qsf.inc",
    "filelists/rtl_core.f",
    "filelists/rtl_core_plus_fft.f",
    "filelists/rtl_de1soc_full.f",
    "rtl/core/trecap_core_top.sv",
    "rtl/sources/trecap_adc_adapter.sv",
    "rtl/sources/trecap_audio_adapter.sv",
    "rtl/sources/trecap_bram_replay_source.sv",
    "rtl/sources/trecap_diagnostic_source.sv",
    "rtl/sources/trecap_source_mux.sv",
    "rtl/platform/de1soc/adc_wrapper.sv",
    "rtl/platform/de1soc/audio_codec_wrapper.sv",
    "rtl/platform/de1soc/clock_reset_ctrl.sv",
    "rtl/platform/de1soc/de1_soc_trecap_top.sv",
    "rtl/top/trecap_de1soc_full_top.sv",
    "rtl/top/trecap_source_core_integration.sv",
    "scripts/check_source_core_integration.py",
    "scripts/gen_filelists.py",
    "scripts/lint.sh",
    "scripts/lint_repo_layout.py",
    "scripts/package_architecture_snapshot.py",
    "scripts/quartus/build_de1soc.sh",
    "spec/generated/core_config.json",
    "spec/generated/csr_map.json",
    "spec/generated/interface_types.json",
    "spec/schemas/source_core_integration.schema.json",
]

STEP8_FILES = [
    "Makefile",
    "README.md",
    "ci/github/check_generated.yml",
    "ci/github/quartus_smoke.yml",
    "config/boards/core_telemetry_composition.json",
    "docs/architecture/architecture_implementation.md",
    "docs/architecture/build_order.md",
    "docs/architecture/cdc_plan.md",
    "docs/architecture/core_telemetry_composition.md",
    "docs/architecture/source_core_integration.md",
    "docs/architecture/dependency_rules.md",
    "docs/architecture/interface_contracts.md",
    "docs/architecture/module_api.md",
    "docs/architecture/module_inventory.md",
    "docs/architecture/repo_architecture.md",
    "filelists/quartus_de1soc.qsf.inc",
    "filelists/rtl_core.f",
    "filelists/rtl_core_plus_fft.f",
    "filelists/rtl_core_telemetry.f",
    "filelists/rtl_de1soc_full.f",
    "filelists/rtl_hps_bridge.f",
    "filelists/rtl_telemetry.f",
    "platform/de1soc/address_map/platform_designer_wrapper.json",
    "rtl/hps_bridge/trecap_hps_bridge_top.sv",
    "rtl/platform/de1soc/de1_soc_trecap_top.sv",
    "rtl/telemetry/trecap_metrics_packetizer.sv",
    "rtl/telemetry/trecap_packet_scheduler.sv",
    "rtl/telemetry/trecap_spec_packetizer.sv",
    "rtl/telemetry/trecap_status_packetizer.sv",
    "rtl/telemetry/trecap_telemetry_top.sv",
    "rtl/telemetry/trecap_wave_packetizer.sv",
    "rtl/top/trecap_core_telemetry_top.sv",
    "rtl/top/trecap_de1soc_full_top.sv",
    "rtl/top/trecap_source_core_integration.sv",
    "scripts/check_core_telemetry_composition.py",
    "scripts/check_generated.py",
    "scripts/gen_filelists.py",
    "scripts/lint.sh",
    "scripts/lint_repo_layout.py",
    "scripts/package_architecture_snapshot.py",
    "scripts/quartus/build_de1soc.sh",
    "scripts/windows/modelsim_compile_windows.ps1",
    "spec/schemas/core_telemetry_composition.schema.json",
]

STEP9_FILES = [
    "Makefile",
    "README.md",
    "ci/github/check_generated.yml",
    "ci/github/quartus_smoke.yml",
    "config/boards/de1soc_board_top_integration.json",
    "docs/architecture/architecture_implementation.md",
    "docs/architecture/build_order.md",
    "docs/architecture/clock_reset_plan.md",
    "docs/architecture/de1soc_board_top_integration.md",
    "docs/architecture/dependency_rules.md",
    "docs/architecture/interface_contracts.md",
    "docs/architecture/module_api.md",
    "docs/architecture/module_inventory.md",
    "docs/architecture/repo_architecture.md",
    "filelists/quartus_de1soc.qsf.inc",
    "filelists/rtl_core.f",
    "filelists/rtl_core_plus_fft.f",
    "filelists/rtl_core_telemetry.f",
    "filelists/rtl_de1soc_full.f",
    "filelists/rtl_hps_bridge.f",
    "filelists/rtl_telemetry.f",
    "rtl/platform/de1soc/adc_wrapper.sv",
    "rtl/platform/de1soc/audio_codec_wrapper.sv",
    "rtl/platform/de1soc/clock_reset_ctrl.sv",
    "rtl/platform/de1soc/de1_soc_trecap_top.sv",
    "rtl/platform/de1soc/platform_designer_wrapper.sv",
    "rtl/top/trecap_de1soc_full_top.sv",
    "rtl/top/trecap_source_core_integration.sv",
    "scripts/check_de1soc_board_top.py",
    "scripts/check_generated.py",
    "scripts/gen_filelists.py",
    "scripts/lint.sh",
    "scripts/lint_repo_layout.py",
    "scripts/package_architecture_snapshot.py",
    "scripts/quartus/build_de1soc.sh",
    "spec/schemas/de1soc_board_top_integration.schema.json",
]

STEP10_FILES = [
    "Makefile",
    "README.md",
    "ci/github/check_generated.yml",
    "ci/github/quartus_smoke.yml",
    "config/boards/core_telemetry_composition.json",
    "config/boards/de1soc_board_top_integration.json",
    "config/boards/de1soc_clock_reset_architecture.json",
    "config/profiles/README.md",
    "constraints/de1soc/clocks.sdc",
    "constraints/de1soc/de1soc.sdc",
    "constraints/de1soc/pin_assignments.tcl",
    "docs/architecture/architecture_implementation.md",
    "docs/architecture/build_order.md",
    "docs/architecture/cdc_plan.md",
    "docs/architecture/clock_reset_plan.md",
    "docs/architecture/core_telemetry_composition.md",
    "docs/architecture/de1soc_board_top_integration.md",
    "docs/architecture/dependency_rules.md",
    "docs/architecture/interface_contracts.md",
    "docs/architecture/module_api.md",
    "docs/architecture/module_inventory.md",
    "docs/architecture/platform_designer_wrapper.md",
    "docs/architecture/repo_architecture.md",
    "docs/architecture/source_core_integration.md",
    "docs/bringup/de1_soc_connections.md",
    "docs/bringup/quartus_programming.md",
    "platform/de1soc/address_map/platform_designer_wrapper.json",
    "rtl/common/reset_sync.sv",
    "rtl/platform/de1soc/adc_wrapper.sv",
    "rtl/platform/de1soc/audio_codec_wrapper.sv",
    "rtl/platform/de1soc/clock_reset_ctrl.sv",
    "rtl/platform/de1soc/de1_soc_trecap_top.sv",
    "rtl/platform/de1soc/platform_designer_wrapper.sv",
    "rtl/telemetry/trecap_packet_fifo.sv",
    "rtl/telemetry/trecap_packet_scheduler.sv",
    "rtl/telemetry/trecap_spec_packetizer.sv",
    "rtl/telemetry/trecap_status_packetizer.sv",
    "rtl/telemetry/trecap_telemetry_top.sv",
    "rtl/telemetry/trecap_wave_packetizer.sv",
    "scripts/check_core_telemetry_composition.py",
    "scripts/check_de1soc_board_top.py",
    "scripts/check_de1soc_clock_reset.py",
    "scripts/check_generated.py",
    "scripts/check_platform_designer_wrapper.py",
    "scripts/lint.sh",
    "scripts/lint_repo_layout.py",
    "scripts/package_architecture_snapshot.py",
    "scripts/quartus/build_de1soc.sh",
    "spec/schemas/core_telemetry_composition.schema.json",
    "spec/schemas/de1soc_board_top_integration.schema.json",
    "spec/schemas/de1soc_clock_reset_architecture.schema.json",
    "spec/schemas/platform_designer_wrapper.schema.json",
]

STEP11_FILES = [
    "Makefile",
    "README.md",
    "config/boards/de1soc_bram_replay_path.json",
    "config/profiles/de1soc_bram_replay.json",
    "config/profiles/telemetry_status_only.json",
    "docs/architecture/de1soc_bram_replay_path.md",
    "docs/architecture/platform_designer_wrapper.md",
    "docs/bringup/bram_replay_signoff.md",
    "filelists/quartus_de1soc.qsf.inc",
    "filelists/rtl_bram_replay_system.f",
    "filelists/rtl_core.f",
    "filelists/rtl_core_plus_fft.f",
    "filelists/rtl_core_telemetry.f",
    "filelists/rtl_de1soc_full.f",
    "filelists/rtl_hps_bridge.f",
    "filelists/rtl_telemetry.f",
    "platform/de1soc/address_map/platform_designer_wrapper.json",
    "rtl/hps_bridge/trecap_avmm_write_master.sv",
    "rtl/hps_bridge/trecap_ddr_ring_writer.sv",
    "rtl/hps_bridge/trecap_hps_bridge_top.sv",
    "rtl/platform/de1soc/de1_soc_trecap_top.sv",
    "rtl/platform/de1soc/platform_designer_wrapper.sv",
    "rtl/sources/trecap_bram_replay_source.sv",
    "rtl/top/trecap_bram_replay_e2e_supervisor.sv",
    "rtl/top/trecap_bram_replay_system_top.sv",
    "rtl/top/trecap_core_bram_replay_top.sv",
    "rtl/top/trecap_de1soc_full_top.sv",
    "rtl/top/trecap_source_core_integration.sv",
    "scripts/check_bram_replay_path.py",
    "scripts/check_de1soc_clock_reset.py",
    "scripts/check_platform_designer_wrapper.py",
    "scripts/check_source_core_integration.py",
    "scripts/gen_filelists.py",
    "scripts/gen_headers.py",
    "scripts/lint.sh",
    "scripts/lint_repo_layout.py",
    "scripts/package_architecture_snapshot.py",
    "scripts/windows/run_c0_golden_v70.ps1",
    "scripts/windows/run_step11_bram_e2e.ps1",
    "sim/README.md",
    "sim/filelists/step11_bram_e2e.f",
    "sim/tb/tb_trecap_step11_bram_e2e.sv",
    "spec/generated/gen_manifest.json",
    "spec/schemas/de1soc_bram_replay_path.schema.json",
    "spec/schemas/platform_designer_wrapper.schema.json",
]

STEP12_FILES = [
    "Makefile",
    "README.md",
    "config/boards/de1soc_bram_replay_path.json",
    "config/boards/de1soc_ddr_ring_ownership.json",
    "config/profiles/de1soc_bram_replay.json",
    "docs/architecture/architecture_implementation.md",
    "docs/architecture/build_order.md",
    "docs/architecture/de1soc_bram_replay_path.md",
    "docs/architecture/de1soc_ddr_ring_ownership.md",
    "docs/architecture/memory_map.md",
    "docs/architecture/module_api.md",
    "docs/architecture/module_inventory.md",
    "docs/bringup/ddr_ring_bringup.md",
    "docs/bringup/hps_ethernet_bringup.md",
    "docs/bringup/quartus_programming.md",
    "platform/de1soc/address_map/address_map.md",
    "platform/de1soc/address_map/hps_bridge_regions.json",
    "platform/de1soc/linux/trecap_reserved_memory.dtsi",
    "platform/de1soc/qsys/hps_config.tcl",
    "rtl/hps_bridge/trecap_avmm_write_master.sv",
    "rtl/hps_bridge/trecap_csr_bank.sv",
    "rtl/hps_bridge/trecap_csr_shadow_commit.sv",
    "rtl/hps_bridge/trecap_ddr_record_builder.sv",
    "rtl/hps_bridge/trecap_ddr_ring_writer.sv",
    "rtl/hps_bridge/trecap_hps_bridge_top.sv",
    "rtl/hps_bridge/trecap_ring_pointer_ctrl.sv",
    "scripts/check_ddr_ring_ownership.py",
    "scripts/clean_outputs.sh",
    "scripts/lint_repo_layout.py",
    "scripts/package_architecture_snapshot.py",
    "scripts/sim/check_step12_ddr_ring_model.py",
    "scripts/windows/run_step12_ddr_ring_ownership.ps1",
    "sim/README.md",
    "sim/filelists/step11_bram_e2e.f",
    "sim/filelists/step12_ddr_ring_ownership.f",
    "sim/tb/tb_trecap_step11_bram_e2e.sv",
    "sim/tb/tb_trecap_step12_ddr_ring_ownership.sv",
    "spec/generated/csr_map.json",
    "spec/generated/packet_layouts.json",
    "spec/schemas/de1soc_ddr_ring_ownership.schema.json",
    "sw/hps/config/trecap_hps_config.json",
    "sw/hps/include/ring_reader.h",
    "sw/hps/include/trecap_hps_config.h",
    "sw/hps/scripts/reserve_ddr_region_notes.md",
    "sw/hps/scripts/run_udp_streamer.sh",
    "sw/hps/src/config.c",
    "sw/hps/src/ring_reader.c",
    "sw/hps/src/trecap_udp_streamer.c",
]

STEP13_FILES = [
    "Makefile",
    "README.md",
    "config/boards/de1soc_hps_transport.json",
    "docs/architecture/architecture_implementation.md",
    "docs/architecture/build_order.md",
    "docs/architecture/de1soc_hps_transport.md",
    "docs/architecture/interface_contracts.md",
    "docs/architecture/memory_map.md",
    "docs/architecture/module_api.md",
    "docs/architecture/module_inventory.md",
    "docs/bringup/ddr_ring_bringup.md",
    "docs/bringup/hps_ethernet_bringup.md",
    "docs/bringup/quartus_programming.md",
    "platform/de1soc/address_map/hps_bridge_regions.json",
    "scripts/check_hps_transport.py",
    "scripts/lint_repo_layout.py",
    "scripts/package_architecture_snapshot.py",
    "spec/schemas/de1soc_hps_transport.schema.json",
    "sw/hps/Makefile",
    "sw/hps/config/trecap_hps_config.json",
    "sw/hps/include/command_server.h",
    "sw/hps/include/csr_map.h",
    "sw/hps/include/ring_reader.h",
    "sw/hps/include/status_patch.h",
    "sw/hps/include/trecap_hps_config.h",
    "sw/hps/include/udp_sender.h",
    "sw/hps/include/generated/trecap_csr.h",
    "sw/hps/include/generated/trecap_packet.h",
    "sw/hps/scripts/reserve_ddr_region_notes.md",
    "sw/hps/scripts/run_udp_streamer.sh",
    "sw/hps/src/command_server.c",
    "sw/hps/src/config.c",
    "sw/hps/src/csr_map.c",
    "sw/hps/src/main.c",
    "sw/hps/src/ring_reader.c",
    "sw/hps/src/status_patch.c",
    "sw/hps/src/trecap_udp_streamer.c",
    "sw/hps/src/udp_sender.c",
    "sw/hps/systemd/trecap_udp_streamer.service",
    "sw/hps/tests/test_step13_hps_transport.c",
]

STEP14_FILES = [
    "CMakeLists.txt",
    "Makefile",
    "README.md",
    "artifacts/manifests/reference_import_manifest.json",
    "ci/github/check_generated.yml",
    "config/boards/de1soc_command_path.json",
    "config/profiles/README.md",
    "config/profiles/baseline_core.json",
    "config/profiles/de1soc_bram_replay.json",
    "config/profiles/de1soc_linein_demo.json",
    "config/profiles/sim_core_only.json",
    "config/profiles/telemetry_full_demo.json",
    "config/profiles/telemetry_status_only.json",
    "docs/architecture/architecture_implementation.md",
    "docs/architecture/build_order.md",
    "docs/architecture/coding_style.md",
    "docs/architecture/de1soc_command_path.md",
    "docs/architecture/de1soc_hps_transport.md",
    "docs/architecture/de1soc_bram_replay_path.md",
    "docs/architecture/dependency_rules.md",
    "docs/architecture/generated_contracts.md",
    "docs/architecture/interface_contracts.md",
    "docs/architecture/memory_map.md",
    "docs/architecture/module_api.md",
    "docs/architecture/module_inventory.md",
    "docs/architecture/repo_architecture.md",
    "docs/bringup/bram_replay_signoff.md",
    "docs/bringup/ddr_ring_bringup.md",
    "docs/bringup/de1_soc_connections.md",
    "docs/bringup/hps_ethernet_bringup.md",
    "docs/bringup/pc_dashboard_bringup.md",
    "docs/bringup/quartus_programming.md",
    "docs/bringup/audio_linein_bringup.md",
    "platform/de1soc/address_map/address_map.md",
    "platform/de1soc/address_map/hps_bridge_regions.json",
    "platform/de1soc/qsys/hps_config.tcl",
    "platform/de1soc/qsys/system.qsys",
    "rtl/hps_bridge/trecap_ddr_ring_writer.sv",
    "rtl/hps_bridge/trecap_csr_bank.sv",
    "rtl/hps_bridge/trecap_hps_bridge_top.sv",
    "rtl/include/generated/trecap_csr_pkg.sv",
    "rtl/include/generated/trecap_core_pkg.sv",
    "rtl/include/generated/trecap_iface_pkg.sv",
    "rtl/include/generated/trecap_packet_pkg.sv",
    "rtl/platform/de1soc/de1_soc_trecap_top.sv",
    "rtl/telemetry/trecap_telemetry_top.sv",
    "rtl/top/trecap_bram_replay_system_top.sv",
    "rtl/top/trecap_bram_replay_e2e_supervisor.sv",
    "rtl/top/trecap_core_telemetry_top.sv",
    "rtl/top/trecap_de1soc_full_top.sv",
    "rtl/top/trecap_source_core_integration.sv",
    "scripts/check_bram_replay_path.py",
    "scripts/check_command_path.py",
    "scripts/check_core_telemetry_composition.py",
    "scripts/check_de1soc_clock_reset.py",
    "scripts/check_generated.py",
    "scripts/check_hps_platform.py",
    "scripts/check_hps_transport.py",
    "scripts/check_source_core_integration.py",
    "scripts/gen_headers.py",
    "scripts/lint.sh",
    "scripts/lint_repo_layout.py",
    "scripts/package_architecture_snapshot.py",
    "sim/check_step14_command_rtl.py",
    "sim/filelists/step14_command_csr.f",
    "sim/tb/tb_trecap_step12_ddr_ring_ownership.sv",
    "sim/tb/tb_trecap_step14_command_csr.sv",
    "spec/generated/csr_map.json",
    "spec/generated/gen_manifest.json",
    "spec/generated/packet_layouts.json",
    "spec/schemas/de1soc_command_path.schema.json",
    "spec/schemas/csr_map.schema.json",
    "spec/schemas/packet_layouts.schema.json",
    "spec/schemas/runtime_profile.schema.json",
    "sw/hps/Makefile",
    "sw/hps/config/trecap_hps_config.json",
    "sw/hps/include/command_bridge.h",
    "sw/hps/include/command_server.h",
    "sw/hps/include/csr_map.h",
    "sw/hps/include/generated/trecap_csr.h",
    "sw/hps/include/generated/trecap_packet.h",
    "sw/hps/include/trecap_hps_config.h",
    "sw/hps/src/command_bridge.c",
    "sw/hps/src/command_server.c",
    "sw/hps/src/config.c",
    "sw/hps/src/csr_map.c",
    "sw/hps/src/trecap_udp_streamer.c",
    "sw/hps/scripts/run_udp_streamer.sh",
    "sw/hps/tests/test_step14_command_path.c",
    "sw/pc_dashboard/generated/trecap_packet.py",
    "sw/pc_dashboard/configs/dashboard_direct_link.json",
    "sw/pc_dashboard/scripts/run_dashboard.py",
    "sw/pc_dashboard/tests/test_step14_command_client.py",
    "sw/pc_dashboard/trecap_dashboard/command_client.py",
    "sw/pc_dashboard/trecap_dashboard/config.py",
    "sw/pc_dashboard/trecap_dashboard/__init__.py",
    "sw/reference_model/generated/trecap_config.py",
    "sw/reference_model/import_manifest.json",
    "tests/test_gen_headers_csr_freeze.py",
    "tests/test_command_path_contract_freeze.py",
]

STEP15_FILES = [
    "Makefile",
    "README.md",
    "ci/github/lint.yml",
    "docs/architecture/architecture_implementation.md",
    "docs/bringup/pc_dashboard_bringup.md",
    "scripts/clean_outputs.sh",
    "scripts/package_architecture_snapshot.py",
    "sw/pc_dashboard/configs/dashboard_direct_link.json",
    "sw/pc_dashboard/scripts/run_dashboard.py",
    "sw/pc_dashboard/tests/test_step15_dashboard.py",
    "sw/pc_dashboard/trecap_dashboard/config.py",
    "sw/pc_dashboard/trecap_dashboard/dashboard.py",
    "sw/pc_dashboard/trecap_dashboard/plots.py",
    "sw/pc_dashboard/trecap_dashboard/ring_buffers.py",
    "sw/pc_dashboard/trecap_dashboard/udp_receiver.py",
]

STEP16_FILES = [
    "Makefile",
    "README.md",
    "ci/github/check_generated.yml",
    "ci/github/lint.yml",
    "ci/github/quartus_smoke.yml",
    "config/boards/de1soc_audio_linein.json",
    "config/boards/de1soc_board_top_integration.json",
    "config/boards/de1soc_clock_reset_architecture.json",
    "config/profiles/de1soc_linein_demo.json",
    "constraints/de1soc/clocks.sdc",
    "constraints/de1soc/de1soc.sdc",
    "constraints/de1soc/pin_assignments.tcl",
    "docs/architecture/architecture_implementation.md",
    "docs/architecture/build_order.md",
    "docs/architecture/cdc_plan.md",
    "docs/architecture/clock_reset_plan.md",
    "docs/architecture/de1soc_board_top_integration.md",
    "docs/architecture/dependency_rules.md",
    "docs/architecture/interface_contracts.md",
    "docs/architecture/module_api.md",
    "docs/architecture/module_inventory.md",
    "docs/architecture/repo_architecture.md",
    "docs/architecture/source_core_integration.md",
    "docs/bringup/audio_linein_bringup.md",
    "docs/bringup/de1_soc_connections.md",
    "docs/bringup/quartus_programming.md",
    "filelists/quartus_de1soc.qsf.inc",
    "filelists/rtl_bram_replay_system.f",
    "filelists/rtl_core.f",
    "filelists/rtl_core_plus_fft.f",
    "filelists/rtl_core_telemetry.f",
    "filelists/rtl_de1soc_full.f",
    "filelists/rtl_hps_bridge.f",
    "filelists/rtl_telemetry.f",
    "rtl/common/async_fifo.sv",
    "rtl/platform/de1soc/audio_codec_i2c_init.sv",
    "rtl/platform/de1soc/audio_codec_wrapper.sv",
    "rtl/platform/de1soc/audio_pll_wrapper.sv",
    "rtl/platform/de1soc/de1_soc_trecap_top.sv",
    "rtl/sources/trecap_audio_adapter.sv",
    "scripts/check_de1soc_audio_path.py",
    "scripts/check_de1soc_board_top.py",
    "scripts/check_de1soc_clock_reset.py",
    "scripts/check_generated.py",
    "scripts/check_profiles.py",
    "scripts/clean_outputs.sh",
    "scripts/gen_filelists.py",
    "scripts/lint.sh",
    "scripts/lint_repo_layout.py",
    "scripts/package_architecture_snapshot.py",
    "scripts/quartus/build_de1soc.sh",
    "scripts/sim/check_step16_audio_model.py",
    "spec/schemas/de1soc_audio_linein.schema.json",
    "spec/schemas/de1soc_board_top_integration.schema.json",
    "spec/schemas/de1soc_clock_reset_architecture.schema.json",
    "spec/schemas/runtime_profile.schema.json",
]

STEP17_FILES = [
    ".gitignore",
    "Makefile",
    "README.md",
    "ci/github/check_generated.yml",
    "ci/github/lint.yml",
    "ci/github/quartus_smoke.yml",
    "config/boards/de1soc_adc_live.json",
    "config/boards/de1soc_board_top_integration.json",
    "config/boards/de1soc_clock_reset_architecture.json",
    "config/profiles/README.md",
    "config/profiles/de1soc_adc_demo.json",
    "constraints/de1soc/clocks.sdc",
    "constraints/de1soc/de1soc.sdc",
    "docs/architecture/architecture_implementation.md",
    "docs/architecture/build_order.md",
    "docs/architecture/cdc_plan.md",
    "docs/architecture/clock_reset_plan.md",
    "docs/architecture/de1soc_board_top_integration.md",
    "docs/architecture/interface_contracts.md",
    "docs/architecture/module_api.md",
    "docs/architecture/module_inventory.md",
    "docs/architecture/repo_architecture.md",
    "docs/architecture/source_core_integration.md",
    "docs/bringup/adc_bringup.md",
    "docs/bringup/de1_soc_connections.md",
    "docs/bringup/quartus_programming.md",
    "rtl/platform/de1soc/adc_wrapper.sv",
    "rtl/platform/de1soc/de1_soc_trecap_top.sv",
    "scripts/check_de1soc_adc_path.py",
    "scripts/check_de1soc_board_top.py",
    "scripts/check_profiles.py",
    "scripts/clean_outputs.sh",
    "scripts/lint.sh",
    "scripts/lint_repo_layout.py",
    "scripts/package_architecture_snapshot.py",
    "scripts/quartus/build_de1soc.sh",
    "scripts/sim/check_step17_adc_model.py",
    "spec/schemas/de1soc_adc_live.schema.json",
    "spec/schemas/de1soc_board_top_integration.schema.json",
    "spec/schemas/de1soc_clock_reset_architecture.schema.json",
    "spec/schemas/runtime_profile.schema.json",
]


class SnapshotValidationError(RuntimeError):
    """Raised when a generated snapshot fails its internal contract."""


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def is_excluded(relative: Path) -> bool:
    relative_posix = relative.as_posix()
    # Promoted artifact directories use ZIP directory members for structure.
    # Do not package their repository-only placeholders. This rule is
    # deliberately scoped to artifacts/: sw/reference_model/.gitkeep is part of
    # the frozen imported-reference inventory and must remain byte-addressable.
    if relative.name == ".gitkeep" and relative.parts[:1] == ("artifacts",):
        return True
    if relative_posix in EXCLUDED_RELATIVE_PATHS:
        return True
    if any(relative_posix.startswith(prefix) for prefix in EXCLUDED_RELATIVE_PREFIXES):
        return True
    directory_parts = relative.parts[:-1]
    if any(part in EXCLUDED_DIRECTORY_NAMES for part in directory_parts):
        return True
    if any(
        fnmatch.fnmatchcase(part, pattern)
        for part in directory_parts
        for pattern in EXCLUDED_DIRECTORY_GLOBS
    ):
        return True
    if directory_parts and any(
        fnmatch.fnmatchcase(directory_parts[0], pattern)
        for pattern in EXCLUDED_ROOT_DIRECTORY_GLOBS
    ):
        return True
    # ModelSim/Questa work libraries are local outputs below the source-owned sim/ tree.
    if (
        len(directory_parts) >= 2
        and directory_parts[0] == "sim"
        and any(
            fnmatch.fnmatchcase(directory_parts[1], pattern)
            for pattern in EXCLUDED_SIM_DIRECTORY_GLOBS
        )
    ):
        return True
    if (
        len(directory_parts) >= 3
        and directory_parts[:2] in {("sw", "reference_model"), ("sw", "golden")}
        and any(
            fnmatch.fnmatchcase(directory_parts[2], pattern)
            for pattern in EXCLUDED_REFERENCE_BUILD_DIRECTORY_GLOBS
        )
    ):
        return True
    # Platform Designer products are generated locally; keep only the hand-written Qsys sources.
    qsys_prefix = ("platform", "de1soc", "qsys")
    if relative.parts[:3] == qsys_prefix:
        if relative.suffix.lower() in QSYS_GENERATED_SUFFIXES:
            return True
        if any(
            part in QSYS_GENERATED_DIRECTORY_NAMES
            for part in relative.parts[3:-1]
        ):
            return True
    # Preserve source-owned audio-IP descriptors such as .ip/.qip/.qsys/.tcl,
    # but omit the generated synthesis/simulation products that vendor tools
    # place below a conventional audio-PLL IP directory.
    audio_ip_root_indexes = [
        index
        for index, part in enumerate(relative.parts[:-1])
        if part.casefold() in AUDIO_IP_ROOT_DIRECTORY_NAMES
    ]
    if audio_ip_root_indexes:
        first_audio_ip_root = audio_ip_root_indexes[0]
        generated_subdirectories = relative.parts[first_audio_ip_root + 1 : -1]
        if any(
            part.casefold() in AUDIO_IP_GENERATED_DIRECTORY_NAMES
            for part in generated_subdirectories
        ):
            return True
        if any(
            fnmatch.fnmatchcase(relative.name.casefold(), pattern)
            for pattern in AUDIO_IP_GENERATED_FILE_GLOBS
        ):
            return True
    if relative.name in EXCLUDED_FILE_NAMES:
        return True
    if any(fnmatch.fnmatchcase(relative.name, pattern) for pattern in EXCLUDED_FILE_GLOBS):
        return True
    if any(relative.name.endswith(ending) for ending in EXCLUDED_FILE_ENDINGS):
        return True
    if relative.suffix.lower() in EXCLUDED_SUFFIXES:
        return True
    return False


def collect_files(root: Path, output: Path) -> list[Path]:
    files: list[Path] = []
    output_resolved = output.resolve()
    paths = sorted(root.rglob("*"), key=lambda path: path.relative_to(root).as_posix())
    for path in paths:
        relative = path.relative_to(root)
        if is_excluded(relative):
            continue
        if path.is_symlink():
            raise SnapshotValidationError(
                f"source snapshot contains a symlink: {relative.as_posix()}"
            )
        if not path.is_file():
            continue
        if path.resolve() == output_resolved:
            continue
        files.append(relative)
    return files


def zip_info(archive_name: str, mode: int) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(archive_name, date_time=ARCHIVE_TIMESTAMP)
    info.create_system = 3
    normalized_mode = 0o755 if mode & stat.S_IXUSR else 0o644
    info.external_attr = (stat.S_IFREG | normalized_mode) << 16
    info.compress_type = zipfile.ZIP_DEFLATED
    return info


def zip_directory_info(archive_name: str) -> zipfile.ZipInfo:
    if not archive_name.endswith("/"):
        archive_name += "/"
    info = zipfile.ZipInfo(archive_name, date_time=ARCHIVE_TIMESTAMP)
    info.create_system = 3
    info.external_attr = ((stat.S_IFDIR | 0o755) << 16) | 0x10
    info.compress_type = zipfile.ZIP_STORED
    return info


def validate_archive_root(archive_root: str) -> None:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", archive_root):
        raise SnapshotValidationError(
            "--archive-root must be one portable directory name containing only "
            "letters, digits, dot, underscore, or hyphen"
        )
    if archive_root in {".", ".."} or archive_root.endswith("."):
        raise SnapshotValidationError(
            "--archive-root is not a safe portable directory name"
        )


def validate_member_name(name: str, archive_root: str, *, directory: bool) -> None:
    if not name or "\x00" in name or "\\" in name or name.startswith("/"):
        raise SnapshotValidationError(f"unsafe ZIP member name: {name!r}")
    if directory != name.endswith("/"):
        raise SnapshotValidationError(f"ZIP member directory marker/type mismatch: {name!r}")

    raw_parts = name.split("/")
    if directory:
        raw_parts = raw_parts[:-1]
    if not raw_parts or raw_parts[0] != archive_root:
        raise SnapshotValidationError(
            f"ZIP member is outside archive root {archive_root!r}: {name!r}"
        )
    if any(part in {"", ".", ".."} for part in raw_parts):
        raise SnapshotValidationError(f"ZIP member has an unsafe path component: {name!r}")


def validate_archive(
    archive_path: Path,
    archive_root: str,
    file_records: list[dict[str, object]],
    manifest_data: bytes,
) -> None:
    """Validate exact members, paths, hashes, sizes, modes, and ZIP metadata."""

    manifest_name = f"{archive_root}/{PACKAGE_MANIFEST_NAME}"
    directory_names = [f"{archive_root}/{name}" for name in STRUCTURAL_EMPTY_DIRECTORIES]
    payload_names = [f"{archive_root}/{record['path']}" for record in file_records]
    expected_names = [manifest_name, *directory_names, *payload_names]

    errors: list[str] = []
    try:
        with zipfile.ZipFile(archive_path, "r") as archive:
            if archive.comment:
                errors.append("ZIP archive comment must be empty")

            infos = archive.infolist()
            actual_names = [info.filename for info in infos]
            if actual_names != expected_names:
                errors.append("ZIP member order/set does not match the canonical manifest order")
            if len(actual_names) != len(set(actual_names)):
                errors.append("ZIP contains duplicate member names")

            portable_names: dict[str, str] = {}
            for info in infos:
                try:
                    validate_member_name(info.filename, archive_root, directory=info.is_dir())
                except SnapshotValidationError as exc:
                    errors.append(str(exc))
                portable = unicodedata.normalize("NFC", info.filename.rstrip("/")).casefold()
                previous = portable_names.setdefault(portable, info.filename)
                if previous != info.filename:
                    errors.append(
                        f"ZIP contains non-portable case/Unicode-colliding names: "
                        f"{previous!r}, {info.filename!r}"
                    )

            if errors:
                raise SnapshotValidationError("\n".join(errors))

            expected_payloads = {
                f"{archive_root}/{record['path']}": record for record in file_records
            }

            for info in infos:
                name = info.filename
                unix_mode = (info.external_attr >> 16) & 0xFFFF
                file_type = stat.S_IFMT(unix_mode)
                permissions = stat.S_IMODE(unix_mode)
                if info.create_system != 3:
                    errors.append(f"{name}: ZIP origin must be Unix")
                if info.date_time != ARCHIVE_TIMESTAMP:
                    errors.append(f"{name}: non-deterministic ZIP timestamp {info.date_time!r}")
                if info.flag_bits & 0x1:
                    errors.append(f"{name}: encrypted ZIP members are forbidden")
                if info.extra:
                    errors.append(f"{name}: ZIP extra fields are forbidden")
                if info.comment:
                    errors.append(f"{name}: ZIP member comments are forbidden")

                if name == manifest_name:
                    expected_data = manifest_data
                    expected_mode = 0o644
                    expected_type = stat.S_IFREG
                    expected_compression = zipfile.ZIP_DEFLATED
                    expected_hash = sha256(expected_data)
                    expected_size = len(expected_data)
                elif name in directory_names:
                    expected_data = b""
                    expected_mode = 0o755
                    expected_type = stat.S_IFDIR
                    expected_compression = zipfile.ZIP_STORED
                    expected_hash = sha256(expected_data)
                    expected_size = 0
                else:
                    record = expected_payloads[name]
                    expected_data = None
                    expected_mode = 0o755 if record["executable"] else 0o644
                    expected_type = stat.S_IFREG
                    expected_compression = zipfile.ZIP_DEFLATED
                    expected_hash = str(record["sha256"])
                    expected_size = int(record["size_bytes"])

                if file_type != expected_type:
                    errors.append(f"{name}: unexpected ZIP file type {oct(file_type)}")
                if permissions != expected_mode:
                    errors.append(
                        f"{name}: ZIP mode {oct(permissions)} != expected {oct(expected_mode)}"
                    )
                if info.compress_type != expected_compression:
                    errors.append(
                        f"{name}: unexpected ZIP compression method {info.compress_type}"
                    )
                if info.file_size != expected_size:
                    errors.append(
                        f"{name}: ZIP size {info.file_size} != expected {expected_size}"
                    )

                try:
                    data = archive.read(info)
                except (OSError, RuntimeError, zipfile.BadZipFile) as exc:
                    errors.append(f"{name}: cannot read/CRC-check ZIP member: {exc}")
                    continue
                if expected_data is not None and data != expected_data:
                    errors.append(f"{name}: ZIP payload bytes do not match generated bytes")
                if sha256(data) != expected_hash:
                    errors.append(f"{name}: ZIP payload SHA-256 does not match manifest")
    except (OSError, zipfile.BadZipFile, zipfile.LargeZipFile) as exc:
        raise SnapshotValidationError(f"cannot validate ZIP archive {archive_path}: {exc}") from exc

    if errors:
        raise SnapshotValidationError("\n".join(errors))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--archive-root",
        help=(
            "One portable root directory name inside the ZIP. Default: "
            "T_RECAP_Phase2_R1_architecture_implementation_steps_1_<step>."
        ),
    )
    parser.add_argument(
        "--step",
        type=int,
        default=14,
        choices=(1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17),
    )
    args = parser.parse_args()

    root = args.repo_root.resolve()
    output = args.output.resolve()
    archive_root = args.archive_root or (
        f"T_RECAP_Phase2_R1_architecture_implementation_steps_1_{args.step}"
    )
    if not (root / "Makefile").is_file():
        print(f"ERROR: not a T-RECAP repository: {root}", file=sys.stderr)
        return 2
    try:
        validate_archive_root(archive_root)
    except SnapshotValidationError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    required = list(STEP1_FILES)
    if args.step >= 2:
        required.extend(STEP2_FILES)
    if args.step >= 3:
        required.extend(STEP3_FILES)
    if args.step >= 4:
        required.extend(STEP4_FILES)
    if args.step >= 5:
        required.extend(STEP5_FILES)
    if args.step >= 6:
        required.extend(STEP6_FILES)
    if args.step >= 7:
        required.extend(STEP7_FILES)
    if args.step >= 8:
        required.extend(STEP8_FILES)
    if args.step >= 9:
        required.extend(STEP9_FILES)
    if args.step >= 10:
        required.extend(STEP10_FILES)
    if args.step >= 11:
        required.extend(STEP11_FILES)
    if args.step >= 12:
        required.extend(STEP12_FILES)
    if args.step >= 13:
        required.extend(STEP13_FILES)
    if args.step >= 14:
        required.extend(STEP14_FILES)
    if args.step >= 15:
        required.extend(STEP15_FILES)
    if args.step >= 16:
        required.extend(STEP16_FILES)
    if args.step >= 17:
        required.extend(STEP17_FILES)
    missing = [name for name in required if not (root / name).is_file()]
    if missing:
        print(f"ERROR: milestone files are missing: {missing}", file=sys.stderr)
        return 1

    try:
        files = collect_files(root, output)
    except (OSError, SnapshotValidationError) as exc:
        print(f"ERROR: cannot collect source snapshot: {exc}", file=sys.stderr)
        return 1
    file_records: list[dict[str, object]] = []
    payloads: list[tuple[Path, bytes, int]] = []
    try:
        for relative in files:
            path = root / relative
            data = path.read_bytes()
            mode = path.stat().st_mode
            payloads.append((relative, data, mode))
            file_records.append(
                {
                    "path": relative.as_posix(),
                    "size_bytes": len(data),
                    "sha256": sha256(data),
                    "executable": bool(mode & stat.S_IXUSR),
                }
            )
    except OSError as exc:
        print(f"ERROR: cannot read source snapshot payload: {exc}", file=sys.stderr)
        return 1

    address_map_freeze = None
    if args.step >= 4:
        try:
            address_source = json.loads(
                (root / "platform/de1soc/address_map/hps_bridge_regions.json").read_text(
                    encoding="utf-8"
                )
            )
            address_map_freeze = address_source["address_map_freeze"]
        except (OSError, KeyError, TypeError, json.JSONDecodeError) as exc:
            print(
                f"ERROR: cannot load Step-4 address-map freeze for package manifest: {exc}",
                file=sys.stderr,
            )
            return 1

    csr_adapter_contract = None
    if args.step >= 5:
        try:
            csr_adapter_contract = json.loads(
                (root / "platform/de1soc/address_map/avalon_csr_adapter.json").read_text(
                    encoding="utf-8"
                )
            )
        except (OSError, TypeError, json.JSONDecodeError) as exc:
            print(
                f"ERROR: cannot load Step-5 Avalon-MM CSR adapter contract for package manifest: {exc}",
                file=sys.stderr,
            )
            return 1

    platform_designer_wrapper_contract = None
    if args.step >= 6:
        try:
            platform_designer_wrapper_contract = json.loads(
                (
                    root
                    / "platform/de1soc/address_map/platform_designer_wrapper.json"
                ).read_text(encoding="utf-8")
            )
        except (OSError, TypeError, json.JSONDecodeError) as exc:
            print(
                "ERROR: cannot load Step-6 Platform Designer wrapper contract for "
                f"package manifest: {exc}",
                file=sys.stderr,
            )
            return 1

    source_core_integration_contract = None
    if args.step >= 7:
        try:
            source_core_integration_contract = json.loads(
                (
                    root
                    / "config/boards/de1soc_source_core_integration.json"
                ).read_text(encoding="utf-8")
            )
        except (OSError, TypeError, json.JSONDecodeError) as exc:
            print(
                "ERROR: cannot load Step-7 source-to-core integration contract for "
                f"package manifest: {exc}",
                file=sys.stderr,
            )
            return 1

    core_telemetry_composition_contract = None
    if args.step >= 8:
        try:
            core_telemetry_composition_contract = json.loads(
                (
                    root
                    / "config/boards/core_telemetry_composition.json"
                ).read_text(encoding="utf-8")
            )
        except (OSError, TypeError, json.JSONDecodeError) as exc:
            print(
                "ERROR: cannot load Step-8 core + telemetry composition contract for "
                f"package manifest: {exc}",
                file=sys.stderr,
            )
            return 1

    de1soc_board_top_contract = None
    if args.step >= 9:
        try:
            de1soc_board_top_contract = json.loads(
                (
                    root
                    / "config/boards/de1soc_board_top_integration.json"
                ).read_text(encoding="utf-8")
            )
        except (OSError, TypeError, json.JSONDecodeError) as exc:
            print(
                "ERROR: cannot load Step-9 DE1-SoC board-top integration contract for "
                f"package manifest: {exc}",
                file=sys.stderr,
            )
            return 1

    de1soc_clock_reset_architecture_contract = None
    if args.step >= 10:
        try:
            de1soc_clock_reset_architecture_contract = json.loads(
                (
                    root
                    / "config/boards/de1soc_clock_reset_architecture.json"
                ).read_text(encoding="utf-8")
            )
        except (OSError, TypeError, json.JSONDecodeError) as exc:
            print(
                "ERROR: cannot load Step-10 DE1-SoC clock/reset architecture contract for "
                f"package manifest: {exc}",
                file=sys.stderr,
            )
            return 1

    de1soc_bram_replay_path_contract = None
    if args.step >= 11:
        try:
            de1soc_bram_replay_path_contract = json.loads(
                (
                    root
                    / "config/boards/de1soc_bram_replay_path.json"
                ).read_text(encoding="utf-8")
            )
        except (OSError, TypeError, json.JSONDecodeError) as exc:
            print(
                "ERROR: cannot load Step-11 DE1-SoC BRAM replay path contract for "
                f"package manifest: {exc}",
                file=sys.stderr,
            )
            return 1

    de1soc_ddr_ring_ownership_contract = None
    if args.step >= 12:
        try:
            de1soc_ddr_ring_ownership_contract = json.loads(
                (
                    root
                    / "config/boards/de1soc_ddr_ring_ownership.json"
                ).read_text(encoding="utf-8")
            )
        except (OSError, TypeError, json.JSONDecodeError) as exc:
            print(
                "ERROR: cannot load Step-12 DE1-SoC DDR ring ownership contract for "
                f"package manifest: {exc}",
                file=sys.stderr,
            )
            return 1

    de1soc_hps_transport_contract = None
    if args.step >= 13:
        try:
            de1soc_hps_transport_contract = json.loads(
                (
                    root
                    / "config/boards/de1soc_hps_transport.json"
                ).read_text(encoding="utf-8")
            )
        except (OSError, TypeError, json.JSONDecodeError) as exc:
            print(
                "ERROR: cannot load Step-13 DE1-SoC HPS transport contract for "
                f"package manifest: {exc}",
                file=sys.stderr,
            )
            return 1

    de1soc_command_path_contract = None
    if args.step >= 14:
        try:
            de1soc_command_path_contract = json.loads(
                (
                    root
                    / "config/boards/de1soc_command_path.json"
                ).read_text(encoding="utf-8")
            )
        except (OSError, TypeError, json.JSONDecodeError) as exc:
            print(
                "ERROR: cannot load Step-14 DE1-SoC command-path contract for "
                f"package manifest: {exc}",
                file=sys.stderr,
            )
            return 1

    de1soc_audio_linein_contract = None
    if args.step >= 16:
        try:
            de1soc_audio_linein_contract = json.loads(
                (
                    root
                    / "config/boards/de1soc_audio_linein.json"
                ).read_text(encoding="utf-8")
            )
        except (OSError, TypeError, json.JSONDecodeError) as exc:
            print(
                "ERROR: cannot load Step-16 DE1-SoC LINE-IN audio contract for "
                f"package manifest: {exc}",
                file=sys.stderr,
            )
            return 1

    de1soc_adc_live_contract = None
    if args.step >= 17:
        try:
            de1soc_adc_live_contract = json.loads(
                (
                    root
                    / "config/boards/de1soc_adc_live.json"
                ).read_text(encoding="utf-8")
            )
        except (OSError, TypeError, json.JSONDecodeError) as exc:
            print(
                "ERROR: cannot load Step-17 DE1-SoC live-ADC contract for "
                f"package manifest: {exc}",
                file=sys.stderr,
            )
            return 1

    step_9_audio_scope = (
        "Step 16 supersedes the original best-effort mailbox and inactive AUD_XCK "
        "with dual audio asynchronous FIFOs and a PLL-generated, lock-qualified "
        "12.288 MHz codec master clock. "
        if args.step >= 16
        else (
            "The best-effort audio monitor may still drop samples while busy, and "
            "AUD_XCK remains unconditionally zero with no enable-able debug divider. "
        )
    )
    step_10_audio_scope = (
        "Step 16 adds the source-level codec-clock PLL, lock-qualified codec setup, "
        "and FIFO-based audio CDC while retaining CLOCK_50 as the sole fabric/core "
        "clock; external audio timing constraints and measured board evidence remain "
        "pending. "
        if args.step >= 16
        else "Live audio PLL/codec timing remains excluded and pending. "
    )

    manifest = {
        "schema": "trecap_architecture_source_snapshot_v1",
        "file_class": "[2] generated package manifest - do not edit",
        "milestone": f"architecture_implementation_step_{args.step}",
        "scope": (
            "Complete repository source-tree snapshot through the selected architecture "
            "milestone. The enumerated exclusion policy removes known local caches, run/build "
            "outputs, vendor-generated Platform Designer products, simulator outputs, logs, "
            "and archive dumps."
        ),
        "evidence_boundary": (
            "No accepted tool-produced run evidence is packaged. Historical hand-written notes, "
            "runner scripts, testbench sources, and frozen reference-model artifacts are source "
            "context, not RTL compile, simulation, Platform Designer generation, Quartus/timing, "
            "or hardware-signoff evidence."
        ),
        "contains_step_1_configuration_profiles": True,
        "contains_step_2_frozen_platform_designer_hps_configuration": args.step >= 2,
        "contains_step_3_platform_designer_generation_flow": args.step >= 3,
        "contains_step_4_source_frozen_address_map": args.step >= 4,
        "contains_step_5_avalon_mm_csr_adapter_source": args.step >= 5,
        "contains_step_6_platform_designer_wrapper_source": args.step >= 6,
        "contains_step_7_source_to_core_integration_source": args.step >= 7,
        "contains_step_8_core_telemetry_composition_source": args.step >= 8,
        "contains_step_9_de1soc_board_top_source": args.step >= 9,
        "contains_step_10_clock_reset_architecture_source": args.step >= 10,
        "contains_step_11_bram_replay_path_source": args.step >= 11,
        "contains_step_12_ddr_ring_ownership_source": args.step >= 12,
        "contains_step_12_linux_reserved_memory_dtsi_source": args.step >= 12,
        "contains_step_13_hps_transport_source": args.step >= 13,
        "contains_step_13_host_transport_test_source": args.step >= 13,
        "contains_step_14_command_v2_source": args.step >= 14,
        "contains_step_14_command_result_source": args.step >= 14,
        "contains_step_14_command_bridge_source": args.step >= 14,
        "contains_step_14_hps_host_test_source": args.step >= 14,
        "contains_step_14_pc_host_test_source": args.step >= 14,
        "contains_step_14_rtl_structural_model_checker_source": args.step >= 14,
        "contains_step_14_directed_rtl_testbench_source": args.step >= 14,
        "contains_step_15_pc_dashboard_source": args.step >= 15,
        "contains_step_15_host_test_source": args.step >= 15,
        "contains_step_15_spectrogram_source": args.step >= 15,
        "contains_step_15_live_command_controls_source": args.step >= 15,
        "contains_step_16_audio_pll_source": args.step >= 16,
        "contains_step_16_codec_i2c_initializer_source": args.step >= 16,
        "contains_step_16_i2s_rx_tx_source": args.step >= 16,
        "contains_step_16_audio_async_fifo_cdc_source": args.step >= 16,
        "contains_step_16_audio_overflow_underflow_counter_source": args.step >= 16,
        "contains_step_16_linein_profile_source": args.step >= 16,
        "contains_step_16_source_checker": args.step >= 16,
        "contains_step_16_dependency_free_behavioral_model_source": args.step >= 16,
        "contains_step_16_native_rtl_testbench_source": False,
        "contains_step_17_ltc2308_protocol_wrapper_source": args.step >= 17,
        "contains_step_17_adc_dout_cdc_source": args.step >= 17,
        "contains_step_17_adc_source_mux_integration_source": args.step >= 17,
        "contains_step_17_adc_profile_source": args.step >= 17,
        "contains_step_17_source_checker": args.step >= 17,
        "contains_step_17_dependency_free_behavioral_model_source": args.step >= 17,
        "contains_step_17_native_rtl_testbench_source": False,
        "step_6_is_source_only": args.step >= 6,
        "step_7_is_source_only": args.step >= 7,
        "step_8_is_source_only": args.step >= 8,
        "step_9_is_source_only": args.step >= 9,
        "step_10_is_source_only": args.step >= 10,
        "step_11_is_source_only": args.step >= 11,
        "step_12_is_source_only": args.step >= 12,
        "step_13_is_source_only": args.step >= 13,
        "step_14_is_source_only": args.step >= 14,
        "step_15_is_source_only": args.step >= 15,
        "step_16_is_source_only": args.step >= 16,
        "step_17_is_source_only": args.step >= 17,
        "contains_platform_designer_generated_artifacts": False,
        "contains_platform_designer_generation_evidence": False,
        "contains_rtl_compile_evidence": False,
        "contains_quartus_compile_evidence": False,
        # The cumulative repository already contains earlier C0 simulation/testbench sources.
        # Steps 7 through 10 deliberately add no new functional-verification implementation/evidence.
        "contains_functional_verification_implementation": any(
            record["path"].startswith("sim/") for record in file_records
        ),
        "contains_preexisting_c0_functional_verification_sources": any(
            record["path"].startswith("sim/") for record in file_records
        ),
        "contains_step_7_functional_verification_implementation": False,
        "contains_step_7_rtl_compile_evidence": False,
        "contains_step_7_quartus_compile_evidence": False,
        "contains_step_8_functional_verification_implementation": False,
        "contains_step_8_rtl_compile_evidence": False,
        "contains_step_8_quartus_compile_evidence": False,
        "contains_step_9_functional_verification_implementation": False,
        "contains_step_9_rtl_compile_evidence": False,
        "contains_step_9_platform_designer_generation_evidence": False,
        "contains_step_9_quartus_compile_evidence": False,
        "contains_step_9_hardware_evidence": False,
        "contains_step_10_functional_verification_implementation": False,
        "contains_step_10_rtl_compile_evidence": False,
        "contains_step_10_platform_designer_generation_evidence": False,
        "contains_step_10_quartus_compile_evidence": False,
        "contains_step_10_timing_closure_evidence": False,
        "contains_step_10_hardware_evidence": False,
        "contains_step_11_functional_verification_implementation": args.step >= 11,
        "contains_step_11_bram_replay_e2e_testbench_source": args.step >= 11,
        "contains_step_11_rtl_compile_evidence": False,
        "contains_step_11_functional_verification_evidence": False,
        "contains_step_11_platform_designer_generation_evidence": False,
        "contains_step_11_quartus_compile_evidence": False,
        "contains_step_11_hps_runtime_evidence": False,
        "contains_step_11_hardware_evidence": False,
        "contains_step_12_functional_verification_implementation": args.step >= 12,
        "contains_step_12_ddr_ring_ownership_testbench_source": args.step >= 12,
        "contains_step_12_rtl_compile_evidence": False,
        "contains_step_12_functional_verification_evidence": False,
        "contains_step_12_linux_dtb_evidence": False,
        "contains_step_12_linux_runtime_evidence": False,
        "contains_step_12_hps_runtime_evidence": False,
        "contains_step_12_hardware_evidence": False,
        "contains_step_13_host_test_execution_evidence": False,
        "contains_step_13_active_reserved_memory_runtime_evidence": False,
        "contains_step_13_csr_mmap_runtime_evidence": False,
        "contains_step_13_reserved_ddr_mmap_runtime_evidence": False,
        "contains_step_13_linux_runtime_evidence": False,
        "contains_step_13_network_runtime_evidence": False,
        "contains_step_13_systemd_runtime_evidence": False,
        "contains_step_13_quartus_compile_evidence": False,
        "contains_step_13_hardware_evidence": False,
        "contains_step_14_host_test_execution_evidence": False,
        "contains_step_14_pc_hps_udp_runtime_evidence": False,
        "contains_step_14_hps_linux_runtime_evidence": False,
        "contains_step_14_csr_mmap_runtime_evidence": False,
        "contains_step_14_lightweight_bridge_runtime_evidence": False,
        "contains_step_14_fpga_command_application_evidence": False,
        "contains_step_14_bram_replay_runtime_evidence": False,
        "contains_step_14_rtl_compile_evidence": False,
        "contains_step_14_rtl_simulation_evidence": False,
        "contains_step_14_platform_designer_generation_evidence": False,
        "contains_step_14_quartus_compile_evidence": False,
        "contains_step_14_timing_closure_evidence": False,
        "contains_step_14_hardware_evidence": False,
        "contains_step_15_host_test_execution_evidence": False,
        "contains_step_15_live_udp_runtime_evidence": False,
        "contains_step_15_gui_runtime_evidence": False,
        "contains_step_15_gui_soak_evidence": False,
        "contains_step_15_hps_fpga_runtime_evidence": False,
        "contains_step_15_hardware_evidence": False,
        "contains_step_16_native_rtl_compile_evidence": False,
        "contains_step_16_native_rtl_simulation_evidence": False,
        "contains_step_16_platform_designer_generation_evidence": False,
        "contains_step_16_quartus_compile_evidence": False,
        "contains_step_16_timequest_timing_closure_evidence": False,
        "contains_step_16_pll_frequency_measurement_evidence": False,
        "contains_step_16_pll_lock_measurement_evidence": False,
        "contains_step_16_codec_i2c_ack_evidence": False,
        "contains_step_16_bclk_lrck_measurement_evidence": False,
        "contains_step_16_live_audio_evidence": False,
        "contains_step_16_hardware_evidence": False,
        "contains_step_17_native_rtl_compile_evidence": False,
        "contains_step_17_native_rtl_simulation_evidence": False,
        "contains_step_17_platform_designer_generation_evidence": False,
        "contains_step_17_quartus_compile_evidence": False,
        "contains_step_17_timequest_timing_closure_evidence": False,
        "contains_step_17_post_fit_io_timing_measurement_evidence": False,
        "contains_step_17_serial_timing_measurement_evidence": False,
        "contains_step_17_sampling_rate_measurement_evidence": False,
        "contains_step_17_analog_characterization_evidence": False,
        "contains_step_17_live_adc_evidence": False,
        "contains_step_17_hardware_evidence": False,
        "contains_functional_verification_evidence": False,
        "contains_hardware_evidence": False,
        "contains_hardware_address_map_signoff": False,
        "contains_hardware_board_connectivity_evidence": False,
        "address_map_contract_stage": (
            "step4_address_map_source_frozen" if args.step >= 4 else None
        ),
        "address_map_hardware_evidence_status": (
            "source_frozen_reserved_memory_dtsi_present_pending_dtb_boot_sopcinfo_and_board_signoff"
            if args.step >= 12
            else (
                "source_frozen_pending_sopcinfo_linux_reservation_and_board_revision_signoff"
                if args.step >= 4
                else None
            )
        ),
        "address_map_freeze": address_map_freeze,
        "csr_adapter_contract_stage": (
            "step5_avalon_mm_csr_adapter_source_implemented" if args.step >= 5 else None
        ),
        "csr_adapter_hardware_evidence_status": (
            csr_adapter_contract.get("status")
            if args.step >= 5
            else None
        ),
        "csr_adapter_contract": csr_adapter_contract,
        "platform_designer_wrapper_contract_stage": (
            platform_designer_wrapper_contract.get("contract_stage")
            if args.step >= 6
            else None
        ),
        "platform_designer_wrapper_contract_status": (
            platform_designer_wrapper_contract.get("status")
            if args.step >= 6
            else None
        ),
        "platform_designer_wrapper_source_status": (
            platform_designer_wrapper_contract.get("status")
            if args.step >= 6
            else None
        ),
        "platform_designer_wrapper_evidence_status": (
            "absent_source_only_milestone" if args.step >= 6 else None
        ),
        "platform_designer_wrapper_contract": platform_designer_wrapper_contract,
        "source_core_integration_contract_stage": (
            source_core_integration_contract.get("contract_stage")
            if args.step >= 7
            else None
        ),
        "source_core_integration_contract_status": (
            source_core_integration_contract.get("status")
            if args.step >= 7
            else None
        ),
        "source_core_integration_evidence_status": (
            "absent_source_only_milestone" if args.step >= 7 else None
        ),
        "source_core_integration_contract": source_core_integration_contract,
        "core_telemetry_composition_contract_stage": (
            core_telemetry_composition_contract.get("contract_stage")
            if args.step >= 8
            else None
        ),
        "core_telemetry_composition_contract_status": (
            core_telemetry_composition_contract.get("status")
            if args.step >= 8
            else None
        ),
        "core_telemetry_composition_evidence_status": (
            "absent_source_only_milestone" if args.step >= 8 else None
        ),
        "core_telemetry_composition_contract": core_telemetry_composition_contract,
        "de1soc_board_top_contract_stage": (
            de1soc_board_top_contract.get("contract_stage")
            if args.step >= 9
            else None
        ),
        "de1soc_board_top_contract_status": (
            de1soc_board_top_contract.get("status")
            if args.step >= 9
            else None
        ),
        "de1soc_board_top_evidence_status": (
            "absent_source_only_milestone" if args.step >= 9 else None
        ),
        "de1soc_board_top_contract": de1soc_board_top_contract,
        "de1soc_clock_reset_architecture_contract_stage": (
            de1soc_clock_reset_architecture_contract.get("contract_stage")
            if args.step >= 10
            else None
        ),
        "de1soc_clock_reset_architecture_contract_status": (
            de1soc_clock_reset_architecture_contract.get("status")
            if args.step >= 10
            else None
        ),
        "de1soc_clock_reset_architecture_evidence_status": (
            "absent_source_only_milestone" if args.step >= 10 else None
        ),
        "de1soc_clock_reset_architecture_contract": (
            de1soc_clock_reset_architecture_contract
        ),
        "de1soc_bram_replay_path_contract_stage": (
            de1soc_bram_replay_path_contract.get("contract_stage")
            if args.step >= 11
            else None
        ),
        "de1soc_bram_replay_path_contract_status": (
            de1soc_bram_replay_path_contract.get("status")
            if args.step >= 11
            else None
        ),
        "de1soc_bram_replay_path_evidence_status": (
            "testbench_source_present_execution_evidence_absent"
            if args.step >= 11
            else None
        ),
        "de1soc_bram_replay_path_contract": de1soc_bram_replay_path_contract,
        "de1soc_ddr_ring_ownership_contract_stage": (
            de1soc_ddr_ring_ownership_contract.get("contract_stage")
            if args.step >= 12
            else None
        ),
        "de1soc_ddr_ring_ownership_contract_status": (
            de1soc_ddr_ring_ownership_contract.get("status")
            if args.step >= 12
            else None
        ),
        "de1soc_ddr_ring_ownership_evidence_status": (
            "testbench_and_dtsi_source_present_execution_dtb_boot_and_hardware_evidence_absent"
            if args.step >= 12
            else None
        ),
        "de1soc_ddr_ring_ownership_contract": de1soc_ddr_ring_ownership_contract,
        "de1soc_hps_transport_contract_stage": (
            de1soc_hps_transport_contract.get("contract_stage")
            if args.step >= 13
            else None
        ),
        "de1soc_hps_transport_contract_status": (
            de1soc_hps_transport_contract.get("status")
            if args.step >= 13
            else None
        ),
        "de1soc_hps_transport_evidence_status": (
            "host_test_source_present_execution_evidence_not_packaged_hps_linux_network_systemd_and_hardware_evidence_absent"
            if args.step >= 13
            else None
        ),
        "de1soc_hps_transport_contract": de1soc_hps_transport_contract,
        "de1soc_command_path_contract_stage": (
            de1soc_command_path_contract.get("contract_stage")
            if args.step >= 14
            else None
        ),
        "de1soc_command_path_contract_status": (
            de1soc_command_path_contract.get("status")
            if args.step >= 14
            else None
        ),
        "de1soc_command_path_evidence_status": (
            "source_and_host_test_sources_present_execution_not_packaged_live_pc_hps_bridge_fpga_quartus_and_hardware_evidence_absent"
            if args.step >= 14
            else None
        ),
        "de1soc_command_path_contract": de1soc_command_path_contract,
        "de1soc_audio_linein_contract_stage": (
            de1soc_audio_linein_contract.get("contract_stage")
            if args.step >= 16
            else None
        ),
        "de1soc_audio_linein_contract_status": (
            de1soc_audio_linein_contract.get("status")
            if args.step >= 16
            else None
        ),
        "de1soc_audio_linein_evidence_status": (
            "source_checker_and_dependency_free_model_present_execution_outputs_not_"
            "packaged_rtl_compile_native_simulation_quartus_timequest_pll_clock_i2c_"
            "ack_live_audio_and_hardware_evidence_absent"
            if args.step >= 16
            else None
        ),
        "de1soc_audio_linein_contract": de1soc_audio_linein_contract,
        "de1soc_adc_live_contract_stage": (
            de1soc_adc_live_contract.get("contract_stage")
            if args.step >= 17
            else None
        ),
        "de1soc_adc_live_contract_status": (
            de1soc_adc_live_contract.get("status")
            if args.step >= 17
            else None
        ),
        "de1soc_adc_live_evidence_status": (
            "source_checker_and_dependency_free_model_present_execution_outputs_not_"
            "packaged_native_rtl_compile_simulation_platform_designer_quartus_timequest_"
            "post_fit_io_serial_rate_analog_live_adc_and_hardware_evidence_absent"
            if args.step >= 17
            else None
        ),
        "de1soc_adc_live_contract": de1soc_adc_live_contract,
        "step_3_scope": (
            "Platform Designer lifecycle/orchestration source only; no fabricated vendor "
            "outputs, typed RTL wrapper, Quartus project, or functional verification."
            if args.step >= 3
            else None
        ),
        "step_4_scope": (
            "Source-frozen address-map contract, schema, mirrors, generation/build gates, "
            "and SOPCINFO evidence policy only. Hardware signoff remains pending until "
            "vendor-generated SOPCINFO, Linux reserved-memory, HPS boot-remap, and board "
            "revision evidence pass their dedicated gates."
            if args.step >= 4
            else None
        ),
        "step_5_scope": (
            "Hand-written Avalon-MM CSR agent, private CSR-leaf integration, full 21-bit-to-12-bit "
            "byte-address decode, strict 32-bit/single-beat access policy, deterministic response "
            "mapping, hierarchy propagation, source-contract gate, and documentation. Platform "
            "Designer AXI-to-Avalon graph integration, generated wrapper, Quartus compile, "
            "SOPCINFO reachability proof, hardware evidence, and functional verification remain "
            "pending."
            if args.step >= 5
            else None
        ),
        "step_6_scope": (
            "Hand-written class-[1] typed Platform Designer boundary wrapper, board-top CSR/DDR "
            "source wiring, reviewed Platform Designer source-graph/interface contract, "
            "source-consistency checker, and build/lint/CI/package integration. Vendor-generated "
            "Platform Designer HDL, QIP, SOPCINFO, Quartus compile evidence, functional "
            "verification, physical-board evidence, and hardware signoff remain excluded and "
            "pending."
            if args.step >= 6
            else None
        ),
        "step_7_scope": (
            "Hand-written source-to-core integration that binds BRAM replay, diagnostic, audio, "
            "and ADC adapters through one safe source mux into the mathematical core; preserves "
            "the C0 finite-replay analysis/tail split; paces board replay/diagnostic sources; "
            "returns real source/core safe boundaries; connects valid-only taps to telemetry; "
            "and integrates new-fault event reporting into the board hierarchy. Step-7-specific "
            "HDL elaboration, RTL simulation, functional verification, Quartus compile, codec/ADC bring-up, "
            "physical-board evidence, and hardware signoff remain excluded and pending."
            if args.step >= 7
            else None
        ),
        "step_8_scope": (
            "Hand-written reusable core + telemetry composition that instantiates the real "
            "mathematical core and non-stalling telemetry formatter; maps core controls, finite "
            "stream/tail routing, valid-only taps, parameterized unique-bin indices, packet modes, "
            "authoritative status/metrics context, one safely applied metric-clear epoch, one "
            "telemetry FIFO output, re-armable new-fault/drop accounting, and a dedicated composed "
            "build filelist. The DE1-SoC path reuses its existing sole source/core owner and the "
            "telemetry-only top rather than instantiating a duplicate core. "
            "Step-8-specific HDL elaboration, RTL simulation, functional verification, Quartus "
            "compile, physical-board evidence, and hardware signoff remain excluded and pending."
            if args.step >= 8
            else None
        ),
        "step_9_scope": (
            "Hand-written physical DE1-SoC board-top source composition with source bindings to "
            "the generated Platform Designer system CSR and F2SDRAM boundary contracts, audio "
            "and LTC2308 capture wrappers, the sole source/core owner, direct core-to-telemetry "
            "observation, best-effort non-stalling core-y audio monitoring, and real LED/HEX "
            "status. Synthetic taps, "
            "safe-idle bus substitutes, constant ADC configuration, audio line-out data "
            "tie-offs, and a constant/disconnected core-y board tieoff are excluded; the "
            f"{step_9_audio_scope}Vendor-generated system "
            "HDL/QIP/SOPCINFO are absent and generation remains pending. Step-9-specific "
            "HDL elaboration, RTL simulation, functional verification, Platform Designer "
            "generation, Quartus compile/timing, codec/ADC operation, physical-board evidence, "
            "and hardware signoff remain excluded and pending."
            if args.step >= 9
            else None
        ),
        "step_10_scope": (
            "One active 50 MHz CLOCK_50 fabric domain; clock_reset_ctrl-owned 20 ms board-reset "
            "release qualification and one canonical reset synchronizer after combining the "
            "qualified board request with H2F reset; exact-average fractional sample, STATUS, "
            "METRICS, heartbeat, and LTC2308 continuous-request enables; synchronous telemetry "
            "formatter/FIFO soft "
            "clear with no derived asynchronous reset; receive-edge and transmit-edge codec-BCLK "
            "reset release; and source-owned SDC/checker/build contracts. Split-clock fabric, "
            f"{step_10_audio_scope}Generated Platform Designer HDL/QIP/SOPCINFO, RTL "
            "compile, functional simulation, Quartus/TimeQuest, physical-board evidence, and "
            "hardware signoff remain excluded and pending."
            if args.step >= 10
            else None
        ),
        "step_11_scope": (
            "Hand-written BRAM-replay system integration, source-frozen path contract, "
            "fail-closed source checker, and a logical end-to-end RTL testbench/filelist. "
            "The source path covers replay admission, mathematical-core completion, "
            "non-stalling telemetry, and the HPS-visible DDR-ring boundary. Accepted "
            "ModelSim/Questa execution, Platform Designer generation, Quartus/TimeQuest, "
            "HPS runtime, physical-board evidence, and hardware signoff remain excluded "
            "and pending."
            if args.step >= 11
            else None
        ),
        "step_12_scope": (
            "Hand-written DDR-ring ownership and Linux reserved-memory source contract, "
            "one canonical no-map DTS reservation, fail-closed source checker, and a "
            "directed RTL ownership/WRAP/reset testbench and filelist. FPGA ownership "
            "of the producer pointer, HPS ownership of the consumer pointer, exact "
            "physical-tail WRAP accounting, and deterministic transport-reset epochs "
            "are checked-in source requirements. Testbench execution, compiled DTB "
            "inspection, Linux boot/runtime reservation evidence, HPS runtime evidence, "
            "Platform Designer generation, Quartus/TimeQuest, physical-board evidence, "
            "and hardware signoff remain excluded and pending. The DTS reservation is "
            "the sole official reservation mechanism; mem=992M is not an active "
            "alternative."
            if args.step >= 12
            else None
        ),
        "step_13_scope": (
            "Hand-written HPS userspace transport with fail-closed live reserved-memory "
            "admission, strict DDR-record validation, exact physical-tail WRAP consume, "
            "one-record-per-datagram UDP forwarding for WAVE/METRICS/STATUS/SPEC64/SPEC129, "
            "commit-after-consume semantics, exactly-once malformed disable/latch behavior, "
            "and a no-CSR/no-DDR diagnostic STATUS dummy mode. A RAM-backed ASan/UBSan host "
            "test and source checker are provided, but their execution outputs are deliberately "
            "not packaged. Live HPS Linux reservation/mmap, Ethernet, systemd, FPGA, and board "
            "evidence remain excluded and pending."
            if args.step >= 13
            else None
        ),
        "step_14_scope": (
            "An explicit command-protocol version-2 source extension preserves the exact "
            "Revision-G version-1 seven-command request contract while adding generated "
            "commands for spectrum mode, telemetry enable, pinned DDR-ring configuration, "
            "transport reset, counter clear, BRAM replay control, and status/version readback. "
            "The version-2 request remains 28 bytes and uses an exact 32-byte result for "
            "every non-PING command; PING remains diagnostic-STATUS-only. Trusted peer "
            "IP and port matching, RFC1982 at-most-once sequencing for every v2 non-PING "
            "request, bounded result "
            "caching, RESET-to-CONFIGURE-to-ENABLE lifecycle ordering, generated CSR minor-1.8 "
            "extensions, source checkers (including a non-native RTL structural/model gate), "
            "a directed RTL testbench/filelist source, "
            "and HPS/PC host-test sources are included. Test "
            "execution output, live PC-to-HPS UDP, Linux mappings, lightweight-bridge traversal, "
            "FPGA command application, BRAM replay execution, RTL simulation, Platform Designer "
            "generation, Quartus/TimeQuest, board, and hardware evidence remain excluded."
            if args.step >= 14
            else None
        ),
        "step_15_scope": (
            "Hand-written PC dashboard source for bounded live STATUS, waveform, metrics, "
            "spectrum, time-history spectrogram, packet-rate and sequence-gap observability; "
            "separate DDR/FIFO drop counters; malformed/truncated receive state; and live "
            "command controls routed only through the Step-14 UDP command client. A "
            "dependency-free host regression source is included, but its execution output is "
            "not packaged. Live PC-to-HPS UDP operation, interactive GUI/runtime soak, Linux, "
            "FPGA, board, Quartus/TimeQuest, and hardware evidence remain excluded."
            if args.step >= 15
            else None
        ),
        "step_16_scope": (
            "Hand-written WM8731 control and LINE-IN source implementation with a peripheral-only "
            "12.288 MHz fractional audio PLL wrapper, lock-qualified open-drain FPGA I2C "
            "initialization, ACK-gated 48 kHz/16-bit codec-master I2S configuration, I2S RX/TX, "
            "dual asynchronous audio FIFOs, source-epoch flushing, and dedicated saturating RX "
            "overflow, TX overflow, and TX underflow counters. Rev-H FPGA I2C pins, the explicitly "
            "selected de1soc_linein_demo build/bring-up profile, a source contract/schema/checker, "
            "and a dependency-free behavioral model are included. BRAM replay remains the "
            "correctness authority. Native RTL compile/simulation, Platform Designer generation, "
            "Quartus/TimeQuest, PLL lock/frequency measurement, codec I2C acknowledgement, measured "
            "BCLK/LRCK, live samples, board operation, and hardware signoff remain excluded and "
            "pending."
            if args.step >= 16
            else None
        ),
        "step_17_scope": (
            "Hand-written DE1-SoC Rev-H LTC2308 live-ADC source implementation with the legacy "
            "ADC_CS_N board port frozen as active-high CONVST, a 40 ns conversion-start pulse, "
            "1.84 us CONVST-to-first-SCLK interval, 2.5 MHz idle-low serial clock, all eight "
            "single-ended unipolar awake channel commands, previous-conversion prime/discard "
            "policy, a 92-cycle post-enable/abort recovery holdoff with sticky early-request "
            "rejection, fail-closed rejection of bipolar/differential/sleep commands, unsigned "
            "12-bit straight-binary centering at code 2048, and an exact "
            "100 kS/s continuous scheduler. ADC_DOUT crosses through an identified two-stage "
            "synchronizer into the sole 50 MHz fabric controller; ADC_SCLK is a protocol output, "
            "not an RTL clock. The wrapper feeds the existing ADC adapter and source mux only "
            "under TSRC_ADC_LIVE, while telemetry reports 100 kS/s for ADC and 48 kHz for BRAM, "
            "diagnostic, and LINE-IN sources. An explicit ADC profile, exact source contract/schema, "
            "source checker, dependency-free behavioral model, build gates, and bring-up notes are "
            "included. BRAM replay remains the default correctness authority and neither it nor "
            "LINE-IN is blocked by ADC-only gates. Native RTL compile/simulation, Platform Designer "
            "generation, Quartus/TimeQuest, post-fit I/O and serial timing measurement, measured "
            "sampling rate, analog characterization, live ADC operation, board evidence, and "
            "hardware signoff remain excluded and pending."
            if args.step >= 17
            else None
        ),
        "hps_preset_effective_sha256": (
            "bf0dc533f1a141c2a3d91058501b19b0a6ef5b479619bb4829fe94bea60e0888"
            if args.step >= 2
            else None
        ),
        "hps_preset_application_sha256": (
            "02c6f1fc1bec86f960d3a7740f38f65ec3931c74458bf338f20c9b9f22f45076"
            if args.step >= 2
            else None
        ),
        "hps_parameter_partition": (
            {"total": 520, "applied": 476, "readback_only": 44}
            if args.step >= 2
            else None
        ),
        "step_1_milestone_files": STEP1_FILES,
        "step_2_milestone_files": STEP2_FILES if args.step >= 2 else [],
        "step_3_milestone_files": STEP3_FILES if args.step >= 3 else [],
        "step_4_milestone_files": STEP4_FILES if args.step >= 4 else [],
        "step_5_milestone_files": STEP5_FILES if args.step >= 5 else [],
        "step_6_milestone_files": STEP6_FILES if args.step >= 6 else [],
        "step_7_milestone_files": STEP7_FILES if args.step >= 7 else [],
        "step_8_milestone_files": STEP8_FILES if args.step >= 8 else [],
        "step_9_milestone_files": STEP9_FILES if args.step >= 9 else [],
        "step_10_milestone_files": STEP10_FILES if args.step >= 10 else [],
        "step_11_milestone_files": STEP11_FILES if args.step >= 11 else [],
        "step_12_milestone_files": STEP12_FILES if args.step >= 12 else [],
        "step_13_milestone_files": STEP13_FILES if args.step >= 13 else [],
        "step_14_milestone_files": STEP14_FILES if args.step >= 14 else [],
        "step_15_milestone_files": STEP15_FILES if args.step >= 15 else [],
        "step_16_milestone_files": STEP16_FILES if args.step >= 16 else [],
        "step_17_milestone_files": STEP17_FILES if args.step >= 17 else [],
        "structural_empty_directories": STRUCTURAL_EMPTY_DIRECTORIES,
        "exclusions": {
            "artifact_gitkeep_glob": "artifacts/**/.gitkeep",
            "directory_names": sorted(EXCLUDED_DIRECTORY_NAMES),
            "directory_globs": sorted(EXCLUDED_DIRECTORY_GLOBS),
            "root_directory_globs": sorted(EXCLUDED_ROOT_DIRECTORY_GLOBS),
            "sim_directory_globs": sorted(EXCLUDED_SIM_DIRECTORY_GLOBS),
            "reference_build_directory_globs": sorted(
                EXCLUDED_REFERENCE_BUILD_DIRECTORY_GLOBS
            ),
            "qsys_generated_directory_names": sorted(QSYS_GENERATED_DIRECTORY_NAMES),
            "qsys_generated_suffixes": sorted(QSYS_GENERATED_SUFFIXES),
            "audio_ip_root_directory_names": sorted(AUDIO_IP_ROOT_DIRECTORY_NAMES),
            "audio_ip_generated_directory_names": sorted(
                AUDIO_IP_GENERATED_DIRECTORY_NAMES
            ),
            "audio_ip_generated_file_globs": sorted(AUDIO_IP_GENERATED_FILE_GLOBS),
            "file_names": sorted(EXCLUDED_FILE_NAMES),
            "file_globs": sorted(EXCLUDED_FILE_GLOBS),
            "file_endings": sorted(EXCLUDED_FILE_ENDINGS),
            "relative_paths": sorted(EXCLUDED_RELATIVE_PATHS),
            "relative_prefixes": sorted(EXCLUDED_RELATIVE_PREFIXES),
            "suffixes": sorted(EXCLUDED_SUFFIXES),
        },
        "file_count": len(file_records),
        "files": file_records,
    }
    manifest_data = (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode("utf-8")

    temporary = output.with_name(output.name + ".tmp")
    try:
        output.parent.mkdir(parents=True, exist_ok=True)
        if temporary.exists():
            temporary.unlink()
        with zipfile.ZipFile(
            temporary, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9
        ) as archive:
            manifest_name = f"{archive_root}/{PACKAGE_MANIFEST_NAME}"
            archive.writestr(zip_info(manifest_name, 0o644), manifest_data)
            for relative_dir in STRUCTURAL_EMPTY_DIRECTORIES:
                archive.writestr(
                    zip_directory_info(f"{archive_root}/{relative_dir}"), b""
                )
            for relative, data, mode in payloads:
                archive_name = f"{archive_root}/{relative.as_posix()}"
                archive.writestr(zip_info(archive_name, mode), data)
        validate_archive(temporary, archive_root, file_records, manifest_data)
        os.replace(temporary, output)
    except (OSError, SnapshotValidationError, zipfile.BadZipFile, zipfile.LargeZipFile) as exc:
        print(f"ERROR: cannot create validated architecture snapshot: {exc}", file=sys.stderr)
        return 1
    finally:
        if temporary.exists():
            temporary.unlink()

    archive_hash = sha256(output.read_bytes())
    print(
        f"package_architecture_snapshot: OK step={args.step} files={len(files)} "
        f"bytes={output.stat().st_size} sha256={archive_hash} output={output}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
