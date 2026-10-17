# T-RECAP design verification portfolio

This portfolio verifies the fixed-point FFT, tunable threshold, IFFT/WOLA and sparse spectral export used by the registered TSH2 finite-file profile on DE1-SoC. It combines executable tests with a requirements ledger, independently checked numerical outputs, observed event coverage, negative checker controls and physical-board evidence.

Start with the [LaTeX report and editable sources](../docs/verification/portfolio/README.md), the [portable regression](tsh2/README.md), and the [public evidence ledger](../docs/results/verification_20261017/README.md). The [accepted campaign testbench sources](campaign_sources/README.md) expose the corner and recovery checkers behind the larger archived campaign. The [active profile source](../profiles/tsh2/README.md) preserves the board adapter, host service, downstream consumer and local visualizer. The original production source remains under `rtl/`, `sw/` and `sim/`.

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

The disposition is a pass for the registered finite-file profile under the tested conditions. It is not a chip-wide production sign-off or an industrial certification. The environment uses SystemVerilog procedural assertions and scoreboards, not UVM or concurrent SVA. Formal proofs, formal CDC/RDC, exhaustive code coverage, live codec/microphone operation and qualification over process/voltage/temperature remain outside this result. The original 46 broad requirements retain 30 partial and 16 excluded dispositions; these numbers are not a test pass rate.

No energy saving, FPGA advantage over a laptop CPU, AI inference speedup or production reliability claim follows from these tests. Spectral packet reduction is measured against the documented dense spectral format, not WAV size.
