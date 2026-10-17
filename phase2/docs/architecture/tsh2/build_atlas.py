#!/usr/bin/env python3
"""Render source-bound current TSH2 diagrams. No model, simulator or board is run."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import struct
import sys
import xml.etree.ElementTree as ET


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def json_write(path: Path, value):
    path.write_text(json.dumps(value, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")


def source_bindings(spec, repo_root):
    bindings = []
    for item in spec["sources"]:
        relative = Path(item["path"])
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError(f"Unsafe source reference: {relative}")
        file = repo_root / relative
        actual = sha(file)
        if actual != item["sha256"]:
            raise ValueError(f"Source changed since review: {relative}")
        bindings.append({"id": item["id"], "path": relative.as_posix(), "sha256": actual})
    return bindings


def archive_bindings(spec, repo_root):
    for item in spec.get("archived_source_bindings", []):
        proof = Path(item["public_binding"])
        if proof.is_absolute() or ".." in proof.parts:
            raise ValueError("Unsafe archived-source proof path")
        entries = read_json(repo_root / proof)["data"]["files"]
        found = [entry for entry in entries if entry["path"] == item["manifest_entry"]]
        if len(found) != 1 or found[0]["sha256"] != item["original_sha256"]:
            raise ValueError(f"Archived source is not bound by the public fitted manifest: {item['id']}")
    return spec.get("archived_source_bindings", [])


def plate_summary(spec):
    return [{"number": p["number"], "title": p["title"], "slug": p["slug"], "source_ids": p["source_ids"]} for p in spec["plates"]]


def check(output, spec, repo_root):
    manifest = read_json(output / "atlas_manifest.json")
    if sha(Path(__file__)) != manifest["generator"]["sha256"] or manifest["generator"]["file"] != "build_atlas.py":
        raise ValueError("Generator hash or filename changed")
    if sha(Path(__file__).with_name("atlas_definitions.json")) != manifest["definitions"]["sha256"] or manifest["definitions"]["file"] != "atlas_definitions.json":
        raise ValueError("Atlas definitions hash or filename changed")
    if len(spec["plates"]) != 8 or [p["number"] for p in spec["plates"]] != list(range(1, 9)) or manifest["plates"] != plate_summary(spec):
        raise ValueError("Plate order or reviewed source mapping changed")
    expected_sources = source_bindings(spec, repo_root)
    if expected_sources != manifest["sources"]:
        raise ValueError("Manifest source bindings do not match the reviewed definition")
    if archive_bindings(spec, repo_root) != manifest["archived_source_bindings"]:
        raise ValueError("Archived-source proof mapping changed")
    expected = {p["slug"] + extension: p["number"] for p in spec["plates"] for extension in (".png", ".svg")}
    names = [item["file"] for item in manifest["artifacts"]]
    if len(names) != 16 or len(set(names)) != 16 or set(names) != set(expected):
        raise ValueError("Exactly one PNG and one SVG are required for each of the eight plates")
    for item in manifest["artifacts"]:
        if Path(item["file"]).name != item["file"] or item["repo_path"] != "docs/architecture/tsh2/" + item["file"] or item["plate"] != expected[item["file"]]:
            raise ValueError("Unsafe artifact path or changed plate association")
        file = output / item["file"]
        if sha(file) != item["sha256"] or file.stat().st_size != item["bytes"]:
            raise ValueError(f"Artifact changed: {item['file']}")
        if file.suffix == ".svg":
            if ET.parse(file).getroot().tag != "{http://www.w3.org/2000/svg}svg":
                raise ValueError("Artifact is not SVG XML")
            if any(line != line.rstrip() for line in file.read_text(encoding="utf-8").splitlines()):
                raise ValueError("SVG trailing whitespace is forbidden")
        else:
            header = file.read_bytes()[:24]
            if header[:8] != b"\x89PNG\r\n\x1a\n" or header[12:16] != b"IHDR" or struct.unpack(">II", header[16:24]) != (2700, 1800):
                raise ValueError("PNG header or dimensions are invalid")
    print(json.dumps({"status": "PASS", "source_files": len(expected_sources), "plates": len(spec["plates"]),
                      "checked_artifacts": len(manifest["artifacts"]), "scope": "Hash and source-binding check only"}))


def render(spec, repo_root, output):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import FancyBboxPatch, FancyArrowPatch, Rectangle
    from matplotlib.font_manager import FontProperties
    from PIL import Image

    plt.rcParams.update({"font.family": "DejaVu Sans", "svg.fonttype": "none", "svg.hashsalt": "tsh2-atlas-v1",
                         "axes.unicode_minus": False, "savefig.facecolor": "#FCFCFE"})
    palette = {
        "ink": "#26364B", "muted": "#586A80", "line": "#708299", "background": "#FCFCFE", "border": "#D8E0EA",
        "mint": "#DDF2E9", "mint_d": "#407D6C", "blue": "#DFECFA", "blue_d": "#4D78A8",
        "lav": "#EBE4FA", "lav_d": "#8066A9", "rose": "#F8E0E8", "rose_d": "#A66882",
        "sand": "#F7ECD5", "sand_d": "#9C7D3F", "gray": "#EBEFF4", "gray_d": "#65778A"
    }
    bindings = source_bindings(spec, repo_root)
    W, H = 1800, 1200
    artifacts, audits, failures = [], [], []
    for plate in spec["plates"]:
        fig = plt.figure(figsize=(18, 12), dpi=120)
        ax = fig.add_axes([0, 0, 1, 1], xlim=(0, W), ylim=(H, 0))
        ax.set_axis_off()
        fig.patch.set_facecolor(palette["background"])
        ax.add_patch(Rectangle((0, 0), W, H, color=palette["background"], zorder=-10))
        fig.canvas.draw()
        renderer = fig.canvas.get_renderer()
        registered = []
        problems = []

        def width(text, size, bold=False, mono=False):
            prop = FontProperties(family="DejaVu Sans Mono" if mono else "DejaVu Sans", size=size, weight="bold" if bold else "normal")
            pixels = renderer.get_text_width_height_descent(text, prop, False)[0]
            return pixels / (fig.dpi / 100)

        def wrap(text, available, size, bold=False, mono=False):
            lines = []
            for paragraph in str(text).split("\n"):
                line = ""
                for word in paragraph.split():
                    candidate = f"{line} {word}".strip()
                    if line and width(candidate, size, bold, mono) > available:
                        lines.append(line)
                        line = word
                    else:
                        line = candidate
                lines.append(line)
            return lines

        def text(x, y, value, size=17, color="ink", bold=False, mono=False, align="left", owner=None, zorder=6):
            if any(character in value for character in "\u2013\u2014"):
                problems.append(f"Forbidden dash in text: {value}")
            artist = ax.text(x, y, value, va="top", ha=align, fontsize=size,
                             color=palette.get(color, color), weight="bold" if bold else "normal",
                             family="DejaVu Sans Mono" if mono else "DejaVu Sans", zorder=zorder,
                             linespacing=1.32)
            registered.append((artist, owner, value))
            return artist

        def box(x, y, w, h, fill, border=None, radius=14, zorder=2):
            patch = FancyBboxPatch((x, y), w, h, boxstyle=f"round,pad=0,rounding_size={radius}",
                                  facecolor=palette.get(fill, fill), edgecolor=palette.get(border, border) if border else "none",
                                  linewidth=1.2, zorder=zorder)
            ax.add_patch(patch)

        # Fixed outer geometry leaves each plate's technical layout fully editable in JSON.
        ax.add_patch(Rectangle((65, 53), 7, 105, color=palette["lav_d"]))
        text(95, 53, "T-RECAP  /  CURRENT TSH2 ARCHITECTURE", 14, "muted", True)
        text(95, 90, plate["title"], 29, "ink", True)
        for n, line in enumerate(wrap(plate["subtitle"], 1510, 16.5)):
            text(95, 140 + 26 * n, line, 16.5, "muted")
        text(1730, 66, f"{plate['number']:02d}", 32, "lav_d", True, align="right")
        ax.plot([65, 1735], [200, 200], color=palette["border"], linewidth=1)

        for panel in plate.get("panels", []):
            x, y, w, h = panel["rect"]
            tone = panel.get("tone", "gray")
            box(x, y, w, h, "#FFFFFF", "border", 18, 0)
            box(x + 1, y + 1, w - 2, 47, tone, None, 17, 0.2)
            ax.add_patch(Rectangle((x + 1, y + 28), w - 2, 20, color=palette[tone], zorder=.3))
            text(x + 18, y + 13, panel["title"], 15.5, tone + "_d", True, owner=(x + 12, y + 5, w - 24, 40))

        nodes = {node["id"]: node for node in plate["nodes"]}
        if len(nodes) != len(plate["nodes"]):
            raise ValueError(f"Duplicate nodes on plate {plate['number']}")

        def point(node_id, side, offset=0):
            x, y, w, h = nodes[node_id]["rect"]
            return {"left": [x, y + h / 2 + offset], "right": [x + w, y + h / 2 + offset],
                    "top": [x + w / 2 + offset, y], "bottom": [x + w / 2 + offset, y + h]}[side]

        routes = []
        for edge in plate.get("edges", []):
            pts = [point(edge["from"], edge.get("fromPort", "right"), edge.get("fromOffset", 0)), *edge.get("via", []), point(edge["to"], edge.get("toPort", "left"), edge.get("toOffset", 0))]
            kind = edge.get("kind", "data")
            color = palette[{"data": "line", "control": "lav_d", "tap": "rose_d", "clock": "blue_d"}[kind]]
            style = "-" if kind in ("data", "clock") else (0, (6, 4)) if kind == "control" else (0, (2, 3))
            ax.plot([p[0] for p in pts[:-1]], [p[1] for p in pts[:-1]], color=color, linewidth=2.0, linestyle=style, zorder=1)
            ax.add_patch(FancyArrowPatch(pts[-2], pts[-1], arrowstyle="-|>", mutation_scale=15,
                                        linewidth=2.0, linestyle=style, color=color, shrinkA=0, shrinkB=2, zorder=1))
            routes.append((edge, pts))
            if edge.get("label"):
                lx, ly = edge["labelAt"]
                label_lines = wrap(edge["label"], edge.get("labelWidth", 290), 12.5)
                content = "\n".join(label_lines)
                maxw = max(width(line, 12.5) for line in label_lines)
                box(lx - maxw / 2 - 6, ly - 3, maxw + 12, len(label_lines) * 21 + 4, "background", None, 4, 4)
                text(lx, ly, content, 12.5, color, align="center", zorder=5)

        for node in plate["nodes"]:
            x, y, w, h = node["rect"]
            tone = node.get("tone", "blue")
            box(x + 2, y + 4, w, h, "#EFF1F6", None, 14, 2)
            box(x, y, w, h, tone, tone + "_d", 14, 3)
            inside = (x + 16, y + 12, w - 32, h - 24)
            title_size = node.get("titleSize", 18)
            title_lines = wrap(node["title"], w - 38, title_size, True)
            cy = y + 17
            text(x + 19, cy, "\n".join(title_lines), title_size, "ink", True, owner=inside)
            cy += len(title_lines) * title_size * 1.83 + 8
            body_size = node.get("bodySize", 15.4)
            body_lines = []
            for paragraph in node.get("body", []):
                body_lines += wrap(paragraph, w - 38, body_size)
            if body_lines:
                text(x + 19, cy, "\n".join(body_lines), body_size, "ink", owner=inside)
                cy += len(body_lines) * body_size * 1.83 + 8
            if node.get("code"):
                code_lines = wrap(node["code"], w - 38, node.get("codeSize", 10.6), mono=True)
                code_y = y + h - 16 - 19 * len(code_lines)
                if cy - 8 > code_y:
                    problems.append(f"Node text/code overlap: {node['id']}")
                text(x + 19, code_y, "\n".join(code_lines), node.get("codeSize", 10.6), tone + "_d", mono=True, owner=inside)

        for note in plate.get("notes", []):
            x, y, w, h = note["rect"]
            tone = note.get("tone", "gray")
            box(x, y, w, h, tone, None, 12, 2)
            text(x + 19, y + 14, note["title"], note.get("titleSize", 15.5), tone + "_d", True, owner=(x + 12, y + 8, w - 24, h - 16))
            note_lines = wrap(note["body"], w - 38, note.get("bodySize", 14.1))
            text(x + 19, y + 41, "\n".join(note_lines), note.get("bodySize", 14.1), "ink", owner=(x + 12, y + 8, w - 24, h - 16))

        ax.plot([65, 1735], [1110, 1110], color=palette["border"], linewidth=1)
        for x, label, tone in [(70, "PCM / sources", "mint"), (340, "DSP / control", "lav"), (615, "Spectral output", "rose"),
                               (915, "Host / HPS", "sand"), (1200, "Memory / platform", "blue")]:
            box(x, 1127, 17, 17, tone, tone + "_d", 4)
            text(x + 25, 1126, label, 12.5, "muted")
        text(1730, 1127, "solid: data   dashed: control", 12, "muted", align="right")
        source_ids = ", ".join(plate["source_ids"])
        text(70, 1160, f"SOURCE BINDINGS: {source_ids}  |  Reviewed source structure, not new execution or timing measurements.", 11.8, "muted")
        text(1730, 1160, f"TSH2 / {plate['number']:02d}", 11.8, "muted", align="right")
        fig.canvas.draw()
        for artist, owner, value in registered:
            bounds = artist.get_window_extent(fig.canvas.get_renderer()).transformed(ax.transData.inverted())
            xx0, yy0, xx1, yy1 = min(bounds.x0, bounds.x1), min(bounds.y0, bounds.y1), max(bounds.x0, bounds.x1), max(bounds.y0, bounds.y1)
            if xx0 < 3 or yy0 < 3 or xx1 > W - 3 or yy1 > H - 3:
                problems.append(f"Text outside plate: {value}")
            if owner:
                ox, oy, ow, oh = owner
                if xx0 < ox - 2 or yy0 < oy - 2 or xx1 > ox + ow + 2 or yy1 > oy + oh + 2:
                    problems.append(f"Text outside owner: {value}")
        # Axis-aligned routes may not pass through unrelated nodes. Diagonal segments are visually reviewed.
        for edge, pts in routes:
            for first, last in zip(pts, pts[1:]):
                for node in plate["nodes"]:
                    if node["id"] in (edge["from"], edge["to"]):
                        continue
                    x, y, w, h = node["rect"]
                    if first[0] == last[0] and x + 2 < first[0] < x + w - 2 and max(min(first[1], last[1]), y + 2) < min(max(first[1], last[1]), y + h - 2):
                        problems.append(f"Edge crosses node: {edge['from']}->{edge['to']} through {node['id']}")
                    if first[1] == last[1] and y + 2 < first[1] < y + h - 2 and max(min(first[0], last[0]), x + 2) < min(max(first[0], last[0]), x + w - 2):
                        problems.append(f"Edge crosses node: {edge['from']}->{edge['to']} through {node['id']}")
        if problems:
            failures.append({"plate": plate["number"], "problems": problems})
            fig.savefig(output / (plate["slug"] + ".layout-preview.png"), dpi=100)
            plt.close(fig)
            continue
        png, svg = output / (plate["slug"] + ".png"), output / (plate["slug"] + ".svg")
        fig.savefig(png, dpi=150, metadata={"Software": "T-RECAP current TSH2 architecture atlas"})
        fig.savefig(svg, metadata={"Date": None, "Creator": "T-RECAP current TSH2 architecture atlas", "Title": plate["title"]})
        # Keep generated vector files clean in repositories that reject trailing whitespace.
        vector = "\n".join(line.rstrip() for line in svg.read_text(encoding="utf-8").splitlines()) + "\n"
        svg.write_text(vector, encoding="utf-8")
        plt.close(fig)
        with Image.open(png) as image:
            image.verify()
        for file in (png, svg):
            artifacts.append({"file": file.name, "repo_path": "docs/architecture/tsh2/" + file.name,
                              "sha256": sha(file), "bytes": file.stat().st_size, "plate": plate["number"]})
        audits.append({"plate": plate["number"], "status": "PASS", "nodes": len(nodes), "edges": len(routes),
                       "text_items": len(registered), "text_containment": "PASS", "orthogonal_route_node_intersections": 0,
                       "png_pixels": [2700, 1800], "visual_review": "Pending separate human/agent inspection"})
    if failures:
        json_write(output / "layout_errors.json", failures)
        raise ValueError("Layout validation failed:\n" + json.dumps(failures, indent=2))
    manifest = {"schema": "trecap-current-tsh2-atlas-v1", "profile": "TSH2", "scope": "Source-derived architecture documentation; no new hardware or simulation execution",
                "generator": {"file": "build_atlas.py", "sha256": sha(Path(__file__)), "matplotlib": matplotlib.__version__},
                "definitions": {"file": "atlas_definitions.json", "sha256": sha(Path(__file__).with_name("atlas_definitions.json"))},
                "sources": bindings, "archived_source_bindings": archive_bindings(spec, repo_root), "plates": plate_summary(spec),
                "artifacts": artifacts, "layout_audit": audits}
    json_write(output / "atlas_manifest.json", manifest)
    print(json.dumps({"status": "PASS", "plates": len(audits), "artifacts": len(artifacts), "sources": len(bindings)}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, required=True, help="The phase2 source root, containing profiles/ and verification/")
    parser.add_argument("--output", type=Path, required=True, help="New artifact directory for generation, or existing directory for --check")
    parser.add_argument("--check", action="store_true", help="Verify admitted source and generated artifact hashes without plotting dependencies")
    parser.add_argument("--python-packages", type=Path, help="Optional existing package directory; otherwise use the current Python environment")
    args = parser.parse_args()
    spec = read_json(Path(__file__).with_name("atlas_definitions.json"))
    if args.check:
        check(args.output, spec, args.repo_root)
        return
    if args.python_packages:
        sys.path.insert(0, str(args.python_packages))
    if args.output.exists() and any(args.output.iterdir()):
        raise ValueError("Output directory must be new or empty; existing atlas artifacts are not overwritten")
    args.output.mkdir(parents=True, exist_ok=True)
    render(spec, args.repo_root, args.output)


if __name__ == "__main__":
    main()
