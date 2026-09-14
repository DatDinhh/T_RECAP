// SPDX-License-Identifier: MIT
// File class: [1] hand-written RTL.
// Layer: rtl/core/
// Owner: T-RECAP Phase 2 implementation.
// Purpose: Build the masked complex spectrum stream consumed by the IFFT engine.
// Contract: Core math only. Applies unique-bin mask decisions to both members of each
//           Hermitian pair while preserving natural-order streaming. No packets, DDR,
//           HPS, Ethernet, or dashboard behavior belongs here.
//
// Input contract:
//   The stream is canonical spectrum Xcan[0:L-1] in natural bin order.  Mask decisions
//   are meaningful only for unique bins 0..L/2.  For bins L/2+1..L-1 this module uses
//   the stored decision for mirror bin L-k.
//
// Output contract:
//   Xb[k] = 0 when mask[k] is asserted, otherwise Xcan[k], with Xb[L-k] using the
//   same unique-bin decision.  DC and Nyquist imaginary parts are forced to zero.

`default_nettype none

module trecap_spectrum_mask_builder
#(
    parameter int unsigned L      = trecap_core_pkg::T_FFT_L,
    parameter int unsigned P      = trecap_core_pkg::T_FFT_P,
    parameter int unsigned DATA_W = trecap_core_pkg::T_CAN_W
) (
    input  logic                         clk,
    input  logic                         rst_n,
    input  logic                         enable_i,
    input  logic                         clear_i,
    input  logic                         clear_sticky_i,

    input  logic                         in_valid_i,
    output logic                         in_ready_o,
    input  logic [63:0]                  in_frame_idx_i,
    input  logic [P-1:0]                 in_bin_idx_i,
    input  logic signed [DATA_W-1:0]     in_re_i,
    input  logic signed [DATA_W-1:0]     in_im_i,
    input  logic                         in_mask_i,
    input  logic                         in_last_i,

    output logic                         out_valid_o,
    input  logic                         out_ready_i,
    output logic [63:0]                  out_frame_idx_o,
    output logic [P-1:0]                 out_bin_idx_o,
    output logic signed [DATA_W-1:0]     out_re_o,
    output logic signed [DATA_W-1:0]     out_im_o,
    output logic                         out_last_o,

    output logic                         protocol_error_sticky_o
);
  import trecap_core_pkg::*;


    localparam int unsigned UNIQUE_BINS  = (L / 2) + 1;
    localparam int unsigned UNIQUE_IDX_W = (UNIQUE_BINS <= 1) ? 1 : $clog2(UNIQUE_BINS);
    localparam logic [P-1:0] LAST_BIN    = P'(L - 1);
    localparam logic [P-1:0] NYQ_BIN     = P'(L / 2);
    localparam logic [P:0]   L_WIDE      = L;

    logic mask_table_q [0:UNIQUE_BINS-1];

    logic                         out_valid_q;
    logic [63:0]                  out_frame_idx_q;
    logic [P-1:0]                 out_bin_idx_q;
    logic signed [DATA_W-1:0]     out_re_q;
    logic signed [DATA_W-1:0]     out_im_q;
    logic                         out_last_q;

    logic [P-1:0]                 expected_bin_q;
    logic [63:0]                  current_frame_q;
    logic                         have_frame_q;

    logic                         in_accept;
    logic                         out_accept;
    logic                         unique_bin_comb;
    logic                         self_conj_bin_comb;
    logic [P:0]                   mirror_bin_wide;
    logic [P-1:0]                 mirror_bin;
    logic [UNIQUE_IDX_W-1:0]      table_idx;
    logic                         stored_mirror_mask;
    logic                         effective_mask;
    logic signed [DATA_W-1:0]     effective_re;
    logic signed [DATA_W-1:0]     effective_im;
    logic                         sequence_error_comb;

    assign in_accept  = in_valid_i && in_ready_o;
    assign out_accept = out_valid_o && out_ready_i;

    // One-entry registered output stage.  Holding valid while ready is low is legal.
    assign in_ready_o = enable_i && !clear_i && (!out_valid_q || out_ready_i);

    assign unique_bin_comb    = (in_bin_idx_i <= NYQ_BIN);
    assign self_conj_bin_comb = (in_bin_idx_i == '0) || (in_bin_idx_i == NYQ_BIN);
    assign mirror_bin_wide    = L_WIDE - {1'b0, in_bin_idx_i};
    assign mirror_bin         = mirror_bin_wide[P-1:0];
    assign table_idx          = unique_bin_comb ?
                                in_bin_idx_i[UNIQUE_IDX_W-1:0] : mirror_bin[UNIQUE_IDX_W-1:0];
    assign stored_mirror_mask = mask_table_q[table_idx];
    assign effective_mask     = unique_bin_comb ? in_mask_i : stored_mirror_mask;
    assign effective_re       = effective_mask ? '0 : in_re_i;
    assign effective_im       = (effective_mask || self_conj_bin_comb) ? '0 : in_im_i;

    assign out_valid_o     = out_valid_q;
    assign out_frame_idx_o = out_frame_idx_q;
    assign out_bin_idx_o   = out_bin_idx_q;
    assign out_re_o        = out_re_q;
    assign out_im_o        = out_im_q;
    assign out_last_o      = out_last_q;

    integer mask_clear_i;

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
                if (have_frame_q && (in_frame_idx_i != current_frame_q)) begin
                    sequence_error_comb = 1'b1;
                end
            end else begin
                if (in_frame_idx_i != current_frame_q) begin
                    sequence_error_comb = 1'b1;
                end
                if (in_bin_idx_i != expected_bin_q) begin
                    sequence_error_comb = 1'b1;
                end
            end

            if (in_last_i != (in_bin_idx_i == LAST_BIN)) begin
                sequence_error_comb = 1'b1;
            end
            if (self_conj_bin_comb && (in_im_i != '0)) begin
                sequence_error_comb = 1'b1;
            end
            if (!unique_bin_comb && in_mask_i) begin
                // Upstream mask decisions are unique-bin decisions.  Non-unique
                // bins get their decision from the stored mirror entry.
                sequence_error_comb = 1'b1;
            end
        end
    end

    always_ff @(posedge clk or negedge rst_n) begin : p_spectrum_mask_builder
        if (!rst_n) begin
            out_valid_q <= 1'b0;
            out_frame_idx_q <= 64'd0;
            out_bin_idx_q <= '0;
            out_re_q <= '0;
            out_im_q <= '0;
            out_last_q <= 1'b0;
            expected_bin_q <= '0;
            current_frame_q <= 64'd0;
            have_frame_q <= 1'b0;
            protocol_error_sticky_o <= 1'b0;
            for (mask_clear_i = 0; mask_clear_i < UNIQUE_BINS; mask_clear_i = mask_clear_i + 1) begin
                mask_table_q[mask_clear_i] <= 1'b0;
            end
        end else begin
            if (clear_i) begin
                out_valid_q <= 1'b0;
                out_last_q <= 1'b0;
                expected_bin_q <= '0;
                current_frame_q <= 64'd0;
                have_frame_q <= 1'b0;
                protocol_error_sticky_o <= 1'b0;
                for (mask_clear_i = 0; mask_clear_i < UNIQUE_BINS; mask_clear_i = mask_clear_i + 1) begin
                    mask_table_q[mask_clear_i] <= 1'b0;
                end
            end else begin
                if (clear_sticky_i) begin
                    protocol_error_sticky_o <= 1'b0;
                end

                if (out_accept && !in_accept) begin
                    out_valid_q <= 1'b0;
                    out_last_q <= 1'b0;
                end

                if (in_accept) begin
                    out_valid_q <= 1'b1;
                    out_frame_idx_q <= in_frame_idx_i;
                    out_bin_idx_q <= in_bin_idx_i;
                    out_re_q <= effective_re;
                    out_im_q <= effective_im;
                    out_last_q <= in_last_i;

                    if (unique_bin_comb) begin
                        mask_table_q[table_idx] <= in_mask_i;
                    end

                    if (!have_frame_q || (in_bin_idx_i == '0)) begin
                        current_frame_q <= in_frame_idx_i;
                        expected_bin_q <= P'(1);
                        have_frame_q <= !in_last_i;
                    end else begin
                        if (in_bin_idx_i == LAST_BIN) begin
                            expected_bin_q <= '0;
                            have_frame_q <= 1'b0;
                        end else begin
                            expected_bin_q <= in_bin_idx_i + P'(1);
                            have_frame_q <= 1'b1;
                        end
                    end

                    if (sequence_error_comb) begin
                        protocol_error_sticky_o <= 1'b1;
                    end
                end
            end
        end
    end

`ifndef SYNTHESIS
    initial begin
        if (L != T_FFT_L) begin
            $fatal(1, "trecap_spectrum_mask_builder: L must match generated T_FFT_L");
        end
        if (P != T_FFT_P) begin
            $fatal(1, "trecap_spectrum_mask_builder: P must match generated T_FFT_P");
        end
        if (DATA_W != T_CAN_W) begin
            $fatal(1, "trecap_spectrum_mask_builder: DATA_W must match generated T_CAN_W");
        end
        if (UNIQUE_BINS != T_UNIQUE_BINS) begin
            $fatal(1, "trecap_spectrum_mask_builder: UNIQUE_BINS mismatch");
        end
    end
`endif

endmodule : trecap_spectrum_mask_builder

`default_nettype wire
