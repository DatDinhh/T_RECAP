# Baseline PDF page 094

Historical Part III, repository architecture. Printed page 81. [Original PDF page](../../specs/t_recap_phase2_integrated_spec.pdf#page=94).

[Previous](page-093.md) | [Index](../README.md) | [Next](page-095.md)

```text
dashboard_direct_link.json
```

The generated Python packet constants shall exist under `sw/pc_dashboard/generated/`. If a short import wrapper is later added at `sw/pc_dashboard/trecap_packet.py`, that wrapper may only import from `sw/pc_dashboard/generated/trecap_packet.py`. It shall not contain a second hand-written copy of packet offsets or sizes. The dashboard shall display `dma_drop_count` and `packet_fifo_drop_count` separately. These counters identify different bottlenecks and shall not be merged in the implementation.

## 44 Runtime and Build Profiles

### 44.1 Profile separation rule

`spec/generated/core_config.json` contains normative contract constants. Runtime and demo choices shall not be mixed into that file. Runtime choices belong under config/profiles/.

```text
config/profiles/
  baseline_core.json
  sim_core_only.json
  de1soc_bram_replay.json
  de1soc_linein_demo.json
  telemetry_status_only.json
  telemetry_full_demo.json
```

### 44.2 Example profile

```json
{
    "profile_name": "de1soc_status_only_bringup",
    "source_mode": "bram_replay",
    "packet_enable": ["STATUS"],
    "spec_mode": "SPEC64",
    "wave_decim": 1,
    "sample_rate_hz": 48000,
    "transport_version_major": 1,
    "transport_version_minor": 7
}
```

Profiles may select source mode, packet enable, sample rate, dashboard defaults, and board-demo settings. They shall not redefine core arithmetic constants such as L, H, F , G, D, or packet payload layouts.

## 45 Coefficient ROM and Memory Primitive Policy

### 45.1 Coefficient ROM ownership

The coefficient artifacts are owned by the golden/tooling layer and consumed by RTL ROM wrappers.
