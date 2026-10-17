"""Queue/HTTP isolation tests with fake data and hardware; no board access."""
import copy
import hashlib
import http.client
from http.server import ThreadingHTTPServer
import io
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
import wave

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from server import App, Handler, JobQueue, THRESHOLDS


def wait_terminal(queue, ident, timeout=3):
    until = time.monotonic() + timeout
    while time.monotonic() < until:
        result = queue.get(ident)
        if result['status'] in ('complete', 'failed', 'superseded'):
            return result
        time.sleep(.005)
    raise AssertionError('Queue did not settle: ' + repr(queue.get(ident)))


class FakeStore:
    """Keep result IDs bound to snapshots while latest pointers can change."""
    def __init__(self, baseline=True):
        self.lock = threading.RLock()
        self.latest = {}
        self.result_captures = {}
        self.actuals = {}
        self.records = {'fixture': {'id': 'fixture', 'input_sha256': hashlib.sha256(b'pcm').hexdigest()}}
        self.register_calls = []
        self.upload_calls = []
        self.bundle_calls = []
        self.saved = {}
        self.sequence = 0
        self.before_capture = None
        self.registration_error = None
        if baseline:
            self.add_archived(0)
            self.add_archived(10000000)

    def add_archived(self, threshold):
        path = 'fixture_' + str(threshold) + '.tsp1'
        digest = hashlib.sha256(path.encode()).hexdigest()
        case = 'fixture_thr' + str(threshold) + '_trial0'
        ident = 'recorded-' + case + '-' + digest[:10]
        self.actuals[('fixture', threshold, 0)] = {'capture_id': case, 'actual_wire_path': path,
                                                'sha256': {path: digest}}
        self.saved[ident] = {'result_id': ident, 'threshold': threshold,
                             'record': {'id': 'fixture'}, 'provenance': {'mode': 'archived_physical'}}
        return ident

    def record(self, source):
        if source not in self.records:
            raise KeyError('Unknown recording')
        return self.records[source]

    def pcm(self, source, padded=True):
        self.record(source)
        return np.array([-2048, 1024, 2047, 0], dtype='<i4')

    def catalog(self):
        return {'records': [{'id': source, 'label': source, 'kind': 'synthetic',
                             'duration_seconds': 1.28,
                             'thresholds': sorted({t for r, t, _ in self.actuals if r == source} |
                                                  {t for r, t in self.latest if r == source})}
                            for source in self.records]}

    def get_capture(self, source, threshold, trial=0):
        if self.before_capture is not None:
            self.before_capture(source, threshold)
        with self.lock:
            self.record(source)
            latest = self.latest.get((source, threshold))
            if latest:
                return self.result_captures[latest]
            row = self.actuals.get((source, threshold, trial))
            if row is None:
                raise KeyError('No physical capture')
            ident = 'recorded-' + row['capture_id'] + '-' + row['sha256'][row['actual_wire_path']][:10]
            self.result_captures[ident] = self.saved[ident]
            return self.result_captures[ident]

    def get_bundle(self, ident):
        if ident not in self.result_captures:
            raise KeyError('Unknown result')
        return copy.deepcopy(self.result_captures[ident])

    def bundle(self, source, threshold, trial=0):
        self.bundle_calls.append((source, threshold))
        return self.get_bundle(self.get_capture(source, threshold, trial)['result_id'])

    def register_capture(self, source, threshold, **kwargs):
        with self.lock:
            if self.registration_error is not None:
                raise ValueError(self.registration_error)
            self.sequence += 1
            ident = 'live-fixture-' + str(threshold) + '-' + str(self.sequence)
            result = {'result_id': ident, 'threshold': threshold, 'record': {'id': source},
                      'sequence': self.sequence, 'provenance': {'mode': 'new_physical'}}
            self.result_captures[ident] = result
            self.latest[(source, threshold)] = ident
            self.register_calls.append((source, threshold, kwargs))
            return ident

    def wav(self, ident, mode):
        self.get_bundle(ident)
        if mode not in ('original', 'processed', 'difference'):
            raise ValueError('Unknown audio mode')
        return b'RIFF-test-only'

    def register_wav(self, filename, raw):
        self.upload_calls.append((filename, raw))
        if raw != b'RIFF-test-WAVE-valid':
            raise ValueError('Invalid WAV fixture')
        ident = 'upload-fixture'
        self.records[ident] = {'id': ident, 'input_sha256': 'fake-pcm-hash'}
        return ident

    def restore_capture(self, path):
        raise AssertionError('Tests have no persisted physical captures to restore')


class FakeHardware:
    def __init__(self, block=False, fail=False):
        self.available = True
        self.block = block
        self.fail = fail
        self.calls = []
        self.started = threading.Event()
        self.release = threading.Event()
        self.finished = threading.Event()
        self.connect_calls = 0

    def status(self):
        return {'available': self.available, 'status': 'Fake hardware for tests only'}

    def connect(self):
        self.connect_calls += 1
        return self.status()

    def capture(self, raw, threshold, input_sha256, folder, progress):
        Path(folder).mkdir(parents=True, exist_ok=False)
        self.calls.append((threshold, folder))
        self.started.set()
        progress({'phase': 'admission', 'message': 'Fake physical admission'})
        progress({'phase': 'starting', 'message': 'Fake service start'})
        progress({'phase': 'sending', 'message': 'Fake input send', 'completed_bytes': 0, 'total_bytes': len(raw)})
        progress({'phase': 'processing', 'message': 'Fake physical epoch in progress'})
        if self.block and len(self.calls) == 1 and not self.release.wait(3):
            raise RuntimeError('Test did not release active epoch')
        if self.fail:
            self.available = False
            raise RuntimeError('Injected hardware failure; no fallback')
        progress({'phase': 'receiving', 'message': 'Fake reply', 'completed_bytes': 20, 'total_bytes': 20})
        progress({'phase': 'verifying', 'message': 'Fake completion verification'})
        self.finished.set()
        return {'y_bytes': b'fake-y', 'wire_bytes': b'fake-wire', 'reply_header': b'fake-header',
                'physical_metadata': {'test_only': True}, 'timing': {}}


class QueueContracts(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = FakeStore()
        self.hardware = FakeHardware()
        self.queue = JobQueue(self.store, self.hardware, Path(self.tmp.name))

    def tearDown(self):
        self.hardware.release.set()
        self.queue.close()
        self.tmp.cleanup()

    def test_newest_pending_wins_without_aborting_active(self):
        self.hardware.block = True
        first = self.queue.submit('fixture', 10000000, True)
        self.assertTrue(self.hardware.started.wait(1))
        middle = self.queue.submit('fixture', 100000000, True)
        latest = self.queue.submit('fixture', 1000000000, True)
        self.assertEqual(self.queue.get(middle['job_id'])['status'], 'superseded')
        self.assertEqual(self.queue.status()['active_job']['job_id'], first['job_id'])
        self.assertEqual(self.queue.status()['pending_job']['job_id'], latest['job_id'])
        self.assertEqual(len(self.hardware.calls), 1)
        self.assertFalse(self.hardware.finished.is_set())
        self.hardware.release.set()
        self.assertEqual(wait_terminal(self.queue, first['job_id'])['status'], 'complete')
        self.assertEqual(wait_terminal(self.queue, latest['job_id'])['status'], 'complete')
        self.assertEqual([t for t, _ in self.hardware.calls], [10000000, 1000000000])
        # The client's initial response was a snapshot, not a mutable job alias.
        self.assertEqual(first['status'], 'queued')

    def test_uploaded_record_requires_real_baseline_then_selected_threshold(self):
        self.store.actuals.clear()
        job = self.queue.submit('fixture', 10000000, True)
        result = wait_terminal(self.queue, job['job_id'])
        self.assertEqual(result['status'], 'complete')
        self.assertEqual([t for t, _ in self.hardware.calls], [0, 10000000])
        self.assertTrue(str(self.hardware.calls[0][1]).endswith('_baseline'))
        reference = [event for event in result['events'] if event['phase'] == 'reference']
        self.assertEqual([(event['pass_kind'], event['threshold']) for event in reference],
                         [('baseline', 0), ('selected', 10000000)])
        baseline_start = next(event['sequence'] for event in result['events']
                              if event['phase'] == 'admission' and event['pass_kind'] == 'baseline')
        selected_start = next(event['sequence'] for event in result['events']
                              if event['phase'] == 'admission' and event['pass_kind'] == 'selected')
        self.assertLess(baseline_start, reference[0]['sequence'])
        self.assertLess(reference[0]['sequence'], selected_start)
        self.assertLess(selected_start, reference[1]['sequence'])
        self.assertEqual(result['progress']['pass_kind'], 'selected')
        self.assertEqual(result['progress']['threshold'], 10000000)

    def test_threshold_zero_missing_baseline_runs_only_once(self):
        self.store.actuals.clear()
        job = self.queue.submit('fixture', 0, True)
        result = wait_terminal(self.queue, job['job_id'])
        self.assertEqual(result['status'], 'complete')
        self.assertEqual([t for t, _ in self.hardware.calls], [0])
        self.assertEqual(result['progress']['pass_kind'], 'baseline')
        self.assertEqual(result['progress']['threshold'], 0)

    def test_hardware_failure_does_not_substitute_recorded_or_software_result(self):
        self.hardware.fail = True
        job = self.queue.submit('fixture', 10000000, True)
        result = wait_terminal(self.queue, job['job_id'])
        self.assertEqual(result['status'], 'failed')
        self.assertNotIn('result_id', result)
        self.assertEqual(self.store.register_calls, [])
        self.assertEqual(self.store.bundle_calls, [])
        self.assertEqual(result['progress']['phase'], 'failed')
        self.assertEqual(result['events'][-1]['phase'], 'failed')
        self.assertNotIn('receiving', [event['phase'] for event in result['events']])

    def test_full_reference_failure_latches_board_and_blocks_next_pending_capture(self):
        self.hardware.block = True
        self.store.registration_error = 'Injected full Y or spectral reference mismatch'
        first = self.queue.submit('fixture', 100000000, True)
        self.assertTrue(self.hardware.started.wait(1))
        pending = self.queue.submit('fixture', 1000000000, True)
        self.assertEqual(self.queue.status()['pending_job']['job_id'], pending['job_id'])
        self.hardware.release.set()
        first_result = wait_terminal(self.queue, first['job_id'])
        next_result = wait_terminal(self.queue, pending['job_id'])
        self.assertEqual(first_result['status'], 'failed')
        self.assertIn('reference mismatch', first_result['message'])
        self.assertEqual(next_result['status'], 'failed')
        self.assertIn('Board is unavailable', next_result['message'])
        self.assertFalse(self.hardware.available)
        self.assertIn('explicit reconnect required', self.hardware.message)
        self.assertEqual([t for t, _ in self.hardware.calls], [100000000])
        self.assertEqual(self.store.register_calls, [])
        self.assertEqual(self.store.bundle_calls, [])
        self.assertNotIn('result_id', first_result)
        self.assertNotIn('result_id', next_result)
        receipt = Path(self.tmp.name) / 'hardware_jobs' / first['job_id'] / 'reference_failure.json'
        evidence = json.loads(receipt.read_text(encoding='utf-8'))
        self.assertEqual(evidence['status'], 'FAIL_REFERENCE_VERIFICATION')
        self.assertIn('reference mismatch', evidence['error'])

    def test_force_false_can_explicitly_reuse_completed_recorded_capture(self):
        self.hardware.available = False
        job = self.queue.submit('fixture', 10000000, False)
        result = wait_terminal(self.queue, job['job_id'])
        self.assertEqual(result['status'], 'complete')
        self.assertTrue(result['result_id'].startswith('recorded-'))
        self.assertEqual(self.hardware.calls, [])
        self.assertEqual([event['phase'] for event in result['events']],
                         ['queued', 'preparing', 'cached', 'consumer', 'complete'])

    def test_progress_history_is_ordered_and_nested_snapshots_are_isolated(self):
        self.hardware.block = True
        submitted = self.queue.submit('fixture', 10000000, True)
        self.assertTrue(self.hardware.started.wait(1))
        ident = submitted['job_id']
        snapshot = self.queue.get(ident)
        self.assertEqual(submitted['events'][0]['phase'], 'queued')
        self.assertEqual(len(submitted['events']), 1)
        snapshot['progress']['phase'] = 'tampered'
        snapshot['events'][0]['message'] = 'tampered'
        snapshot['events'].clear()
        active = self.queue.status()['active_job']
        active['events'][0]['message'] = 'changed through status'
        self.assertEqual(self.queue.get(ident)['events'][0]['message'], 'Queued')
        self.assertNotEqual(self.queue.get(ident)['progress']['phase'], 'tampered')
        self.hardware.release.set()
        result = wait_terminal(self.queue, ident)
        events = result['events']
        self.assertEqual([event['phase'] for event in events],
                         ['queued', 'preparing', 'preparing', 'admission', 'starting', 'sending',
                          'processing', 'receiving', 'verifying', 'reference', 'consumer', 'complete'])
        self.assertEqual([event['sequence'] for event in events], list(range(1, len(events) + 1)))
        self.assertEqual([event['elapsed_ms'] for event in events], sorted(event['elapsed_ms'] for event in events))
        self.assertTrue(all(event['at'] >= result['created_at'] for event in events))
        self.assertTrue(all(event['pass_kind'] == 'selected' and event['threshold'] == 10000000 for event in events))
        self.assertEqual(result['progress']['phase'], 'complete')
        self.assertNotIn('completed_bytes', result['progress'], 'Byte progress belongs only to its measured phase')

    def test_superseded_pending_request_has_terminal_progress_without_board_events(self):
        self.hardware.block = True
        self.queue.submit('fixture', 10000000, True)
        self.assertTrue(self.hardware.started.wait(1))
        pending = self.queue.submit('fixture', 100000000, True)
        self.queue.submit('fixture', 1000000000, True)
        result = self.queue.get(pending['job_id'])
        self.assertEqual(result['progress']['phase'], 'superseded')
        self.assertEqual([event['phase'] for event in result['events']], ['queued', 'superseded'])

    def test_stop_discards_pending_but_waits_for_started_capture(self):
        self.hardware.block = True
        active = self.queue.submit('fixture', 10000000)
        self.assertTrue(self.hardware.started.wait(1))
        queued = self.queue.submit('fixture', 100000000)
        stopped = threading.Event()
        thread = threading.Thread(target=lambda: (self.queue.close(), stopped.set()), daemon=True)
        thread.start()
        until = time.monotonic() + 1
        while self.queue.get(queued['job_id'])['status'] != 'superseded' and time.monotonic() < until:
            time.sleep(.005)
        self.assertEqual(self.queue.get(queued['job_id'])['status'], 'superseded')
        self.assertFalse(stopped.is_set())
        self.hardware.release.set()
        self.assertTrue(stopped.wait(2))
        self.assertEqual(self.queue.get(active['job_id'])['status'], 'complete')
        self.assertEqual(len(self.hardware.calls), 1)

    def test_invalid_thresholds_do_not_enter_queue(self):
        for value in (-1, True, '10000000', 1.5, None, THRESHOLDS[-1] + 1):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.queue.submit('fixture', value)
        self.assertEqual(self.queue.jobs, {})
        self.assertEqual(self.hardware.calls, [])


class HTTPContracts(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = FakeStore()
        self.hardware = FakeHardware()
        self.app = App(self.store, self.hardware, Path(self.tmp.name))
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.server.app = self.app
        self.server.daemon_threads = True
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={'poll_interval': .01}, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.hardware.release.set()
        self.server.shutdown()
        self.server.server_close()
        self.app.queue.close()
        self.tmp.cleanup()

    def request(self, method, path, body=None, headers=None, token=True):
        hdr = {'Connection': 'close'}
        if isinstance(body, (dict, list)):
            body = json.dumps(body).encode()
            hdr['Content-Type'] = 'application/json'
        if method == 'POST' and token:
            hdr['X-Demo-Token'] = self.app.token
        if headers:
            hdr.update(headers)
        conn = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=3)
        try:
            conn.request(method, path, body=body, headers=hdr)
            response = conn.getresponse()
            raw = response.read()
            return response.status, dict(response.getheaders()), raw
        finally:
            conn.close()

    def test_valid_run_and_historical_result_remain_distinct(self):
        old_id = next(k for k, v in self.app.result_lookup.items() if v[1] == 10000000)
        status, _, old_raw = self.request('GET', '/api/results/' + old_id)
        self.assertEqual(status, 200)
        status, _, reply = self.request('POST', '/api/run', {'source_id': 'fixture', 'threshold': 10000000})
        self.assertEqual(status, 202)
        job = wait_terminal(self.app.queue, json.loads(reply)['job_id'])
        self.assertEqual(job['status'], 'complete')
        self.assertNotEqual(job['result_id'], old_id)
        status, _, still_old = self.request('GET', '/api/results/' + old_id)
        self.assertEqual(status, 200)
        self.assertEqual(old_raw, still_old)
        self.assertEqual(self.store.latest[('fixture', 10000000)], job['result_id'])

    def test_historical_first_get_after_new_capture_still_loads_original(self):
        old_id = next(k for k, v in self.app.result_lookup.items() if v[1] == 10000000)
        job = self.app.queue.submit('fixture', 10000000)
        result = wait_terminal(self.app.queue, job['job_id'])
        status, _, raw = self.request('GET', '/api/results/' + old_id)
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(raw)['provenance']['mode'], 'archived_physical')
        self.assertEqual(self.store.latest[('fixture', 10000000)], result['result_id'])

    def test_lazy_historical_get_does_not_overwrite_concurrent_latest_result(self):
        old_id = next(k for k, v in self.app.result_lookup.items() if v[1] == 10000000)
        self.store.register_capture('fixture', 10000000)
        entered, release, written = threading.Event(), threading.Event(), threading.Event()
        results, errors = {}, []

        def gate(source, threshold):
            if source == 'fixture' and threshold == 10000000:
                entered.set()
                if not release.wait(2):
                    raise RuntimeError('Historical read gate timed out')

        def getter():
            try:
                results['old'] = self.app.bundle(old_id)
            except Exception as exc:
                errors.append(exc)

        def writer():
            results['new'] = self.store.register_capture('fixture', 10000000)
            written.set()

        self.store.before_capture = gate
        get_thread = threading.Thread(target=getter, daemon=True)
        write_thread = threading.Thread(target=writer, daemon=True)
        get_thread.start()
        self.assertTrue(entered.wait(1))
        write_thread.start()
        try:
            self.assertFalse(written.wait(.05), 'New result must wait for the complete historical latest-pointer operation')
        finally:
            release.set()
            get_thread.join(2)
            write_thread.join(2)
            self.store.before_capture = None
        self.assertEqual(errors, [])
        self.assertEqual(results['old']['result_id'], old_id)
        self.assertEqual(self.store.latest[('fixture', 10000000)], results['new'])

    def test_source_preview_uses_fixed_shared_gain_eight(self):
        status, _, raw = self.request('GET', '/api/sources/fixture/audio')
        self.assertEqual(status, 200)
        with wave.open(io.BytesIO(raw), 'rb') as wav:
            samples = np.frombuffer(wav.readframes(wav.getnframes()), dtype='<i2')
        np.testing.assert_array_equal(samples, self.store.pcm('fixture', False) * 8)

    def test_missing_or_incorrect_token_never_touches_hardware(self):
        for headers in ({}, {'X-Demo-Token': 'not-the-token'}):
            status, _, _ = self.request('POST', '/api/run', {'source_id': 'fixture', 'threshold': 0},
                                        headers=headers, token=False)
            self.assertEqual(status, 400)
        self.assertEqual(self.app.queue.jobs, {})
        self.assertEqual(self.hardware.calls, [])

    def test_cross_origin_and_untrusted_host_are_rejected(self):
        for headers in ({'Origin': 'https://example.invalid'}, {'Origin': 'null'}, {'Host': 'attacker.invalid'}):
            status, _, _ = self.request('POST', '/api/run', {'source_id': 'fixture', 'threshold': 0}, headers=headers)
            self.assertEqual(status, 400)
        status, _, _ = self.request('GET', '/api/config', headers={'Host': 'attacker.invalid'})
        self.assertEqual(status, 400)
        self.assertEqual(self.app.queue.jobs, {})

    def test_matching_loopback_origin_is_accepted(self):
        status, _, _ = self.request('POST', '/api/run', {'source_id': 'fixture', 'threshold': 0},
                                    headers={'Origin': 'http://127.0.0.1:' + str(self.server.server_port)})
        self.assertEqual(status, 202)

    def test_path_traversal_does_not_read_local_files(self):
        for path in ('/../data.py', '/%2e%2e/data.py', '/static/../../data.py', '/api/results/..',
                     '/api/sources/../../data.py/audio', '/C:/Windows/win.ini'):
            with self.subTest(path=path):
                status, _, raw = self.request('GET', path)
                self.assertEqual(status, 404)
                self.assertNotIn(b'Hash-bound physical', raw)

    def test_json_threshold_and_shape_validation(self):
        for value in (-1, True, '10000000', 1.5, None, 100000000001):
            with self.subTest(value=value):
                status, _, _ = self.request('POST', '/api/run', {'source_id': 'fixture', 'threshold': value})
                self.assertEqual(status, 400)
        status, _, _ = self.request('POST', '/api/run', [])
        self.assertEqual(status, 400)
        status, _, _ = self.request('POST', '/api/run', b'not-json', headers={'Content-Type': 'application/json'})
        self.assertEqual(status, 400)
        self.assertEqual(self.app.queue.jobs, {})

    def test_upload_larger_than_32mib_is_rejected_without_reading_or_parsing(self):
        status, _, raw = self.request('POST', '/api/upload', b'',
                                      headers={'Content-Type': 'audio/wav', 'Content-Length': str(32 * 1024 * 1024 + 1)})
        self.assertEqual(status, 400)
        self.assertIn(b'too large', raw)
        self.assertEqual(self.store.upload_calls, [])

    def test_bad_wav_returns_error_and_no_hardware_job(self):
        status, _, raw = self.request('POST', '/api/upload', b'not-a-wave',
                                      headers={'Content-Type': 'audio/wav', 'X-Filename': 'bad.wav'})
        self.assertEqual(status, 400)
        self.assertIn(b'Invalid WAV', raw)
        self.assertEqual(self.app.queue.jobs, {})
        self.assertEqual(self.hardware.calls, [])

    def test_valid_upload_adds_source_without_starting_hardware(self):
        status, _, raw = self.request('POST', '/api/upload', b'RIFF-test-WAVE-valid',
                                      headers={'Content-Type': 'audio/wav', 'X-Filename': 'test%20file.wav'})
        self.assertEqual(status, 201)
        self.assertEqual(json.loads(raw)['source_id'], 'upload-fixture')
        self.assertEqual(self.store.upload_calls[0][0], 'test file.wav')
        self.assertEqual(self.hardware.calls, [])

    def test_config_and_error_responses_do_not_enable_cross_origin_reads(self):
        status, headers, raw = self.request('GET', '/api/config')
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(raw)['csrf_token'], self.app.token)
        self.assertNotIn('Access-Control-Allow-Origin', headers)
        self.assertEqual(headers['X-Content-Type-Options'], 'nosniff')
        self.assertIn("frame-ancestors 'none'", headers['Content-Security-Policy'])


class RestoreChronology(unittest.TestCase):
    class Store(FakeStore):
        def __init__(self):
            super().__init__(baseline=False)
            self.restored = []

        def restore_capture(self, path):
            manifest = json.loads(Path(path).read_text(encoding='utf-8'))
            if manifest.get('invalid_validation'):
                raise ValueError('Injected raw capture verification failure')
            result_id = manifest['result_id']
            self.restored.append(result_id)
            self.result_captures[result_id] = manifest
            self.latest[(manifest['record_id'], manifest['threshold'])] = result_id
            return result_id

    def test_recorded_time_with_timezone_wins_over_reverse_lexical_job_folders(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cases = [('z-old', '2026-10-04T03:30:00+02:00', 49, 'old'),
                     ('m-middle', '2026-10-04T01:45:00Z', 50, 'middle'),
                     ('a-new', '2026-10-03T22:15:00-04:00', 51, 'new')]
            for folder, timestamp, epoch, result_id in cases:
                path = root / 'captures' / folder
                path.mkdir(parents=True)
                value = {'result_id': result_id, 'record_id': 'fixture', 'threshold': 10000000,
                         'physical_metadata': {'recorded_at': timestamp, 'epoch': epoch}}
                (path / 'capture.json').write_text(json.dumps(value), encoding='utf-8')
            store = self.Store()
            app = App(store, None, root)
            try:
                self.assertEqual(store.restored, ['old', 'middle', 'new'])
                self.assertEqual(store.latest[('fixture', 10000000)], 'new')
                self.assertEqual(app.restore_errors, [])
            finally:
                app.queue.close()

    def test_epoch_breaks_equal_instant_tie_and_invalid_manifests_remain_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            entries = [('z-epoch-low', {'recorded_at': '2026-10-04T02:15:00+00:00', 'epoch': 51}, False),
                       ('a-epoch-high', {'recorded_at': '2026-10-03T22:15:00-04:00', 'epoch': 52}, False),
                       ('invalid-time', {'recorded_at': '2026-10-04T02:15:00', 'epoch': 53}, False),
                       ('invalid-raw', {'recorded_at': '2026-10-04T02:20:00Z', 'epoch': 54}, True)]
            for folder, meta, invalid in entries:
                path = root / 'captures' / folder
                path.mkdir(parents=True)
                value = {'result_id': folder, 'record_id': 'fixture', 'threshold': 10000000,
                         'physical_metadata': meta, 'invalid_validation': invalid}
                (path / 'capture.json').write_text(json.dumps(value), encoding='utf-8')
            malformed = root / 'captures' / 'invalid-json'
            malformed.mkdir()
            (malformed / 'capture.json').write_text('not json', encoding='utf-8')
            store = self.Store()
            app = App(store, None, root)
            try:
                self.assertEqual(store.restored, ['z-epoch-low', 'a-epoch-high'])
                self.assertEqual(store.latest[('fixture', 10000000)], 'a-epoch-high')
                self.assertEqual({Path(e['path']).parent.name for e in app.restore_errors},
                                 {'invalid-time', 'invalid-raw', 'invalid-json'})
            finally:
                app.queue.close()


if __name__ == '__main__':
    unittest.main()
