# Baseline PDF page 081

Historical Part III, repository architecture. Printed page 68. [Original PDF page](../../specs/t_recap_phase2_integrated_spec.pdf#page=81).

[Previous](page-080.md) | [Index](../README.md) | [Next](page-082.md)

[Edit Markdown and LaTeX source](../source/baseline/page-081.md). Equations are rendered locally as SVG.

1. Generated SV/C/Python headers shall be committed under rtl/include/generated/, sw/hps/ include/generated/, `sw/pc_dashboard/generated/`, and sw/golden/generated/.

2. `scripts/gen_headers.py` shall emit `spec/generated/gen_manifest.json` containing source schema hashes, generator version, generated output paths, and generated output hashes.

3. make check-generated shall regenerate all headers and fail if any regenerated output differs from the checked-in generated file.

4. Generated files shall contain a header banner: AUTO-GENERATED - DO NOT EDIT.

5. Manual edits to generated files are invalid. Required changes shall be made in the schema and regenerated.

### 35.5 Generated filelists

SystemVerilog compile order is part of the implementation contract. Packages must compile before interfaces, interfaces before modules, and core modules before integration tops. Therefore, compile/build order shall be generated, not guessed manually.

**Table 31. Required generated filelists.**

| Filelist | Purpose |
| --- | --- |
| `filelists/rtl_core.f` | Core packages, common helpers, interfaces, source adapter stubs, and partial core modules. This is a skeleton smoke filelist when FFT is separated. It is not sufficient for Cut C0 signoff. |
| `filelists/rtl_core_plus_fft.f` | Core filelist plus FFT/IFFT modules or wrappers. |
| `filelists/rtl_telemetry.f` | Core tap typedefs plus telemetry packet scheduler, packetizers, and packet FIFO. |
| `filelists/rtl_hps_bridge.f` | Generated packages, telemetry record types, CSR bank, ring pointer control, record builder, and DDR ring writer. |
| `filelists/rtl_de1soc_full.f` | Full DE1-SoC top-level build including platform wrappers and Platform Designer boundary. |
| `filelists/quartus_de1soc.qsf.inc` | Generated or maintained Quartus file assignment include for the DE1-SoC build. |


`scripts/gen_filelists.py` owns these outputs. No compile or synthesis flow shall rely on hand-written source ordering outside these filelists. If a module is not present in the proper filelist, it is not part of that build cut. Cut C0 shall use `filelists/rtl_core_plus_fft.f`. `Filelists/rtl_core.f` is only a partial skeleton smoke target when FFT/IFFT files are separated.

### 35.6 Normative CSR map rule

The CSR map is normative. It shall not be described as recommended in the implementation repository. If a CSR offset, bit, access semantic, or reset value differs from `csr_map.json`, the implementation is out of contract.
