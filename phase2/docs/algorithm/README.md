# Complete editable T-RECAP specification

**Threshold-based Reduction and Encoding for Controlled Audio Processing.**

[Read the complete specification](complete_specification.md). It contains the entire 106-page historical specification in Markdown, followed by the [current finite-profile and recorded-RF specification](current_profiles_and_rf.md). Equations are editable LaTeX math, tables are Markdown, and algorithms, schemas and directory trees are editable code blocks.

## Choose a reading path

| Topic | Editable source | Historical PDF pages |
| --- | --- | --- |
| Cover, executive summary and original contents | [Front matter](baseline/page-001.md) | 1 to 13 |
| Fixed-point algorithm, FFT/IFFT, threshold, WOLA and signoff | [Part I](baseline/page-014.md) | 14 to 36 |
| Historical non-stalling DDR ring and UDP telemetry proposal | [Part II](baseline/page-037.md) | 37 to 72 |
| Historical repository organization and implementation plan | [Part III](baseline/page-073.md) | 73 to 101 |
| Vendor FFT checklist, Phase 1 anchor and file inventories | [Appendices](baseline/page-102.md) | 102 to 105 |
| Original bibliography | [References](baseline/page-106.md) | 106 |
| Implemented finite profiles and recorded RF integration | [Current specification](current_profiles_and_rf.md) | Later extension |
| Whole-project diagrams after RF integration | [System architecture atlas](../architecture/system/README.md) | Later implementation views |

The [page-by-page index](page_index.md) accounts for every source page. Each page has previous, next and original-PDF links. The [read-all document](complete_specification.md) has explicit page anchors and rebased links for reading or searching the entire specification at once.

## Historical baseline and current implementation

The original document is dated May 4, 2026. It contains Core Revision J, Telemetry Revision G and Repository Architecture Revision D. Its historical full project name is retained on the transcribed cover. The current project name appears in this guide and the current-profile appendix.

Part I specifies the deterministic signed 12-bit core with a 256-point FFT, a 128-sample hop, 15 fractional bits and a 384-sample nominal delay. Its mathematical and artifact rules remain distinguishable from the application wrappers.

Part II proposes a continuously running core with non-stalling telemetry taps, an HPS DDR ring and UDP transport. TSH2 and TRF1 are later finite-record application profiles with bounded buffers and their own interfaces. TSH2 uses a TCP request/reply service. TRF1 uses a bounded host transfer and HPS MMIO client. The current appendix documents those differences and the RF adapter without rewriting the historical proposal as if it described the fitted applications.

Part III records the repository plan at that time. Its statements that verification work is outside scope are historical scope statements. Current verification evidence is documented separately in the [verification index](../verification/README.md) and [RF supplement](../verification/rf_iq/README.md).

## Full-content inventory

| Item | Preserved content |
| --- | --- |
| Source pages | All 106, including cover, contents, lists and references |
| Numbered main sections | All 53 |
| Numbered display equations | All 116, with original equation labels |
| Numbered tables | All 45, including tables continued across pages |
| Numbered algorithms | All 7, including their continued portions |
| Appendices | A through D |
| Other structured material | JSON examples, SystemVerilog types, CSV headers, file trees, ownership flows and unnumbered formulas |

The transcription removes repeated running headers and printed page footers. Source-page identity remains in every page heading and the coverage manifest. It changes presentation and punctuation, not the intended historical requirements. See the [conversion notes](conversion_notes.md) for notation repairs and the limits of the automated checks.

## Source identity

The [original PDF](../specs/t_recap_phase2_integrated_spec.pdf) is unchanged. Its SHA-256 is:

```text
7de45d2764bacc090d2837501382c82a7f081884b7c929b8b4aa4b536bff2aaf
```

[Source inventory](source_inventory.json) records original page extraction hashes and equation/table inventories. [Coverage manifest](coverage_manifest.json) maps all 106 pages to editable files. [Bundle manifest](bundle_manifest.json) binds the reviewed Markdown, conversion rules and checking tools.

## Edit and check

Edit the Markdown files under [source/baseline](source/baseline/page-001.md) or the [current-profile source](source/current_profiles_and_rf.md). These are the canonical editable files, including LaTeX formulas. The matching files under `baseline/` and the read-all document are generated reading views.

Equations are rendered locally by LaTeX and dvisvgm into vector images with outlined glyphs. The reading views require no math plugin and do not depend on a viewer's macro allowlist. Both display and inline equations use this path, including equations inside table cells. Each page links to its editable source. The source can always be edited through GitHub's Code view or a text editor.

After editing a source, rebuild the formula assets and reading views. Generation requires a LaTeX installation with `amsmath`, `amssymb` and `dvisvgm`:

```powershell
python phase2/docs/algorithm/render_math.py
python phase2/docs/algorithm/assemble_spec.py
python phase2/docs/algorithm/render_math.py --check
```

Use `--latex path/to/latex` and `--dvisvgm path/to/dvisvgm` when the tools are not on PATH. Checking committed output needs only Python's standard library. It verifies source-to-image coverage, vector image dimensions and aspect ratios, local glyph references, generated Markdown, original PDF identity, section/table/algorithm/equation coverage, links and hashes. It does not run hardware or certify mathematical equivalence. See [rendering verification](rendering_verification.md) for the reviewed failure cases.

After a reviewed change, refresh the bundle with:

```powershell
python phase2/docs/algorithm/check_spec.py --seal
python phase2/docs/algorithm/check_spec.py
```

The reviewed historical conversion is reproducible from a UTF-8 `pdftotext -layout` extraction. The default command compares generated content without overwriting edits:

```powershell
python phase2/docs/algorithm/transcribe_pdf.py --layout path/to/algorithm_pdf_layout.txt
```

Alternatively, supply `--pdftotext path/to/pdftotext` to extract the original PDF directly. Extraction page hashes must match the reviewed layout. Different PDF text engines can order mathematical glyphs differently, so an extraction mismatch requires review before regeneration.

`conversion_rules.json` contains the reviewed equation, table and structured-block repairs. Update those rules when an intentional baseline transcription correction should remain reproducible. The explicit `--write` option regenerates the 106 canonical source files. It does not alter the original PDF or current-profile appendix. Run the rendering and assembly commands afterward.
