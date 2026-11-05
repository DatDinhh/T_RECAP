# Baseline PDF page 083

Historical Part III, repository architecture. Printed page 70. [Original PDF page](../../specs/t_recap_phase2_integrated_spec.pdf#page=83).

[Previous](page-082.md) | [Index](../README.md) | [Next](page-084.md)

[Edit Markdown and LaTeX source](../source/baseline/page-083.md). Equations are rendered locally as SVG.

```systemverilog
typedef enum logic [15:0] {
  TPKT_WAVE    = 16'h0001,
  TPKT_SPEC64 = 16'h0002,
  TPKT_SPEC129 = 16'h0003,
  TPKT_METRICS = 16'h0004,
  TPKT_STATUS = 16'h0005,
  TPKT_WRAP    = 16'h007f
} trecap_packet_type_e;

typedef struct packed {
  logic                      valid;
  trecap_packet_type_e       packet_type;
  logic [15:0]               flags;
  logic [31:0]               seq;
  logic [63:0]               timestamp;
  logic [15:0]               payload_bytes;
  logic [1:0]                drop_priority;
} trecap_record_meta_t;
```

The packet FIFO shall carry `trecap_record_meta_t` plus payload bytes. If an implementation stores payload bytes in a separate RAM, metadata and payload commit shall remain atomic at the record boundary. Internal Revision G metadata may store `payload_bytes` in 16 bits because every legal Revision G UDP datagram satisfies 32 + Pbytes ≤ 1200, so `payload_bytes` is at most 1168. The 32-bit DDR/UDP header field shall zero-extend this internal value. The `drop_priority` field is normative when priority-based telemetry shedding is implemented: priority 0 is lowest and is dropped first for WAVE. Priority 1 is used for SPEC64/SPEC129. Priority 2 is used for METRICS. Priority 3 is highest and is dropped last for STATUS. The packet FIFO admission logic shall use this field to evict or shed lower-priority records, or shall reserve enough high-priority capacity to satisfy the admission guarantee in Section 13.3.

### 36.4 Core tap interface rule

Telemetry taps observe the core. They do not control the core.

```text
core output tap_sample_valid
core output tap_x_delayed
core output tap_y_out
core output tap_error
core output tap_sample_idx

core output tap_frame_valid
core output tap_frame_idx
core output tap_mag2_unique_bins
core output tap_mask_unique_bins
core output tap_frame_stats
```

No telemetry signal shall drive a ready signal into the core sample path, frame scheduler, FFT/IFFT path, WOLA path, or metrics accumulator.
