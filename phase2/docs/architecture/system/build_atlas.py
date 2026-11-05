#!/usr/bin/env python3
"""Render source-bound unified system diagrams. No model, simulator or board is run."""
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
    expected = {p["slug"] + extension: p["number"] for p in spec["plates"] for extension in (".png", ".svg", ".pdf")}
    names = [item["file"] for item in manifest["artifacts"]]
    if len(names) != 24 or len(set(names)) != 24 or set(names) != set(expected):
        raise ValueError("Exactly one PNG, SVG and PDF are required for each of the eight plates")
    for item in manifest["artifacts"]:
        if Path(item["file"]).name != item["file"] or item["repo_path"] != "docs/architecture/system/" + item["file"] or item["plate"] != expected[item["file"]]:
            raise ValueError("Unsafe artifact path or changed plate association")
        file = output / item["file"]
        if sha(file) != item["sha256"] or file.stat().st_size != item["bytes"]:
            raise ValueError(f"Artifact changed: {item['file']}")
        if file.suffix == ".svg":
            if ET.parse(file).getroot().tag != "{http://www.w3.org/2000/svg}svg":
                raise ValueError("Artifact is not SVG XML")
            if any(line != line.rstrip() for line in file.read_text(encoding="utf-8").splitlines()):
                raise ValueError("SVG trailing whitespace is forbidden")
        elif file.suffix == ".pdf":
            if not file.read_bytes().startswith(b"%PDF-"):
                raise ValueError("Invalid diagram PDF")
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

    plt.rcParams.update({"font.family": "STIXGeneral", "svg.fonttype": "none", "svg.hashsalt": "system-atlas-v1",
                         "axes.unicode_minus": False, "savefig.facecolor": "#FFFEFB"})
    palette = {
        "ink": "#263540", "muted": "#586A80", "line": "#708299", "background": "#FFFEFB", "border": "#D8E0EA",
        "mint": "#E8F1E5", "mint_d": "#407D6C", "blue": "#E4EEF7", "blue_d": "#4D78A8",
        "lav": "#EEE8F3", "lav_d": "#8066A9", "rose": "#F7E4DE", "rose_d": "#A66882",
        "sand": "#F6EDD9", "sand_d": "#9C7D3F", "gray": "#EBEFF4", "gray_d": "#65778A"
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
            prop = FontProperties(family="DejaVu Sans Mono" if mono else "STIXGeneral", size=size, weight="bold" if bold else "normal")
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
            if any(character in value for character in ";\u2013\u2014"):
                problems.append(f"Forbidden dash in text: {value}")
            artist = ax.text(x, y, value, va="top", ha=align, fontsize=size,
                             color=palette.get(color, color), weight="bold" if bold else "normal",
                             family="DejaVu Sans Mono" if mono else "STIXGeneral", zorder=zorder,
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
        text(95, 53, "T-RECAP  /  SYSTEM ARCHITECTURE AFTER RF INTEGRATION", 14, "muted", True)
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
        for x, label, tone in [(70, "Signal input", "mint"), (340, "DSP / control", "lav"), (615, "Signal outputs", "rose"),
                               (915, "Host / HPS", "sand"), (1200, "Storage / platform", "blue")]:
            box(x, 1127, 17, 17, tone, tone + "_d", 4)
            text(x + 25, 1126, label, 12.5, "muted")
        text(1730, 1127, "solid: data   dashed: control", 12, "muted", align="right")
        source_ids = ", ".join(plate["source_ids"])
        text(70, 1160, f"SOURCE BINDINGS: {source_ids}  |  Reviewed source structure, not new execution or timing measurements.", 11.8, "muted")
        text(1730, 1160, f"SYSTEM / {plate['number']:02d}", 11.8, "muted", align="right")
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
        png, svg, pdf = [output / (plate["slug"] + ext) for ext in (".png", ".svg", ".pdf")]
        fig.savefig(png, dpi=150, metadata={"Software": "T-RECAP unified system architecture atlas"})
        fig.savefig(svg, metadata={"Date": None, "Creator": "T-RECAP unified system architecture atlas", "Title": plate["title"]})
        fig.savefig(pdf, metadata={"CreationDate": None, "ModDate": None, "Title": plate["title"]})
        # Keep generated vector files clean in repositories that reject trailing whitespace.
        vector = "\n".join(line.rstrip() for line in svg.read_text(encoding="utf-8").splitlines()) + "\n"
        svg.write_text(vector, encoding="utf-8")
        plt.close(fig)
        with Image.open(png) as image:
            image.verify()
        for file in (png, svg, pdf):
            artifacts.append({"file": file.name, "repo_path": "docs/architecture/system/" + file.name,
                              "sha256": sha(file), "bytes": file.stat().st_size, "plate": plate["number"]})
        audits.append({"plate": plate["number"], "status": "PASS", "nodes": len(nodes), "edges": len(routes),
                       "text_items": len(registered), "text_containment": "PASS", "orthogonal_route_node_intersections": 0,
                       "png_pixels": [2700, 1800], "visual_review": "See visual_review.json for separate inspection"})
    if failures:
        json_write(output / "layout_errors.json", failures)
        raise ValueError("Layout validation failed:\n" + json.dumps(failures, indent=2))
    manifest = {"schema": "trecap-unified-system-atlas-v1", "profile": "PROJECT", "scope": "Source-derived architecture documentation. Rendering runs no hardware or simulation.",
                "generator": {"file": "build_atlas.py", "sha256": sha(Path(__file__)), "matplotlib": matplotlib.__version__},
                "definitions": {"file": "atlas_definitions.json", "sha256": sha(Path(__file__).with_name("atlas_definitions.json"))},
                "sources": bindings, "archived_source_bindings": archive_bindings(spec, repo_root), "plates": plate_summary(spec),
                "artifacts": artifacts, "layout_audit": audits}
    json_write(output / "atlas_manifest.json", manifest)
    print(json.dumps({"status": "PASS", "plates": len(audits), "artifacts": len(artifacts), "sources": len(bindings)}))


def prose_check(text):
    if any(c in text for c in [';', '\u2013', '\u2014']):
        raise ValueError('Forbidden punctuation in authored prose')


def tex_escape(text):
    for old, new in [('\\', r'\textbackslash{}'), ('&', r'\&'), ('%', r'\%'), ('$', r'\$'), ('#', r'\#'), ('_', r'\_')]:
        text = text.replace(old, new)
    return text


def write_documents(spec, output):
    import html
    prose = []
    for p in spec['plates']:
        prose += [p['title'], p['subtitle'], *p['description']]
        for n in p['nodes']:
            prose += [n['title'], *n.get('body', [])]
        for n in p['notes']:
            prose += [n['title'], n['body']]
    for text in prose:
        prose_check(text)
    rows = ['# T-RECAP system architecture atlas', '',
            '**Threshold-based Reduction and Encoding for Controlled Audio Processing**', '',
            'This is the primary whole-project architecture after recorded RF integration. Eight coordinated views connect audio and accelerometer replay, the new I/Q hardware adapter, the shared numerical core, HPS transport and laptop consumers.', '',
            '[Open the offline gallery](index.html) | [Read the academic LaTeX atlas](TRECAP_System_Architecture_Atlas.pdf)', '',
            'TSH2 and TRF1 are alternative fitted applications. Their shared core is one implementation reused by both profiles. The diagrams do not imply a runtime input selector or simultaneous processing of all signal types.', '',
            'The colors identify responsibilities consistently. Sage denotes signal input, blue denotes storage or platform interfaces, lilac denotes DSP, peach denotes returned signal representations, and warm cream denotes host software or transaction control.', '',
            '## Eight views', '', '| View | What it explains |', '|---|---|']
    for p in spec['plates']:
        rows.append(f"| [{p['number']}. {p['title']}]({p['slug']}.png) | {p['subtitle']} |")
    for p in spec['plates']:
        rows += ['', '## '+str(p['number'])+'. '+p['title'], '', '!['+p['title']+']('+p['slug']+'.png)', '']
        rows += [item+'\n' for item in p['description']]
        rows += ['| Block | Responsibility |', '|---|---|']
        for n in p['nodes']:
            rows.append('| '+n['title']+' | '+'. '.join(n['body'])+'. |')
        rows += ['', '**Interpretation:** '+p['notes'][0]['body'], '',
                 'Source bindings: '+', '.join(p['source_ids'])+'.', '',
                 '[Editable SVG]('+p['slug']+'.svg) | [Vector PDF]('+p['slug']+'.pdf)']
    rows += ['', '## Source review and reproduction', '',
             'The source bindings below hash the public files used to review these views. The generator checks these identities and the artifact inventory. It does not execute RTL, access a board or rerun a hardware benchmark.', '',
             '| ID | Published source |', '|---|---|']
    for s in spec['sources']:
        rows.append('| '+s['id']+' | ['+s['path']+'](../../../'+s['path']+') |')
    rows += ['', 'The accelerometer acquisition and axis-replay workflow was reviewed from local scripts. Their relative workspace identifiers and digests are preserved in `atlas_definitions.json`. These files are not bundled here, so the public checker does not claim to re-execute or revalidate that local acquisition workflow.', '',
             'From the repository root:', '', '```sh', 'python phase2/docs/architecture/system/build_atlas.py --check', '```', '',
             'To regenerate, install Matplotlib and Pillow, run the same script without `--check`, and compile `TRECAP_System_Architecture_Atlas.tex` twice with `pdflatex` from this directory. Review the rendered figures and pages, update `visual_review.json`, then run the generator with `--seal`. Rendering does not change source RTL or verification evidence.', '',
             'The [audio atlas](../tsh2/README.md) and [RF specialist atlas](../rf_iq/README.md) retain their original detailed scopes. The [RF verification supplement](../../verification/rf_iq/README.md) contains the executed results behind the RF evidence summary.', '']
    readme='\n'.join(rows)
    prose_check(readme)
    (output/'README.md').write_text(readme, encoding='utf-8')

    cards=[]
    for p in spec['plates']:
        paragraphs=''.join('<p>'+html.escape(x)+'</p>' for x in p['description'])
        blocks=''.join('<tr><th>'+html.escape(n['title'])+'</th><td>'+html.escape('. '.join(n['body'])+'.')+'</td></tr>' for n in p['nodes'])
        cards.append(f'<section id="view{p["number"]}"><h2>{p["number"]}. {html.escape(p["title"])}</h2><p class="lead">{html.escape(p["subtitle"])}</p><a class="figure" href="{p["slug"]}.svg" target="_blank"><img src="{p["slug"]}.png" alt="{html.escape(p["title"])}"></a><div class="description">{paragraphs}<details><summary>Block responsibilities and source bindings</summary><table>{blocks}</table><p>Source bindings: {html.escape(", ".join(p["source_ids"]))}.</p></details><p class="note">{html.escape(p["notes"][0]["body"])}</p></div></section>')
    nav=''.join(f'<a href="#view{p["number"]}">{p["number"]}. {html.escape(p["title"])}</a>' for p in spec['plates'])
    doc='''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>T-RECAP System Architecture Atlas</title><style>
    :root{color-scheme:light}*{box-sizing:border-box}body{margin:0;background:#fffcf6;color:#263540;font-family:Georgia,"Times New Roman",serif;line-height:1.65}header,main{max-width:1280px;margin:auto;padding:28px}header{padding-top:50px}h1{font-size:clamp(30px,4vw,52px);line-height:1.12;margin:10px 0}h2{font-size:29px;line-height:1.2}.eyebrow{letter-spacing:.12em;color:#65798d;font-family:Arial,sans-serif;font-size:12px;text-transform:uppercase}.intro{font-size:19px;max-width:900px}nav{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px}nav a{display:block;background:#e4eef7;padding:10px 14px;border-radius:8px;font-size:15px}a{color:#315f80;text-underline-offset:3px}section{margin:25px 0 55px;padding:26px;background:white;border:1px solid #dce1e5;border-radius:15px;scroll-margin-top:20px}.lead{color:#5d6975}.figure{display:block;background:#fffefa;border:1px solid #e3e5e6;border-radius:9px;overflow:auto}.figure img{width:100%;height:auto;display:block}.description{max-width:980px;margin:25px auto 0;font-size:18px}.note{background:#f6edd9;padding:16px 19px;border-left:4px solid #b49b65}details{background:#f4f1f7;padding:15px 20px;border-radius:8px}summary{cursor:pointer;font-weight:bold}table{border-collapse:collapse;width:100%;font-size:15px;margin-top:16px}th,td{padding:9px 8px;text-align:left;vertical-align:top;border-bottom:1px solid #d7d3df}th{width:32%}footer{max-width:1280px;margin:auto;padding:28px;color:#617282}.links a{display:inline-block;margin-right:20px}@media(max-width:700px){header,main{padding:18px}nav{grid-template-columns:1fr}section{padding:15px}.description{font-size:16px}h2{font-size:25px}}
    </style></head><body><header><div class="eyebrow">Senior design project / source-derived architecture</div><h1>T-RECAP System Architecture Atlas</h1><p class="intro">Eight coordinated views of the complete project after RF integration, from recorded signal inputs through HPS and FPGA processing to laptop results.</p><p>Audio TSH2 and RF TRF1 are separate fitted applications that reuse the same numerical core. Accelerometer data follows a local capture-and-replay workflow into the real-sample path.</p><p class="links"><a href="TRECAP_System_Architecture_Atlas.pdf">Academic LaTeX atlas</a><a href="README.md">Full written guide</a></p><nav>'''+nav+'</nav></header><main>'+''.join(cards)+'</main><footer>Click a diagram to open its scalable SVG. These views describe source structure and evidence boundaries. They do not represent a new hardware run.</footer></body></html>\n'
    (output/'index.html').write_text(doc, encoding='utf-8')

    tex=[r'\documentclass[11pt,letterpaper]{article}',r'\usepackage[margin=0.65in,headheight=15pt]{geometry}',
         r'\usepackage[T1]{fontenc}',r'\usepackage{mathptmx,graphicx,booktabs,tabularx,array,xcolor,caption,fancyhdr,float}',
         r'\usepackage[hyphens]{url}',r'\usepackage[colorlinks=true,urlcolor=blue,linkcolor=blue]{hyperref}',
         r'\hypersetup{pdftitle={T-RECAP System Architecture Atlas},pdfauthor={T-RECAP Senior Design Project}}',
         r'\pagestyle{fancy}\fancyhf{}\lhead{\small T-RECAP System Architecture}\rhead{\small After RF integration}\cfoot{\thepage}',
         r'\setlength{\parindent}{1em}\setlength{\parskip}{4pt}\setlength{\emergencystretch}{2em}',
         r'\captionsetup{font=small,labelfont=bf}',r'\newcolumntype{Y}{>{\raggedright\arraybackslash}X}',r'\begin{document}',
         r'\begin{center}{\LARGE\bfseries T-RECAP System Architecture Atlas}\par\vspace{6pt}',
         r'{\large Complete project after recorded RF integration}\par\vspace{6pt}',
         r'{\small Threshold-based Reduction and Encoding for Controlled Audio Processing}\par\vspace{4pt}',
         r'{\small Senior design project}\end{center}',
         'This atlas explains the complete project through eight coordinated views. The RF extension is placed in the same system context as audio processing, accelerometer replay, HPS transport and laptop analysis. The source-derived diagrams use a consistent academic pastel palette.',
         'TSH2 and TRF1 are separate fitted FPGA applications. They reuse the same numerical core without an implemented runtime audio/RF selector. The accelerometer acquisition and axis-preparation scripts describe a local capture-and-replay workflow rather than a new live FPGA sensor frontend.',
         r'\section*{Reading the atlas}',r'\begin{tabularx}{\linewidth}{@{}p{0.35in}X@{}}\toprule']
    for p in spec['plates']:
        tex += [str(p['number'])+' & '+tex_escape(p['title'])+r' \\']
    tex += [r'\bottomrule\end{tabularx}',r'\par\vspace{10pt}',
            'Sage marks signal inputs, blue marks storage and platform interfaces, lilac marks DSP, peach marks returned signal representations, and warm cream marks host software or transaction control. Solid arrows represent data. Dashed arrows represent control. Dotted arrows identify observation taps.',
            r'\section*{Evidence boundary}',
            'The views are architecture documentation. Source bindings identify the public implementation used for review. Historical board measurements, fresh RTL simulations and scoped formal/UVM results retain their own boundaries. Rendering this atlas does not rerun synthesis or verification.',
            'Each view has a full diagram, a system-level explanation and a table describing its blocks. The companion SVG files remain scalable for zooming during a demonstration.',r'\clearpage']
    for p in spec['plates']:
        tex += [r'\section{'+tex_escape(p['title'])+'}',tex_escape(p['subtitle'])+r'\par',
                r'\begin{figure}[H]\centering\includegraphics[width=\linewidth]{'+p['slug']+r'.pdf}\caption{'+tex_escape(p['notes'][0]['body'])+r'}\end{figure}\par']
        tex += [tex_escape(x)+'\n' for x in p['description'][:2]]
        tex += [r'\noindent\textbf{Source bindings:} '+tex_escape(', '.join(p['source_ids']))+'.',r'\clearpage',
                r'\subsection*{Block responsibilities}',
                tex_escape(p['description'][2]),r'\par\medskip\noindent',
                r'\begin{tabularx}{\linewidth}{@{}>{\raggedright\arraybackslash}p{1.65in}Y@{}}\toprule',r'\textbf{Block} & \textbf{Responsibility} \\ \midrule']
        for n in p['nodes']:
            tex.append(tex_escape(n['title'])+' & '+tex_escape('. '.join(n['body'])+'.')+r' \\[5pt]')
        tex += [r'\bottomrule\end{tabularx}',r'\vspace{8pt}',r'\noindent\textbf{Interpretation.} '+tex_escape(p['notes'][0]['body']),r'\clearpage']
    tex += [r'\section*{Reproduction and source review}',
            'The companion atlas definitions contain the exact source hashes, block text, routing coordinates and local workflow review identities. The generator creates the PNG, SVG and vector PDF diagrams together with the written guide and offline gallery.',
            r'\begin{verbatim}',r'python phase2/docs/architecture/system/build_atlas.py --check',r'\end{verbatim}',
            'This check uses only the Python standard library. It validates public source bindings and artifact hashes. Local accelerometer source identities are recorded for provenance but their files are not bundled. The checker does not claim to rerun that acquisition workflow.',
            r'\par\medskip\noindent\begin{tabularx}{\linewidth}{@{}p{0.4in}Y@{}}\toprule',r'\textbf{ID} & \textbf{Published source path} \\ \midrule']
    for s in spec['sources']:
        tex += [s['id']+r' & \path{'+s['path']+r'} \\[4pt]']
    tex += [r'\bottomrule\end{tabularx}',r'\end{document}','']
    textext='\n'.join(tex)
    prose_check(textext)
    (output/'TRECAP_System_Architecture_Atlas.tex').write_text(textext,encoding='utf-8')


def document_inventory(output):
    names=['README.md','index.html','TRECAP_System_Architecture_Atlas.tex','TRECAP_System_Architecture_Atlas.pdf','visual_review.json']
    return {name:sha(output/name) for name in names}


def seal_documents(output):
    data=read_json(output/'atlas_manifest.json')
    data['documents']=document_inventory(output)
    json_write(output/'atlas_manifest.json',data)


def check_documents(output):
    data=read_json(output/'atlas_manifest.json')
    if data.get('documents') != document_inventory(output):
        raise ValueError('Written atlas or reviewed PDF changed')
    for name in ['README.md','TRECAP_System_Architecture_Atlas.tex']:
        prose_check((output/name).read_text(encoding='utf-8'))
    review=read_json(output/'visual_review.json')
    if review['status']!='PASS' or len(review['plates'])!=8:
        raise ValueError('Eight reviewed diagrams are required')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[3], help="The phase2 source root")
    parser.add_argument("--output", type=Path, default=Path(__file__).resolve().parent, help="The atlas artifact directory")
    parser.add_argument("--seal", action="store_true", help="Seal the reviewed PDF and written documentation after compilation")
    parser.add_argument("--check", action="store_true", help="Verify admitted source and generated artifact hashes without plotting dependencies")
    parser.add_argument("--python-packages", type=Path, help="Optional existing package directory. Otherwise use the current Python environment")
    args = parser.parse_args()
    spec = read_json(Path(__file__).with_name("atlas_definitions.json"))
    if args.seal:
        seal_documents(args.output)
        check(args.output, spec, args.repo_root)
        return
    if args.check:
        check_documents(args.output)
        check(args.output, spec, args.repo_root)
        return
    if args.python_packages:
        sys.path.insert(0, str(args.python_packages))
    if args.output.resolve() != Path(__file__).resolve().parent:
        raise ValueError("Author this atlas only beside its reviewed generator and definitions")
    args.output.mkdir(parents=True, exist_ok=True)
    render(spec, args.repo_root, args.output)
    write_documents(spec, args.output)


if __name__ == "__main__":
    main()
