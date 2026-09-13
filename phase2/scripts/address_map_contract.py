#!/usr/bin/env python3
"""Build the deterministic Step-4 DE1-SoC address-map freeze record.

The record deliberately hashes a semantic projection rather than the complete
``hps_bridge_regions.json`` file.  This avoids a self-referential digest and
allows comments/prose to improve without silently changing an address.  The
three independent source authorities consumed by the map are pinned by their
raw-file SHA-256 digests.

This helper is read-only.  It prints the record that a reviewer must copy into
``address_map_freeze`` in the bridge-region source.  The checker rejects any
drift after that review.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
from typing import Any, Mapping, Sequence


ADDRESS_MAP_REL = Path("platform/de1soc/address_map/hps_bridge_regions.json")
CSR_MAP_REL = Path("spec/generated/csr_map.json")
RUNTIME_CONFIG_REL = Path("sw/hps/config/trecap_hps_config.json")
BLUEPRINT_REL = Path("platform/de1soc/qsys/system_blueprint.xml")

FREEZE_REVISION = "step4_address_map_v1"
FREEZE_SCOPE = "source_only_structural_contract"
CANONICALIZATION = "trecap_address_map_semantic_projection_v1"
CANONICALIZATION_DESCRIPTION = (
    "Canonical UTF-8 JSON (sorted object keys, compact separators, one trailing LF) "
    "of the lifecycle identity, board/preset identity, Platform Designer address-relevant "
    "settings, exports, internal interfaces, required clock connections, CSR/DDR bridge "
    "assignments, region geometry and policies, and runtime network tuple selected by "
    "semantic_projection(). The address_map_freeze block, related-file prose, human "
    "definitions, and bring-up checklist text are excluded. CSR-map, HPS-runtime, and "
    "immutable Platform Designer blueprint files are pinned separately by raw-byte SHA-256."
)

PINNED_SOURCE_RELS = (CSR_MAP_REL, RUNTIME_CONFIG_REL, BLUEPRINT_REL)


class AddressMapContractError(ValueError):
    """Raised when the source cannot be projected deterministically."""


def _require_mapping(value: Any, path: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise AddressMapContractError(f"{path} must be an object")
    return value


def _require_sequence(value: Any, path: str) -> Sequence[Any]:
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(value, Sequence):
        raise AddressMapContractError(f"{path} must be an array")
    return value


def _select(mapping: Mapping[str, Any], keys: Sequence[str], path: str) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key in keys:
        if key not in mapping:
            raise AddressMapContractError(f"{path}.{key} is required by {CANONICALIZATION}")
        result[key] = mapping[key]
    return result


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise AddressMapContractError(f"cannot read JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise AddressMapContractError(f"{path} must contain a JSON object")
    return value


def canonical_json_bytes(value: Any) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    try:
        return sha256_bytes(path.read_bytes())
    except OSError as exc:
        raise AddressMapContractError(f"cannot hash {path}: {exc}") from exc


def _project_region(region: Mapping[str, Any], index: int) -> dict[str, Any]:
    path = f"regions[{index}]"
    kind = region.get("kind")
    if kind == "csr":
        access = _require_mapping(region.get("access"), f"{path}.access")
        return {
            **_select(
                region,
                (
                    "name",
                    "kind",
                    "owner_rtl",
                    "hps_physical_base",
                    "span_bytes",
                    "end_exclusive",
                    "offset_source",
                    "generated_hps_header",
                    "required_id_value",
                    "required_version_value",
                ),
                path,
            ),
            "access": _select(
                access,
                (
                    "word_size_bytes",
                    "alignment_bytes",
                    "byte_order",
                    "multiword_transfer_policy",
                ),
                f"{path}.access",
            ),
        }
    if kind == "ddr_ring":
        address_translation = _require_mapping(
            region.get("address_translation"), f"{path}.address_translation"
        )
        record_contract = _require_mapping(
            region.get("record_contract"), f"{path}.record_contract"
        )
        pointer_contract = _require_mapping(
            region.get("pointer_contract"), f"{path}.pointer_contract"
        )
        return {
            **_select(
                region,
                (
                    "name",
                    "kind",
                    "owner_rtl",
                    "record_builder_rtl",
                    "pointer_ctrl_rtl",
                    "hps_reader_software",
                    "hps_physical_base",
                    "fpga_visible_base",
                    "size_bytes",
                    "end_exclusive",
                    "guard_bytes",
                    "alignment_bytes",
                    "natural_alignment_bytes",
                    "minimum_size_bytes",
                    "power_of_two_size_required",
                    "linux_allocation_policy",
                    "hps_cache_policy",
                ),
                path,
            ),
            "record_contract": _select(
                record_contract,
                (
                    "header_bytes",
                    "normal_record_alignment_bytes",
                    "normal_length_rule",
                    "wrap_packet_type",
                    "wrap_payload_bytes",
                    "wrap_effective_length_rule",
                    "udp_forwards_padding",
                ),
                f"{path}.record_contract",
            ),
            "pointer_contract": _select(
                pointer_contract,
                (
                    "pointer_width_bits",
                    "producer_pointer",
                    "consumer_pointer",
                    "offset_rule",
                    "producer_commit_rule",
                    "consumer_commit_rule",
                ),
                f"{path}.pointer_contract",
            ),
            "address_translation": _select(
                address_translation,
                (
                    "policy",
                    "fpga_to_hps_offset_bytes",
                    "required_boot_remap",
                    "evidence_status",
                ),
                f"{path}.address_translation",
            ),
        }
    raise AddressMapContractError(f"{path}.kind has unsupported value {kind!r}")


def semantic_projection(address_map: Mapping[str, Any]) -> dict[str, Any]:
    """Return the exact semantic object covered by the Step-4 digest."""

    board_profile = _require_mapping(address_map.get("board_profile"), "board_profile")
    source_spec = _require_mapping(address_map.get("source_spec"), "source_spec")
    pd = _require_mapping(address_map.get("platform_designer"), "platform_designer")
    exports = _require_mapping(address_map.get("exports"), "exports")
    internal = _require_mapping(address_map.get("internal_interfaces"), "internal_interfaces")
    bridges = _require_mapping(address_map.get("bridges"), "bridges")
    csr_bridge = _require_mapping(bridges.get("csr_bridge"), "bridges.csr_bridge")
    csr_translation = _require_mapping(
        csr_bridge.get("address_translation"), "bridges.csr_bridge.address_translation"
    )
    ddr_bridge = _require_mapping(bridges.get("ddr_writer_bridge"), "bridges.ddr_writer_bridge")
    runtime_network = _require_mapping(address_map.get("runtime_network"), "runtime_network")

    clock_rows = []
    for index, raw in enumerate(
        _require_sequence(address_map.get("required_clock_connections"), "required_clock_connections")
    ):
        row = _require_mapping(raw, f"required_clock_connections[{index}]")
        clock_rows.append(_select(row, ("source", "sink"), f"required_clock_connections[{index}]"))
    clock_rows.sort(key=lambda row: (str(row["source"]), str(row["sink"])))

    region_rows = []
    for index, raw in enumerate(_require_sequence(address_map.get("regions"), "regions")):
        region_rows.append(_project_region(_require_mapping(raw, f"regions[{index}]"), index))
    region_rows.sort(key=lambda row: str(row["name"]))

    return {
        "canonicalization": CANONICALIZATION,
        "lifecycle": _select(address_map, ("schema", "contract_stage", "status"), "root"),
        "identity": _select(address_map, ("project", "board"), "root"),
        "board_profile": _select(
            board_profile,
            ("preset", "source_revision", "physical_board_revision_status"),
            "board_profile",
        ),
        "source_spec": _select(
            source_spec,
            ("algorithm_revision", "transport_revision", "repository_revision"),
            "source_spec",
        ),
        "platform_designer": _select(
            pd,
            (
                "system_name",
                "contract_status",
                "address_contract_status",
                "quartus_release",
                "qsys_api_version",
                "hps_component_version",
                "hps_preset_tsv",
                "hps_preset_effective_sha256",
                "hps_preset_application_sha256",
                "hps_parameter_count",
                "hps_applied_parameter_count",
                "hps_readback_only_parameter_count",
                "f2sdram_type",
                "f2sdram_width_bits",
                "qsys_file",
                "generated_dir",
                "sopcinfo_file",
                "sopcinfo_source_package_policy",
                "qip_file",
            ),
            "platform_designer",
        ),
        "exports": dict(exports),
        "internal_interfaces": dict(internal),
        "required_clock_connections": clock_rows,
        "bridges": {
            "csr_bridge": {
                **_select(
                    csr_bridge,
                    (
                        "export",
                        "hps_lw_base_phys",
                        "hps_lw_span_bytes",
                        "csr_offset_in_lw",
                        "csr_base_hps_phys",
                        "csr_span_bytes",
                        "data_width_bits",
                        "master_byte_address_width_bits",
                        "csr_leaf_byte_address_width_bits",
                        "byte_order",
                        "access_alignment_bytes",
                        "full_decode_required",
                        "unused_aperture_policy",
                    ),
                    "bridges.csr_bridge",
                ),
                "address_translation": _select(
                    csr_translation,
                    ("policy", "formula", "offset_bytes"),
                    "bridges.csr_bridge.address_translation",
                ),
            },
            "ddr_writer_bridge": _select(
                ddr_bridge,
                (
                    "export",
                    "writer_rtl",
                    "avmm_master_rtl",
                    "data_width_bits",
                    "byteenable_width_bits",
                    "burstcount_width_bits",
                    "current_burst_policy",
                    "waitrequest_policy",
                    "write_response_policy",
                ),
                "bridges.ddr_writer_bridge",
            ),
        },
        "regions": region_rows,
        "runtime_network": dict(runtime_network),
        "validation_rules": list(
            _require_sequence(address_map.get("validation_rules"), "validation_rules")
        ),
    }


def build_freeze_record(root: Path, address_map: Mapping[str, Any] | None = None) -> dict[str, Any]:
    root = root.resolve()
    source = address_map if address_map is not None else load_json(root / ADDRESS_MAP_REL)
    projection = semantic_projection(source)
    pinned = {rel.as_posix(): sha256_file(root / rel) for rel in PINNED_SOURCE_RELS}
    return {
        "revision": FREEZE_REVISION,
        "scope": FREEZE_SCOPE,
        "hardware_signoff": False,
        "canonicalization": CANONICALIZATION,
        "canonical_sha256": sha256_bytes(canonical_json_bytes(projection)),
        "pinned_source_sha256": pinned,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo-root", type=Path, default=Path(__file__).resolve().parents[1]
    )
    parser.add_argument(
        "--projection",
        action="store_true",
        help="print the canonical semantic projection instead of the freeze record",
    )
    parser.add_argument(
        "--explain",
        action="store_true",
        help="print the canonicalization description to stderr",
    )
    args = parser.parse_args()
    root = args.repo_root.resolve()
    try:
        source = load_json(root / ADDRESS_MAP_REL)
        value = semantic_projection(source) if args.projection else build_freeze_record(root, source)
    except AddressMapContractError as exc:
        print(f"address_map_contract: ERROR: {exc}", file=sys.stderr)
        return 1
    if args.explain:
        print(CANONICALIZATION_DESCRIPTION, file=sys.stderr)
    print(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
