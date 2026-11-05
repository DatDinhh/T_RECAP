# Algorithm specification rendering verification

[Specification index](README.md) | [Reported page](baseline/page-017.md) | [Editable source](source/baseline/page-017.md)

## Reported failure and correction

The first Markdown publication passed structural coverage checks but failed visual rendering. On page 017, the sample-range equation collapsed vertically and the saturation equation was rejected with an unsupported `operatorname` macro error. These failures were reproduced in the GitHub preview. The earlier source checks did not establish readable browser output.

The reading views now embed locally typeset LaTeX formulas as SVG images. Glyphs are vector paths, so the browser does not need LaTeX macros, a math plugin or an installed math font. Explicit image dimensions and view boxes preserve the formula's proportions. A white background and dark ink keep the equations readable in both light and dark surrounding pages.

Canonical Markdown and LaTeX remain editable under `source/`. The original PDF remains unchanged. Both the page-by-page and combined reading views are generated from the same source files. The combined document now nests section headings below each source-page heading.

## Coverage

| Check | Result |
| --- | --- |
| Historical source pages | 106 retained |
| Current finite-profile and RF appendix | Retained separately |
| Display formulas rendered | 123 |
| Inline formulas rendered, including table cells | 173 |
| Total vector formula assets | 296 |
| Historical numbered equations | All 116 retained |
| Historical tables, algorithms and main sections | 45, 7 and 53 retained |
| Source notation repairs | 37 targeted repairs across 12 pages |

The notation repairs restore subscripts, canonical-spectrum superscripts, complex conjugation and width expressions lost in PDF text extraction. They do not change fenced algorithm examples or the historical display-equation definitions. Operator-name underscores are escaped for LaTeX typesetting without changing the function name.

## Checks that run without LaTeX

`render_math.py --check` reconstructs each reading view from the canonical source and validates every formula mapping, source identity, image identity, accessible source text, image dimensions and aspect ratio. It rejects missing images, orphaned images, unresolved vector references and active or external SVG content.

The eight regression tests in [test_algorithm_math.py](../../tests/verification/test_algorithm_math.py) exercise the original page 017 failure and deliberate damage to the generated output. They cover missing images, stale source mappings, zero-width equations, distorted proportions, raw formula reintroduction, external glyph references and images without vector glyphs. These tests are included in GitHub Actions.

`check_spec.py` also checks the unchanged PDF identity, all numbered inventories, Markdown tables, local links, punctuation and the complete publication manifest.

## Visual review

The local Markdown preview was checked for page 017 sample range and piecewise saturation, page 019 inline equations in the width table, and the RF appendix interpolation formulas. The complete reading view loaded all 296 formula images successfully and has one top-level heading. Browser inspection complements the structural tests. It is not a mathematical equivalence proof or a new hardware verification run.

To reproduce after an edit:

```powershell
python phase2/docs/algorithm/render_math.py
python phase2/docs/algorithm/assemble_spec.py
python phase2/docs/algorithm/render_math.py --check
python phase2/tests/verification/test_algorithm_math.py
python phase2/docs/algorithm/check_spec.py --seal
python phase2/docs/algorithm/check_spec.py
```

Review changed formulas in a Markdown preview before sealing. The seal records reviewed bytes and does not by itself prove visual or mathematical correctness.
