# Reference source history and artifact ownership

This file retains the context of the earlier v69 source/hash-chain repair. The
current repository contains the reconciled software reference source at
`sw/reference_model/` and the integrated specification at
`docs/specs/t_recap_phase2_integrated_spec.pdf`. See the
[specification index](../specs/README.md) and
[repository maintenance guide](../repository_maintenance.md) for the current
source and document policy.

## What the earlier repair addressed

Earlier source packaging changed line endings and some development tooling.
The associated source/artifact manifests needed to describe those actual bytes,
rather than retaining hashes from a different package. The repair distinguished
source identity from the logical integer-vector hashes used for coefficient,
input, and output memory artifacts.

Historical archive records described an incomplete ZIP. That observation does
not establish provenance for the current reconciled directory snapshot and does
not imply that the current repository is waiting for a missing PDF or ZIP. We
retain source identity only to the level supported by the recorded manifests.

## Current ownership

- `sw/reference_model/` owns reference arithmetic and its artifact tooling.
- `artifacts/coefficients/`, `artifacts/test_vectors/`, and
  `artifacts/reference_outputs/` contain the root-facing promoted artifacts.
- `config/reference_import_promotions.json` describes the promoted paths.
- Reference-import manifests record the corresponding source and promoted files.

A source update must preserve these relationships and document intentional
changes to configuration, arithmetic, coefficient handling, or artifact
production. Do not overwrite an expected-output set and keep an unrelated
manifest, or describe a filesystem-byte hash as proof of numerical correctness.

## Terminology and limits

We use **reference model** for the software package. Compatibility names such as
`phase2_golden_model` and internal `artifacts/golden/` directories remain where
required by existing APIs and tools. A release label or internally consistent
hash chain does not establish agreement with RTL or operation on a physical
board. Those remain separate project milestones.

The earlier C0 runner and artifact notes are retained as development history.
Their recorded outputs are not new results for the current integrated source.
