# RF file adapter v1

This extension accepts unsigned eight-bit interleaved I/Q from a saved file. It produces real signed 12-bit samples for the existing T-RECAP input. This is a source adapter, not a new FFT or a demodulator. Clock domain crossing, transport and board registers are outside this block.

## Ports and transaction

Module `trecap_rf_iq_adapter` uses one `clk`, active-low asynchronous `rst_n`, and synchronous `clear_i` which aborts the current transaction and clears its history and status.

- `start_valid_i`, `start_ready_o` start handshake. `pair_count_i[31:0]` must be 1 through MAX_PAIRS (default 96000). `gain_shift_i[1:0]` is latched at admission. An invalid count sets `config_error_o` until clear and accepts no samples. A valid new start clears previous transaction counters. Busy transactions cannot accept another start.
- `iq_valid_i`, `iq_ready_o`, `iq_i_i[7:0]`, `iq_q_i[7:0]` transfer a pair. Hold both bytes while stalled. The count determines the end of the file. No input last marker is required.
- `sample_valid_o`, `sample_ready_i`, signed `sample_data_o[11:0]`, `sample_index_o[31:0]`, `sample_last_o`, `sample_clipped_o` transfer real samples. All payload and valid remain stable while stalled. Exactly 4 times pair_count samples are emitted, indexed from zero.
- `busy_o` covers an admitted transaction until its last output handshake. `done_o` pulses for one cycle on that last handshake. Done means adapter completion only, not downstream FFT completion.
- `input_count_o`, `output_count_o`, `clip_count_o` count accepted input pairs, accepted output samples and accepted clipped outputs. `clip_sticky_o` records any accepted clipped output. Clear and an accepted valid start reset counters.
- All ready and valid outputs are low during reset or clear. A configuration error blocks subsequent start until clear. There is no internal timeout for a stalled host or sink.

## Arithmetic

For each CU8 component b, signed internal value d = 2*b - 255. This represents the normalized input d/256. File tails use exact signed zero inside the block, never byte 127 or 128.

The prototype filter is `4 * scipy.signal.firwin(81, 0.25, window=('kaiser', 8.6))`. Stored coefficients are signed 18-bit integers, nearest ties-to-even quantization at 16 fractional bits. Four polyphase branches use coefficients h[4*k+p] for k 0 through 20. Positions beyond index80 are zero. A single shared multiply-accumulate datapath selects the I history for even phases and Q for odd phases. Accumulation is signed36, without intermediate rounding.

Phase signs are +I, -Q, -I, +Q. Round once after mixing to nearest integer, ties away from zero. The arithmetic divisor is 2^(16-gain_shift), equivalent to normalized-input gain 256*2^gain_shift. Gain1 gives512 counts per normalized unit and guarantees no clipping for the fixed coefficients and all CU8 inputs. Gain2 gives1024 counts and can clip an adversarial input. Saturate to [-2048,2047] and report clipping. There is no per-file peak normalization and no implicit gain default on the configuration port.

History begins at zero. Process the N admitted pairs followed by10 exact-zero pairs. Discard the first40 causal FIR outputs. Emit the next4*N. This produces the centered finite-file alignment of the prototype interpolation, including its zero boundary assumption. The mixer phase advances once per produced causal sample, including discarded startup samples. It freezes on output backpressure.

The sample rate metadata becomes4*Fs_IQ and the real intermediate-frequency center isFs_IQ. These describe the signal samples, not a sustainable processing throughput claim. The sequential implementation is intended for buffered file operation.

## Integration

Connect the adapter output to `trecap_pcm_stream_top`'s PCM ready/valid port in a dedicated RF application wrapper. The original finite profile expects384000 real samples. A file wrapper must pad after the4*N valid samples to that count, or explicitly configure and validate another finite geometry. The RF block itself does not emit that extra transaction padding. Do not feed arbitrary complex I/Q directly into the real-input FFT or reinterpret TSP1 power values as phase-preserving I/Q.

The existing global source-mode enum and TSH2 register ABI remain unchanged. The integrated TRF1 board interface identifies the RF profile and explicitly admits CU8 payloads. An old audio deployment must not accept raw I/Q as PCM.
