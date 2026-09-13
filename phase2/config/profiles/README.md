# T-RECAP runtime and build profiles

File class: **[1] hand-written runtime/build configuration**.

This directory implements Section 44 of the integrated Phase 2 specification. The five build
profiles select a build target, input binding, board/runtime dependencies, and one reusable
telemetry preset:

```text
baseline_core.json
sim_core_only.json
de1soc_bram_replay.json
de1soc_linein_demo.json
de1soc_adc_demo.json
```

The two telemetry presets contain only Revision-G runtime controls:

```text
telemetry_status_only.json
telemetry_full_demo.json
```

Validate the complete inventory with:

```bash
make check-profiles
```

Inspect the normalized settings that a build profile resolves to with:

```bash
python3 scripts/check_profiles.py \
  --profile config/profiles/de1soc_bram_replay.json \
  --print-effective
```

## Ownership rule

Profiles reference these sources of truth:

```text
spec/generated/core_config.json
spec/generated/csr_map.json
spec/generated/packet_layouts.json
platform/de1soc/address_map/hps_bridge_regions.json
sw/hps/config/trecap_hps_config.json
```

Profiles must not copy or override core constants (`N`, `L`, `P`, `H`, `F`, `G`, `D`, `THR2`,
fixed-point widths), CSR offsets, packet IDs, payload layouts, or DDR addresses. In particular,
`SPEC64` and `SPEC129` are display packet formats; they are not alternate FFT sizes.

`de1soc_bram_replay.json` references the current platform address-map source instead of claiming
that the bootstrap DDR/CSR addresses have been proven. Those addresses remain provisional until
the real Platform Designer `system.sopcinfo` is generated and reconciled.

## Canonical names and safety defaults

- Profile source names follow the generated contract: `bram_replay`, `adc_live`,
  `audio_wrapper`, and `diagnostic_source`. The informal alias `audio` is rejected.
- `PEAKS` and `DEBUG` are reserved-disabled in Telemetry Revision G and are rejected.
- Revision-G command version 1 has no HPS/PC replay-start command. Step 14 adds
  `START_BRAM_REPLAY` only in explicit command version 2; profiles still cannot
  auto-select a network request.
- The generated transport/CSR capability is major 1, minor 8. The telemetry
  common-header version remains 1.
- The DE1-SoC BRAM profile declares a nominal 48 ksample/s demo rate. Both valid and ready
  acceptance for BRAM replay are gated by the Step-10 exact-average fractional board sample
  clock enable. That source cadence is still not measured codec/ADC or hardware timing evidence.
- The DDR ring may be enabled only after the base/size configuration and the initial `Rd=0`
  commit are complete.
- The LINE-IN profile freezes 48 ksample/s, signed 16-bit codec input, the left channel,
  a reviewed 12.288 MHz master clock, and line-out disabled.
- The ADC profile freezes the DE1-SoC LTC2308 at 100 ksample/s, a 2.5 MHz serial
  clock, unsigned straight-binary 12-bit samples recentered at code 2048, single-
  ended/unipolar/awake operation, DC blocking disabled, and `SW[6:4]` channel
  selection latched only on entry to the `adc_live` source epoch. It uses full
  telemetry but does not change the default BRAM-replay profile.

The profiles are validated and recorded by the build entry point. Later architecture steps still
have to bind the normalized settings to Quartus parameters and HPS CSR initialization; a JSON file
cannot alter synthesized RTL by itself.
