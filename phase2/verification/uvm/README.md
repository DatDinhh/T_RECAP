# TSH2 UVM verification

This package executes the official Accellera UVM 1.2 library against the finite TSH2 PCM stream, DSP core and spectral exporter. It uses the unchanged 26 RTL files, coefficients and synthetic reference fixtures in the sibling [tsh2 package](../tsh2/README.md). It does not access a board or rebuild an FPGA image.

## Run

Python 3.10 or later and a simulator that executes SystemVerilog UVM classes are required. The executed campaign uses ModelSim Intel FPGA Starter Edition 2020.1 and its bundled `verilog_src/uvm-1.2` source distribution. The simulator and UVM library are not redistributed here. Set the paths to your installation:

```sh
python run.py --check-package
python run.py --sim-bin "$MODELSIM_BIN" --uvm-home "$UVM_HOME" --out runs/my_run
```

In PowerShell, use `"$env:MODELSIM_BIN"` and `"$env:UVM_HOME"`. `--source-root PATH` selects an explicit admitted TSH2 package when the packages are not siblings. The output directory must not already exist. Success returns zero; a failed check or unexpected simulator diagnostic returns nonzero. `--skip-negative` is a debugging mode that returns an explicit incomplete disposition and nonzero exit, even when its positive simulations pass. Each tool invocation has a configurable host deadline, default 600 seconds, plus simulation cycle and time watchdogs. Timeout cleanup targets only the spawned process tree; a denied cleanup is retained in the command receipt.

`--check-package` checks the exact UVM file manifest and all admitted sibling inputs. It does not invoke a simulator and is not UVM execution evidence. Results include `summary.json`, `junit.xml`, per-seed coverage CSV, raw observations, tool transcripts and command receipts. No preexisting result is overwritten.

## Environment and checks

`epoch_sequence` sends typed items through a real UVM sequencer to `epoch_driver`. The driver accesses a virtual interface. An independent `stream_monitor` samples DUT handshakes and sends transactions through a UVM analysis port to `stream_scoreboard`. Factory construction, build/connect/run/check/report/final phases, objections and UVM reporting execute in the official library. The driver never supplies observed data to the scoreboard.

The default matrix is three deterministic seeds, `1,7,20261017`, with four completed configurations per seed: threshold 0 or 100000000, each using dense or sparse TSP1 export. Each configuration accepts 1024 signed PCM samples and checks all 1536 output samples and indices, 1161 canonical spectral rows, every exported packet byte, final counts and time-domain error metrics against independently generated fixtures. Both source padding and tail ticks are checked. The fixtures contain project-generated integer synthetic input, with C++ reference and independent recursive integer-oracle provenance in the sibling package. They contain no recorded audio.

Each seed first aborts an additional partial epoch by asserting reset while a spectral frame is busy. The monitor observes the reset, discards only that epoch's partial scoreboard state, and checks the next accepted epoch from index/frame zero. No accepted Y, tap or packet outside an accepted epoch is allowed. The immediate recovery epoch is one of the four completed configurations, so the default denominator is **12 completed epochs, including three recovery epochs, plus three aborted prefixes**.

Input gaps and Y/packet backpressure use an explicit 32-bit recurrence. A valid input remains stable until accepted. The monitor checks unknown controls and valid PCM/Y/packet/tap payloads, stalled payload stability, frame credit, faults and final-Y completion. It requires observed FIFO empty/one/full states, input gaps, both output stalls, discontinuity and the final Y hold. Coverage CSVs also count masked, kept and ineligible canonical bins. These are actual observed events, not driver intentions, code coverage, covergroup coverage, or a percentage of the state space.

The runner independently rereads the complete recorded trace and rejects missing, extra, reordered, unknown or mismatched event records. An executed negative control changes the first expected Y sample in memory and must terminate with `UVM_FATAL [Y_GOLD_MISMATCH]` and a nonzero simulator exit. The DUT and admitted fixtures remain unchanged.

## Tool limits and scope

The official library is compiled with its supported `UVM_NO_DPI` option. HDL backdoor/DPI, DPI regular expressions and DPI command-line support are disabled; this environment uses direct plusargs, frontdoor interface signals and UVM TLM instead. The library's component-name check reports its DPI limitation. The Intel Starter compiler warns that constraint randomization, covergroups and some assertion features require Questa. This environment does not use a solver, covergroups, UVM register backdoor access or assertion coverage. It uses deterministic UVM sequences and explicit four-state procedural checks. UVM-aware debugger extensions are not present. The Starter edition also warns about its recommended design capacity. Those diagnostics are preserved, not interpreted as licensed feature support.

`SYNTHESIS` is not defined. Existing RTL assertion syntax is present, but no claim of simulator assertion coverage or SVA qualification follows from this run. Source net-type warnings from the unchanged DUT are explicitly downgraded with `-warning 2892`, matching the existing package. Unused top-level observation outputs are explicitly open. UVM report severities and simulator errors are checked independently of process exit status.

This suite covers a finite 1024-sample geometry and one mid-spectrum reset phase. It does not replace the prior full384000 simulations, other reset/geometry/checker campaigns, physical board captures, static timing, CDC analysis, formal proofs or host protocol tests. The simulation clock is 10 ns for scheduling convenience, not a board throughput measurement. The active design uses power-only TSP1 telemetry alongside full complex reconstruction; the suite does not claim waveform compression.

## Evidence and provenance

The run manifest hashes every admitted DUT/fixture/coefficient, each UVM harness file, the runner, tool executables and the complete official UVM source tree. The runner checks source bytes again after execution. Published evidence is a selected transcript/receipt export. Local build libraries, simulator binaries, complete trace files and failed development attempts are not part of the public source package. The evidence export records original and published hashes plus its exact sanitization mapping. No new hardware measurement is claimed.
