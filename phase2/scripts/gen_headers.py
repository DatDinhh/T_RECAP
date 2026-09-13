#!/usr/bin/env python3
"""Generate T-RECAP Phase 2 SV/C/Python contract headers.

File class: [1] hand-written generator script.

Inputs:
  spec/generated/csr_map.json
  spec/generated/packet_layouts.json
  spec/generated/interface_types.json
  optional spec/generated/core_config.json
  optional spec/generated/width_config.json
  optional spec/generated/artifact_contract.json

Outputs:
  spec/generated/gen_manifest.json
  rtl/include/generated/trecap_core_pkg.sv
  rtl/include/generated/trecap_csr_pkg.sv
  rtl/include/generated/trecap_packet_pkg.sv
  rtl/include/generated/trecap_iface_pkg.sv
  sw/hps/include/generated/trecap_csr.h
  sw/hps/include/generated/trecap_packet.h
  sw/pc_dashboard/generated/trecap_packet.py
  sw/reference_model/generated/trecap_config.py
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, MutableMapping, Optional, Sequence, Tuple

try:
    import jsonschema
except Exception:  # pragma: no cover - intentionally optional for bare lab machines
    jsonschema = None  # type: ignore[assignment]

GENERATOR_VERSION = "r1.2.0"
GENERATOR_PATH = "scripts/gen_headers.py"
MANIFEST_PATH = "spec/generated/gen_manifest.json"

# Step 14 extends the CSR map above 0x088, but the established register surface
# through PACKET_FIFO_DROP_COUNT remains a compatibility boundary.  Keep this
# digest in executable code rather than trusting source-owned metadata: changing
# a legacy register and updating the JSON claim in the same patch must still be
# rejected.  The digest covers each complete raw register object, including
# descriptions, access/owner/reset, validity/write semantics, and nested fields.
LEGACY_CSR_FIRST_OFFSET = 0x000
LEGACY_CSR_LAST_OFFSET = 0x088
LEGACY_CSR_REGISTER_COUNT = 35
LEGACY_CSR_CANONICALIZATION = (
    "json_sorted_keys_compact_utf8_full_register_objects_sorted_by_numeric_offset"
)
LEGACY_CSR_SEMANTIC_SHA256 = (
    "1169ac8154dfd510598efd17bacfc356cd694d86da791f083b9ec290f1ac424d"
)
STEP14_CSR_EXTENSION_FIRST_OFFSET = 0x08C
STEP14_CSR_EXTENSION_LAST_OFFSET = 0x094
STEP14_CSR_EXTENSION_REGISTER_COUNT = 3
STEP14_CSR_EXTENSION_SEMANTIC_SHA256 = (
    "d671c1aca84f2e811419608070886f6b78e74e6f5d0c9ac95acb73d99e3780f2"
)

SOURCE_PATHS = {
    "core_config": "spec/generated/core_config.json",
    "width_config": "spec/generated/width_config.json",
    "artifact_contract": "spec/generated/artifact_contract.json",
    "csr_map": "spec/generated/csr_map.json",
    "packet_layouts": "spec/generated/packet_layouts.json",
    "interface_types": "spec/generated/interface_types.json",
}

SCHEMA_PATHS = {
    "csr_map": "spec/schemas/csr_map.schema.json",
    "packet_layouts": "spec/schemas/packet_layouts.schema.json",
    "interface_types": "spec/schemas/interface_types.schema.json",
    "core_config": "spec/schemas/core_config.schema.json",
}

OUTPUT_PATHS = [
    "rtl/include/generated/trecap_core_pkg.sv",
    "rtl/include/generated/trecap_csr_pkg.sv",
    "rtl/include/generated/trecap_packet_pkg.sv",
    "rtl/include/generated/trecap_iface_pkg.sv",
    "sw/hps/include/generated/trecap_csr.h",
    "sw/hps/include/generated/trecap_packet.h",
    "sw/pc_dashboard/generated/trecap_packet.py",
    "sw/reference_model/generated/trecap_config.py",
]

DEFAULT_CORE_CONFIG: Dict[str, Any] = {
    "configuration": {
        "N": 12,
        "L": 256,
        "P": 8,
        "H": 128,
        "F": 15,
        "G": 128,
        "D": 384,
        "PROTECT_DC": 1,
        "PROTECT_NYQ": 0,
    },
    "widths": {
        "W_Qw": 16,
        "W_tw": 17,
        "W_u": 27,
        "W_fft": 28,
        "W_fft_pre": 29,
        "W_can_pre": 29,
        "W_can": 28,
        "W_mag2": 56,
        "W_ifft": 36,
        "W_z": 36,
        "W_ola": 37,
    },
    "contract": {
        "fft_mode": "custom_radix2_dit_bitrev_in_natural_out",
        "rounding_mode": "round_nearest_ties_away_from_zero",
        "tail_policy": "full_tail",
        "threshold_mapping": "raw_thr2",
    },
}


def repo_root_from_script() -> Path:
    return Path(__file__).resolve().parents[1]


def fail(message: str) -> None:
    raise SystemExit(f"ERROR: {message}")


def load_json(path: Path) -> Any:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError as exc:
        fail(f"invalid JSON in {path}: {exc}")
    except OSError as exc:
        fail(f"cannot read {path}: {exc}")


def canonical_json_bytes(data: Any) -> bytes:
    return (json.dumps(data, indent=2, sort_keys=True) + "\n").encode("utf-8")


def canonical_compact_json_bytes(data: Any) -> bytes:
    """Canonical bytes used by immutable semantic-snapshot checks."""

    return json.dumps(
        data,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def relpath(root: Path, path: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def safe_join(root: Path, rel: str) -> Path:
    path = (root / rel).resolve()
    try:
        path.relative_to(root.resolve())
    except ValueError:
        fail(f"output path escapes repository root: {rel}")
    return path


def validate_schema(root: Path, name: str, data: Any, warnings: List[str]) -> None:
    schema_rel = SCHEMA_PATHS.get(name)
    if not schema_rel:
        return
    schema_path = root / schema_rel
    if not schema_path.exists():
        warnings.append(f"schema missing for {name}: {schema_rel}; skipped JSON Schema validation")
        return
    if jsonschema is None:
        # Tool availability is runtime evidence, not generated design content.  Keeping it out of
        # gen_manifest.json makes the checked outputs byte-identical on a bare lab machine and in
        # the dependency-locked verification environment.  The invocation still reports the
        # skipped optional validation on stderr below.
        return
    schema = load_json(schema_path)
    try:
        jsonschema.Draft202012Validator(schema).validate(data)
    except Exception as exc:
        fail(f"{SOURCE_PATHS[name]} does not validate against {schema_rel}: {exc}")


def parse_int(value: Any) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        text = value.strip().replace("_", "")
        m = re.fullmatch(r"(\d+)'([hHdDbB])([0-9a-fA-FxXzZ]+)", text)
        if m:
            base = {"h": 16, "d": 10, "b": 2}[m.group(2).lower()]
            digits = m.group(3).lower().replace("x", "0").replace("z", "0")
            return int(digits, base)
        if text.lower().startswith("0x"):
            return int(text, 16)
        return int(text, 10)
    raise TypeError(f"cannot parse integer from {value!r}")


def sv_uint(value: int, width: int = 32, base: str = "h") -> str:
    if value < 0:
        fail(f"negative value cannot be emitted as unsigned literal: {value}")
    if base == "d":
        return f"{width}'d{value}"
    digits = max(1, (width + 3) // 4)
    return f"{width}'h{value:0{digits}x}"


def c_uint(value: int, bits: int = 32) -> str:
    if bits <= 32:
        return f"UINT32_C(0x{value & 0xFFFFFFFF:08x})"
    return f"UINT64_C(0x{value & 0xFFFFFFFFFFFFFFFF:016x})"


def sanitize_upper(name: str) -> str:
    out = re.sub(r"[^A-Za-z0-9]+", "_", name).strip("_").upper()
    out = re.sub(r"_+", "_", out)
    if not out:
        fail(f"cannot sanitize empty name from {name!r}")
    if out[0].isdigit():
        out = "N_" + out
    return out


def field_mask(lsb: int, msb: int) -> int:
    if msb < lsb:
        fail(f"invalid bit range msb {msb} < lsb {lsb}")
    return ((1 << (msb - lsb + 1)) - 1) << lsb


def banner(comment: str, generator: str = GENERATOR_PATH) -> str:
    if comment == "sv" or comment == "py":
        prefix = "//" if comment == "sv" else "#"
        return "\n".join(
            [
                f"{prefix} AUTO-GENERATED - DO NOT EDIT",
                f"{prefix} Generator: {generator}",
                f"{prefix} Generator version: {GENERATOR_VERSION}",
                f"{prefix} Source manifest: {MANIFEST_PATH}",
                "",
            ]
        )
    if comment == "c":
        return (
            "/* AUTO-GENERATED - DO NOT EDIT\n"
            f" * Generator: {generator}\n"
            f" * Generator version: {GENERATOR_VERSION}\n"
            f" * Source manifest: {MANIFEST_PATH}\n"
            " */\n\n"
        )
    fail(f"unknown banner type: {comment}")
    return ""


def core_dict_from_sources(root: Path, sources: Mapping[str, Any], warnings: List[str]) -> Dict[str, Any]:
    cfg = copy.deepcopy(DEFAULT_CORE_CONFIG)
    core = sources.get("core_config")
    if core is None:
        warnings.append(
            "spec/generated/core_config.json missing; generated trecap_core_pkg.sv uses Revision J bootstrap constants"
        )
    else:
        for key in ("configuration", "contract", "hashes", "stream_hashes", "artifact_rows"):
            if isinstance(core, Mapping) and isinstance(core.get(key), Mapping):
                cfg.setdefault(key, {}).update(core[key])
        if isinstance(core, Mapping) and isinstance(core.get("widths"), Mapping):
            cfg.setdefault("widths", {}).update(core["widths"])
        # Some reference packages use flat names. Accept those without changing the schema.
        for key in ["N", "L", "P", "H", "F", "G", "D", "PROTECT_DC", "PROTECT_NYQ"]:
            if isinstance(core, Mapping) and key in core:
                cfg["configuration"][key] = core[key]

    width_cfg = sources.get("width_config")
    if isinstance(width_cfg, Mapping):
        if isinstance(width_cfg.get("widths"), Mapping):
            cfg["widths"].update(width_cfg["widths"])
        else:
            for key, value in width_cfg.items():
                if key.startswith("W_") or key.startswith("W"):
                    cfg["widths"][key] = value

    config = cfg["configuration"]
    width = cfg["widths"]
    config["D"] = parse_int(config.get("D", parse_int(config["L"]) + parse_int(config["G"])))
    expected_d = parse_int(config["L"]) + parse_int(config["G"])
    if parse_int(config["D"]) != expected_d:
        fail(f"core delay D must equal L + G: D={config['D']} L+G={expected_d}")
    if parse_int(config["H"]) * 2 != parse_int(config["L"]):
        warnings.append("baseline expects H=L/2; source core_config currently differs")
    if parse_int(width.get("W_mag2", 0)) != 2 * parse_int(width.get("W_can", 0)):
        warnings.append("baseline expects W_mag2 = 2*W_can; source width_config currently differs")
    return cfg


def check_csr(csr: Mapping[str, Any]) -> None:
    regs = csr.get("registers")
    if not isinstance(regs, list) or not regs:
        fail("csr_map.json must contain a non-empty registers array")
    offsets: Dict[int, str] = {}
    ordered_offsets: List[int] = []
    for index, reg in enumerate(regs):
        if not isinstance(reg, Mapping):
            fail(f"CSR register entry {index} must be an object")
        name = reg.get("name")
        if not isinstance(name, str) or not name:
            fail(f"CSR register entry {index} must have a non-empty string name")
        raw_offset = reg.get("offset")
        if isinstance(raw_offset, bool) or not isinstance(raw_offset, int):
            fail(f"CSR register {name} offset must be an integer")
        off = raw_offset
        if off % 4:
            fail(f"CSR register {name} offset 0x{off:x} is not 32-bit aligned")
        if off in offsets:
            fail(f"duplicate CSR offset 0x{off:x}: {offsets[off]} and {name}")
        offsets[off] = name
        ordered_offsets.append(off)

        offset_hex = reg.get("offset_hex")
        canonical_offset_hex = f"0x{off:03X}"
        if not isinstance(offset_hex, str):
            fail(f"CSR register {name} offset_hex must be a string")
        try:
            offset_hex_value = parse_int(offset_hex)
        except (TypeError, ValueError):
            fail(f"CSR register {name} has invalid offset_hex {offset_hex!r}")
        if offset_hex_value != off:
            fail(
                f"CSR register {name} offset_hex {offset_hex!r} does not match "
                f"numeric offset 0x{off:03X}"
            )
        if offset_hex != canonical_offset_hex:
            fail(
                f"CSR register {name} offset_hex must use canonical uppercase form "
                f"{canonical_offset_hex}, got {offset_hex!r}"
            )

        seen_fields: set[str] = set()
        fields = reg.get("fields", [])
        if not isinstance(fields, list):
            fail(f"CSR register {name} fields must be an array")
        for field_index, field in enumerate(fields):
            if not isinstance(field, Mapping):
                fail(f"CSR field {name}[{field_index}] must be an object")
            fname = field.get("name")
            if not isinstance(fname, str) or not fname:
                fail(f"CSR field {name}[{field_index}] must have a non-empty string name")
            if fname in seen_fields:
                fail(f"duplicate field {name}.{fname}")
            seen_fields.add(fname)
            raw_lsb = field.get("lsb")
            raw_msb = field.get("msb", raw_lsb)
            if isinstance(raw_lsb, bool) or not isinstance(raw_lsb, int):
                fail(f"CSR field {name}.{fname} lsb must be an integer")
            if isinstance(raw_msb, bool) or not isinstance(raw_msb, int):
                fail(f"CSR field {name}.{fname} msb must be an integer")
            lsb = raw_lsb
            msb = raw_msb
            if not (0 <= lsb <= msb < 32):
                fail(f"illegal CSR field range {name}.{fname}[{msb}:{lsb}]")

    if ordered_offsets != sorted(ordered_offsets):
        fail("CSR registers must be sorted by strictly increasing numeric offset")

    expected_legacy_offsets = list(
        range(LEGACY_CSR_FIRST_OFFSET, LEGACY_CSR_LAST_OFFSET + 4, 4)
    )
    legacy_regs = [
        reg
        for reg in regs
        if isinstance(reg, Mapping)
        and isinstance(reg.get("offset"), int)
        and not isinstance(reg.get("offset"), bool)
        and LEGACY_CSR_FIRST_OFFSET <= reg["offset"] <= LEGACY_CSR_LAST_OFFSET
    ]
    legacy_offsets = [int(reg["offset"]) for reg in legacy_regs]
    if legacy_offsets != expected_legacy_offsets:
        fail(
            "legacy CSR compatibility slice must contain exactly the sorted offsets "
            "0x000..0x088 at 4-byte spacing"
        )
    if len(legacy_regs) != LEGACY_CSR_REGISTER_COUNT:
        fail(
            f"legacy CSR compatibility slice must contain {LEGACY_CSR_REGISTER_COUNT} "
            f"registers, got {len(legacy_regs)}"
        )

    expected_freeze = {
        "first_offset": LEGACY_CSR_FIRST_OFFSET,
        "last_offset": LEGACY_CSR_LAST_OFFSET,
        "first_offset_hex": f"0x{LEGACY_CSR_FIRST_OFFSET:03X}",
        "last_offset_hex": f"0x{LEGACY_CSR_LAST_OFFSET:03X}",
        "register_count": LEGACY_CSR_REGISTER_COUNT,
        "canonicalization": LEGACY_CSR_CANONICALIZATION,
        "sha256": LEGACY_CSR_SEMANTIC_SHA256,
    }
    if csr.get("legacy_register_freeze") != expected_freeze:
        fail(
            "csr_map.json legacy_register_freeze must exactly describe the executable "
            "0x000..0x088 compatibility snapshot"
        )
    legacy_digest = sha256_bytes(canonical_compact_json_bytes(legacy_regs))
    if legacy_digest != LEGACY_CSR_SEMANTIC_SHA256:
        fail(
            "legacy CSR semantics changed in 0x000..0x088: expected semantic SHA-256 "
            f"{LEGACY_CSR_SEMANTIC_SHA256}, got {legacy_digest}"
        )

    step14_extension_regs = [
        reg
        for reg in regs
        if isinstance(reg, Mapping)
        and isinstance(reg.get("offset"), int)
        and not isinstance(reg.get("offset"), bool)
        and STEP14_CSR_EXTENSION_FIRST_OFFSET
        <= reg["offset"]
        <= STEP14_CSR_EXTENSION_LAST_OFFSET
    ]
    expected_step14_extension_offsets = list(
        range(
            STEP14_CSR_EXTENSION_FIRST_OFFSET,
            STEP14_CSR_EXTENSION_LAST_OFFSET + 4,
            4,
        )
    )
    if [int(reg["offset"]) for reg in step14_extension_regs] != expected_step14_extension_offsets:
        fail("Step-14 CSR extension must contain exactly sorted offsets 0x08C, 0x090, 0x094")
    if len(step14_extension_regs) != STEP14_CSR_EXTENSION_REGISTER_COUNT:
        fail(
            "Step-14 CSR extension must contain exactly "
            f"{STEP14_CSR_EXTENSION_REGISTER_COUNT} registers"
        )
    step14_extension_digest = sha256_bytes(
        canonical_compact_json_bytes(step14_extension_regs)
    )
    if step14_extension_digest != STEP14_CSR_EXTENSION_SEMANTIC_SHA256:
        fail(
            "Step-14 CSR extension semantics changed: expected semantic SHA-256 "
            f"{STEP14_CSR_EXTENSION_SEMANTIC_SHA256}, got {step14_extension_digest}"
        )

    version = csr.get("constants", {}).get("VERSION", {})
    if version:
        packed = (parse_int(version["major"]) << 16) | parse_int(version["minor"])
        if packed != parse_int(version["packed_hex"]):
            fail("VERSION packed value does not match major/minor")


def check_packets(packet: Mapping[str, Any]) -> None:
    seen: Dict[int, str] = {}
    for pkt in packet.get("packet_types", []):
        code = parse_int(pkt["code"])
        if code in seen:
            fail(f"duplicate packet type code 0x{code:04x}: {seen[code]} and {pkt['name']}")
        seen[code] = pkt["name"]
    transport = packet.get("transport", {})
    max_udp = parse_int(transport.get("udp_no_fragment_payload_max_bytes", 1200))
    header = parse_int(transport.get("telemetry_header_bytes", 32))
    for name, payload in packet.get("payloads", {}).items():
        rule = payload.get("payload_size_rule", {})
        if rule.get("kind") == "exact":
            payload_bytes = parse_int(rule["bytes"])
            if header + payload_bytes > max_udp and name != "WRAP":
                fail(f"{name} payload exceeds UDP no-fragment bound")
        elif rule.get("kind") == "variable":
            max_bytes = parse_int(rule["max_bytes"])
            if header + max_bytes > max_udp:
                fail(f"{name} max payload exceeds UDP no-fragment bound")
    cmds = packet.get("command_packet", {}).get("command_types", [])
    seen_cmds: Dict[int, str] = {}
    for cmd in cmds:
        code = parse_int(cmd["code"])
        if code in seen_cmds:
            fail(f"duplicate command code 0x{code:04x}: {seen_cmds[code]} and {cmd['name']}")
        seen_cmds[code] = cmd["name"]


def check_iface(iface: Mapping[str, Any]) -> None:
    enum_names: set[str] = set()
    for enum in iface.get("enums", []):
        ename = enum["name"]
        if ename in enum_names:
            fail(f"duplicate enum {ename}")
        enum_names.add(ename)
        values: set[str] = set()
        for val in enum.get("values", []):
            if val["name"] in values:
                fail(f"duplicate enum value {ename}.{val['name']}")
            values.add(val["name"])
    struct_names: set[str] = set()
    for struct in iface.get("structs", []):
        sname = struct["name"]
        if sname in struct_names:
            fail(f"duplicate struct {sname}")
        struct_names.add(sname)
        fields: set[str] = set()
        for field in struct.get("fields", []):
            fname = field["name"]
            if fname in fields:
                fail(f"duplicate struct field {sname}.{fname}")
            fields.add(fname)


def gen_core_pkg(core: Mapping[str, Any]) -> str:
    cfg = core["configuration"]
    widths = core["widths"]
    lines = [banner("sv"), "package trecap_core_pkg;", ""]
    consts = [
        ("T_SAMPLE_W", "N", "External signed input/output sample width."),
        ("T_FFT_L", "L", "FFT length."),
        ("T_FFT_P", "P", "Number of radix-2 stages."),
        ("T_HOP_H", "H", "Hop size."),
        ("T_FRAC_F", "F", "Fixed-point fractional width."),
        ("T_CUSHION_G", "G", "Scheduling cushion."),
        ("T_DELAY_D", "D", "Exact causal delay L+G."),
    ]
    lines.append("  // Core baseline parameters.")
    for out_name, src_key, comment in consts:
        lines.append(f"  localparam int unsigned {out_name:<22} = {parse_int(cfg[src_key])};  // {comment}")
    lines.append(f"  localparam bit          T_PROTECT_DC           = {parse_int(cfg.get('PROTECT_DC', 1))};")
    lines.append(f"  localparam bit          T_PROTECT_NYQ          = {parse_int(cfg.get('PROTECT_NYQ', 0))};")
    lines.append("")
    lines.append("  // Fixed-point and internal width schedule.")
    width_map = [
        ("T_QW_W", "W_Qw"),
        ("T_TWIDDLE_W", "W_tw"),
        ("T_U_W", "W_u"),
        ("T_FFT_W", "W_fft"),
        ("T_FFT_PRE_W", "W_fft_pre"),
        ("T_CAN_PRE_W", "W_can_pre"),
        ("T_CAN_W", "W_can"),
        ("T_MAG2_W", "W_mag2"),
        ("T_IFFT_W", "W_ifft"),
        ("T_Z_W", "W_z"),
        ("T_OLA_W", "W_ola"),
    ]
    for out_name, src_key in width_map:
        lines.append(f"  localparam int unsigned {out_name:<22} = {parse_int(widths[src_key])};")
    lines.append("")
    lines.append("  // Derived constants used by core, telemetry taps, and artifact consumers.")
    lines.append("  localparam int unsigned T_UNIQUE_BINS          = (T_FFT_L/2) + 1;")
    lines.append("  localparam int unsigned T_SELF_CONJ_DC_BIN     = 0;")
    lines.append("  localparam int unsigned T_SELF_CONJ_NYQ_BIN    = T_FFT_L/2;")
    lines.append("  localparam logic [T_MAG2_W-1:0] T_THR2_RESET   = '0;")
    lines.append("  localparam int signed   T_SAMPLE_MIN           = -(1 << (T_SAMPLE_W-1));")
    lines.append("  localparam int signed   T_SAMPLE_MAX           =  (1 << (T_SAMPLE_W-1)) - 1;")
    lines.append("")
    lines.append("endpackage : trecap_core_pkg")
    return "\n".join(lines) + "\n"


def gen_csr_pkg(csr: Mapping[str, Any]) -> str:
    lines = [banner("sv"), "package trecap_csr_pkg;", ""]
    constants = csr.get("constants", {})
    version = constants.get("VERSION", {})
    lines.append("  // Transport identity and version.")
    if "ID" in constants:
        lines.append(f"  localparam logic [31:0] TCSR_ID_VALUE = {sv_uint(parse_int(constants['ID']['value_hex']), 32)};")
    if version:
        lines.append(f"  localparam int unsigned TCSR_VERSION_MAJOR = {parse_int(version['major'])};")
        lines.append(f"  localparam int unsigned TCSR_VERSION_MINOR = {parse_int(version['minor'])};")
        lines.append(f"  localparam logic [31:0] TCSR_VERSION_VALUE = {sv_uint(parse_int(version['packed_hex']), 32)};")
    for name in ["THR2_WIDTH_BITS", "SPEC_SHIFT_MAX", "WAVE_DECIM_MIN", "WAVE_DECIM_MAX", "RING_ALIGNMENT_BYTES", "RING_GUARD_BYTES_MIN"]:
        if name in constants:
            lines.append(f"  localparam int unsigned TCSR_{sanitize_upper(name):<28} = {parse_int(constants[name])};")
    lines.append("")
    lines.append("  // CSR register offsets.")
    for reg in csr["registers"]:
        rn = sanitize_upper(reg["name"])
        lines.append(f"  localparam int unsigned {('TCSR_' + rn + '_OFFSET'):<48} = 32'h{parse_int(reg['offset']):08x};")
    lines.append("")
    lines.append("  // CSR reset values.")
    for reg in csr["registers"]:
        if "reset" not in reg:
            continue
        rn = sanitize_upper(reg["name"])
        lines.append(f"  localparam logic [31:0] {('TCSR_' + rn + '_RESET'):<48} = {sv_uint(parse_int(reg['reset']), 32)};")
    lines.append("")
    lines.append("  // CSR bit positions and masks.")
    for reg in csr["registers"]:
        fields = reg.get("fields", [])
        if not fields:
            continue
        rn = sanitize_upper(reg["name"])
        lines.append(f"  // {reg['name']}")
        for field in fields:
            fn = sanitize_upper(field["name"])
            lsb = parse_int(field["lsb"])
            msb = parse_int(field.get("msb", lsb))
            mask = field_mask(lsb, msb)
            lines.append(f"  localparam int unsigned TCSR_{rn}_{fn}_LSB = {lsb};")
            lines.append(f"  localparam int unsigned TCSR_{rn}_{fn}_MSB = {msb};")
            lines.append(f"  localparam logic [31:0] TCSR_{rn}_{fn}_MASK = 32'h{mask:08x};")
    lines.append("")
    lines.append("  // CSR enum mirror values.")
    for enum_name, values in csr.get("enums", {}).items():
        eprefix = sanitize_upper(enum_name)
        for item in values:
            lines.append(f"  localparam int unsigned TCSR_{eprefix}_{sanitize_upper(item['name'])} = {parse_int(item['value'])};")
    lines.append("")
    lines.append("endpackage : trecap_csr_pkg")
    return "\n".join(lines) + "\n"


def payload_size_constants(packet: Mapping[str, Any]) -> List[Tuple[str, int]]:
    result: List[Tuple[str, int]] = []
    for name, payload in packet.get("payloads", {}).items():
        rule = payload.get("payload_size_rule", {})
        n = sanitize_upper(name)
        if rule.get("kind") == "exact" and "bytes" in rule:
            result.append((f"TPKT_PAYLOAD_{n}_BYTES", parse_int(rule["bytes"])))
        elif rule.get("kind") == "variable":
            for suffix, key in [("MIN_BYTES", "min_bytes"), ("MAX_BYTES", "max_bytes"), ("NSAMP_MIN", "nsamp_min"), ("NSAMP_MAX", "nsamp_max")]:
                if key in rule:
                    result.append((f"TPKT_PAYLOAD_{n}_{suffix}", parse_int(rule[key])))
    return result


def gen_packet_pkg(packet: Mapping[str, Any]) -> str:
    tr = packet["transport"]
    result = packet["command_result"]
    lines = [banner("sv"), "package trecap_packet_pkg;", ""]
    lines.append("  // Transport constants.")
    scalar_consts = [
        ("TPKT_TELEMETRY_MAGIC", tr["telemetry_magic_hex"], 32),
        ("TCMD_COMMAND_MAGIC", tr["command_magic_hex"], 32),
        ("TCMD_RESULT_MAGIC", result["magic_hex"], 32),
    ]
    for name, value, width in scalar_consts:
        lines.append(f"  localparam logic [{width-1}:0] {name:<36} = {sv_uint(parse_int(value), width)};")
    for name, key in [
        ("TPKT_HEADER_VERSION", "telemetry_header_version"),
        ("TPKT_HEADER_BYTES", "telemetry_header_bytes"),
        ("TCMD_PACKET_BYTES", "command_packet_bytes"),
        ("TPKT_UDP_MAX_BYTES", "udp_no_fragment_payload_max_bytes"),
        ("TPKT_DDR_ALIGN_BYTES", "ddr_record_alignment_bytes"),
        ("TPKT_TRANSPORT_VERSION_MAJOR", "transport_version_major"),
        ("TPKT_TRANSPORT_VERSION_MINOR", "transport_version_minor"),
    ]:
        lines.append(f"  localparam int unsigned {name:<36} = {parse_int(tr[key])};")
    for version in tr["command_versions_supported"]:
        lines.append(f"  localparam int unsigned TCMD_VERSION_V{parse_int(version)}{'':<19} = {parse_int(version)};")
    lines.append(f"  localparam int unsigned {'TCMD_VERSION_CURRENT':<36} = {parse_int(tr['command_version'])};")
    lines.append(f"  localparam int unsigned {'TCMD_VERSION':<36} = TCMD_VERSION_CURRENT;")
    lines.append(f"  localparam int unsigned {'TCMD_RESULT_VERSION':<36} = {parse_int(result['version'])};")
    lines.append(f"  localparam int unsigned {'TCMD_RESULT_BYTES':<36} = {parse_int(result['size_bytes'])};")
    lines.append("")
    lines.append("  // Packet type IDs and drop priorities.")
    for pkt in packet["packet_types"]:
        pn = sanitize_upper(pkt["name"])
        lines.append(f"  localparam logic [15:0] TPKT_TYPE_{pn:<16} = {sv_uint(parse_int(pkt['code']), 16)};")
        if pkt.get("priority") is not None:
            lines.append(f"  localparam logic [1:0]  TPKT_PRIORITY_{pn:<12} = 2'd{parse_int(pkt['priority'])};")
    lines.append("")
    lines.append("  // Common telemetry header offsets.")
    for field in packet["common_header"]["fields"]:
        fn = sanitize_upper(field["name"])
        lines.append(f"  localparam int unsigned {('TPKT_HDR_' + fn + '_OFFSET'):<48} = {parse_int(field['offset'])};")
    lines.append("")
    lines.append("  // Common telemetry flag bits and masks.")
    for flag in packet["common_flags"]:
        fn = sanitize_upper(flag["name"])
        lsb = parse_int(flag["lsb"])
        msb = parse_int(flag.get("msb", lsb))
        ident_lsb = f"TPKT_FLAG_{fn}_LSB"
        lines.append(f"  localparam int unsigned {ident_lsb:<48} = {lsb};")
        ident_mask = f"TPKT_FLAG_{fn}_MASK"
        lines.append(f"  localparam logic [15:0] {ident_mask:<48} = 16'h{field_mask(lsb, msb):04x};")
    lines.append("")
    lines.append("  // Payload size constants.")
    for name, value in payload_size_constants(packet):
        lines.append(f"  localparam int unsigned {name:<36} = {value};")
    lines.append("")
    lines.append("  // Payload field offsets.")
    for payload_name, payload in packet.get("payloads", {}).items():
        for field in payload.get("fields", []):
            if "offset" not in field:
                continue
            lines.append(
                f"  localparam int unsigned {('TPKT_' + sanitize_upper(payload_name) + '_' + sanitize_upper(field['name']) + '_OFFSET'):<48} = {parse_int(field['offset'])};"
            )
    lines.append("")
    lines.append("  // PC command packet field offsets and command IDs.")
    cmd = packet["command_packet"]
    for field in cmd.get("fields", []):
        lines.append(f"  localparam int unsigned {('TCMD_' + sanitize_upper(field['name']) + '_OFFSET'):<48} = {parse_int(field['offset'])};")
    for item in cmd.get("command_types", []):
        lines.append(f"  localparam logic [15:0] TCMD_TYPE_{sanitize_upper(item['name']):<20} = {sv_uint(parse_int(item['code']), 16)};")
    lines.append("")
    lines.append("  // Version-2 command-result offsets and enum values.")
    for field in result.get("fields", []):
        lines.append(f"  localparam int unsigned {('TCMD_RESULT_' + sanitize_upper(field['name']) + '_OFFSET'):<48} = {parse_int(field['offset'])};")
    for item in result.get("dispositions", []):
        lines.append(f"  localparam int unsigned TCMD_DISPOSITION_{sanitize_upper(item['name']):<20} = {parse_int(item['code'])};")
    for item in result.get("reject_reasons", []):
        lines.append(f"  localparam int unsigned TCMD_REJECT_{sanitize_upper(item['name']):<25} = {parse_int(item['code'])};")
    lines.append("")
    lines.append("endpackage : trecap_packet_pkg")
    return "\n".join(lines) + "\n"


def gen_iface_pkg(iface: Mapping[str, Any]) -> str:
    pkg = iface.get("package", {})
    imports = pkg.get("imports", [])
    lines = [banner("sv"), f"package {pkg.get('name', 'trecap_iface_pkg')};", ""]
    for item in imports:
        lines.append(f"  import {item};")
    if imports:
        lines.append("")
    lines.append("  // Primitive aliases.")
    for alias in iface.get("primitive_width_aliases", []):
        name = alias["name"]
        typ = alias["sv_type"]
        typedef_name = re.sub(r"_t_", "_", name)
        if not typedef_name.endswith("_t"):
            typedef_name = typedef_name + "_t"
        lines.append(f"  typedef {typ} {typedef_name};")
    lines.append("")
    lines.append("  // Shared enums.")
    for enum in iface.get("enums", []):
        lines.append(f"  typedef enum {enum['base_sv_type']} {{")
        values = enum.get("values", [])
        for idx, val in enumerate(values):
            comma = "," if idx < len(values) - 1 else ""
            lines.append(f"    {val['name']:<28} = {val['value_hex']}{comma}")
        lines.append(f"  }} {enum['name']};")
        lines.append("")
    lines.append("  // Shared packed structs.")
    for struct in iface.get("structs", []):
        packed = " packed" if struct.get("packed", True) else ""
        lines.append(f"  typedef struct{packed} {{")
        for field in struct.get("fields", []):
            lines.append(f"    {field['sv_type']:<38} {field['name']};")
        lines.append(f"  }} {struct['name']};")
        lines.append("")
    lines.append(f"endpackage : {pkg.get('name', 'trecap_iface_pkg')}")
    return "\n".join(lines) + "\n"


def gen_csr_h(csr: Mapping[str, Any]) -> str:
    lines = [banner("c"), "#ifndef TRECAP_CSR_H", "#define TRECAP_CSR_H", "", "#include <stdint.h>", "", "#ifdef __cplusplus", 'extern "C" {', "#endif", ""]
    constants = csr.get("constants", {})
    if "ID" in constants:
        lines.append(f"#define TCSR_ID_VALUE {c_uint(parse_int(constants['ID']['value_hex']), 32)}")
    version = constants.get("VERSION", {})
    if version:
        lines.append(f"#define TCSR_VERSION_MAJOR {parse_int(version['major'])}u")
        lines.append(f"#define TCSR_VERSION_MINOR {parse_int(version['minor'])}u")
        lines.append(f"#define TCSR_VERSION_VALUE {c_uint(parse_int(version['packed_hex']), 32)}")
    for name in ["THR2_WIDTH_BITS", "SPEC_SHIFT_MAX", "WAVE_DECIM_MIN", "WAVE_DECIM_MAX", "RING_ALIGNMENT_BYTES", "RING_GUARD_BYTES_MIN"]:
        if name in constants:
            lines.append(f"#define TCSR_{sanitize_upper(name)} {parse_int(constants[name])}u")
    lines.append("")
    lines.append("/* CSR register offsets. */")
    for reg in csr["registers"]:
        lines.append(f"#define {('TCSR_' + sanitize_upper(reg['name']) + '_OFFSET'):<48} {c_uint(parse_int(reg['offset']), 32)}")
    lines.append("")
    lines.append("/* CSR reset values. */")
    for reg in csr["registers"]:
        if "reset" in reg:
            lines.append(f"#define {('TCSR_' + sanitize_upper(reg['name']) + '_RESET'):<48} {c_uint(parse_int(reg['reset']), 32)}")
    lines.append("")
    lines.append("/* CSR bit positions and masks. */")
    for reg in csr["registers"]:
        for field in reg.get("fields", []):
            rn = sanitize_upper(reg["name"])
            fn = sanitize_upper(field["name"])
            lsb = parse_int(field["lsb"])
            msb = parse_int(field.get("msb", lsb))
            lines.append(f"#define TCSR_{rn}_{fn}_LSB {lsb}u")
            lines.append(f"#define TCSR_{rn}_{fn}_MSB {msb}u")
            lines.append(f"#define TCSR_{rn}_{fn}_MASK {c_uint(field_mask(lsb, msb), 32)}")
    lines.append("")
    lines.append("/* CSR enum mirror values. */")
    for enum_name, values in csr.get("enums", {}).items():
        eprefix = sanitize_upper(enum_name)
        for item in values:
            lines.append(f"#define TCSR_{eprefix}_{sanitize_upper(item['name'])} {parse_int(item['value'])}u")
    lines.append("")
    lines += ["#ifdef __cplusplus", "}", "#endif", "", "#endif /* TRECAP_CSR_H */"]
    return "\n".join(lines) + "\n"


def gen_packet_h(packet: Mapping[str, Any]) -> str:
    tr = packet["transport"]
    result = packet["command_result"]
    lines = [banner("c"), "#ifndef TRECAP_PACKET_H", "#define TRECAP_PACKET_H", "", "#include <stdint.h>", "", "#ifdef __cplusplus", 'extern "C" {', "#endif", ""]
    lines.append(f"#define TPKT_TELEMETRY_MAGIC {c_uint(parse_int(tr['telemetry_magic_hex']), 32)}")
    lines.append(f"#define TCMD_COMMAND_MAGIC {c_uint(parse_int(tr['command_magic_hex']), 32)}")
    lines.append(f"#define TCMD_RESULT_MAGIC {c_uint(parse_int(result['magic_hex']), 32)}")
    for name, key in [
        ("TPKT_HEADER_VERSION", "telemetry_header_version"),
        ("TPKT_HEADER_BYTES", "telemetry_header_bytes"),
        ("TCMD_PACKET_BYTES", "command_packet_bytes"),
        ("TPKT_UDP_MAX_BYTES", "udp_no_fragment_payload_max_bytes"),
        ("TPKT_DDR_ALIGN_BYTES", "ddr_record_alignment_bytes"),
        ("TPKT_TRANSPORT_VERSION_MAJOR", "transport_version_major"),
        ("TPKT_TRANSPORT_VERSION_MINOR", "transport_version_minor"),
    ]:
        lines.append(f"#define {name} {parse_int(tr[key])}u")
    for version in tr["command_versions_supported"]:
        lines.append(f"#define TCMD_VERSION_V{parse_int(version)} {parse_int(version)}u")
    lines.append(f"#define TCMD_VERSION_CURRENT {parse_int(tr['command_version'])}u")
    lines.append("#define TCMD_VERSION TCMD_VERSION_CURRENT")
    lines.append(f"#define TCMD_RESULT_VERSION {parse_int(result['version'])}u")
    lines.append(f"#define TCMD_RESULT_BYTES {parse_int(result['size_bytes'])}u")
    lines.append("")
    lines.append("/* Packet type IDs and priorities. */")
    for pkt in packet["packet_types"]:
        pn = sanitize_upper(pkt["name"])
        lines.append(f"#define TPKT_TYPE_{pn:<16} UINT16_C(0x{parse_int(pkt['code']):04x})")
        if pkt.get("priority") is not None:
            lines.append(f"#define TPKT_PRIORITY_{pn:<12} {parse_int(pkt['priority'])}u")
    lines.append("")
    lines.append("/* Common telemetry header offsets. */")
    for field in packet["common_header"]["fields"]:
        lines.append(f"#define {('TPKT_HDR_' + sanitize_upper(field['name']) + '_OFFSET'):<48} {parse_int(field['offset'])}u")
    lines.append("")
    lines.append("/* Common telemetry flag bits and masks. */")
    for flag in packet["common_flags"]:
        fn = sanitize_upper(flag["name"])
        lsb = parse_int(flag["lsb"])
        msb = parse_int(flag.get("msb", lsb))
        ident_lsb = f"TPKT_FLAG_{fn}_LSB"
        lines.append(f"#define {ident_lsb:<56} {lsb}u")
        ident_mask = f"TPKT_FLAG_{fn}_MASK"
        lines.append(f"#define {ident_mask:<56} UINT16_C(0x{field_mask(lsb, msb):04x})")
    lines.append("")
    lines.append("/* Payload size constants. */")
    for name, value in payload_size_constants(packet):
        lines.append(f"#define {name:<36} {value}u")
    lines.append("")
    lines.append("/* Payload field offsets. */")
    for payload_name, payload in packet.get("payloads", {}).items():
        for field in payload.get("fields", []):
            if "offset" not in field:
                continue
            lines.append(f"#define {('TPKT_' + sanitize_upper(payload_name) + '_' + sanitize_upper(field['name']) + '_OFFSET'):<48} {parse_int(field['offset'])}u")
    lines.append("")
    lines.append("/* PC command packet field offsets and command IDs. */")
    for field in packet["command_packet"].get("fields", []):
        lines.append(f"#define {('TCMD_' + sanitize_upper(field['name']) + '_OFFSET'):<48} {parse_int(field['offset'])}u")
    for item in packet["command_packet"].get("command_types", []):
        lines.append(f"#define TCMD_TYPE_{sanitize_upper(item['name']):<20} UINT16_C(0x{parse_int(item['code']):04x})")
    lines.append("")
    lines.append("/* Version-2 command-result offsets and enum values. */")
    for field in result.get("fields", []):
        lines.append(f"#define {('TCMD_RESULT_' + sanitize_upper(field['name']) + '_OFFSET'):<48} {parse_int(field['offset'])}u")
    for item in result.get("dispositions", []):
        lines.append(f"#define TCMD_DISPOSITION_{sanitize_upper(item['name']):<20} {parse_int(item['code'])}u")
    for item in result.get("reject_reasons", []):
        lines.append(f"#define TCMD_REJECT_{sanitize_upper(item['name']):<25} {parse_int(item['code'])}u")
    lines.append("")
    lines += ["#ifdef __cplusplus", "}", "#endif", "", "#endif /* TRECAP_PACKET_H */"]
    return "\n".join(lines) + "\n"


def gen_packet_py(csr: Mapping[str, Any], packet: Mapping[str, Any]) -> str:
    tr = packet["transport"]
    result = packet["command_result"]
    lines = [banner("py"), "from __future__ import annotations", "", "import struct", "", "# Transport constants"]
    py_scalars = {
        "TELEMETRY_MAGIC": parse_int(tr["telemetry_magic_hex"]),
        "COMMAND_MAGIC": parse_int(tr["command_magic_hex"]),
        "TELEMETRY_HEADER_VERSION": parse_int(tr["telemetry_header_version"]),
        "COMMAND_VERSION_CURRENT": parse_int(tr["command_version"]),
        "TELEMETRY_HEADER_BYTES": parse_int(tr["telemetry_header_bytes"]),
        "COMMAND_PACKET_BYTES": parse_int(tr["command_packet_bytes"]),
        "UDP_NO_FRAGMENT_PAYLOAD_MAX_BYTES": parse_int(tr["udp_no_fragment_payload_max_bytes"]),
        "DDR_RECORD_ALIGNMENT_BYTES": parse_int(tr["ddr_record_alignment_bytes"]),
        "TRANSPORT_VERSION_MAJOR": parse_int(tr["transport_version_major"]),
        "TRANSPORT_VERSION_MINOR": parse_int(tr["transport_version_minor"]),
        "COMMAND_RESULT_MAGIC": parse_int(result["magic_hex"]),
        "COMMAND_RESULT_VERSION": parse_int(result["version"]),
        "COMMAND_RESULT_BYTES": parse_int(result["size_bytes"]),
    }
    for key, value in py_scalars.items():
        lines.append(f"{key} = {value}")
    for version in tr["command_versions_supported"]:
        lines.append(f"COMMAND_VERSION_V{parse_int(version)} = {parse_int(version)}")
    lines.append("COMMAND_VERSION = COMMAND_VERSION_CURRENT")
    lines.append(f"COMMAND_VERSIONS_SUPPORTED = {tuple(parse_int(version) for version in tr['command_versions_supported'])!r}")
    lines.append("")
    lines.append('TELEMETRY_HEADER_STRUCT = struct.Struct("<IHHHHIQII")')
    lines.append('COMMAND_STRUCT = struct.Struct("<IHHIIIII")')
    lines.append('COMMAND_RESULT_STRUCT = struct.Struct("<IHHIIIIII")')
    lines.append("")
    lines.append("PACKET_TYPES = {")
    for pkt in packet["packet_types"]:
        lines.append(f"    {pkt['name']!r}: {parse_int(pkt['code'])},")
    lines.append("}")
    lines.append("PACKET_TYPE_NAMES = {value: key for key, value in PACKET_TYPES.items()}")
    lines.append("PACKET_PRIORITIES = {")
    for pkt in packet["packet_types"]:
        if pkt.get("priority") is not None:
            lines.append(f"    {pkt['name']!r}: {parse_int(pkt['priority'])},")
    lines.append("}")
    lines.append("")
    lines.append("HEADER_OFFSETS = {")
    for field in packet["common_header"]["fields"]:
        lines.append(f"    {field['name']!r}: {parse_int(field['offset'])},")
    lines.append("}")
    lines.append("COMMON_FLAG_BITS = {")
    for flag in packet["common_flags"]:
        lines.append(f"    {flag['name']!r}: ({parse_int(flag['lsb'])}, {parse_int(flag.get('msb', flag['lsb']))}),")
    lines.append("}")
    lines.append("")
    lines.append("PAYLOAD_RULES = {")
    for name, payload in packet.get("payloads", {}).items():
        lines.append(f"    {name!r}: {json.dumps(payload.get('payload_size_rule', {}), sort_keys=True)},")
    lines.append("}")
    lines.append("PAYLOAD_OFFSETS = {")
    for payload_name, payload in packet.get("payloads", {}).items():
        lines.append(f"    {payload_name!r}: {{")
        for field in payload.get("fields", []):
            if "offset" in field:
                lines.append(f"        {field['name']!r}: {parse_int(field['offset'])},")
        lines.append("    },")
    lines.append("}")
    lines.append("")
    lines.append("COMMAND_TYPES = {")
    for item in packet["command_packet"].get("command_types", []):
        lines.append(f"    {item['name']!r}: {parse_int(item['code'])},")
    lines.append("}")
    lines.append("COMMAND_TYPE_NAMES = {value: key for key, value in COMMAND_TYPES.items()}")
    lines.append("COMMAND_TYPE_MIN_VERSION = {")
    for item in packet["command_packet"].get("command_types", []):
        lines.append(f"    {parse_int(item['code'])}: {parse_int(item['introduced_in_version'])},")
    lines.append("}")
    lines.append("COMMAND_V1_TYPES = frozenset(value for value, version in COMMAND_TYPE_MIN_VERSION.items() if version <= 1)")
    lines.append("COMMAND_V2_TYPES = frozenset(value for value, version in COMMAND_TYPE_MIN_VERSION.items() if version <= 2)")
    lines.append("COMMAND_OFFSETS = {")
    for field in packet["command_packet"].get("fields", []):
        lines.append(f"    {field['name']!r}: {parse_int(field['offset'])},")
    lines.append("}")
    lines.append("COMMAND_RESULT_OFFSETS = {")
    for field in result.get("fields", []):
        lines.append(f"    {field['name']!r}: {parse_int(field['offset'])},")
    lines.append("}")
    lines.append("COMMAND_DISPOSITIONS = {")
    for item in result.get("dispositions", []):
        lines.append(f"    {item['name']!r}: {parse_int(item['code'])},")
    lines.append("}")
    lines.append("COMMAND_DISPOSITION_NAMES = {value: key for key, value in COMMAND_DISPOSITIONS.items()}")
    lines.append("COMMAND_REJECT_REASONS = {")
    for item in result.get("reject_reasons", []):
        lines.append(f"    {item['name']!r}: {parse_int(item['code'])},")
    lines.append("}")
    lines.append("COMMAND_REJECT_REASON_NAMES = {value: key for key, value in COMMAND_REJECT_REASONS.items()}")
    lines.append("")
    lines.append("CSR_OFFSETS = {")
    for reg in csr["registers"]:
        lines.append(f"    {reg['name']!r}: {parse_int(reg['offset'])},")
    lines.append("}")
    lines.append("CSR_BITS = {")
    for reg in csr["registers"]:
        if reg.get("fields"):
            lines.append(f"    {reg['name']!r}: {{")
            for field in reg["fields"]:
                lines.append(f"        {field['name']!r}: ({parse_int(field['lsb'])}, {parse_int(field.get('msb', field['lsb']))}),")
            lines.append("    },")
    lines.append("}")
    lines.append("")
    lines.append("def align64(n: int) -> int:")
    lines.append("    return (int(n) + 63) & ~63")
    lines.append("")
    lines.append("def expected_payload_bytes(packet_type_name: str, *, nsamp: int | None = None) -> int:")
    lines.append("    rule = PAYLOAD_RULES[packet_type_name]")
    lines.append("    if rule.get('kind') == 'exact':")
    lines.append("        return int(rule['bytes'])")
    lines.append("    if rule.get('kind') == 'variable' and packet_type_name == 'WAVE':")
    lines.append("        if nsamp is None:")
    lines.append("            raise ValueError('WAVE requires nsamp')")
    lines.append("        if not (int(rule['nsamp_min']) <= nsamp <= int(rule['nsamp_max'])):")
    lines.append("            raise ValueError(f'WAVE nsamp out of range: {nsamp}')")
    lines.append("        return 16 + 6 * nsamp")
    lines.append("    raise ValueError(f'no fixed payload rule for {packet_type_name}')")
    return "\n".join(lines) + "\n"


def gen_reference_config_py(core: Mapping[str, Any], csr: Mapping[str, Any], packet: Mapping[str, Any]) -> str:
    cfg = core["configuration"]
    widths = core["widths"]
    data = {
        "CONFIGURATION": {k: parse_int(v) if isinstance(v, (int, str, bool)) else v for k, v in cfg.items()},
        "WIDTHS": {k: parse_int(v) if isinstance(v, (int, str, bool)) else v for k, v in widths.items()},
        "TRANSPORT": {
            "VERSION_MAJOR": parse_int(packet["transport"]["transport_version_major"]),
            "VERSION_MINOR": parse_int(packet["transport"]["transport_version_minor"]),
            "TELEMETRY_MAGIC": parse_int(packet["transport"]["telemetry_magic_hex"]),
            "COMMAND_MAGIC": parse_int(packet["transport"]["command_magic_hex"]),
        },
        "CSR_OFFSETS": {reg["name"]: parse_int(reg["offset"]) for reg in csr["registers"]},
        "PACKET_TYPES": {pkt["name"]: parse_int(pkt["code"]) for pkt in packet["packet_types"]},
    }
    lines = [banner("py"), "from __future__ import annotations", ""]
    for name, obj in data.items():
        lines.append(f"{name} = {json.dumps(obj, indent=2, sort_keys=True)}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def stage_outputs(root: Path, outputs: Mapping[str, str]) -> Dict[str, str]:
    hashes: Dict[str, str] = {}
    for rel, text in outputs.items():
        if not text.endswith("\n"):
            fail(f"generated output missing final newline: {rel}")
        if "\r" in text:
            fail(f"generated output contains CR line endings: {rel}")
        path = safe_join(root, rel)
        path.parent.mkdir(parents=True, exist_ok=True)
        data = text.encode("utf-8")
        path.write_bytes(data)
        hashes[rel] = sha256_bytes(data)
    return hashes


def build_manifest(root: Path, source_hashes: Mapping[str, str], output_hashes: Mapping[str, str], warnings: Sequence[str]) -> Dict[str, Any]:
    return {
        "schema": "trecap_phase2_gen_manifest_v1",
        "file_class": "[2] generated manifest - do not edit by hand",
        "generator": {
            "path": GENERATOR_PATH,
            "version": GENERATOR_VERSION,
        },
        "source_files": [
            {"path": path, "sha256": source_hashes[path]} for path in sorted(source_hashes)
        ],
        "output_files": [
            {"path": path, "sha256": output_hashes[path]} for path in sorted(output_hashes)
        ],
        "warnings": list(warnings),
    }


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Generate T-RECAP Phase 2 shared SV/C/Python contract headers.")
    parser.add_argument("--root", default=None, help="Repository root. Default: parent of this script directory.")
    parser.add_argument("--check", action="store_true", help="Generate into a temporary directory and fail if checked-in outputs differ.")
    parser.add_argument("--quiet", action="store_true", help="Reduce progress messages.")
    args = parser.parse_args(argv)

    root = Path(args.root).resolve() if args.root else repo_root_from_script()
    if not (root / "Makefile").exists():
        fail(f"repository root does not look valid: {root}")

    if jsonschema is None and not args.quiet:
        print(
            "warning: jsonschema Python package is unavailable; skipped optional JSON Schema validation",
            file=sys.stderr,
        )

    warnings: List[str] = []
    sources: Dict[str, Any] = {}
    source_hashes: Dict[str, str] = {}
    for name, rel in SOURCE_PATHS.items():
        path = root / rel
        if not path.exists():
            if name in {"csr_map", "packet_layouts", "interface_types"}:
                fail(f"required source contract missing: {rel}")
            warnings.append(f"optional source contract missing: {rel}")
            continue
        data = load_json(path)
        validate_schema(root, name, data, warnings)
        sources[name] = data
        source_hashes[rel] = sha256_file(path)

    csr = sources["csr_map"]
    packet = sources["packet_layouts"]
    iface = sources["interface_types"]
    check_csr(csr)
    check_packets(packet)
    check_iface(iface)
    core = core_dict_from_sources(root, sources, warnings)

    outputs: Dict[str, str] = {
        "rtl/include/generated/trecap_core_pkg.sv": gen_core_pkg(core),
        "rtl/include/generated/trecap_csr_pkg.sv": gen_csr_pkg(csr),
        "rtl/include/generated/trecap_packet_pkg.sv": gen_packet_pkg(packet),
        "rtl/include/generated/trecap_iface_pkg.sv": gen_iface_pkg(iface),
        "sw/hps/include/generated/trecap_csr.h": gen_csr_h(csr),
        "sw/hps/include/generated/trecap_packet.h": gen_packet_h(packet),
        "sw/pc_dashboard/generated/trecap_packet.py": gen_packet_py(csr, packet),
        "sw/reference_model/generated/trecap_config.py": gen_reference_config_py(core, csr, packet),
    }

    if args.check:
        with tempfile.TemporaryDirectory(prefix="trecap_gen_headers_") as tmp:
            tmp_root = Path(tmp)
            for rel, text in outputs.items():
                dst = tmp_root / rel
                dst.parent.mkdir(parents=True, exist_ok=True)
                dst.write_text(text, encoding="utf-8", newline="\n")
            tmp_hashes = {rel: sha256_file(tmp_root / rel) for rel in outputs}
            manifest = build_manifest(root, source_hashes, tmp_hashes, warnings)
            manifest_bytes = canonical_json_bytes(manifest)
            (tmp_root / MANIFEST_PATH).parent.mkdir(parents=True, exist_ok=True)
            (tmp_root / MANIFEST_PATH).write_bytes(manifest_bytes)
            tmp_hashes[MANIFEST_PATH] = sha256_bytes(manifest_bytes)
            failures = []
            for rel in list(outputs) + [MANIFEST_PATH]:
                current = root / rel
                generated = tmp_root / rel
                if not current.exists():
                    failures.append(f"missing checked-in generated file: {rel}")
                elif current.read_bytes() != generated.read_bytes():
                    failures.append(f"generated drift: {rel}")
            if failures:
                for item in failures:
                    print(item, file=sys.stderr)
                return 1
            if not args.quiet:
                print("gen_headers.py --check: OK")
            return 0

    output_hashes = stage_outputs(root, outputs)
    manifest = build_manifest(root, source_hashes, output_hashes, warnings)
    manifest_path = safe_join(root, MANIFEST_PATH)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_bytes(canonical_json_bytes(manifest))
    if not args.quiet:
        print(f"generated {len(outputs)} header/config files")
        print(f"wrote {MANIFEST_PATH}")
        for item in warnings:
            print(f"warning: {item}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
