// SPDX-License-Identifier: MIT
// File class: [1] hand-written RTL.
// Layer: rtl/core/
// Owner: T-RECAP Phase 2 implementation.
// Purpose: Compute canonical-bin magnitude-squared, unique-bin threshold decisions,
//          protection rules, and per-frame spectral statistics.
// Contract: Core math only. This block does not build packets, write DDR, talk to HPS,
//           or create any backpressure from telemetry/dashboard layers.
//
// Revision-J mapping:
//   mag2[k]        = Re{Xcan[k]}^2 + Im{Xcan[k]}^2 for unique bins 0..L/2
//   pre_mask[k]    = (mag2[k] < THR2)
//   mask[k]        = 0 for protected DC/Nyquist bins, otherwise pre_mask[k]
//   eligible[k]    = epsilon[k] from the spec protection rule
//   wgt[k]         = 1 for DC/Nyquist, 2 for interior unique bins
//
// This module streams all L canonical bins onward.  For non-unique bins, mask/eligible
// are driven low and mag2 is diagnostic only.  The actual construction of Xb[k] and
// Xb[L-k] is owned by trecap_spectrum_mask_builder.sv.

`default_nettype none

module trecap_mag2_mask
  import trecap_core_pkg::*;
  import trecap_iface_pkg::*;
#(
    parameter int unsigned L      = T_FFT_L,
    parameter int unsigned P      = T_FFT_P,
    parameter int unsigned DATA_W = T_CAN_W,
    parameter int unsigned MAG2_W = T_MAG2_W
) (
    input  logic                         clk,
    input  logic                         rst_n,
    input  logic                         enable_i,
    input  logic                         clear_i,
    input  logic                         clear_metrics_i,
    input  logic                         clear_sticky_i,
    input  logic [MAG2_W-1:0]            thr2_i,

    input  logic                         in_valid_i,
    output logic                         in_ready_o,
    input  logic [63:0]                  in_frame_idx_i,
    input  logic [P-1:0]                 in_bin_idx_i,
    input  logic signed [DATA_W-1:0]     in_re_i,
    input  logic signed [DATA_W-1:0]     in_im_i,
    input  logic                         in_unique_i,
    input  logic                         in_self_conj_i,
    input  logic                         in_last_i,

    output logic                         out_valid_o,
    input  logic                         out_ready_i,
    output logic [63:0]                  out_frame_idx_o,
    output logic [P-1:0]                 out_bin_idx_o,
    output logic signed [DATA_W-1:0]     out_re_o,
    output logic signed [DATA_W-1:0]     out_im_o,
    output logic [MAG2_W-1:0]            out_mag2_o,
    output logic                         out_pre_mask_o,
    output logic                         out_mask_o,
    output logic                         out_eligible_o,
    output logic                         out_unique_o,
    output logic                         out_last_o,

    output logic                         frame_stats_valid_o,
    output logic [63:0]                  frame_stats_frame_idx_o,
    output trecap_frame_stats_t          frame_stats_o,
    output logic                         overflow_sticky_o
);

    localparam logic [P-1:0] LAST_BIN = P'(L - 1);
    localparam logic [P-1:0] NYQ_BIN  = P'(L / 2);
    localparam int unsigned SQUARE_W  = DATA_W * 2;
    localparam int unsigned SUM_W     = SQUARE_W + 1;
    localparam int unsigned METRIC_ADD_W = 65;

    logic                         out_valid_q;
    logic [63:0]                  out_frame_idx_q;
    logic [P-1:0]                 out_bin_idx_q;
    logic signed [DATA_W-1:0]     out_re_q;
    logic signed [DATA_W-1:0]     out_im_q;
    logic [MAG2_W-1:0]            out_mag2_q;
    logic                         out_pre_mask_q;
    logic                         out_mask_q;
    logic                         out_eligible_q;
    logic                         out_unique_q;
    logic                         out_last_q;

    logic [63:0]                  frame_idx_q;
    logic [P-1:0]                 expected_bin_q;
    logic                         have_frame_q;
    logic [31:0]                  unique_bins_q;
    logic [31:0]                  unique_suppressed_bins_q;
    logic [31:0]                  eligible_unique_bins_q;
    logic [31:0]                  eligible_suppressed_bins_q;
    logic [63:0]                  eligible_kept_mag2_lo_q;
    logic [63:0]                  eligible_total_mag2_lo_q;
    logic                         mag2_truncated_q;
    logic                         overflow_sticky_q;

    logic [SQUARE_W-1:0]          re_square_u;
    logic [SQUARE_W-1:0]          im_square_u;
    logic signed [SQUARE_W-1:0]   re_operand_wide_s;
    logic signed [SQUARE_W-1:0]   im_operand_wide_s;
    logic [SUM_W-1:0]             mag2_full;
    logic [MAG2_W-1:0]            mag2_value;
    logic                         mag2_width_overflow;

    logic                         self_conj_bin_comb;
    logic                         protected_bin_comb;
    logic                         eligible_comb;
    logic                         pre_mask_comb;
    logic                         mask_comb;
    logic                         interior_unique_comb;

    logic [METRIC_ADD_W-1:0]      weighted_mag2_ext;
    logic [METRIC_ADD_W-1:0]      eligible_total_addend_ext;
    logic [METRIC_ADD_W-1:0]      eligible_kept_addend_ext;
    logic [METRIC_ADD_W-1:0]      total_add_ext;
    logic [METRIC_ADD_W-1:0]      kept_add_ext;
    logic                         total_add_overflow;
    logic                         kept_add_overflow;
    logic                         total_addend_overflow;
    logic                         kept_addend_overflow;

    logic                         in_accept;
    logic                         out_accept;
    logic                         sequence_error_comb;

    assign in_accept  = in_valid_i && in_ready_o;
    assign out_accept = out_valid_o && out_ready_i;

    // One-entry registered output stage.  Normal ready/valid backpressure is legal;
    // it is not treated as a protocol error.
    assign in_ready_o = enable_i && !clear_i && (!out_valid_q || out_ready_i);

    assign out_valid_o     = out_valid_q;
    assign out_frame_idx_o = out_frame_idx_q;
    assign out_bin_idx_o   = out_bin_idx_q;
    assign out_re_o        = out_re_q;
    assign out_im_o        = out_im_q;
    assign out_mag2_o      = out_mag2_q;
    assign out_pre_mask_o  = out_pre_mask_q;
    assign out_mask_o      = out_mask_q;
    assign out_eligible_o  = out_eligible_q;
    assign out_unique_o    = out_unique_q;
    assign out_last_o      = out_last_q;
    assign overflow_sticky_o = overflow_sticky_q;

    assign frame_stats_o.unique_bins              = unique_bins_q;
    assign frame_stats_o.unique_suppressed_bins   = unique_suppressed_bins_q;
    assign frame_stats_o.eligible_unique_bins     = eligible_unique_bins_q;
    assign frame_stats_o.eligible_suppressed_bins = eligible_suppressed_bins_q;
    assign frame_stats_o.eligible_kept_mag2_lo    = eligible_kept_mag2_lo_q;
    assign frame_stats_o.eligible_total_mag2_lo   = eligible_total_mag2_lo_q;
    assign frame_stats_o.mag2_truncated           = mag2_truncated_q;

    // Full-precision square and sum.  With DATA_W=28 and MAG2_W=56, the legal
    // Revision-J canonical range fits in MAG2_W bits; the extra SUM_W bit catches
    // any unexpected out-of-contract arithmetic range.
    // A SystemVerilog multiply otherwise inherits the operand width.  Squaring
    // two DATA_W values directly can therefore discard the upper DATA_W product
    // bits before assignment to SQUARE_W.  Widen one signed operand explicitly
    // so the multiply itself is SQUARE_W wide on every supported frontend.
    assign re_operand_wide_s =
        {{(SQUARE_W-DATA_W){in_re_i[DATA_W-1]}}, in_re_i};
    assign im_operand_wide_s =
        {{(SQUARE_W-DATA_W){in_im_i[DATA_W-1]}}, in_im_i};
    assign re_square_u =
        $unsigned(re_operand_wide_s * $signed(in_re_i));
    assign im_square_u =
        $unsigned(im_operand_wide_s * $signed(in_im_i));
    assign mag2_full   = {{(SUM_W-SQUARE_W){1'b0}}, re_square_u} +
                         {{(SUM_W-SQUARE_W){1'b0}}, im_square_u};

    assign mag2_width_overflow = |mag2_full[SUM_W-1:MAG2_W];
    assign mag2_value          = mag2_width_overflow ? {MAG2_W{1'b1}} : mag2_full[MAG2_W-1:0];

    assign self_conj_bin_comb = (in_bin_idx_i == '0) || (in_bin_idx_i == NYQ_BIN);
    assign protected_bin_comb = in_unique_i &&
                                (((in_bin_idx_i == '0) && T_PROTECT_DC) ||
                                 ((in_bin_idx_i == NYQ_BIN) && T_PROTECT_NYQ));
    assign eligible_comb        = in_unique_i && !protected_bin_comb;
    assign pre_mask_comb        = in_unique_i && (mag2_value < thr2_i);
    assign mask_comb            = eligible_comb && pre_mask_comb;
    assign interior_unique_comb = in_unique_i && !self_conj_bin_comb;

    // Reference-model equivalent for the two spectral energy counters:
    //
    //   weighted              = unique_bin_weight(k) * mag2[k]
    //   eligible_total_mag2  += weighted             iff eligible[k]
    //   eligible_kept_mag2   += weighted             iff eligible[k] && !mask[k]
    //
    // where unique_bin_weight is 1 for DC/Nyquist and 2 for interior unique bins.
    // Protected bins are not eligible, even though their pre_mask value is retained
    // for debug.  Non-unique mirror bins never contribute to either counter.
    assign weighted_mag2_ext = interior_unique_comb ?
                               ({{(METRIC_ADD_W-MAG2_W){1'b0}}, mag2_value} << 1) :
                               {{(METRIC_ADD_W-MAG2_W){1'b0}}, mag2_value};

    assign eligible_total_addend_ext = eligible_comb ? weighted_mag2_ext : '0;
    assign eligible_kept_addend_ext  = (eligible_comb && !mask_comb) ? weighted_mag2_ext : '0;

    assign total_add_ext = {1'b0, eligible_total_mag2_lo_q} + eligible_total_addend_ext;
    assign kept_add_ext  = {1'b0, eligible_kept_mag2_lo_q}  + eligible_kept_addend_ext;

    assign total_addend_overflow = |eligible_total_addend_ext[METRIC_ADD_W-1:64];
    assign kept_addend_overflow  = |eligible_kept_addend_ext[METRIC_ADD_W-1:64];
    assign total_add_overflow    = total_add_ext[64] | total_addend_overflow;
    assign kept_add_overflow     = kept_add_ext[64]  | kept_addend_overflow;

    always_comb begin
        sequence_error_comb = 1'b0;
        if (in_accept) begin
            if (!have_frame_q || (in_bin_idx_i == '0)) begin
                if (!have_frame_q && (in_bin_idx_i != '0)) begin
                    sequence_error_comb = 1'b1;
                end
                if (have_frame_q && (in_bin_idx_i == '0)) begin
                    sequence_error_comb = 1'b1;
                end
                if (in_frame_idx_i != frame_idx_q && have_frame_q) begin
                    sequence_error_comb = 1'b1;
                end
            end else begin
                if (in_frame_idx_i != frame_idx_q) begin
                    sequence_error_comb = 1'b1;
                end
                if (in_bin_idx_i != expected_bin_q) begin
                    sequence_error_comb = 1'b1;
                end
            end

            if (in_unique_i != (in_bin_idx_i <= NYQ_BIN)) begin
                sequence_error_comb = 1'b1;
            end
            if (in_self_conj_i != self_conj_bin_comb) begin
                sequence_error_comb = 1'b1;
            end
            if (in_last_i != (in_bin_idx_i == LAST_BIN)) begin
                sequence_error_comb = 1'b1;
            end
            if (in_self_conj_i && (in_im_i != '0)) begin
                sequence_error_comb = 1'b1;
            end
        end
    end

    always_ff @(posedge clk or negedge rst_n) begin : p_mag2_mask
        if (!rst_n) begin
            out_valid_q <= 1'b0;
            out_frame_idx_q <= 64'd0;
            out_bin_idx_q <= '0;
            out_re_q <= '0;
            out_im_q <= '0;
            out_mag2_q <= '0;
            out_pre_mask_q <= 1'b0;
            out_mask_q <= 1'b0;
            out_eligible_q <= 1'b0;
            out_unique_q <= 1'b0;
            out_last_q <= 1'b0;
            frame_idx_q <= 64'd0;
            expected_bin_q <= '0;
            have_frame_q <= 1'b0;
            unique_bins_q <= 32'd0;
            unique_suppressed_bins_q <= 32'd0;
            eligible_unique_bins_q <= 32'd0;
            eligible_suppressed_bins_q <= 32'd0;
            eligible_kept_mag2_lo_q <= 64'd0;
            eligible_total_mag2_lo_q <= 64'd0;
            mag2_truncated_q <= 1'b0;
            overflow_sticky_q <= 1'b0;
            frame_stats_valid_o <= 1'b0;
            frame_stats_frame_idx_o <= 64'd0;
        end else begin
            frame_stats_valid_o <= 1'b0;

            if (clear_i) begin
                out_valid_q <= 1'b0;
                out_last_q <= 1'b0;
                out_pre_mask_q <= 1'b0;
                frame_idx_q <= 64'd0;
                expected_bin_q <= '0;
                have_frame_q <= 1'b0;
                unique_bins_q <= 32'd0;
                unique_suppressed_bins_q <= 32'd0;
                eligible_unique_bins_q <= 32'd0;
                eligible_suppressed_bins_q <= 32'd0;
                eligible_kept_mag2_lo_q <= 64'd0;
                eligible_total_mag2_lo_q <= 64'd0;
                mag2_truncated_q <= 1'b0;
                overflow_sticky_q <= 1'b0;
            end else begin
                if (clear_sticky_i) begin
                    overflow_sticky_q <= 1'b0;
                end

                if (clear_metrics_i) begin
                    unique_bins_q <= 32'd0;
                    unique_suppressed_bins_q <= 32'd0;
                    eligible_unique_bins_q <= 32'd0;
                    eligible_suppressed_bins_q <= 32'd0;
                    eligible_kept_mag2_lo_q <= 64'd0;
                    eligible_total_mag2_lo_q <= 64'd0;
                    mag2_truncated_q <= 1'b0;
                end

                if (out_accept && !in_accept) begin
                    out_valid_q <= 1'b0;
                    out_last_q <= 1'b0;
                end

                if (in_accept) begin
                    out_valid_q <= 1'b1;
                    out_frame_idx_q <= in_frame_idx_i;
                    out_bin_idx_q <= in_bin_idx_i;
                    // Pass the canonical spectrum through unchanged.  The next block
                    // owns Xb construction for both k and L-k.
                    out_re_q <= in_re_i;
                    out_im_q <= in_self_conj_i ? '0 : in_im_i;
                    out_mag2_q <= mag2_value;
                    out_pre_mask_q <= pre_mask_comb;
                    out_mask_q <= mask_comb;
                    out_eligible_q <= eligible_comb;
                    out_unique_q <= in_unique_i;
                    out_last_q <= in_last_i;

                    if (!have_frame_q || (in_bin_idx_i == '0)) begin
                        frame_idx_q <= in_frame_idx_i;
                        expected_bin_q <= P'(1);
                        have_frame_q <= !in_last_i;
                        unique_bins_q <= in_unique_i ? 32'd1 : 32'd0;
                        unique_suppressed_bins_q <= (in_unique_i && mask_comb) ? 32'd1 : 32'd0;
                        eligible_unique_bins_q <= eligible_comb ? 32'd1 : 32'd0;
                        eligible_suppressed_bins_q <= (eligible_comb && mask_comb) ? 32'd1 : 32'd0;
                        eligible_total_mag2_lo_q <= eligible_total_addend_ext[63:0];
                        eligible_kept_mag2_lo_q <= eligible_kept_addend_ext[63:0];
                        mag2_truncated_q <= mag2_width_overflow |
                                            total_addend_overflow |
                                            kept_addend_overflow;
                        if (mag2_width_overflow || total_addend_overflow || kept_addend_overflow) begin
                            overflow_sticky_q <= 1'b1;
                        end
                    end else begin
                        if (in_unique_i) begin
                            unique_bins_q <= unique_bins_q + 32'd1;
                            if (mask_comb) begin
                                unique_suppressed_bins_q <= unique_suppressed_bins_q + 32'd1;
                            end
                        end

                        if (eligible_comb) begin
                            eligible_unique_bins_q <= eligible_unique_bins_q + 32'd1;
                            eligible_total_mag2_lo_q <= total_add_ext[63:0];
                            eligible_kept_mag2_lo_q <= kept_add_ext[63:0];
                            if (total_add_overflow || kept_add_overflow) begin
                                mag2_truncated_q <= 1'b1;
                                overflow_sticky_q <= 1'b1;
                            end

                            if (mask_comb) begin
                                eligible_suppressed_bins_q <= eligible_suppressed_bins_q + 32'd1;
                            end
                        end

                        if (mag2_width_overflow) begin
                            mag2_truncated_q <= 1'b1;
                            overflow_sticky_q <= 1'b1;
                        end

                        if (in_bin_idx_i == LAST_BIN) begin
                            expected_bin_q <= '0;
                            have_frame_q <= 1'b0;
                        end else begin
                            expected_bin_q <= in_bin_idx_i + P'(1);
                            have_frame_q <= 1'b1;
                        end
                    end

                    if (sequence_error_comb) begin
                        overflow_sticky_q <= 1'b1;
                    end

                    if (in_last_i) begin
                        frame_stats_valid_o <= 1'b1;
                        frame_stats_frame_idx_o <= in_frame_idx_i;
                    end
                end
            end
        end
    end

`ifndef SYNTHESIS
    initial begin
        if (L != T_FFT_L) begin
            $fatal(1, "trecap_mag2_mask: L must match generated T_FFT_L");
        end
        if (P != T_FFT_P) begin
            $fatal(1, "trecap_mag2_mask: P must match generated T_FFT_P");
        end
        if (DATA_W != T_CAN_W) begin
            $fatal(1, "trecap_mag2_mask: DATA_W must match generated T_CAN_W");
        end
        if (MAG2_W != T_MAG2_W) begin
            $fatal(1, "trecap_mag2_mask: MAG2_W must match generated T_MAG2_W");
        end
        if (MAG2_W != (2 * DATA_W)) begin
            $fatal(1, "trecap_mag2_mask: Revision-J baseline expects MAG2_W=2*DATA_W");
        end
        if (METRIC_ADD_W < (MAG2_W + 9)) begin
            $fatal(1, "trecap_mag2_mask: metric adder width is too small");
        end
    end
`endif

endmodule : trecap_mag2_mask

`default_nettype wire
