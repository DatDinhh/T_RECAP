#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Prepare two board-checker ROMs after C++/independent integer agreement."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import subprocess
import sys


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def integers(path, bits, signed=True):
    values = [int(s, 16) for s in path.read_text().split()]
    assert all(0 <= v < (1 << bits) for v in values), path
    if signed:
        values = [v - (1 << bits) if v >= (1 << (bits - 1)) else v for v in values]
    return values


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--reference-exe', type=Path, required=True)
    args = parser.parse_args()
    repo, out = args.repo.resolve(), args.out.resolve()
    out.mkdir(parents=True, exist_ok=False)
    sys.path.insert(0, str(repo / 'scripts/verification'))
    import reference_integer_oracle as oracle
    vector = repo / 'artifacts/test_vectors/near_threshold_multitone_Ns1024_thr64'
    coeff = repo / 'artifacts/coefficients'
    x = integers(vector / 'x_in.memh', 12)
    window = integers(coeff / 'window_qw.memh', 16, signed=False)
    forward = list(zip(integers(coeff / 'twiddle_re.memh', 17),
                       integers(coeff / 'twiddle_im.memh', 17)))
    inverse = list(zip(integers(coeff / 'twiddle_inv_re.memh', 17),
                       integers(coeff / 'twiddle_inv_im.memh', 17)))
    assert len(x) == 1024 and any(x)
    manifest = {'scope': 'Two finite multitone workloads; C++/independent integer output agreement',
                'input_samples': len(x), 'output_samples': 1536, 'frames': 9,
                'input_sha256': sha(vector / 'x_in.memh'),
                'reference_executable_sha256': sha(args.reference_exe),
                'oracle_sha256': sha(Path(oracle.__file__)),
                'coefficient_sha256': {p.name: sha(p) for p in sorted(coeff.glob('*.memh'))},
                'cases': [],
                'limitations': ['This does not qualify the entire input domain.',
                                'Threshold comparisons retain the full FFT/IFFT schedule.',
                                'Spectral retention is not electrical energy saving.']}
    for name, threshold in [('dense', 0), ('masked', 100_000_000_000)]:
        target = out / name
        command = [str(args.reference_exe), '--vector-dir', str(vector),
                   '--coeff-dir', str(coeff), '--output-dir', str(target),
                   '--thr2', str(threshold), '--collect-bin-stats']
        result = subprocess.run(command, capture_output=True, text=True)
        (out / (name + '.log')).write_text(result.stdout + result.stderr)
        if result.returncode:
            raise RuntimeError(f'C++ reference failed for {name}: {result.returncode}')
        expected = oracle.run(x, threshold, window, forward, inverse)
        y = integers(target / 'y_out.memh', 12)
        assert len(y) == 1536
        independent = [expected[('Y', i)][0] for i in range(1536)]
        mismatches = [i for i, (a, b) in enumerate(zip(y, independent)) if a != b]
        if mismatches:
            raise RuntimeError(f'{name}: oracle disagreement at {mismatches[:10]}')
        encoded = ''.join(f'{v & 0xfff:03x}\n' for v in independent).encode('ascii')
        rom = out / ('y_' + name + '.memh')
        rom.write_bytes(encoded)
        reference = [x[i - 384] if 384 <= i < 1408 else 0 for i in range(1536)]
        error = [a-b for a,b in zip(reference, y)]
        eligible = expected[('M', 'eligible_unique_bins')][0]
        suppressed = expected[('M', 'eligible_suppressed_bins')][0]
        manifest['cases'].append({'name': name, 'threshold': threshold,
            'cpp_oracle_output_mismatches': 0, 'output_sha256': sha(rom),
            'eligible_bins': eligible, 'suppressed_bins': suppressed,
            'rmse_full_stream_lsb': math.sqrt(sum(e*e for e in error) / len(error)),
            'max_abs_error_lsb': max(map(abs, error)),
            'spectral_retention_ratio': expected[('M', 'eligible_kept_mag2')][0] /
                                        expected[('M', 'eligible_total_mag2')][0]})
    (out / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print(json.dumps(manifest, indent=2))


if __name__ == '__main__':
    main()
