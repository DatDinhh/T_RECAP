# V3 finite core admission harness

Compile `filelists/rtl_core_plus_fft.f`, a run-local
`trecap_artifact_expectations_pkg.sv`, then
`sim/filelists/verification_core.f`. Select `core_finite_replay_tb` explicitly;
other production modules in the library are not simulation tops. `SYNTHESIS`
is forbidden, and production immediate assertions remain enabled. Simulation
working libraries and `modelsim.ini` belong to the unique run directory.

The package uses the `TEXP_*` geometry, threshold and aggregate constants listed
by `scripts/sim/trecap_artifact_scoreboard.py::render_header`. Its unused SHA
constants are optional. Generate values from the qualified independent oracle
metrics and vector configuration, and retain artifact and source hashes in the
runner manifest. The frozen impulse bundle has no bin CSV; its complete oracle
bin file must come from the qualified reference implementation.

Top-level string parameters `X_FILE`, `Y_FILE`, `FRAME_FILE`, `BIN_FILE`, and `IFFT_FILE`
select the input memh and independent expected output memh/frame CSV/bin CSV/complete complex IFFT CSV.
`+CORE_CAPTURE_DIR=<existing-directory>` is required. The admitted arithmetic
profile remains signed 12-bit input, L=256, H=128, F=15 and D=384. Positive input
lengths use Nframes=floor((Ns+254)/128), Nframes*128 active tokens, 384 drain
tokens, Ny=Nframes*128+384 outputs and Nframes*129 unique-bin rows. The harness
checks these relationships independently of the supplied constants. The clock
period is 20 ns. Execution evidence declares the actual selected lengths; this
parameterization is not evidence for every possible length.

Run each vector first with `FINAL_STALL_CYCLES=0, STALL_PATTERN=0`, then with
`FINAL_STALL_CYCLES=37, STALL_PATTERN=1`. Drivers update on falling edges. Replay
start waits for WOLA initialization to release structural busy. The output
stall pattern is deterministic and never changes data supplied to the core.

The monitor samples source/output handshakes and the accepted-bin tap before
NBA. It samples registered sample/frame/lifecycle pulses 1 ps after that edge.
Sample taps mean metric commits; they are not aliases for public output
acceptance. `source_accepts.csv`, `y_accepts.csv`, `sample_commits.csv`, and
`lifecycle.csv` retain these separate observations and cycle identities.
`ifft_samples.csv` records all Nframes*256 accepted complex IFFT samples. Both
real and imaginary words must match the independent oracle. Some short inputs
have exactly zero imaginary residuals; other inputs exercise nonzero residuals.
The oracle determines the required count and maximum magnitude for each case.
A nonzero imaginary residual alone is not a protocol error.
`y_out.memh`, `frame_stats.csv`, `bin_stats.csv`, and `metrics_observed.json`
provide exact post-run comparison material.

A pass requires exact stream contents and cardinalities, independent bin
magnitude/mask and delayed-error recomputation, matching metrics and stage
counters, one accepted start, one completion pulse, and structural idle.
Completion is forbidden while the final output is stalled. After completion,
1024 clocks must remain quiet with stable done and clear error status. This
bounded extra-output check is not a universal proof of latency. A separate
500000-cycle watchdog rejects noncompletion.

The runner must require `CORE_COMPLETION_COUNTS`, `CORE_IFFT_EXACT`, and `CORE_RTL_PASS`, scan
for error/fatal diagnostics, reject timeout, and compare captures. ModelSim
may return process exit zero after `$fatal`; exit status alone is insufficient.
Keep qualification status separate from any earlier diagnostic runs against
unqualified candidate artifacts.
