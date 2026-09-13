// SPDX-License-Identifier: MIT
// File class: [1] hand-written RTL.
// Layer: rtl/core/
// Owner: T-RECAP Phase 2 implementation.
// Purpose: Reference-model-compatible Hermitian canonicalization for real-input FFT frames.
// Contract: For each pair k and L-k, computes
//             R = rnd2(Re{X[k]} + Re{X[L-k]})
//             I = rnd2(Im{X[k]} - Im{X[L-k]})
//             Xcan[k]   = R + jI
//             Xcan[L-k] = R - jI
//           while forcing DC and Nyquist imaginary parts to zero. This block does not decide
//           masks, run IFFT/WOLA, format telemetry, write DDR, or interact with HPS/Ethernet.

`default_nettype none

module trecap_hermitian_canonicalizer
  import trecap_core_pkg::*;
#(
    parameter int unsigned L     = T_FFT_L,
    parameter int unsigned P     = T_FFT_P,
    parameter int unsigned IN_W  = T_FFT_W,
    parameter int unsigned OUT_W = T_CAN_W
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
    input  logic signed [IN_W-1:0]       in_re_i,
    input  logic signed [IN_W-1:0]       in_im_i,
    input  logic                         in_last_i,

    output logic                         out_valid_o,
    input  logic                         out_ready_i,
    output logic [63:0]                  out_frame_idx_o,
    output logic [P-1:0]                 out_bin_idx_o,
    output logic signed [OUT_W-1:0]      out_re_o,
    output logic signed [OUT_W-1:0]      out_im_o,
    output logic                         out_unique_o,
    output logic                         out_self_conj_o,
    output logic                         out_last_o,

    output logic                         protocol_error_sticky_o
);

    localparam int unsigned NYQ_INT = L / 2;
    localparam logic [P-1:0] LAST_BIN = L - 1;
    localparam logic [P-1:0] NYQ_BIN  = NYQ_INT;
    localparam logic [P:0]   L_WIDE   = L;

    typedef enum logic [1:0] {
        S_LOAD = 2'd0,
        S_EMIT = 2'd1
    } state_t;

    logic signed [IN_W-1:0] re_mem [0:L-1];
    logic signed [IN_W-1:0] im_mem [0:L-1];

    state_t      state_q;
    logic [P-1:0] expected_bin_q;
    logic [P-1:0] emit_bin_q;
    logic [63:0] frame_idx_q;
    logic        have_frame_q;

    logic        in_accept;
    logic        out_accept;
    logic        emit_self_conj;
    logic        emit_unique;
    logic        emit_negative_half;
    logic [P-1:0] emit_pos_bin;
    logic [P-1:0] emit_neg_bin;
    logic [P:0]   mirror_bin_wide;

    logic signed [IN_W-1:0] raw_re;
    logic signed [IN_W-1:0] raw_im;
    logic signed [IN_W:0]   pair_re_pre;
    logic signed [IN_W:0]   pair_im_pre;
    logic signed [OUT_W:0]  neg_pair_im_pre;

    logic signed [OUT_W-1:0] raw_re_sat;
    logic signed [OUT_W-1:0] pair_re_sat;
    logic signed [OUT_W-1:0] pair_im_sat;
    logic signed [OUT_W-1:0] neg_pair_im_sat;
    logic                    raw_re_sat_any;
    logic                    pair_re_sat_any;
    logic                    pair_im_sat_any;
    logic                    neg_pair_im_sat_any;

    logic signed [OUT_W-1:0] out_re_comb;
    logic signed [OUT_W-1:0] out_im_comb;
    logic                    out_sat_comb;

    assign in_accept = in_valid_i && in_ready_o;
    assign out_accept = out_valid_o && out_ready_i;

    assign in_ready_o = enable_i && !clear_i && (state_q == S_LOAD);
    assign out_valid_o = enable_i && (state_q == S_EMIT);
    assign out_frame_idx_o = frame_idx_q;
    assign out_bin_idx_o = emit_bin_q;
    assign out_unique_o = emit_unique;
    assign out_self_conj_o = emit_self_conj;
    assign out_last_o = (emit_bin_q == LAST_BIN);
    assign out_re_o = out_re_comb;
    assign out_im_o = out_im_comb;

    assign emit_unique = (emit_bin_q <= NYQ_BIN);
    assign emit_self_conj = (emit_bin_q == '0) || (emit_bin_q == NYQ_BIN);
    assign emit_negative_half = (emit_bin_q > NYQ_BIN);
    assign mirror_bin_wide = L_WIDE - {1'b0, emit_bin_q};
    assign emit_pos_bin = emit_negative_half ? mirror_bin_wide[P-1:0] : emit_bin_q;
    assign emit_neg_bin = emit_negative_half ? emit_bin_q : mirror_bin_wide[P-1:0];

    assign raw_re = re_mem[emit_bin_q];
    assign raw_im = im_mem[emit_bin_q];
    assign pair_re_pre = $signed({re_mem[emit_pos_bin][IN_W-1], re_mem[emit_pos_bin]}) +
                         $signed({re_mem[emit_neg_bin][IN_W-1], re_mem[emit_neg_bin]});
    assign pair_im_pre = $signed({im_mem[emit_pos_bin][IN_W-1], im_mem[emit_pos_bin]}) -
                         $signed({im_mem[emit_neg_bin][IN_W-1], im_mem[emit_neg_bin]});
    assign neg_pair_im_pre = -$signed({pair_im_sat[OUT_W-1], pair_im_sat});

    trecap_round_sat #(
        .IN_W( IN_W ),
        .OUT_W( OUT_W ),
        .SHIFT( 0 )
    ) u_raw_re_sat (
        .value_i( raw_re ),
        .value_o( raw_re_sat ),
        .sat_hi_o( ),
        .sat_lo_o( ),
        .sat_any_o( raw_re_sat_any )
    );

    trecap_round_sat #(
        .IN_W( IN_W + 1 ),
        .OUT_W( OUT_W ),
        .SHIFT( 1 )
    ) u_pair_re_sat (
        .value_i( pair_re_pre ),
        .value_o( pair_re_sat ),
        .sat_hi_o( ),
        .sat_lo_o( ),
        .sat_any_o( pair_re_sat_any )
    );

    trecap_round_sat #(
        .IN_W( IN_W + 1 ),
        .OUT_W( OUT_W ),
        .SHIFT( 1 )
    ) u_pair_im_sat (
        .value_i( pair_im_pre ),
        .value_o( pair_im_sat ),
        .sat_hi_o( ),
        .sat_lo_o( ),
        .sat_any_o( pair_im_sat_any )
    );

    trecap_round_sat #(
        .IN_W( OUT_W + 1 ),
        .OUT_W( OUT_W ),
        .SHIFT( 0 )
    ) u_neg_pair_im_sat (
        .value_i( neg_pair_im_pre ),
        .value_o( neg_pair_im_sat ),
        .sat_hi_o( ),
        .sat_lo_o( ),
        .sat_any_o( neg_pair_im_sat_any )
    );

    always_comb begin
        out_re_comb = '0;
        out_im_comb = '0;
        out_sat_comb = 1'b0;

        if (emit_self_conj) begin
            out_re_comb = raw_re_sat;
            out_im_comb = '0;
            out_sat_comb = raw_re_sat_any;
        end else if (emit_negative_half) begin
            out_re_comb = pair_re_sat;
            out_im_comb = neg_pair_im_sat;
            out_sat_comb = pair_re_sat_any | pair_im_sat_any | neg_pair_im_sat_any;
        end else begin
            out_re_comb = pair_re_sat;
            out_im_comb = pair_im_sat;
            out_sat_comb = pair_re_sat_any | pair_im_sat_any;
        end
    end

    always_ff @(posedge clk or negedge rst_n) begin : p_hermitian
        if (!rst_n) begin
            state_q                 <= S_LOAD;
            expected_bin_q          <= '0;
            emit_bin_q              <= '0;
            frame_idx_q             <= 64'd0;
            have_frame_q            <= 1'b0;
            protocol_error_sticky_o <= 1'b0;
        end else begin
            if (clear_i) begin
                state_q                 <= S_LOAD;
                expected_bin_q          <= '0;
                emit_bin_q              <= '0;
                frame_idx_q             <= 64'd0;
                have_frame_q            <= 1'b0;
                protocol_error_sticky_o <= 1'b0;
            end else begin
                if (clear_sticky_i) begin
                    protocol_error_sticky_o <= 1'b0;
                end

                if (!enable_i) begin
                    state_q <= S_LOAD;
                    expected_bin_q <= '0;
                    emit_bin_q <= '0;
                    have_frame_q <= 1'b0;
                end else begin
                    if (in_accept) begin
                        re_mem[in_bin_idx_i] <= in_re_i;
                        im_mem[in_bin_idx_i] <= in_im_i;

                        if (!have_frame_q || (in_bin_idx_i == '0)) begin
                            have_frame_q <= 1'b1;
                            frame_idx_q <= in_frame_idx_i;
                            expected_bin_q <= {{(P-1){1'b0}}, 1'b1};
                            if (in_bin_idx_i != '0) begin
                                protocol_error_sticky_o <= 1'b1;
                            end
                        end else begin
                            if (in_frame_idx_i != frame_idx_q) begin
                                protocol_error_sticky_o <= 1'b1;
                            end
                            if (in_bin_idx_i != expected_bin_q) begin
                                protocol_error_sticky_o <= 1'b1;
                            end
                            if (in_bin_idx_i == LAST_BIN) begin
                                expected_bin_q <= '0;
                                have_frame_q <= 1'b0;
                            end else begin
                                expected_bin_q <= in_bin_idx_i + {{(P-1){1'b0}}, 1'b1};
                            end
                        end

                        if ((in_bin_idx_i == LAST_BIN) != in_last_i) begin
                            protocol_error_sticky_o <= 1'b1;
                        end
                        if (((in_bin_idx_i == '0) || (in_bin_idx_i == NYQ_BIN)) && (in_im_i != '0)) begin
                            protocol_error_sticky_o <= 1'b1;
                        end
                        if (in_bin_idx_i == LAST_BIN) begin
                            state_q <= S_EMIT;
                            emit_bin_q <= '0;
                        end
                    end

                    if ((state_q == S_EMIT) && out_accept) begin
                        if (out_sat_comb) begin
                            protocol_error_sticky_o <= 1'b1;
                        end
                        if (emit_bin_q == LAST_BIN) begin
                            state_q <= S_LOAD;
                            emit_bin_q <= '0;
                        end else begin
                            emit_bin_q <= emit_bin_q + {{(P-1){1'b0}}, 1'b1};
                        end
                    end
                end
            end
        end
    end

`ifndef SYNTHESIS
    initial begin
        if (L != T_FFT_L) begin
            $fatal(1, "trecap_hermitian_canonicalizer: L must match generated T_FFT_L");
        end
        if (P != T_FFT_P) begin
            $fatal(1, "trecap_hermitian_canonicalizer: P must match generated T_FFT_P");
        end
        if (OUT_W != T_CAN_W) begin
            $fatal(1, "trecap_hermitian_canonicalizer: OUT_W must match generated T_CAN_W");
        end
        if (IN_W != T_FFT_W) begin
            $fatal(1, "trecap_hermitian_canonicalizer: IN_W must match generated T_FFT_W");
        end
    end
`endif

endmodule : trecap_hermitian_canonicalizer

`default_nettype wire
