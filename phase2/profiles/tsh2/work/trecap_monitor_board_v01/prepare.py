"""Prepare PC-only gold and signed12 PCM for the existing finite TSH2 image.

This script never opens serial, network, JTAG, /dev/mem, or a board device.
Only records[].input_i32le is an input payload. All expected outputs stay on PC.
"""
from pathlib import Path
import argparse
import hashlib
import importlib.util
import json
import re
import sys

sys.dont_write_bytecode = True
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
WORK = Path(__file__).resolve().parent
OUT = ROOT / 'outputs/trecap_monitor_board_v01'
OLD_WORK = ROOT / 'work/trecap_spectral_monitor_v02'
OLD_OUT = ROOT / 'outputs/trecap_spectral_monitor_v01/revision02'
COEFF = ROOT / 'outputs/trecap_stream8_v01/fixtures02/coefficients'
GEOMETRY = {'Ns': 384000, 'Ny': 384512, 'frames': 3001,
            'sample_rate': 48000, 'delay': 384, 'hop': 128}
THRESHOLDS = (0, 10000000)
SOURCE_ID = '39db0fdf3d451dfbf2d878575725cedd3df450980b40b2a742620dfb76a1a8ed'
SOF_SHA = 'f96bc5a35adf08711a5f392baf9f8cbf5ec65a17211a58117bdb53f62acbb7ab'


def need(ok, message):
    if not ok:
        raise ValueError(message)


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def save(path, value):
    Path(path).write_text(json.dumps(value, indent=2, allow_nan=False) + '\n', encoding='utf-8')


def verify(mapping):
    for path, expected in mapping.items():
        need(sha(path) == expected, 'Changed evidence: ' + path)


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def padded_pcm(original):
    need(isinstance(original, np.ndarray) and original.dtype == np.dtype('<i4')
         and original.ndim == 1 and original.flags.c_contiguous, 'Input must be int32 PCM')
    need(len(original) in (240000, 245760), 'Only frozen 5s/5.12s cases')
    need(np.all((original >= -2048) & (original <= 2047)), 'Signed12 input range')
    result = np.zeros(GEOMETRY['Ns'], dtype='<i4')
    result[:len(original)] = original
    need(np.array_equal(result[:len(original)], original), 'Original samples preserved')
    need(not np.any(result[len(original):]), 'Only zero padding')
    return result


def bindings():
    idxpath = OLD_OUT / 'inputs01/index.json'
    calpath = OLD_OUT / 'calibration01/calibration.json'
    qualpath = OLD_OUT / 'quality01/quality.json'
    idx, cal, quality = read(idxpath), read(calpath), read(qualpath)
    need(idx['status'] == 'PASS_REGISTERED_INPUTS', 'Registered v02 inputs')
    need(cal['status'] == 'PASS_SELECTION_FROZEN' and cal['threshold'] == THRESHOLDS[1]
         and not cal['fallback_no_accepted_threshold'], 'Frozen accepted threshold 1e7')
    need(quality['status'] == 'PASS_HELDOUT_EVALUATION' and quality['heldout_quality_pass']
         and quality['threshold'] == THRESHOLDS[1], 'Prior heldout evaluation')
    need(cal['input_index_sha256'] == sha(idxpath), 'Calibration input identity')
    need(quality['calibration_sha256'] == sha(calpath), 'Quality calibration identity')
    need(idx['protocol_sha256'] == sha(OLD_WORK / 'PROTOCOL.md'), 'Original v02 protocol identity')
    evidence = dict(cal['sources_sha256'])
    verify(evidence)
    for path in (idxpath, calpath, qualpath, WORK / 'prepare.py', WORK / 'PROTOCOL.md'):
        evidence[str(path)] = sha(path)
    for qpath in (ROOT / 'work/trecap_ai_scheduler_v01/native/build01/qualification.json',
                  ROOT / 'work/trecap_spectral_monitor_v01/native/build01/qualification.json'):
        q = read(qpath)
        need(q['status'].startswith('PASS'), 'Qualified native reference')
        values = q.get('evidence_sha256', q.get('files_sha256', {}))
        need(bool(values), 'Native reference hash evidence')
        verify(values)
        evidence.update(values)
        evidence[str(qpath)] = sha(qpath)
    for path in COEFF.glob('*.memh'):
        evidence[str(path)] = sha(path)
    sof = ROOT / 'outputs/trecap_stream8_v01/build01/output_files/audio_hps.sof'
    arm = ROOT / 'outputs/trecap_laptop_fpga_v01/service_build01/service.arm'
    qualification_path = arm.parent / 'qualification.json'
    qualification = read(qualification_path)
    package_path = ROOT / 'outputs/trecap_stream8_v01/package01/package.json'
    registration = ROOT / 'outputs/trecap_stream8_v01/build01/registration.json'
    package = read(package_path)
    need(sha(sof) == SOF_SHA, 'Frozen TSH2 SOF identity')
    need(read(registration)['source_id'] == SOURCE_ID == package['source_id'], 'TSH2 source identity')
    need(sha(registration) == package['build_registration']['sha256'], 'TSH2 build registration')
    need(qualification['status'] == 'PASS_FINITE_TCP_SERVICE_OFFLINE', 'Finite TCP service qualification')
    need(sha(arm) == qualification['binary_sha256'] ==
         'e1e762c820ec8054864cea687f27d3299ba51d6616759fb7fce82ee93e8511ea', 'TSH2 TCP ARM binary identity')
    hardware = {str(path): sha(path) for path in (sof, arm, qualification_path, package_path, registration)}
    hardware.update(qualification['source_sha256'])
    hardware.update(qualification['build_evidence_sha256'])
    entries = [entry for entry in idx['records'] if entry['split'] == 'heldout' or entry['kind'] == 'synthetic']
    need(sum(e['kind'] == 'natural' for e in entries) == 4 and len(entries) == 12, 'Fixed 4+8 cases')
    prior = {record['id']: record for record in cal['results'] + quality['results']}
    for entry in entries:
        need(re.fullmatch(r'[A-Za-z0-9_-]+', entry['id']), 'Safe case identifier')
        evidence[entry['pcm']] = entry['sha256']
        if entry['kind'] == 'natural':
            evidence[entry['source']['path']] = entry['source']['sha256']
        for case in prior[entry['id']]['cases']:
            if case['threshold'] in THRESHOLDS:
                evidence.update(case['sha256'])
    verify(evidence)
    verify(hardware)
    return entries, prior, evidence, hardware


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--out', type=Path, default=OUT / 'inputs01')
    args = parser.parse_args()
    need(not args.out.exists(), 'Fresh evidence directory required')
    need(OUT.exists() and OUT.resolve().drive.upper() == 'D:', 'Root must prepare D: output junction first')
    entries, prior, evidence, hardware = bindings()
    monitor_native = module('monitor_native_reference', ROOT / 'work/trecap_spectral_monitor_v01/native/native_api.py')
    full_native = module('full_native_reference', ROOT / 'work/trecap_ai_scheduler_v01/native/native_api.py')
    sys.path.insert(0, str(OLD_WORK))
    from monitor import monitor, serial
    args.out.mkdir(parents=True)
    registration = {'schema': 'trecap-monitor-board-registration-v1', 'status': 'REGISTERED_BEFORE_NEW_GOLD',
                    'geometry': GEOMETRY, 'thresholds': list(THRESHOLDS),
                    'source_bindings': evidence, 'hardware_bindings': hardware,
                    'record_ids': [e['id'] for e in entries],
                    'case_order': [e['id'] + '_thr' + str(t) for e in entries for t in THRESHOLDS],
                    'physical_capture_repeats': 2, 'new_physical_captures': False}
    save(args.out / 'registration.json', registration)
    records, cases = [], []
    with monitor_native.Native(COEFF, GEOMETRY['Ns']) as native, full_native.Native(COEFF, GEOMETRY['Ns']) as full:
        for entry in entries:
            original = np.load(entry['pcm'], allow_pickle=False)
            need(len(original) == entry['ns'], 'Source sample count')
            pcm = padded_pcm(original)
            record_dir = args.out / entry['id']
            record_dir.mkdir()
            input_path = record_dir / 'input.i32le'
            input_path.write_bytes(pcm.tobytes())
            record = {'id': entry['id'], 'category': entry['category'], 'kind': entry['kind'], 'split': entry['split'],
                      'original_ns': len(original), 'transaction_ns': len(pcm), 'zero_pad_samples': len(pcm)-len(original),
                      'prefix_frames': len(original)//128+1, 'input_i32le': str(input_path),
                      'input_sha256': sha(input_path), 'source': entry}
            records.append(record)
            for threshold in THRESHOLDS:
                prior_case = next(case for case in prior[entry['id']]['cases'] if case['threshold'] == threshold)
                prefix_frames = record['prefix_frames']
                produced = native.produce(pcm, threshold)
                gold = full.run_full(pcm, threshold)
                need(gold['wire'] == produced['wire'], 'Independent native DSP/monitor sparse packets')
                need(len(gold['y']) == GEOMETRY['Ny'] and produced['features'].shape == (3001, 21), '8s output geometry')
                need(np.array_equal(gold['bands'], produced['features'][:, :16]), 'Independent native band sums')
                need(np.array_equal(native.decode(gold['wire'], threshold, 3001), produced['features']), 'Strict sparse decode')
                old_features = np.load(prior_case['files']['features.npy'], allow_pickle=False)
                old_spectra = np.load(prior_case['files']['spectra.npy'], allow_pickle=False)
                old_wire = Path(prior_case['files']['sparse.tsp1']).read_bytes()
                need(np.array_equal(produced['features'][:prefix_frames], old_features), 'Original feature prefix exact')
                need(np.array_equal(produced['spectra'][:prefix_frames], old_spectra), 'Original spectrum prefix exact')
                need(gold['wire'].startswith(old_wire), 'Original encoded wire prefix exact')
                original_gold = full.run_full(original, threshold)
                need(np.array_equal(gold['y'][:len(original_gold['y'])], original_gold['y']), 'Original finite waveform and tail exact')
                need(original_gold['wire'] == old_wire, 'Independent original short reference matches saved wire')
                if threshold == 0:
                    need(np.array_equal(gold['y'][384:384+len(pcm)], pcm), 'Threshold0 exact reconstruction')
                prefix_monitor = serial(monitor(produced['features'][:prefix_frames], len(original)))
                need(prefix_monitor == read(prior_case['files']['monitor.json']), 'Frozen consumer output exact')
                case_id = entry['id'] + '_thr' + str(threshold)
                folder = record_dir / ('thr' + str(threshold))
                folder.mkdir()
                y_path, wire_path = folder / 'y.i32le', folder / 'sparse.tsp1'
                y_path.write_bytes(gold['y'].astype('<i4', copy=False).tobytes())
                wire_path.write_bytes(gold['wire'])
                files = {'y.i32le': str(y_path), 'sparse.tsp1': str(wire_path)}
                for label in ('features', 'spectra'):
                    path = folder / (label + '.npy')
                    np.save(path, produced[label], allow_pickle=False)
                    files[label + '.npy'] = str(path)
                case = {'case_id': case_id, 'record_id': entry['id'], 'threshold': threshold, 'sparse': 1,
                        'original_ns': len(original), 'frames': 3001, 'prefix_frames': prefix_frames,
                        'y_i32le': str(y_path), 'y_sha256': sha(y_path),
                        'packets': {'sparse': {'path': str(wire_path), 'bytes': len(gold['wire']), 'sha256': sha(wire_path)}},
                        'files': files, 'sha256': {path: sha(path) for path in files.values()},
                        'original_case': prior_case,
                        'prefix_sparse_bytes': len(old_wire), 'prefix_compact_dense_bytes': prefix_frames * 952,
                        'transaction_compact_dense_bytes': 3001 * 952,
                        'prefix_equal_original_software_reference': True,
                        'full_y_prefix_equal_original_finite_y': True, 'consumer_prefix_equal_original': True}
                cases.append(case)
                print(case_id + ' PASS_PC_GOLD_EXACT_PREFIX', flush=True)
    verify(evidence)
    verify(hardware)
    need([case['case_id'] for case in cases] == registration['case_order'], 'Registered case order')
    result = {'schema': 'trecap-monitor-board-inputs-v1', 'status': 'PASS_PC_REFERENCES_ONLY',
              'geometry': GEOMETRY, 'thresholds': list(THRESHOLDS), 'source_id': SOURCE_ID,
              'sof_sha256': SOF_SHA, 'records': records, 'cases': cases,
              'source_bindings': evidence, 'hardware_bindings': hardware,
              'registration_sha256': sha(args.out / 'registration.json'),
              'physical_capture_repeats': 2, 'new_physical_captures': False,
              'board_upload_allowlist': [record['input_i32le'] for record in records],
              'scope': '8s finite transaction with 5s/5.12s original-signal prefix and explicit zero padding; no hardware execution.'}
    save(args.out / 'index.json', result)
    manifest = {path.relative_to(args.out).as_posix(): sha(path)
                for path in sorted(args.out.rglob('*')) if path.is_file()}
    save(args.out / 'manifest.json', manifest)
    print(json.dumps({'status': result['status'], 'records': len(records), 'cases': len(cases),
                      'index': str(args.out / 'index.json'), 'index_sha256': sha(args.out / 'index.json')}), flush=True)


if __name__ == '__main__':
    main()
