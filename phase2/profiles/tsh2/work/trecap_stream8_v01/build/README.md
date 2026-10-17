# TSH2 source-bound build

The parent is the qualified C: workspace image
`outputs/trecap_hps_transport_v01/build01`. No original project/cache files or
prior snapshots are edited. Generated HPS/Qsys source, peripheral constraints,
reset topology, CLOCK_50, 127 HPS pins and 11 FPGA clock/LED pins are retained.
The new application uses streaming PCM, spectral and waveform FIFOs.

Freeze root RTL, core source/top and CONTRACT.md before `build.py --stage
prepare`. New registration binds every source, setting and SOURCE_ID. The top
wrapper changes only the adapter module name. No HPS/Qsys regeneration is needed.

After root releases the candidate, `simulate.py` can compile the root-owned
testbench against the registered application and actual numerical core. Pass
`--build`, fresh `--out`, `--testbench`, `--top` and exact `--pass-marker`;
optional `--plusarg` values are forwarded to ModelSim. `source_id.svh` defines
TEST_SOURCE_ID, and `+OUT` names the simulation output directory. A passing
marker confirms only the assertions actually implemented by that testbench.

Each hardware-tool stage is explicit: map, vendor DDR capture, fit, STA and
independent timing review. New STA dispatch uses its supported project command,
without map/fit-only option flags. Inspect all FIFO RAM inference after map.
Require source-bound simulation before fitting and all 18 clocks/four corners,
32 calibrated DDR categories and exact pin/exception coverage before assembly.

The assessment binds expected HPS handoff bytes. Assembly produces and compares
all 15 actual handoff files with the qualified parent before issuing PASS.
Programming, Linux ownership and bridge isolation remain root-owned and separate.

Build01 passed the actual-core adapter suite (12 normal epochs, 13 negative
cases, all three FIFOs forced full), the independent core suite, synthesis,
DDR capture, fit and complete timing/pin review. It uses 6521 ALMs, 8568
registers, 47 M10Ks and 35 DSP blocks. All four-corner CLOCK_50 margins pass:
worst setup 3.237 ns, hold 0.105 ns, recovery 12.181 ns and removal 0.434 ns.
Assembly confirmed exact parent HPS handoff and unchanged admission evidence.

SOF SHA256:
`f96bc5a35adf08711a5f392baf9f8cbf5ec65a17211a58117bdb53f62acbb7ab`.
SOURCE_ID:
`39db0fdf3d451dfbf2d878575725cedd3df450980b40b2a742620dfb76a1a8ed`.
The RTL simulation used 1024-sample parameter variants; the assembled image is
configured for 384000 samples. These build receipts alone do not establish a
successful physical eight-second run.
