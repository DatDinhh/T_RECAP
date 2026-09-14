#!/usr/bin/env python3
"""Validate and resolve T-RECAP Phase 2 runtime/build profiles.

File class: [1] hand-written repository infrastructure.

The validator is deliberately self-contained so a profile check does not depend on
an optional Python package. If ``jsonschema`` is installed, the same files are also
checked against ``spec/schemas/runtime_profile.schema.json``. Semantic checks always
run and derive enums, ranges, masks, and transport versions from the generated source
contracts instead of maintaining a second hand-written numeric contract.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

PROFILE_SCHEMA_NAME = "trecap_phase2_runtime_profile_v1"
PROFILE_SCHEMA_PATH = "spec/schemas/runtime_profile.schema.json"
PROFILE_DIR = "config/profiles"

REQUIRED_PROFILE_FILES = (
    "baseline_core.json",
    "sim_core_only.json",
    "de1soc_bram_replay.json",
    "de1soc_linein_demo.json",
    "de1soc_adc_demo.json",
    "telemetry_status_only.json",
    "telemetry_full_demo.json",
)

EXPECTED_PROFILE_KINDS = {
    "baseline_core": "build",
    "sim_core_only": "build",
    "de1soc_bram_replay": "build",
    "de1soc_linein_demo": "build",
    "de1soc_adc_demo": "build",
    "telemetry_status_only": "telemetry_preset",
    "telemetry_full_demo": "telemetry_preset",
}

CONTRACT_REFS = {
    "core_config": "spec/generated/core_config.json",
    "csr_map": "spec/generated/csr_map.json",
    "packet_layouts": "spec/generated/packet_layouts.json",
}

BUILD_TOP_BY_TARGET = {
    "core_only": "trecap_core_only_top",
    "bram_replay": "trecap_core_bram_replay_top",
    "core_telemetry": "trecap_core_telemetry_top",
    "hps_bridge": "trecap_de1soc_full_top",
    "de1soc_full": "de1_soc_trecap_top",
}

BUILD_PLATFORMS = {"generic_rtl", "simulation", "de1soc"}
INPUT_KINDS = {
    "external_stream",
    "bram_replay",
    "adc_live",
    "audio_wrapper",
    "diagnostic_source",
}
REPLAY_START_POLICIES = {
    "testbench_pulse",
    "board_key",
    "auto_start_on_reset_release",
}
SPEC_MODE_PROFILE_TO_CONTRACT = {
    "DISABLED": "SPEC_DISABLED",
    "SPEC64": "SPEC64",
    "SPEC129": "SPEC129",
}

BUILD_PROFILE_KEYS = {
    "schema",
    "profile_kind",
    "profile_name",
    "description",
    "build",
    "contract_refs",
    "input",
    "sample_rate_hz",
    "telemetry_profile",
    "transport",
    "transport_version_major",
    "transport_version_minor",
}
TELEMETRY_PROFILE_KEYS = {
    "schema",
    "profile_kind",
    "profile_name",
    "description",
    "packet_enable",
    "spec_mode",
    "wave_decim",
    "spec_shift",
    "status_rate_hz",
    "metrics_rate_hz",
    "transport_version_major",
    "transport_version_minor",
}
BUILD_KEYS = {"target", "top_module", "platform", "board", "quartus_project"}
INPUT_KEYS = {
    "kind",
    "source_mode",
    "vector_config",
    "input_memh",
    "replay_start_policy",
    "audio",
    "adc",
}
AUDIO_KEYS = {
    "codec_sample_width",
    "channel_select",
    "input_scale_rule",
    "master_clock_hz",
    "lineout_enable",
    "codec_control",
    "audio_pll",
    "hardware_gate",
}
CODEC_CONTROL_KEYS = {
    "enable",
    "codec_model",
    "i2c_bus",
    "i2c_address_7bit",
    "serial_format",
    "sample_rate_hz",
    "word_width_bits",
    "clock_role",
}
AUDIO_PLL_KEYS = {
    "enable",
    "reference_clock",
    "reference_clock_hz",
    "output_clock",
    "output_clock_hz",
}
AUDIO_HARDWARE_GATE_KEYS = {
    "codec_init_requires_pll_locked",
    "audio_capture_requires_config_done",
}
ADC_KEYS = {
    "device_model",
    "sample_width_bits",
    "sample_format",
    "input_mode",
    "polarity",
    "power_mode",
    "input_range_volts",
    "zero_code",
    "input_scale_rule",
    "channel_select",
    "default_channel",
    "channel_change_policy",
    "first_result_policy",
    "sampling_mode_select",
    "continuous_sample_rate_hz",
    "serial_clock_hz",
    "dc_block_enable",
}
TRANSPORT_KEYS = {
    "hps_ddr_enable",
    "hps_udp_enable",
    "command_server_enable",
    "ring_enable_policy",
    "address_map",
    "hps_runtime_config",
    "dashboard_config",
}

# These keys belong to generated core contracts or vector artifacts, never profiles.
FORBIDDEN_PROFILE_KEYS = {
    "N",
    "L",
    "P",
    "H",
    "F",
    "G",
    "D",
    "THR2",
    "PROTECT_DC",
    "PROTECT_NYQ",
    "W_Qw",
    "W_tw",
    "W_u",
    "W_fft",
    "W_fft_pre",
    "W_can_pre",
    "W_can",
    "W_mag2",
    "W_ifft",
    "W_z",
    "W_ola",
    "csr_offsets",
    "packet_ids",
    "payload_layouts",
    "ring_base_hps_phys",
    "ring_base_fpga",
    "ring_size_bytes",
}


class ProfileCheckError(RuntimeError):
    """Raised for malformed, inconsistent, or contract-drifting profiles."""


@dataclass(frozen=True)
class Contracts:
    source_modes: Mapping[str, int]
    spec_modes: Mapping[str, int]
    packet_masks: Mapping[str, int]
    wave_decim_min: int
    wave_decim_max: int
    spec_shift_max: int
    ring_size_min: int
    ring_alignment: int
    ring_guard_min: int
    transport_major: int
    transport_minor: int


def repo_root_from_script() -> Path:
    return Path(__file__).resolve().parents[1]


def _reject_duplicates(path: Path):
    def hook(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ProfileCheckError(f"duplicate JSON key in {path}: {key!r}")
            result[key] = value
        return result

    return hook


def load_json(path: Path) -> object:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise ProfileCheckError(f"cannot read {path}: {exc}") from exc
    if raw.startswith(b"\xef\xbb\xbf"):
        raise ProfileCheckError(f"UTF-8 BOM is forbidden: {path}")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ProfileCheckError(f"file is not UTF-8: {path}: {exc}") from exc
    try:
        return json.loads(
            text,
            object_pairs_hook=_reject_duplicates(path),
            parse_constant=lambda value: (_ for _ in ()).throw(
                ProfileCheckError(f"non-finite JSON number in {path}: {value}")
            ),
        )
    except json.JSONDecodeError as exc:
        raise ProfileCheckError(f"invalid JSON in {path}: {exc}") from exc


def require_mapping(value: object, context: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ProfileCheckError(f"{context} must be a JSON object")
    return value


def require_exact_keys(
    value: Mapping[str, Any],
    allowed: set[str],
    required: set[str],
    context: str,
) -> None:
    missing = sorted(required - set(value))
    unknown = sorted(set(value) - allowed)
    if missing:
        raise ProfileCheckError(f"{context} is missing required keys: {missing}")
    if unknown:
        raise ProfileCheckError(f"{context} contains unknown keys: {unknown}")


def require_string(value: object, context: str) -> str:
    if not isinstance(value, str) or not value:
        raise ProfileCheckError(f"{context} must be a non-empty string")
    return value


def require_int(value: object, context: str, minimum: int, maximum: int) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise ProfileCheckError(f"{context} must be an integer in range {minimum}..{maximum}")
    return value


def parse_contract_int(value: object, context: str) -> int:
    if type(value) is int:
        return value
    if isinstance(value, str):
        try:
            return int(value, 0)
        except ValueError as exc:
            raise ProfileCheckError(f"{context} is not an integer or base-prefixed string") from exc
    raise ProfileCheckError(f"{context} is not an integer or base-prefixed string")


def require_bool(value: object, context: str) -> bool:
    if type(value) is not bool:
        raise ProfileCheckError(f"{context} must be a boolean")
    return value


def validate_relative_path(root: Path, value: object, context: str, must_exist: bool) -> Path:
    text = require_string(value, context)
    candidate = Path(text)
    if candidate.is_absolute() or ".." in candidate.parts:
        raise ProfileCheckError(f"{context} must be a repository-relative path: {text}")
    resolved = (root / candidate).resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ProfileCheckError(f"{context} escapes the repository root: {text}") from exc
    if must_exist and not resolved.is_file():
        raise ProfileCheckError(f"{context} does not exist: {text}")
    return resolved


def find_register(csr: Mapping[str, Any], name: str) -> Mapping[str, Any]:
    for item in csr.get("registers", []):
        if isinstance(item, Mapping) and item.get("name") == name:
            return item
    raise ProfileCheckError(f"CSR contract is missing register {name}")


def load_contracts(root: Path) -> Contracts:
    core = require_mapping(load_json(root / CONTRACT_REFS["core_config"]), "core_config")
    csr = require_mapping(load_json(root / CONTRACT_REFS["csr_map"]), "csr_map")
    packets = require_mapping(
        load_json(root / CONTRACT_REFS["packet_layouts"]), "packet_layouts"
    )

    source_modes_raw = require_mapping(core.get("source_modes"), "core_config.source_modes")
    source_modes = {str(name): int(value) for name, value in source_modes_raw.items()}
    expected_sources = {"bram_replay", "adc_live", "audio_wrapper", "diagnostic_source"}
    if set(source_modes) != expected_sources:
        raise ProfileCheckError(
            "core_config.source_modes does not contain the canonical Revision-J source set"
        )

    enums = require_mapping(csr.get("enums"), "csr_map.enums")
    spec_modes_raw = enums.get("spec_mode")
    if not isinstance(spec_modes_raw, list):
        raise ProfileCheckError("csr_map.enums.spec_mode must be an array")
    spec_modes: dict[str, int] = {}
    for item in spec_modes_raw:
        entry = require_mapping(item, "csr_map.enums.spec_mode entry")
        spec_modes[require_string(entry.get("name"), "spec mode name")] = require_int(
            entry.get("value"), "spec mode value", 0, 0xFFFF_FFFF
        )
    if set(spec_modes) != set(SPEC_MODE_PROFILE_TO_CONTRACT.values()):
        raise ProfileCheckError("csr_map spec-mode enum does not match the Revision-G profile set")

    packet_reg = find_register(csr, "PACKET_ENABLE")
    packet_masks: dict[str, int] = {}
    for field_raw in packet_reg.get("fields", []):
        field = require_mapping(field_raw, "PACKET_ENABLE field")
        kind = str(field.get("kind", ""))
        field_name = str(field.get("name", ""))
        if kind != "enable" or not field_name.endswith("_EN"):
            continue
        packet_name = field_name.removesuffix("_EN")
        lsb = require_int(field.get("lsb"), f"PACKET_ENABLE.{field_name}.lsb", 0, 31)
        msb = require_int(field.get("msb"), f"PACKET_ENABLE.{field_name}.msb", lsb, 31)
        packet_masks[packet_name] = ((1 << (msb - lsb + 1)) - 1) << lsb
    if set(packet_masks) != {"WAVE", "SPEC", "METRICS", "STATUS"}:
        raise ProfileCheckError("CSR PACKET_ENABLE fields do not match Revision-G profile packets")

    constants = require_mapping(csr.get("constants"), "csr_map.constants")
    version = require_mapping(constants.get("VERSION"), "csr_map.constants.VERSION")
    transport = require_mapping(packets.get("transport"), "packet_layouts.transport")
    major = require_int(version.get("major"), "CSR version major", 0, 0xFFFF)
    minor = require_int(version.get("minor"), "CSR version minor", 0, 0xFFFF)
    packet_major = require_int(
        transport.get("transport_version_major"), "packet transport major", 0, 0xFFFF
    )
    packet_minor = require_int(
        transport.get("transport_version_minor"), "packet transport minor", 0, 0xFFFF
    )
    if (major, minor) != (packet_major, packet_minor):
        raise ProfileCheckError("CSR and packet transport versions disagree")

    return Contracts(
        source_modes=source_modes,
        spec_modes=spec_modes,
        packet_masks=packet_masks,
        wave_decim_min=require_int(
            constants.get("WAVE_DECIM_MIN"), "WAVE_DECIM_MIN", 1, 0xFFFF
        ),
        wave_decim_max=require_int(
            constants.get("WAVE_DECIM_MAX"), "WAVE_DECIM_MAX", 1, 0xFFFF
        ),
        spec_shift_max=require_int(
            constants.get("SPEC_SHIFT_MAX"), "SPEC_SHIFT_MAX", 0, 0xFFFF
        ),
        ring_size_min=require_int(
            constants.get("RING_SIZE_MIN_BYTES"), "RING_SIZE_MIN_BYTES", 1, 0xFFFF_FFFF
        ),
        ring_alignment=require_int(
            constants.get("RING_ALIGNMENT_BYTES"), "RING_ALIGNMENT_BYTES", 1, 0xFFFF_FFFF
        ),
        ring_guard_min=require_int(
            constants.get("RING_GUARD_BYTES_MIN"), "RING_GUARD_BYTES_MIN", 1, 0xFFFF_FFFF
        ),
        transport_major=major,
        transport_minor=minor,
    )


def validate_no_contract_overrides(value: object, context: str = "profile") -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            if key in FORBIDDEN_PROFILE_KEYS:
                raise ProfileCheckError(
                    f"{context}.{key} is contract-owned and must not be overridden by a profile"
                )
            validate_no_contract_overrides(child, f"{context}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            validate_no_contract_overrides(child, f"{context}[{index}]")


def validate_identity(profile: Mapping[str, Any], path: Path) -> tuple[str, str]:
    if profile.get("schema") != PROFILE_SCHEMA_NAME:
        raise ProfileCheckError(
            f"{path}: schema must be {PROFILE_SCHEMA_NAME!r}, got {profile.get('schema')!r}"
        )
    profile_name = require_string(profile.get("profile_name"), f"{path}.profile_name")
    if re.fullmatch(r"[a-z][a-z0-9_]*", profile_name) is None:
        raise ProfileCheckError(f"{path}: profile_name must use lowercase snake_case")
    if profile_name != path.stem:
        raise ProfileCheckError(
            f"{path}: profile_name {profile_name!r} must match filename stem {path.stem!r}"
        )
    profile_kind = require_string(profile.get("profile_kind"), f"{path}.profile_kind")
    expected_kind = EXPECTED_PROFILE_KINDS.get(profile_name)
    if expected_kind is None:
        raise ProfileCheckError(f"{path}: profile_name is not in the frozen profile inventory")
    if profile_kind != expected_kind:
        raise ProfileCheckError(
            f"{path}: profile_kind {profile_kind!r} must be {expected_kind!r}"
        )
    require_string(profile.get("description"), f"{path}.description")
    validate_no_contract_overrides(profile)
    return profile_name, profile_kind


def validate_version(profile: Mapping[str, Any], path: Path, contracts: Contracts) -> None:
    major = require_int(
        profile.get("transport_version_major"),
        f"{path}.transport_version_major",
        0,
        0xFFFF,
    )
    minor = require_int(
        profile.get("transport_version_minor"),
        f"{path}.transport_version_minor",
        0,
        0xFFFF,
    )
    if (major, minor) != (contracts.transport_major, contracts.transport_minor):
        raise ProfileCheckError(
            f"{path}: transport version {major}.{minor} does not match generated contract "
            f"{contracts.transport_major}.{contracts.transport_minor}"
        )


def validate_telemetry_preset(
    profile: Mapping[str, Any], path: Path, contracts: Contracts
) -> None:
    require_exact_keys(
        profile,
        TELEMETRY_PROFILE_KEYS,
        TELEMETRY_PROFILE_KEYS,
        str(path),
    )
    validate_identity(profile, path)
    validate_version(profile, path, contracts)

    packets_raw = profile.get("packet_enable")
    if not isinstance(packets_raw, list) or any(not isinstance(item, str) for item in packets_raw):
        raise ProfileCheckError(f"{path}.packet_enable must be an array of packet names")
    packets = list(packets_raw)
    if len(packets) != len(set(packets)):
        raise ProfileCheckError(f"{path}.packet_enable contains duplicate packet names")
    unknown = sorted(set(packets) - set(contracts.packet_masks))
    if unknown:
        raise ProfileCheckError(
            f"{path}.packet_enable contains unknown or reserved-disabled packets: {unknown}"
        )

    spec_mode = require_string(profile.get("spec_mode"), f"{path}.spec_mode")
    if spec_mode not in SPEC_MODE_PROFILE_TO_CONTRACT:
        raise ProfileCheckError(f"{path}.spec_mode is not a canonical Revision-G value")
    spec_enabled = "SPEC" in packets
    if spec_enabled and spec_mode == "DISABLED":
        raise ProfileCheckError(f"{path}: SPEC is enabled but spec_mode is DISABLED")
    if not spec_enabled and spec_mode != "DISABLED":
        raise ProfileCheckError(f"{path}: spec_mode must be DISABLED when SPEC is not enabled")

    require_int(
        profile.get("wave_decim"),
        f"{path}.wave_decim",
        contracts.wave_decim_min,
        contracts.wave_decim_max,
    )
    require_int(
        profile.get("spec_shift"),
        f"{path}.spec_shift",
        0,
        contracts.spec_shift_max,
    )
    status_rate = require_int(profile.get("status_rate_hz"), f"{path}.status_rate_hz", 0, 1000)
    metrics_rate = require_int(
        profile.get("metrics_rate_hz"), f"{path}.metrics_rate_hz", 0, 1000
    )
    if ("STATUS" in packets) != (status_rate > 0):
        raise ProfileCheckError(
            f"{path}: status_rate_hz must be positive exactly when STATUS is enabled"
        )
    if ("METRICS" in packets) != (metrics_rate > 0):
        raise ProfileCheckError(
            f"{path}: metrics_rate_hz must be positive exactly when METRICS is enabled"
        )

    if path.stem == "telemetry_status_only" and packets != ["STATUS"]:
        raise ProfileCheckError(f"{path}: status-only preset must contain only STATUS")
    if path.stem == "telemetry_full_demo" and set(packets) != set(contracts.packet_masks):
        raise ProfileCheckError(f"{path}: full-demo preset must enable all Revision-G packets")


def validate_contract_refs(root: Path, value: object, context: str) -> None:
    refs = require_mapping(value, context)
    require_exact_keys(refs, set(CONTRACT_REFS), set(CONTRACT_REFS), context)
    for key, expected in CONTRACT_REFS.items():
        actual = refs.get(key)
        if actual != expected:
            raise ProfileCheckError(f"{context}.{key} must be {expected!r}, got {actual!r}")
        validate_relative_path(root, actual, f"{context}.{key}", must_exist=True)


def validate_build_block(root: Path, value: object, context: str) -> Mapping[str, Any]:
    build = require_mapping(value, context)
    require_exact_keys(build, BUILD_KEYS, {"target", "top_module", "platform"}, context)
    target = require_string(build.get("target"), f"{context}.target")
    top = require_string(build.get("top_module"), f"{context}.top_module")
    platform = require_string(build.get("platform"), f"{context}.platform")
    if target not in BUILD_TOP_BY_TARGET:
        raise ProfileCheckError(f"{context}.target is not a supported build target: {target}")
    if top != BUILD_TOP_BY_TARGET[target]:
        raise ProfileCheckError(
            f"{context}.top_module must be {BUILD_TOP_BY_TARGET[target]!r} for target {target!r}"
        )
    if platform not in BUILD_PLATFORMS:
        raise ProfileCheckError(f"{context}.platform is not supported: {platform}")
    if platform == "de1soc":
        if build.get("board") != "de1soc":
            raise ProfileCheckError(f"{context}.board must be 'de1soc'")
        validate_relative_path(
            root,
            build.get("quartus_project"),
            f"{context}.quartus_project",
            must_exist=False,
        )
        if target != "de1soc_full":
            raise ProfileCheckError(f"{context}: DE1-SoC platform must use de1soc_full target")
    elif "board" in build or "quartus_project" in build:
        raise ProfileCheckError(
            f"{context}: board/quartus_project are legal only for the de1soc platform"
        )
    return build


def count_memh_rows(path: Path) -> int:
    rows = 0
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.split("//", 1)[0].strip()
        if line:
            rows += 1
    return rows


def validate_input_block(
    root: Path,
    value: object,
    sample_rate_hz: int,
    context: str,
    contracts: Contracts,
) -> Mapping[str, Any]:
    input_cfg = require_mapping(value, context)
    require_exact_keys(input_cfg, INPUT_KEYS, {"kind", "source_mode"}, context)
    kind = require_string(input_cfg.get("kind"), f"{context}.kind")
    if kind not in INPUT_KINDS:
        raise ProfileCheckError(f"{context}.kind is not supported: {kind}")
    source_mode = input_cfg.get("source_mode")

    if kind == "external_stream":
        if source_mode is not None:
            raise ProfileCheckError(f"{context}.source_mode must be null for external_stream")
        extras = set(input_cfg) - {"kind", "source_mode"}
        if extras:
            raise ProfileCheckError(
                f"{context}: external_stream contains illegal keys: {sorted(extras)}"
            )
        if sample_rate_hz != 0:
            raise ProfileCheckError(f"{context}: external_stream sample_rate_hz must be 0")
        return input_cfg

    if source_mode != kind or kind not in contracts.source_modes:
        raise ProfileCheckError(
            f"{context}.source_mode must use the generated canonical name {kind!r}"
        )

    if kind == "bram_replay":
        required = {"kind", "source_mode", "vector_config", "input_memh", "replay_start_policy"}
        require_exact_keys(input_cfg, required, required, context)
        vector_path = validate_relative_path(
            root, input_cfg.get("vector_config"), f"{context}.vector_config", must_exist=True
        )
        memh_path = validate_relative_path(
            root, input_cfg.get("input_memh"), f"{context}.input_memh", must_exist=True
        )
        start_policy = require_string(
            input_cfg.get("replay_start_policy"), f"{context}.replay_start_policy"
        )
        if start_policy not in REPLAY_START_POLICIES:
            raise ProfileCheckError(
                f"{context}.replay_start_policy cannot claim an undefined HPS/PC replay command"
            )
        vector = require_mapping(load_json(vector_path), f"{context}.vector_config")
        expected_name = vector_path.parent.name
        if vector.get("vector_name") != expected_name:
            raise ProfileCheckError(
                f"{context}.vector_config vector_name does not match directory {expected_name!r}"
            )
        if memh_path.parent != vector_path.parent:
            raise ProfileCheckError(
                f"{context}.input_memh must belong to the selected vector directory"
            )
        rows = require_mapping(vector.get("artifact_rows"), "vector artifact_rows").get("x_in")
        expected_rows = require_int(rows, "vector artifact_rows.x_in", 1, 0xFFFF_FFFF)
        actual_rows = count_memh_rows(memh_path)
        if actual_rows != expected_rows:
            raise ProfileCheckError(
                f"{context}.input_memh row count mismatch: expected {expected_rows}, "
                f"got {actual_rows}"
            )
    elif kind == "adc_live":
        required = {"kind", "source_mode", "adc"}
        require_exact_keys(input_cfg, required, required, context)
        if sample_rate_hz != 100_000:
            raise ProfileCheckError(f"{context}: adc_live sample_rate_hz must be 100000")
        adc = require_mapping(input_cfg.get("adc"), f"{context}.adc")
        require_exact_keys(adc, ADC_KEYS, ADC_KEYS, f"{context}.adc")
        expected_adc = {
            "device_model": "ltc2308",
            "sample_width_bits": 12,
            "sample_format": "unsigned_straight_binary",
            "input_mode": "single_ended",
            "polarity": "unipolar",
            "power_mode": "awake",
            "input_range_volts": "0_to_4.096",
            "zero_code": 2048,
            "input_scale_rule": (
                "unsigned_midscale_subtract_then_signed_rnd_shr_Badc_minus_N"
            ),
            "channel_select": "sw6_4_latched_on_source_entry",
            "default_channel": 0,
            "channel_change_policy": "leave_and_reenter_adc_source",
            "first_result_policy": "prime_and_discard_previous_configuration",
            "sampling_mode_select": "sw7_low_continuous_high_key2_diagnostic_only",
            "continuous_sample_rate_hz": 100_000,
            "serial_clock_hz": 2_500_000,
            "dc_block_enable": False,
        }
        if dict(adc) != expected_adc:
            raise ProfileCheckError(f"{context}.adc differs from the frozen LTC2308 profile")
        if adc.get("continuous_sample_rate_hz") != sample_rate_hz:
            raise ProfileCheckError(
                f"{context}.adc.continuous_sample_rate_hz must match sample_rate_hz"
            )
    elif kind == "audio_wrapper":
        required = {"kind", "source_mode", "audio"}
        require_exact_keys(input_cfg, required, required, context)
        if sample_rate_hz <= 0:
            raise ProfileCheckError(f"{context}: audio_wrapper requires a positive sample_rate_hz")
        audio = require_mapping(input_cfg.get("audio"), f"{context}.audio")
        require_exact_keys(audio, AUDIO_KEYS, AUDIO_KEYS, f"{context}.audio")
        require_int(
            audio.get("codec_sample_width"),
            f"{context}.audio.codec_sample_width",
            1,
            32,
        )
        if audio.get("channel_select") != "left":
            raise ProfileCheckError(f"{context}.audio.channel_select must be 'left'")
        if audio.get("input_scale_rule") != "signed_rnd_shr_Baudio_minus_N":
            raise ProfileCheckError(f"{context}.audio.input_scale_rule is not the frozen rule")
        if audio.get("master_clock_hz") != 12_288_000:
            raise ProfileCheckError(f"{context}.audio.master_clock_hz must be 12288000")
        require_bool(audio.get("lineout_enable"), f"{context}.audio.lineout_enable")

        codec_control = require_mapping(
            audio.get("codec_control"), f"{context}.audio.codec_control"
        )
        require_exact_keys(
            codec_control,
            CODEC_CONTROL_KEYS,
            CODEC_CONTROL_KEYS,
            f"{context}.audio.codec_control",
        )
        if require_bool(
            codec_control.get("enable"), f"{context}.audio.codec_control.enable"
        ) is not True:
            raise ProfileCheckError(f"{context}.audio.codec_control.enable must be true")
        codec_constants = {
            "codec_model": "wm8731",
            "i2c_bus": "fpga_i2c",
            "i2c_address_7bit": "0x1a",
            "serial_format": "i2s",
            "clock_role": "codec_master",
        }
        for key, expected in codec_constants.items():
            if codec_control.get(key) != expected:
                raise ProfileCheckError(
                    f"{context}.audio.codec_control.{key} must be {expected!r}"
                )
        codec_sample_rate = require_int(
            codec_control.get("sample_rate_hz"),
            f"{context}.audio.codec_control.sample_rate_hz",
            1,
            0xFFFF_FFFF,
        )
        codec_word_width = require_int(
            codec_control.get("word_width_bits"),
            f"{context}.audio.codec_control.word_width_bits",
            1,
            32,
        )
        if codec_sample_rate != sample_rate_hz or codec_sample_rate != 48_000:
            raise ProfileCheckError(
                f"{context}.audio.codec_control.sample_rate_hz must match the 48000 Hz profile rate"
            )
        if codec_word_width != audio.get("codec_sample_width") or codec_word_width != 16:
            raise ProfileCheckError(
                f"{context}.audio.codec_control.word_width_bits must match the 16-bit codec width"
            )

        audio_pll = require_mapping(audio.get("audio_pll"), f"{context}.audio.audio_pll")
        require_exact_keys(
            audio_pll,
            AUDIO_PLL_KEYS,
            AUDIO_PLL_KEYS,
            f"{context}.audio.audio_pll",
        )
        if require_bool(audio_pll.get("enable"), f"{context}.audio.audio_pll.enable") is not True:
            raise ProfileCheckError(f"{context}.audio.audio_pll.enable must be true")
        pll_constants = {
            "reference_clock": "CLOCK_50",
            "reference_clock_hz": 50_000_000,
            "output_clock": "AUD_XCK",
            "output_clock_hz": 12_288_000,
        }
        for key, expected in pll_constants.items():
            if audio_pll.get(key) != expected:
                raise ProfileCheckError(
                    f"{context}.audio.audio_pll.{key} must be {expected!r}"
                )
        if audio_pll.get("output_clock_hz") != audio.get("master_clock_hz"):
            raise ProfileCheckError(
                f"{context}.audio.audio_pll.output_clock_hz must match master_clock_hz"
            )

        hardware_gate = require_mapping(
            audio.get("hardware_gate"), f"{context}.audio.hardware_gate"
        )
        require_exact_keys(
            hardware_gate,
            AUDIO_HARDWARE_GATE_KEYS,
            AUDIO_HARDWARE_GATE_KEYS,
            f"{context}.audio.hardware_gate",
        )
        for key in sorted(AUDIO_HARDWARE_GATE_KEYS):
            if require_bool(
                hardware_gate.get(key), f"{context}.audio.hardware_gate.{key}"
            ) is not True:
                raise ProfileCheckError(f"{context}.audio.hardware_gate.{key} must be true")
    else:
        required = {"kind", "source_mode"}
        require_exact_keys(input_cfg, required, required, context)
        if sample_rate_hz <= 0:
            raise ProfileCheckError(f"{context}: {kind} requires a positive sample_rate_hz")
    return input_cfg


def validate_transport(
    root: Path,
    value: object,
    telemetry_profile: object,
    platform: str,
    context: str,
    contracts: Contracts,
) -> Mapping[str, Any]:
    transport = require_mapping(value, context)
    required = {
        "hps_ddr_enable",
        "hps_udp_enable",
        "command_server_enable",
        "ring_enable_policy",
    }
    require_exact_keys(transport, TRANSPORT_KEYS, required, context)
    hps_ddr = require_bool(transport.get("hps_ddr_enable"), f"{context}.hps_ddr_enable")
    hps_udp = require_bool(transport.get("hps_udp_enable"), f"{context}.hps_udp_enable")
    command_server = require_bool(
        transport.get("command_server_enable"), f"{context}.command_server_enable"
    )
    ring_policy = require_string(
        transport.get("ring_enable_policy"), f"{context}.ring_enable_policy"
    )
    if hps_udp and not hps_ddr:
        raise ProfileCheckError(f"{context}: HPS UDP transport requires the HPS DDR reader")
    if command_server and not hps_udp:
        raise ProfileCheckError(f"{context}: command server requires the HPS transport runtime")
    if (hps_ddr or hps_udp or command_server) and platform != "de1soc":
        raise ProfileCheckError(f"{context}: HPS services are legal only on the de1soc platform")

    optional_paths = {"address_map", "hps_runtime_config", "dashboard_config"}
    present_paths = optional_paths & set(transport)
    if hps_ddr:
        if ring_policy != "after_config_and_rd_commit":
            raise ProfileCheckError(
                f"{context}: DDR ring must use after_config_and_rd_commit enable policy"
            )
        missing = {"address_map", "hps_runtime_config"} - set(transport)
        if missing:
            raise ProfileCheckError(f"{context} is missing HPS/DDR references: {sorted(missing)}")
        for key in sorted(present_paths):
            validate_relative_path(root, transport.get(key), f"{context}.{key}", must_exist=True)
        validate_platform_runtime_refs(root, transport, contracts, context)
    else:
        if ring_policy != "disabled":
            raise ProfileCheckError(
                f"{context}: disabled DDR transport requires ring policy disabled"
            )
        if present_paths:
            raise ProfileCheckError(
                f"{context}: disabled HPS transport must not carry platform paths: "
                f"{sorted(present_paths)}"
            )

    if telemetry_profile is None:
        if hps_ddr or hps_udp or command_server:
            raise ProfileCheckError(
                f"{context}: transport cannot be enabled without telemetry_profile"
            )
    elif not hps_ddr:
        raise ProfileCheckError(f"{context}: DE1-SoC telemetry profile requires the DDR transport")
    return transport


def validate_platform_runtime_refs(
    root: Path,
    transport: Mapping[str, Any],
    contracts: Contracts,
    context: str,
) -> None:
    address_path = validate_relative_path(
        root, transport.get("address_map"), f"{context}.address_map", must_exist=True
    )
    hps_path = validate_relative_path(
        root,
        transport.get("hps_runtime_config"),
        f"{context}.hps_runtime_config",
        must_exist=True,
    )
    address = require_mapping(load_json(address_path), f"{context}.address_map")
    hps = require_mapping(load_json(hps_path), f"{context}.hps_runtime_config")

    hps_version = (
        parse_contract_int(hps.get("transport_version_major"), "HPS transport major"),
        parse_contract_int(hps.get("transport_version_minor"), "HPS transport minor"),
    )
    if hps_version != (contracts.transport_major, contracts.transport_minor):
        raise ProfileCheckError(
            f"{context}: HPS runtime transport version {hps_version[0]}.{hps_version[1]} "
            "does not match generated contracts"
        )

    bridges = require_mapping(address.get("bridges"), "address_map.bridges")
    csr_bridge = require_mapping(bridges.get("csr_bridge"), "address_map.bridges.csr_bridge")
    regions_raw = address.get("regions")
    if not isinstance(regions_raw, list):
        raise ProfileCheckError("address_map.regions must be an array")
    ring_region: Mapping[str, Any] | None = None
    for region_raw in regions_raw:
        region = require_mapping(region_raw, "address_map region")
        if region.get("name") == "telemetry_ddr_ring":
            ring_region = region
            break
    if ring_region is None:
        raise ProfileCheckError("address map is missing telemetry_ddr_ring")

    comparisons = {
        "csr_base_phys": (
            hps.get("csr_base_phys"),
            csr_bridge.get("csr_base_hps_phys"),
        ),
        "csr_span_bytes": (
            hps.get("csr_span_bytes"),
            csr_bridge.get("csr_span_bytes"),
        ),
        "ring_base_hps_phys": (
            hps.get("ring_base_hps_phys"),
            ring_region.get("hps_physical_base"),
        ),
        "ring_base_fpga": (
            hps.get("ring_base_fpga"),
            ring_region.get("fpga_visible_base"),
        ),
        "ring_size_bytes": (
            hps.get("ring_size_bytes"),
            ring_region.get("size_bytes"),
        ),
        "ring_guard_bytes": (
            hps.get("ring_guard_bytes"),
            ring_region.get("guard_bytes"),
        ),
    }
    for name, (hps_value, address_value) in comparisons.items():
        left = parse_contract_int(hps_value, f"HPS {name}")
        right = parse_contract_int(address_value, f"address-map {name}")
        if left != right:
            raise ProfileCheckError(
                f"{context}: HPS/address-map mismatch for {name}: {left:#x} != {right:#x}"
            )

    ring_hps_base = parse_contract_int(hps.get("ring_base_hps_phys"), "HPS ring base")
    ring_fpga_base = parse_contract_int(hps.get("ring_base_fpga"), "FPGA ring base")
    ring_size = parse_contract_int(hps.get("ring_size_bytes"), "ring size")
    ring_guard = parse_contract_int(hps.get("ring_guard_bytes"), "ring guard")
    if ring_size < contracts.ring_size_min or ring_size & (ring_size - 1):
        raise ProfileCheckError(
            f"{context}: ring size must be a power of two and at least {contracts.ring_size_min}"
        )
    if ring_size % contracts.ring_alignment != 0:
        raise ProfileCheckError(
            f"{context}: ring size must be aligned to {contracts.ring_alignment} bytes"
        )
    if ring_hps_base % contracts.ring_alignment or ring_fpga_base % contracts.ring_alignment:
        raise ProfileCheckError(
            f"{context}: HPS and FPGA ring bases must be {contracts.ring_alignment}-byte aligned"
        )
    if ring_guard < contracts.ring_guard_min:
        raise ProfileCheckError(
            f"{context}: ring guard must be at least {contracts.ring_guard_min} bytes"
        )

    network = require_mapping(address.get("runtime_network"), "address_map.runtime_network")
    network_fields = {
        "telemetry_dst_port": "telemetry_dst_port",
        "command_listen_port": "command_listen_port",
        "transport_version_major": "transport_version_major",
        "transport_version_minor": "transport_version_minor",
    }
    for hps_key, address_key in network_fields.items():
        left = parse_contract_int(hps.get(hps_key), f"HPS {hps_key}")
        right = parse_contract_int(network.get(address_key), f"address-map {address_key}")
        if left != right:
            raise ProfileCheckError(
                f"{context}: HPS/address-map mismatch for {hps_key}: {left} != {right}"
            )


def validate_build_profile(
    root: Path,
    profile: Mapping[str, Any],
    path: Path,
    contracts: Contracts,
    cache: dict[Path, Mapping[str, Any]],
) -> None:
    require_exact_keys(profile, BUILD_PROFILE_KEYS, BUILD_PROFILE_KEYS, str(path))
    profile_name, _ = validate_identity(profile, path)
    validate_version(profile, path, contracts)
    build = validate_build_block(root, profile.get("build"), f"{path}.build")
    validate_contract_refs(root, profile.get("contract_refs"), f"{path}.contract_refs")
    sample_rate = require_int(
        profile.get("sample_rate_hz"), f"{path}.sample_rate_hz", 0, 0xFFFF_FFFF
    )
    input_cfg = validate_input_block(
        root, profile.get("input"), sample_rate, f"{path}.input", contracts
    )

    telemetry_ref = profile.get("telemetry_profile")
    if telemetry_ref is not None:
        telemetry_path = validate_relative_path(
            root, telemetry_ref, f"{path}.telemetry_profile", must_exist=True
        )
        expected_dir = (root / PROFILE_DIR).resolve()
        if telemetry_path.parent != expected_dir:
            raise ProfileCheckError(f"{path}.telemetry_profile must refer to config/profiles/")
        telemetry = cache.get(telemetry_path)
        if telemetry is None:
            telemetry = require_mapping(load_json(telemetry_path), str(telemetry_path))
            validate_telemetry_preset(telemetry, telemetry_path, contracts)
            cache[telemetry_path] = telemetry
        if telemetry.get("profile_kind") != "telemetry_preset":
            raise ProfileCheckError(
                f"{path}.telemetry_profile does not refer to a telemetry preset"
            )

    validate_transport(
        root,
        profile.get("transport"),
        telemetry_ref,
        str(build.get("platform")),
        f"{path}.transport",
        contracts,
    )

    expected_roles = {
        "baseline_core": ("core_only", "external_stream", None),
        "sim_core_only": ("bram_replay", "bram_replay", None),
        "de1soc_bram_replay": (
            "de1soc_full",
            "bram_replay",
            "config/profiles/telemetry_status_only.json",
        ),
        "de1soc_linein_demo": (
            "de1soc_full",
            "audio_wrapper",
            "config/profiles/telemetry_full_demo.json",
        ),
        "de1soc_adc_demo": (
            "de1soc_full",
            "adc_live",
            "config/profiles/telemetry_full_demo.json",
        ),
    }
    expected_target, expected_input, expected_telemetry = expected_roles[profile_name]
    actual_role = (build.get("target"), input_cfg.get("kind"), telemetry_ref)
    if actual_role != (expected_target, expected_input, expected_telemetry):
        raise ProfileCheckError(
            f"{path}: role drift; expected target/input/telemetry "
            f"{(expected_target, expected_input, expected_telemetry)}, got {actual_role}"
        )


def optional_jsonschema_validate(
    root: Path, profiles: Iterable[tuple[Path, Mapping[str, Any]]]
) -> None:
    try:
        import jsonschema  # type: ignore[import-not-found]
    except ModuleNotFoundError:
        return
    schema_path = root / PROFILE_SCHEMA_PATH
    schema = load_json(schema_path)
    validator = jsonschema.Draft202012Validator(schema)
    for path, profile in profiles:
        errors = sorted(validator.iter_errors(profile), key=lambda item: list(item.absolute_path))
        if errors:
            detail = errors[0]
            location = ".".join(str(part) for part in detail.absolute_path) or "<root>"
            raise ProfileCheckError(
                f"{path}: schema validation failed at {location}: {detail.message}"
            )


def packet_mask(profile: Mapping[str, Any], contracts: Contracts) -> int:
    mask = 0
    for name in profile.get("packet_enable", []):
        mask |= contracts.packet_masks[str(name)]
    return mask


def effective_profile(
    root: Path,
    profile: Mapping[str, Any],
    profile_path: Path,
    contracts: Contracts,
) -> Mapping[str, Any]:
    if profile.get("profile_kind") != "build":
        raise ProfileCheckError("--print-effective requires a build profile, not a preset")
    telemetry_ref = profile.get("telemetry_profile")
    if telemetry_ref is None:
        telemetry: Mapping[str, Any] = {
            "packet_enable": [],
            "spec_mode": "DISABLED",
            "wave_decim": contracts.wave_decim_min,
            "spec_shift": 0,
            "status_rate_hz": 0,
            "metrics_rate_hz": 0,
        }
        telemetry_sha256 = None
    else:
        telemetry_path = validate_relative_path(
            root, telemetry_ref, "telemetry_profile", must_exist=True
        )
        telemetry = require_mapping(load_json(telemetry_path), str(telemetry_path))
        telemetry_sha256 = hashlib.sha256(telemetry_path.read_bytes()).hexdigest()
    source_mode = require_mapping(profile.get("input"), "input").get("source_mode")
    spec_contract_name = SPEC_MODE_PROFILE_TO_CONTRACT[str(telemetry["spec_mode"])]
    return {
        "schema": "trecap_phase2_effective_profile_v1",
        "source_profile": profile_path.relative_to(root).as_posix(),
        "source_profile_sha256": hashlib.sha256(profile_path.read_bytes()).hexdigest(),
        "profile_name": profile["profile_name"],
        "build": profile["build"],
        "contract_refs": profile["contract_refs"],
        "input": profile["input"],
        "source_mode_value": (
            None if source_mode is None else contracts.source_modes[str(source_mode)]
        ),
        "sample_rate_hz": profile["sample_rate_hz"],
        "telemetry_profile": telemetry_ref,
        "telemetry_profile_sha256": telemetry_sha256,
        "packet_enable": telemetry["packet_enable"],
        "packet_enable_mask": f"0x{packet_mask(telemetry, contracts):08x}",
        "spec_mode": telemetry["spec_mode"],
        "spec_mode_value": contracts.spec_modes[spec_contract_name],
        "wave_decim": telemetry["wave_decim"],
        "spec_shift": telemetry["spec_shift"],
        "status_rate_hz": telemetry["status_rate_hz"],
        "metrics_rate_hz": telemetry["metrics_rate_hz"],
        "transport": profile["transport"],
        "transport_version_major": contracts.transport_major,
        "transport_version_minor": contracts.transport_minor,
    }


def resolve_cli_profile(root: Path, value: str) -> Path:
    candidate = Path(value)
    path = candidate.resolve() if candidate.is_absolute() else (root / candidate).resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise ProfileCheckError(f"profile path escapes the repository root: {value}") from exc
    if not path.is_file():
        raise ProfileCheckError(f"profile file does not exist: {value}")
    if path.parent != (root / PROFILE_DIR).resolve():
        raise ProfileCheckError(f"profile must reside directly under {PROFILE_DIR}: {value}")
    return path


def validate_paths(
    root: Path,
    paths: Sequence[Path],
    contracts: Contracts,
) -> dict[Path, Mapping[str, Any]]:
    cache: dict[Path, Mapping[str, Any]] = {}
    loaded: list[tuple[Path, Mapping[str, Any]]] = []
    for path in paths:
        profile = require_mapping(load_json(path), str(path))
        profile_kind = str(profile.get("profile_kind", ""))
        if profile_kind == "telemetry_preset":
            validate_telemetry_preset(profile, path, contracts)
        elif profile_kind == "build":
            validate_build_profile(root, profile, path, contracts, cache)
        else:
            raise ProfileCheckError(f"{path}: unknown profile_kind {profile_kind!r}")
        cache[path] = profile
        loaded.append((path, profile))
    optional_jsonschema_validate(root, loaded)
    return cache


def all_profile_paths(root: Path) -> list[Path]:
    profile_dir = root / PROFILE_DIR
    if not profile_dir.is_dir():
        raise ProfileCheckError(f"profile directory is missing: {PROFILE_DIR}")
    expected = {profile_dir / name for name in REQUIRED_PROFILE_FILES}
    actual = set(profile_dir.glob("*.json"))
    missing = sorted(path.name for path in expected - actual)
    extra = sorted(path.name for path in actual - expected)
    if missing:
        raise ProfileCheckError(f"required profiles are missing: {missing}")
    if extra:
        raise ProfileCheckError(f"unexpected profile JSON files are present: {extra}")
    return [profile_dir / name for name in REQUIRED_PROFILE_FILES]


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate T-RECAP runtime/build profiles against generated contracts."
    )
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument(
        "--all", action="store_true", help="Validate the frozen seven-profile inventory."
    )
    selection.add_argument("--profile", help="Validate one profile and its referenced preset.")
    parser.add_argument(
        "--print-effective",
        action="store_true",
        help="Print the normalized effective JSON for one build profile.",
    )
    parser.add_argument(
        "--require-build",
        action="store_true",
        help="Reject a telemetry preset; intended for synthesis/build entry points.",
    )
    parser.add_argument("--expect-target", help="Require the selected build.target value.")
    parser.add_argument("--expect-top", help="Require the selected build.top_module value.")
    parser.add_argument("--expect-platform", help="Require the selected build.platform value.")
    parser.add_argument(
        "--expect-profile-name", help="Require the selected top-level profile_name value."
    )
    parser.add_argument(
        "--expect-input-kind", help="Require the selected input.kind value."
    )
    parser.add_argument(
        "--expect-project",
        help="Require the selected build.quartus_project repository-relative base path.",
    )
    parser.add_argument("--root", default=None, help="Repository root; defaults to script parent.")
    parser.add_argument("--quiet", action="store_true", help="Suppress the success summary.")
    args = parser.parse_args(argv)

    try:
        root = Path(args.root).resolve() if args.root else repo_root_from_script()
        if not (root / "Makefile").is_file():
            raise ProfileCheckError(f"repository root does not look valid: {root}")
        schema = require_mapping(load_json(root / PROFILE_SCHEMA_PATH), PROFILE_SCHEMA_PATH)
        if schema.get("$id") != "https://trecap.local/schemas/runtime_profile.schema.json":
            raise ProfileCheckError(f"{PROFILE_SCHEMA_PATH} has an unexpected $id")
        contracts = load_contracts(root)

        if args.profile:
            paths = [resolve_cli_profile(root, args.profile)]
        else:
            paths = all_profile_paths(root)
        profiles = validate_paths(root, paths, contracts)

        if (
            args.require_build
            or args.expect_target
            or args.expect_top
            or args.expect_platform
            or args.expect_project
            or args.expect_profile_name
            or args.expect_input_kind
        ):
            if not args.profile:
                raise ProfileCheckError("build expectations require --profile")
            selected = profiles[paths[0]]
            if selected.get("profile_kind") != "build":
                raise ProfileCheckError(
                    "selected profile is a telemetry preset, not a build profile"
                )
            build = require_mapping(selected.get("build"), "selected profile build")
            expectations = {
                "target": args.expect_target,
                "top_module": args.expect_top,
                "platform": args.expect_platform,
                "quartus_project": args.expect_project,
            }
            for key, expected in expectations.items():
                if expected is not None and build.get(key) != expected:
                    raise ProfileCheckError(
                        f"selected profile build.{key} is {build.get(key)!r}; expected {expected!r}"
                    )
            if (
                args.expect_profile_name is not None
                and selected.get("profile_name") != args.expect_profile_name
            ):
                raise ProfileCheckError(
                    "selected profile_name is "
                    f"{selected.get('profile_name')!r}; expected {args.expect_profile_name!r}"
                )
            selected_input = require_mapping(selected.get("input"), "selected profile input")
            if (
                args.expect_input_kind is not None
                and selected_input.get("kind") != args.expect_input_kind
            ):
                raise ProfileCheckError(
                    "selected profile input.kind is "
                    f"{selected_input.get('kind')!r}; expected {args.expect_input_kind!r}"
                )

        if args.print_effective:
            if not args.profile:
                raise ProfileCheckError("--print-effective requires --profile")
            path = paths[0]
            resolved = effective_profile(root, profiles[path], path, contracts)
            print(json.dumps(resolved, indent=2, sort_keys=True))
        elif not args.quiet:
            builds = sum(
                1 for profile in profiles.values() if profile.get("profile_kind") == "build"
            )
            presets = sum(
                1
                for profile in profiles.values()
                if profile.get("profile_kind") == "telemetry_preset"
            )
            print(
                f"check_profiles: OK ({len(paths)} requested, "
                f"{builds} build profiles, {presets} telemetry presets)"
            )
        return 0
    except ProfileCheckError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
