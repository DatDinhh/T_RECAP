# Reader-facing prose revision

This publication revision replaces prose semicolons, en dashes and em dashes with ordinary sentences, commas or written ranges. It covers authored Markdown, HTML body text and the retained TSH2 atlas descriptions. The verification report sources and rebuilt PDFs have their own current publication manifests.

The revision does not change RTL, C/C++ software, test stimulus, expected numerical results or recorded board observations. Fenced commands, inline code, link destinations and numeric tokens were compared before and after the Markdown edits. Executable punctuation and the original third-party legal notice remain intact.

## Traceability

[The editorial ledger](manifest.json) records each document's original and current SHA-256. Original document bytes are recoverable from Git commit `07bc8224aa080c8eaa1b77b4603c118d853465d0`. It also identifies current publication inventories that were refreshed after the prose changed. The TSH2 atlas images were regenerated from the edited descriptions with the existing renderer.

Four duplicate verification previews in the project overview now use the pastel portfolio drawings. The ledger records the previous preview hash and the exact current portfolio source for each copy. The historical figure provenance and measured result data remain unchanged.

Historical fitted-source manifests, registered plans, proof receipts, simulation receipts, captured data and original source hashes remain unchanged. Those hashes identify the versions used when the experiments ran. They must not be replaced with hashes of later editorial revisions. For example, the current UVM and formal package inventories bind their current README files while the execution receipts continue to identify the original executed packages.

The imported reference proxy was refreshed with its supported `refresh-proxy` command. This updates a maintained reference inventory. It does not verify the original source archive or claim another verification run.

## Reproduce the prose check

Run from the repository root.

```text
python phase2/docs/editorial/20261104-prose/check_prose.py --repo-root . --check-ledger
```

The checker scans authored Markdown, RST, LaTeX prose and HTML text nodes. It reports every remaining finding with a path and line. It protects code fences, inline code, markup, link destinations, scripts, styles, LaTeX listings and TikZ paths. The exact third-party legal exclusion is printed in the result. Raw machine records and executable source remain outside the authored prose formats.

The ledger is an editorial record of this revision. Later intentional document changes can require another editorial record. The checker does not change files or reinterpret a historical verification result.
