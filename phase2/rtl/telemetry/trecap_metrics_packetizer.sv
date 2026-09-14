// SPDX-License-Identifier: MIT
// File class: [1] hand-written RTL.
// Layer: rtl/telemetry/
// Owner: T-RECAP Phase 2 implementation.
// Purpose: Build Revision G METRICS payload records from core frame/sample metric taps.
// Contract: Non-stalling packetizer. It never drives ready/backpressure into the core.
// Generated dependencies: trecap_core_pkg, trecap_packet_pkg, trecap_iface_pkg.

`default_nettype none

// Revision G METRICS packetizer.
//
// This block emits one aggregate METRICS record when metrics_tick_i is asserted and metrics
// telemetry is enabled. Eligible-bin aggregates are accumulated from frame taps. Error aggregates
// are snapshotted from the mathematical core's authoritative counters so a second telemetry-side
// accumulator cannot drift across output stalls, core metric clears, or telemetry soft resets.
//
// Core-observer rule:
//   tap_frame_i and the core counter inputs are observations only. No ready/backpressure signal is
//   returned to the STFT/WOLA core. If another METRICS tick arrives while a previous metrics record
//   is still being emitted, the new telemetry event is dropped and reported through drop_pulse_o.
//
// Payload layout, little-endian, no implicit padding:
//   0   uint64 frame_idx
//   8   uint32 eligible_unique_bins
//   12  uint32 eligible_suppressed_bins
//   16  uint64 eligible_kept_mag2_lo
//   24  uint64 eligible_total_mag2_lo
//   32  uint64 sum_abs_err_lo
//   40  uint64 sum_sq_err_lo
//   48  uint32 max_abs_err
//   52  uint32 overflow_flags
module trecap_metrics_packetizer
#(
    parameter int unsigned PAYLOAD_DATA_W = 32,
    parameter int unsigned PAYLOAD_KEEP_W = (PAYLOAD_DATA_W + 7) / 8
) (
    input  logic                       clk,
    input  logic                       rst_n,

    input  logic                       enable_i,
    // Formatter-only reset. Aggregate metrics deliberately survive telemetry soft reset so their
    // epoch remains aligned with the authoritative core error accumulators.
    input  logic                       formatter_reset_i,
    input  logic                       clear_metrics_i,
    input  logic                       metrics_tick_i,
    input  trecap_iface_pkg::trecap_core_tap_frame_t     tap_frame_i,
    input  logic [63:0]                core_sum_abs_err_lo_i,
    input  logic [63:0]                core_sum_sq_err_lo_i,
    input  logic [31:0]                core_max_abs_err_i,
    input  logic                       core_metric_truncated_i,
    input  logic [31:0]                overflow_flags_i,

    output logic                       out_valid_o,
    input  logic                       out_ready_i,
    output trecap_iface_pkg::trecap_record_meta_t        out_meta_o,
    output logic [PAYLOAD_DATA_W-1:0]  out_payload_data_o,
    output logic [PAYLOAD_KEEP_W-1:0]  out_payload_keep_o,
    output logic                       out_payload_last_o,

    output logic                       drop_pulse_o
);
  import trecap_core_pkg::*;
  import trecap_packet_pkg::*;
  import trecap_iface_pkg::*;
  import trecap_build_pkg::*;


    localparam int unsigned PAYLOAD_BYTE_W    = PAYLOAD_KEEP_W;
    localparam int unsigned METRICS_BYTES     = TPKT_PAYLOAD_METRICS_BYTES;

    typedef enum logic [0:0] {
        ST_IDLE = 1'b0,
        ST_EMIT = 1'b1
    } metrics_state_e;

    metrics_state_e state_q;
    trecap_record_meta_t meta_q;
    logic [7:0] payload_mem [0:METRICS_BYTES-1];

    logic [63:0] latest_frame_idx_q;
    logic [31:0] eligible_unique_bins_q;
    logic [31:0] eligible_suppressed_bins_q;
    logic [63:0] eligible_kept_mag2_lo_q;
    logic [63:0] eligible_total_mag2_lo_q;
    logic        aggregate_truncated_q;

    logic [63:0] latest_frame_idx_n;
    logic [31:0] eligible_unique_bins_n;
    logic [31:0] eligible_suppressed_bins_n;
    logic [63:0] eligible_kept_mag2_lo_n;
    logic [63:0] eligible_total_mag2_lo_n;
    logic        aggregate_truncated_n;

    int unsigned emit_offset_q;
    logic drop_pulse_q;

    logic emit_accept;
    logic emit_last;
    int unsigned emit_remaining;

    logic [32:0] eligible_unique_sum;
    logic [32:0] eligible_suppressed_sum;
    logic [64:0] eligible_kept_sum;
    logic [64:0] eligible_total_sum;

    assign emit_accept = out_valid_o && out_ready_i;
    assign emit_last = (emit_offset_q + PAYLOAD_BYTE_W) >= int'(meta_q.payload_bytes);
    assign emit_remaining = (int'(meta_q.payload_bytes) > emit_offset_q) ?
                            (int'(meta_q.payload_bytes) - emit_offset_q) : 0;

    function automatic logic [PAYLOAD_KEEP_W-1:0] keep_for_remaining(
        input int unsigned remaining_bytes
    );
        logic [PAYLOAD_KEEP_W-1:0] keep;
        begin
            keep = '0;
            for (int unsigned byte_idx = 0; byte_idx < PAYLOAD_KEEP_W; byte_idx++) begin
                keep[byte_idx] = (byte_idx < remaining_bytes);
            end
            return keep;
        end
    endfunction : keep_for_remaining

    task automatic write_u32(input int unsigned off, input logic [31:0] value);
        begin
            payload_mem[off + 0] <= value[7:0];
            payload_mem[off + 1] <= value[15:8];
            payload_mem[off + 2] <= value[23:16];
            payload_mem[off + 3] <= value[31:24];
        end
    endtask : write_u32

    task automatic write_u64(input int unsigned off, input logic [63:0] value);
        begin
            payload_mem[off + 0] <= value[7:0];
            payload_mem[off + 1] <= value[15:8];
            payload_mem[off + 2] <= value[23:16];
            payload_mem[off + 3] <= value[31:24];
            payload_mem[off + 4] <= value[39:32];
            payload_mem[off + 5] <= value[47:40];
            payload_mem[off + 6] <= value[55:48];
            payload_mem[off + 7] <= value[63:56];
        end
    endtask : write_u64

    task automatic write_metrics_payload(
        input logic [63:0] frame_idx,
        input logic [31:0] eligible_unique_bins,
        input logic [31:0] eligible_suppressed_bins,
        input logic [63:0] eligible_kept_mag2_lo,
        input logic [63:0] eligible_total_mag2_lo,
        input logic [63:0] sum_abs_err_lo,
        input logic [63:0] sum_sq_err_lo,
        input logic [31:0] max_abs_err,
        input logic [31:0] overflow_flags
    );
        begin
            write_u64(TPKT_METRICS_FRAME_IDX_OFFSET, frame_idx);
            write_u32(TPKT_METRICS_ELIGIBLE_UNIQUE_BINS_OFFSET, eligible_unique_bins);
            write_u32(TPKT_METRICS_ELIGIBLE_SUPPRESSED_BINS_OFFSET, eligible_suppressed_bins);
            write_u64(TPKT_METRICS_ELIGIBLE_KEPT_MAG2_LO_OFFSET, eligible_kept_mag2_lo);
            write_u64(TPKT_METRICS_ELIGIBLE_TOTAL_MAG2_LO_OFFSET, eligible_total_mag2_lo);
            write_u64(TPKT_METRICS_SUM_ABS_ERR_LO_OFFSET, sum_abs_err_lo);
            write_u64(TPKT_METRICS_SUM_SQ_ERR_LO_OFFSET, sum_sq_err_lo);
            write_u32(TPKT_METRICS_MAX_ABS_ERR_OFFSET, max_abs_err);
            write_u32(TPKT_METRICS_OVERFLOW_FLAGS_OFFSET, overflow_flags);
        end
    endtask : write_metrics_payload

    function automatic trecap_record_meta_t make_meta(
        input logic [63:0] frame_idx,
        input logic        payload_truncated
    );
        trecap_record_meta_t meta;
        begin
            meta = '0;
            meta.valid = 1'b1;
            meta.packet_type = TPKT_METRICS;
            meta.flags = TPKT_FLAG_AGGREGATE_METRICS_MASK |
                         (payload_truncated ? TPKT_FLAG_PAYLOAD_TRUNCATED_MASK : 16'h0000);
            meta.seq = 32'h0000_0000;
            meta.timestamp = frame_idx;
            meta.payload_bytes = METRICS_BYTES;
            meta.drop_priority = TPKT_PRIORITY_METRICS;
            return meta;
        end
    endfunction : make_meta

    always_comb begin
        latest_frame_idx_n = latest_frame_idx_q;
        eligible_unique_bins_n = eligible_unique_bins_q;
        eligible_suppressed_bins_n = eligible_suppressed_bins_q;
        eligible_kept_mag2_lo_n = eligible_kept_mag2_lo_q;
        eligible_total_mag2_lo_n = eligible_total_mag2_lo_q;
        aggregate_truncated_n = aggregate_truncated_q;

        eligible_unique_sum = {1'b0, eligible_unique_bins_q};
        eligible_suppressed_sum = {1'b0, eligible_suppressed_bins_q};
        eligible_kept_sum = {1'b0, eligible_kept_mag2_lo_q};
        eligible_total_sum = {1'b0, eligible_total_mag2_lo_q};
        if (clear_metrics_i) begin
            latest_frame_idx_n = 64'd0;
            eligible_unique_bins_n = 32'd0;
            eligible_suppressed_bins_n = 32'd0;
            eligible_kept_mag2_lo_n = 64'd0;
            eligible_total_mag2_lo_n = 64'd0;
            aggregate_truncated_n = 1'b0;
        end else if (tap_frame_i.valid) begin
            latest_frame_idx_n = tap_frame_i.frame_idx;

            eligible_unique_sum = {1'b0, eligible_unique_bins_q} +
                                  {1'b0, tap_frame_i.stats.eligible_unique_bins};
            eligible_suppressed_sum = {1'b0, eligible_suppressed_bins_q} +
                                      {1'b0, tap_frame_i.stats.eligible_suppressed_bins};
            eligible_kept_sum = {1'b0, eligible_kept_mag2_lo_q} +
                                {1'b0, tap_frame_i.stats.eligible_kept_mag2_lo};
            eligible_total_sum = {1'b0, eligible_total_mag2_lo_q} +
                                 {1'b0, tap_frame_i.stats.eligible_total_mag2_lo};

            eligible_unique_bins_n = eligible_unique_sum[31:0];
            eligible_suppressed_bins_n = eligible_suppressed_sum[31:0];
            eligible_kept_mag2_lo_n = eligible_kept_sum[63:0];
            eligible_total_mag2_lo_n = eligible_total_sum[63:0];

            if (eligible_unique_sum[32] || eligible_suppressed_sum[32] ||
                eligible_kept_sum[64] || eligible_total_sum[64] ||
                tap_frame_i.stats.mag2_truncated) begin
                aggregate_truncated_n = 1'b1;
            end
        end
    end

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state_q <= ST_IDLE;
            meta_q <= '0;
            latest_frame_idx_q <= 64'd0;
            eligible_unique_bins_q <= 32'd0;
            eligible_suppressed_bins_q <= 32'd0;
            eligible_kept_mag2_lo_q <= 64'd0;
            eligible_total_mag2_lo_q <= 64'd0;
            aggregate_truncated_q <= 1'b0;
            emit_offset_q <= 0;
            drop_pulse_q <= 1'b0;
        end else begin
            latest_frame_idx_q <= latest_frame_idx_n;
            eligible_unique_bins_q <= eligible_unique_bins_n;
            eligible_suppressed_bins_q <= eligible_suppressed_bins_n;
            eligible_kept_mag2_lo_q <= eligible_kept_mag2_lo_n;
            eligible_total_mag2_lo_q <= eligible_total_mag2_lo_n;
            aggregate_truncated_q <= aggregate_truncated_n;

            if (formatter_reset_i) begin
                state_q <= ST_IDLE;
                meta_q <= '0;
                emit_offset_q <= 0;
                drop_pulse_q <= 1'b0;
            end else begin
                drop_pulse_q <= 1'b0;
                unique case (state_q)
                    ST_IDLE: begin
                        emit_offset_q <= 0;
                        if (metrics_tick_i && enable_i && !clear_metrics_i) begin
                            write_metrics_payload(latest_frame_idx_n,
                                                  eligible_unique_bins_n,
                                                  eligible_suppressed_bins_n,
                                                  eligible_kept_mag2_lo_n,
                                                  eligible_total_mag2_lo_n,
                                                  core_sum_abs_err_lo_i,
                                                  core_sum_sq_err_lo_i,
                                                  core_max_abs_err_i,
                                                  overflow_flags_i);
                            meta_q <= make_meta(latest_frame_idx_n,
                                                aggregate_truncated_n || core_metric_truncated_i);
                            state_q <= ST_EMIT;
                        end
                    end
                    ST_EMIT: begin
                        if (metrics_tick_i && enable_i && !clear_metrics_i) begin
                            drop_pulse_q <= 1'b1;
                        end
                        if (emit_accept) begin
                            if (emit_last) begin
                                state_q <= ST_IDLE;
                                emit_offset_q <= 0;
                            end else begin
                                emit_offset_q <= emit_offset_q + PAYLOAD_BYTE_W;
                            end
                        end
                    end
                    default: begin
                        state_q <= ST_IDLE;
                        emit_offset_q <= 0;
                    end
                endcase
            end
        end
    end

    always_comb begin
        out_valid_o = (state_q == ST_EMIT);
        // Inactive fields are don't-care; consumers transact only when valid.
        // Keep valid/flush gating out of downstream payload-size arithmetic.
        out_meta_o = meta_q;
        out_meta_o.valid = out_valid_o && meta_q.valid;
        out_payload_data_o = '0;
        out_payload_keep_o = '0;
        out_payload_last_o = 1'b0;
        if (state_q == ST_EMIT) begin
            for (int unsigned byte_idx = 0; byte_idx < PAYLOAD_BYTE_W; byte_idx++) begin
                if ((emit_offset_q + byte_idx) < int'(meta_q.payload_bytes)) begin
                    out_payload_data_o[8*byte_idx +: 8] = payload_mem[emit_offset_q + byte_idx];
                end
            end
            out_payload_keep_o = keep_for_remaining(emit_remaining);
            out_payload_last_o = emit_last;
        end
    end

    assign drop_pulse_o = drop_pulse_q;

    wire unused_tap_frame_fields = tap_frame_i.stats.unique_bins[0] ^
                                   tap_frame_i.stats.unique_suppressed_bins[0];
    wire unused_silence = unused_tap_frame_fields;

`ifndef SYNTHESIS
    initial begin
        if (PAYLOAD_DATA_W < 8) begin
            $fatal(1, "trecap_metrics_packetizer: PAYLOAD_DATA_W must be at least 8");
        end
        if ((PAYLOAD_DATA_W % 8) != 0) begin
            $fatal(1, "trecap_metrics_packetizer: PAYLOAD_DATA_W must be byte-aligned");
        end
        if (PAYLOAD_KEEP_W != ((PAYLOAD_DATA_W + 7) / 8)) begin
            $fatal(1, "trecap_metrics_packetizer: PAYLOAD_KEEP_W does not match PAYLOAD_DATA_W");
        end
        if (TPKT_PAYLOAD_METRICS_BYTES != (TPKT_METRICS_OVERFLOW_FLAGS_OFFSET + 4)) begin
            $fatal(1, "trecap_metrics_packetizer: METRICS payload-size constant mismatch");
        end
    end
`endif

endmodule : trecap_metrics_packetizer

`default_nettype wire
