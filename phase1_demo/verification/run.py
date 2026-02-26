# Arizona State University 
# Capstone Senior Project
# Sigma Force
# Dat Dinh, Dat Huynh, Paul Applebee, Kyung Jae Son
"""
run.py - ModelSim/Questa runner for T_RECAP Phase1 (non-UVM DV)

It will:
  - create an isolated run directory per test (runs/<test>_<timestamp>/)
  - compile ALL SV sources (including DUT + TB) into a fresh work library
  - run a selected test via +TEST=<name>
  - save logs (compile.log, sim.log) and a small run_summary.json

Notes:
  - This DV is NON-UVM; test selection is done by tb_top.sv using +TEST=<name>.
  - For sweep/stress tests we default scoreboards/monitors to MODEL modes so
    we don’t get false failures if golden memh files are present.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple


# Known tests (tb_top.sv)

KNOWN_TESTS = [
    "golden_thresh16",
    "bypass_lossless",
    "threshold_sweep",
    "clear_metrics_midrun",
    "mode_switch_stress",
]

# Per-test default plusargs we inject for *safety*.
DEFAULT_PLUSARGS_BY_TEST: Dict[str, List[str]] = {
    # Golden test: we want memh/json checks ON. Paths are added automatically
    # from --golden-dir (or will be left as relative x.memh/y.memh/...).
    "golden_thresh16": [],

    # Non-golden tests: force model/pairs modes so memh artifacts (if present)
    # don’t cause false failures.
    "bypass_lossless": [
        "+PAIR_SB_MODE=model",
        "+Y_SB_MODE=model_pairs",
        "+Y_MON_MODE=pairs",
        "+X_MON_MODE=predict",
        "+MET_SB_NO_CHECK_JSON",
    ],
    "threshold_sweep": [
        "+PAIR_SB_MODE=model",
        "+Y_SB_MODE=model_pairs",
        "+Y_MON_MODE=pairs",
        "+X_MON_MODE=predict",
        "+MET_SB_NO_CHECK_JSON",
    ],
    "clear_metrics_midrun": [
        "+PAIR_SB_MODE=model",
        "+Y_SB_MODE=model_pairs",
        "+Y_MON_MODE=pairs",
        "+X_MON_MODE=predict",
        "+MET_SB_NO_CHECK_JSON",
    ],
    "mode_switch_stress": [
        "+PAIR_SB_MODE=model",
        "+Y_SB_MODE=model_pairs",
        "+Y_MON_MODE=pairs",
        "+X_MON_MODE=predict",
        "+MET_SB_NO_CHECK_JSON",
    ],
}

# Patterns to treat as FAIL even if ModelSim returns code 0 (belt + suspenders)
FAIL_PATTERNS = [
    re.compile(r"\*\*\s*Fatal", re.IGNORECASE),
    re.compile(r"\*\*\s*Error", re.IGNORECASE),
    re.compile(r"\$fatal", re.IGNORECASE),
    re.compile(r"\bUVM_FATAL\b", re.IGNORECASE),
    re.compile(r"\bFATAL\b", re.IGNORECASE),
]


@dataclass
class ModelSimTools:
    vlib: Path
    vmap: Path
    vlog: Path
    vsim: Path


def is_windows() -> bool:
    return os.name == "nt"


def _exe(name: str) -> str:
    return name + (".exe" if is_windows() else "")


def find_tools(modelsime_path: Optional[str]) -> ModelSimTools:
    """
    Find vlib/vmap/vlog/vsim based on a user-provided modelsim.exe (or vsim.exe) path
    OR by searching PATH.

    Truth: ModelSim installs multiple executables. Using them directly is the most
    reliable way to get proper return codes for compile/sim.
    """
    candidates: List[Path] = []

    if modelsime_path:
        p = Path(modelsime_path).expanduser()
        candidates.append(p)

    # Also allow environment variable
    env_p = os.environ.get("MODELSIM_EXE") or os.environ.get("MODELSIM") or os.environ.get("QUESTA")
    if env_p:
        candidates.append(Path(env_p).expanduser())

    # Build a list of candidate bin directories
    bin_dirs: List[Path] = []
    for c in candidates:
        if c.is_dir():
            bin_dirs.append(c)
        else:
            bin_dirs.append(c.parent)

    # If none provided, rely on PATH (subprocess will find).
    def tool_path(bin_dir: Optional[Path], tool: str) -> Path:
        if bin_dir is None:
            return Path(_exe(tool))  # resolved by PATH
        return bin_dir / _exe(tool)

    # Try each candidate directory until we find all tools.
    last_err = None
    for bd in bin_dirs:
        t = ModelSimTools(
            vlib=tool_path(bd, "vlib"),
            vmap=tool_path(bd, "vmap"),
            vlog=tool_path(bd, "vlog"),
            vsim=tool_path(bd, "vsim"),
        )
        if all(x.exists() for x in [t.vlib, t.vmap, t.vlog, t.vsim]):
            return t
        last_err = f"Missing one or more tools in {bd}"

    # Fallback: PATH
    t = ModelSimTools(
        vlib=tool_path(None, "vlib"),
        vmap=tool_path(None, "vmap"),
        vlog=tool_path(None, "vlog"),
        vsim=tool_path(None, "vsim"),
    )
    # Can't .exists() these reliably if they are PATH-resolved; we'll just return.
    if not modelsime_path and not env_p:
        return t

    raise FileNotFoundError(
        "Could not locate ModelSim tools (vlib/vmap/vlog/vsim). "
        "Pass --modelsim pointing to modelsim.exe OR ensure they are on PATH. "
        f"Details: {last_err}"
    )


def find_project_paths(script_dir: Path, rtl_path_arg: Optional[str], golden_dir_arg: Optional[str]) -> Tuple[Path, Path, Path]:
    """
    Returns:
      (tb_dir, rtl_file, golden_dir)
    """
    tb_dir = script_dir

    # RTL
    if rtl_path_arg:
        rtl_file = Path(rtl_path_arg).expanduser()
        if not rtl_file.exists():
            raise FileNotFoundError(f"RTL file not found: {rtl_file}")
    else:
        # Try common locations
        cand = [
            tb_dir / "t_recap_demo_top.sv",
            tb_dir.parent / "t_recap_demo_top.sv",
            tb_dir.parent / "rtl" / "t_recap_demo_top.sv",
            tb_dir.parent / "src" / "t_recap_demo_top.sv",
            tb_dir.parent / "rtl" / "phase1" / "t_recap_demo_top.sv",
        ]
        rtl_file = next((p for p in cand if p.exists()), None)
        if rtl_file is None:
            raise FileNotFoundError(
                "Could not find t_recap_demo_top.sv. "
                "Pass --rtl with the full path, e.g. --rtl D:\\T_RECAP\\Phase1\\rtl\\t_recap_demo_top.sv"
            )

    # Golden dir
    if golden_dir_arg:
        golden_dir = Path(golden_dir_arg).expanduser()
        if not golden_dir.exists():
            raise FileNotFoundError(f"Golden dir not found: {golden_dir}")
    else:
        cand = [
            tb_dir.parent / "golden_model",
            tb_dir / "golden_model",
            tb_dir.parent / "golden",
        ]
        golden_dir = next((p for p in cand if p.exists()), cand[0])

    return tb_dir, rtl_file, golden_dir


def sv_sources(tb_dir: Path, rtl_file: Path, use_board_driver_sv: bool = True) -> List[Path]:
    """
    Ordered source list for compilation.
    """
    # TB sources (most are in tb_dir)
    def f(name: str) -> Path:
        return tb_dir / name

    sources = [
        f("tb_pkg.sv"),
        f("board_if.sv"),
        f("tap_if.sv"),
        f("bind_taps.sv"),
        rtl_file,
        f("ref_model_phase1.sv"),
        f("golden_files_loader.sv"),
        f("x_stream_monitor.sv"),
        f("pair_monitor.sv"),
        f("y_stream_monitor.sv"),
        f("metrics_monitor.sv"),
        f("io_monitor.sv"),
        f("scoreboard_pairs.sv"),
        f("scoreboard_y_stream.sv"),
        f("scoreboard_metrics.sv"),
        f("cov_phase1.sv"),
        f("sva_phase1_bind.sv"),
    ]

    if use_board_driver_sv:
        sources.append(f("board_driver.sv"))
    else:
        sources.append(f("board_driver_pkg.sv"))

    sources += [
        f("test_base.sv"),
        f("test_bypass_lossless.sv"),
        f("test_golden_thresh16.sv"),
        f("test_threshold_sweep.sv"),
        f("test_clear_metrics_midrun.sv"),
        f("test_mode_switch_stress.sv"),
        f("tb_top.sv"),
    ]

    # Fail fast if something is missing
    missing = [p for p in sources if not p.exists()]
    if missing:
        msg = "\\n".join(str(p) for p in missing)
        raise FileNotFoundError(f"Missing required SV source files:\\n{msg}")

    return sources


def mkdir_clean(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def timestamp() -> str:
    return _dt.datetime.now().strftime("%Y%m%d_%H%M%S")


def run_cmd(cmd: Sequence[str], cwd: Path, log_path: Path) -> int:
    """
    Run command, teeing stdout/stderr into log_path.
    Returns process return code.
    """
    with log_path.open("w", encoding="utf-8", errors="replace") as f:
        f.write("CMD:\\n  " + " ".join(cmd) + "\\n\\n")
        f.flush()
        p = subprocess.run(
            list(cmd),
            cwd=str(cwd),
            stdout=f,
            stderr=subprocess.STDOUT,
            text=True,
            shell=False,
        )
        return int(p.returncode)


def scan_log_for_fail(log_path: Path) -> Optional[str]:
    if not log_path.exists():
        return None
    txt = log_path.read_text(encoding="utf-8", errors="replace")
    for pat in FAIL_PATTERNS:
        m = pat.search(txt)
        if m:
            # Return a short snippet around the match
            s = max(0, m.start() - 120)
            e = min(len(txt), m.end() + 120)
            snippet = txt[s:e].replace("\\r", "")
            return f"Matched failure pattern '{pat.pattern}'. Snippet:\\n{snippet}"
    return None


def build_plusargs(
    test: str,
    golden_dir: Path,
    want_golden_paths: bool,
    extra_plus: List[str],
) -> List[str]:
    """
    Assemble plusargs list including:
      - per-test defaults (safety)
      - optional golden file paths (for golden test)
      - user extra plusargs
    """
    plusargs: List[str] = []

    # Per-test default (safety)
    plusargs += DEFAULT_PLUSARGS_BY_TEST.get(test, [])

    # Add golden paths if requested (usually only for golden_thresh16)
    if want_golden_paths:
        x = golden_dir / "x.memh"
        y = golden_dir / "y.memh"
        sup = golden_dir / "sup.memh"
        met = golden_dir / "metrics.json"

        # These plusargs are recognized across the TB:
        # - golden_files_loader: X_MEMH/Y_MEMH/SUP_MEMH/METRICS_JSON
        # - test_golden_thresh16: GT_X_FILE/GT_Y_FILE/GT_SUP_FILE/GT_METRICS_FILE
        plusargs += [
            f"+X_MEMH={str(x)}",
            f"+Y_MEMH={str(y)}",
            f"+SUP_MEMH={str(sup)}",
            f"+METRICS_JSON={str(met)}",
            f"+GT_X_FILE={str(x)}",
            f"+GT_Y_FILE={str(y)}",
            f"+GT_SUP_FILE={str(sup)}",
            f"+GT_METRICS_FILE={str(met)}",
        ]

    # User extra plusargs last (so user can override our defaults)
    plusargs += extra_plus

    # Ensure each starts with +
    fixed: List[str] = []
    for p in plusargs:
        if not p:
            continue
        if p[0] != "+":
            fixed.append("+" + p)
        else:
            fixed.append(p)
    return fixed


def copy_golden_artifacts(golden_dir: Path, run_dir: Path) -> None:
    """
    Copy golden artifacts into run_dir as x.memh/y.memh/sup.memh/metrics.json if present.
    This makes relative defaults work and keeps the run self-contained.
    """
    for name in ["x.memh", "y.memh", "sup.memh", "metrics.json"]:
        src = golden_dir / name
        if src.exists():
            shutil.copy2(src, run_dir / name)


def compile_sv(
    tools: ModelSimTools,
    run_dir: Path,
    sources: List[Path],
    incdirs: List[Path],
    defines: List[str],
    coverage: bool,
) -> int:
    # Create work library
    rc = run_cmd([str(tools.vlib), "work"], cwd=run_dir, log_path=run_dir / "vlib.log")
    if rc != 0:
        return rc
    rc = run_cmd([str(tools.vmap), "work", "work"], cwd=run_dir, log_path=run_dir / "vmap.log")
    if rc != 0:
        return rc

    vlog_cmd = [str(tools.vlog), "-sv", "-work", "work", "-suppress", "2892"]
    if coverage:
        # ModelSim: -cover options can vary by edition. We keep it minimal.
        vlog_cmd += ["-cover", "bcst"]

    for d in incdirs:
        vlog_cmd.append(f"+incdir+{str(d)}")
    for df in defines:
        # Accept either "FOO" or "FOO=123"
        if df.startswith("+define+"):
            vlog_cmd.append(df)
        else:
            vlog_cmd.append("+define+" + df)

    vlog_cmd += [str(p) for p in sources]

    rc = run_cmd(vlog_cmd, cwd=run_dir, log_path=run_dir / "compile.log")
    return rc


def sim_sv(
    tools: ModelSimTools,
    run_dir: Path,
    test: str,
    plusargs: List[str],
    gui: bool,
    vopt_acc: bool,
    coverage: bool,
    sv_seed: Optional[int],
    vcd: bool,
    wlf: Optional[str],
) -> int:
    vsim_cmd = [str(tools.vsim)]
    if not gui:
        vsim_cmd += ["-c"]
    # Quiet reduces noise, but still shows $display and errors
    vsim_cmd += ["-quiet"]

    if coverage:
        vsim_cmd += ["-coverage"]

    if sv_seed is not None:
        vsim_cmd += ["-sv_seed", str(sv_seed)]

    if wlf:
        vsim_cmd += ["-wlf", str(run_dir / wlf)]

    # Load top
    top = "work.tb_top"

    # voptargs for signal visibility (good for debug, and makes waves easier)
    if vopt_acc:
        vsim_cmd += ["-voptargs=+acc"]

    # Plusargs: select test and any other knobs
    sim_plus = [f"+TEST={test}"] + plusargs
    vsim_cmd += [top] + sim_plus

    # Runtime do commands
    do_cmds: List[str] = []
    if vcd:
        do_cmds.append("set NoQuitOnFinish 1")
        # VCD creation is controlled by +VCD inside tb_top.sv, but we can still
        # run with +VCD from CLI. 
    if not gui:
        do_cmds.append("run -all")
        # Save coverage if enabled
        if coverage:
            do_cmds.append("coverage save -onexit {coverage.ucdb}")
        do_cmds.append("quit -f")
    else:
        # GUI mode: load and (optionally) run. We default to *not* auto-run.
        do_cmds.append("echo \"[run.py] GUI loaded. Use: run -all\"")

    if do_cmds:
        vsim_cmd += ["-do", "; ".join(do_cmds)]

    rc = run_cmd(vsim_cmd, cwd=run_dir, log_path=run_dir / "sim.log")
    return rc


def write_summary(
    run_dir: Path,
    test: str,
    status: str,
    tools: ModelSimTools,
    sources: List[Path],
    defines: List[str],
    plusargs: List[str],
    extra: Dict,
) -> None:
    summary = {
        "test": test,
        "status": status,
        "run_dir": str(run_dir),
        "timestamp": timestamp(),
        "modelsim_tools": {
            "vlib": str(tools.vlib),
            "vmap": str(tools.vmap),
            "vlog": str(tools.vlog),
            "vsim": str(tools.vsim),
        },
        "defines": defines,
        "plusargs": plusargs,
        "sources": [str(p) for p in sources],
    }
    summary.update(extra)
    (run_dir / "run_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")


def cmd_list_tests(_: argparse.Namespace) -> int:
    print("Available tests (use: --test <name>):")
    for t in KNOWN_TESTS:
        print(f"  - {t}")
    return 0


def cmd_run(ns: argparse.Namespace) -> int:
    script_dir = Path(__file__).resolve().parent
    tb_dir, rtl_file, golden_dir = find_project_paths(script_dir, ns.rtl, ns.golden_dir)

    tools = find_tools(ns.modelsim)

    # Build run directory
    runs_root = tb_dir / "runs"
    mkdir_clean(runs_root)

    run_name = f"{ns.test}_{timestamp()}"
    run_dir = runs_root / run_name
    mkdir_clean(run_dir)

    # Decide whether we need golden artifacts (golden signoff test)
    want_golden_paths = (ns.test == "golden_thresh16")
    if want_golden_paths:
        if not golden_dir.exists():
            raise FileNotFoundError(
                "golden_thresh16 requires the golden_model directory. "
                "Pass --golden-dir, e.g. --golden-dir D:\\T_RECAP\\Phase1\\golden_model"
            )
        required = ["x.memh", "y.memh", "sup.memh", "metrics.json"]
        missing = [n for n in required if not (golden_dir / n).exists()]
        if missing:
            raise FileNotFoundError(
                "Missing golden artifacts in golden_dir: "
                + ", ".join(missing)
                + f"  (golden_dir={golden_dir})"
            )

        # Copy golden artifacts into the run directory so relative defaults work
        # and each run is self-contained.
        if not ns.no_copy_golden:
            copy_golden_artifacts(golden_dir, run_dir)

    # Compile sources
    sources = sv_sources(tb_dir, rtl_file, use_board_driver_sv=True)

    # Include dirs: tb_dir + rtl parent
    incdirs = [tb_dir, rtl_file.parent]

    # Defines (compile-time)
    defines = list(ns.define) if ns.define else []
    if ns.coverage:
        defines.append("TB_ENABLE_COV")
    if ns.sim_sample_div is not None:
        defines.append(f"SIM_SAMPLE_DIV={ns.sim_sample_div}")
    if ns.sim_dbg_div is not None:
        defines.append(f"SIM_DBG_DIV={ns.sim_dbg_div}")

    # Plusargs
    extra_plus = list(ns.plus) if ns.plus else []
    # Option toggles
    if ns.vcd and not any(p.startswith("+VCD") for p in extra_plus):
        extra_plus.append("+VCD")
    if ns.tb_verbose and not any(p.startswith("+TB_VERBOSE") for p in extra_plus):
        extra_plus.append("+TB_VERBOSE")

    plusargs = build_plusargs(
        test=ns.test,
        golden_dir=golden_dir,
        want_golden_paths=want_golden_paths,
        extra_plus=extra_plus,
    )

    # Print where we're running (useful when debugging file path issues)
    print(f"[run.py] Run dir: {run_dir}")
    print(f"[run.py] RTL: {rtl_file}")
    if ns.test == "golden_thresh16":
        print(f"[run.py] Golden dir: {golden_dir}")

    # Compile
    rc = compile_sv(
        tools=tools,
        run_dir=run_dir,
        sources=sources,
        incdirs=incdirs,
        defines=defines,
        coverage=ns.coverage,
    )
    if rc != 0:
        reason = scan_log_for_fail(run_dir / "compile.log") or f"vlog return code {rc}"
        print("[run.py] COMPILE FAIL:", reason)
        write_summary(run_dir, ns.test, "COMPILE_FAIL", tools, sources, defines, plusargs, {"reason": reason})
        return rc

    # Simulate
    rc = sim_sv(
        tools=tools,
        run_dir=run_dir,
        test=ns.test,
        plusargs=plusargs,
        gui=ns.gui,
        vopt_acc=not ns.no_acc,
        coverage=ns.coverage,
        sv_seed=ns.sv_seed,
        vcd=ns.vcd,
        wlf=ns.wlf,
    )

    # Determine PASS/FAIL
    fail_reason = scan_log_for_fail(run_dir / "sim.log")
    if rc != 0:
        status = "SIM_FAIL"
        fail_reason = fail_reason or f"vsim return code {rc}"
    elif fail_reason:
        status = "SIM_FAIL"
    else:
        status = "PASS"

    print(f"[run.py] {ns.test}: {status}")
    if fail_reason and status != "PASS":
        print("[run.py] Reason:", fail_reason)

    write_summary(run_dir, ns.test, status, tools, sources, defines, plusargs, {"reason": fail_reason or ""})

    # VCD
    if ns.vcd:
        vcd_path = run_dir / "waves.vcd"
        if not vcd_path.exists():
            print("[run.py] NOTE: You requested --vcd but waves.vcd not found.")
            print("         Make sure +VCD is being passed and tb_top.sv sees it.")

    return 0 if status == "PASS" else 1


def cmd_regress(ns: argparse.Namespace) -> int:
    # Run a list of tests (each gets its own run dir)
    tests = ns.tests or KNOWN_TESTS
    rc_all = 0
    for t in tests:
        ns_run = argparse.Namespace(**vars(ns))
        ns_run.test = t
        # In regress mode, never open GUI
        ns_run.gui = False
        rc = cmd_run(ns_run)
        if rc != 0:
            rc_all = rc_all or rc
    return rc_all


def cmd_clean(ns: argparse.Namespace) -> int:
    script_dir = Path(__file__).resolve().parent
    runs_root = script_dir / "runs"
    if runs_root.exists():
        shutil.rmtree(runs_root)
        print(f"[run.py] Deleted: {runs_root}")
    else:
        print(f"[run.py] Nothing to clean: {runs_root} does not exist.")
    return 0


def build_argparser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="T_RECAP Phase1 ModelSim runner (non-UVM DV)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    ap_list = sub.add_parser("list-tests", help="List tests known by tb_top.sv")
    ap_list.set_defaults(func=cmd_list_tests)

    def add_common(p: argparse.ArgumentParser) -> None:
        p.add_argument("--modelsim", type=str, default=None,
                       help="Path to modelsim.exe (or the bin directory). "
                            "Example: D:\\Quartus\\modelsim_ase\\win32aloem\\modelsim.exe")
        p.add_argument("--rtl", type=str, default=None,
                       help="Path to t_recap_demo_top.sv (if not in default locations).")
        p.add_argument("--golden-dir", type=str, default=None,
                       help="Path to golden_model directory containing x.memh/y.memh/sup.memh/metrics.json.")
        p.add_argument("--define", action="append", default=[],
                       help="Extra compile define (FOO or FOO=123). Can be repeated.")
        p.add_argument("--plus", action="append", default=[],
                       help="Extra simulator plusarg (with or without leading +). Can be repeated.")
        p.add_argument("--sim-sample-div", type=int, default=None,
                       help="Compile-time define SIM_SAMPLE_DIV (tb_top overrides SAMPLE_DIV).")
        p.add_argument("--sim-dbg-div", type=int, default=None,
                       help="Compile-time define SIM_DBG_DIV (tb_top overrides DBG_DIV).")
        p.add_argument("--coverage", action="store_true",
                       help="Enable simulator coverage (if supported by your ModelSim edition).")
        p.add_argument("--sv-seed", type=int, default=None,
                       help="Pass -sv_seed to vsim for SV randomization.")
        p.add_argument("--vcd", action="store_true",
                       help="Enable VCD dumping (adds +VCD). Produces waves.vcd in run dir.")
        p.add_argument("--wlf", type=str, default="waves.wlf",
                       help="WLF wave file name (default waves.wlf). Use '' to disable.")
        p.add_argument("--no-acc", action="store_true",
                       help="Disable -voptargs=+acc (less visibility, slightly faster).")
        p.add_argument("--tb-verbose", action="store_true",
                       help="Add +TB_VERBOSE automatically.")
        p.add_argument("--no-copy-golden", action="store_true",
                       help="Do not copy golden artifacts into the run dir (golden test only).")

    ap_run = sub.add_parser("run", help="Compile+run one test")
    ap_run.add_argument("--test", required=True, choices=KNOWN_TESTS, help="Test name (tb_top +TEST=...)")
    ap_run.add_argument("--gui", action="store_true", help="Open GUI (loads design but does not auto-run).")
    add_common(ap_run)
    ap_run.set_defaults(func=cmd_run)

    ap_reg = sub.add_parser("regress", help="Run multiple tests (each in its own run dir)")
    ap_reg.add_argument("--tests", nargs="*", default=None,
                        help="Optional list of tests. Default = all known tests.")
    add_common(ap_reg)
    ap_reg.set_defaults(func=cmd_regress)

    ap_clean = sub.add_parser("clean", help="Delete runs/ directory")
    ap_clean.set_defaults(func=cmd_clean)

    return ap


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = build_argparser()
    ns = ap.parse_args(argv)

    # Handle wlf disabling
    if hasattr(ns, "wlf") and ns.wlf == "":
        ns.wlf = None

    # Sanity: user asked for a known test
    if hasattr(ns, "test"):
        if ns.test not in KNOWN_TESTS:
            print(f"[run.py] Unknown test: {ns.test}", file=sys.stderr)
            return 2

    try:
        return int(ns.func(ns))
    except FileNotFoundError as e:
        print(f"[run.py] ERROR: {e}", file=sys.stderr)
        return 2
    except subprocess.CalledProcessError as e:
        print(f"[run.py] ERROR: command failed: {e}", file=sys.stderr)
        return int(e.returncode) if e.returncode is not None else 1


if __name__ == "__main__":
    raise SystemExit(main())
