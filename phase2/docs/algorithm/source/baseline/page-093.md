# Baseline PDF page 093

Historical Part III, repository architecture. Printed page 80. [Original PDF page](../../../specs/t_recap_phase2_integrated_spec.pdf#page=93).

[Previous](../../baseline/page-092.md) | [Index](../../README.md) | [Next](../../baseline/page-094.md)

```text
  trecap_hps_config.h     // non-generated runtime-config API
src/
  trecap_udp_streamer.c
  csr_map.c
  ring_reader.c
  udp_sender.c
  command_server.c
  status_patch.c
  config.c
config/
  trecap_hps_config.json
scripts/
  setup_static_ip.sh
  run_udp_streamer.sh
  reserve_ddr_region_notes.md
```

The generated HPS headers shall exist only under sw/hps/include/generated/. Non-generated C files may include them, but shall not duplicate their CSR offsets, bit masks, packet IDs, or payload-size constants.

### 43.3 HPS runtime configuration manifest

The HPS streamer shall read a configuration manifest instead of scattering physical addresses and UDP ports across source files.

```json
{
    "csr_base_phys": "0xff200000",
    "csr_span_bytes": 4096,
    "ring_base_hps_phys": "0x3e000000",
    "ring_base_fpga": "0x3e000000",
    "ring_size_bytes": 33554432,
    "telemetry_dst_ip": "192.168.10.1",
    "telemetry_dst_port": 5005,
    "command_listen_port": 5006,
    "trusted_command_peer": "192.168.10.1",
    "transport_version_major": 1,
    "transport_version_minor": 7
}
```

### 43.4 PC dashboard software

```text
sw/pc_dashboard/
  generated/
    trecap_packet.py        // generated packet constants and parser helpers
  packet_parser.py
  dashboard.py
  ring_buffers.py
  plots.py
  command_client.py
  config.py
  configs/
```
