"""Evidence and display contracts; no hardware calls or new-physical claims."""
import io
import json
from pathlib import Path
import struct
import sys
import tempfile
import unittest
import wave

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from data import (CaptureStore, DELAY, FRAMES, HOP, NS, NY, RATE, make_wav,
                  packet_sizes, sha_bytes, shared_audio_gain, validate_header, waveform_envelopes)


class PhysicalCaptureContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.store = CaptureStore(output_root=Path(cls.tmp.name))

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_catalog_four_natural_eight_controls(self):
        records = self.store.catalog()['records']
        self.assertEqual(len(records), 12)
        self.assertEqual(sum(r['kind'] == 'natural' for r in records), 4)
        self.assertTrue(all(r['thresholds'] == [0, 10000000] for r in records))
        self.assertTrue(all(r['attribution'] for r in records))

    def test_all_24_selected_actual_cases_have_exact_full_gold(self):
        for info in self.store.catalog()['records']:
            for threshold in (0, 10000000):
                with self.subTest(record=info['id'], threshold=threshold):
                    c = self.store.get_capture(info['id'], threshold)
                    self.assertTrue(c['full_reference_exact'])
                    self.assertEqual(c['mode'], 'archived_physical')
                    self.assertEqual(c['spectra'].shape, (len(c['original']) // HOP + 1, 129))
                    if threshold == 0:
                        np.testing.assert_array_equal(c['original'], c['processed'])

    def test_missing_threshold_never_falls_back_to_software(self):
        with self.assertRaisesRegex(KeyError, 'No physical capture'):
            self.store.bundle('synthetic_weak32', 100000000)

    def test_bundle_time_axes_and_exact_causal_event(self):
        b = self.store.bundle('synthetic_weak32', 10000000)
        self.assertAlmostEqual(b['spectra']['frame_end_seconds'][0], 128 / RATE)
        self.assertAlmostEqual(b['monitor']['after']['ends'][0], 49 * 128 / RATE)
        self.assertAlmostEqual(b['monitor']['after']['events'][0]['time'], 2.4346666666666668)
        self.assertEqual(b['geometry']['reconstruction_delay_samples_removed'], DELAY)
        self.assertTrue(b['provenance']['full_reference_exact'])
        self.assertEqual(len(b['cpu_timing']['routes']), 4)
        self.assertTrue(all(len(r['trials_ms']) == 5 for r in b['cpu_timing']['routes']))
        json.dumps(b, allow_nan=False)

    def test_prefix_bytes_exclude_zero_tail(self):
        b = self.store.bundle('synthetic_weak32', 10000000)
        self.assertEqual(b['metrics']['dense_bytes'], 952 * (245760 // 128 + 1))
        self.assertEqual(b['metrics']['pcm16_bytes'], 245760 * 2)
        self.assertLess(b['metrics']['sparse_bytes'], b['metrics']['transaction_sparse_bytes'])
        self.assertEqual(b['metrics']['sparse_bytes'], sum(b['spectra']['after_packet_bytes']))

    def test_silence_stays_finite_and_invalid_centroid(self):
        b = self.store.bundle('synthetic_zero', 10000000)
        self.assertEqual(b['metrics']['waveform_nrmse_percent'], 0)
        self.assertFalse(any(b['monitor']['after']['valid']))
        self.assertEqual(b['monitor']['after']['events'], [])
        json.dumps(b, allow_nan=False)

    def test_wav_a_b_share_gain_and_difference_matches(self):
        b = self.store.bundle('synthetic_weak32', 10000000)
        arrays = {}
        for mode in ('original', 'processed', 'difference'):
            with wave.open(io.BytesIO(self.store.wav(b['result_id'], mode)), 'rb') as w:
                self.assertEqual((w.getframerate(), w.getsampwidth(), w.getnchannels()), (RATE, 2, 1))
                self.assertEqual(w.getnframes(), 245760)
                arrays[mode] = np.frombuffer(w.readframes(w.getnframes()), dtype='<i2').astype(np.int32)
        np.testing.assert_array_equal(arrays['original'] - arrays['processed'], arrays['difference'])

    def test_different_thresholds_do_not_change_original_audio_gain(self):
        a = self.store.bundle('synthetic_weak32', 0)
        b = self.store.bundle('synthetic_weak32', 10000000)
        self.assertEqual(a['audio']['shared_pcm16_gain'], 8)
        self.assertEqual(b['audio']['shared_pcm16_gain'], 8)
        self.assertEqual(self.store.wav(a['result_id'], 'original'), self.store.wav(b['result_id'], 'original'))

    def test_new_capture_verifier_can_check_actual_archived_bytes_without_relabeling(self):
        a = self.store.actuals[('synthetic_weak16', 10000000, 0)]
        got = self.store._transform(a['record_id'], a['threshold'], Path(a['actual_y_path']).read_bytes(),
                                    Path(a['actual_wire_path']).read_bytes(), Path(a['reply_header_path']).read_bytes(),
                                    a['physical_metadata'], a['timing'], 'archived_physical', 'test-only',
                                    verify_reference=True)
        self.assertTrue(got['full_reference_exact'])
        self.assertEqual(got['mode'], 'archived_physical')

    def test_corrupt_new_capture_rejected_before_any_evidence_directory(self):
        a = self.store.actuals[('synthetic_weak16', 10000000, 0)]
        wire = bytearray(Path(a['actual_wire_path']).read_bytes())
        wire[64] ^= 1
        meta = {**a['physical_metadata'], 'input_sha256': self.store.record(a['record_id'])['input_sha256']}
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / 'must-not-exist'
            with self.assertRaisesRegex(ValueError, 'exact full PC reference'):
                self.store.register_capture(a['record_id'], a['threshold'], Path(a['actual_y_path']).read_bytes(),
                                            bytes(wire), Path(a['reply_header_path']).read_bytes(),
                                            meta, a['timing'], target)
            self.assertFalse(target.exists())

    def test_header_epoch_and_source_are_not_assumed(self):
        a = self.store.actuals[('synthetic_zero', 0, 0)]
        args = (Path(a['reply_header_path']).read_bytes(), Path(a['actual_y_path']).read_bytes(),
                Path(a['actual_wire_path']).read_bytes())
        with self.assertRaisesRegex(ValueError, 'epoch'):
            validate_header(*args, {**a['physical_metadata'], 'epoch': 99999}, a['timing'])
        with self.assertRaisesRegex(ValueError, 'FPGA identity'):
            validate_header(*args, {**a['physical_metadata'], 'source_id': '0' * 64}, a['timing'])

    def test_truncated_packet_fails_bounded_parser(self):
        c = self.store.get_capture('synthetic_zero', 0)
        with self.assertRaises(ValueError):
            packet_sizes(c['sparse'][:-1], len(c['spectra']))

    def test_restored_capture_stays_archived_and_detects_file_change(self):
        # Exercise persistence with real archived bytes; do not call this a new run.
        a = self.store.actuals[('synthetic_zero', 0, 0)]
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            actual = {'y.i32le': Path(a['actual_y_path']).read_bytes(),
                      'sparse.tsp1': Path(a['actual_wire_path']).read_bytes(),
                      'reply.bin': Path(a['reply_header_path']).read_bytes()}
            for name, value in actual.items():
                (folder / name).write_bytes(value)
            meta = {**a['physical_metadata'], 'input_sha256': self.store.record(a['record_id'])['input_sha256']}
            manifest = {'schema': 'trecap-visualizer-physical-capture-v1', 'status': 'PASS_EXACT_ACTUAL_CAPTURE',
                        'result_id': 'live-test-archived-fixture', 'record_id': a['record_id'], 'threshold': 0,
                        'input_sha256': meta['input_sha256'], 'physical_metadata': meta, 'timing': a['timing'],
                        'sha256': {str(folder / name): sha_bytes(value) for name, value in actual.items()}}
            path = folder / 'capture.json'
            path.write_text(json.dumps(manifest), encoding='utf-8')
            result_id = self.store.restore_capture(path)
            try:
                self.assertEqual(self.store.result_captures[result_id]['mode'], 'archived_physical')
                self.assertTrue(self.store.result_captures[result_id]['full_reference_exact'])
                (folder / 'reply.bin').write_bytes(b'changed')
                with self.assertRaisesRegex(ValueError, 'Changed evidence'):
                    self.store.restore_capture(path)
            finally:
                self.store.latest.pop((a['record_id'], 0), None)
                self.store.result_captures.pop(result_id, None)


class AudioMath(unittest.TestCase):
    def test_single_gain_prevents_difference_clipping(self):
        original = np.array([-2048, 2047], dtype=np.int32)
        processed = np.array([2047, -2048], dtype=np.int32)
        gain = shared_audio_gain(original, processed)
        self.assertEqual(gain, 8)
        for a in (original, processed, original - processed):
            self.assertGreater(len(make_wav(a, gain)), 44)

    def test_no_independent_peak_normalization(self):
        original = np.array([0, 1024], dtype=np.int32)
        processed = np.array([0, 512], dtype=np.int32)
        gain = shared_audio_gain(original, processed)
        self.assertEqual(gain, 8)
        got = waveform_envelopes(original, processed, points=2)
        self.assertEqual(got['before_max'][1], 0.5)
        self.assertEqual(got['after_max'][1], 0.25)


class UserUpload(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.store = CaptureStore(output_root=Path(cls.tmp.name))

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_upload_preserves_level_and_trims_playback_duration(self):
        stream = io.BytesIO()
        with wave.open(stream, 'wb') as w:
            w.setnchannels(2)
            w.setsampwidth(2)
            w.setframerate(12000)
            # Stereo mean is .25 full scale, without normalizing it to unity.
            x = np.tile(np.array([16384, 0], dtype='<i2'), (16001, 1))
            w.writeframes(x.tobytes())
        with tempfile.TemporaryDirectory() as tmp:
            self.store.output_root = Path(tmp)
            rid = self.store.register_wav('../local-example.wav', stream.getvalue())
            try:
                entry = self.store.record(rid)
                pcm = self.store.pcm(rid)
                self.assertEqual(entry['audio_ns'], 64004)
                self.assertEqual(entry['original_ns'] % 128, 0)
                self.assertEqual(entry['original_ns'] - entry['audio_ns'], 124)
                self.assertTrue(np.all(pcm[entry['audio_ns']:] == 0))
                self.assertAlmostEqual(float(np.mean(pcm[200:60000])), 512, delta=1)
                self.assertAlmostEqual(self.store._record_info(rid)['duration_seconds'], 16001 / 12000)
                self.assertEqual(entry['source']['source']['source_title'], 'local-example.wav')
                self.assertEqual(entry['preprocessing']['clipped_samples'], 0)
                restored = CaptureStore(output_root=Path(tmp))
                self.assertEqual(restored.record(rid)['audio_ns'], 64004)
                np.testing.assert_array_equal(restored.pcm(rid), pcm)
                with self.assertRaisesRegex(KeyError, 'No physical capture'):
                    self.store.bundle(rid, 0)
            finally:
                self.store.records.pop(rid, None)

    def test_short_upload_fails_before_creating_input(self):
        stream = io.BytesIO()
        with wave.open(stream, 'wb') as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(48000)
            w.writeframes(np.zeros(4800, dtype='<i2').tobytes())
        with tempfile.TemporaryDirectory() as tmp:
            self.store.output_root = Path(tmp)
            with self.assertRaisesRegex(ValueError, 'duration'):
                self.store.register_wav('short.wav', stream.getvalue())
            self.assertEqual(list(Path(tmp).iterdir()), [])


if __name__ == '__main__':
    unittest.main()
