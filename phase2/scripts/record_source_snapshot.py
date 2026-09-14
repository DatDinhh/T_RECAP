#!/usr/bin/env python3
"""Record the maintained reference-source bytes without regenerating numerical artifacts."""
from __future__ import annotations

import argparse
from pathlib import Path
import subprocess
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--proxy-id", default="trecap-phase2-maintained-reference-v1",
                        help="Stable identity of this maintained source lineage")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    command = [sys.executable, str(root / "scripts/reference_import.py"), "refresh-proxy",
               "--repo-root", str(root),
               "--promotion-map", str(root / "config/reference_import_promotions.json"),
               "--proxy-id", args.proxy_id,
               "--output-manifest", "sw/reference_model/import_manifest.json",
               "--output-manifest", "artifacts/manifests/reference_import_manifest.json",
               "--replace-manifests"]
    return subprocess.run(command, cwd=root, check=False).returncode


if __name__ == "__main__":
    raise SystemExit(main())
