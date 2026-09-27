# Changelog

## Unreleased

- Prepared the Phase 2 source and reviewed September 2026 result packages for publication to `DatDinhh/T_RECAP`; corrected stale status text and report typography while preserving numerical evidence, historical identities, and the FFT/threshold/IFFT baseline.

- Extended verification to 20 finite input lengths with two static thresholds and output stalls; recorded [80 passing boundary cases](docs/results/verification_boundaries_20260915.md), baseline regression and checker qualification. Added supplemental reference bundles and validated compiled configuration against report metadata.

- Added native simulator, artifact, independent reference, arithmetic and finite-core verification runners with immutable evidence and deliberate checker-failure witnesses.
- Corrected signed-zero comparisons in rounded-shift RTL and shared math helpers, preserving negative rounding and saturation.
- Stopped classifying legitimate fixed-point IFFT imaginary residuals as WOLA protocol faults; exact complex comparisons remain in verification.
- Corrected the simulation assertion for delayed-history responses retained during output stalls. Recorded the scoped results in [the first verification campaign](docs/results/verification_baseline_20260915.md).

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

This entry does not announce hardware completion. Verification claims are limited to the linked executed campaigns; detailed reference-model changes are maintained with that component.
