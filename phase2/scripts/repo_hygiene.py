#!/usr/bin/env python3
"""Check source hygiene without importing project code or running functional tests."""
from __future__ import annotations

import argparse
import ast
import json
import os
from pathlib import Path
import re
import sys
import subprocess
import tomllib
import xml.etree.ElementTree as ET
import zipfile
from urllib.parse import unquote, urlsplit

IGNORED_DIRS = {
    ".git", ".venv", "venv", "env", "ENV", "__pycache__", ".pytest_cache",
    ".mypy_cache", ".ruff_cache", ".cache", ".tox", ".nox", "node_modules",
    "build", "out", "runs", "dist", "install", "CMakeFiles", "Testing",
    "db", "incremental_db", "output_files", "work", "htmlcov", ".idea", ".vscode",
}
BINARY_SUFFIXES = {".pdf", ".png", ".jpg", ".jpeg", ".gif", ".ico", ".woff", ".woff2"}
LOCAL_SUFFIXES = {
    ".exe", ".dll", ".obj", ".o", ".a", ".lib", ".pdb", ".so", ".dylib",
    ".pyc", ".zip", ".7z", ".tar", ".gz", ".sof", ".rbf", ".wlf", ".vcd",
    ".log", ".bak", ".tmp",
}
PERSONAL_PATH = re.compile(
    r"(?:[A-Za-z]:[\\/]+Users[\\/]+(?!Public\b|Default\b)[A-Za-z0-9_.-]+"
    r"|/(?:Users|home)/[A-Za-z0-9_.-]+)"
)
SECRET_PATTERNS = (
    re.compile(r"^-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----$"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}\b"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{60,}\b"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{20,}\b"),
)
CONFLICT = re.compile(r"^(?:<<<<<<< |>>>>>>> )")
LINK = re.compile(r'!?\[[^\]\n]*\]\((?:<([^>\n]+)>|([^\s)]+))(?:\s+"[^"\n]*")?\)')


# Local exports already excluded by .gitignore. Only the non-Git source walk
# skips these exact paths; accidentally tracked copies still fail the Git scan.
LOCAL_EXPORT_PATHS = {
    "docs/presentation/T_RECAP_Architecture_Figures_20260922.zip",
    "docs/presentation/T_RECAP_Reference_Model_Figures_20260922.zip",
    "docs/presentation/architecture_20260922/data/stalled/architecture.vcd",
    "docs/presentation/architecture_20260922/data/static/architecture.vcd",
}

# These text receipts were reviewed for public evidence and intentionally retained.
PUBLIC_RECEIPT_DIR = "docs/results/hps_cpu_benchmark_20260925/data/qualification"
# Links in this generator input are relative to the reviewed generated report.
MARKDOWN_OUTPUT_DIRS = {
    "experiments/ifft_zero_isolation/study/report_template.md":
        "docs/results/ifft_zero_isolation_20260925",
}


def git_source_files(root: Path):
    """Return publishable checkout files; keep tracked ignored files visible."""
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "ls-files", "--cached", "--others",
             "--exclude-standard", "-z", "--", "."],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
        )
    except OSError:
        return None
    if result.returncode:
        return None
    paths = []
    for raw_name in result.stdout.split(b"\0"):
        if raw_name:
            path = root / os.fsdecode(raw_name)
            # Deleted index entries are not a local source file; Git reviews them.
            if path.exists() or path.is_symlink():
                paths.append(path)
    return sorted(set(paths))


def source_files(root: Path):
    """Walk source without following directory links or entering local build trees."""
    git_paths = git_source_files(root)
    if git_paths is not None:
        yield from git_paths
        return
    for directory, names, filenames in os.walk(root, followlinks=False):
        parent = Path(directory)
        # Quartus products are local build output; their vendor-generated text
        # is not maintained repository source. The normalized .qsys is retained.
        if parent.relative_to(root).as_posix() == "platform/de1soc/qsys":
            names[:] = [name for name in names if name != "system"]
            filenames = [name for name in filenames if name != "system.sopcinfo"]
        if parent.relative_to(root).as_posix() == "platform/de1soc/quartus":
            # Quartus emits matched preloader data, including binary .hiof files.
            # The complete generated handoff stays in local build/run evidence.
            names[:] = [name for name in names if name != "hps_isw_handoff"]
            # The vendor DDR pin script can leave its diagnostic dump here
            # after a failed/interrupted run; it is not maintained source.
            filenames = [name for name in filenames if name != "hps_sdram_p0_all_pins.txt"]
        names[:] = sorted(name for name in names if name not in IGNORED_DIRS
                          and not name.startswith(("build-", "build_", "cmake-build-")))
        for name in list(names):
            path = parent / name
            if path.is_symlink():
                yield path
                names.remove(name)
        for name in sorted(filenames):
            path = parent / name
            if path.relative_to(root).as_posix() not in LOCAL_EXPORT_PATHS:
                yield path


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def invalid_constant(value):
    raise ValueError(f"non-finite JSON number: {value}")


def markdown_links(text):
    fence = None
    for number, line in enumerate(text.splitlines(), 1):
        stripped = line.lstrip()
        marker = re.match(r"(`{3,}|~{3,})", stripped)
        if marker:
            token = marker.group(1)
            if fence is None:
                fence = token
            elif token[0] == fence[0] and len(token) >= len(fence):
                fence = None
            continue
        if fence is None:
            # Inline code often contains illustrative Markdown rather than a link.
            line = re.sub(r"`[^`]*`", "", line)
            for match in LINK.finditer(line):
                yield number, match.group(1) or match.group(2)


def check_presentation(path: Path, report):
    """Inspect Open XML text and metadata without extracting embedded files."""
    try:
        with zipfile.ZipFile(path) as archive:
            parts = archive.infolist()
            if len(parts) > 1000 or sum(part.file_size for part in parts) > 50 * 1024 * 1024:
                report(path, "presentation exceeds the package-review limit")
                return
            names = [part.filename for part in parts]
            if len(names) != len(set(names)):
                report(path, "presentation contains duplicate package entries")
            if "[Content_Types].xml" not in names or "ppt/presentation.xml" not in names:
                report(path, "presentation is missing required Open XML parts")
            for part in parts:
                name = part.filename
                if part.is_dir():
                    continue
                if name.startswith("/") or ".." in Path(name).parts or "\\" in name:
                    report(path, "presentation contains an unsafe package path")
                    continue
                if not name.endswith((".xml", ".rels")):
                    # Images are ordinary presentation assets; embedded programs
                    # and other opaque payloads need an explicit publication review.
                    if not (name.startswith("ppt/media/") and Path(name).suffix.lower() in BINARY_SUFFIXES):
                        report(path, "presentation contains an unreviewed binary part")
                    continue
                raw = archive.read(part)
                tree = ET.fromstring(raw)
                content = "\n".join(list(tree.itertext()) + [
                    value for element in tree.iter() for value in element.attrib.values()
                ])
                if PERSONAL_PATH.search(content):
                    report(path, "personal absolute path in presentation XML (value withheld)")
                if any(pattern.search(line.strip())
                       for line in content.splitlines() for pattern in SECRET_PATTERNS):
                    report(path, "possible credential in presentation XML (value withheld)")
                if name.endswith(".rels"):
                    for relation in tree:
                        if relation.get("TargetMode") == "External":
                            target = relation.get("Target", "")
                            if urlsplit(target).scheme.lower() not in {"https", "http", "mailto"}:
                                report(path, "presentation has a local or unsupported external relationship")
    except (OSError, zipfile.BadZipFile, ET.ParseError, UnicodeError, RuntimeError):
        report(path, "invalid or unreadable Open XML presentation")


def check(root: Path) -> tuple[int, list[str]]:
    issues = []
    seen = {}
    count = 0

    def report(path, message, line=None):
        location = path.relative_to(root).as_posix()
        if line is not None:
            location += f":{line}"
        issues.append(f"{location}: {message}")

    for path in source_files(root):
        count += 1
        relative = path.relative_to(root).as_posix()
        folded = relative.casefold()
        if folded in seen and seen[folded] != relative:
            report(path, f"case-insensitive path collision with {seen[folded]}")
        seen[folded] = relative
        if path.is_symlink():
            if not path.resolve().is_relative_to(root):
                report(path, "symlink points outside the repository")
            continue
        public_receipt = (path.parent.relative_to(root).as_posix() == PUBLIC_RECEIPT_DIR
                          and path.suffix.lower() == ".log")
        if path.suffix.lower() in LOCAL_SUFFIXES and not public_receipt:
            report(path, "local build/output file in the source tree")
            continue
        if path.stat().st_size > 10 * 1024 * 1024:
            report(path, "file exceeds the 10 MiB source-review limit")
            continue
        if path.name == ".env" or (path.name.startswith(".env.")
                                    and path.name not in {".env.example", ".env.sample"}):
            report(path, "local environment file must stay outside source distribution")
        if path.suffix.lower() == ".pptx":
            check_presentation(path, report)
            continue
        if path.suffix.lower() in BINARY_SUFFIXES:
            continue
        raw = path.read_bytes()
        if b"\0" in raw:
            report(path, "unexpected binary content in a source file")
            continue
        try:
            content = raw.decode("utf-8-sig")
        except UnicodeDecodeError:
            report(path, "source text is not UTF-8")
            continue
        for number, line in enumerate(content.splitlines(), 1):
            if CONFLICT.match(line):
                report(path, "unresolved merge conflict marker", number)
            if PERSONAL_PATH.search(line):
                report(path, "personal absolute path; use a relative path or environment variable", number)
            if any(pattern.search(line.strip()) for pattern in SECRET_PATTERNS):
                report(path, "possible credential material; inspect locally (value withheld)", number)
        try:
            if path.suffix == ".py":
                ast.parse(content, filename=relative)
            elif path.suffix == ".json":
                json.loads(content, object_pairs_hook=unique_object, parse_constant=invalid_constant)
            elif path.suffix == ".toml":
                tomllib.loads(content)
        except (SyntaxError, ValueError) as error:
            # Parser details can contain source values; report only location/type.
            report(path, f"invalid {path.suffix[1:].upper()} syntax ({type(error).__name__})",
                   getattr(error, "lineno", None))
        if path.suffix.lower() == ".md":
            for number, target in markdown_links(content):
                parsed = urlsplit(target)
                if parsed.scheme or parsed.netloc or not parsed.path:
                    continue
                link_base = root / MARKDOWN_OUTPUT_DIRS[relative] if relative in MARKDOWN_OUTPUT_DIRS else path.parent
                destination = (link_base / unquote(parsed.path)).resolve()
                if not destination.is_relative_to(root):
                    report(path, "relative Markdown link escapes the repository", number)
                elif not destination.exists():
                    report(path, f"relative Markdown target does not exist: {parsed.path}", number)
    return count, issues


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    root = args.root.resolve()
    if not (root / "CMakeLists.txt").is_file():
        parser.error("--root must be the T-RECAP repository root")
    count, issues = check(root)
    for issue in issues:
        print(issue, file=sys.stderr)
    print(f"Source hygiene: {count} files inspected; {len(issues)} findings. No functional tests run.")
    return 1 if issues else 0


if __name__ == "__main__":
    raise SystemExit(main())
