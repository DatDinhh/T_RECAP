// SPDX-License-Identifier: MIT
// File class: [1] hand-written RTL.
// Layer: rtl/fft/
// Owner: T-RECAP Phase 2 implementation.
// Purpose: Explicit fixed-point complex multiply with one final rounded shift and saturation.
// Contract: Implements the Revision J rule that product sums are formed at full precision before
//           the single round-to-nearest/ties-away-from-zero rescale. This block is core datapath
//           RTL only; it does not format telemetry, write DDR, or interact with HPS/Ethernet.

`default_nettype none

module trecap_complex_mul_q
#(
    parameter int unsigned A_W             = trecap_core_pkg::T_CAN_W,
    parameter int unsigned B_W             = trecap_core_pkg::T_TWIDDLE_W,
    parameter int unsigned OUT_W           = trecap_core_pkg::T_CAN_W,
    parameter int unsigned FRAC_SHIFT      = trecap_core_pkg::T_FRAC_F,
    parameter bit          REGISTER_OUTPUT = 1'b1
) (
    input  logic                         clk,
    input  logic                         rst_n,
    input  logic                         clear_i,

    input  logic                         valid_i,
    output logic                         ready_o,
    input  logic signed [A_W-1:0]        ar_i,
    input  logic signed [A_W-1:0]        ai_i,
    input  logic signed [B_W-1:0]        br_i,
    input  logic signed [B_W-1:0]        bi_i,

    output logic                         valid_o,
    input  logic                         ready_i,
    output logic signed [OUT_W-1:0]      pr_o,
    output logic signed [OUT_W-1:0]      pi_o,
    output logic                         sat_re_o,
    output logic                         sat_im_o,
    output logic                         sat_any_o,

    output logic                         input_accept_pulse_o,
    output logic                         output_accept_pulse_o
);
  import trecap_core_pkg::*;


    localparam int unsigned PROD_W = A_W + B_W;
    localparam int unsigned SUM_W  = PROD_W + 2;

    typedef logic signed [PROD_W-1:0] prod_s_t;
    typedef logic signed [SUM_W-1:0]  sum_s_t;

    prod_s_t ac_prod;
    prod_s_t bd_prod;
    prod_s_t ad_prod;
    prod_s_t bc_prod;
    sum_s_t  pre_re;
    sum_s_t  pre_im;

    logic signed [OUT_W-1:0] comb_re;
    logic signed [OUT_W-1:0] comb_im;
    logic                    comb_sat_re_hi;
    logic                    comb_sat_re_lo;
    logic                    comb_sat_im_hi;
    logic                    comb_sat_im_lo;
    logic                    comb_sat_re;
    logic                    comb_sat_im;

    assign ac_prod = ar_i * br_i;
    assign bd_prod = ai_i * bi_i;
    assign ad_prod = ar_i * bi_i;
    assign bc_prod = ai_i * br_i;

    assign pre_re = {{(SUM_W-PROD_W){ac_prod[PROD_W-1]}}, ac_prod} -
                    {{(SUM_W-PROD_W){bd_prod[PROD_W-1]}}, bd_prod};
    assign pre_im = {{(SUM_W-PROD_W){ad_prod[PROD_W-1]}}, ad_prod} +
                    {{(SUM_W-PROD_W){bc_prod[PROD_W-1]}}, bc_prod};

    trecap_round_sat #(
        .IN_W(SUM_W),
        .OUT_W(OUT_W),
        .SHIFT(FRAC_SHIFT)
    ) u_round_sat_re (
        .value_i(pre_re),
        .value_o(comb_re),
        .sat_hi_o(comb_sat_re_hi),
        .sat_lo_o(comb_sat_re_lo),
        .sat_any_o(comb_sat_re)
    );

    trecap_round_sat #(
        .IN_W(SUM_W),
        .OUT_W(OUT_W),
        .SHIFT(FRAC_SHIFT)
    ) u_round_sat_im (
        .value_i(pre_im),
        .value_o(comb_im),
        .sat_hi_o(comb_sat_im_hi),
        .sat_lo_o(comb_sat_im_lo),
        .sat_any_o(comb_sat_im)
    );

    generate
        if (REGISTER_OUTPUT) begin : gen_registered_output
            logic                    valid_q;
            logic signed [OUT_W-1:0] pr_q;
            logic signed [OUT_W-1:0] pi_q;
            logic                    sat_re_q;
            logic                    sat_im_q;
            logic                    can_accept;
            logic                    input_accept;
            logic                    output_accept;

            assign can_accept = !valid_q || ready_i;
            assign input_accept = valid_i && can_accept;
            assign output_accept = valid_q && ready_i;

            assign ready_o = can_accept;
            assign valid_o = valid_q;
            assign pr_o = pr_q;
            assign pi_o = pi_q;
            assign sat_re_o = sat_re_q;
            assign sat_im_o = sat_im_q;
            assign sat_any_o = sat_re_q || sat_im_q;
            assign input_accept_pulse_o = input_accept;
            assign output_accept_pulse_o = output_accept;

            always_ff @(posedge clk or negedge rst_n) begin
                if (!rst_n) begin
                    valid_q  <= 1'b0;
                    pr_q     <= '0;
                    pi_q     <= '0;
                    sat_re_q <= 1'b0;
                    sat_im_q <= 1'b0;
                end else begin
                    if (clear_i) begin
                        valid_q  <= 1'b0;
                        pr_q     <= '0;
                        pi_q     <= '0;
                        sat_re_q <= 1'b0;
                        sat_im_q <= 1'b0;
                    end else if (can_accept) begin
                        valid_q <= valid_i;
                        if (valid_i) begin
                            pr_q     <= comb_re;
                            pi_q     <= comb_im;
                            sat_re_q <= comb_sat_re;
                            sat_im_q <= comb_sat_im;
                        end else begin
                            pr_q     <= '0;
                            pi_q     <= '0;
                            sat_re_q <= 1'b0;
                            sat_im_q <= 1'b0;
                        end
                    end
                end
            end
        end else begin : gen_comb_output
            assign ready_o = ready_i;
            assign valid_o = valid_i;
            assign pr_o = comb_re;
            assign pi_o = comb_im;
            assign sat_re_o = comb_sat_re;
            assign sat_im_o = comb_sat_im;
            assign sat_any_o = comb_sat_re || comb_sat_im;
            assign input_accept_pulse_o = valid_i && ready_i;
            assign output_accept_pulse_o = valid_i && ready_i;

            logic unused_seq_inputs;
            always_comb begin
                unused_seq_inputs = clk ^ rst_n ^ clear_i ^ comb_sat_re_hi ^ comb_sat_re_lo ^
                                    comb_sat_im_hi ^ comb_sat_im_lo;
            end
        end
    endgenerate

`ifndef SYNTHESIS
    initial begin
        if ((A_W == 0) || (B_W == 0) || (OUT_W == 0)) begin
            $error("trecap_complex_mul_q: A_W, B_W, and OUT_W must all be nonzero");
        end
    end
`endif

endmodule : trecap_complex_mul_q

`default_nettype wire
