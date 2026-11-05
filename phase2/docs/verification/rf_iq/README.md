# Recorded RF verification supplement

[Read the academic LaTeX report](rf_verification_supplement.pdf). It covers the CU8 I/Q contract, adapter scheduling, requirement traceability, actual RTL waveforms, fresh simulation and the separately identified historical board qualification.

The report uses the eight views from the [RF architecture atlas](../../architecture/rf_iq/index.html). It does not modify the FPGA architecture or claim RF formal/UVM coverage.

## Evidence scope

- [Fresh regression projection](evidence/fresh_projection.json) summarizes the published simulation runs. No board was accessed by that refresh.
- [Historical projection](evidence/historical_projection.json) contains selected fields from the earlier five physical captures and qualified build. It preserves original receipt and result digests. Its 224 local file-hash checks were rerun before export.
- [Actual RTL waveform provenance](evidence/waveform_source.json) binds the plotted interval to a fresh simulation VCD and its extracted [trace](evidence/waveform_trace.csv).
- [Bundle manifest](bundle_manifest.json) detects changes to the report, figures, evidence and eight linked atlas images. It is a consistency check, not an independent digital signature.

Raw RF recordings, returned sample arrays and large capture archives are excluded from this report bundle. The historical projection is explicitly labeled as a projection. It is not a substitute for the original capture files when repeating the full numerical analysis.

## Run verification

Use the [RF simulation guide](../../../verification/rf_iq/README.md) and its runner. The independent golden model and adapter sources are in [the TRF1 profile](../../../profiles/trf1/README.md).

The earlier TSH2 formal and UVM work remains limited to its documented scope. The new RF adapter and application wrapper have directed and randomized self-checking simulation evidence. No new RF formal proof or RF UVM environment is claimed.

## Rebuild the PDF

From this directory, using a LaTeX distribution with the standard packages used by the source:

```powershell
pdflatex -interaction=nonstopmode -halt-on-error rf_verification_supplement.tex
pdflatex -interaction=nonstopmode -halt-on-error rf_verification_supplement.tex
```

The source uses the Times academic font family, numbered equations, captioned figures, requirement tables and exact artifact identities. All figure files and generated result text are committed. PDF compilation does not rerun the hardware or simulations.

To render for visual inspection with Poppler:

```powershell
pdftoppm -r 120 -png rf_verification_supplement.pdf review-page
```

Generated `.aux`, `.log`, `.out` and review-page images are build artifacts and need not be committed. The build used MiKTeX `pdflatex` on Windows and Poppler for page rendering.

## Audit the bundle

```powershell
python check_bundle.py
```

This command requires only Python's standard library. It verifies exact file digests, the expected inventory, historical projection status, fresh result status and waveform linkage. It never accesses the board or network.

Authors can refresh the manifest with `python check_bundle.py --seal` after rebuilding and reviewing the report. This intentionally updates digests. It does not independently establish that the content is correct.

## Regenerate derived evidence and figures

`export_historical.py --workspace PATH` requires the original local evidence workspace. It reads and verifies the preserved build, program, capture, sample and numerical-analysis records before producing a sanitized projection. It does not program or query hardware.

`make_fresh_projection.py` accepts the fresh local run directories and produces compact report tables. `make_figures.py --vcd PATH` rebuilds the measured tradeoff chart and an extracted RTL backpressure plot. Figure generation needs NumPy and Matplotlib. The plotted waveform is actual simulator output, not an illustrative animation.

The original recording is pinned by URL and digest in the historical projection. It is a short recorded civilian OOK signal. A recovered payload is useful application evidence for that fixture, but does not establish arbitrary-protocol preservation, weak-signal sensitivity, CPU workload savings or electrical-power savings.
