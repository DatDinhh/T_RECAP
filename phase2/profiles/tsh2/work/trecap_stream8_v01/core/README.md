# Streaming PCM numerical-core overlay

`trecap_pcm_stream_top.sv` is derived by `prepare_top.py` from the frozen
`outputs/trecap_hps_transport_v01/core_overlay02/trecap_pcm_replay_top.sv`.
The inherited file header describes that historical wrapper; this overlay uses
the host stream FIFO in `trecap_pcm_stream_source.sv`, not a replay ROM.
The FFT, threshold, IFFT, WOLA, delay metrics, coefficient files, and observed
canonical-bin tap are unchanged from `outputs/trecap_hps_transport_v01/build01`.

The top defaults to 384000 input samples and a 256-entry signed 12-bit PCM FIFO.
Its `INPUT_SAMPLES` parameter also supports the 1024-sample reference regression.
`pcm_valid_i && pcm_ready_o` accepts one host sample only during an active epoch.
`pcm_accepted_count_o` counts those host acceptances. `pcm_fifo_level_o` counts
RAM-owned samples, excluding up to two elastic read/output entries. No input is
accepted before START or after the exact input count. There is no chunk marker
and no reset, discontinuity, or overlap clearing at a host pause.

The Revision-J formula is Nframes=floor((Ns+L-2)/H), tau_last=Nframes*H,
Ny=tau_last+G+L. With Ns=384000,L=256,H=128,G=128 this gives 3001 frames,
384128 analysis tokens, and 384512 Y samples. The source appends 128 analysis
zeros and 384 pure WOLA drain ticks. The existing exact-completion checks remain.

The exporter tap has no ready signal. `export_emitted_frames_i` must connect to
the exporter's epoch-local emitted-record counter, incremented only after the
last output-byte handshake. A new analysis hop starts only after the previous
hop's record has been completely emitted. This reserves at most one exporter
slot regardless of downstream stalls. Admission gates source valid/ready only;
the numerical core's enable must remain high during an active run. Gating its
enable can discard pending scheduler work and is not a backpressure mechanism.
Tail ticks produce no new frames and do not need exporter credit.

The enclosing adapter must consume Y with valid/ready, provide exporter output
backpressure, and service input and both outputs concurrently. If the host only
uploads all PCM before draining bounded output FIFOs, it can deadlock by design.

`verify_stream.py verification02` runs the actual numerical core against all 12
frozen excerpt/threshold/format cases. It checks every source token, full-tail Y,
canonical tap field, and TSP1 byte while independently pausing input, Y, and the
export stream. It also checks one-frame credit, one discontinuity per epoch,
FIFO-full coverage, and stable stalled outputs. Results bind source hashes.
The regression covers 1024-sample epochs; it does not establish full 384000-sample
simulation, FPGA fit/timing, HPS transport, or physical eight-second execution.
