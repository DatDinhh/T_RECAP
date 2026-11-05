// SPDX-License-Identifier: MIT
// File class: [1] hand-written RTL.
// Layer: rtl/core/
// Owner: T-RECAP Phase 2 implementation.
// Purpose: Core-only STFT/WOLA selective-suppression integration wrapper.
// Contract: Builds the mathematical core boundary without board pins or external transport logic. Observation leaves this module only as valid-only taps.

`default_nettype none

module trecap_core_top
#(
    parameter int unsigned SAMPLE_W      = trecap_core_pkg::T_SAMPLE_W,
    parameter int unsigned L             = trecap_core_pkg::T_FFT_L,
    parameter int unsigned P             = trecap_core_pkg::T_FFT_P,
    parameter int unsigned BIN_IDX_W     = (trecap_core_pkg::T_UNIQUE_BINS <= 1) ? 1 : $clog2(trecap_core_pkg::T_UNIQUE_BINS),
    parameter              WINDOW_FILE   = "artifacts/coefficients/window_qw.memh",
    parameter              TWIDDLE_RE_FILE = "artifacts/coefficients/twiddle_re.memh",
    parameter              TWIDDLE_IM_FILE = "artifacts/coefficients/twiddle_im.memh",
    parameter              TWIDDLE_INV_RE_FILE = "artifacts/coefficients/twiddle_inv_re.memh",
    parameter              TWIDDLE_INV_IM_FILE = "artifacts/coefficients/twiddle_inv_im.memh"
) (
    input  logic                         clk,
    input  logic                         rst_n,
    input  logic                         enable_i,
    input  logic                         clear_i,
    input  logic                         clear_sticky_i,
    input  logic                         clear_metrics_i,

    // Signed N-bit source stream after source selection/adaptation.  Backpressure here belongs
    // only to core-local buffering; external observer or transport layers must not drive it.
    input  trecap_iface_pkg::trecap_sample_t               sample_i,
    input  logic                         sample_valid_i,
    output logic                         sample_ready_o,

    input  logic [trecap_core_pkg::T_MAG2_W-1:0]          thr2_i,
    input  logic                         source_discontinuity_i,

    // Finite-stream geometry and pure tail ticks. active_frame_count_i limits scheduler work;
    // tail ticks bypass the input ring/FFT/mask path and advance only the WOLA OLA ring.
    input  logic                         finite_stream_i,
    input  logic [63:0]                  active_frame_count_i,
    input  logic                         tail_tick_valid_i,
    output logic                         tail_tick_ready_o,
    input  logic [63:0]                  tail_tick_sample_idx_i,
    input  logic                         tail_tick_last_i,
    input  logic [31:0]                  tail_tick_count_i,

    // Core output stream for C0 replay/signoff harnesses.  This is y[n] after exact D alignment.
    output logic                         y_valid_o,
    input  logic                         y_ready_i,
    output trecap_iface_pkg::trecap_sample_t               y_sample_o,
    output logic signed [SAMPLE_W-1:0]   y_data_o,
    output logic [63:0]                  y_sample_idx_o,

    // Valid-only observation taps. No ready/backpressure returns from observer logic.
    output trecap_iface_pkg::trecap_core_tap_sample_t      tap_sample_o,
    output trecap_iface_pkg::trecap_core_tap_frame_t       tap_frame_o,
    output logic                         tap_bin_valid_o,
    output logic [63:0]                  tap_bin_frame_idx_o,
    output logic [BIN_IDX_W-1:0]         tap_bin_idx_o,
    output logic signed [trecap_core_pkg::T_CAN_W-1:0]    tap_bin_re_o,
    output logic signed [trecap_core_pkg::T_CAN_W-1:0]    tap_bin_im_o,
    output logic [trecap_core_pkg::T_MAG2_W-1:0]          tap_bin_mag2_o,
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
    output logic                         tail_drain_active_o,
    output logic                         tail_drain_accept_pulse_o,
    output logic                         tail_drain_done_pulse_o,
    output logic [63:0]                  wola_output_count_o,
    output logic [31:0]                  overflow_flags_o,
    output logic                         saturation_sticky_o,
    output logic                         protocol_error_sticky_o
);
  import trecap_core_pkg::*;
  import trecap_iface_pkg::*;


    // Implementation-local delay history. This is deliberately pinned here rather than added to
    // the mathematical generated configuration: it is a buffering/resource choice, not a change
    // to the Phase-2 algorithm contract.
    localparam int unsigned DELAY_HISTORY_DEPTH  = 1024;
    localparam int unsigned DELAY_HISTORY_ADDR_W = $clog2(DELAY_HISTORY_DEPTH);
    // Public core overflow namespace follows the architecture-facing status contract:
    // bit 0 is arithmetic and bit 2 is retained-history/ring integrity.
    localparam logic [31:0] CORE_ARITHMETIC_OVERFLOW_MASK = 32'h0000_0001;
    localparam logic [31:0] CORE_HISTORY_OVERFLOW_MASK    = 32'h0000_0004;

    // Input acceptance and frame generation.
    logic sample_accept_w;
    logic input_ring_sample_ready_w;
    logic delay_x_valid_w;
    logic accepted_sample_valid_w;
    logic signed [SAMPLE_W-1:0] accepted_sample_w;
    logic [63:0] accepted_sample_idx_w;

    logic frame_valid_w;
    logic frame_ready_w;
    logic input_ring_frame_ready_w;

    // Thresholds belong to admitted frames, not to a later live CSR level. The
    // ordered metadata queue spans the FFT/canonicalizer latency without changing
    // any fixed-point operation. Full capacity backpressures only frame admission.
    localparam int unsigned FRAME_CONFIG_DEPTH = 4;
    localparam int unsigned FRAME_CONFIG_PTR_W = $clog2(FRAME_CONFIG_DEPTH);
    logic [T_MAG2_W-1:0] frame_thr2_q [0:FRAME_CONFIG_DEPTH-1];
    logic [63:0] frame_config_idx_q [0:FRAME_CONFIG_DEPTH-1];
    logic [FRAME_CONFIG_PTR_W-1:0] frame_config_wr_q, frame_config_rd_q;
    logic [FRAME_CONFIG_PTR_W:0] frame_config_count_q;
    logic frame_config_room_w, frame_config_match_w;
    logic frame_config_push_w, frame_config_pop_w;
    logic frame_config_protocol_q;
    logic mask_input_ready_w;
    logic [63:0] frame_idx_w;
    logic [63:0] frame_trigger_sample_idx_w;

    // Frame samples from input ring into analysis window.
    logic frame_sample_valid_w;
    logic frame_sample_ready_w;
    logic signed [SAMPLE_W-1:0] frame_sample_w;
    logic [63:0] frame_sample_idx_w;
    logic [P-1:0] frame_sample_offset_w;
    logic [63:0] frame_sample_frame_idx_w;
    logic frame_sample_last_w;

    // Analysis window -> FFT.
    logic window_valid_w;
    logic window_ready_w;
    logic signed [T_U_W-1:0] window_sample_w;
    logic [P-1:0] window_offset_w;
    logic [63:0] window_frame_idx_w;
    logic [63:0] window_source_sample_idx_w;
    logic window_last_w;

    // FFT -> Hermitian/canonical stream.
    logic fft_valid_w;
    logic fft_ready_w;
    logic signed [T_FFT_W-1:0] fft_re_w;
    logic signed [T_FFT_W-1:0] fft_im_w;
    logic [P-1:0] fft_bin_idx_w;
    logic [63:0] fft_frame_idx_w;
    logic fft_last_w;

    // Canonical -> mask/stat/builder stream.
    logic canon_valid_w;
    logic canon_ready_w;
    logic [63:0] canon_frame_idx_w;
    logic [P-1:0] canon_bin_idx_w;
    logic signed [T_CAN_W-1:0] canon_re_w;
    logic signed [T_CAN_W-1:0] canon_im_w;
    logic canon_unique_w;
    logic canon_self_conj_w;
    logic canon_last_w;

    // Masked unique/full-spectrum stream.
    logic mask_valid_w;
    logic mask_ready_w;
    logic [63:0] mask_frame_idx_w;
    logic [P-1:0] mask_bin_idx_w;
    logic signed [T_CAN_W-1:0] mask_re_w;
    logic signed [T_CAN_W-1:0] mask_im_w;
    logic [T_MAG2_W-1:0] mask_mag2_w;
    logic mask_pre_mask_w;
    logic mask_drop_w;
    logic mask_eligible_w;
    logic mask_unique_w;
    logic mask_last_w;

    trecap_frame_stats_t frame_stats_w;
    logic frame_stats_valid_w;
    logic [63:0] frame_stats_frame_idx_w;

    // Spectrum builder -> IFFT.
    logic spec_valid_w;
    logic spec_ready_w;
    logic [63:0] spec_frame_idx_w;
    logic [P-1:0] spec_bin_idx_w;
    logic signed [T_CAN_W-1:0] spec_re_w;
    logic signed [T_CAN_W-1:0] spec_im_w;
    logic spec_last_w;

    // IFFT -> synthesis WOLA.
    logic ifft_valid_w;
    logic ifft_ready_w;
    logic signed [T_IFFT_W-1:0] ifft_re_w;
    logic signed [T_IFFT_W-1:0] ifft_im_w;
    logic [P-1:0] ifft_sample_offset_w;
    logic [63:0] ifft_frame_idx_w;
    logic ifft_last_w;

    // WOLA -> delay/error metrics.
    logic wola_valid_w;
    logic wola_ready_w;
    logic signed [SAMPLE_W-1:0] wola_sample_w;
    logic [63:0] wola_sample_idx_w;
    logic [63:0] wola_frame_idx_w;
    logic wola_last_w;
    logic wola_busy_w;

    logic input_ring_busy_w;
    logic analysis_busy_w;
    logic fft_busy_w;
    logic ifft_busy_w;
    logic [63:0] scheduler_frame_count_w;

    logic delay_x_ready_w;
    logic [DELAY_HISTORY_ADDR_W:0] delay_history_occupancy_w;
    logic delay_history_full_w;
    logic delay_history_empty_w;
    logic delay_busy_w;
    logic [63:0] delay_x_count_w;
    logic [63:0] delay_y_count_w;
    logic [63:0] sum_abs_err_lo_w;
    logic [63:0] sum_sq_err_lo_w;
    logic [15:0] max_abs_err_w;
    logic [31:0] delay_overflow_flags_w;

    logic input_ring_overflow_w;
    logic frame_scheduler_error_w;
    logic analysis_saturation_w;
    logic analysis_protocol_w;
    logic fft_saturation_w;
    logic fft_protocol_w;
    logic canon_protocol_w;
    logic mask_overflow_w;
    logic builder_protocol_w;
    logic ifft_saturation_w;
    logic ifft_protocol_w;
    logic wola_saturation_w;
    logic wola_protocol_w;
    logic delay_metric_overflow_w;
    logic delay_protocol_w;

    // Atomic ready/valid fork: the input ring and delayed-x history either accept the same public
    // sample on the same edge or neither accepts it. The ring's registered accept pulse remains
    // scheduler-only and is never presented to a backpressurable consumer.
    assign sample_ready_o = input_ring_sample_ready_w && delay_x_ready_w;
    assign delay_x_valid_w = sample_valid_i && input_ring_sample_ready_w;
    assign sample_accept_w = sample_valid_i && sample_ready_o;
    assign frame_config_match_w = (frame_config_count_q != '0) &&
        (frame_config_idx_q[frame_config_rd_q] == canon_frame_idx_w);
    assign canon_ready_w = mask_input_ready_w && frame_config_match_w;
    assign frame_config_pop_w = canon_valid_w && canon_ready_w && canon_last_w;
    assign frame_config_room_w = (frame_config_count_q < FRAME_CONFIG_DEPTH) ||
                                 frame_config_pop_w;
    assign frame_ready_w = input_ring_frame_ready_w && frame_config_room_w;
    assign frame_config_push_w = frame_valid_w && frame_ready_w;

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            frame_config_wr_q <= '0;
            frame_config_rd_q <= '0;
            frame_config_count_q <= '0;
            frame_config_protocol_q <= 1'b0;
        end else if (clear_i || source_discontinuity_i) begin
            frame_config_wr_q <= '0;
            frame_config_rd_q <= '0;
            frame_config_count_q <= '0;
            frame_config_protocol_q <= 1'b0;
        end else begin
            if (clear_sticky_i) frame_config_protocol_q <= 1'b0;
            if (canon_valid_w && !frame_config_match_w)
                frame_config_protocol_q <= 1'b1;
            if (frame_config_push_w) begin
                frame_thr2_q[frame_config_wr_q] <= thr2_i;
                frame_config_idx_q[frame_config_wr_q] <= frame_idx_w;
                frame_config_wr_q <= frame_config_wr_q + 1'b1;
            end
            if (frame_config_pop_w)
                frame_config_rd_q <= frame_config_rd_q + 1'b1;
            unique case ({frame_config_push_w, frame_config_pop_w})
                2'b10: frame_config_count_q <= frame_config_count_q + 1'b1;
                2'b01: frame_config_count_q <= frame_config_count_q - 1'b1;
                default: begin end
            endcase
        end
    end

    assign core_sample_count_o = delay_x_count_w;
    assign core_frame_count_o = scheduler_frame_count_w;
    assign core_error_sample_count_o = delay_y_count_w;
    assign core_sum_abs_err_lo_o = sum_abs_err_lo_w;
    assign core_sum_sq_err_lo_o = sum_sq_err_lo_w;
    assign core_max_abs_err_o = max_abs_err_w;
    assign core_metric_overflow_sticky_o = delay_metric_overflow_w;
    assign core_alive_o = rst_n && enable_i && (sample_accept_w || core_busy_o);

    // Busy is an in-flight contract, not merely an OR of visible stream valids. Analysis,
    // FFT, IFFT, and WOLA all have legal internal states with no output valid asserted.
    // The public output buffer is included so a held final y beat cannot look complete.
    assign core_busy_o = rst_n &&
                         ((frame_config_count_q != '0) || sample_accept_w || accepted_sample_valid_w ||
                          frame_valid_w || input_ring_busy_w ||
                          frame_sample_valid_w || analysis_busy_w || window_valid_w ||
                          fft_busy_w || fft_valid_w ||
                          canon_valid_w || mask_valid_w || spec_valid_w ||
                          ifft_busy_w || ifft_valid_w ||
                          wola_busy_w || wola_valid_w || delay_busy_w || y_valid_o);

    assign tap_frame_o.valid = frame_stats_valid_w;
    assign tap_frame_o.frame_idx = frame_stats_frame_idx_w;
    assign tap_frame_o.stats = frame_stats_w;

    assign tap_bin_valid_o = mask_valid_w && mask_ready_w && mask_unique_w;
    assign tap_bin_frame_idx_o = mask_frame_idx_w;
    assign tap_bin_idx_o = mask_bin_idx_w[BIN_IDX_W-1:0];
    assign tap_bin_re_o = mask_re_w;
    assign tap_bin_im_o = mask_im_w;
    assign tap_bin_mag2_o = mask_mag2_w;
    assign tap_bin_pre_mask_o = mask_pre_mask_w;
    assign tap_bin_mask_o = mask_drop_w;
    assign tap_bin_eligible_o = mask_eligible_w;
    // mask_last_w denotes full-spectrum bin L-1, so it cannot also be unique.
    // The artifact-facing tap is a compact unique-bin stream and terminates at L/2.
    assign tap_bin_last_o =
        tap_bin_valid_o && (mask_bin_idx_w == P'(L / 2));

    assign saturation_sticky_o = analysis_saturation_w | fft_saturation_w | ifft_saturation_w |
                                 wola_saturation_w;
    assign protocol_error_sticky_o = frame_scheduler_error_w | analysis_protocol_w | fft_protocol_w |
                                     canon_protocol_w | builder_protocol_w | ifft_protocol_w |
                                     wola_protocol_w | delay_protocol_w | frame_config_protocol_q;
    always_comb begin : p_core_overflow_map
        overflow_flags_o = 32'd0;
        if (delay_overflow_flags_w[0] || saturation_sticky_o ||
            mask_overflow_w || delay_metric_overflow_w) begin
            overflow_flags_o |= CORE_ARITHMETIC_OVERFLOW_MASK;
        end
        if (delay_overflow_flags_w[1] || input_ring_overflow_w) begin
            overflow_flags_o |= CORE_HISTORY_OVERFLOW_MASK;
        end
    end

    trecap_input_ring #(
        .SAMPLE_W( SAMPLE_W ),
        .L( L )
    ) u_input_ring (
        .clk( clk ),
        .rst_n( rst_n ),
        .enable_i( enable_i ),
        .clear_i( clear_i | source_discontinuity_i ),
        .clear_sticky_i( clear_sticky_i ),
        .sample_valid_i( sample_valid_i && delay_x_ready_w ),
        .sample_ready_o( input_ring_sample_ready_w ),
        .sample_i( sample_i.data ),
        .sample_idx_i( sample_i.sample_idx ),
        .sample_accept_pulse_o( accepted_sample_valid_w ),
        .accepted_sample_o( accepted_sample_w ),
        .accepted_sample_idx_o( accepted_sample_idx_w ),
        .frame_req_valid_i( frame_valid_w && frame_config_room_w ),
        .frame_req_ready_o( input_ring_frame_ready_w ),
        .frame_req_frame_idx_i( frame_idx_w ),
        .frame_req_trigger_sample_idx_i( frame_trigger_sample_idx_w ),
        .frame_sample_valid_o( frame_sample_valid_w ),
        .frame_sample_ready_i( frame_sample_ready_w ),
        .frame_sample_o( frame_sample_w ),
        .frame_sample_idx_o( frame_sample_idx_w ),
        .frame_sample_offset_o( frame_sample_offset_w ),
        .frame_sample_frame_idx_o( frame_sample_frame_idx_w ),
        .frame_sample_last_o( frame_sample_last_w ),
        .busy_o( input_ring_busy_w ),
        .overflow_sticky_o( input_ring_overflow_w )
    );

    trecap_frame_scheduler #(
        .H( T_HOP_H )
    ) u_frame_scheduler (
        .clk( clk ),
        .rst_n( rst_n ),
        .enable_i( enable_i ),
        .clear_i( clear_i | source_discontinuity_i ),
        .clear_sticky_i( clear_sticky_i ),
        .sample_accept_i( accepted_sample_valid_w ),
        .sample_idx_i( accepted_sample_idx_w ),
        .source_discontinuity_i( source_discontinuity_i ),
        .finite_stream_i( finite_stream_i ),
        .active_frame_count_i( active_frame_count_i ),
        .frame_valid_o( frame_valid_w ),
        .frame_ready_i( frame_ready_w ),
        .frame_idx_o( frame_idx_w ),
        .trigger_sample_idx_o( frame_trigger_sample_idx_w ),
        .frame_boundary_pulse_o( frame_boundary_pulse_o ),
        .frame_count_o( scheduler_frame_count_w ),
        .protocol_error_sticky_o( frame_scheduler_error_w )
    );

    trecap_analysis_window #(
        .L( L ),
        .P( P ),
        .SAMPLE_W( SAMPLE_W ),
        .WINDOW_W( T_QW_W ),
        .OUT_W( T_U_W ),
        .WINDOW_FILE( WINDOW_FILE )
    ) u_analysis_window (
        .clk( clk ),
        .rst_n( rst_n ),
        .enable_i( enable_i ),
        .clear_i( clear_i | source_discontinuity_i ),
        .clear_sticky_i( clear_sticky_i ),
        .frame_valid_i( frame_sample_valid_w && (frame_sample_offset_w == '0) ),
        .frame_ready_o( ),
        .frame_idx_i( frame_sample_frame_idx_w ),
        .frame_start_sample_idx_i( frame_sample_idx_w ),
        .sample_valid_i( frame_sample_valid_w ),
        .sample_ready_o( frame_sample_ready_w ),
        .sample_i( frame_sample_w ),
        .sample_idx_i( frame_sample_idx_w ),
        .out_valid_o( window_valid_w ),
        .out_ready_i( window_ready_w ),
        .out_sample_o( window_sample_w ),
        .out_sample_offset_o( window_offset_w ),
        .out_frame_idx_o( window_frame_idx_w ),
        .out_source_sample_idx_o( window_source_sample_idx_w ),
        .out_last_o( window_last_w ),
        .busy_o( analysis_busy_w ),
        .frame_accept_pulse_o( ),
        .sample_accept_pulse_o( ),
        .output_accept_pulse_o( ),
        .frame_done_pulse_o( ),
        .input_underrun_sticky_o( ),
        .output_backpressure_sticky_o( ),
        .protocol_error_sticky_o( analysis_protocol_w ),
        .window_oob_sticky_o( ),
        .saturation_sticky_o( analysis_saturation_w )
    );

    trecap_fft256 #(
        .L( L ),
        .P( P ),
        .IN_W( T_U_W ),
        .DATA_W( T_FFT_W ),
        .TWIDDLE_W( T_TWIDDLE_W ),
        .TWIDDLE_RE_FILE( TWIDDLE_RE_FILE ),
        .TWIDDLE_IM_FILE( TWIDDLE_IM_FILE )
    ) u_fft256 (
        .clk( clk ),
        .rst_n( rst_n ),
        .clear_i( clear_i | source_discontinuity_i ),
        .in_valid_i( window_valid_w ),
        .in_ready_o( window_ready_w ),
        .in_sample_i( window_sample_w ),
        .in_frame_idx_i( window_frame_idx_w ),
        .out_valid_o( fft_valid_w ),
        .out_ready_i( fft_ready_w ),
        .out_re_o( fft_re_w ),
        .out_im_o( fft_im_w ),
        .out_bin_idx_o( fft_bin_idx_w ),
        .out_frame_idx_o( fft_frame_idx_w ),
        .out_last_o( fft_last_w ),
        .busy_o( fft_busy_w ),
        .load_active_o( ),
        .compute_active_o( ),
        .output_active_o( ),
        .frame_done_pulse_o( ),
        .saturation_sticky_o( fft_saturation_w ),
        .protocol_error_sticky_o( fft_protocol_w ),
        .clear_sticky_i( clear_sticky_i )
    );

    trecap_hermitian_canonicalizer #(
        .IN_W( T_FFT_W ),
        .OUT_W( T_CAN_W )
    ) u_hermitian_canonicalizer (
        .clk( clk ),
        .rst_n( rst_n ),
        .enable_i( enable_i ),
        .clear_i( clear_i | source_discontinuity_i ),
        .clear_sticky_i( clear_sticky_i ),
        .in_valid_i( fft_valid_w ),
        .in_ready_o( fft_ready_w ),
        .in_frame_idx_i( fft_frame_idx_w ),
        .in_bin_idx_i( fft_bin_idx_w ),
        .in_re_i( fft_re_w ),
        .in_im_i( fft_im_w ),
        .in_last_i( fft_last_w ),
        .out_valid_o( canon_valid_w ),
        .out_ready_i( canon_ready_w ),
        .out_frame_idx_o( canon_frame_idx_w ),
        .out_bin_idx_o( canon_bin_idx_w ),
        .out_re_o( canon_re_w ),
        .out_im_o( canon_im_w ),
        .out_unique_o( canon_unique_w ),
        .out_self_conj_o( canon_self_conj_w ),
        .out_last_o( canon_last_w ),
        .protocol_error_sticky_o( canon_protocol_w )
    );

    trecap_mag2_mask #(
        .DATA_W( T_CAN_W ),
        .MAG2_W( T_MAG2_W )
    ) u_mag2_mask (
        .clk( clk ),
        .rst_n( rst_n ),
        .enable_i( enable_i ),
        .clear_i( clear_i | source_discontinuity_i ),
        .clear_metrics_i( clear_metrics_i ),
        .clear_sticky_i( clear_sticky_i ),
        .thr2_i( frame_thr2_q[frame_config_rd_q] ),
        .in_valid_i( canon_valid_w && frame_config_match_w ),
        .in_ready_o( mask_input_ready_w ),
        .in_frame_idx_i( canon_frame_idx_w ),
        .in_bin_idx_i( canon_bin_idx_w ),
        .in_re_i( canon_re_w ),
        .in_im_i( canon_im_w ),
        .in_unique_i( canon_unique_w ),
        .in_self_conj_i( canon_self_conj_w ),
        .in_last_i( canon_last_w ),
        .out_valid_o( mask_valid_w ),
        .out_ready_i( mask_ready_w ),
        .out_frame_idx_o( mask_frame_idx_w ),
        .out_bin_idx_o( mask_bin_idx_w ),
        .out_re_o( mask_re_w ),
        .out_im_o( mask_im_w ),
        .out_mag2_o( mask_mag2_w ),
        .out_pre_mask_o( mask_pre_mask_w ),
        .out_mask_o( mask_drop_w ),
        .out_eligible_o( mask_eligible_w ),
        .out_unique_o( mask_unique_w ),
        .out_last_o( mask_last_w ),
        .frame_stats_valid_o( frame_stats_valid_w ),
        .frame_stats_frame_idx_o( frame_stats_frame_idx_w ),
        .frame_stats_o( frame_stats_w ),
        .overflow_sticky_o( mask_overflow_w )
    );

    trecap_spectrum_mask_builder #(
        .DATA_W( T_CAN_W )
    ) u_spectrum_mask_builder (
        .clk( clk ),
        .rst_n( rst_n ),
        .enable_i( enable_i ),
        .clear_i( clear_i | source_discontinuity_i ),
        .clear_sticky_i( clear_sticky_i ),
        .in_valid_i( mask_valid_w ),
        .in_ready_o( mask_ready_w ),
        .in_frame_idx_i( mask_frame_idx_w ),
        .in_bin_idx_i( mask_bin_idx_w ),
        .in_re_i( mask_re_w ),
        .in_im_i( mask_im_w ),
        .in_mask_i( mask_drop_w ),
        .in_last_i( mask_last_w ),
        .out_valid_o( spec_valid_w ),
        .out_ready_i( spec_ready_w ),
        .out_frame_idx_o( spec_frame_idx_w ),
        .out_bin_idx_o( spec_bin_idx_w ),
        .out_re_o( spec_re_w ),
        .out_im_o( spec_im_w ),
        .out_last_o( spec_last_w ),
        .protocol_error_sticky_o( builder_protocol_w )
    );

    trecap_ifft256 #(
        .L( L ),
        .P( P ),
        .IN_W( T_CAN_W ),
        .DATA_W( T_IFFT_W ),
        .TWIDDLE_W( T_TWIDDLE_W ),
        .TWIDDLE_RE_FILE( TWIDDLE_RE_FILE ),
        .TWIDDLE_IM_FILE( TWIDDLE_IM_FILE ),
        .TWIDDLE_INV_RE_FILE( TWIDDLE_INV_RE_FILE ),
        .TWIDDLE_INV_IM_FILE( TWIDDLE_INV_IM_FILE )
    ) u_ifft256 (
        .clk( clk ),
        .rst_n( rst_n ),
        .clear_i( clear_i | source_discontinuity_i ),
        .in_valid_i( spec_valid_w ),
        .in_ready_o( spec_ready_w ),
        .in_re_i( spec_re_w ),
        .in_im_i( spec_im_w ),
        .in_frame_idx_i( spec_frame_idx_w ),
        .out_valid_o( ifft_valid_w ),
        .out_ready_i( ifft_ready_w ),
        .out_re_o( ifft_re_w ),
        .out_im_o( ifft_im_w ),
        .out_sample_offset_o( ifft_sample_offset_w ),
        .out_frame_idx_o( ifft_frame_idx_w ),
        .out_last_o( ifft_last_w ),
        .busy_o( ifft_busy_w ),
        .load_active_o( ),
        .compute_active_o( ),
        .output_active_o( ),
        .frame_done_pulse_o( ),
        .saturation_sticky_o( ifft_saturation_w ),
        .protocol_error_sticky_o( ifft_protocol_w ),
        .clear_sticky_i( clear_sticky_i )
    );

    trecap_synthesis_wola #(
        .IFFT_W( T_IFFT_W ),
        .OUT_W( SAMPLE_W ),
        .WINDOW_FILE( WINDOW_FILE )
    ) u_synthesis_wola (
        .clk( clk ),
        .rst_n( rst_n ),
        .enable_i( enable_i ),
        .clear_i( clear_i | source_discontinuity_i ),
        .clear_sticky_i( clear_sticky_i ),
        .in_valid_i( ifft_valid_w ),
        .in_ready_o( ifft_ready_w ),
        .in_frame_idx_i( ifft_frame_idx_w ),
        .in_sample_offset_i( ifft_sample_offset_w ),
        .in_re_i( ifft_re_w ),
        .in_im_i( ifft_im_w ),
        .in_last_i( ifft_last_w ),
        .drain_valid_i( tail_tick_valid_i ),
        .drain_ready_o( tail_tick_ready_o ),
        .drain_sample_idx_i( tail_tick_sample_idx_i ),
        .drain_last_i( tail_tick_last_i ),
        .drain_sample_count_i( tail_tick_count_i ),
        .out_valid_o( wola_valid_w ),
        .out_ready_i( wola_ready_w ),
        .out_sample_o( wola_sample_w ),
        .out_sample_idx_o( wola_sample_idx_w ),
        .out_frame_idx_o( wola_frame_idx_w ),
        .out_last_o( wola_last_w ),
        .busy_o( wola_busy_w ),
        .drain_active_o( tail_drain_active_o ),
        .drain_accept_pulse_o( tail_drain_accept_pulse_o ),
        .drain_done_pulse_o( tail_drain_done_pulse_o ),
        .accepted_output_count_o( wola_output_count_o ),
        .saturation_sticky_o( wola_saturation_w ),
        .protocol_error_sticky_o( wola_protocol_w )
    );

    trecap_delay_error_metrics #(
        .SAMPLE_W( SAMPLE_W ),
        .DELAY_D( T_DELAY_D ),
        .ERR_W( 16 ),
        .DEPTH( DELAY_HISTORY_DEPTH )
    ) u_delay_error_metrics (
        .clk( clk ),
        .rst_n( rst_n ),
        .enable_i( enable_i ),
        .clear_i( clear_i | source_discontinuity_i ),
        .clear_metrics_i( clear_metrics_i ),
        .clear_sticky_i( clear_sticky_i ),
        .x_valid_i( delay_x_valid_w ),
        .x_ready_o( delay_x_ready_w ),
        .x_sample_i( sample_i.data ),
        .x_sample_idx_i( sample_i.sample_idx ),
        .y_valid_i( wola_valid_w ),
        .y_ready_o( wola_ready_w ),
        .y_sample_i( wola_sample_w ),
        .y_sample_idx_i( wola_sample_idx_w ),
        .y_out_valid_o( y_valid_o ),
        .y_out_ready_i( y_ready_i ),
        .y_sample_o( y_sample_o ),
        .y_sample_data_o( y_data_o ),
        .y_sample_idx_o( y_sample_idx_o ),
        .tap_sample_o( tap_sample_o ),
        .tap_sample_valid_o( ),
        .accepted_x_count_o( delay_x_count_w ),
        .accepted_y_count_o( delay_y_count_w ),
        .history_occupancy_o( delay_history_occupancy_w ),
        .history_full_o( delay_history_full_w ),
        .history_empty_o( delay_history_empty_w ),
        .busy_o( delay_busy_w ),
        .sum_abs_err_lo_o( sum_abs_err_lo_w ),
        .sum_sq_err_lo_o( sum_sq_err_lo_w ),
        .max_abs_err_o( max_abs_err_w ),
        .overflow_flags_o( delay_overflow_flags_w ),
        .delay_not_full_sticky_o( ),
        .metric_overflow_sticky_o( delay_metric_overflow_w ),
        .protocol_error_sticky_o( delay_protocol_w ),
        .output_backpressure_sticky_o( )
    );

`ifndef SYNTHESIS
    initial begin
        if (SAMPLE_W != T_SAMPLE_W) begin
            $fatal(1, "trecap_core_top: SAMPLE_W must match generated T_SAMPLE_W");
        end
        if (L != T_FFT_L) begin
            $fatal(1, "trecap_core_top: L must match generated T_FFT_L");
        end
        if (P != T_FFT_P) begin
            $fatal(1, "trecap_core_top: P must match generated T_FFT_P");
        end
        if ((DELAY_HISTORY_DEPTH < (2*T_DELAY_D)) ||
            ((DELAY_HISTORY_DEPTH & (DELAY_HISTORY_DEPTH - 1)) != 0)) begin
            $fatal(1, "trecap_core_top: delay history must be power-of-two and at least 2*D");
        end
    end

    always_ff @(posedge clk) begin
        if (rst_n && !clear_i && !source_discontinuity_i) begin
            if (sample_accept_w !==
                (sample_valid_i && input_ring_sample_ready_w &&
                 delay_x_ready_w)) begin
                $error("trecap_core_top: public sample acceptance fork is not atomic");
            end
            if (delay_history_occupancy_w > (DELAY_HISTORY_ADDR_W + 1)'(DELAY_HISTORY_DEPTH)) begin
                $error("trecap_core_top: delay history occupancy exceeded depth");
            end
            if (delay_history_full_w && delay_history_empty_w) begin
                $error("trecap_core_top: delay history cannot be full and empty");
            end
        end
    end
`endif

endmodule : trecap_core_top

`default_nettype wire
