# Baseline PDF page 089

Historical Part III, repository architecture. Printed page 76. [Original PDF page](../../specs/t_recap_phase2_integrated_spec.pdf#page=89).

[Previous](page-088.md) | [Index](../README.md) | [Next](page-090.md)

**Table 40. Top-level build variants.**

| Top module | Purpose |
| --- | --- |
| `trecap_core_only_top.sv` | Pure core wrapper. No board pins, HPS bridge, DDR writer, Ethernet, dashboard, or telemetry transport. |
| `trecap_core_bram_replay_top.sv` | BRAM replay source plus core plus artifact-facing outputs. Used for first core implementation cut. |
| `trecap_core_telemetry_top.sv` | Core plus telemetry packetizers and packet FIFO, but no DE1-SoC physical pins or Platform Designer boundary. |
| `trecap_de1soc_full_top.sv` | Full board top with Platform Designer/HPS, audio/ADC wrappers, telemetry bridge, and board pins. |


## 40 Dependency Rules

The allowed dependency graph is:

```text
rtl/include      -> no RTL dependencies
rtl/common       -> rtl/include
rtl/interfaces   -> rtl/include
rtl/sources      -> rtl/include, rtl/common, rtl/interfaces
rtl/fft          -> rtl/include, rtl/common, rtl/interfaces
rtl/core         -> rtl/include, rtl/common, rtl/interfaces, rtl/fft
rtl/telemetry    -> rtl/include, rtl/common, rtl/interfaces, core tap typedefs
rtl/hps_bridge   -> rtl/include, rtl/common, rtl/interfaces, telemetry record typedefs
rtl/platform     -> all RTL layers, board-specific only
rtl/top          -> integration only; may instantiate rtl/sources, rtl/core, rtl/
    telemetry, rtl/hps_bridge, and platform wrappers
```

Forbidden dependencies:

- rtl/core/ shall not import rtl/telemetry/, `rtl/hps_bridge/`, or rtl/sources/.

- rtl/core/ shall not know packet type IDs, UDP payload layout, or DDR ring layout.

- rtl/telemetry/ shall not contain `trecap_ddr_ring_writer.sv`.

- sw/golden/ shall not depend on sw/hps/ or `sw/pc_dashboard/`.

- sw/hps/ shall not implement signal-processing algorithms.

- `sw/pc_dashboard/` shall not be used as a core correctness authority.

- Switches, LEDs, HEX displays, GPIO pins, audio codec pins, and HPS CSR ports shall terminate only in rtl/platform/ or rtl/top/. No hidden board-demo logic is allowed inside rtl/core/.
