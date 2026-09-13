// SPDX-License-Identifier: MIT
// File class: [1] hand-written RTL.
// Layer: rtl/top/
// Owner: T-RECAP Phase 2 implementation.
// Purpose: Pure core build variant for Cut C0 compile/smoke and direct RTL harnesses.
// Contract: Instantiates the STFT/WOLA mathematical core only. No board pins, HPS bridge,
//           DDR writer, Ethernet telemetry, packetizer, or dashboard dependency exists here.

`default_nettype none

module trecap_core_only_top
  import trecap_core_pkg::*;
  import trecap_iface_pkg::*;
  import trecap_build_pkg::*;
#(
    parameter int unsigned SAMPLE_W            = T_SAMPLE_W,
    parameter int unsigned L                   = T_FFT_L,
    parameter int unsigned P                   = T_FFT_P,
    parameter int unsigned BIN_IDX_W           = (T_UNIQUE_BINS <= 1) ? 1 : $clog2(T_UNIQUE_BINS),
    parameter string       WINDOW_FILE         = TBUILD_WINDOW_QW_MEMH,
    parameter string       TWIDDLE_RE_FILE     = TBUILD_TWIDDLE_RE_MEMH,
    parameter string       TWIDDLE_IM_FILE     = TBUILD_TWIDDLE_IM_MEMH,
    parameter string       TWIDDLE_INV_RE_FILE = TBUILD_TWIDDLE_INV_RE_MEMH,
    parameter string       TWIDDLE_INV_IM_FILE = TBUILD_TWIDDLE_INV_IM_MEMH
) (
    input  logic                         clk,
    input  logic                         rst_n,

    input  logic                         enable_i,
    input  logic                         clear_i,
    input  logic                         clear_sticky_i,
    input  logic                         clear_metrics_i,

    input  trecap_sample_t               sample_i,
    input  logic                         sample_valid_i,
    output logic                         sample_ready_o,

    input  logic [T_MAG2_W-1:0]          thr2_i,
    input  logic                         source_discontinuity_i,

    output logic                         y_valid_o,
    input  logic                         y_ready_i,
    output trecap_sample_t               y_sample_o,
    output logic signed [SAMPLE_W-1:0]   y_data_o,
    output logic [63:0]                  y_sample_idx_o,

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
    output logic [31:0]                  overflow_flags_o,
    output logic                         saturation_sticky_o,
    output logic                         protocol_error_sticky_o,
    output logic                         build_contract_error_o
);

    assign build_contract_error_o = !TBUILD_CONTRACT_OK;

    trecap_core_top #(
        .SAMPLE_W( SAMPLE_W ),
        .L( L ),
        .P( P ),
        .BIN_IDX_W( BIN_IDX_W ),
        .WINDOW_FILE( WINDOW_FILE ),
        .TWIDDLE_RE_FILE( TWIDDLE_RE_FILE ),
        .TWIDDLE_IM_FILE( TWIDDLE_IM_FILE ),
        .TWIDDLE_INV_RE_FILE( TWIDDLE_INV_RE_FILE ),
        .TWIDDLE_INV_IM_FILE( TWIDDLE_INV_IM_FILE )
    ) u_core (
        .clk( clk ),
        .rst_n( rst_n ),
        .enable_i( enable_i ),
        .clear_i( clear_i ),
        .clear_sticky_i( clear_sticky_i ),
        .clear_metrics_i( clear_metrics_i ),
        .sample_i( sample_i ),
        .sample_valid_i( sample_valid_i ),
        .sample_ready_o( sample_ready_o ),
        .thr2_i( thr2_i ),
        .source_discontinuity_i( source_discontinuity_i ),
        .finite_stream_i( 1'b0 ),
        .active_frame_count_i( 64'd0 ),
        .tail_tick_valid_i( 1'b0 ),
        .tail_tick_ready_o( ),
        .tail_tick_sample_idx_i( 64'd0 ),
        .tail_tick_last_i( 1'b0 ),
        .tail_tick_count_i( 32'd0 ),
        .y_valid_o( y_valid_o ),
        .y_ready_i( y_ready_i ),
        .y_sample_o( y_sample_o ),
        .y_data_o( y_data_o ),
        .y_sample_idx_o( y_sample_idx_o ),
        .tap_sample_o( tap_sample_o ),
        .tap_frame_o( tap_frame_o ),
        .tap_bin_valid_o( tap_bin_valid_o ),
        .tap_bin_frame_idx_o( tap_bin_frame_idx_o ),
        .tap_bin_idx_o( tap_bin_idx_o ),
        .tap_bin_re_o( tap_bin_re_o ),
        .tap_bin_im_o( tap_bin_im_o ),
        .tap_bin_mag2_o( tap_bin_mag2_o ),
        .tap_bin_pre_mask_o( tap_bin_pre_mask_o ),
        .tap_bin_mask_o( tap_bin_mask_o ),
        .tap_bin_eligible_o( tap_bin_eligible_o ),
        .tap_bin_last_o( tap_bin_last_o ),
        .frame_boundary_pulse_o( frame_boundary_pulse_o ),
        .core_alive_o( core_alive_o ),
        .core_busy_o( core_busy_o ),
        .core_sample_count_o( core_sample_count_o ),
        .core_frame_count_o( core_frame_count_o ),
        .core_error_sample_count_o( core_error_sample_count_o ),
        .core_sum_abs_err_lo_o( core_sum_abs_err_lo_o ),
        .core_sum_sq_err_lo_o( core_sum_sq_err_lo_o ),
        .core_max_abs_err_o( core_max_abs_err_o ),
        .core_metric_overflow_sticky_o( core_metric_overflow_sticky_o ),
        .tail_drain_active_o( ),
        .tail_drain_accept_pulse_o( ),
        .tail_drain_done_pulse_o( ),
        .wola_output_count_o( ),
        .overflow_flags_o( overflow_flags_o ),
        .saturation_sticky_o( saturation_sticky_o ),
        .protocol_error_sticky_o( protocol_error_sticky_o )
    );

`ifndef SYNTHESIS
    initial begin
        if (!TBUILD_CONTRACT_OK) begin
            $fatal(1, "trecap_core_only_top: generated build/core/packet contract check failed");
        end
        if (SAMPLE_W != T_SAMPLE_W) begin
            $fatal(1, "trecap_core_only_top: SAMPLE_W must match generated T_SAMPLE_W");
        end
        if (L != T_FFT_L) begin
            $fatal(1, "trecap_core_only_top: L must match generated T_FFT_L");
        end
        if (P != T_FFT_P) begin
            $fatal(1, "trecap_core_only_top: P must match generated T_FFT_P");
        end
    end
`endif

endmodule : trecap_core_only_top

`default_nettype wire
