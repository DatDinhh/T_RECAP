# Baseline PDF page 073

Historical Part III, repository architecture. Printed page 60. [Original PDF page](../../../specs/t_recap_phase2_integrated_spec.pdf#page=73).

[Previous](../../baseline/page-072.md) | [Index](../../README.md) | [Next](../../baseline/page-074.md)

## Part III - Core Implementation Repository Architecture

Part III translates the frozen core and telemetry contracts into an implementation repository. It defines the tree, generated shared contracts, filelists, RTL layer ownership, HPS and PC software layout, build profiles, coefficient ROM ownership, memory primitive rules, and staged implementation cuts. It deliberately excludes verification architecture, which will be specified separately after the implementation repository is frozen.

## 31 Repository Architecture Executive Summary

Phase 2 is an implementation project, not a single demonstration file. The final system has a deterministic FPGA STFT/WOLA core, a frozen artifact flow, a non-stalling telemetry path, an HPS-mediated Ethernet path, and a PC dashboard. The repository must therefore separate implementation ownership before code begins. Revision D keeps the scope focused on the core implementation repository. It adds the implementation discipline needed before substantial RTL is written. Verification directories, scoreboards, regression hierarchy, assertion packages, and testbench inventory remain intentionally deferred. This revision adds source-of-truth filelists, generated-file commit rules, module API and naming rules, clock/reset ownership, compile-only smoke checks, Platform Designer artifact policy, runtime profile separation, coefficient ROM ownership, memory primitive policy, top-level build variants, and a core-first implementation cut. It also fixes three consistency issues before freeze: generated software header paths, minimum documentation inventory, and the distinction between the core-first implementation cut and the first full-demo scope. The design rule is unchanged:

The FPGA fabric owns all real-time signal processing. The HPS performs transport and control only. The PC visualizes and sends commands only. BRAM replay remains the correctness signoff path.

This document adds the following implementation-critical decisions:

1. `trecap_ddr_ring_writer.sv` belongs to `rtl/hps_bridge/`, not rtl/telemetry/. Telemetry produces formatted records. The HPS bridge writes records to DDR.

2. CSR maps, packet layouts, core constants, and cross-language packet definitions shall be generated from one source of truth under spec/generated/.

3. The CSR map is normative, not recommended. RTL, HPS C code, and Python dashboard code shall consume generated headers from the same schema.

4. Core SystemVerilog interfaces and typedefs shall be frozen in generated or checked packages before packetizers and bridge logic are implemented.

5. DE1-SoC Platform Designer, address-map, and constraint files have explicit ownership under rtl/platform/de1soc/ and constraints/de1soc/.

6. HPS physical address mapping and UDP target configuration shall be captured in a runtime manifest, not hard-coded in multiple files.
