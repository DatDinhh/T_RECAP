# Baseline PDF page 082

Historical Part III, repository architecture. Printed page 69. [Original PDF page](../../specs/t_recap_phase2_integrated_spec.pdf#page=82).

[Previous](page-081.md) | [Index](../README.md) | [Next](page-083.md)

All CSR consumers - SystemVerilog CSR bank, HPS C code, and Python command tooling - shall use generated definitions from `csr_map.json`. Hand-coded duplicated CSR offsets are not allowed outside generated headers.

## 36 SystemVerilog Interface and Typedef Baseline

### 36.1 Package organization

The minimum package set is:

```text
rtl/include/
  generated/
    trecap_core_pkg.sv        // generated core parameters and widths
    trecap_csr_pkg.sv         // generated CSR constants
    trecap_packet_pkg.sv      // generated packet constants
    trecap_iface_pkg.sv       // generated or schema-checked typedefs
  trecap_math_pkg.sv          // hand-written fixed-point helper declarations if needed
  trecap_build_pkg.sv         // optional hand-written wrappers around generated
    constants
```

### 36.2 Core sample and frame typedefs

The exact field names may be generated from `interface_types.json`, but the following shapes are the baseline contract.

```systemverilog
typedef struct packed {
  logic                         valid;
  logic signed [T_SAMPLE_W-1:0] data;
  logic [63:0]                  sample_idx;
} trecap_sample_t;

typedef struct packed {
  logic        valid;
  logic [63:0] frame_idx;
  logic [63:0] trigger_sample_idx;
} trecap_frame_event_t;

typedef struct packed {
  logic [31:0] unique_bins;
  logic [31:0] unique_suppressed_bins;
  logic [31:0] eligible_unique_bins;
  logic [31:0] eligible_suppressed_bins;
  logic [63:0] eligible_kept_mag2_lo;
  logic [63:0] eligible_total_mag2_lo;
  logic        mag2_truncated;
} trecap_frame_stats_t;
```

### 36.3 Telemetry record typedefs
