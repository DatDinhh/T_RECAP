# Transcription and review notes

This is a full-content transcription of the 106-page integrated specification. It is not a new algorithm revision. The original PDF remains the reference when resolving a transcription question. The current finite-profile and RF extension is a separately identified appendix.

## Presentation changes

- The repeated running header and printed page footer are omitted from the body. Every physical PDF page has a corresponding Markdown page and original-PDF link.
- Line wrapping is removed from prose. Words, identifiers and paths split by typesetting are rejoined.
- Numbered tables use editable Markdown rows. Continued tables retain the original table number.
- Numbered equations use LaTeX math with their original labels. Fractions, powers, floor operations, sums, subscripts, piecewise cases and conjugation are restored from the typeset source.
- Algorithms retain their inputs, outputs, steps and ordering. ASCII forms such as `sum(k=0..L/2, expression)` express summation in editable pseudocode without changing the operation.
- JSON examples and SystemVerilog declarations remain code. JSON fragments that continue onto another source page are intentionally still fragments on the corresponding page.
- The executive-summary flow is an editable Mermaid diagram with the same historical sequence. Other ownership and dependency flows remain editable text diagrams. The current architecture atlas provides the later whole-project implementation drawings.
- Human prose uses periods, commas or ASCII hyphens in place of semicolons and typographic dashes. Syntax within code blocks is preserved.

## Notation repairs

The PDF text layer separates superscripts and subscripts from their bases. The conversion restores the original distinction between `256` and $2^{56}$, between `232` and $2^{32}$, and between a plain variable and its indexed form. The 56-bit threshold range remains $0\le\mathrm{THR2}<2^{56}$.

The core uses round-to-nearest with ties away from zero. The restored formula retains the sign term and floor operation. It does not replace the rule with a programming language's default `round` function. The arithmetic right-shift formula retains its floor on negative inputs.

The full-tail frame count retains the floor of $(N_s+L-2)/H$. The exact output length remains $N_y=N_{\mathrm{frames}}H+G+L$. The forward FFT retains its $1/L$ scaling and per-stage rounding. The inverse retains the unscaled butterfly additions.

In Table 11, the wrapped names `thr2_commit` plus `pending` and `source_commit` plus `pending` are written as `thr2_commit_pending` and `source_commit_pending`. These spellings also appear in the historical generated CSR schema. Table 26 rejoins the broken counter labels as `PACKET_FIFO_DROP_COUNT` and `CSR_COMMAND_REJECT_COUNT`, consistent with the full CSR map in Table 8.

The multiplication helper's argument separator in Equation 3.8 is presented as a comma. Its arguments and arithmetic are unchanged. Bibliographic page ranges use ASCII hyphens. Bibliographic titles retain their meaning while typographic dash punctuation is replaced.

The unnumbered SPEC64 suppression ratio on source page 58 is explicitly a fraction. Both numerator and denominator remain indexed by the same bucket, and the following nonzero-denominator condition is retained.

## Review and reproducibility

The source inventory lists all 106 source pages, 116 numbered equations, 45 tables and seven algorithms. The converter compares each extracted page against its reviewed extraction hash before applying the recorded repairs. A second review checked page coverage, numbered-equation coverage, numeric fields, core arithmetic, table reconstruction and pseudocode against the source text.

Rendered source pages were used to inspect fixed-point rounding, the finite-stream formulas, window equations, FFT/IFFT notation, threshold and reconstruction equations, spectral metrics, signal generators and throughput inequalities. The conversion does not use a generic OCR interpretation as arithmetic authority.

The automated checker establishes inventory completeness and internal consistency. It does not prove every equation equivalent to RTL, prove every prose sentence semantically identical, or establish that the historical DDR/UDP proposal was deployed. Those claims require their own implementation evidence and review.

## Current-profile boundary

The [current-profile appendix](current_profiles_and_rf.md) cites actual RTL, host code, coefficient data and verification artifacts. Its TSH2/TRF1 interfaces, finite transaction lengths, backpressure rules and recorded RF adaptation are not silently substituted into the historical DDR/UDP specification.
