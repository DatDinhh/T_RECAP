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
#(
    parameter int unsigned L     = trecap_core_pkg::T_FFT_L,
    parameter int unsigned P     = trecap_core_pkg::T_FFT_P,
    parameter int unsigned IN_W  = trecap_core_pkg::T_FFT_W,
    parameter int unsigned OUT_W = trecap_core_pkg::T_CAN_W
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
  import trecap_core_pkg::*;


    localparam logic [P-1:0] LAST_BIN = P'(L - 1);
    localparam logic [P-1:0] NYQ_BIN = P'(L / 2);
    localparam logic [P:0] L_WIDE = (P+1)'(L);
    localparam int unsigned COMPLEX_W = 2 * IN_W;

    typedef enum logic [2:0] {S_LOAD, S_READ, S_PRE, S_ROUND, S_EMIT, S_FAULT} state_t;
    state_t state_q;
    logic [P-1:0] expected_bin_q, emit_bin_q;
    logic [63:0] frame_idx_q;
    logic have_frame_q, in_accept, out_accept, read_pair, malformed_input;

    // One packed M10K true-dual-port store. Port A writes during frame load
    // and reads the positive member of a pair; port B reads its mirror.
    // There are no content or read-data resets and no read/write overlap.
    (* ramstyle = "M10K" *) logic [COMPLEX_W-1:0] frame_mem [0:L-1];
    logic [COMPLEX_W-1:0] pos_data_q, neg_data_q;
    logic [P-1:0] pos_bin, neg_bin, port_a_addr;
    logic [P:0] mirror_bin;
    logic emit_self_conj, emit_unique, emit_negative_half;
    logic signed [IN_W-1:0] pos_re, pos_im, neg_re, neg_im, raw_re_q;
    logic signed [IN_W:0] pair_re_pre_q, pair_im_pre_q;
    logic signed [OUT_W:0] neg_pair_im_pre;
    logic signed [OUT_W-1:0] raw_re_sat, pair_re_sat, pair_im_sat, neg_pair_im_sat;
    logic raw_re_sat_any, pair_re_sat_any, pair_im_sat_any, neg_pair_im_sat_any;
    logic signed [OUT_W-1:0] out_re_q, out_im_q;
    logic out_sat_q;

    assign in_ready_o = rst_n && enable_i && !clear_i && (state_q == S_LOAD);
    assign in_accept = in_valid_i && in_ready_o;
    assign malformed_input = (in_bin_idx_i != expected_bin_q) ||
                             ((in_bin_idx_i == LAST_BIN) != in_last_i) ||
                             (have_frame_q && (in_frame_idx_i != frame_idx_q));
    assign out_valid_o = rst_n && enable_i && !clear_i && (state_q == S_EMIT);
    assign out_accept = out_valid_o && out_ready_i;
    assign out_frame_idx_o = frame_idx_q;
    assign out_bin_idx_o = emit_bin_q;
    assign out_unique_o = emit_unique;
    assign out_self_conj_o = emit_self_conj;
    assign out_last_o = (emit_bin_q == LAST_BIN);
    assign out_re_o = out_re_q;
    assign out_im_o = out_im_q;

    assign emit_unique = (emit_bin_q <= NYQ_BIN);
    assign emit_self_conj = (emit_bin_q == '0) || (emit_bin_q == NYQ_BIN);
    assign emit_negative_half = (emit_bin_q > NYQ_BIN);
    assign mirror_bin = L_WIDE - {1'b0, emit_bin_q};
    assign pos_bin = emit_negative_half ? mirror_bin[P-1:0] : emit_bin_q;
    assign neg_bin = emit_negative_half ? emit_bin_q : mirror_bin[P-1:0];
    assign read_pair = rst_n && enable_i && !clear_i && (state_q == S_READ);

    assign port_a_addr = in_accept ? in_bin_idx_i : pos_bin;

    // Synchronous RAM ports. Self-conjugate bins may read the same address
    // through both ports; no collision is possible because both are reads.
    always @(posedge clk) begin
        if (in_accept && !malformed_input) frame_mem[port_a_addr] <= {in_re_i, in_im_i};
        if (read_pair) pos_data_q <= frame_mem[port_a_addr];
    end
    always @(posedge clk) begin
        if (read_pair) neg_data_q <= frame_mem[neg_bin];
    end
    assign pos_re = $signed(pos_data_q[COMPLEX_W-1:IN_W]);
    assign pos_im = $signed(pos_data_q[IN_W-1:0]);
    assign neg_re = $signed(neg_data_q[COMPLEX_W-1:IN_W]);
    assign neg_im = $signed(neg_data_q[IN_W-1:0]);
    assign neg_pair_im_pre = -$signed({pair_im_sat[OUT_W-1], pair_im_sat});

    trecap_round_sat #(.IN_W(IN_W), .OUT_W(OUT_W), .SHIFT(0))
        u_raw_re_sat (.value_i(raw_re_q), .value_o(raw_re_sat),
                      .sat_hi_o(), .sat_lo_o(), .sat_any_o(raw_re_sat_any));
    trecap_round_sat #(.IN_W(IN_W+1), .OUT_W(OUT_W), .SHIFT(1))
        u_pair_re_sat (.value_i(pair_re_pre_q), .value_o(pair_re_sat),
                       .sat_hi_o(), .sat_lo_o(), .sat_any_o(pair_re_sat_any));
    trecap_round_sat #(.IN_W(IN_W+1), .OUT_W(OUT_W), .SHIFT(1))
        u_pair_im_sat (.value_i(pair_im_pre_q), .value_o(pair_im_sat),
                       .sat_hi_o(), .sat_lo_o(), .sat_any_o(pair_im_sat_any));
    trecap_round_sat #(.IN_W(OUT_W+1), .OUT_W(OUT_W), .SHIFT(0))
        u_neg_pair_im_sat (.value_i(neg_pair_im_pre), .value_o(neg_pair_im_sat),
                           .sat_hi_o(), .sat_lo_o(), .sat_any_o(neg_pair_im_sat_any));

    // Register the widened pre-adds before round/saturate. The negative
    // half negates the already rounded positive imaginary value, preserving
    // the specified tie behavior; it does not round the opposite pre-add.
    always_ff @(posedge clk) begin
        if (rst_n && enable_i && !clear_i) begin
            if (state_q == S_PRE) begin
                raw_re_q <= pos_re;
                pair_re_pre_q <= $signed({pos_re[IN_W-1], pos_re}) +
                                 $signed({neg_re[IN_W-1], neg_re});
                pair_im_pre_q <= $signed({pos_im[IN_W-1], pos_im}) -
                                 $signed({neg_im[IN_W-1], neg_im});
            end
            if (state_q == S_ROUND) begin
                if (emit_self_conj) begin
                    out_re_q <= raw_re_sat;
                    out_im_q <= '0;
                    out_sat_q <= raw_re_sat_any;
                end else begin
                    out_re_q <= pair_re_sat;
                    out_im_q <= emit_negative_half ? neg_pair_im_sat : pair_im_sat;
                    out_sat_q <= pair_re_sat_any | pair_im_sat_any |
                                 (emit_negative_half && neg_pair_im_sat_any);
                end
            end
        end
    end

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state_q <= S_LOAD;
            expected_bin_q <= '0;
            emit_bin_q <= '0;
            frame_idx_q <= '0;
            have_frame_q <= 1'b0;
            protocol_error_sticky_o <= 1'b0;
        end else if (clear_i) begin
            state_q <= S_LOAD;
            expected_bin_q <= '0;
            emit_bin_q <= '0;
            frame_idx_q <= '0;
            have_frame_q <= 1'b0;
            protocol_error_sticky_o <= 1'b0;
        end else begin
            if (clear_sticky_i) protocol_error_sticky_o <= 1'b0;
            if (!enable_i) begin
                state_q <= S_LOAD;
                expected_bin_q <= '0;
                emit_bin_q <= '0;
                have_frame_q <= 1'b0;
            end else begin
                case (state_q)
                    S_LOAD: if (in_accept) begin
                        if (malformed_input) begin
                            // Never read an incomplete memory epoch. Clear or
                            // disable starts a new frame; clearing sticky bits
                            // alone does not recover the datapath.
                            state_q <= S_FAULT;
                            protocol_error_sticky_o <= 1'b1;
                        end else begin
                            if (!have_frame_q) begin
                                frame_idx_q <= in_frame_idx_i;
                                have_frame_q <= 1'b1;
                            end
                            if (((in_bin_idx_i == '0) || (in_bin_idx_i == NYQ_BIN)) &&
                                (in_im_i != '0)) protocol_error_sticky_o <= 1'b1;
                            expected_bin_q <= in_bin_idx_i + P'(1);
                            if (in_bin_idx_i == LAST_BIN) begin
                                state_q <= S_READ;
                                emit_bin_q <= '0;
                                expected_bin_q <= '0;
                                have_frame_q <= 1'b0;
                            end
                        end
                    end
                    S_READ: state_q <= S_PRE;
                    S_PRE: state_q <= S_ROUND;
                    S_ROUND: state_q <= S_EMIT;
                    S_EMIT: if (out_accept) begin
                        if (out_sat_q) protocol_error_sticky_o <= 1'b1;
                        if (emit_bin_q == LAST_BIN) begin
                            state_q <= S_LOAD;
                            emit_bin_q <= '0;
                        end else begin
                            emit_bin_q <= emit_bin_q + P'(1);
                            state_q <= S_READ;
                        end
                    end
                    S_FAULT: begin
                        protocol_error_sticky_o <= 1'b1;
                    end
                    default: begin
                        state_q <= S_FAULT;
                        expected_bin_q <= '0;
                        have_frame_q <= 1'b0;
                        protocol_error_sticky_o <= 1'b1;
                    end
                endcase
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
