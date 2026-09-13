// AUTO-GENERATED - DO NOT EDIT
// Generator: scripts/gen_headers.py
// Generator version: r1.2.0
// Source manifest: spec/generated/gen_manifest.json

package trecap_iface_pkg;

  import trecap_core_pkg::*;
  import trecap_packet_pkg::*;

  // Primitive aliases.
  typedef logic signed [T_SAMPLE_W-1:0] trecap_sample_data_t;
  typedef logic [63:0] trecap_sample_idx_t;
  typedef logic [63:0] trecap_frame_idx_t;
  typedef logic [T_MAG2_W-1:0] trecap_thr2_t;
  typedef logic signed [15:0] trecap_wave_i16_t;
  typedef logic [15:0] trecap_u16_t;
  typedef logic [31:0] trecap_u32_t;
  typedef logic [63:0] trecap_u64_t;

  // Shared enums.
  typedef enum logic [15:0] {
    TPKT_WAVE                    = 16'h0001,
    TPKT_SPEC64                  = 16'h0002,
    TPKT_SPEC129                 = 16'h0003,
    TPKT_METRICS                 = 16'h0004,
    TPKT_STATUS                  = 16'h0005,
    TPKT_PEAKS                   = 16'h0006,
    TPKT_DEBUG                   = 16'h007e,
    TPKT_WRAP                    = 16'h007f
  } trecap_packet_type_e;

  typedef enum logic [1:0] {
    TSRC_BRAM_REPLAY             = 2'd0,
    TSRC_ADC_LIVE                = 2'd1,
    TSRC_AUDIO_WRAPPER           = 2'd2,
    TSRC_DIAGNOSTIC              = 2'd3
  } trecap_source_mode_e;

  typedef enum logic [1:0] {
    TSPEC_DISABLED               = 2'd0,
    TSPEC_SPEC64                 = 2'd1,
    TSPEC_SPEC129                = 2'd2
  } trecap_spec_mode_e;

  // Shared packed structs.
  typedef struct packed {
    logic                                  valid;
    logic signed [T_SAMPLE_W-1:0]          data;
    logic [63:0]                           sample_idx;
  } trecap_sample_t;

  typedef struct packed {
    logic                                  valid;
    logic [63:0]                           frame_idx;
    logic [63:0]                           trigger_sample_idx;
  } trecap_frame_event_t;

  typedef struct packed {
    logic [31:0]                           unique_bins;
    logic [31:0]                           unique_suppressed_bins;
    logic [31:0]                           eligible_unique_bins;
    logic [31:0]                           eligible_suppressed_bins;
    logic [63:0]                           eligible_kept_mag2_lo;
    logic [63:0]                           eligible_total_mag2_lo;
    logic                                  mag2_truncated;
  } trecap_frame_stats_t;

  typedef struct packed {
    logic signed [15:0]                    xdel;
    logic signed [15:0]                    yout;
    logic signed [15:0]                    err;
  } trecap_wave_triplet_t;

  typedef struct packed {
    logic                                  valid;
    trecap_packet_type_e                   packet_type;
    logic [15:0]                           flags;
    logic [31:0]                           seq;
    logic [63:0]                           timestamp;
    logic [15:0]                           payload_bytes;
    logic [1:0]                            drop_priority;
  } trecap_record_meta_t;

  typedef struct packed {
    logic                                  valid;
    logic signed [T_SAMPLE_W-1:0]          x_delayed;
    logic signed [T_SAMPLE_W-1:0]          y_out;
    logic signed [15:0]                    error_i16;
    logic [63:0]                           sample_idx;
  } trecap_core_tap_sample_t;

  typedef struct packed {
    logic                                  valid;
    logic [63:0]                           frame_idx;
    trecap_frame_stats_t                   stats;
  } trecap_core_tap_frame_t;

  typedef struct packed {
    logic                                  telemetry_enable;
    logic                                  ring_writer_enable;
    logic                                  clear_metrics_w1p;
    logic [T_MAG2_W-1:0]                   thr2_active;
    logic [31:0]                           packet_enable;
    logic [15:0]                           wave_decim;
    trecap_spec_mode_e                     spec_mode;
    logic [5:0]                            spec_shift;
    trecap_source_mode_e                   source_mode;
  } trecap_hps_bridge_ctrl_t;

  typedef struct packed {
    logic                                  configured;
    logic [63:0]                           base_addr;
    logic [31:0]                           size_bytes;
    logic [31:0]                           size_mask;
  } trecap_ring_config_t;

endpackage : trecap_iface_pkg
