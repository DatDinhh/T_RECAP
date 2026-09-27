# IFFT exact-zero opportunity profile

This profile reproduces the current 256-point IFFT's bit-reversed load and iterative stage/base/j order. The recursive integer oracle supplies masked spectra and expected frame outputs. The profiler uses an independent ties-away rounding expression and checks every reconstructed complex frame exactly.

`case_summary.csv` gives whole-case counts and full-stream reconstruction error. `stage_counts.csv` aggregates each stage across frames; `frame_stage_counts.csv` supports direct comparison with an RTL transaction monitor. `frame_checks.csv` records every frame comparison and digest. `bin_masks.csv` preserves all unique-bin mask decisions, including protected DC and eligible Nyquist. Input and reconstructed output MEMH files are included with hashes in the manifest/tables.

The original measured multitone is accompanied by deterministic tonal, broadband, transient, and zero-control inputs. Synthetic inputs are defined by integer rules in `manifest.json`; they are stress cases, not a representative application corpus. Errors use the 384-sample-delayed, zero-padded input over the full output length.

`b_complex_zero` marks an exactly zero twiddle-multiplied operand. Its product is exactly zero, leaving butterfly outputs equal to a. `both_complex_zero` is a subset where both outputs also remain zero. Component-zero, axis-twiddle, and zero-real-product counts overlap these sets. A suppressed-bin percentage does not equal a skipped-butterfly percentage; values spread and cancel during later stages.

These are arithmetic opportunities, not energy savings or implemented skipped cycles. Any optimization still needs exact output/handshake/fault checks, synthesis/timing/resource comparison, and a matched board experiment at the same threshold and output quality. The FFT and other pipeline stages remain outside this IFFT profile.

Reproduce with `python profile_ifft_zeros.py --repo <repository> --out <new-directory>`; add `--no-plots` for standard-library-only operation. Plot generation additionally needs Matplotlib.
