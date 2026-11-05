"""Separate maximum-file-size fixture. Does not rewrite the small regression."""
from pathlib import Path
import hashlib
import json
import numpy as np
from reference import convert

BASE = Path(__file__).resolve().parents[1]


def main():
    out = BASE / "vectors_limit"
    out.mkdir(exist_ok=True)
    pairs = np.random.default_rng(20261103).integers(0, 256, (96000, 2), dtype=np.uint8)
    result = convert(pairs, 3)
    acc = result["accumulators"]
    ties = (abs(acc) % 8192 == 4096) & ~result["clipped"]
    positive = int(np.sum(ties & (acc > 0)))
    negative = int(np.sum(ties & (acc < 0)))
    assert positive > 0 and negative > 0
    def write_hex(name, values, width):
        mask = (1 << (4*width))-1
        (out / name).write_text("".join(f"{int(v)&mask:0{width}x}\n" for v in values), encoding="ascii")
    write_hex("max96000.input.hex", pairs[:,0].astype(np.int64) | (pairs[:,1].astype(np.int64)<<8), 4)
    write_hex("max96000.output.hex", result["samples"], 3)
    write_hex("max96000.clip.hex", result["clipped"], 1)
    clips = int(result["clipped"].sum())
    (out / "cases.txt").write_text(f"max96000 96000 3 {clips}\n", encoding="ascii")
    manifest = dict(name="max96000", pair_count=96000, output_count=384000,
        gain_shift=3, expected_clip_count=clips, seed=20261103,
        positive_unsaturated_rounding_ties=positive, negative_unsaturated_rounding_ties=negative,
        files={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in out.glob("*.hex")})
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2)+"\n")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
