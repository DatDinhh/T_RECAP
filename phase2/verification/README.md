# T-RECAP design verification portfolio

This portfolio verifies the fixed-point FFT, tunable threshold, IFFT/WOLA and sparse spectral export used by the registered TSH2 finite-file profile on DE1-SoC. It combines executable tests with a requirements ledger, independently checked numerical outputs, observed event coverage, negative checker controls and physical-board evidence.

Start with the [LaTeX report and editable sources](../docs/verification/portfolio/README.md), the [portable regression](tsh2/README.md), and the [public evidence ledger](../docs/results/verification_20261017/README.md). The [accepted campaign testbench sources](campaign_sources/README.md) expose the corner and recovery checkers behind the larger archived campaign. The [active profile source](../profiles/tsh2/README.md) preserves the board adapter, host service, downstream consumer and local visualizer. The original production source remains under `rtl/`, `sw/` and `sim/`.

## UVM and formal supplement

The [new academic supplement](../docs/verification/uvm_formal/README.md) documents genuine [UVM 1.2 simulation](uvm/README.md) and [local formal verification](formal/README.md) of unchanged TSH2 RTL. UVM completes 12 epochs across three seeds, with three reset recoveries included in that count and three interrupted prefixes recorded separately. It checks 18,432 waveform outputs, 13,932 canonical-bin rows and 94,440 packet bytes. A separate deliberately corrupted reference must fail with the intended UVM fatal error.

Formal executes 16 safety/equivalence jobs, 14 bounded-cover jobs and three intentionally false-property controls. The proofs cover exact FIFO order at reduced depths, output-FIFO control at the deployed 32-by-1024 configuration, 11 round/saturate parameter sets and selected magnitude-mask relations. They do not establish complete pipeline equivalence, production-depth FIFO data order or correctness of the different PCM source FIFO.

The UVM simulator startup crash and its explicit bounded recovery remain recorded. The package uses seeded schedules and observed event counters, without claiming solver-constrained randomization, covergroups or code-coverage closure. The formal package includes explicit assumptions, witnesses, negative counterexamples and original/exported evidence hashes. The dedicated formal CI workflow executes real solvers; ordinary package checks only validate identities and published receipts.

## What a reviewer can run

From `phase2/`, using Python 3.11 or later:

```sh
python verification/tsh2/run.py --check-package
python docs/results/verification_20261017/export_public_evidence.py --check docs/results/verification_20261017
cmake --preset verify
cmake --build --preset verify --parallel 2
ctest --preset verify
```

The first command qualifies the checker and verifies package integrity without simulating a DUT. It must not be described as an RTL pass. With an installed ModelSim-compatible simulator, use the portable runner's documented smoke and seeded regression commands. No board, private recordings or network service is needed for that regression. GitHub Actions runs the portable package checks, reference functional tests, source hygiene and RTL frontend elaboration on Linux and Windows. Licensed RTL simulation and physical deployment are separate, explicitly recorded runs.

## Verification work demonstrated

| Engineering task | Evidence and boundary |
| --- | --- |
| Define a verification contract | Epoch admission, framing, threshold latching, ready/valid transfer, final drain, reset and bounded timeout behavior |
| Build a checking environment | Exact Y-stream, canonical-bin and packet-byte scoreboards; independent fixed-point arithmetic checks |
| Exercise corner cases | Shift and saturation boundaries, finite geometry, stalls, reset/recovery, malformed packet rejection |
| Qualify the checker | Intentional wrong or missing results must fail; fixture and source identities are verified before a run |
| Close observed functional coverage | Named event bins from simulator observations, seeds and reproducible receipts; no inferred code-coverage percentage |
| Debug and prevent a real defect | Signed rounding at shifts 63 and 64, reproduced before the fix and independently checked afterwards |
| Check physical integration | 58 physical epochs across 29 configurations, with exact output and final-register checks |
| Communicate sign-off limits | Explicit partial/excluded requirements, original failed infrastructure attempts, archived timing evidence and residual gaps |

The original campaign recorded 14 fresh RTL suites, 729,156 independent arithmetic comparisons, 11 C++ tests, 248 synthetic finite-input checks, and 58 physical epochs. See the report for exact denominators, freshness and reused evidence. The small public seeded regression is supplemental; it does not replace the full archived campaign.

## Scope of the result

The disposition is a pass for the registered finite-file profile under the tested conditions. It is not a chip-wide production sign-off or an industrial certification. The original campaign uses SystemVerilog procedural assertions and scoreboards. Its historical results are separate from the supplemental UVM environment and local formal proofs. Formal harnesses use immediate assertions/covers and explicit history state. Full pipeline formal verification, concurrent-SVA coverage, formal CDC/RDC, exhaustive code coverage, live codec/microphone operation and qualification over process/voltage/temperature remain outside the accepted scope. The original 46 broad requirements retain 30 partial and 16 excluded dispositions; these numbers are not a test pass rate.

No energy saving, FPGA advantage over a laptop CPU, AI inference speedup or production reliability claim follows from these tests. Spectral packet reduction is measured against the documented dense spectral format, not WAV size.
