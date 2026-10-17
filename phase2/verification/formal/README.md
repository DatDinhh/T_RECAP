# TSH2 local formal verification

This package applies formal checks to unchanged RTL from the active finite-file TSH2 profile. It is a local block proof portfolio, separate from the existing simulation and physical-board results. No FPGA, JTAG, MMIO, network service or board image is operated by this runner.

The authoritative execution and witness inventory are in [evidence/summary.json](evidence/summary.json) and [evidence/index.json](evidence/index.json). A normal proof must return PASS. A deliberate false-property control must return FAIL, identify the intended assertion, exit nonzero and produce a VCD counterexample. A timeout, tool error, incomplete run or unrelated failure is never accepted as a proof.

## What is checked

| DUT and exact parameters | Property scope | Method |
| --- | --- | --- |
| `stream_fifo`, WIDTH=8, DEPTH=3 and 4 | Occupancy, flags, accepted-operation recurrence, output hold, and exact FIFO order against an independent shifting reference queue | Unbounded ABC PDR proof |
| `stream_fifo`, WIDTH=32, DEPTH=1024 | Deployed output-FIFO occupancy, flags, count recurrence and output hold | Unbounded SMT temporal induction; no pointer progression or data-order claim |
| `stream_fifo`, WIDTH=32, DEPTH=256 | Additional parameter configuration with the same control properties | Unbounded SMT temporal induction; this is not the PCM source's different FIFO implementation |
| `trecap_round_sat`, 11 explicit parameter sets | Rounded value and all saturation flags for every bit pattern of each listed input width | Combinational exhaustive equivalence using SMT |
| `trecap_mag2_mask`, unchanged default L=256, P=8, DATA_W=28, MAG2_W=56 | Output ownership, held payload, metadata and complex-value passthrough, strict threshold comparison, equality retention, unique-bin eligibility and DC protection | Unbounded SMT temporal induction; relational checks use the DUT's output magnitude |

The adapter instantiates two default 32-by-1024 `stream_fifo` instances for Y and spectral output. The 256-entry PCM buffer is different RTL inside `trecap_pcm_stream_source` and is not proved here. Small-depth FIFO order proofs do not establish production-depth data order. Their non-power-of-two depth also exercises explicit pointer wrap behavior through externally observed order, without claiming a parameterized theorem over every depth.

The round/saturate oracle uses a signed floor quotient and nonnegative remainder to decide the nearest integer, with ties away from zero, then applies signed bounds. It does not repeat the DUT's biased-magnitude implementation. Parameter sets `(IN_W, OUT_W, SHIFT)` are:

```text
(29,28,1)  (28,28,0)  (37,12,15)
(8,4,0)   (8,4,1)    (8,4,4)    (8,4,8)   (8,4,9)
(64,32,63) (64,32,64) (64,32,65)
```

The first two match canonicalizer instances. `(37,12,15)` matches WOLA's final output conversion: `T_OLA_W=37`, `T_SAMPLE_W=12`, `T_FRAC_F=15`. Their unchanged caller and generated-constant files are hash-bound in [admission.json](admission.json). The remaining sets exercise saturation and shifts at and beyond the signed input width. This is a finite set of parameter proofs, not a theorem over arbitrary widths and shifts.

Mask properties intentionally compare `out_mag2_o` with the threshold captured on the accepted input beat. They do not independently recompute the square/sum and do not prove multiplication, statistics, complete legal-frame sequencing or diagnostic sticky bits. Bin metadata is unconstrained and can trigger unclaimed diagnostics. DC is protected; Nyquist is eligible in the admitted generated package. Equality retains a bin because suppression uses strict `<`.

## Assumptions and witnesses

The sequential harnesses make one environmental assumption: reset is asserted at the first sampled clock step. Reset, CLEAR, enable, push/pop, data, threshold, metadata and output readiness are otherwise unconstrained where present. There is no fairness assumption, no assumption forbidding full pushes or empty pops, and no assumption of RAM initialization. The combinational round harness has no assumptions.

FIFO operations are accepted using pre-edge flags. At full, simultaneous push/pop accepts only pop; at empty, it accepts only push. The oracle checks registered read data on the next sampled edge. Output data has no reset value and is not asserted as zero after reset/CLEAR. Reset cancels pending validity checks. Eight reduced-instance cover goals reach full, drain to empty after full, simultaneous accepted operations, simultaneous requests at full and empty, read/write wrap, recovery after nonempty CLEAR, and recovery after a sampled reset following traffic. The production-depth cases do not include those full/wrap reachability jobs.

Round cover jobs reach selected zero, minimum, maximum, tie and saturation inputs when those conditions exist for the chosen parameters. The mask cover job reaches seven scenarios: stall, simultaneous input/output acceptance, protected DC despite pre-mask, suppressed Nyquist, retained equality, just-below-threshold suppression, and CLEAR recovery. Covers establish existence of witnesses within their configured bounds; they do not prove safety or exhaustive scenario coverage.

Formal clocks and VCD timestamps represent logical steps. `async2sync` models sampled reset behavior for the single-clock proofs. These results do not establish physical reset release timing, glitch immunity, metastability, CDC/RDC safety, timing closure, analog behavior or board latency.

## Reproduce

Use the official [OSS CAD Suite release 2026-10-16](https://github.com/YosysHQ/oss-cad-suite-build/releases/tag/2026-10-16). [toolchain.json](toolchain.json) pins the Linux x64 archive URL, size and SHA-256. The suite is downloaded separately; binaries are not redistributed here. Python's standard library is sufficient for the runner. The suite supplies Yosys, SBY, ABC, Z3 and the slang frontend.

From the repository root, with the extracted suite available:

```sh
source /path/to/oss-cad-suite/environment
python3 phase2/verification/formal/run.py \
  --repo-root phase2 \
  --tool-bin /path/to/oss-cad-suite/bin \
  --output formal-runs/attempt01
```

Output directories must be new. Each attempt records tool versions and executable hashes, harness/runner/case hashes, unchanged DUT hashes, command arguments, stdout/stderr, status, elapsed time and VCD hashes. The runner rejects changed source admission and input drift. Every SBY job has a tool timeout plus an external deadline; on Linux the runner kills only the owned process group if that deadline is exceeded. An incomplete requested run remains RUNNING. Repeated `--case` options select exact IDs from [cases.json](cases.json); an explicit subset can finish PASS only for those selected cases. Publication admission requires all 33 registered jobs.

The safe CI identity check does not need formal tools and does not execute a proof:

```sh
python3 phase2/verification/formal/run.py --repo-root phase2 --check-package
```

The intended full suite is 33 jobs: 16 safety/equivalence proofs, 14 bounded cover jobs, and three deliberately failing controls. Exact engines, bounds and expected outcomes are machine-readable in `cases.json`. For the stateless arithmetic checks, depth 1 covers all symbolic input values; it is not a temporal bounded-only claim. Sequential PDR/induction PASS is distinguished from bounded reachability in the receipts.

## Evidence handling and failed attempts

Published evidence is a derived export of immutable local receipts. [export_evidence.py](export_evidence.py) replaces invocation-specific absolute roots with `archive:formal/attempts`, `repo:phase2` and `external-tool:oss-cad-suite`, and writes UTF-8 LF. The index records both each original byte hash and its exported hash. VCD signal values and solver outcomes are preserved. These aliases are provenance identifiers, not executable filesystem paths. Hashes establish identity, not mathematical validity or a digital signature.

Superseded attempts are retained and indexed. The initial reduced FIFO SMT induction timed out; ABC PDR subsequently discharged that proof. Early mask elaboration attempts used an unsupported frontend option and omitted a package dependency. An internal-reg `anyseq` harness representation was not preserved as shared symbolic nets by the slang frontend and produced spurious stall failures and an unreachable recovery cover. The accepted representation uses explicit unconstrained top-level ports, with the same reset assumption, plus a separate false-property counterexample control for this frontend. None of these changes modified the DUT. Refer to the exported attempt history for original statuses and hashes.

This package does not prove the complete DSP pipeline, adapter protocol, PCM source, exporter, HPS platform, physical board or fitted image. It adds local formal evidence to the existing [portable simulation package](../tsh2/README.md) and [verification overview](../README.md). The [SBY documentation](https://yosyshq.readthedocs.io/projects/sby/en/latest/) describes proof, cover and counterexample modes; the [slang frontend](https://github.com/povik/sv-elab) elaborates the unchanged SystemVerilog packages used by the mask block.
