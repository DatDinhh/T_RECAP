# TRECAP design verification portfolio

**T-RECAP: Threshold-based Reduction and Encoding for Configurable Analysis Pipelines.** See [project naming and scope](../../project_identity.md).

This editable LaTeX portfolio presents the registered TSH2 finite-file verification campaign, a reproduced and repaired arithmetic defect, exact RTL scoreboards, observed event coverage, and fresh DE1-SoC captures. The supplemental seeded runner section reports executed results and a qualified negative control. It does not claim UVM, concurrent SVA, coverage closure percentages, formal proof, or complete signoff of the original project specification.

The report uses traditional academic typography: 11-point Latin Modern serif body, headings and math, a conventional title and abstract, numbered sections and captions, and restrained black/gray document styling. The eight scientific vector figures retain their measured content and use pastel sage, blue, lilac and peach. Dark labels and muted strokes keep plots readable.

- [Read the compiled portfolio](TRECAP_DV_Portfolio.pdf)
- [Edit the LaTeX source](main.tex)
- [Published campaign evidence](../../results/verification_20261017/README.md)
- [Original-to-public evidence manifest](../../results/verification_20261017/manifest.json)
- [Portable seeded RTL runner](../../../verification/tsh2/README.md)
- [Verification overview](../../../verification/README.md)

## Build

Install a TeX distribution with pdfLaTeX and the packages listed in `main.tex`. The eight local figure PDFs are included. Run these commands in this directory:

```sh
pdflatex -interaction=nonstopmode -halt-on-error -file-line-error main.tex
pdflatex -interaction=nonstopmode -halt-on-error -file-line-error main.tex
```

This produces `main.pdf`. Alternatively `python build.py --compiler pdflatex` creates `TRECAP_DV_Portfolio.pdf` and a new immutable `build/attemptNN` with exact local command logs, source snapshots and output hashes. MiKTeX automatic package installation is disabled by the script. Install required packages beforehand. No shell escape, FPGA, Python numerical library or simulator is needed to compile the document.

## Reproduction boundary

Compiling the report does not rerun verification. Short evidence paths printed in the PDF identify historical campaign artifacts. The linked public export provides normalized summaries and compact case ledgers. Archive identifiers are not files promised by this repository. Raw physical sample libraries and vendor-tool databases remain outside this compact publication.

`source_manifest.json` binds all vector figures, the public evidence export, and its original versus derived hashes. `build_receipt.public.json` is a normalized derivation of the local compiler receipt. The original receipt hash is preserved separately. `document_audit.public.json` records PDF page, caption, numeric and layout checks. Personal absolute paths and runtime UUID/IP/MAC identifiers are excluded from the approved publication files.

The integration section reports the supplemental Windows ModelSim run for seeds 1, 7 and 20261017. It is not a claim of Linux simulator execution or hosted RTL CI. See the runner's evidence receipt for its exact source and fixture identities. Public synthetic fixtures contain no recorded audio.

Local reruns intentionally write workstation-specific receipts under `build/`. These are not automatically approved publication artifacts. Review and normalize new receipts before publishing them. The historical campaign reports remain preserved separately.

## Publication refresh

The current PDF was rebuilt from LaTeX after prose cleanup and a pastel figure refresh. The historical verification results are unchanged. [The vector audit](figures/editorial_refresh.json) preserves original and current hashes and checks every geometric PDF operator. No trace values, event times, numerical labels or plotted data paths were recomputed.

To reproduce the figure style, install `pypdf` and `fonttools`, then run `python restyle_figures.py --source BASELINE_FIGURES --output figures --family portfolio`. Use the original figures from commit `07bc8224aa080c8eaa1b77b4603c118d853465d0` as `BASELINE_FIGURES`. The script changes presentation only. PNG previews are rendered from the resulting vector PDFs.
