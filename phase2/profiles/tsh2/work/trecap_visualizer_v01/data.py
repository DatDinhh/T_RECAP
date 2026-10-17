"""Hash-bound physical capture adapter for the local TSH2 visualizer.

Public API (no hardware access):
    store = CaptureStore()
    store.catalog(); store.record(record_id); store.pcm(record_id, padded=True)
    record_id = store.register_wav(filename, wav_bytes)
    bundle = store.bundle(record_id, threshold, trial=0)
    store.get_bundle(bundle['result_id']); store.wav(result_id, mode)
    result_id = store.register_capture(record_id, threshold, y_bytes, wire_bytes,
        reply_header, physical_metadata, timing, capture_dir)
    store.restore_capture(capture_manifest_path)  # after restarting the app

Only admitted physical captures can populate spectra/audio. Software full DSP is
used solely as an exact verifier, outside every displayed timer. Frame time is
the end of the input window: frame 0 ends at sample 128 and has a zero left half.
The consumer ends are taken unchanged from the frozen causal monitor.
"""
from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import math
from pathlib import Path
import struct
import sys
import threading
import time
import uuid
import wave

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
NS, NY, FRAMES, RATE, HOP, DELAY = 384000, 384512, 3001, 48000, 128, 384
SOURCE_ID = '39db0fdf3d451dfbf2d878575725cedd3df450980b40b2a742620dfb76a1a8ed'
SOF_SHA = 'f96bc5a35adf08711a5f392baf9f8cbf5ec65a17211a58117bdb53f62acbb7ab'
SERVICE_SHA = 'e1e762c820ec8054864cea687f27d3299ba51d6616759fb7fce82ee93e8511ea'
DEFAULT_CAPTURES = ROOT / 'outputs/trecap_monitor_board_v01/captures01/index.json'
COEFF = ROOT / 'outputs/trecap_stream8_v01/fixtures02/coefficients'


def need(ok, message):
    if not ok:
        raise ValueError(message)


def sha_bytes(value):
    return hashlib.sha256(value).hexdigest()


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    got = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(got)
    return got


def validate_header(header, y_bytes, wire_bytes, meta, timing):
    """Check the successful finite service response; never infer success."""
    need(isinstance(header, bytes) and len(header) == 40, 'Exact 40-byte service response required')
    magic, status, ny, nw, epoch, wall, cpu = struct.unpack('<IIIIQQQ', header)
    need(magic == 0x31535254 and status == 0, 'Unsuccessful physical service response')
    need(ny == NY * 4 == len(y_bytes), 'Full reconstructed sample geometry required')
    need(nw == len(wire_bytes) and 48 * FRAMES <= nw <= 1080 * FRAMES, 'Spectral byte geometry')
    need(epoch > 0 and epoch == meta['epoch'], 'Physical epoch binding')
    need(wall > 0 and cpu > 0, 'Positive physical service intervals')
    need(wall == timing['board_wall_ns'] and cpu == timing['board_thread_cpu_ns'], 'Service timing/header binding')
    need(timing['host_roundtrip_ns'] > 0, 'Positive observed host interval')
    need(meta['source_id'] == SOURCE_ID and meta['sof_sha256'] == SOF_SHA, 'Qualified unchanged FPGA identity required')
    need(meta['service_sha256'] == SERVICE_SHA and bool(meta['boot_id']), 'Qualified service and observed boot identity required')
    need(meta.get('gold_uploaded') is False, 'PC-only golden output policy')
    return {'epoch': epoch, 'y_bytes': ny, 'wire_bytes': nw, 'board_wall_ns': wall,
            'board_thread_cpu_ns': cpu}


def packet_sizes(wire, count):
    """Bounded geometry helper; Native.prepare performs semantic/checksum checks."""
    sizes, offset = [], 0
    for frame in range(count):
        need(offset + 48 <= len(wire), 'Truncated TSP1 header')
        need(wire[offset:offset + 4] == b'TSP1', 'TSP1 magic')
        need(struct.unpack_from('<Q', wire, offset + 16)[0] == frame, 'TSP1 frame sequence')
        payload = struct.unpack_from('<I', wire, offset + 12)[0]
        size = (48 + payload + 7) & ~7
        need(size <= 1080 and offset + size <= len(wire), 'TSP1 packet extent')
        sizes.append(size)
        offset += size
    return sizes, offset


def waveform_envelopes(original, processed, points=1200):
    """Min/max envelopes preserve visible transients; all paths use scale 2048."""
    need(original.shape == processed.shape and original.ndim == 1, 'Aligned waveform pair')
    edges = np.linspace(0, len(original), min(points, len(original)) + 1, dtype=np.int64)
    result = {'times_seconds': ((edges[:-1] + edges[1:] - 1) / (2 * RATE)).tolist()}
    for name, values in (('before', original), ('after', processed),
                         ('difference', original.astype(np.int64) - processed.astype(np.int64))):
        result[name + '_min'] = [float(values[a:b].min()) / 2048 for a, b in zip(edges[:-1], edges[1:])]
        result[name + '_max'] = [float(values[a:b].max()) / 2048 for a, b in zip(edges[:-1], edges[1:])]
    return result


def shared_audio_gain(original, processed):
    """Fixed 8x conversion across every recording, threshold and audio mode.

    Both signals are signed12. Their maximum possible difference is4095, so8x
    fits PCM16 without clipping. No result-dependent normalization is allowed.
    """
    need(np.all((original >= -2048) & (original <= 2047)), 'Original playback must be signed12')
    need(np.all((processed >= -2048) & (processed <= 2047)), 'Reconstructed playback must be signed12')
    return 8.0


def make_wav(samples, gain):
    values = np.rint(np.asarray(samples, dtype=np.float64) * gain)
    need(np.all((values >= -32768) & (values <= 32767)), 'Shared audio gain must prevent clipping')
    stream = io.BytesIO()
    with wave.open(stream, 'wb') as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(RATE)
        out.writeframes(values.astype('<i2').tobytes())
    return stream.getvalue()


class CaptureStore:
    """Validated, in-memory demo cache. Lock covers native contexts and timing.

    Initial admission verifies the historical manifests, source hashes, raw
    headers and all 48 capture hashes. Selected captures additionally receive
    strict codec checks and full equality checks against registered PC gold.
    Missing thresholds raise KeyError and never synthesize a hardware result.
    """

    def __init__(self, capture_path=DEFAULT_CAPTURES, output_root=None):
        self.lock = threading.RLock()
        self.audit = module('visualizer_physical_audit', ROOT / 'work/trecap_monitor_board_v01/analyze.py')
        self.mon, self.Native = self.audit.imports()
        contract = self.audit.load_contract(Path(capture_path))
        self.manifest, self.inputs, _, _, self.gold, actuals = contract
        self.records = {r['id']: r for r in self.inputs['records']}
        self.actuals = {(c['record_id'], int(c['threshold']), int(c['trial_index'])): c for c in actuals.values()}
        self.captures, self.bundles, self.result_captures = {}, {}, {}
        self.latest = {}
        self.capture_index_hash = self.audit.sha(capture_path)
        self.output_root = Path(output_root or ROOT / 'outputs/trecap_visualizer_v01')
        for record_id in self.records:
            self.pcm(record_id, padded=True)
        qualification_path = ROOT / 'work/trecap_ai_scheduler_v01/native/build01/qualification.json'
        qualification = read_json(qualification_path)
        need(qualification['status'] == 'PASS_EXACT_NATIVE_FULL_SPECTRAL_AND_DECODE', 'Qualified full DSP verifier')
        need(self.audit.sha(qualification['dll']) == qualification['dll_sha256'], 'Full DSP verifier DLL changed')
        self.audit.verify(qualification['evidence_sha256'])
        self.FullNative = module('visualizer_full_reference', ROOT / 'work/trecap_ai_scheduler_v01/native/native_api.py').Native
        uploads = self.output_root / 'uploads'
        if uploads.exists():
            for manifest in sorted(uploads.glob('upload-*/record.json')):
                entry = read_json(manifest)
                need(entry['id'] == manifest.parent.name and entry['kind'] == 'uploaded', 'Restored upload identity')
                need(Path(entry['input_i32le']).resolve() == (manifest.parent / 'input.i32le').resolve(), 'Restored upload input location')
                need(Path(entry['source']['pcm']).resolve() == (manifest.parent / 'original.npy').resolve(), 'Restored upload PCM location')
                self.records[entry['id']] = entry
                self.pcm(entry['id'])

    def record(self, record_id):
        if record_id not in self.records:
            raise KeyError('Unknown registered recording')
        return self.records[record_id]

    def pcm(self, record_id, padded=True):
        entry = self.record(record_id)
        self.audit.verify({entry['input_i32le']: entry['input_sha256'],
                           entry['source']['pcm']: entry['source']['sha256']})
        x = np.fromfile(entry['input_i32le'], dtype='<i4')
        original = np.load(entry['source']['pcm'], allow_pickle=False)
        ns = entry['original_ns']
        need(x.shape == (NS,) and original.shape == (ns,), 'Registered input geometry')
        need(original.dtype == np.dtype('<i4') and np.array_equal(x[:ns], original), 'Exact original input prefix')
        need(np.all(x[ns:] == 0) and np.all((x >= -2048) & (x <= 2047)), 'Signed12 PCM and only zero tail')
        return x if padded else original.copy()

    def _record_info(self, record_id):
        e = self.record(record_id)
        src = e['source'].get('source', {})
        attribution = {k: src[k] for k in ('source_title', 'source_url', 'creator', 'source_license',
                                           'official_attribution_line', 'url') if k in src}
        if e['kind'] == 'synthetic':
            attribution = {'source_title': 'Deterministic project test signal', 'source_license': 'Project-generated'}
        labels = {'synthetic_zero': 'Silence', 'synthetic_steady': 'Steady 1.5 kHz tone',
                  'synthetic_weak16': 'Added 9 kHz tone (amplitude 16)',
                  'synthetic_weak32': 'Added 9 kHz tone (amplitude 32)',
                  'synthetic_weak64': 'Added 9 kHz tone (amplitude 64)',
                  'synthetic_switch': 'Frequency switch: 1.5 to 3.75 kHz',
                  'synthetic_transient': 'Brief added tone (128 ms)',
                  'synthetic_offbin_noise': 'Off-bin tones plus noise'}
        return {'id': record_id, 'label': labels.get(record_id, e['category'].replace('_', ' ').title()), 'kind': e['kind'],
                'duration_seconds': e.get('audio_ns', e['original_ns']) / RATE,
                'original_samples': e.get('audio_ns', e['original_ns']), 'analysis_samples': e['original_ns'],
                'analysis_zero_pad_samples': e['original_ns'] - e.get('audio_ns', e['original_ns']),
                'attribution': attribution, 'expected_events': e['source'].get('expected_events', [])}

    def register_wav(self, filename, wav_bytes):
        """Import local 1.28--8 s WAV without normalizing; no synthetic FPGA output.

        Integer/float PCM, one to eight channels, is averaged to mono, resampled
        to 48 kHz, and rounded/saturated to signed12. Original resampled audio
        length is retained for playback; analysis adds at most 127 tail zeros.
        Both threshold-zero and selected-threshold physical captures are needed.
        Returns a record ID suitable for pcm() and the hardware request queue.
        """
        with self.lock:
            from scipy.io import wavfile
            from scipy.signal import resample_poly
            need(isinstance(wav_bytes, bytes) and 44 <= len(wav_bytes) <= 32 * 1024 * 1024, 'WAV upload size must be 44 bytes to 32 MiB')
            rate, samples = wavfile.read(io.BytesIO(wav_bytes))
            need(isinstance(rate, int) and 8000 <= rate <= 192000, 'Supported WAV sample rate is 8--192 kHz')
            need(samples.ndim in (1, 2), 'Mono or interleaved multichannel WAV')
            channels = 1 if samples.ndim == 1 else samples.shape[1]
            need(1 <= channels <= 8, 'One to eight input channels')
            need(1.28 <= len(samples) / rate <= 8.0, 'Demo WAV duration must be 1.28--8.0 seconds')
            if samples.dtype == np.uint8:
                normalized = (samples.astype(np.float64) - 128) / 128
            elif np.issubdtype(samples.dtype, np.signedinteger):
                normalized = samples.astype(np.float64) / 2 ** (8 * samples.dtype.itemsize - 1)
            elif np.issubdtype(samples.dtype, np.floating):
                normalized = samples.astype(np.float64)
            else:
                raise ValueError('Unsupported WAV PCM data type')
            need(np.all(np.isfinite(normalized)), 'WAV must contain finite samples')
            if normalized.ndim == 2:
                normalized = normalized.mean(axis=1)
            divisor = math.gcd(rate, RATE)
            resampled = resample_poly(normalized, RATE // divisor, rate // divisor, window=('kaiser', 5.0))
            quantized = np.rint(resampled * 2048)
            clipped = int(np.count_nonzero((quantized < -2048) | (quantized > 2047)))
            audio = np.clip(quantized, -2048, 2047).astype('<i4')
            audio_ns = len(audio)
            analysis_ns = ((audio_ns + HOP - 1) // HOP) * HOP
            need(analysis_ns <= NS, 'Resampled WAV exceeds eight-second transaction')
            original = np.zeros(analysis_ns, dtype='<i4')
            original[:audio_ns] = audio
            padded = np.zeros(NS, dtype='<i4')
            padded[:analysis_ns] = original
            record_id = 'upload-' + sha_bytes(original.tobytes())[:20]
            if record_id in self.records:
                return record_id
            folder = self.output_root / 'uploads' / record_id
            if folder.exists():
                entry = read_json(folder / 'record.json')
                need(entry['input_sha256'] == sha_bytes(padded.tobytes()), 'Existing upload identity')
                self.records[record_id] = entry
                self.pcm(record_id)
                return record_id
            folder.mkdir(parents=True)
            (folder / 'source.wav').write_bytes(wav_bytes)
            np.save(folder / 'original.npy', original, allow_pickle=False)
            (folder / 'input.i32le').write_bytes(padded.tobytes())
            display_name = Path(str(filename).replace('\\', '/')).name
            entry = {'id': record_id, 'category': Path(display_name).stem or 'Uploaded WAV', 'kind': 'uploaded',
                     'split': 'demo_only', 'original_ns': analysis_ns, 'audio_ns': audio_ns,
                     'transaction_ns': NS, 'zero_pad_samples': NS - analysis_ns,
                     'prefix_frames': analysis_ns // HOP + 1, 'input_i32le': str(folder / 'input.i32le'),
                     'input_sha256': sha_bytes(padded.tobytes()),
                     'source': {'id': record_id, 'category': display_name, 'kind': 'uploaded',
                                'pcm': str(folder / 'original.npy'), 'ns': analysis_ns,
                                'sha256': self.audit.sha(folder / 'original.npy'), 'clipped_samples': clipped,
                                'source': {'source_title': display_name, 'source_license': 'User-provided audio; no redistribution license inferred'}},
                     'preprocessing': {'source_rate': rate, 'source_channels': channels, 'source_sha256': sha_bytes(wav_bytes),
                                       'channel_mix': 'Arithmetic mono mean', 'resampling': 'scipy resample_poly Kaiser5 to 48000 Hz',
                                       'quantization': 'round to signed12 scale2048; saturate; no peak normalization',
                                       'clipped_samples': clipped, 'audio_ns': audio_ns, 'analysis_zero_pad_samples': analysis_ns - audio_ns}}
            (folder / 'record.json').write_text(json.dumps(entry, indent=2, allow_nan=False) + '\n', encoding='utf-8')
            self.records[record_id] = entry
            return record_id

    def catalog(self):
        records = []
        for record_id in self.records:
            info = self._record_info(record_id)
            info['thresholds'] = sorted({t for r, t, _ in self.actuals if r == record_id} |
                                        {t for r, t in self.latest if r == record_id})
            records.append(info)
        return {'schema': 'trecap-visualizer-catalog-v1', 'records': records,
                'geometry': {'sample_rate': RATE, 'fft': 256, 'hop': HOP, 'bin_hz': 187.5,
                             'transaction_samples': NS, 'transaction_seconds': 8},
                'capture_index_sha256': self.capture_index_hash,
                'dataset': {'name': 'ESC-50 held-out excerpt selection and synthetic controls',
                            'collection_license': 'CC BY-NC 3.0; per-recording attribution retained',
                            'pinned_commit': '33c8ce9eb2cf0b1c2f8bcf322eb349b6be34dbb6'},
                'scope': 'Actual physical captures. Playback is synchronized replay of complete finite captures; it is not live ADC input.'}

    def _transform(self, record_id, threshold, y_bytes, wire, header, meta, timing, mode, result_id,
                   gold=None, verify_reference=False):
        need(isinstance(threshold, int) and 0 <= threshold < 1 << 56, 'Unsigned56 threshold')
        validate_header(header, y_bytes, wire, meta, timing)
        original = self.pcm(record_id, padded=False)
        ns = len(original)
        y = np.frombuffer(y_bytes, dtype='<i4').copy()
        need(np.all((y >= -2048) & (y <= 2047)), 'Reconstructed output must retain signed12 range')
        if gold is not None:
            self.audit.verify({gold['y_i32le']: gold['y_sha256'],
                               gold['packets']['sparse']['path']: gold['packets']['sparse']['sha256']})
            need(y_bytes == Path(gold['y_i32le']).read_bytes(), 'Actual Y differs from registered full reference')
            need(wire == Path(gold['packets']['sparse']['path']).read_bytes(), 'Actual spectrum differs from registered full reference')
        if verify_reference:
            # Independent PC gold never enters the hardware request or UI data.
            with self.FullNative(COEFF, NS) as full_native:
                reference = full_native.run_full(self.pcm(record_id, padded=True), threshold)
            need(wire == reference['wire'] and np.array_equal(y, reference['y']), 'New actual capture fails exact full PC reference')
        with self.Native(COEFF, NS) as native:
            full = native.prepare(wire, threshold, FRAMES)
            _, end = packet_sizes(wire, FRAMES)
            need(end == len(wire), 'No trailing physical spectral bytes')
            sizes, end = packet_sizes(wire, ns // HOP + 1)
            prefix = wire[:end]
            prepared = native.prepare(prefix, threshold, ns // HOP + 1)
            need(np.array_equal(prepared['features'], full['features'][:ns // HOP + 1]), 'Exact physical prefix features')
        aligned = y[DELAY:DELAY + ns].copy()
        if threshold == 0:
            need(np.array_equal(original, aligned), 'Unthresholded actual reconstruction must equal input')
        monitor = self.mon.monitor(prepared['features'], ns)
        return {'result_id': result_id, 'record_id': record_id, 'threshold': threshold,
                'original': original, 'processed': aligned, 'spectra': prepared['spectra'],
                'features': prepared['features'], 'sparse': prefix, 'dense': prepared['wire'],
                'packet_sizes': sizes, 'monitor': monitor, 'physical_metadata': dict(meta),
                'timing': dict(timing), 'mode': mode, 'transaction_sparse_bytes': len(wire),
                'sha256': {'y': sha_bytes(y_bytes), 'wire': sha_bytes(wire), 'header': sha_bytes(header)},
                'full_reference_exact': gold is not None or verify_reference}

    def get_capture(self, record_id, threshold, trial=0):
        with self.lock:
            self.record(record_id)
            key = (record_id, int(threshold), int(trial))
            live_id = self.latest.get((record_id, int(threshold))) if trial == 0 else None
            if live_id:
                return self.result_captures[live_id]
            if key in self.captures:
                return self.captures[key]
            if key not in self.actuals:
                raise KeyError('No physical capture at this threshold; request a new board run')
            a = self.actuals[key]
            self.audit.verify(a['sha256'])
            wire = Path(a['actual_wire_path']).read_bytes()
            result_id = 'recorded-' + a['capture_id'] + '-' + sha_bytes(wire)[:10]
            capture = self._transform(record_id, int(threshold), Path(a['actual_y_path']).read_bytes(), wire,
                                      Path(a['reply_header_path']).read_bytes(), a['physical_metadata'], a['timing'],
                                      'archived_physical', result_id, gold=self.gold[a['case_id']])
            self.captures[key] = capture
            self.result_captures[result_id] = capture
            return capture

    def _cpu_timing(self, before, after):
        """Five short paired demo trials, not the formal 30-trial benchmark."""
        routes = [('original_dense', 'Original spectrum: dense + monitor', before, 'dense'),
                  ('processed_dense', 'Thresholded spectrum: dense + monitor', after, 'dense'),
                  ('processed_sparse', 'Thresholded spectrum: sparse + monitor', after, 'sparse'),
                  ('cpu_pcm_monitor', 'CPU PCM: FFT + threshold + monitor', after, 'pcm')]
        measured = {r[0]: [] for r in routes}
        expected = {r[0]: self.mon.serial(r[2]['monitor']) for r in routes}
        with self.Native(COEFF, NS) as native:
            for trial in range(-3, 5):
                order = routes if trial % 2 == 0 else routes[::-1]
                for route_id, _, capture, encoding in order:
                    start = time.perf_counter_ns()
                    if encoding == 'pcm':
                        features = native.run_pcm(capture['original'], capture['threshold'])
                    else:
                        features = native.decode(capture[encoding], capture['threshold'], len(capture['spectra']), encoding)
                    monitor = self.mon.monitor(features, len(capture['original']))
                    elapsed = time.perf_counter_ns() - start
                    need(self.mon.serial(monitor) == expected[route_id], 'Timed consumer output equality')
                    if trial >= 0:
                        measured[route_id].append(elapsed / 1e6)
        return {'routes': [{'id': rid, 'label': label, 'median_ms': float(np.median(measured[rid])),
                            'trials_ms': measured[rid]} for rid, label, _, _ in routes],
                'warmups': 3, 'trials': 5, 'every_output_checked': True,
                'scope': 'Warm-RAM laptop per original clip. Spectral routes: strict packet decode + native features + complete causal monitor. CPU PCM route: FFT + same threshold + features + monitor, without IFFT or packet generation. Excludes physical FPGA producer, transport, file IO, audio, visual rendering and context construction. Short demo timing, not a formal benchmark.',
                'comparison': 'Processed dense and sparse contain identical values. Original dense changes both signal values and threshold; no whole-system FPGA speedup is inferred.'}

    def build_bundle(self, after, before=None):
        with self.lock:
            before = before or self.get_capture(after['record_id'], 0)
            need(before['record_id'] == after['record_id'] and before['threshold'] == 0, 'Actual zero-threshold baseline required')
            need(np.array_equal(before['original'], after['original']), 'Same original PCM for comparison')
            original, processed = after['original'], after['processed']
            audio_ns = self.record(after['record_id']).get('audio_ns', len(original))
            audio_original, audio_processed = original[:audio_ns], processed[:audio_ns]
            error = np.linalg.norm(audio_processed.astype(float) - audio_original)
            norm = np.linalg.norm(audio_original.astype(float))
            nrmse = float(100 * error / norm) if norm else (0.0 if error == 0 else None)
            before_nonzero = np.count_nonzero(before['spectra'])
            after_nonzero = np.count_nonzero(after['spectra'])
            after_m = self.mon.serial(after['monitor'])
            before_m = self.mon.serial(before['monitor'])
            gain = shared_audio_gain(audio_original, audio_processed)
            result_id = after['result_id']
            bundle = {'schema': 'trecap-visualizer-result-v1', 'result_id': result_id,
                      'record': self._record_info(after['record_id']), 'threshold': after['threshold'],
                      'geometry': {'sample_rate': RATE, 'fft': 256, 'hop': HOP, 'bin_hz': 187.5,
                                   'reconstruction_delay_samples_removed': DELAY, 'transaction_samples': NS,
                                   'transaction_seconds': 8, 'zero_pad_samples': NS - len(original)},
                      'spectra': {'frame_end_seconds': ((np.arange(len(after['spectra'])) + 1) * HOP / RATE).tolist(),
                                  'frequencies_hz': (np.arange(129) * 187.5).tolist(),
                                  'before_power': before['spectra'].astype(float).tolist(),
                                  'after_power': after['spectra'].astype(float).tolist(),
                                  'after_packet_bytes': after['packet_sizes'],
                                  'display_precision': 'Raw fixed-point squared magnitude cast to JS double for display only; all verification uses exact uint64.',
                                  'time_scope': 'Input-window end times. Frame 0 has 128 leading zeros. Final flush frame ends 128 samples after the original clip.'},
                      'monitor': {'before': before_m, 'after': after_m},
                      'waveform': waveform_envelopes(audio_original, audio_processed),
                      'metrics': {'waveform_nrmse_percent': nrmse, 'sparse_bytes': len(after['sparse']),
                                  'dense_bytes': len(after['dense']), 'pcm16_bytes': audio_ns * 2,
                                  'packet_reduction_percent': 100 * (1 - len(after['sparse']) / len(after['dense'])),
                                  'sparse_over_pcm16': len(after['sparse']) / (audio_ns * 2),
                                  'retained_nonzero_fraction': after_nonzero / before_nonzero if before_nonzero else 1.0,
                                  'quality': self.mon.natural_quality(before['monitor'], after['monitor']),
                                  'transaction_sparse_bytes': after['transaction_sparse_bytes'],
                                  'byte_scope': 'Prefix through original duration, including one flush spectral frame. The separate 8-second transaction includes a zero tail.'},
                      'audio': {'sample_rate': RATE, 'shared_pcm16_gain': gain,
                                'normalization': 'Fixed 8x integer conversion for every recording, threshold and audio mode. No independent normalization or clipping.',
                                'original': '/api/results/' + result_id + '/audio/original',
                                'processed': '/api/results/' + result_id + '/audio/processed',
                                'difference': '/api/results/' + result_id + '/audio/difference'},
                      'provenance': {'mode': after['mode'], **after['physical_metadata'],
                                     'capture_sha256': after['sha256'], 'full_reference_exact': after['full_reference_exact'],
                                     'baseline_mode': before['mode'], 'baseline_capture_sha256': before['sha256'],
                                     'baseline_epoch': before['physical_metadata']['epoch'],
                                     'baseline_boot_id': before['physical_metadata']['boot_id'],
                                     'timing': after['timing'],
                                     'physical_timing_scope': 'Full padded 8-second finite transaction; service includes HPS PIO/feed/drain stalls. Host roundtrip also includes network. Neither is compute-only FPGA time.',
                                     'playback_scope': 'Time-synchronized playback after physical finite capture, not a live ADC or incremental FPGA stream.'},
                      'cpu_timing': self._cpu_timing(before, after)}
            bundle['metrics']['cpu_pcm_ms'] = next(r['median_ms'] for r in bundle['cpu_timing']['routes'] if r['id'] == 'cpu_pcm_monitor')
            # Strict JSON conversion is also a nonfinite guard before HTTP use.
            json.dumps(bundle, allow_nan=False)
            self.bundles[result_id] = bundle
            self.result_captures[result_id] = after
            return bundle

    def bundle(self, record_id, threshold, trial=0):
        with self.lock:
            latest = self.latest.get((record_id, int(threshold))) if trial == 0 else None
            capture = self.result_captures[latest] if latest else self.get_capture(record_id, int(threshold), trial)
            return self.get_bundle(capture['result_id'])

    def get_bundle(self, result_id):
        with self.lock:
            if result_id not in self.bundles:
                if result_id not in self.result_captures:
                    raise KeyError('Unknown completed physical result')
                self.build_bundle(self.result_captures[result_id])
            return self.bundles[result_id]

    def wav(self, result_id, mode):
        with self.lock:
            need(mode in ('original', 'processed', 'difference'), 'Known audio A/B mode')
            bundle = self.get_bundle(result_id)
            capture = self.result_captures[result_id]
            values = capture['original'] if mode == 'original' else capture['processed']
            if mode == 'difference':
                values = capture['original'].astype(np.int64) - capture['processed'].astype(np.int64)
            audio_ns = self.record(capture['record_id']).get('audio_ns', len(values))
            return make_wav(values[:audio_ns], bundle['audio']['shared_pcm16_gain'])

    def register_capture(self, record_id, threshold, y_bytes, wire_bytes, reply_header,
                         physical_metadata, timing, capture_dir):
        """Admit a new finite board result, retain raw evidence, and return its ID.

        Required metadata: boot_id, source_id, sof_sha256, service_sha256, epoch,
        gold_uploaded=False, input_sha256. Optional admission_sha256 maps receipt
        paths to hashes and is verified before admission. The hardware backend
        owns fresh board identity/isolation checks; this layer verifies data.
        """
        with self.lock:
            entry = self.record(record_id)
            need(physical_metadata.get('input_sha256') == entry['input_sha256'], 'New capture binds exact uploaded PCM')
            self.audit.verify(physical_metadata.get('admission_sha256', {}))
            result_id = 'live-' + record_id + '-t' + str(threshold) + '-' + uuid.uuid4().hex[:12]
            capture = self._transform(record_id, threshold, y_bytes, wire_bytes, reply_header,
                                      physical_metadata, timing, 'new_physical', result_id, verify_reference=True)
            folder = Path(capture_dir)
            need(not folder.exists(), 'New capture directory must preserve historical evidence')
            folder.mkdir(parents=True)
            raw = {'y.i32le': y_bytes, 'sparse.tsp1': wire_bytes, 'reply.bin': reply_header}
            for name, data in raw.items():
                (folder / name).write_bytes(data)
            manifest = {'schema': 'trecap-visualizer-physical-capture-v1', 'status': 'PASS_EXACT_ACTUAL_CAPTURE',
                        'result_id': result_id, 'record_id': record_id, 'threshold': threshold,
                        'physical_metadata': physical_metadata, 'timing': timing,
                        'input_sha256': entry['input_sha256'], 'full_reference_exact': True,
                        'adapter_source_sha256': self.audit.sha(Path(__file__)),
                        'sha256': {str(folder / k): sha_bytes(v) for k, v in raw.items()},
                        'verification_scope': 'Full 384512-sample Y and 3001 spectral frames exactly match PC-only reference; no reference bytes are used as physical output.'}
            (folder / 'capture.json').write_text(json.dumps(manifest, indent=2, allow_nan=False) + '\n', encoding='utf-8')
            capture['manifest_path'] = str(folder / 'capture.json')
            self.result_captures[result_id] = capture
            self.latest[(record_id, threshold)] = result_id
            return result_id

    def restore_capture(self, manifest_path):
        """Reload only a saved verified physical result; recheck actual raw data.

        A caller supplies its own capture-directory manifest list. No broad disk
        discovery or current-board access happens. Restored output is labeled as
        an archived physical capture, even if it was live in the prior session.
        Uploaded input records under this output_root are restored at startup.
        """
        with self.lock:
            path = Path(manifest_path)
            manifest = read_json(path)
            need(manifest['schema'] == 'trecap-visualizer-physical-capture-v1' and
                 manifest['status'] == 'PASS_EXACT_ACTUAL_CAPTURE', 'Completed saved physical result required')
            entry = self.record(manifest['record_id'])
            need(manifest['input_sha256'] == entry['input_sha256'], 'Saved capture input identity')
            expected = {str(path.parent / name) for name in ('y.i32le', 'sparse.tsp1', 'reply.bin')}
            need({Path(p).resolve() for p in manifest['sha256']} == {Path(p).resolve() for p in expected}, 'Saved raw paths stay within capture directory')
            self.audit.verify(manifest['sha256'])
            meta = manifest['physical_metadata']
            need(meta.get('input_sha256') == entry['input_sha256'], 'Saved upload/physical binding')
            self.audit.verify(meta.get('admission_sha256', {}))
            result_id = manifest['result_id']
            need(result_id.startswith('live-') and '/' not in result_id and '\\' not in result_id, 'Saved local result identifier')
            capture = self._transform(manifest['record_id'], manifest['threshold'],
                                      (path.parent / 'y.i32le').read_bytes(), (path.parent / 'sparse.tsp1').read_bytes(),
                                      (path.parent / 'reply.bin').read_bytes(), meta, manifest['timing'],
                                      'archived_physical', result_id, verify_reference=True)
            capture['manifest_path'] = str(path)
            self.result_captures[result_id] = capture
            self.latest[(manifest['record_id'], manifest['threshold'])] = result_id
            return result_id
