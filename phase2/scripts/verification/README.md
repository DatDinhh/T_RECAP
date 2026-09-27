# Running verification campaigns

Run these commands from the repository root. Python, CMake, a C++20 compiler and
the qualified native ModelSim command tools are needed for the relevant stages.
The recorded host uses Windows and ModelSim Intel FPGA Starter Edition 2020.1.
The scripts accept explicit tool paths instead of storing local installation
paths in the repository.
The simulator commands below assume `vsim` is on PATH. Otherwise append
`--simulator-dir <directory-containing-vsim.exe>` to the environment, rounding
and core runner commands.

The [execution plan](../../docs/verification/execution_plan.md) defines the
milestones. These commands implement bounded campaigns. Each run records its selected
cases; they do not cover every case in the full test catalog.

## Environment, inputs and reference

Start with:

```powershell
python scripts/verification/simulator_qualification.py
python scripts/verification/artifact_admission.py --output runs/verification/my-admission/admission.json
python tests/verification/test_artifact_admission.py --evidence runs/verification/my-admission/faults.json
python scripts/verification/reference_qualification.py --run-dir runs/verification/my-reference --build-dir build/verification/my-reference
python scripts/verification/rounding_qualification.py
```

Use a new evidence name for a new attempt. The environment and rounding runners
create unique directories automatically. The reference runner rejects an
existing evidence directory; CMake may reuse its isolated build directory.
Always inspect both exit status and the recorded result scope before continuing.

The reference runner's bounded PASS can coexist with an explicitly reported
public-API failure outside the baseline shift domain. This is recorded in its
JSON and does not qualify the entire public API. Artifact admission similarly
does not accept unresolved historical generator identities or quality bounds.

## Native finite core replay

Pass the actual environment run directory printed by the first command and the
reference run directory created above:

```powershell
python scripts/verification/core_replay.py --environment-run runs/verification/environment-RUN_ID --reference-run runs/verification/my-reference
```

Replace environment-RUN_ID with that existing run directory. By default this
executes static and stalled variants for the two selected nonzero vectors, then
checks a deliberately corrupted expected y value in the first vector. The
stalled variants use a deterministic LFSR and hold the last output for at least
37 cycles; ordinary readiness can extend that interval.

Every vector has an isolated simulator library, configuration and working
directory. Exact admitted coefficient bytes are staged at the relative ROM
paths expected by the DUT. The runner checks qualification hashes, source and
input identities, generated expectations, native diagnostics, exact capture
post-checks and final completion. It rechecks source, ROM and reference
identities after execution.

A wrong-y qualification case passes only when the intended checker rejects it.
An error-free normal replay needs the completion, exact IFFT and PASS sentinels,
plus a successful independent capture comparison. A zero simulator exit code
alone is insufficient.

Raw logs, CSV/MEMH traces, waveform files and summaries remain under ignored
runs/verification/. The public result document contains sanitized identities
and scope; it does not require committing local simulator libraries or logs.

## Short-length and finite-tail boundaries

Supplemental vectors are generated into a new evidence directory. They do not
replace the frozen input vectors or historical reference outputs. First qualify
the public C++ adapter and independent integer oracle with the baseline command
above, then run:

```powershell
python scripts/verification/reference_boundaries.py --baseline-reference-run runs/verification/my-reference --adapter build/verification/my-reference/Release/reference_api_adapter.exe --run-dir runs/verification/my-boundary-reference
python scripts/verification/core_replay.py --environment-run runs/verification/environment-RUN_ID --reference-run runs/verification/my-boundary-reference
```

The adapter path above matches a Visual Studio Release build; use the actual
qualified executable location for another generator. Its hash must match the
baseline report.

The boundary report declares the default selected cases. The native runner uses
that list and the report-pinned supplemental inputs; repeat `--vector CASE_NAME`
to run a subset. Each selected case still executes static and stalled variants
unless `--variant` selects one. The input path, signed width, row count, finite
geometry and oracle file identities must agree before compilation.

The matrix covers Ns=1,2,126,127,128,129,130,254,255,256,257,258,383,384,385,386,
511,512,513,514 with raw THR2=0 and 8796093022208 (2^43). Because the first window coefficient is
zero, the frame-count changes occur at Ns=2,130,258,386,514. The +2 cases are
necessary to distinguish a complete tail from an extra zero-window edge frame.
This is a deterministic length/threshold matrix, not dynamic-threshold or
arbitrary input-gap coverage.

## Checker qualification

The reference-admission witnesses use isolated synthetic inputs:

```powershell
python tests/verification/test_core_replay_admission.py --evidence runs/verification/my-admission/core-runner.json
```

The capture mutation suite accepts an actual positive capture, its admitted
oracle directory and its input file. Inspect its --help for explicit paths:

```powershell
python tests/verification/test_core_capture_check.py --help
```

It changes copies of the evidence to demonstrate rejection of missing,
duplicated, truncated, reordered or numerically incorrect data. Passing these
witnesses establishes checker sensitivity for the selected cases; it does not
add another RTL or board execution.

## Tool policy

Functional compilation does not define SYNTHESIS. ModelSim diagnostic 2892 is
retained as a warning for the existing ANSI input logic declarations under
default_nettype none. The installed verror 2892 explains this port-kind
diagnostic. No assertion/error/fatal diagnostics are suppressed. Four-state
behavior, scheduling, wide integer file I/O and deliberate failures are tested
under the selected tool settings. Concurrent SVA, covergroups, code coverage,
DPI and vendor models are outside this qualification.

Do not use historical vector/coefficient regeneration targets to resolve a
mismatch. Correctness investigations retain the failed run and compare against
independent requirements; a changed source or checker produces new evidence.
