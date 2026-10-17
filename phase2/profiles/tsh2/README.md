# Archived TSH2 application source

This source snapshot preserves the maintained finite-file TSH2 application behind
the physical verification campaign: PCM streaming, the HPS adapter and FIFOs,
finite request service, native arithmetic and packet consumers, spectral monitor,
and local visualizer. The `work/<component>/...` layout preserves relative Python
imports and C++ includes. The original broader DDR/UDP architecture remains in
the surrounding `phase2` tree; this snapshot does not close its acceptance gaps.

For a portable, synthetic, off-board verification entry point, use
[the TSH2 DV package](../../verification/tsh2/README.md). This archived workbench is
not a turnkey board deployment or a self-contained hardware rebuild. The public
DV package supplies its own admitted fixtures and source snapshot. Public campaign
evidence is a derived review export and does not contain every original raw byte.

| Source group | Purpose |
|---|---|
| `trecap_stream8_v01` | Stream source/top, MMIO adapter/FIFOs, host validation, source-bound historical build scripts |
| `trecap_laptop_fpga_v01` | Finite TCP service and matched CPU wrappers |
| `trecap_cpu_fpga_bench_v01/cpu02`, `host02` | Frozen arithmetic included by CPU wrappers and finite MMIO client included by the service |
| `trecap_downstream8_v01`, `trecap_sparse_consumer_v01` | Native packet codecs/consumers, reference packet audit |
| `trecap_jtag_readback_v01/physical/validate_tsp1.py` | Pure off-board packet validator imported by the stream host checks |
| `trecap_ai_scheduler_v01/native` | Native full/spectral reference API; this component loads no AI model |
| `trecap_spectral_monitor_v01/native`, `trecap_spectral_monitor_v02` | Qualified native features and causal monitor revision 02 |
| `trecap_monitor_board_v01` | Input preparation and off-board monitor/capture analysis |
| `trecap_visualizer_v01` | Local UI, queue/data/hardware contracts, fake-hardware tests, read-only probe source |

## Reproduction boundaries

The preserved scripts refer to archived `outputs/` receipts, coefficients, input
audio, native DLL qualification, fitted image/HPS handoff, and toolchain paths.
Those generated artifacts and vendor dependencies are deliberately absent here.
Do not substitute unrelated binaries or regenerate coefficients and claim the
original source-bound result. Original build scripts are retained for review,
not advertised as portable commands. Python components additionally depend on
NumPy and, for selected preparation paths, SciPy; native builds used C++20/MSVC.
The service/probe shell builders now require `TSH2_ARM_DEPS` to identify an
externally provided cross-toolchain root; the original personal path was removed.

The local visualizer's `hardware.py` includes an explicit historical `provision`
operation and admission checks because server/fake-hardware tests import its
contract. It is not an endorsed deployment entry point. The UART executor,
runtime plans, board programming, boot images, deploy/launch scripts and stored
session identities are omitted. Any future board execution requires a freshly
reviewed image, boot, ownership, bridge/MMIO and service admission. None of the
public verification commands invokes this archived hardware path.

The optional remote gateway, remote configuration and remote UI were excluded.
The preserved local server still contains optional remote flags/routes; they are
unsupported in this source snapshot. Use the local contract tests or the separate
recorded demonstration. Native wrappers require their missing qualified DLLs and
archived coefficients before real-capture replay can work.

No raw audio, external dataset, trained model, vendor IP, generated FPGA files,
executable, cache or private runtime plan is included. University of Iowa sample
permission and ESC-50/ESC-10 attribution distinctions are documented in the public
evidence provenance. This snapshot makes no ML training/accuracy, power, hard
real-time, full architecture closure or industrial certification claim.

## Source lineage

`source_lineage.json` records each original archive identifier and original SHA256,
the published SHA256, and any documented transformation. All RTL, C and C++ bytes
are unchanged. One Markdown command replaces a personal Python executable path
with `python`, and two shell builders require `TSH2_ARM_DEPS` instead of a personal
toolchain path; no RTL/C/C++ or contract semantics changed. The physical image remains
bound to its original 182-file manifest, not to a new unbuilt image from this tree.
Existing source copyright notices are retained; project-authored source follows
the parent project license. External platform licenses remain separate.
