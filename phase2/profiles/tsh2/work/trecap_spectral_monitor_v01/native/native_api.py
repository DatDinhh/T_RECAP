"""Exact monitor arithmetic. Every public result is copied before return.

Allocate context and read wire/PCM outside timers. decode() times strict packet
validation plus direct sparse/dense consumption and result copy. run_pcm() has
FFT/threshold/monitor with no IFFT or serialization. produce()/prepare() are
untimed input preparation, returning all spectra and encoded packets as copies.
"""
from pathlib import Path
import ctypes as C
import os
import numpy as np

COLUMNS = 21
FEATURE_COLUMNS = [*[f'band_{i}' for i in range(16)], 'total_power', 'weighted_bin_low64',
                   'peak_power', 'peak_bin_uint64_max_if_zero', 'weighted_bin_high64']

def load_library(path=None):
    lib = C.CDLL(str(path or Path(__file__).parent/'build01/trecap_monitor.dll'))
    p, u = C.c_void_p, C.c_uint64
    defs = {
        'tsm_version': ([], C.c_uint32), 'tsm_create': ([C.c_char_p,u],p),
        'tsm_decode': ([p,p,u,u,u,C.c_uint,C.c_int],C.c_int),
        'tsm_pcm': ([p,C.POINTER(C.c_int32),u,u,C.c_int],C.c_int),
        'tsm_matrix': ([p,C.POINTER(u),u],C.c_int),
        'tsm_features': ([p],C.POINTER(u)), 'tsm_spectra': ([p],C.POINTER(u)),
        'tsm_frames': ([p],u), 'tsm_wire': ([p],p), 'tsm_wire_bytes': ([p],u),
        'tsm_error': ([],C.c_char_p), 'tsm_destroy': ([p],None),
    }
    for name,(args,ret) in defs.items():
        fn=getattr(lib,name);fn.argtypes=args;fn.restype=ret
    if lib.tsm_version()!=0x10000: raise RuntimeError('ABI mismatch')
    return lib

class Native:
    def __init__(self,coeff_dir,max_samples,dll_path=None):
        if not isinstance(max_samples,int) or not 0<max_samples<=5760000 or max_samples%128:
            raise ValueError('max_samples must be positive multiple128 <=5760000')
        self.lib=load_library(dll_path)
        self.handle=self.lib.tsm_create(os.fsencode(coeff_dir),max_samples)
        if not self.handle: raise RuntimeError(self.lib.tsm_error().decode())
        self.max_samples=max_samples
    def close(self):
        if getattr(self,'handle',None): self.lib.tsm_destroy(self.handle);self.handle=None
    def __del__(self): self.close()
    def __enter__(self): return self
    def __exit__(self,*args): self.close()
    def _check(self,result):
        if result: raise RuntimeError(self.lib.tsm_error().decode())
    def _open(self):
        if not self.handle: raise RuntimeError('Context closed')
    def _thr(self,threshold):
        if not isinstance(threshold,(int,np.integer)) or not 0<=threshold<1<<56:
            raise ValueError('threshold must fit unsigned56')
        return int(threshold)
    def _features(self):
        n=self.lib.tsm_frames(self.handle)
        if not n: raise RuntimeError('No valid output')
        return np.ctypeslib.as_array(self.lib.tsm_features(self.handle),shape=(n*COLUMNS,)).reshape(n,COLUMNS).copy()
    def _prepared(self):
        n=self.lib.tsm_frames(self.handle)
        return {'features':self._features(),
                'wire':C.string_at(self.lib.tsm_wire(self.handle),self.lib.tsm_wire_bytes(self.handle)),
                'spectra':np.ctypeslib.as_array(self.lib.tsm_spectra(self.handle),shape=(n*129,)).reshape(n,129).copy()}
    def _decode(self,wire,threshold,frames,encoding,prepare):
        self._open();thr=self._thr(threshold)
        if not isinstance(wire,bytes): raise TypeError('wire must be preloaded bytes')
        if not isinstance(frames,(int,np.integer)) or not 0<frames<=self.max_samples//128+1:
            raise ValueError('frames outside context capacity')
        if encoding not in ('dense','sparse'): raise ValueError('encoding must be dense or sparse')
        self._check(self.lib.tsm_decode(self.handle,C.cast(C.c_char_p(wire),C.c_void_p),len(wire),int(frames),thr,
                                       int(encoding=='sparse'),int(prepare)))
    def decode(self,wire,threshold,frames,encoding='sparse'):
        self._decode(wire,threshold,frames,encoding,False)
        return self._features()
    def prepare(self,wire,threshold,frames,encoding='sparse'):
        """Outside timer: returns compact dense wire, dense matrix, and monitor outputs."""
        self._decode(wire,threshold,frames,encoding,True)
        return self._prepared()
    def dense_wire(self,wire,threshold,frames): return self.prepare(wire,threshold,frames)['wire']
    def decode_spectra(self,wire,threshold,frames,encoding='sparse'):
        return self.prepare(wire,threshold,frames,encoding)['spectra']
    def _pcm(self,pcm,threshold,produce):
        self._open();thr=self._thr(threshold)
        if not isinstance(pcm,np.ndarray) or pcm.dtype!=np.dtype('<i4') or pcm.ndim!=1 or not pcm.flags.c_contiguous or not pcm.flags.aligned:
            raise TypeError('pcm must be aligned contiguous one-dimensional int32')
        self._check(self.lib.tsm_pcm(self.handle,pcm.ctypes.data_as(C.POINTER(C.c_int32)),pcm.size,thr,int(produce)))
    def run_pcm(self,pcm,threshold):
        self._pcm(pcm,threshold,False)
        return self._features()
    def produce(self,pcm,threshold):
        """Outside timer: PCM FFT/threshold plus sparse packet and spectrum output."""
        self._pcm(pcm,threshold,True)
        return self._prepared()
    def consume_dense(self,spectra):
        self._open()
        if not isinstance(spectra,np.ndarray) or spectra.dtype!=np.dtype('<u8') or spectra.ndim!=2 or spectra.shape[1]!=129 or not spectra.flags.c_contiguous or not spectra.flags.aligned:
            raise TypeError('spectra must be aligned contiguous uint64 [frames,129]')
        self._check(self.lib.tsm_matrix(self.handle,spectra.ctypes.data_as(C.POINTER(C.c_uint64)),spectra.shape[0]))
        return self._features()
