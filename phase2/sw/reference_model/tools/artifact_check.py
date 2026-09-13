#!/usr/bin/env python3
"""Fail-closed T-RECAP artifact, release, and import-provenance checker."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REFERENCE_ROOT = Path(__file__).resolve().parents[1]
PYTHON_ROOT = REFERENCE_ROOT / "python"
if str(PYTHON_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_ROOT))

from trecap_golden.artifacts.checker import (  # noqa: E402
    CheckReport,
    check_artifact_tree,
    check_reference_import_manifest,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Validate the complete T-RECAP artifact DAG. Missing dependencies, "
            "schemas, release manifests, files, hashes, or paths are fatal."
        )
    )
    parser.add_argument("--artifacts", type=Path, default=Path("artifacts"))
    parser.add_argument("--schemas", type=Path, default=Path("spec/schemas"))
    parser.add_argument(
        "--output-subdir",
        choices=("golden", "reference_outputs"),
        default=None,
        help="Expected output namespace. Default: require unambiguous auto-detection.",
    )
    parser.add_argument(
        "--source-root",
        type=Path,
        default=REFERENCE_ROOT,
        help="Reference source root used to authenticate generator source bundles.",
    )
    parser.add_argument(
        "--allow-unfrozen",
        action="store_true",
        help=(
            "Explicit pre-freeze content mode. It ignores index/release manifests "
            "and must never be used for packaging or signoff."
        ),
    )
    parser.add_argument(
        "--architecture-root",
        type=Path,
        default=None,
        help="Architecture repository root for v3 import/provenance verification.",
    )
    parser.add_argument(
        "--import-manifest",
        type=Path,
        default=None,
        help="v3 reference import manifest to verify after the artifact DAG.",
    )
    parser.add_argument(
        "--require-verified-source",
        action="store_true",
        help="Reject an explicitly unverified embedded-proxy source status.",
    )
    parser.add_argument(
        "--source-archive",
        type=Path,
        default=None,
        help="Optional clean source archive whose exact hash must match the v3 record.",
    )
    parser.add_argument("--json", action="store_true", help="Emit a machine-readable report.")
    return parser


def _print_human(report: CheckReport) -> None:
    for issue in report.issues:
        stream = sys.stderr if issue.severity == "error" else sys.stdout
        print(
            f"{issue.severity.upper()}: {issue.path}: {issue.check}: {issue.message}",
            file=stream,
        )
    if report.ok:
        checked = " ".join(f"{key}={value}" for key, value in sorted(report.checked.items()))
        print(f"artifact_check: OK {checked}")
    else:
        errors = sum(issue.severity == "error" for issue in report.issues)
        print(f"artifact_check: FAIL errors={errors}", file=sys.stderr)


def run(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    report = check_artifact_tree(
        args.artifacts,
        schemas_dir=args.schemas,
        output_subdir=args.output_subdir,
        source_root=args.source_root,
        require_frozen=not args.allow_unfrozen,
    )
    if args.import_manifest is not None or args.architecture_root is not None:
        if args.import_manifest is None or args.architecture_root is None:
            report.add_issue(
                args.import_manifest or args.architecture_root or Path("."),
                "arguments",
                "--architecture-root and --import-manifest must be supplied together",
            )
        else:
            check_reference_import_manifest(
                args.architecture_root,
                args.import_manifest,
                schemas_dir=args.schemas,
                require_verified_source=args.require_verified_source,
                source_archive=args.source_archive,
                report=report,
            )
    if args.json:
        print(json.dumps(report.to_dict(), indent=2, sort_keys=True))
    else:
        _print_human(report)
    return 0 if report.ok else 2


if __name__ == "__main__":
    raise SystemExit(run())
