"""Validate physical TSH2 captures and run the frozen host spectral monitor.

There is deliberately no fallback from a missing capture to golden data.
The fixed 8-s transaction and the original 5/5.12-s observation are separate.
"""
from __future__ import annotations
import argparse
import csv
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import platform
import struct
import sys
import time

sys.dont_write_bytecode = True
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
FROZEN = ROOT / 'work/trecap_spectral_monitor_v02'
PRIOR = ROOT / 'outputs/trecap_spectral_monitor_v01/revision02'
NATIVE = ROOT / 'work/trecap_spectral_monitor_v01/native'
COEFF = ROOT / 'outputs/trecap_stream8_v01/fixtures02/coefficients'
NS, NY, FRAMES, THRESHOLD = 384000, 384512, 3001, 10000000


def need(condition, message):
    if not condition:
        raise ValueError(message)


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for part in iter(lambda: f.read(1024 * 1024), b''):
            h.update(part)
    return h.hexdigest()


def save(path, value):
    Path(path).write_text(json.dumps(value, indent=2, allow_nan=False) + '\n', encoding='utf-8')


def verify(mapping):
    for path, expected in mapping.items():
        need(sha(path) == expected, 'Changed evidence: ' + path)


def fresh(path):
    p = Path(path)
    need(not p.exists(), 'Preserve existing evidence: ' + str(p))
    p.mkdir(parents=True)
    return p


def csv_out(path, rows):
    with Path(path).open('w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    got = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(got)
    return got


def imports():
    common = module('frozen_monitor_common', FROZEN / 'common.py')
    previous = sys.modules.get('common')
    sys.modules['common'] = common
    try:
        mon = module('frozen_monitor', FROZEN / 'monitor.py')
    finally:
        if previous is None:
            del sys.modules['common']
        else:
            sys.modules['common'] = previous
    native = module('qualified_monitor_native', NATIVE / 'native_api.py')
    return mon, native.Native


def prefix_wire(wire, count):
    """A byte prefix of whole unchanged TSP1 packets, never re-encoded."""
    offset = 0
    for frame in range(count):
        need(offset + 48 <= len(wire), 'Truncated packet header')
        need(wire[offset:offset + 4] == b'TSP1', 'Wrong packet magic')
        need(struct.unpack_from('<Q', wire, offset + 16)[0] == frame, 'Wrong frame order')
        payload = struct.unpack_from('<I', wire, offset + 12)[0]
        offset += (48 + payload + 7) & ~7
        need(offset <= len(wire), 'Truncated packet body')
    return wire[:offset]


def load_contract(capture_path):
    cap = read(capture_path)
    need(cap['schema'] == 'trecap-monitor-board-captures-v1', 'Physical capture schema')
    need(cap['status'] == 'PASS_ACTUAL_BOARD_CAPTURE', 'Completed physical capture required')
    verify(cap['source_sha256'])
    verify(cap['admission_sha256'])
    index_path = Path(cap['input_index_path'])
    need(sha(index_path) == cap['input_index_sha256'], 'Capture/input binding')
    idx = read(index_path)
    need(idx['schema'] == 'trecap-monitor-board-inputs-v1', 'Board input schema')
    verify(idx['source_bindings'])
    verify(idx['hardware_bindings'])
    meta = cap['physical_metadata']
    need(meta['source_id'] == idx['source_id'] and meta['sof_sha256'] == idx['sof_sha256'], 'Registered FPGA source/SOF identity')
    need(bool(meta['boot_id']) and bool(meta['service_sha256']), 'Observed boot and qualified service required')
    evidence_paths = {Path(p).resolve() for p in cap['admission_sha256']}
    required_receipts = [ROOT / 'outputs/trecap_monitor_board_v01' / name for name in ('verify01.json', 'start01.json', 'finish01.json')]
    required_receipts.append(ROOT / 'outputs/trecap_stream8_v01/program_monitor01/receipt.json')
    for receipt in required_receipts:
        need(receipt.resolve() in evidence_paths, 'Capture must bind current physical receipt: ' + str(receipt))
    need(cap['final_receipt_sha256'] == sha(required_receipts[2]), 'Final service receipt binding')
    previous_epoch = None
    for actual in cap['cases']:
        physical = actual['physical_metadata']
        for key in ('boot_id', 'source_id', 'sof_sha256', 'service_sha256'):
            need(physical[key] == meta[key], 'Per-epoch physical identity mismatch: ' + key)
        need(previous_epoch is None or physical['epoch'] == previous_epoch + 1, 'Sequential physical epochs')
        previous_epoch = physical['epoch']
        verify(actual['sha256'])
        need(actual['reply_header_path'] in actual['sha256'], 'Raw response header hash required')
        header = Path(actual['reply_header_path']).read_bytes()
        need(len(header) == 40, 'Exact service header length')
        magic, status, ny, nw, epoch, wall, cpu = struct.unpack('<IIIIQQQ', header)
        need(magic == 0x31535254 and status == 0 and ny == NY * 4, 'Physical service success/geometry')
        need(epoch == physical['epoch'] and ny == actual['y_bytes'] and nw == actual['wire_bytes'], 'Header/record geometry and epoch match')
        need(ny == Path(actual['actual_y_path']).stat().st_size and nw == Path(actual['actual_wire_path']).stat().st_size, 'Header/payload byte counts')
        need(wall == actual['timing']['board_wall_ns'] and cpu == actual['timing']['board_thread_cpu_ns'], 'Header/service timing match')
        need(wall > 0 and cpu > 0 and actual['timing']['host_roundtrip_ns'] > 0, 'Positive measured service and roundtrip intervals')
    cal = read(PRIOR / 'calibration01/calibration.json')
    q = read(PRIOR / 'quality01/quality.json')
    need(cal['threshold'] == THRESHOLD, 'Use previously selected threshold, no retuning')
    need(q['calibration_sha256'] == sha(PRIOR / 'calibration01/calibration.json'), 'Frozen prior quality')
    verify(cal['sources_sha256'])
    qualification = read(NATIVE / 'build01/qualification.json')
    verify(qualification['evidence_sha256'])
    prior_idx = read(PRIOR / 'inputs01/index.json')
    need(cal['input_index_sha256'] == sha(PRIOR / 'inputs01/index.json'), 'Frozen source input index')
    source = {r['id']: r for r in prior_idx['records']}
    prior_results = {r['id']: r for r in cal['results'] + q['results']}
    wanted = {r['id'] for r in prior_idx['records'] if r['split'] == 'heldout' or r['kind'] == 'synthetic'}
    need(len(wanted) == 12, 'Four held-out natural and eight synthetic recordings')
    need({r['id'] for r in idx['records']} == wanted, 'Fixed original recording selection')
    case_map = {c['case_id']: c for c in idx['cases']}
    actual_map = {c['capture_id']: c for c in cap['cases']}
    need(len(idx['cases']) == len(case_map) == 24, 'All 24 registered cases, no duplicates')
    need(len(cap['cases']) == len(actual_map) == 48, 'All 48 physical epochs, no duplicates')
    need({(c['case_id'], c['trial_index']) for c in cap['cases']} == {(c, t) for c in case_map for t in (0, 1)}, 'Two physical repeats per registered case')
    pairs = {(c['record_id'], c['threshold']) for c in case_map.values()}
    need(pairs == {(record, t) for record in wanted for t in (0, THRESHOLD)}, 'Exact recording/threshold matrix')
    return cap, idx, source, prior_results, case_map, actual_map


def analyze(capture_path, output):
    mon, Native = imports()
    cap, idx, sources, prior_results, gold_map, actual_map = load_contract(capture_path)
    out = fresh(output)
    bindings = {str(capture_path): sha(capture_path), cap['input_index_path']: cap['input_index_sha256'],
                str(Path(__file__)): sha(__file__)}
    bindings.update(idx['source_bindings'])
    bindings.update(idx['hardware_bindings'])
    bindings.update(cap['source_sha256'])
    bindings.update(cap['admission_sha256'])
    for receipt in (PRIOR / 'inputs01/index.json', PRIOR / 'calibration01/calibration.json', PRIOR / 'quality01/quality.json'):
        bindings[str(receipt)] = sha(receipt)
    cases = []
    monitor_cache = {}
    for entry in idx['records']:
        source = sources[entry['id']]
        need(entry['original_ns'] == source['ns'], 'Original duration unchanged')
        need(entry['transaction_ns'] == NS and entry['zero_pad_samples'] == NS - source['ns'], 'Fixed zero-pad geometry')
        need(sha(entry['input_i32le']) == entry['input_sha256'], 'Registered PCM hash')
        need(sha(source['pcm']) == source['sha256'], 'Original source PCM hash')
        original = np.load(source['pcm'], allow_pickle=False)
        padded = np.fromfile(entry['input_i32le'], dtype='<i4')
        need(padded.shape == (NS,) and np.array_equal(padded[:source['ns']], original), 'Unchanged PCM prefix')
        need(np.all(padded[source['ns']:] == 0), 'Only zero tail added')
        bindings[entry['input_i32le']] = entry['input_sha256']
        bindings[source['pcm']] = source['sha256']
    with Native(COEFF, NS) as native:
        for capture_id in sorted(actual_map):
            actual = actual_map[capture_id]
            case_id = actual['case_id']
            gold = gold_map[case_id]
            source = sources[gold['record_id']]
            ns, threshold = source['ns'], int(gold['threshold'])
            need(actual['record_id'] == source['id'] and actual['threshold'] == threshold, 'Registered capture/input case identity')
            need(gold['frames'] == FRAMES, 'Complete TSH2 frame geometry')
            verify(actual['sha256'])
            for key in ('actual_wire_path', 'actual_y_path'):
                need(actual[key] in actual['sha256'], 'Actual capture hash required: ' + key)
            need(bool(actual.get('physical_metadata', cap.get('physical_metadata'))), 'Physical provenance required')
            bindings.update(actual['sha256'])
            wire = Path(actual['actual_wire_path']).read_bytes()
            y = np.fromfile(actual['actual_y_path'], dtype='<i4')
            need(y.shape == (NY,), 'All 384512 reconstructed samples required')
            # Strict native validation includes all 3001 sequence numbers, FNV
            # checksums, threshold masks, DC protection, and packet boundaries.
            full = native.prepare(wire, threshold, FRAMES)
            need(len(prefix_wire(wire, FRAMES)) == len(wire), 'No trailing bytes')
            need(sha(gold['y_i32le']) == gold['y_sha256'], 'Golden Y binding')
            packet = gold['packets']['sparse']
            need(sha(packet['path']) == packet['sha256'], 'Golden spectrum binding')
            need(wire == Path(packet['path']).read_bytes(), 'Actual full wire differs from padded reference: ' + case_id)
            expected_y = np.fromfile(gold['y_i32le'], dtype='<i4')
            need(np.array_equal(y, expected_y), 'Actual full Y differs from padded reference: ' + case_id)
            bindings[gold['y_i32le']] = gold['y_sha256']
            bindings[packet['path']] = packet['sha256']
            count = ns // 128 + 1
            prefix = prefix_wire(wire, count)
            prepared = native.prepare(prefix, threshold, count)
            f = prepared['features']
            need(np.array_equal(f, full['features'][:count]), 'Prefix/full feature equality')
            old = next(c for c in prior_results[source['id']]['cases'] if c['threshold'] == threshold)
            verify(old['sha256'])
            bindings.update(old['sha256'])
            need(prefix == Path(old['files']['sparse.tsp1']).read_bytes(), 'Physical prefix/old finite-window packet equality')
            need(np.array_equal(f, np.load(old['files']['features.npy'], allow_pickle=False)), 'Physical prefix/old feature equality')
            need(np.array_equal(prepared['spectra'], np.load(old['files']['spectra.npy'], allow_pickle=False)), 'Physical prefix/old power equality')
            monitored = mon.monitor(f, ns)
            need(mon.serial(monitored) == read(old['files']['monitor.json']), 'Physical monitor/frozen prior equality')
            if (source['id'], threshold) in monitor_cache:
                need(mon.serial(monitored) == mon.serial(monitor_cache[(source['id'], threshold)]), 'Repeat monitor identity')
            monitor_cache[(source['id'], threshold)] = monitored
            pcm = np.load(source['pcm'], allow_pickle=False)
            reconstructed = y[384:384 + ns]
            error_norm = float(np.linalg.norm(reconstructed.astype(float) - pcm))
            norm = float(np.linalg.norm(pcm.astype(float)))
            need(norm > 0 or error_norm == 0, 'A zero input must reconstruct to zero')
            nrmse = 100 * error_norm / norm if norm else 0.0
            need(abs(nrmse - old['waveform_nrmse_percent']) <= 1e-12, 'Original-duration waveform error unchanged')
            if threshold == 0:
                need(np.array_equal(reconstructed, pcm), 'Threshold-zero identity')
            folder = out / capture_id
            folder.mkdir()
            files = {}
            for name, data in [('actual_prefix.sparse.tsp1', prefix), ('same_threshold.dense.tsp1', prepared['wire'])]:
                p = folder / name
                p.write_bytes(data)
                files[name] = str(p)
            for name, data in [('actual_features.npy', f), ('actual_spectra.npy', prepared['spectra'])]:
                p = folder / name
                np.save(p, data, allow_pickle=False)
                files[name] = str(p)
            p = folder / 'monitor.json'
            save(p, mon.serial(monitored))
            files['monitor.json'] = str(p)
            cases.append({'capture_id': capture_id, 'trial_index': actual['trial_index'], 'case_id': case_id, 'record_id': source['id'], 'category': source['category'],
                          'kind': source['kind'], 'threshold': threshold, 'original_ns': ns, 'prefix_frames': count,
                          'transaction_ns': NS, 'transaction_frames': FRAMES, 'zero_pad_samples': NS - ns,
                          'actual_capture_source': actual, 'full_wire_exact': True, 'full_y_exact': True,
                          'prefix_matches_original_finite_reference': True, 'monitor_matches_frozen_prior': True,
                          'transaction_sparse_bytes': len(wire), 'transaction_compact_dense_bytes': len(full['wire']),
                          'prefix_sparse_bytes': len(prefix), 'prefix_compact_dense_bytes': len(prepared['wire']),
                          'prefix_reduction_vs_compact_dense_percent': 100 * (1 - len(prefix) / len(prepared['wire'])),
                          'original_pcm16_bytes': ns * 2, 'prefix_sparse_over_pcm16': len(prefix) / (ns * 2),
                          'waveform_nrmse_percent': nrmse, 'monitor_groups': len(monitored['ends']),
                          'files': files, 'files_sha256': {p: sha(p) for p in files.values()}})
            print('PHYSICAL EXACT ' + capture_id, flush=True)
    results = []
    for entry in idx['records']:
        source = sources[entry['id']]
        baseline = monitor_cache[(entry['id'], 0)]
        processed = monitor_cache[(entry['id'], THRESHOLD)]
        quality = mon.natural_quality(baseline, processed)
        synthetic = mon.match_events(source.get('expected_events', []), processed['events'], .512) if source['kind'] == 'synthetic' else None
        results.append({'id': entry['id'], 'category': source['category'], 'kind': source['kind'],
                        'quality': quality, 'synthetic_events': synthetic,
                        'pass': synthetic['pass'] if synthetic is not None else quality['pass']})
    verify(bindings)
    result = {'status': 'PASS_ACTUAL_BOARD_MONITOR_ANALYSIS', 'new_physical_captures': True,
              'threshold': THRESHOLD, 'case_count': len(gold_map), 'physical_epoch_count': len(cases), 'cases': cases, 'results': results,
              'quality_pass': all(r['pass'] for r in results), 'all_full_wire_and_y_exact': True,
              'input_index_path': cap['input_index_path'], 'capture_manifest_path': str(capture_path),
              'source_bindings': bindings,
              'scope': 'Actual unchanged TSH2 FPGA captures; host receives and monitors spectral packets. Each physical transaction is 8 s, with a zero tail after the original 5/5.12 s. Numerical quality and prefix byte comparisons exclude this tail. No live jack input or whole-system acceleration claim.',
              'timing_scope': 'Any board service/PIO timings include host/driver stalls; they are not compute-only FPGA times.'}
    save(out / 'analysis.json', result)
    csv_out(out / 'byte_quality_summary.csv', [{k: c[k] for k in ('capture_id', 'trial_index', 'case_id', 'category', 'kind', 'threshold', 'original_ns', 'prefix_frames', 'transaction_sparse_bytes', 'transaction_compact_dense_bytes', 'prefix_sparse_bytes', 'prefix_compact_dense_bytes', 'prefix_reduction_vs_compact_dense_percent', 'original_pcm16_bytes', 'prefix_sparse_over_pcm16', 'waveform_nrmse_percent')} for c in cases])
    print('PASS ALL ACTUAL BOARD CASES', flush=True)


def benchmark(analysis_path, output):
    mon, Native = imports()
    result = read(analysis_path)
    need(result['status'] == 'PASS_ACTUAL_BOARD_MONITOR_ANALYSIS' and result['new_physical_captures'], 'Validated physical analysis first')
    verify(result['source_bindings'])
    idx = read(result['input_index_path'])
    sources = {e['id']: e for e in idx['records']}
    prior_idx = {e['id']: e for e in read(PRIOR / 'inputs01/index.json')['records']}
    selected = [c for c in result['cases'] if c['kind'] == 'natural' and c['threshold'] == THRESHOLD and c['trial_index'] == 0]
    need(len(selected) == 4, 'Exactly four natural held-out cases')
    out = fresh(output)
    routes = ['receiver_sparse', 'receiver_dense', 'cpu_pcm_monitor']
    data = []
    for c in selected:
        verify(c['files_sha256'])
        src = prior_idx[c['record_id']]
        need(sha(src['pcm']) == src['sha256'], 'Unchanged original PCM')
        data.append({'id': c['record_id'], 'category': c['category'], 'ns': c['original_ns'], 'frames': c['prefix_frames'],
                     'pcm': np.load(src['pcm'], allow_pickle=False),
                     'sparse': Path(c['files']['actual_prefix.sparse.tsp1']).read_bytes(),
                     'dense': Path(c['files']['same_threshold.dense.tsp1']).read_bytes(),
                     'monitor': read(c['files']['monitor.json'])})
    with Native(COEFF, NS) as native:
        def operation(route, d):
            if route == 'cpu_pcm_monitor':
                features = native.run_pcm(d['pcm'], THRESHOLD)
            else:
                enc = 'sparse' if route == 'receiver_sparse' else 'dense'
                features = native.decode(d[enc], THRESHOLD, d['frames'], enc)
            return mon.monitor(features, d['ns'])
        def check(got, d):
            need(mon.serial(got) == d['monitor'], 'Timed monitor output differs')
        batches, pilots = {}, []
        for d in data:
            for route in routes:
                samples = []
                for _ in range(2):
                    t = time.perf_counter_ns()
                    got = operation(route, d)
                    samples.append(time.perf_counter_ns() - t)
                    check(got, d)
                reps = min(256, 2 ** max(0, math.ceil(math.log2(100000000 / max(min(samples), 1)))))
                batches[(d['id'], route)] = reps
                pilots.append({'recording': d['id'], 'route': route, 'pilot_ns': samples, 'repetitions': reps})
        save(out / 'registration.json', {'source': 'ACTUAL_NEW_DE1SOC_SPECTRAL_CAPTURE', 'analysis_path': str(analysis_path),
             'analysis_sha256': sha(analysis_path), 'threshold': THRESHOLD, 'routes': routes, 'warmups': 3, 'trials': 30,
             'pilots': pilots, 'recordings': [d['id'] for d in data],
             'boundary': 'Warm-RAM CPU-only per original 5-second clip. Sparse/dense include strict packet validation, native features, and complete causal monitor; CPU PCM includes FFT/threshold/features/monitor, no IFFT or packet serialization. No physical FPGA, input transport, output transport, disk or context construction timed.'})
        rows = []
        for trial in range(-3, 30):
            j = trial + 3
            ordered = data if j % 2 == 0 else data[::-1]
            for i, d in enumerate(ordered):
                rr = routes if (i + j) % 2 == 0 else routes[::-1]
                shift = (i + j) % len(routes)
                rr = rr[shift:] + rr[:shift]
                for position, route in enumerate(rr):
                    reps = batches[(d['id'], route)]
                    ct, wt = time.process_time_ns(), time.perf_counter_ns()
                    for _ in range(reps):
                        got = operation(route, d)
                    wall, cpu = time.perf_counter_ns() - wt, time.process_time_ns() - ct
                    check(got, d)
                    rows.append({'trial': trial, 'warmup': int(trial < 0), 'recording': d['id'], 'route': route,
                                 'order': position, 'repetitions': reps, 'wall_batch_ns': wall, 'cpu_batch_ns': cpu,
                                 'wall_ns_per_clip': wall / reps, 'cpu_ns_per_clip': cpu / reps})
            if trial < 0 or trial % 5 == 4:
                print('PHYSICAL RECEIVER REPLAY ' + str(trial) + ' PASS', flush=True)
    csv_out(out / 'raw_trials.csv', rows)
    verify(result['source_bindings'])
    need(len(rows) == 396, 'Complete 33 x 4 x 3 matrix')
    save(out / 'validation.json', {'status': 'PASS_ACTUAL_CAPTURE_RECEIVER_TIMING', 'new_physical_captures': True,
         'observations': len(rows), 'measured_observations': sum(r['warmup'] == 0 for r in rows),
         'every_output_checked': True, 'raw_trials_sha256': sha(out / 'raw_trials.csv'),
         'source_analysis_sha256': sha(analysis_path), 'platform': platform.platform(), 'python': platform.python_version(),
         'zero_cpu_batches': sum(r['cpu_batch_ns'] == 0 for r in rows),
         'minimum_batch_wall_ns': min(r['wall_batch_ns'] for r in rows)})
    print('ACTUAL CAPTURE RECEIVER BENCHMARK PASS', flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('phase', choices=['analyze', 'benchmark'])
    parser.add_argument('--input', type=Path, required=True, help='Capture manifest for analyze; analysis.json for benchmark')
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    (analyze if args.phase == 'analyze' else benchmark)(args.input, args.out)
