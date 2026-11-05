"""Recompute every public fixture with the independent integer FIR reference."""
from pathlib import Path
import argparse, hashlib, importlib.util, json, re
import numpy as np

HERE = Path(__file__).resolve().parent
MODEL = HERE.parents[1]/'profiles/trf1/adapter/model/reference.py'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    spec = importlib.util.spec_from_file_location('rf_reference', MODEL)
    model = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(model)
    checks = []
    sample_count = 0
    for directory in ('vectors', 'vectors_limit'):
        for line in (HERE/directory/'cases.txt').read_text().splitlines():
            name, count, gain, clips = line.split()
            packed = np.loadtxt(HERE/directory/(name+'.input.hex'), dtype=np.int64,
                                converters=lambda x: int(x, 16), ndmin=1)
            pairs = np.stack([packed & 255, packed >> 8], axis=1)
            expected = np.loadtxt(HERE/directory/(name+'.output.hex'), dtype=np.int64,
                                  converters=lambda x: int(x, 16), ndmin=1)
            expected = np.where(expected >= 2048, expected-4096, expected)
            expected_clips = np.loadtxt(HERE/directory/(name+'.clip.hex'), dtype=np.int64, ndmin=1)
            result = model.convert(pairs, int(gain))
            assert len(pairs) == int(count)
            np.testing.assert_array_equal(result['samples'], expected)
            np.testing.assert_array_equal(result['clipped'], expected_clips)
            assert int(result['clipped'].sum()) == int(clips)
            sample_count += len(expected)
            checks.append(dict(fixture=name, samples=len(expected), gain=int(gain), status='PASS'))
    manifest = json.loads((HERE/'fixtures/manifest.json').read_text())
    for fixture in manifest['cases']:
        name = fixture['name']
        packed = np.loadtxt(HERE/'fixtures'/(name+'.iq.hex'), dtype=np.int64,
                            converters=lambda x: int(x, 16), ndmin=1)
        pairs = np.stack([packed & 255, packed >> 8], axis=1)
        expected = np.loadtxt(HERE/'fixtures'/(name+'.pcm.hex'), dtype=np.int64,
                              converters=lambda x: int(x, 16), ndmin=1)
        expected = np.where(expected >= 2048, expected-4096, expected)
        result = model.convert(pairs, fixture['gain'])
        np.testing.assert_array_equal(result['samples'], expected[:4*len(pairs)])
        assert np.all(expected[4*len(pairs):] == 0)
        assert int(result['clipped'].sum()) == fixture['clips']
        sample_count += len(expected)
        checks.append(dict(fixture=name, samples=len(expected), gain=fixture['gain'], status='PASS'))
    coefficients = HERE.parents[1]/'profiles/trf1/adapter/coefficients/rf_coefficients.svh'
    entries = re.findall(r"7'd(\d+): rf_coeff = (-?)18'sd(\d+)", coefficients.read_text())
    actual = np.array([(-1 if sign else 1)*int(value) for index, sign, value in entries])
    assert [int(index) for index, _, _ in entries] == list(range(81))
    np.testing.assert_array_equal(actual, model.coefficients())
    report = dict(status='PASS', scope='Independent full-convolution fixture and coefficient regeneration',
                  rtl_simulation_performed=False, fixtures=len(checks), samples=sample_count,
                  coefficients_checked=81, reference_sha256=hashlib.sha256(MODEL.read_bytes()).hexdigest(),
                  results=checks)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2)+'\n', newline='\n')
    print(json.dumps({k: v for k, v in report.items() if k != 'results'}))


if __name__ == '__main__':
    main()
