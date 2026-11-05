# Baseline PDF page 084

Historical Part III, repository architecture. Printed page 71. [Original PDF page](../../specs/t_recap_phase2_integrated_spec.pdf#page=84).

[Previous](page-083.md) | [Index](../README.md) | [Next](page-085.md)

## 37 Module API, Parameter, and Naming Rules

### 37.1 Parameter ownership

1. All RTL modules shall import constants from `trecap_core_pkg.sv`, `trecap_csr_pkg.sv`, `trecap_packet_pkg.sv`, and `trecap_iface_pkg.sv` as appropriate.

2. Hard-coded duplicates of L, H, F , N , G, D, packet types, CSR offsets, payload sizes, and VERSION values are forbidden.

3. Only top-level integration modules may override public parameters. Leaf modules shall use package constants unless explicitly designed as reusable primitives.

4. A reusable primitive may be parameterized by width or depth, but it shall not internally redefine T-RECAP contract constants.

### 37.2 Port naming rules

**Table 32. RTL API and naming rules.**

| Signal class | Required naming convention |
| --- | --- |
| Clock | input logic clk. If multiple clocks exist, use suffixes such as `clk_core`, `clk_csr`, or `clk_avmm`. |
| Reset | Active-low reset named `rst_n`. Reset deassertion shall be synchronized per clock domain. |
| Valid-only taps | Use *_valid plus associated payload signals. No ready signal may return into core logic. |
| Ready/valid streams | Use `in_valid`, `in_ready`, `in_payload`, `out_valid`, `out_ready`, and `out_payload`. |
| Sample index | Use a uint64-equivalent logic [63:0] sample index. |
| Frame index | Use a uint64-equivalent logic [63:0] frame index. |
| Module names | Use trecap_* prefix except board-vendor wrappers. |
| Generated packages | Use trecap_*_pkg.sv. |


### 37.3 Coding style baseline

The implementation repository shall include `docs/architecture/coding_style.md`. The minimum style rules are:

- SystemVerilog uses logic, `always_ff` for sequential logic, and `always_comb` for combinational logic.

- Sequential logic uses nonblocking assignments. Combinational logic uses blocking assignments.

- One RTL module per file, except small typedef/package files.

- HPS C code shall include generated headers from sw/hps/include/generated/. Hardware addresses shall come from runtime config, not hard-coded literals.
