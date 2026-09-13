// SPDX-License-Identifier: MIT
// File class: [1] hand-written RTL.
// Layer: rtl/fft/
// Owner: T-RECAP Phase 2 implementation.
// Purpose: One radix-2 fixed-point complex butterfly used by the iterative FFT/IFFT engines.
// Contract: Forms the complex twiddle product at full precision through trecap_complex_mul_q,
//           then applies the stage-specific add/subtract and explicit round/saturate operators.
//           It does not own frame buffering, packetization, DDR, HPS, Ethernet, or dashboard logic.

`default_nettype none

module trecap_fft_stage
  import trecap_core_pkg::*;
#(
    parameter int unsigned DATA_W          = T_FFT_W,
    parameter int unsigned TWIDDLE_W       = T_TWIDDLE_W,
    parameter int unsigned OUT_W           = DATA_W,
    parameter int unsigned FRAC_SHIFT      = T_FRAC_F,
    parameter bit          NORMALIZE_BY_2  = 1'b1,
    parameter bit          REGISTER_OUTPUT = 1'b0
) (
    input  logic                         clk,
    input  logic                         rst_n,
    input  logic                         clear_i,

    input  logic                         valid_i,
    output logic                         ready_o,
    input  logic signed [DATA_W-1:0]     a_re_i,
    input  logic signed [DATA_W-1:0]     a_im_i,
    input  logic signed [DATA_W-1:0]     b_re_i,
    input  logic signed [DATA_W-1:0]     b_im_i,
    input  logic signed [TWIDDLE_W-1:0]  tw_re_i,
    input  logic signed [TWIDDLE_W-1:0]  tw_im_i,

    output logic                         valid_o,
    input  logic                         ready_i,
    output logic signed [OUT_W-1:0]      y0_re_o,
    output logic signed [OUT_W-1:0]      y0_im_o,
    output logic signed [OUT_W-1:0]      y1_re_o,
    output logic signed [OUT_W-1:0]      y1_im_o,
    output logic                         sat_any_o,
    output logic                         input_accept_pulse_o,
    output logic                         output_accept_pulse_o
);

    localparam int unsigned MUL_W = DATA_W;
    localparam int unsigned SUM_W = ((DATA_W > MUL_W) ? DATA_W : MUL_W) + 2;
    localparam int unsigned SHIFT = NORMALIZE_BY_2 ? 1 : 0;

    logic                         mul_ready;
    logic                         mul_valid;
    logic signed [MUL_W-1:0]      t_re;
    logic signed [MUL_W-1:0]      t_im;
    logic                         mul_sat_re;
    logic                         mul_sat_im;
    logic                         mul_sat_any;
    logic                         mul_input_accept;
    logic                         mul_output_accept;

    logic signed [SUM_W-1:0]      a_re_ext;
    logic signed [SUM_W-1:0]      a_im_ext;
    logic signed [SUM_W-1:0]      t_re_ext;
    logic signed [SUM_W-1:0]      t_im_ext;
    logic signed [SUM_W-1:0]      sum_re;
    logic signed [SUM_W-1:0]      sum_im;
    logic signed [SUM_W-1:0]      diff_re;
    logic signed [SUM_W-1:0]      diff_im;

    logic signed [OUT_W-1:0]      y0_re_comb;
    logic signed [OUT_W-1:0]      y0_im_comb;
    logic signed [OUT_W-1:0]      y1_re_comb;
    logic signed [OUT_W-1:0]      y1_im_comb;
    logic                         y0_re_sat;
    logic                         y0_im_sat;
    logic                         y1_re_sat;
    logic                         y1_im_sat;
    logic                         y0_re_sat_hi;
    logic                         y0_re_sat_lo;
    logic                         y0_im_sat_hi;
    logic                         y0_im_sat_lo;
    logic                         y1_re_sat_hi;
    logic                         y1_re_sat_lo;
    logic                         y1_im_sat_hi;
    logic                         y1_im_sat_lo;
    logic                         sat_any_comb;

    trecap_complex_mul_q #(
        .A_W( DATA_W ),
        .B_W( TWIDDLE_W ),
        .OUT_W( MUL_W ),
        .FRAC_SHIFT( FRAC_SHIFT ),
        .REGISTER_OUTPUT( 1'b0 )
    ) u_twiddle_mul (
        .clk( clk ),
        .rst_n( rst_n ),
        .clear_i( clear_i ),
        .valid_i( valid_i ),
        .ready_o( mul_ready ),
        .ar_i( b_re_i ),
        .ai_i( b_im_i ),
        .br_i( tw_re_i ),
        .bi_i( tw_im_i ),
        .valid_o( mul_valid ),
        .ready_i( 1'b1 ),
        .pr_o( t_re ),
        .pi_o( t_im ),
        .sat_re_o( mul_sat_re ),
        .sat_im_o( mul_sat_im ),
        .sat_any_o( mul_sat_any ),
        .input_accept_pulse_o( mul_input_accept ),
        .output_accept_pulse_o( mul_output_accept )
    );

    always_comb begin
        a_re_ext = {{(SUM_W-DATA_W){a_re_i[DATA_W-1]}}, a_re_i};
        a_im_ext = {{(SUM_W-DATA_W){a_im_i[DATA_W-1]}}, a_im_i};
        t_re_ext = {{(SUM_W-MUL_W){t_re[MUL_W-1]}}, t_re};
        t_im_ext = {{(SUM_W-MUL_W){t_im[MUL_W-1]}}, t_im};

        sum_re  = a_re_ext + t_re_ext;
        sum_im  = a_im_ext + t_im_ext;
        diff_re = a_re_ext - t_re_ext;
        diff_im = a_im_ext - t_im_ext;
    end

    trecap_round_sat #(
        .IN_W( SUM_W ),
        .OUT_W( OUT_W ),
        .SHIFT( SHIFT )
    ) u_y0_re_round_sat (
        .value_i( sum_re ),
        .value_o( y0_re_comb ),
        .sat_hi_o( y0_re_sat_hi ),
        .sat_lo_o( y0_re_sat_lo ),
        .sat_any_o( y0_re_sat )
    );

    trecap_round_sat #(
        .IN_W( SUM_W ),
        .OUT_W( OUT_W ),
        .SHIFT( SHIFT )
    ) u_y0_im_round_sat (
        .value_i( sum_im ),
        .value_o( y0_im_comb ),
        .sat_hi_o( y0_im_sat_hi ),
        .sat_lo_o( y0_im_sat_lo ),
        .sat_any_o( y0_im_sat )
    );

    trecap_round_sat #(
        .IN_W( SUM_W ),
        .OUT_W( OUT_W ),
        .SHIFT( SHIFT )
    ) u_y1_re_round_sat (
        .value_i( diff_re ),
        .value_o( y1_re_comb ),
        .sat_hi_o( y1_re_sat_hi ),
        .sat_lo_o( y1_re_sat_lo ),
        .sat_any_o( y1_re_sat )
    );

    trecap_round_sat #(
        .IN_W( SUM_W ),
        .OUT_W( OUT_W ),
        .SHIFT( SHIFT )
    ) u_y1_im_round_sat (
        .value_i( diff_im ),
        .value_o( y1_im_comb ),
        .sat_hi_o( y1_im_sat_hi ),
        .sat_lo_o( y1_im_sat_lo ),
        .sat_any_o( y1_im_sat )
    );

    assign sat_any_comb = mul_sat_any | y0_re_sat | y0_im_sat | y1_re_sat | y1_im_sat;

    generate
        if (REGISTER_OUTPUT) begin : gen_registered_output
            logic                    valid_q;
            logic signed [OUT_W-1:0] y0_re_q;
            logic signed [OUT_W-1:0] y0_im_q;
            logic signed [OUT_W-1:0] y1_re_q;
            logic signed [OUT_W-1:0] y1_im_q;
            logic                    sat_any_q;
            logic                    can_accept;
            logic                    input_accept;
            logic                    output_accept;

            assign can_accept   = !valid_q || ready_i;
            assign input_accept = valid_i && can_accept;
            assign output_accept = valid_q && ready_i;

            assign ready_o = can_accept;
            assign valid_o = valid_q;
            assign y0_re_o = y0_re_q;
            assign y0_im_o = y0_im_q;
            assign y1_re_o = y1_re_q;
            assign y1_im_o = y1_im_q;
            assign sat_any_o = sat_any_q;
            assign input_accept_pulse_o = input_accept;
            assign output_accept_pulse_o = output_accept;

            always_ff @(posedge clk or negedge rst_n) begin
                if (!rst_n) begin
                    valid_q   <= 1'b0;
                    y0_re_q   <= '0;
                    y0_im_q   <= '0;
                    y1_re_q   <= '0;
                    y1_im_q   <= '0;
                    sat_any_q <= 1'b0;
                end else begin
                    if (clear_i) begin
                        valid_q   <= 1'b0;
                        y0_re_q   <= '0;
                        y0_im_q   <= '0;
                        y1_re_q   <= '0;
                        y1_im_q   <= '0;
                        sat_any_q <= 1'b0;
                    end else if (can_accept) begin
                        valid_q <= valid_i;
                        if (valid_i) begin
                            y0_re_q   <= y0_re_comb;
                            y0_im_q   <= y0_im_comb;
                            y1_re_q   <= y1_re_comb;
                            y1_im_q   <= y1_im_comb;
                            sat_any_q <= sat_any_comb;
                        end else begin
                            y0_re_q   <= '0;
                            y0_im_q   <= '0;
                            y1_re_q   <= '0;
                            y1_im_q   <= '0;
                            sat_any_q <= 1'b0;
                        end
                    end
                end
            end
        end else begin : gen_comb_output
            assign ready_o = ready_i;
            assign valid_o = valid_i;
            assign y0_re_o = y0_re_comb;
            assign y0_im_o = y0_im_comb;
            assign y1_re_o = y1_re_comb;
            assign y1_im_o = y1_im_comb;
            assign sat_any_o = sat_any_comb;
            assign input_accept_pulse_o = valid_i && ready_i;
            assign output_accept_pulse_o = valid_i && ready_i;

            logic unused_registered_inputs;
            always_comb begin
                unused_registered_inputs = mul_ready ^ mul_valid ^ mul_input_accept ^ mul_output_accept ^
                                           y0_re_sat_hi ^ y0_re_sat_lo ^ y0_im_sat_hi ^ y0_im_sat_lo ^
                                           y1_re_sat_hi ^ y1_re_sat_lo ^ y1_im_sat_hi ^ y1_im_sat_lo;
            end
        end
    endgenerate

`ifndef SYNTHESIS
    initial begin
        if ((DATA_W == 0) || (TWIDDLE_W == 0) || (OUT_W == 0)) begin
            $fatal(1, "trecap_fft_stage: DATA_W, TWIDDLE_W, and OUT_W must be nonzero");
        end
        if (FRAC_SHIFT == 0) begin
            $warning("trecap_fft_stage: FRAC_SHIFT is zero; verify this is intentional");
        end
    end
`endif

endmodule : trecap_fft_stage

`default_nettype wire
