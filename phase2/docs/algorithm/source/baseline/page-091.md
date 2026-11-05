# Baseline PDF page 091

Historical Part III, repository architecture. Printed page 78. [Original PDF page](../../../specs/t_recap_phase2_integrated_spec.pdf#page=91).

[Previous](../../baseline/page-090.md) | [Index](../../README.md) | [Next](../../baseline/page-092.md)

`hps_config.tcl` `generate_system.sh` `address_map/` `address_map.md` `hps_bridge_regions.json` `sopcinfo_location.md` `generated_notes/` `generated_files_readme.md`

constraints/de1soc/ de1soc.qsf de1soc.sdc `pin_assignments.tcl` clocks.sdc

### 42.2 Platform Designer generated-artifact policy

Platform Designer generated output directories shall not be hand-edited. The repository shall either commit the generated wrapper files needed for the Quartus build or provide a deterministic `platform_designer.tcl` flow that regenerates them. Revision D selects the practical senior-project policy:

- commit `platform_designer.tcl`, `hps_config.tcl`, and system.qsys once stable.

- commit .sopcinfo if HPS software or address-map scripts consume it.

- commit generated wrapper HDL only if the Quartus project directly depends on it.

- document the selected generated-file policy in `platform/de1soc/generated_notes/generated_files_readme.md`.

- never manually edit generated Platform Designer HDL.

### 42.3 Bridge assumptions

The implementation assumes:

- HPS Ethernet is used for the final dashboard transport.

- HPS-to-FPGA lightweight bridge or equivalent CSR bridge exposes CSR registers to HPS software.

- FPGA-to-HPS SDRAM bridge or equivalent FPGA-side master path allows `trecap_ddr_ring_writer.sv` to write to HPS DDR.

- `RING_BASE` is an FPGA-visible bus address, not a Linux userspace virtual address.

- HPS software is responsible for translating reserved/allocated DDR physical addresses into the FPGA-visible address required by the platform integration.
