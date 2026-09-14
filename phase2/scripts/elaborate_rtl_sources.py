#!/usr/bin/env python3
"""Elaborate the production board RTL; do not run a simulator or testbench."""
from __future__ import annotations

import argparse
from collections import Counter
import importlib.metadata
import os
from pathlib import Path
import sys


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--report", type=Path, default=Path("build/rtl-source-diagnostics.txt"))
    args = parser.parse_args()
    try:
        from pyslang import DiagnosticEngine
        from pyslang.driver import Driver
    except ImportError:
        parser.error("install scripts/requirements-source.txt in the source-tools environment")
    version = importlib.metadata.version("pyslang")
    if version != "11.0.0":
        parser.error(f"pyslang11.0.0 is required; found {version}")
    os.chdir(args.root.resolve())
    driver = Driver()
    driver.addStandardArgs()
    # Vendor IP remains external. Do not hide unknown project modules with a
    # global ignore-unknown option or substitute fabricated vendor port stubs.
    command = ("slang -f filelists/rtl_de1soc_full.f "
               "--top de1_soc_trecap_top -DSYNTHESIS")
    if not driver.parseCommandLine(command) or not driver.processOptions():
        return 2
    if not driver.parseAllSources():
        driver.reportParseDiags()
        return 1
    compilation = driver.createCompilation()
    diagnostics = compilation.getAllDiagnostics()
    external = []
    retained = []
    for diagnostic in diagnostics:
        if (str(diagnostic.code) == "DiagCode(UnknownModule)"
                and len(diagnostic.args) == 1
                and str(diagnostic.args[0]) in {"system", "altera_pll"}):
            external.append(str(diagnostic.args[0]))
        else:
            retained.append(diagnostic)
    errors = sum(d.isError() for d in retained)
    warnings = len(retained) - errors
    rendered = DiagnosticEngine.reportAll(compilation.sourceManager, retained)
    counts = Counter(str(d.code) for d in retained)
    summary = (f"Production RTL: {errors} errors, {warnings} non-error diagnostics.\n"
               f"External vendor modules: {', '.join(sorted(set(external))) or 'none'}.\n"
               "No simulation, testbench, or generated vendor IP was executed.\n")
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(summary + "\n" + rendered + "\n" +
                           "\n".join(f"{k}: {v}" for k, v in sorted(counts.items())) + "\n",
                           encoding="utf-8")
    print(summary, end="")
    print(f"Diagnostic report: {args.report}")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
