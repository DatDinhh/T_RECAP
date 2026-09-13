// SPDX-License-Identifier: MIT
// File class: [1] hand-written RTL.
// Layer: rtl/top/
// Owner: T-RECAP Phase 2 implementation.
// Purpose: Standalone normalized-source -> mathematical-core -> telemetry composition.
// Contract: Instantiate the real core and the non-stalling telemetry observer without HPS/DDR,
//           Platform Designer, source selection, or board pins.
// Generated dependencies: trecap_core_pkg, trecap_csr_pkg, trecap_packet_pkg,
//                         trecap_iface_pkg, trecap_build_pkg.

`default_nettype none

// Core + telemetry build variant.
//
// Forward path:
//   normalized source ready/valid -> trecap_core_top -> valid-only observation taps
//                                                    -> trecap_telemetry_top -> record stream
//
// The source and y-output ready paths terminate in trecap_core_top. record_ready_i is consumed
// only below trecap_telemetry_top and has no path to sample_ready_o, y_ready_i, the frame
// scheduler, FFT/IFFT, WOLA, or core metric accumulation.
//
// This top deliberately does not own source muxing, finite-replay geometry, DDR record headers,
// ring writes, sequence allocation, HPS CSRs, Ethernet/UDP, or board pins. A source integration
// supplies already-normalized samples and, when required, the finite-stream/tail controls.
module trecap_core_telemetry_top
  import trecap_core_pkg::*;
  import trecap_csr_pkg::*;
  import trecap_packet_pkg::*;
  import trecap_iface_pkg::*;
  import trecap_build_pkg::*;
#(
    parameter int unsigned SAMPLE_W             = T_SAMPLE_W,
    parameter int unsigned L                    = T_FFT_L,
    parameter int unsigned P                    = T_FFT_P,
    parameter int unsigned BIN_IDX_W            = (T_UNIQUE_BINS <= 1) ? 1 : $clog2(T_UNIQUE_BINS),
    parameter string       WINDOW_FILE           = "artifacts/coefficients/window_qw.memh",
    parameter string       TWIDDLE_RE_FILE       = "artifacts/coefficients/twiddle_re.memh",
    parameter string       TWIDDLE_IM_FILE       = "artifacts/coefficients/twiddle_im.memh",
    parameter string       TWIDDLE_INV_RE_FILE   = "artifacts/coefficients/twiddle_inv_re.memh",
    parameter string       TWIDDLE_INV_IM_FILE   = "artifacts/coefficients/twiddle_inv_im.memh",
    parameter int unsigned PAYLOAD_DATA_W        = 32,
    parameter int unsigned PAYLOAD_KEEP_W        = (PAYLOAD_DATA_W + 7) / 8,
    parameter int unsigned PACKET_FIFO_RECORDS   = 8,
    parameter int unsigned PACKET_FIFO_BYTES     = TPKT_UDP_MAX_BYTES,
    parameter bit          CLEAR_COUNTERS_ON_SOFT_RESET = 1'b1
) (
    input  logic                         clk,
    input  logic                         rst_n,

    // Mathematical-core controls. ctrl_i.thr2_active is the only threshold presented to the core,
    // so STATUS and arithmetic cannot observe different active thresholds. clear_metrics_w1p is
    // assumed to be a one-cycle pulse already qualified at a safe integration boundary.
    input  logic                         enable_i,
    input  logic                         clear_i,
    input  logic                         clear_sticky_i,
    input  logic                         telemetry_soft_reset_i,
    input  trecap_hps_bridge_ctrl_t      ctrl_i,

    // Normalized source stream. Backpressure here is core-local only.
    input  trecap_sample_t               sample_i,
    input  logic                         sample_valid_i,
    output logic                         sample_ready_o,
    input  logic                         source_discontinuity_i,

    // Finite-stream/tail routing is owned by the source integration layer.
    input  logic                         finite_stream_i,
    input  logic [63:0]                  active_frame_count_i,
    input  logic                         tail_tick_valid_i,
    output logic                         tail_tick_ready_o,
    input  logic [63:0]                  tail_tick_sample_idx_i,
    input  logic                         tail_tick_last_i,
    input  logic [31:0]                  tail_tick_count_i,

    // Mathematical output. y_ready_i belongs to a real core-output sink, never telemetry.
    output logic                         y_valid_o,
    input  logic                         y_ready_i,
    output trecap_sample_t               y_sample_o,
    output logic signed [SAMPLE_W-1:0]   y_data_o,
    output logic [63:0]                  y_sample_idx_o,

    // Low-rate telemetry scheduler ticks and transport-owned STATUS context.
    input  logic                         status_tick_i,
    input  logic                         metrics_tick_i,
    input  logic [31:0]                  sample_rate_hz_i,
    // Level-based flags owned outside this composition. They are included in STATUS/output but are
    // not latched or cleared here; their owner must implement its own W1C/event semantics.
    input  logic [31:0]                  external_overflow_flags_i,
    // W1C mask applies only to telemetry sticky flags owned by this composition.
    input  logic [31:0]                  clear_telemetry_flags_w1c_i,
    input  logic [31:0]                  dma_drop_count_i,
    input  logic [31:0]                  dma_packet_count_i,
    input  logic [31:0]                  csr_command_reject_count_i,

    // Formatted payload stream. The downstream owner adds the common header/sequence and DDR
    // framing. Backpressure may stall this stream and cause telemetry drops, never core stalls.
    output logic                         record_valid_o,
    input  logic                         record_ready_i,
    output trecap_record_meta_t          record_meta_o,
    output logic [PAYLOAD_DATA_W-1:0]    record_payload_data_o,
    output logic [PAYLOAD_KEEP_W-1:0]    record_payload_keep_o,
    output logic                         record_payload_last_o,

    // Direct valid-only taps remain visible for observability and alternate non-stalling sinks.
    output trecap_core_tap_sample_t      tap_sample_o,
    output trecap_core_tap_frame_t       tap_frame_o,
    output logic                         tap_bin_valid_o,
    output logic [63:0]                  tap_bin_frame_idx_o,
    output logic [BIN_IDX_W-1:0]         tap_bin_idx_o,
    output logic signed [T_CAN_W-1:0]    tap_bin_re_o,
    output logic signed [T_CAN_W-1:0]    tap_bin_im_o,
    output logic [T_MAG2_W-1:0]          tap_bin_mag2_o,
    output logic                         tap_bin_pre_mask_o,
    output logic                         tap_bin_mask_o,
    output logic                         tap_bin_eligible_o,
    output logic                         tap_bin_last_o,

    // Core status/counters.
    output logic                         frame_boundary_pulse_o,
    output logic                         core_alive_o,
    output logic                         core_busy_o,
    output logic [63:0]                  core_sample_count_o,
    output logic [63:0]                  core_frame_count_o,
    output logic [63:0]                  core_error_sample_count_o,
    output logic [63:0]                  core_sum_abs_err_lo_o,
    output logic [63:0]                  core_sum_sq_err_lo_o,
    output logic [15:0]                  core_max_abs_err_o,
    output logic                         core_metric_overflow_sticky_o,
    output logic                         tail_drain_active_o,
    output logic                         tail_drain_accept_pulse_o,
    output logic                         tail_drain_done_pulse_o,
    output logic [63:0]                  wola_output_count_o,
    output logic [31:0]                  core_overflow_flags_o,
    output logic                         core_saturation_sticky_o,
    output logic                         core_protocol_error_sticky_o,

    // Telemetry admission/drop/status.
    output logic [31:0]                  packet_fifo_drop_count_o,
    output logic                         packet_fifo_drop_pulse_o,
    output logic                         packet_fifo_full_o,
    output logic                         packet_fifo_overflow_o,
    output logic [31:0]                  overflow_flags_o,
    output logic                         packet_enable_illegal_o,
    output logic                         spec_mode_illegal_o,
    output logic                         spec_shift_illegal_o,
    output logic                         wave_decim_illegal_o,
    output logic                         telemetry_config_illegal_o,
    output logic                         telemetry_active_o,
    output logic                         core_tap_seen_o,
    output logic                         scheduler_backpressure_o,
    output logic                         scheduler_disabled_drop_o,
    output logic                         scheduler_illegal_drop_o
);

    trecap_core_tap_sample_t tap_sample_w;
    trecap_core_tap_frame_t  tap_frame_w;
    logic                    tap_bin_valid_w;
    logic [63:0]             tap_bin_frame_idx_w;
    logic [BIN_IDX_W-1:0]    tap_bin_idx_w;
    logic signed [T_CAN_W-1:0] tap_bin_re_w;
    logic signed [T_CAN_W-1:0] tap_bin_im_w;
    logic [T_MAG2_W-1:0]     tap_bin_mag2_w;
    logic                    tap_bin_pre_mask_w;
    logic                    tap_bin_mask_w;
    logic                    tap_bin_eligible_w;
    logic                    tap_bin_last_w;

    logic                    core_tap_seen_q;
    logic [31:0]             telemetry_overflow_flags_q;
    logic [31:0]             telemetry_overflow_set_w;
    logic [31:0]             combined_overflow_flags_w;
    logic                    telemetry_config_illegal_q;
    logic                    telemetry_config_illegal_new_w;
    logic                    metrics_epoch_clear_w;

    // Illegal optional/reserved packet enables are rejected by the command layer. If malformed
    // controls escape that layer, telemetry admission is fail-closed and the fault is observable.
    assign packet_enable_illegal_o =
        ((ctrl_i.packet_enable & TCSR_PACKET_ENABLE_RESERVED_31_6_MASK) != 32'h0000) ||
        ((ctrl_i.packet_enable & TCSR_PACKET_ENABLE_PEAKS_EN_MASK) != 32'h0000) ||
        ((ctrl_i.packet_enable & TCSR_PACKET_ENABLE_DEBUG_EN_MASK) != 32'h0000);

    assign spec_mode_illegal_o = !((ctrl_i.spec_mode == TSPEC_DISABLED) ||
                                   (ctrl_i.spec_mode == TSPEC_SPEC64)   ||
                                   (ctrl_i.spec_mode == TSPEC_SPEC129));
    assign spec_shift_illegal_o = (int'(ctrl_i.spec_shift) > TCSR_SPEC_SHIFT_MAX);
    assign wave_decim_illegal_o = (ctrl_i.wave_decim == 16'd0);
    assign telemetry_config_illegal_o = packet_enable_illegal_o ||
                                        spec_mode_illegal_o ||
                                        spec_shift_illegal_o ||
                                        wave_decim_illegal_o;
    assign telemetry_active_o = ctrl_i.telemetry_enable && !telemetry_config_illegal_o;
    assign telemetry_config_illegal_new_w = telemetry_config_illegal_o &&
                                            !telemetry_config_illegal_q;
    // Every operation that resets core-owned metric state also resets the telemetry-owned eligible-
    // bin aggregate. Telemetry soft reset is intentionally absent: it is formatter-only.
    assign metrics_epoch_clear_w = ctrl_i.clear_metrics_w1p || clear_i || !enable_i ||
                                   source_discontinuity_i;

    assign tap_sample_o = tap_sample_w;
    assign tap_frame_o = tap_frame_w;
    assign tap_bin_valid_o = tap_bin_valid_w;
    assign tap_bin_frame_idx_o = tap_bin_frame_idx_w;
    assign tap_bin_idx_o = tap_bin_idx_w;
    assign tap_bin_re_o = tap_bin_re_w;
    assign tap_bin_im_o = tap_bin_im_w;
    assign tap_bin_mag2_o = tap_bin_mag2_w;
    assign tap_bin_pre_mask_o = tap_bin_pre_mask_w;
    assign tap_bin_mask_o = tap_bin_mask_w;
    assign tap_bin_eligible_o = tap_bin_eligible_w;
    assign tap_bin_last_o = tap_bin_last_w;
    assign core_tap_seen_o = core_tap_seen_q;

    always_comb begin
        telemetry_overflow_set_w = 32'd0;
        // Set from new events, never from the sticky packet_fifo_overflow_o level. Otherwise a
        // W1C operation could never remain clear while the lower-level debug sticky is asserted.
        if (packet_fifo_drop_pulse_o) begin
            telemetry_overflow_set_w |= TCSR_OVERFLOW_FLAGS_PACKET_FIFO_OVERFLOW_MASK;
        end
        if (scheduler_illegal_drop_o) begin
            telemetry_overflow_set_w |= TCSR_OVERFLOW_FLAGS_MALFORMED_PACKET_MASK;
        end
        if (telemetry_config_illegal_new_w) begin
            telemetry_overflow_set_w |= TCSR_OVERFLOW_FLAGS_ILLEGAL_COMMAND_MASK;
        end
    end

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            core_tap_seen_q <= 1'b0;
            telemetry_overflow_flags_q <= 32'd0;
            telemetry_config_illegal_q <= 1'b0;
        end else begin
            telemetry_overflow_flags_q <=
                (telemetry_overflow_flags_q & ~clear_telemetry_flags_w1c_i) |
                telemetry_overflow_set_w;

            // Track the current fault episode, independently of W1C. Clearing the sticky owner
            // while malformed controls remain must not manufacture another "new" event; the
            // detector re-arms only after the fault level deasserts, then reports a later recurrence.
            telemetry_config_illegal_q <= telemetry_config_illegal_o;

            if (telemetry_soft_reset_i || clear_i || source_discontinuity_i) begin
                core_tap_seen_q <= 1'b0;
            end else if (tap_sample_w.valid || tap_frame_w.valid || tap_bin_valid_w) begin
                core_tap_seen_q <= 1'b1;
            end
        end
    end

    assign combined_overflow_flags_w = external_overflow_flags_i |
                                       core_overflow_flags_o |
                                       telemetry_overflow_flags_q;
    assign overflow_flags_o = combined_overflow_flags_w;

    trecap_core_top #(
        .SAMPLE_W(SAMPLE_W),
        .L(L),
        .P(P),
        .BIN_IDX_W(BIN_IDX_W),
        .WINDOW_FILE(WINDOW_FILE),
        .TWIDDLE_RE_FILE(TWIDDLE_RE_FILE),
        .TWIDDLE_IM_FILE(TWIDDLE_IM_FILE),
        .TWIDDLE_INV_RE_FILE(TWIDDLE_INV_RE_FILE),
        .TWIDDLE_INV_IM_FILE(TWIDDLE_INV_IM_FILE)
    ) u_core (
        .clk(clk),
        .rst_n(rst_n),
        .enable_i(enable_i),
        .clear_i(clear_i || !enable_i),
        .clear_sticky_i(clear_sticky_i),
        .clear_metrics_i(ctrl_i.clear_metrics_w1p),
        .sample_i(sample_i),
        .sample_valid_i(sample_valid_i),
        .sample_ready_o(sample_ready_o),
        .thr2_i(ctrl_i.thr2_active),
        .source_discontinuity_i(source_discontinuity_i),
        .finite_stream_i(finite_stream_i),
        .active_frame_count_i(active_frame_count_i),
        .tail_tick_valid_i(tail_tick_valid_i),
        .tail_tick_ready_o(tail_tick_ready_o),
        .tail_tick_sample_idx_i(tail_tick_sample_idx_i),
        .tail_tick_last_i(tail_tick_last_i),
        .tail_tick_count_i(tail_tick_count_i),
        .y_valid_o(y_valid_o),
        .y_ready_i(y_ready_i),
        .y_sample_o(y_sample_o),
        .y_data_o(y_data_o),
        .y_sample_idx_o(y_sample_idx_o),
        .tap_sample_o(tap_sample_w),
        .tap_frame_o(tap_frame_w),
        .tap_bin_valid_o(tap_bin_valid_w),
        .tap_bin_frame_idx_o(tap_bin_frame_idx_w),
        .tap_bin_idx_o(tap_bin_idx_w),
        .tap_bin_re_o(tap_bin_re_w),
        .tap_bin_im_o(tap_bin_im_w),
        .tap_bin_mag2_o(tap_bin_mag2_w),
        .tap_bin_pre_mask_o(tap_bin_pre_mask_w),
        .tap_bin_mask_o(tap_bin_mask_w),
        .tap_bin_eligible_o(tap_bin_eligible_w),
        .tap_bin_last_o(tap_bin_last_w),
        .frame_boundary_pulse_o(frame_boundary_pulse_o),
        .core_alive_o(core_alive_o),
        .core_busy_o(core_busy_o),
        .core_sample_count_o(core_sample_count_o),
        .core_frame_count_o(core_frame_count_o),
        .core_error_sample_count_o(core_error_sample_count_o),
        .core_sum_abs_err_lo_o(core_sum_abs_err_lo_o),
        .core_sum_sq_err_lo_o(core_sum_sq_err_lo_o),
        .core_max_abs_err_o(core_max_abs_err_o),
        .core_metric_overflow_sticky_o(core_metric_overflow_sticky_o),
        .tail_drain_active_o(tail_drain_active_o),
        .tail_drain_accept_pulse_o(tail_drain_accept_pulse_o),
        .tail_drain_done_pulse_o(tail_drain_done_pulse_o),
        .wola_output_count_o(wola_output_count_o),
        .overflow_flags_o(core_overflow_flags_o),
        .saturation_sticky_o(core_saturation_sticky_o),
        .protocol_error_sticky_o(core_protocol_error_sticky_o)
    );

    trecap_telemetry_top #(
        .PAYLOAD_DATA_W(PAYLOAD_DATA_W),
        .PAYLOAD_KEEP_W(PAYLOAD_KEEP_W),
        .PACKET_FIFO_RECORDS(PACKET_FIFO_RECORDS),
        .PACKET_FIFO_BYTES(PACKET_FIFO_BYTES),
        .BIN_IDX_W(BIN_IDX_W),
        .CLEAR_COUNTERS_ON_SOFT_RESET(CLEAR_COUNTERS_ON_SOFT_RESET)
    ) u_telemetry (
        .clk(clk),
        .rst_n(rst_n),
        .telemetry_soft_reset_i(telemetry_soft_reset_i),
        .formatter_flush_i(source_discontinuity_i || clear_i || !enable_i),
        .counter_clear_i(1'b0),
        .observation_epoch_reset_i(source_discontinuity_i || clear_i || !enable_i),
        .metrics_clear_i(metrics_epoch_clear_w),
        .ctrl_i(ctrl_i),
        .tap_sample_i(tap_sample_w),
        .tap_frame_i(tap_frame_w),
        .tap_bin_valid_i(tap_bin_valid_w),
        .tap_bin_frame_idx_i(tap_bin_frame_idx_w),
        .tap_bin_idx_i(tap_bin_idx_w),
        .tap_bin_mag2_i(tap_bin_mag2_w),
        .tap_bin_mask_i(tap_bin_mask_w),
        .tap_bin_eligible_i(tap_bin_eligible_w),
        .tap_bin_last_i(tap_bin_last_w),
        .status_tick_i(status_tick_i),
        .metrics_tick_i(metrics_tick_i),
        .core_sample_count_i(core_sample_count_o),
        .core_frame_count_i(core_frame_count_o),
        .core_sum_abs_err_lo_i(core_sum_abs_err_lo_o),
        .core_sum_sq_err_lo_i(core_sum_sq_err_lo_o),
        .core_max_abs_err_i({16'd0, core_max_abs_err_o}),
        .core_metric_truncated_i(core_metric_overflow_sticky_o),
        .sample_rate_hz_i(sample_rate_hz_i),
        .overflow_flags_i(combined_overflow_flags_w),
        .dma_drop_count_i(dma_drop_count_i),
        .dma_packet_count_i(dma_packet_count_i),
        .csr_command_reject_count_i(csr_command_reject_count_i),
        .record_valid_o(record_valid_o),
        .record_ready_i(record_ready_i),
        .record_meta_o(record_meta_o),
        .record_payload_data_o(record_payload_data_o),
        .record_payload_keep_o(record_payload_keep_o),
        .record_payload_last_o(record_payload_last_o),
        .packet_fifo_drop_count_o(packet_fifo_drop_count_o),
        .packet_fifo_drop_pulse_o(packet_fifo_drop_pulse_o),
        .packet_fifo_full_o(packet_fifo_full_o),
        .packet_fifo_overflow_o(packet_fifo_overflow_o),
        .scheduler_backpressure_o(scheduler_backpressure_o),
        .scheduler_disabled_drop_o(scheduler_disabled_drop_o),
        .scheduler_illegal_drop_o(scheduler_illegal_drop_o)
    );

`ifndef SYNTHESIS
    initial begin
        if (!TBUILD_CONTRACT_OK) begin
            $fatal(1, "trecap_core_telemetry_top: generated contract sanity check failed");
        end
        if ((SAMPLE_W != T_SAMPLE_W) || (L != T_FFT_L) || (P != T_FFT_P)) begin
            $fatal(1, "trecap_core_telemetry_top: core parameters must match generated contract");
        end
        if ((PAYLOAD_DATA_W < 8) || ((PAYLOAD_DATA_W % 8) != 0)) begin
            $fatal(1, "trecap_core_telemetry_top: PAYLOAD_DATA_W must be byte-aligned");
        end
        if (PAYLOAD_KEEP_W != (PAYLOAD_DATA_W / 8)) begin
            $fatal(1, "trecap_core_telemetry_top: PAYLOAD_KEEP_W must equal PAYLOAD_DATA_W/8");
        end
    end

    always_ff @(posedge clk) begin
        if (rst_n) begin
            if (record_valid_o && !record_meta_o.valid) begin
                $error("trecap_core_telemetry_top: record valid with invalid metadata");
            end
            if (record_valid_o && trecap_packet_type_reserved_disabled(record_meta_o.packet_type)) begin
                $error("trecap_core_telemetry_top: reserved-disabled packet emitted");
            end
            if (record_valid_o && !trecap_payload_bytes_valid(record_meta_o.packet_type,
                                                              int'(record_meta_o.payload_bytes))) begin
                $error("trecap_core_telemetry_top: emitted payload size is illegal");
            end
        end
    end
`endif

endmodule : trecap_core_telemetry_top

`default_nettype wire
