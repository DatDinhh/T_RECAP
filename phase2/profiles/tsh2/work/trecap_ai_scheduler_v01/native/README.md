# Native scheduler reference

`build01/trecap_scheduler.dll` is a Windows x64 DLL built with MSVC C++20 `/O2 /GL- /LTCG:OFF`. It includes the existing CPU02 arithmetic and coefficient loader unchanged and links the existing TSP1 codec and consumer unchanged. It does not set thread affinity, touch hardware, or load an AI model.

```python
from native_api import Native

# Construct outside timed intervals. pcm is contiguous, aligned NumPy int32.
with Native(coefficient_directory, max_samples=3072000) as engine:
    result = engine.run_full(pcm, 100000000)
    y, wire, bands = result['y'], result['wire'], result['bands']
    spectral_bands = engine.run_spectral(pcm, 100000000)
    decoded_bands = engine.decode(wire, 100000000, len(bands))
```

Every method returns copied outputs; timing the Python call includes those copies and wrapper checks. Existing input arrays and immutable `bytes` are passed directly to native code. Construct input arrays, contexts and packet bytes before a compute timing interval. The native entry points contain no timers.

An input is an independent finite epoch containing signed12 samples in int32 storage. Length must be a positive multiple of128, no greater than the context capacity. Capacity is at most5,760,000 samples (120seconds at48kHz). Threshold is an unsigned56 integer. A length of `Ns` produces `Ns/128+1` spectral frames and `Ns+512` full waveform samples. The existing zero extension, initial zero state and384-sample signal delay are preserved. Splitting a recording into independent calls resets filter state; it is not equivalent to one continuous epoch.

`run_full` computes FFT, threshold, IFFT/overlap-add, sparse TSP1 serialization and16band accumulation. `run_spectral` computes only FFT, threshold and16band accumulation; it does not reconstruct or serialize packets. `decode` validates the complete TSP1 stream and consumes either dense or sparse packets into identical16bands. Band assignment is `floor(16*k/129)`; canonical squared magnitude is weighted1 for DC/Nyquist and2 otherwise. Each returned band array has shape `(frames,16)` and dtype uint64.

The strict decoder checks headers, version/configuration, payload lengths, frame order, expected threshold, protected DC, sparse index order, mask legality, padding, checksums and total stream length. Invalid native calls invalidate all prior native outputs. A Python argument-type rejection happens before a native call and raises an exception. Recovery by a subsequent valid call is supported.

The C API exports `tsa_create`, `tsa_full`, `tsa_spectral`, `tsa_decode`, `tsa_features`, `tsa_frames`, `tsa_y`, `tsa_y_count`, `tsa_tsp1`, `tsa_tsp1_bytes`, `tsa_error`, `tsa_destroy` and `tsa_version`. ABI version is65536. Full/spectral arguments are `(context, int32_input, uint64_samples, uint64_threshold)`; decode arguments are `(context, byte_input, uint64_bytes, uint64_expected_frames, uint64_threshold)`. Processing returns0 on success and-1 on failure. Getters expose context-owned memory until the next call or destruction; use only valid handles returned by `tsa_create`. One context must not be used concurrently. Python copies remain valid across later calls and close.

Build command is recorded verbatim in `build01/build_command.txt`; `build.ps1` requires a fresh output directory and leaves all frozen source files unchanged. Qualification command:

```powershell
python 'work/trecap_ai_scheduler_v01/native/qualify.py'
```

`build01/qualification.json` binds the DLL, compiled sources, Python wrapper, fixtures and existing physical evidence. It confirms exact full waveform/TSP1 matches against actual8-second FPGA captures at thresholds0 and100000000, matching bands in all routes, two1024-sample reference cases,20 invalid-input/packet checks, recovery and unchanged thread affinity. A64-second repeated-flute case establishes software consistency only. This qualification adds no hardware result, AI accuracy result or performance measurement.
