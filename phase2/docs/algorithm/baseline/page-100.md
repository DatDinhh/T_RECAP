# Baseline PDF page 100

Historical Part III, repository architecture. Printed page 87. [Original PDF page](../../specs/t_recap_phase2_integrated_spec.pdf#page=100).

[Previous](page-099.md) | [Index](../README.md) | [Next](page-101.md)

[Edit Markdown and LaTeX source](../source/baseline/page-100.md). Equations are rendered locally as SVG.

### 51.2 First full-demo scope after C0/T0

The first full-demo implementation begins after C0 is stable and after the transport cut T0 is explicitly opened. These items are required for the first complete board demonstration, but they are not the first code to write.

- Telemetry packetizers for STATUS, WAVE, METRICS, and one spectrum mode.

- HPS bridge with normative CSR map, DDR record builder, and DDR ring writer.

- HPS UDP streamer and runtime config manifest.

- PC dashboard parser and plots.

- PC command path for THR2 and packet-enable control.

- LINE-IN wrapper for controlled audio demo.

### 51.3 Deferred

- Verification repository architecture.

- Scoreboards, monitors, coverage, and regression hierarchy.

- PEAKS packet.

- DEBUG packet.

- CRC enable.

- Kernel DMA-coherent driver.

- Simultaneous SPEC64 and SPEC129 output.

- HPS/Linux audio path.

- PC-driven artifact signoff.

## 52 Repository Acceptance Criteria

The implementation repository is accepted when:

1. rtl/core/ can be inspected and built as a core-only layer without HPS, DDR, Ethernet, or dashboard code.

2. `trecap_ddr_ring_writer.sv` exists only under `rtl/hps_bridge/`.

3. spec/generated/ contains `csr_map.json`, `packet_layouts.json`, `core_config.json`, and `interface_types`. json.

4. `scripts/gen_headers.py` generates SystemVerilog, C, and Python constants from the same schemas.

5. CSR offsets and packet payload sizes are not hand-coded independently in RTL, HPS C, and Python.

6. platform/de1soc/ includes Platform Designer/Qsys ownership files and an address-map document.
