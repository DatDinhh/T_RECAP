#!/usr/bin/env python3
"""Check generated T-RECAP Phase 2 contract outputs for drift.

File class: [1] hand-written repository infrastructure.

The script is intentionally stricter than a plain `git diff` wrapper because the
project commits generated SV/C/Python headers and generated filelists. It checks
that the generator scripts are runnable, that checked-in outputs match fresh
regeneration, and that the generated manifest hashes describe the checked-in
files that actually exist on disk.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Iterable, Mapping, Sequence

try:
    import jsonschema
except Exception as exc:  # pragma: no cover - dependency-failure regression
    jsonschema = None  # type: ignore[assignment]
    JSONSCHEMA_IMPORT_ERROR: Exception | None = exc
else:
    JSONSCHEMA_IMPORT_ERROR = None

REQUIRED_GENERATED_OUTPUTS = [
    "rtl/include/generated/trecap_core_pkg.sv",
    "rtl/include/generated/trecap_csr_pkg.sv",
    "rtl/include/generated/trecap_packet_pkg.sv",
    "rtl/include/generated/trecap_iface_pkg.sv",
    "sw/hps/include/generated/trecap_csr.h",
    "sw/hps/include/generated/trecap_packet.h",
    "sw/pc_dashboard/generated/trecap_packet.py",
    "sw/reference_model/generated/trecap_config.py",
]

# These generated contract sources must remain explicit manifest inputs. The
# generator's --check pass below then proves their SV/C/Python mirrors are
# byte-for-byte current rather than merely present.
REQUIRED_CONTRACT_MIRRORS = {
    "spec/generated/csr_map.json": (
        "rtl/include/generated/trecap_csr_pkg.sv",
        "sw/hps/include/generated/trecap_csr.h",
    ),
    "spec/generated/packet_layouts.json": (
        "rtl/include/generated/trecap_packet_pkg.sv",
        "sw/hps/include/generated/trecap_packet.h",
        "sw/pc_dashboard/generated/trecap_packet.py",
    ),
}

REQUIRED_FILELISTS = [
    "filelists/rtl_core.f",
    "filelists/rtl_core_plus_fft.f",
    "filelists/rtl_telemetry.f",
    "filelists/rtl_core_telemetry.f",
    "filelists/rtl_hps_bridge.f",
    "filelists/rtl_de1soc_full.f",
    "filelists/quartus_de1soc.qsf.inc",
]

SOURCE_SCHEMA_PAIRS = [
    ("spec/generated/csr_map.json", "spec/schemas/csr_map.schema.json"),
    ("spec/generated/packet_layouts.json", "spec/schemas/packet_layouts.schema.json"),
    ("spec/generated/interface_types.json", "spec/schemas/interface_types.schema.json"),
    (
        "config/boards/de1soc_clock_reset_architecture.json",
        "spec/schemas/de1soc_clock_reset_architecture.schema.json",
    ),
    (
        "config/boards/de1soc_audio_linein.json",
        "spec/schemas/de1soc_audio_linein.schema.json",
    ),
    (
        "config/boards/de1soc_command_path.json",
        "spec/schemas/de1soc_command_path.schema.json",
    ),
]

CSR_FREEZE_NEGATIVE_TEST = "tests/test_gen_headers_csr_freeze.py"
COMMAND_CONTRACT_FREEZE_NEGATIVE_TEST = "tests/test_command_path_contract_freeze.py"


class CheckFailure(RuntimeError):
    pass


def repo_root_from_script() -> Path:
    return Path(__file__).resolve().parents[1]


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_json(path: Path) -> object:
    def reject_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise CheckFailure(f"duplicate JSON key in {path}: {key!r}")
            result[key] = value
        return result

    def reject_nonfinite(value: str) -> None:
        raise CheckFailure(f"non-finite JSON number in {path}: {value}")

    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise CheckFailure(f"cannot read JSON file {path}: {exc}") from exc
    if raw.startswith(b"\xef\xbb\xbf"):
        raise CheckFailure(f"UTF-8 BOM is forbidden in {path}")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise CheckFailure(f"{path} is not UTF-8: {exc}") from exc
    try:
        return json.loads(
            text,
            object_pairs_hook=reject_duplicates,
            parse_constant=reject_nonfinite,
        )
    except json.JSONDecodeError as exc:
        raise CheckFailure(f"invalid JSON in {path}: {exc}") from exc


def run_cmd(root: Path, cmd: Sequence[str], quiet: bool) -> None:
    if not quiet:
        print("+ " + " ".join(cmd))
    proc = subprocess.run(
        list(cmd),
        cwd=root,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    if proc.returncode != 0:
        if proc.stdout:
            print(proc.stdout, file=sys.stderr, end="" if proc.stdout.endswith("\n") else "\n")
        raise CheckFailure(f"command failed with exit code {proc.returncode}: {' '.join(cmd)}")
    if proc.stdout and not quiet:
        print(proc.stdout, end="" if proc.stdout.endswith("\n") else "\n")


def check_required_files(root: Path, paths: Iterable[str]) -> None:
    missing = [p for p in paths if not (root / p).is_file()]
    if missing:
        raise CheckFailure("missing generated output files:\n  " + "\n  ".join(missing))


def check_no_edit_banners(root: Path) -> None:
    for rel in REQUIRED_GENERATED_OUTPUTS:
        path = root / rel
        text = path.read_text(encoding="utf-8", errors="replace")[:512]
        if "AUTO-GENERATED - DO NOT EDIT" not in text:
            raise CheckFailure(f"generated output missing no-edit banner: {rel}")
    for rel in REQUIRED_FILELISTS:
        text = (root / rel).read_text(encoding="utf-8", errors="replace")[:512]
        if "AUTO-GENERATED - DO NOT EDIT" not in text:
            raise CheckFailure(f"generated filelist missing no-edit banner: {rel}")


def validate_source_schemas(root: Path, quiet: bool) -> None:
    if jsonschema is None:
        raise CheckFailure(
            "jsonschema is required for generated-contract validation; "
            f"install the locked dependencies ({JSONSCHEMA_IMPORT_ERROR})"
        )
    for source_rel, schema_rel in SOURCE_SCHEMA_PAIRS:
        source = root / source_rel
        schema = root / schema_rel
        if not source.exists() or not schema.exists():
            raise CheckFailure(f"schema/source pair missing: {source_rel}, {schema_rel}")
        try:
            jsonschema.Draft202012Validator(load_json(schema)).validate(load_json(source))
        except Exception as exc:  # jsonschema has multiple exception classes
            raise CheckFailure(f"{source_rel} does not validate against {schema_rel}: {exc}") from exc


def check_manifest(root: Path) -> None:
    manifest_path = root / "spec/generated/gen_manifest.json"
    if not manifest_path.is_file():
        raise CheckFailure("missing generated manifest: spec/generated/gen_manifest.json")
    manifest = load_json(manifest_path)
    if not isinstance(manifest, Mapping):
        raise CheckFailure("gen_manifest.json root must be an object")
    if manifest.get("schema") != "trecap_phase2_gen_manifest_v1":
        raise CheckFailure("gen_manifest.json has unexpected schema")
    generator = manifest.get("generator", {})
    if not isinstance(generator, Mapping) or generator.get("path") != "scripts/gen_headers.py":
        raise CheckFailure("gen_manifest.json generator.path must be scripts/gen_headers.py")

    output_entries = manifest.get("output_files", [])
    if not isinstance(output_entries, list):
        raise CheckFailure("gen_manifest.json output_files must be a list")
    output_by_path = {str(item.get("path")): str(item.get("sha256")) for item in output_entries if isinstance(item, Mapping)}
    for rel in REQUIRED_GENERATED_OUTPUTS:
        if rel not in output_by_path:
            raise CheckFailure(f"gen_manifest.json does not list generated output: {rel}")
        actual = sha256_file(root / rel)
        if actual != output_by_path[rel]:
            raise CheckFailure(f"gen_manifest hash mismatch for {rel}: manifest={output_by_path[rel]} actual={actual}")

    source_entries = manifest.get("source_files", [])
    if not isinstance(source_entries, list):
        raise CheckFailure("gen_manifest.json source_files must be a list")
    source_by_path = {
        str(item.get("path")): str(item.get("sha256"))
        for item in source_entries
        if isinstance(item, Mapping)
    }
    for source_rel, mirror_rels in REQUIRED_CONTRACT_MIRRORS.items():
        if source_rel not in source_by_path:
            raise CheckFailure(f"gen_manifest.json does not list contract source: {source_rel}")
        for mirror_rel in mirror_rels:
            if mirror_rel not in output_by_path:
                raise CheckFailure(
                    f"gen_manifest.json does not list {source_rel} mirror: {mirror_rel}"
                )
    for item in source_entries:
        if not isinstance(item, Mapping):
            raise CheckFailure("gen_manifest.json source file entry is not an object")
        rel = str(item.get("path"))
        sha = str(item.get("sha256"))
        path = root / rel
        if not path.is_file():
            raise CheckFailure(f"gen_manifest source file no longer exists: {rel}")
        actual = sha256_file(path)
        if actual != sha:
            raise CheckFailure(f"gen_manifest source hash mismatch for {rel}: manifest={sha} actual={actual}")


def check_filelist_ownership(root: Path) -> None:
    for rel in REQUIRED_FILELISTS:
        text = (root / rel).read_text(encoding="utf-8", errors="replace")
        if "legacy/" in text or "legacy\\" in text:
            raise CheckFailure(f"generated filelist includes legacy path: {rel}")
    telemetry = (root / "filelists/rtl_telemetry.f").read_text(encoding="utf-8", errors="replace")
    if "trecap_ddr_ring_writer.sv" in telemetry:
        raise CheckFailure("rtl_telemetry.f must not include trecap_ddr_ring_writer.sv")
    if "rtl/core/trecap_core_top.sv" in telemetry or "rtl/top/trecap_core_telemetry_top.sv" in telemetry:
        raise CheckFailure("rtl_telemetry.f must remain a telemetry-only compile closure")

    core_telemetry = (root / "filelists/rtl_core_telemetry.f").read_text(
        encoding="utf-8", errors="replace"
    )
    for required in (
        "rtl/core/trecap_core_top.sv",
        "rtl/telemetry/trecap_telemetry_top.sv",
        "rtl/top/trecap_core_telemetry_top.sv",
    ):
        if core_telemetry.count(required) != 1:
            raise CheckFailure(f"rtl_core_telemetry.f must list {required} exactly once")
    if "rtl/hps_bridge/" in core_telemetry or "rtl/sources/" in core_telemetry:
        raise CheckFailure(
            "rtl_core_telemetry.f must not own source selection or the HPS/DDR bridge"
        )

    for rel in ("filelists/rtl_de1soc_full.f", "filelists/quartus_de1soc.qsf.inc"):
        board_closure = (root / rel).read_text(encoding="utf-8", errors="replace")
        if "rtl/top/trecap_core_telemetry_top.sv" in board_closure:
            raise CheckFailure(
                f"{rel} must not add the standalone core+telemetry top to the source-owned board core"
            )
        for required in (
            "rtl/platform/de1soc/platform_designer_wrapper.sv",
            "rtl/platform/de1soc/audio_codec_wrapper.sv",
            "rtl/platform/de1soc/adc_wrapper.sv",
            "rtl/platform/de1soc/clock_reset_ctrl.sv",
            "rtl/top/trecap_source_core_integration.sv",
            "rtl/top/trecap_de1soc_full_top.sv",
            "rtl/platform/de1soc/de1_soc_trecap_top.sv",
        ):
            if board_closure.count(required) != 1:
                raise CheckFailure(f"{rel} must list {required} exactly once")


def check_git_diff(root: Path, quiet: bool) -> None:
    git_dir = root / ".git"
    if not git_dir.exists():
        if not quiet:
            print("warning: .git not present; skipped git diff generated-output check")
        return
    paths = ["spec/generated/gen_manifest.json", *REQUIRED_GENERATED_OUTPUTS, *REQUIRED_FILELISTS]
    proc = subprocess.run(
        ["git", "diff", "--exit-code", "--", *paths],
        cwd=root,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    if proc.returncode != 0:
        if proc.stdout:
            print(proc.stdout, file=sys.stderr, end="" if proc.stdout.endswith("\n") else "\n")
        raise CheckFailure("generated outputs differ from the git index/worktree")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check generated T-RECAP Phase 2 contract outputs.")
    parser.add_argument("--root", default=None, help="Repository root. Default: parent of this script directory.")
    parser.add_argument("--headers-only", action="store_true", help="Only check generated headers/configs.")
    parser.add_argument("--filelists-only", action="store_true", help="Only check generated filelists.")
    parser.add_argument("--skip-schema", action="store_true", help="Skip JSON Schema validation.")
    parser.add_argument("--git-diff", action="store_true", help="Also require no git diff in generated outputs when .git exists.")
    parser.add_argument("--quiet", action="store_true", help="Reduce progress output.")
    args = parser.parse_args(argv)

    root = Path(args.root).resolve() if args.root else repo_root_from_script()
    if not (root / "Makefile").is_file():
        print(f"ERROR: repository root does not look valid: {root}", file=sys.stderr)
        return 2

    try:
        if not args.filelists_only:
            check_required_files(root, REQUIRED_GENERATED_OUTPUTS)
            if not args.skip_schema:
                validate_source_schemas(root, args.quiet)
            run_cmd(root, [sys.executable, CSR_FREEZE_NEGATIVE_TEST], args.quiet)
            run_cmd(root, [sys.executable, COMMAND_CONTRACT_FREEZE_NEGATIVE_TEST], args.quiet)
            run_cmd(root, [sys.executable, "scripts/gen_headers.py", "--check", "--quiet"], args.quiet)
            check_manifest(root)
        if not args.headers_only:
            check_required_files(root, REQUIRED_FILELISTS)
            run_cmd(root, [sys.executable, "scripts/gen_filelists.py", "--check", "--quiet"], args.quiet)
            check_filelist_ownership(root)
        check_no_edit_banners(root)
        if args.git_diff:
            check_git_diff(root, args.quiet)
    except CheckFailure as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    if not args.quiet:
        print("check_generated: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
