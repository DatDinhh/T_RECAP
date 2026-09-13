#!/usr/bin/env python3
"""Write and validate a Platform Designer generation-run manifest.

This is generation provenance, not functional verification. It records the
exact Qsys source and mandatory artifacts produced by the pinned Quartus flow.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
from typing import Any


BOOTSTRAP_MARKER = b"T_RECAP_BOOTSTRAP_QSYS_SOURCE=1"
QSYS_REL = Path("platform/de1soc/qsys/system.qsys")
BLUEPRINT_REL = Path("platform/de1soc/qsys/system_blueprint.xml")
ADDRESS_MAP_REL = Path("platform/de1soc/address_map/hps_bridge_regions.json")
SOPCINFO_REL = Path("platform/de1soc/qsys/system.sopcinfo")
QIP_REL = Path("platform/de1soc/qsys/system/synthesis/system.qip")
HDL_CANDIDATES = (
    Path("platform/de1soc/qsys/system/synthesis/system.v"),
    Path("platform/de1soc/qsys/system/synthesis/system.sv"),
)
PRESET_REL = Path("platform/de1soc/qsys/presets/terasic_de1soc_revh_qp20_1_hps.tsv")
EXPECTED_READBACK_COUNT = 44


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def artifact_record(root: Path, relative: Path) -> dict[str, Any]:
    path = root / relative
    record: dict[str, Any] = {"path": relative.as_posix(), "present": path.is_file()}
    if path.is_file():
        data = path.read_bytes()
        record.update(size_bytes=len(data), sha256=digest(data))
    else:
        record.update(size_bytes=None, sha256=None)
    return record


def run_file_record(root: Path, path: Path) -> dict[str, Any]:
    try:
        display_path = path.relative_to(root).as_posix()
    except ValueError:
        display_path = str(path)
    data = path.read_bytes()
    return {"path": display_path, "size_bytes": len(data), "sha256": digest(data)}


def expected_readback_values(root: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line_number, raw in enumerate((root / PRESET_REL).read_text(encoding="utf-8").splitlines(), 1):
        if not raw or raw.startswith("#"):
            continue
        fields = raw.split("\t")
        if len(fields) != 3:
            raise ValueError(f"{PRESET_REL}:{line_number}: expected three TSV columns")
        name, value, mode = fields
        if mode == "readback_only":
            values[name] = value
    if len(values) != EXPECTED_READBACK_COUNT:
        raise ValueError(
            f"frozen preset exposes {len(values)} readback-only parameters; "
            f"expected {EXPECTED_READBACK_COUNT}"
        )
    return values


def load_readback(root: Path, path: Path | None) -> dict[str, Any]:
    if path is None:
        return {
            "present": False,
            "path": None,
            "parameter_count": 0,
            "canonical_sha256": None,
            "frozen_observation_mismatch_count": None,
            "parameters": [],
        }
    resolved = path if path.is_absolute() else root / path
    if not resolved.is_file():
        return {
            "present": False,
            "path": str(path),
            "parameter_count": 0,
            "canonical_sha256": None,
            "frozen_observation_mismatch_count": None,
            "parameters": [],
        }
    values: dict[str, str] = {}
    for line_number, raw in enumerate(resolved.read_text(encoding="utf-8").splitlines(), 1):
        if not raw or raw.startswith("#"):
            continue
        fields = raw.split("\t")
        if len(fields) != 2:
            raise ValueError(f"{resolved}:{line_number}: expected name<TAB>value")
        name, value = fields
        if name in values:
            raise ValueError(f"{resolved}:{line_number}: duplicate readback parameter {name}")
        if any(character in value for character in "\r\n\t"):
            raise ValueError(f"{resolved}:{line_number}: unsafe readback value")
        values[name] = value
    expected_values = expected_readback_values(root)
    expected_names = list(expected_values)
    if list(values) != expected_names:
        missing = sorted(set(expected_names) - set(values))
        extra = sorted(set(values) - set(expected_names))
        raise ValueError(
            "readback capture does not match the frozen ordered 44-parameter partition; "
            f"missing={missing}, extra={extra}"
        )
    canonical = "".join(f"{name}={values[name]}\n" for name in expected_names).encode("utf-8")
    mismatch_count = sum(values[name] != expected_values[name] for name in expected_names)
    try:
        display_path = resolved.relative_to(root).as_posix()
    except ValueError:
        display_path = str(resolved)
    return {
        "present": True,
        "path": display_path,
        "parameter_count": len(expected_names),
        "canonical_sha256": digest(canonical),
        "frozen_observation_mismatch_count": mismatch_count,
        "parameters": [
            {
                "name": name,
                "value": values[name],
                "frozen_observation": expected_values[name],
                "matches_frozen_observation": values[name] == expected_values[name],
            }
            for name in expected_names
        ],
    }


def atomic_write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--mode-requested", required=True)
    parser.add_argument("--mode-effective", required=True)
    parser.add_argument("--construction-performed", choices=("true", "false"), required=True)
    parser.add_argument("--qsys-script", default="qsys-script")
    parser.add_argument("--qsys-generate", default="qsys-generate")
    parser.add_argument("--quartus-version-file", type=Path)
    parser.add_argument("--readback-tsv", type=Path)
    parser.add_argument("--require-generated", action="store_true")
    args = parser.parse_args()

    root = args.repo_root.resolve()
    output = args.output if args.output.is_absolute() else root / args.output
    try:
        qsys_data = (root / QSYS_REL).read_bytes()
        readback = load_readback(root, args.readback_tsv)
        address_map = json.loads((root / ADDRESS_MAP_REL).read_text(encoding="utf-8"))
        freeze = address_map["address_map_freeze"]
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f"ERROR: invalid Step-4 address-map freeze: {exc}", file=sys.stderr)
        return 1

    qsys_state = "bootstrap" if BOOTSTRAP_MARKER in qsys_data else "quartus_normalized"
    artifacts = {
        "blueprint": artifact_record(root, BLUEPRINT_REL),
        "address_map_source": artifact_record(root, ADDRESS_MAP_REL),
        "system_qsys": artifact_record(root, QSYS_REL),
        "system_sopcinfo": artifact_record(root, SOPCINFO_REL),
        "system_qip": artifact_record(root, QIP_REL),
        "generated_hdl": [artifact_record(root, relative) for relative in HDL_CANDIDATES],
    }
    version_text = None
    if args.quartus_version_file is not None:
        version_path = (
            args.quartus_version_file
            if args.quartus_version_file.is_absolute()
            else root / args.quartus_version_file
        )
        if version_path.is_file():
            version_text = version_path.read_text(encoding="utf-8", errors="replace").strip()
    command_logs = [
        run_file_record(root, path)
        for path in sorted(output.parent.glob("*.log"))
        if path.is_file()
        and path.name not in {"generate_system.log", "manifest_writer.log"}
    ]

    errors: list[str] = []
    if address_map.get("contract_stage") != "step4_address_map_source_frozen":
        errors.append("address-map source is not at the Step-4 frozen stage")
    if freeze.get("revision") != "step4_address_map_v1":
        errors.append("address-map freeze revision is not step4_address_map_v1")
    if freeze.get("scope") != "source_only_structural_contract":
        errors.append("address-map freeze scope is not source-only")
    if freeze.get("hardware_signoff") is not False:
        errors.append("source address-map freeze must not claim hardware signoff")
    canonical_sha = freeze.get("canonical_sha256")
    if not isinstance(canonical_sha, str) or len(canonical_sha) != 64:
        errors.append("address-map freeze canonical SHA-256 is missing or malformed")
    pinned_sources = freeze.get("pinned_source_sha256")
    if not isinstance(pinned_sources, dict) or set(pinned_sources) != {
        "platform/de1soc/qsys/system_blueprint.xml",
        "spec/generated/csr_map.json",
        "sw/hps/config/trecap_hps_config.json",
    }:
        errors.append("address-map freeze pinned-source inventory is incomplete")
    if args.require_generated:
        if qsys_state != "quartus_normalized":
            errors.append("system.qsys is still the hand-written bootstrap")
        for key in ("system_sopcinfo", "system_qip"):
            if not artifacts[key]["present"]:
                errors.append(f"mandatory generated artifact is missing: {artifacts[key]['path']}")
            elif artifacts[key]["size_bytes"] == 0:
                errors.append(f"mandatory generated artifact is empty: {artifacts[key]['path']}")
        if not any(
            item["present"] and item["size_bytes"] > 0
            for item in artifacts["generated_hdl"]
        ):
            errors.append(
                "mandatory generated HDL is missing or empty: expected synthesis/system.v or synthesis/system.sv"
            )
        if not readback["present"] or readback["parameter_count"] != EXPECTED_READBACK_COUNT:
            errors.append("complete 44-parameter HPS readback capture is missing")
        if (
            version_text is None
            or "20.1" not in version_text
            or "standard edition" not in version_text.lower()
        ):
            errors.append(
                "Quartus version provenance is missing or is not release 20.1 Standard Edition"
            )

    manifest = {
        "schema": "trecap_phase2_platform_generation_manifest_v3",
        "file_class": "[2] generated run provenance - do not edit by hand",
        "scope": "Platform Designer construction/generation provenance; not functional verification or hardware signoff",
        "mode_requested": args.mode_requested,
        "mode_effective": args.mode_effective,
        "construction_performed": args.construction_performed == "true",
        "qsys_state": qsys_state,
        "platform_contract": "step2_frozen_v1",
        "address_map_contract": {
            "path": ADDRESS_MAP_REL.as_posix(),
            "schema": address_map.get("schema"),
            "contract_stage": address_map.get("contract_stage"),
            "status": address_map.get("status"),
            "freeze_revision": freeze.get("revision"),
            "canonicalization": freeze.get("canonicalization"),
            "canonical_sha256": freeze.get("canonical_sha256"),
            "pinned_source_sha256": freeze.get("pinned_source_sha256"),
            "hardware_signoff": freeze.get("hardware_signoff"),
            "generated_hardware_evidence_required": args.require_generated,
        },
        "quartus_release_required": "20.1",
        "quartus_edition_required": "Standard Edition",
        "quartus_version_output": version_text,
        "tools": {
            "qsys_script": args.qsys_script,
            "qsys_generate": args.qsys_generate,
        },
        "command_logs": command_logs,
        "hps_readback": readback,
        "artifacts": artifacts,
        "generated_artifacts_required": args.require_generated,
        "complete": not errors,
        "errors": errors,
    }
    atomic_write_json(output, manifest)
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print(f"write_platform_generation_manifest: OK output={output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
