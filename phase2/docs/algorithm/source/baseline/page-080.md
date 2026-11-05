# Baseline PDF page 080

Historical Part III, repository architecture. Printed page 67. [Original PDF page](../../../specs/t_recap_phase2_integrated_spec.pdf#page=80).

[Previous](../../baseline/page-079.md) | [Index](../../README.md) | [Next](../../baseline/page-081.md)

**Table 29. Generated-contract schema files.**

| File | Purpose |
| --- | --- |
| `core_config.json` | Core parameters, widths, artifact row-count names, source-mode IDs, and default baseline configuration. |
| `csr_map.json` | Normative CSR offsets, access type, reset value, bit fields, write semantics, and ownership. |
| `packet_layouts.json` | Normative DDR/UDP packet types, header fields, payload byte sizes, payload field offsets, and packet-specific flags. |
| `interface_types.json` | Shared SystemVerilog interface and struct field definitions used by core, telemetry, and HPS bridge layers. |
| `gen_manifest.json` | Generation metadata, generator version, expected output files, and hashes of generated headers. |


### 35.3 Generated outputs

The script `scripts/gen_headers.py` shall generate the files listed in Table 30. Generated files shall contain a banner stating that they are generated and shall not be hand-edited.

**Table 30. Generated header outputs.**

| Generated file | Consumer |
| --- | --- |
| `rtl/include/generated/trecap_core_pkg.sv` | Core constants, widths, source-mode IDs, delay parameters, and artifact-related constants. |
| `rtl/include/generated/trecap_csr_pkg.sv` | CSR offsets, bit positions, reset values, access semantics, and transport VERSION values. |
| `rtl/include/generated/trecap_packet_pkg.sv` | Packet type IDs, payload sizes, max packet lengths, flag bits, and STATUS layout constants. |
| `rtl/include/generated/trecap_iface_pkg.sv` | Shared packed structs for sample, frame, mask stats, metrics, record metadata, and HPS bridge control. |
| `sw/hps/include/generated/trecap_csr.h` | HPS C CSR offsets, bit masks, VERSION fields, and command-safe constants. |
| `sw/hps/include/generated/trecap_packet.h` | HPS C packet IDs, header layout, payload offsets, and exact payload sizes. |
| `sw/pc_dashboard/generated/trecap_packet.py` | Python packet constants, struct formats, payload sizes, and parser validation fields. |
| `sw/golden/generated/trecap_config.py` | Golden-model constants derived from the same core schema. |


### 35.4 Generated-file commit policy

Revision D uses the senior-project practical policy. Generated headers are checked into the repository. The repository also keeps the schema files that produce them. This avoids Quartus, HPS, and dashboard builds failing because a generated file was absent, while still making regeneration deterministic.
