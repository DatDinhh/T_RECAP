"""Generate synthetic integration fixtures from independent full convolution."""
from pathlib import Path
import argparse, hashlib, importlib.util, json
import numpy as np

HERE = Path(__file__).resolve().parent
MODEL = HERE.parents[1] / 'profiles/trf1/adapter/model/reference.py'


def generate(out):
    spec = importlib.util.spec_from_file_location('rf_reference', MODEL)
    model = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(model)
    out.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(20261104)
    n = np.arange(128)
    tone = np.rint(127.5 + 100*np.stack([
        np.cos(2*np.pi*13*n/128), np.sin(2*np.pi*13*n/128)], axis=1)).astype(np.uint8)
    random = rng.integers(0, 256, (512, 2), dtype=np.uint8)
    taps = model.coefficients()
    extreme = np.full((21, 2), 128, dtype=np.uint8)
    for lag in range(21):
        index = 4*lag+2
        coefficient = int(taps[index]) if index < 81 else 0
        extreme[20-lag, 0] = 255 if -coefficient >= 0 else 0
    cases = []
    rows = []
    for name, pairs, gain, configurations in (
        ('tone128', tone, 1, [(t, s) for t in (0, 100000000) for s in (0, 1)]),
        ('random512', random, 1, [(t, s) for t in (0, 100000000) for s in (0, 1)]),
        ('clip21', extreme, 3, [(t, s) for t in (0, 100000000) for s in (0, 1)]),
        ('minimum1_gain0', np.array([[255, 0]], dtype=np.uint8), 0, [(0, 1), ((1 << 56)-1, 1)]),
        ('tone128_gain2', tone, 2, [(100000000, 0), ((1 << 56)-1, 1)]),
    ):
        result = model.convert(pairs, gain)
        pcm = np.zeros(2048, dtype=np.int16)
        pcm[:len(result['samples'])] = result['samples']
        values = pairs[:, 0].astype(int) | (pairs[:, 1].astype(int) << 8)
        (out / (name+'.iq.hex')).write_text(''.join(f'{int(v):04x}\n' for v in values), newline='\n')
        (out / (name+'.pcm.hex')).write_text(''.join(f'{int(v)&4095:03x}\n' for v in pcm), newline='\n')
        clips = int(result['clipped'].sum())
        cases.append(dict(name=name, pairs=len(pairs), gain=gain, clips=clips,
                          configurations=[dict(threshold=t, sparse=s) for t, s in configurations]))
        for threshold, sparse in configurations:
            rows.append(f'fixtures/{name}.iq.hex fixtures/{name}.pcm.hex {len(pairs)} {gain} {clips} {threshold:x} {sparse}')
    (out/'cases.txt').write_text('\n'.join(rows)+'\n', newline='\n')
    result = dict(schema='rf-synthetic-integration-fixtures-v1', cases=cases, configuration_count=len(rows),
                  reference='profiles/trf1/adapter/model/reference.py',
                  reference_sha256=hashlib.sha256(MODEL.read_bytes()).hexdigest(),
                  files={p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(out.glob('*.hex'))})
    (out/'manifest.json').write_text(json.dumps(result, indent=2)+'\n', newline='\n')
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(generate(args.out)))
