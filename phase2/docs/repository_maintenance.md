# Repository maintenance

We keep the mathematical reference, FPGA implementation, HPS transport, dashboard,
and specification in one repository so that each design change has a reviewable
context. `sw/reference_model/` is the only maintained reference source tree.

## Consolidated source baseline

The source package contained an implementation tree and a separate reference
package. Their C++ core sources and public headers were byte-identical. The
implementation copy included additional artifact and configuration tooling fixes,
so we retained it as the maintained reference and preserved the original reference
license. The supplied specification copies were identical; the authoritative copy
is listed in [the specification index](specs/README.md).

Historical package labels and `trecap_golden` identifiers remain where changing
an identifier would break compatibility. They do not indicate golden-model status.
Existing coefficient tables, vectors and reference outputs remain historical
reference artifacts. Editing source does not automatically regenerate or promote
those artifacts.

The v3 import manifest uses historical `embedded_proxy` terminology for a source
tree whose original ZIP bytes are not being claimed. A current source snapshot
records the maintained tree, while Git history records subsequent changes. The
source's availability and its status as a reference model are independent of
whether an original archive is available.

## What belongs in Git

We commit source code, readable design documents, the project specification,
reviewed configuration, generated interface headers and small reference artifacts.
We exclude local virtual environments, compiler output, Quartus-generated output,
simulator libraries, raw captures, logs, credentials and editor state.

We preserve reference artifact bytes with `.gitattributes`. A formatter must not
rewrite `.memh`, CSV, manifests or generated contracts merely to normalize style.
Regenerate contracts through their owning generator when the source changes.

Personal tool-installation paths belong in environment variables or explicit
command-line arguments. The checked-in private-network addresses are documented
DE1-SoC direct-link defaults, not credentials or a deployed network inventory.
Team attribution and the specification's authorship are retained. The adapted
Linux board DTS retains its GPL-2.0+ license and Altera copyright; see the
[platform notices](../platform/de1soc/linux/THIRD_PARTY_NOTICES.md).

## Local checks

Run `python scripts/repo_hygiene.py` before preparing a commit. It parses Python,
JSON and TOML sources, checks relative Markdown links, finds common credential
patterns and machine-specific paths, and reports portable-path conflicts. It does
not execute project code or functional tests. Pattern scanning has limited coverage;
review the proposed commit contents as well.

In a Git checkout, the hygiene scan checks tracked files and unignored new
files; tracked build products remain findings. Reviewed CPU qualification
logs are still scanned as text, and presentation XML is inspected for local
paths and credential patterns. Run `python tests/verification/test_repo_hygiene.py`
to check these publication safeguards with disposable fixtures.

The optional local pre-commit hook runs this same command. Build the software with
`cmake --preset host` and `cmake --build --preset host`; the presets disable tests.
The Linux `hps` preset adds the transport executable. The optional pinned
`pyslang` frontend elaborates production RTL through
`python scripts/elaborate_rtl_sources.py`; vendor IP remains external.

Use `python scripts/record_source_snapshot.py` after an intentional reference
source update to refresh its byte inventory. This records source identity and
checks that copied reference contracts/artifacts still match their originals;
it does not generate new model outputs or establish numerical correctness.

## Publication

The canonical GitHub repository is [DatDinhh/T_RECAP](https://github.com/DatDinhh/T_RECAP),
with this maintained source tree under `phase2/`. The existing local publication
checkout is under `build/github-publish-20260914/`, which is ignored by this
source tree. Preserve its Git history and review the intended `phase2/` diff
before committing with the team's normal Git identity. Run the source checks
from the `phase2/` directory. Do not include local build or execution logs as
project evidence without describing how they were made; the reviewed CPU
qualification exports are an explicit published-evidence exception.
