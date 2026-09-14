# Changelog

## Unreleased

- Implemented synchronous M10K frame/history/OLA stores, a registered seven-clock butterfly, and explicit RAM port schedules while retaining the arithmetic rounding boundaries.
- Replaced whole-payload telemetry movement with ownership slots and streamed DDR record construction from RAM.
- Added fail-stop live-source continuity, physical stop acknowledgement, coherent source-health CSR counters, and explicit rearm.
- Added a Linux 6.12.109 board source baseline, static reserved-memory/device nodes, a read-only noncached ring driver, persistent codec-mux GPIO ownership, and paired systemd units.
- Added codec/ADC physical timing allocations, bounded audio CDC routes, synchronized I2C ACK capture, and a production-only RTL elaboration command.

- Consolidated the Phase 2 implementation and reconciled reference source into one repository with a single canonical integrated specification.
- Reworked the project overview and architecture documentation around the engineering question, core deliverable, component ownership, and remaining design decisions.
- Clarified that suppression and retained spectral-energy ratios are representation metrics; the baseline does not claim measured power savings or runtime precision scaling.
- Added contributor guidance and separated active source documentation from historical Phase 1 and C0 revision material.
- Made threshold configuration belong to an admitted frame through an ordered metadata queue, preventing a later CSR update from splitting that frame's mask decisions.
- Separated button-paced ADC diagnostics from continuous DSP acquisition and reset the DSP epoch when switching between those acquisition modes.
- Bound runtime profiles to synthesized FPGA parameters and HPS startup arguments, with paired effective-configuration manifests and a source-owned Quartus project entry point.
- Disabled optional LINE-OUT by default and distinguished unavailable sample-rate metadata from a periodic acquisition rate.
- Tightened direct reference CLI configuration handling, loaded the existing coefficient files, and separated immutable input metadata from newly generated run outputs.
- Added source-generated reference configuration bindings, portable CMake presets, source-hygiene tooling, and a GitHub workflow limited to source checks and host builds.
- Excluded local environments, credentials, tool output, and captures from source distribution while preserving existing coefficient, input-vector, and reference-output bytes.

This entry records repository and design work. It does not announce hardware completion or new verification results. Detailed reference-model changes are maintained with that component.
