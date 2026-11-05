"""Restyle published vector figures without recomputing any measured data.

Requires pypdf. Supply an unmodified baseline figure directory as --source.
The output audit checks every non-presentation PDF operator and operand.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import copy
from io import BytesIO
from pathlib import Path

from pypdf import PdfReader, PdfWriter
from pypdf.generic import ArrayObject, ByteStringObject, ContentStream, FloatObject, NameObject, NumberObject

PALETTE = {
    "sage_fill": "DCEBDD", "blue_fill": "DBE9F4", "lilac_fill": "E7DFF0",
    "peach_fill": "F5E2D3", "sage_stroke": "63917A", "blue_stroke": "718FAE",
    "lilac_stroke": "9C85B4", "peach_stroke": "C48F70", "ink": "273445",
    "grid": "E3E7EB", "neutral": "ACB6C5",
}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def rgb(name):
    value = PALETTE[name]
    return [FloatObject(int(value[i:i + 2], 16) / 255) for i in (0, 2, 4)]


def signature(operations):
    # Geometry, clipping, axes, transforms and line styles must remain identical.
    omit = {b"rg", b"RG", b"g", b"G", b"k", b"K", b"TJ", b"Tj"}
    items = [(op.decode(), repr(args)) for args, op in operations if op not in omit]
    return hashlib.sha256(json.dumps(items).encode()).hexdigest()


def cid_width(font, cid):
    descendant = font["/DescendantFonts"][0].get_object()
    widths = descendant["/W"] if "/W" in descendant else []
    i = 0
    while i < len(widths):
        start = int(widths[i])
        i += 1
        if isinstance(widths[i], list):
            values = widths[i]
            if start <= cid < start + len(values):
                return float(values[cid - start])
            i += 1
        else:
            end, value = int(widths[i]), float(widths[i + 1])
            if start <= cid <= end:
                return value
            i += 2
    return float(descendant.get("/DW", 1000))


def ensure_comma(font):
    """Add a missing subset comma using the semicolon's existing lower contour.

    The original DejaVu semicolon consists of a dot and a comma. The new glyph
    copies only the comma contour. Every original glyph remains unchanged.
    """
    descendant = font["/DescendantFonts"][0].get_object()
    cid_map = descendant["/CIDToGIDMap"]
    mapping = bytearray(cid_map.get_data())
    if mapping[88:90] != b"\0\0":
        return
    from fontTools.ttLib import TTFont
    from fontTools.ttLib.tables._g_l_y_f import GlyphCoordinates
    from fontTools.ttLib.tables.ttProgram import Program
    font_file = descendant["/FontDescriptor"]["/FontFile2"]
    tt = TTFont(BytesIO(font_file.get_data()))
    name = tt.getGlyphName(int.from_bytes(mapping[118:120], "big"))
    original = tt["glyf"][name]
    assert original.numberOfContours == 2
    split = original.endPtsOfContours[0] + 1
    assert min(y for x, y in original.coordinates[:split]) > max(y for x, y in original.coordinates[split:])
    comma = copy.deepcopy(original)
    comma.coordinates = GlyphCoordinates(original.coordinates[split:])
    comma.flags = original.flags[split:]
    comma.endPtsOfContours = [len(comma.coordinates) - 1]
    comma.numberOfContours = 1
    comma.program = Program()
    comma.program.fromBytecode([])
    new_name = "editorialComma"
    tt["glyf"][new_name] = comma
    order = tt.getGlyphOrder()
    if new_name not in order:
        order.append(new_name)
        tt.setGlyphOrder(order)
    tt["hmtx"].metrics[new_name] = tt["hmtx"].metrics[name]
    mapping[88:90] = tt.getGlyphID(new_name).to_bytes(2, "big")
    saved = BytesIO()
    tt.save(saved)
    font_file.set_data(saved.getvalue())
    font_file[NameObject("/Length1")] = NumberObject(len(saved.getvalue()))
    cid_map.set_data(bytes(mapping))
    descendant["/W"].extend([NumberObject(44), ArrayObject([FloatObject(cid_width(font, 59))])])
    unicode_map = font["/ToUnicode"]
    unicode_map.set_data(unicode_map.get_data().replace(b"endcmap", b"1 beginbfchar\n<002c> <002c>\nendbfchar\nendcmap"))


def recolor(args, op, family, counters):
    values = tuple(round(float(x), 6) for x in args)
    if family == "uvm_formal":
        if op == b"g" and values == (0.96,):
            # Matplotlib repeats each box fill operator twice.
            index = counters["fill"] // 2
            counters["fill"] += 1
            return rgb(["blue_fill", "lilac_fill", "peach_fill", "sage_fill"][index % 4]), b"rg"
        if op == b"G" and values == (0.15,):
            index = counters["trace"]
            counters["trace"] += 1
            return rgb(["blue_stroke", "sage_stroke", "lilac_stroke", "peach_stroke"][index % 4]), b"RG"
        if op in (b"G", b"g") and values == (0.2,):
            return rgb("ink"), b"RG" if op == b"G" else b"rg"
        return args, op
    if op in (b"rg", b"RG"):
        r, g, b = values
        # Preserve dark text and white backgrounds. Map established plot roles.
        if max(values) < 0.55 and r < 0.4 and g < 0.45:
            return args, op
        if min(values) > 0.85:
            name = "sage_fill" if g > r and g > b else "blue_fill"
            if op == b"RG":
                name = "grid"
        elif r > 0.7 and r > g * 1.3:
            name = "peach_stroke" if op == b"RG" else "peach_fill"
        elif g > r * 1.8 and g > b * 1.1:
            name = "sage_stroke" if op == b"RG" else "sage_fill"
        elif b > r * 1.8:
            name = "blue_stroke" if op == b"RG" else "blue_fill"
        elif 0.5 < r < 0.75 and abs(r - g) < 0.15:
            name = "lilac_stroke" if op == b"RG" else "lilac_fill"
        else:
            return args, op
        return rgb(name), op
    return args, op


def restyle(source, output, family):
    reader = PdfReader(source)
    before_text = "\n".join(p.extract_text() or "" for p in reader.pages)
    writer = PdfWriter(clone_from=reader)
    changes = 0
    geometry = []
    for page in writer.pages:
        content = ContentStream(page.get_contents(), writer)
        before = signature(content.operations)
        font = None
        counters = {"fill": 0, "trace": 0}
        new_ops = []
        for index, (args, op) in enumerate(content.operations):
            if op == b"Tf":
                font = page["/Resources"]["/Font"][args[0]].get_object()
            if op == b"TJ":
                array = args[0]
                revised = ArrayObject()
                for item in array:
                    if isinstance(item, str) and ";" in item:
                        assert item == ";", "Unexpected multi-glyph semicolon operand"
                        assert font["/Encoding"] == "/Identity-H"
                        ensure_comma(font)
                        revised.append(ByteStringObject(b"\x00,"))
                        # PDF TJ numbers subtract glyph advance in 1/1000 em.
                        revised.append(FloatObject(cid_width(font, 44) - cid_width(font, 59)))
                        changes += 1
                    else:
                        revised.append(item)
                args = [revised]
            args, op = recolor(args, op, family, counters) if op in (b"rg", b"RG", b"g", b"G") else (args, op)
            if op == b"rg":
                # Filled plot marks can be pale. Text must stay readable.
                for future_args, future_op in content.operations[index + 1:]:
                    if future_op == b"BT":
                        args = rgb("ink")
                        break
                    if future_op in (b"f", b"f*", b"B", b"B*", b"S", b"rg", b"g", b"Q"):
                        break
            new_ops.append((args, op))
        content.operations = new_ops
        assert signature(new_ops) == before
        page[NameObject("/Contents")] = writer._add_object(content)
        geometry.append(before)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("wb") as stream:
        writer.write(stream)
    final = PdfReader(output)
    after_text = "\n".join(p.extract_text() or "" for p in final.pages)
    assert after_text == before_text.replace(";", ",")
    assert re.findall(r"\d+(?:\.\d+)?", before_text) == re.findall(r"\d+(?:\.\d+)?", after_text)
    assert all(signature(ContentStream(p.get_contents(), final).operations) == expected
               for p, expected in zip(final.pages, geometry))
    return {"file": output.name, "original_sha256": sha(source), "published_sha256": sha(output),
            "geometry_operator_sha256": geometry, "geometry_unchanged": True,
            "numeric_text_unchanged": True, "semicolon_to_comma_edits": changes,
            "text_advance_compensated": True}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--family", choices=["portfolio", "uvm_formal"], required=True)
    args = parser.parse_args()
    assert args.source.resolve() != args.output.resolve()
    entries = [restyle(p, args.output / p.name, args.family) for p in sorted(args.source.glob("*.pdf"))]
    audit = {"schema": "trecap-vector-editorial-refresh-v1", "kind": "Presentation change only",
             "baseline_commit": "07bc8224aa080c8eaa1b77b4603c118d853465d0", "palette": PALETTE,
             "generator_sha256": sha(__file__), "files": entries,
             "scope": "Original vector paths, axes, event times and data labels retained. No new simulation, proof or board execution."}
    (args.output / "editorial_refresh.json").write_text(json.dumps(audit, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"figures": len(entries), "status": "VECTOR_GEOMETRY_VERIFIED"}))


if __name__ == "__main__":
    main()
