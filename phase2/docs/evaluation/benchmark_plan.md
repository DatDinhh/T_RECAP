# Benchmark and evaluation plan

Status: bounded FPGA-only electrical studies and a physical ARM/HPS timing comparison completed on 25 September 2026. The [CPU result](../results/hps_cpu_benchmark_20260925/README.md) compares 60 exact-output CPU trials with matched historical FPGA finite-record counters: 1.339x dense and 1.312x masked service-time ratios for this implementation and workload. Transfers and complete-system offload are outside that timing boundary. The [board-power report](../results/board_power_20260925/README.md) and [IFFT isolation study](../results/ifft_zero_isolation_20260925/README.md) do not establish calibrated electrical savings. New equal-work CPU/FPGA energy measurements remain pending. The [integrated specification](../specs/README.md) continues to define the production baseline; the separate experiments do not revise its arithmetic or interfaces.

## Purpose and application

We will evaluate the fixed-point window / FFT / Hermitian canonicalization /
spectral-mask / IFFT / WOLA pipeline as a waveform-reconstruction front end for
acoustic monitoring.
Controlled tones and recorded machine sounds are candidate workloads. Application
usefulness requires reconstruction-error and relevant spectral-feature limits
agreed before the final evaluation; machine-fault detection and general denoising
are not established functions.

The engineering questions are whether FPGA execution reduces processing time or
CPU work relative to a suitable ARM implementation, and whether zero-aware IFFT
hardware can reduce electrical energy at an acceptable reconstruction error.
Offload, real-time operation, speedup, and energy efficiency are separate claims.

## First milestone: a trustworthy baseline

The [verification design package](../verification/README.md) specifies the environments, reference qualification, requirement mapping and acceptance evidence for this milestone.

The [baseline](../results/verification_baseline_20260915.md), [finite-boundary](../results/verification_boundaries_20260915.md), and [selected board workload](../results/board_power_20260925/README.md) campaigns provide bounded evidence. Closing the remaining functional requirements precedes qualification of the proposed energy optimization. The baseline requirements are:

1. Record the source revision, coefficient hashes, configuration, input hashes,
   tool versions, and build options in a run manifest. Preserve signed 12-bit
   input, L=256, H=128, F=15, forward per-stage scaling, unscaled inverse,
   canonicalization, rounding/saturation, and full-tail geometry in both paths.
2. Check the reference arithmetic independently at rounding, saturation, scaling,
   and threshold boundaries; then compare baseline RTL against the reference.
   The reference model is not yet a qualified golden model.
3. Exercise nonzero tones, off-bin tones, multitone and broadband signals,
   transients, full-scale cases, and finite-record completion. Zero input is a
   diagnostic case, not the representative energy workload.
4. Check output values and counts, full-tail completion, frame-owned thresholds,
   the 384-sample delayed reference, and defined behavior under backpressure and
   reset. Telemetry loss must be reported separately from core sample loss.
5. Repeat a selected deterministic BRAM replay on the board and retain the input,
   output, configuration, counters, and comparison result. Decimated or lossy
   dashboard captures do not establish complete output equivalence.

Acceptance requires explained results with no unresolved output mismatches or
unexpected core sample loss for the agreed suite. Compilation and fitted timing
are supporting implementation evidence, not substitutes for these checks.
Board confirmation follows simulation and requires a programmable bitstream.

## Comparisons

| Candidate | Role |
| --- | --- |
| ARM software | [Implemented and measured](../../experiments/hps_cpu_benchmark/README.md): preallocated fixed-point CPU datapath on one HPS Cortex-A9 core; coefficients, threshold, finite geometry and full outputs match the compared FPGA workload |
| FPGA A | Dense reconstruction with all eligible bins retained; establishes the unmasked quality reference within the hardware pipeline |
| FPGA B | Existing spectral suppression and unchanged IFFT schedule |
| FPGA C | Experimental zero-aware IFFT operand isolation at the same threshold and fixed schedule as B; source, verification and results are in the [isolation study](../results/ifft_zero_isolation_20260925/README.md) |

The software benchmark is separate from the production HPS transport application.
Use a Release build and a reasonable implementation; exclude diagnostic exports
from compute timing, consume/check the output, and record CPU frequency, compiler
flags, affinity, and thread count. Prefer preallocated working buffers and validate
coefficients outside the timed region. The existing reference path allocates
intermediate vectors and validates tables per frame; timing it unchanged must be
labeled a reference-implementation baseline, not an optimized CPU limit. Any
alternative numerical implementation needs an explicit quality-equivalence
criterion.

ARM versus FPGA at a matched threshold addresses acceleration. B versus C must
produce identical output bits and addresses the hardware optimization. A versus C
addresses the combined quality/energy tradeoff. Account for the complete added
mask, zero-detection, metadata, and enable logic when reporting net benefit;
a clean dense hardware reference may be needed beyond running THR2=0.

## Measurement boundaries

Keep the initial arithmetic comparison to the same algorithm with input resident
in each processor's local memory. Report processing service time separately from
sample-paced elapsed time, the fixed sample-domain delay, and finite-stream
startup/flush. A paced 48 ksample/s replay does not establish maximum throughput,
and the 18000-clock design allocation is not a measured execution time.

An end-to-end speedup claim additionally requires matched input/output boundaries
and includes transfer, launch, and synchronization costs. BRAM replay alone is
not an end-to-end ARM-memory-to-FPGA benchmark.

For energy, use equal useful sample counts and comparable durations. Measure
voltage and current at the board DC input with an external logger and report
energy per processed sample, repeats, and uncertainty. Keep HPS activity,
telemetry, interfaces, and temperature conditions comparable. Specify internal
integration/averaging so periodic compute bursts are not represented by sparse
instantaneous readings.

Whole-board electrical measurements include HPS, DDR, and peripherals. Report
workload-driven post-fit FPGA power estimates separately. A runtime B/C enable in
one bitstream can help paired comparisons, but it shares the optimization's
hardware overhead; compare original and modified builds as well when establishing
total implementation cost. Do not infer electrical savings from masked-bin count.

## Sequence and decision gates

| Order | Deliverable and decision |
| --- | --- |
| 1 | Baseline verification evidence and repeatable BRAM operation |
| 2 | Completed for one resident-input multitone record at two thresholds; [physical results and limits](../results/hps_cpu_benchmark_20260925/README.md). Broader workload and end-to-end comparisons remain open |
| 3 | Threshold sweep: reconstruction error and zero-operand opportunities per IFFT stage |
| 4 | If opportunities justify it, prototype operand isolation/enables with an unchanged schedule; demonstrate bit-exact B/C equivalence and record resource/timing cost |
| 5 | Estimate workload-dependent power, select a logger appropriate to the expected difference, and characterize its repeatability |
| 6 | Repeated physical measurements and quality-versus-energy results |

Some preparation can run in parallel, but each claim depends on its preceding
evidence. The initial application acceptance limits and benchmark suite remain
to be agreed. We do not set a savings percentage in advance. If the measured
difference is below uncertainty, report that no distinguishable saving was found
under those conditions and reassess the mechanism.
