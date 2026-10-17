"""Frozen-arithmetic CPU reference and strict TSP1 consumer. No affinity changes.

Returned arrays/bytes are copies. Context construction allocates buffers and loads
coefficients; do it outside timed intervals. Calls accept existing contiguous
int32 PCM arrays without copying the input. A context is not thread safe.
"""
from pathlib import Path
import ctypes as C
import os
import numpy as np


def load_library(path=None):
    lib = C.CDLL(str(path or Path(__file__).parent / 'build01/trecap_scheduler.dll'))
    ptr, u64 = C.c_void_p, C.c_uint64
    signatures = {
        'tsa_version': ([], C.c_uint32),
        'tsa_create': ([C.c_char_p, u64], ptr),
        'tsa_full': ([ptr, C.POINTER(C.c_int32), u64, u64], C.c_int),
        'tsa_spectral': ([ptr, C.POINTER(C.c_int32), u64, u64], C.c_int),
        'tsa_decode': ([ptr, ptr, u64, u64, u64], C.c_int),
        'tsa_features': ([ptr], C.POINTER(u64)),
        'tsa_frames': ([ptr], u64),
        'tsa_y': ([ptr], C.POINTER(C.c_int32)),
        'tsa_y_count': ([ptr], u64),
        'tsa_tsp1': ([ptr], ptr),
        'tsa_tsp1_bytes': ([ptr], u64),
        'tsa_error': ([], C.c_char_p),
        'tsa_destroy': ([ptr], None),
    }
    for name, (args, result) in signatures.items():
        fn = getattr(lib, name)
        fn.argtypes, fn.restype = args, result
    if lib.tsa_version() != 0x10000:
        raise RuntimeError('Native ABI version mismatch')
    return lib


class Native:
    def __init__(self, coeff_dir, max_samples, dll_path=None):
        if not isinstance(max_samples, int) or not 0 < max_samples <= 5760000 or max_samples % 128:
            raise ValueError('max_samples must be a positive multiple of128, at most5760000')
        self.lib = load_library(dll_path)
        self.handle = self.lib.tsa_create(os.fsencode(coeff_dir), max_samples)
        if not self.handle:
            raise RuntimeError(self.lib.tsa_error().decode('utf-8', errors='replace'))
        self.max_samples = max_samples

    def close(self):
        if getattr(self, 'handle', None):
            self.lib.tsa_destroy(self.handle)
            self.handle = None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def __del__(self):
        self.close()

    def _check(self, result):
        if result:
            raise RuntimeError(self.lib.tsa_error().decode('utf-8', errors='replace'))

    def _args(self, pcm, threshold):
        if not self.handle:
            raise RuntimeError('Context is closed')
        if not isinstance(pcm, np.ndarray) or pcm.dtype != np.dtype('<i4') or pcm.ndim != 1 or not pcm.flags.c_contiguous or not pcm.flags.aligned:
            raise TypeError('Input must be an aligned contiguous one-dimensional int32 NumPy array')
        if not isinstance(threshold, (int, np.integer)) or not 0 <= threshold < 1 << 56:
            raise ValueError('threshold must fit unsigned56')
        return self.handle, pcm.ctypes.data_as(C.POINTER(C.c_int32)), pcm.size, int(threshold)

    def _bands(self):
        frames = self.lib.tsa_frames(self.handle)
        if not frames:
            raise RuntimeError('No valid native output')
        return np.ctypeslib.as_array(self.lib.tsa_features(self.handle), shape=(frames * 16,)).reshape(frames, 16).copy()

    def run_full(self, pcm, threshold):
        self._check(self.lib.tsa_full(*self._args(pcm, threshold)))
        return {
            'y': np.ctypeslib.as_array(self.lib.tsa_y(self.handle), shape=(self.lib.tsa_y_count(self.handle),)).copy(),
            'wire': C.string_at(self.lib.tsa_tsp1(self.handle), self.lib.tsa_tsp1_bytes(self.handle)),
            'bands': self._bands(),
        }

    def run_spectral(self, pcm, threshold):
        self._check(self.lib.tsa_spectral(*self._args(pcm, threshold)))
        return self._bands()

    def decode(self, wire, threshold, frames):
        if not self.handle:
            raise RuntimeError('Context is closed')
        if not isinstance(wire, bytes):
            raise TypeError('wire must be bytes; construct it outside timed intervals')
        if not isinstance(threshold, (int, np.integer)) or not 0 <= threshold < 1 << 56:
            raise ValueError('threshold must fit unsigned56')
        if not isinstance(frames, (int, np.integer)) or not 0 < frames <= self.max_samples // 128 + 1:
            raise ValueError('frames outside allocated capacity')
        self._check(self.lib.tsa_decode(self.handle, C.cast(C.c_char_p(wire), C.c_void_p), len(wire), int(frames), int(threshold)))
        return self._bands()
