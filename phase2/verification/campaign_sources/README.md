# Accepted release testbench archive

These are the exact accepted SystemVerilog bench bytes from the 14-suite active TSH2 release campaign. They are published for code review of the checks behind the report. `source_lineage.json` records each source hash, its original relative campaign path and the accepted report hash. No DUT was edited for this archive.

This folder is an archived source collection, not a standalone runner. The original local orchestration, complete fixture inventories and registered full-length inputs are not included. The full-stream benches expect external input, Y and packet fixtures; the arithmetic benches expect generated vectors and coefficient tables. Module names are intentionally unchanged, so compile each selected bench separately. Do not compile all archived files together.

For a self-contained runnable example with redistributable synthetic fixtures, use [the seeded TSH2 regression](../tsh2/README.md).

| Bench family | Accepted evidence represented |
|---|---|
| Environment and rounding qualification | Four-state behavior, procedural assertion/error/fatal propagation, completion and watchdog controls; fixed-point rounding comparisons |
| Large shifts, analysis window, butterfly, canonicalizer and mask | Directed numerical boundaries, payload stability, ordering and malformed/unknown controls |
| Finite geometry | Lengths around frame/hop boundaries with exact accepted outputs |
| Busy reset and waveform replay | Pipeline-phase cancellation, clear/hard-reset recovery and recorded signal windows |
| Final Y completion | Held final token, busy/done ordering and exact final time metrics |
| Full stream | 384,000-input dense threshold-zero and sparse threshold-100,000,000 runs |

There are 13 source files representing 14 suites because positive mask and X/Z controls share a bench. The two full-stream files are identical bytes retained under their accepted run names. The archive contains no failed earlier bench variants, generated DUT snapshot, audio recordings, raw captures or vendor binaries. Procedural checks and observed event counts do not imply UVM, concurrent SVA, formal verification, code-coverage percentages, analog CDC qualification or industrial certification.
