# Baseline PDF page 028

Historical Part I, core algorithm. Printed page 15. [Original PDF page](../../specs/t_recap_phase2_integrated_spec.pdf#page=28).

[Previous](page-027.md) | [Index](../README.md) | [Next](page-029.md)

[Edit Markdown and LaTeX source](../source/baseline/page-028.md). Equations are rendered locally as SVG.

- `window_qw.memh` shall contain exactly L lines. Line i stores ![Q_w&#91;i&#93;](../math/baseline-page-028-001.svg) for i = 0, . . . , L - 1.

- `twiddle_re.memh`, `twiddle_im.memh`, `twiddle_inv_re.memh`, and `twiddle_inv_im.memh` shall each contain exactly L lines. Line e stores the coefficient for e = 0, . . . , L - 1.

- `x_in.memh` shall contain exactly ![N_s](../math/baseline-page-028-002.svg) lines.

- `y_out.memh` shall contain exactly ![N_y](../math/baseline-page-028-003.svg) lines.

- `frame_stats.csv` shall contain one header row plus exactly ![N_{&#92;mathrm{frames}}](../math/baseline-page-028-004.svg) data rows.

- Conditional `bin_stats.csv`: when required for a vector, one header row plus exactly ![N_{&#92;mathrm{frames}}(L/2+1)](../math/baseline-page-028-005.svg) data rows. The baseline stores L twiddle entries for a simple artifact contract, even though a hardware implementation may store fewer entries internally after a separate ROM-addressing proof. Internal ROM compaction shall not change the external artifact contract. The `bin_stats.csv` artifact is conditional:

- If the file is not required for a vector, omit `bin_stats_data_rows` from `artifact_rows`.

- If that row-count field is present, then `bin_stats.csv` shall be present and shall contain exactly that number of data rows.

### 7.8 Required artifacts

**Table 4. Required stream and coefficient artifacts.**

| Artifact | Contract |
| --- | --- |
| `x_in.memh` | Input stream in signed ![N](../math/baseline-page-028-006.svg)-bit two’s-complement hex, exactly ![&#92;lceil N/4&#92;rceil](../math/baseline-page-028-007.svg) digits per line. |
| `y_out.memh` | Reconstructed stream ![y&#91;0&#93;,&#92;ldots,y&#91;N_y-1&#93;](../math/baseline-page-028-008.svg) in the same signed ![N](../math/baseline-page-028-009.svg)-bit format. |
| `window_qw.memh` | Quantized window ROM ![Q_w&#91;i&#93;](../math/baseline-page-028-010.svg), unsigned width ![W_{Q_w}=F+1](../math/baseline-page-028-011.svg). |
| `twiddle_re.memh` | Forward twiddle real table, signed width ![W_{&#92;mathrm{tw}}](../math/baseline-page-028-012.svg). |
| `twiddle_im.memh` | Forward twiddle imaginary table, signed width ![W_{&#92;mathrm{tw}}](../math/baseline-page-028-013.svg). |
| `twiddle_inv_re.memh` | Inverse twiddle real table, signed width ![W_{&#92;mathrm{tw}}](../math/baseline-page-028-014.svg). |
| `twiddle_inv_im.memh` | Inverse twiddle imaginary table, signed width ![W_{&#92;mathrm{tw}}](../math/baseline-page-028-015.svg). |


**Table 5. Required metadata, statistics, and signoff artifacts.**

| Artifact | Contract |
| --- | --- |
| config.json | Configuration metadata, contract strings, width fields, threshold mapping, and coefficient hashes. |
| `test_vectors.json` | Frozen test-vector manifest with generator parameters, threshold, protection flags, and tail policy. |
| `quality_bounds.json` | Frozen no-suppression quality limits per vector after the first golden-model release. |
| `frame_stats.csv` | One row per signoff frame with mandatory columns below. |
| metrics.json | Aggregate signoff metrics under the exact schema below. |
| `bin_stats.csv` | Conditional debug artifact for near-threshold and small regression vectors. |
