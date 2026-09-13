// SPDX-License-Identifier: MIT
// File class: [1] hand-written RTL.
// Layer: rtl/fft/
// Owner: T-RECAP Phase 2 implementation.
// Purpose: Iterative 256-point unscaled radix-2 IFFT engine for the Phase 2 synthesis path.
// Contract: Matches the reference-model IFFT scheduling order: bit-reversed complex spectrum
//           load, radix-2 DIT butterflies, inverse twiddles, and no per-stage divide-by-two.
//           This module is core math only; it does not know telemetry, DDR, HPS, Ethernet, or PC UI.

`default_nettype none

module trecap_ifft256
  import trecap_core_pkg::*;
#(
    parameter int unsigned L                  = T_FFT_L,
    parameter int unsigned P                  = T_FFT_P,
    parameter int unsigned IN_W               = T_CAN_W,
    parameter int unsigned DATA_W             = T_IFFT_W,
    parameter int unsigned TWIDDLE_W          = T_TWIDDLE_W,
    parameter string       TWIDDLE_RE_FILE    = "artifacts/coefficients/twiddle_re.memh",
    parameter string       TWIDDLE_IM_FILE    = "artifacts/coefficients/twiddle_im.memh",
    parameter string       TWIDDLE_INV_RE_FILE = "artifacts/coefficients/twiddle_inv_re.memh",
    parameter string       TWIDDLE_INV_IM_FILE = "artifacts/coefficients/twiddle_inv_im.memh"
) (
    input  logic                         clk,
    input  logic                         rst_n,
    input  logic                         clear_i,

    input  logic                         in_valid_i,
    output logic                         in_ready_o,
    input  logic signed [IN_W-1:0]       in_re_i,
    input  logic signed [IN_W-1:0]       in_im_i,
    input  logic [63:0]                  in_frame_idx_i,

    output logic                         out_valid_o,
    input  logic                         out_ready_i,
    output logic signed [DATA_W-1:0]     out_re_o,
    output logic signed [DATA_W-1:0]     out_im_o,
    output logic [P-1:0]                 out_sample_offset_o,
    output logic [63:0]                  out_frame_idx_o,
    output logic                         out_last_o,

    output logic                         busy_o,
    output logic                         load_active_o,
    output logic                         compute_active_o,
    output logic                         output_active_o,
    output logic                         frame_done_pulse_o,
    output logic                         saturation_sticky_o,
    output logic                         protocol_error_sticky_o,
    input  logic                         clear_sticky_i
);

    localparam int unsigned ADDR_W = P;
    localparam logic [ADDR_W-1:0] LAST_ADDR = L - 1;
    localparam logic [P:0]        LAST_STAGE = P;

    typedef enum logic [1:0] {
        S_IDLE    = 2'd0,
        S_LOAD    = 2'd1,
        S_COMPUTE = 2'd2,
        S_OUTPUT  = 2'd3
    } state_t;

    state_t                         state_q;
    logic [ADDR_W-1:0]              load_count_q;
    logic [ADDR_W-1:0]              output_count_q;
    logic [P:0]                     stage_q;
    logic [ADDR_W-1:0]              base_q;
    logic [ADDR_W-1:0]              j_q;
    logic [63:0]                    frame_idx_q;
    logic                           saturation_sticky_q;
    logic                           protocol_error_sticky_q;

    logic signed [DATA_W-1:0]       data_re_mem [0:L-1];
    logic signed [DATA_W-1:0]       data_im_mem [0:L-1];

    logic                           bitrev_valid;
    logic [ADDR_W-1:0]              bitrev_load_addr;

    logic [ADDR_W:0]                span_comb;
    logic [ADDR_W:0]                half_comb;
    logic [ADDR_W-1:0]              addr_lo_comb;
    logic [ADDR_W-1:0]              addr_hi_comb;
    logic [ADDR_W-1:0]              twiddle_index_comb;
    logic                           compute_last_j_comb;
    logic                           compute_last_base_comb;
    logic                           compute_last_stage_comb;
    int unsigned                    base_plus_span_comb;

    logic                           tw_valid;
    logic                           tw_inverse;
    logic [ADDR_W-1:0]              tw_index;
    logic signed [TWIDDLE_W-1:0]    tw_re;
    logic signed [TWIDDLE_W-1:0]    tw_im;
    logic                           tw_oob;

    logic                           stage_ready;
    logic                           stage_valid;
    logic signed [DATA_W-1:0]       stage_y0_re;
    logic signed [DATA_W-1:0]       stage_y0_im;
    logic signed [DATA_W-1:0]       stage_y1_re;
    logic signed [DATA_W-1:0]       stage_y1_im;
    logic                           stage_sat_any;
    logic                           stage_input_accept;
    logic                           stage_output_accept;

    logic signed [DATA_W-1:0]       input_re_ext;
    logic signed [DATA_W-1:0]       input_im_ext;
    logic                           input_accept;
    logic                           output_accept;

    trecap_bit_reverse_addr #(
        .ADDR_W( ADDR_W ),
        .REGISTER_OUTPUT( 1'b0 )
    ) u_load_bit_reverse (
        .clk( clk ),
        .rst_n( rst_n ),
        .clear_i( clear_i ),
        .valid_i( 1'b1 ),
        .addr_i( load_count_q ),
        .valid_o( bitrev_valid ),
        .addr_o( bitrev_load_addr )
    );

    trecap_twiddle_rom #(
        .DEPTH( L ),
        .ADDR_W( ADDR_W ),
        .TWIDDLE_W( TWIDDLE_W ),
        .FWD_RE_FILE( TWIDDLE_RE_FILE ),
        .FWD_IM_FILE( TWIDDLE_IM_FILE ),
        .INV_RE_FILE( TWIDDLE_INV_RE_FILE ),
        .INV_IM_FILE( TWIDDLE_INV_IM_FILE ),
        .USE_INVERSE_FILES( 1'b1 ),
        .REGISTER_OUTPUT( 1'b0 )
    ) u_twiddle_rom (
        .clk( clk ),
        .rst_n( rst_n ),
        .clear_i( clear_i ),
        .valid_i( state_q == S_COMPUTE ),
        .inverse_i( 1'b1 ),
        .index_i( twiddle_index_comb ),
        .valid_o( tw_valid ),
        .inverse_o( tw_inverse ),
        .index_o( tw_index ),
        .tw_re_o( tw_re ),
        .tw_im_o( tw_im ),
        .index_oob_o( tw_oob )
    );

    trecap_fft_stage #(
        .DATA_W( DATA_W ),
        .TWIDDLE_W( TWIDDLE_W ),
        .OUT_W( DATA_W ),
        .FRAC_SHIFT( T_FRAC_F ),
        .NORMALIZE_BY_2( 1'b0 ),
        .REGISTER_OUTPUT( 1'b0 )
    ) u_butterfly_stage (
        .clk( clk ),
        .rst_n( rst_n ),
        .clear_i( clear_i ),
        .valid_i( state_q == S_COMPUTE ),
        .ready_o( stage_ready ),
        .a_re_i( data_re_mem[addr_lo_comb] ),
        .a_im_i( data_im_mem[addr_lo_comb] ),
        .b_re_i( data_re_mem[addr_hi_comb] ),
        .b_im_i( data_im_mem[addr_hi_comb] ),
        .tw_re_i( tw_re ),
        .tw_im_i( tw_im ),
        .valid_o( stage_valid ),
        .ready_i( 1'b1 ),
        .y0_re_o( stage_y0_re ),
        .y0_im_o( stage_y0_im ),
        .y1_re_o( stage_y1_re ),
        .y1_im_o( stage_y1_im ),
        .sat_any_o( stage_sat_any ),
        .input_accept_pulse_o( stage_input_accept ),
        .output_accept_pulse_o( stage_output_accept )
    );

    always_comb begin
        input_re_ext = {{(DATA_W-IN_W){in_re_i[IN_W-1]}}, in_re_i};
        input_im_ext = {{(DATA_W-IN_W){in_im_i[IN_W-1]}}, in_im_i};
        input_accept = in_valid_i && in_ready_o;
        output_accept = out_valid_o && out_ready_i;

        span_comb = (stage_q == 0) ? {{ADDR_W{1'b0}}, 1'b1} : ({{ADDR_W{1'b0}}, 1'b1} << stage_q);
        half_comb = span_comb >> 1;
        addr_lo_comb = base_q + j_q;
        addr_hi_comb = base_q + j_q + half_comb[ADDR_W-1:0];
        twiddle_index_comb = j_q << (P - stage_q[ADDR_W-1:0]);

        compute_last_j_comb = (j_q == (half_comb[ADDR_W-1:0] - {{(ADDR_W-1){1'b0}}, 1'b1}));
        base_plus_span_comb = int'(base_q) + int'(span_comb);
        compute_last_base_comb = (base_plus_span_comb >= L);
        compute_last_stage_comb = (stage_q == LAST_STAGE);
    end

    assign in_ready_o = (state_q == S_IDLE) || (state_q == S_LOAD);
    assign out_valid_o = (state_q == S_OUTPUT);
    assign out_re_o = data_re_mem[output_count_q];
    assign out_im_o = data_im_mem[output_count_q];
    assign out_sample_offset_o = output_count_q;
    assign out_frame_idx_o = frame_idx_q;
    assign out_last_o = (state_q == S_OUTPUT) && (output_count_q == LAST_ADDR);
    assign busy_o = (state_q != S_IDLE);
    assign load_active_o = (state_q == S_LOAD);
    assign compute_active_o = (state_q == S_COMPUTE);
    assign output_active_o = (state_q == S_OUTPUT);
    assign saturation_sticky_o = saturation_sticky_q;
    assign protocol_error_sticky_o = protocol_error_sticky_q;

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state_q                 <= S_IDLE;
            load_count_q            <= '0;
            output_count_q          <= '0;
            stage_q                 <= '0;
            base_q                  <= '0;
            j_q                     <= '0;
            frame_idx_q             <= '0;
            saturation_sticky_q     <= 1'b0;
            protocol_error_sticky_q <= 1'b0;
            frame_done_pulse_o      <= 1'b0;
        end else begin
            frame_done_pulse_o <= 1'b0;

            if (clear_i) begin
                state_q            <= S_IDLE;
                load_count_q       <= '0;
                output_count_q     <= '0;
                stage_q            <= '0;
                base_q             <= '0;
                j_q                <= '0;
                frame_idx_q        <= '0;
            end else begin
                if (clear_sticky_i) begin
                    saturation_sticky_q     <= 1'b0;
                    protocol_error_sticky_q <= 1'b0;
                end

                unique case (state_q)
                    S_IDLE: begin
                        if (input_accept) begin
                            frame_idx_q <= in_frame_idx_i;
                            data_re_mem[bitrev_load_addr] <= input_re_ext;
                            data_im_mem[bitrev_load_addr] <= input_im_ext;
                            load_count_q <= {{(ADDR_W-1){1'b0}}, 1'b1};
                            state_q <= (L == 1) ? S_OUTPUT : S_LOAD;
                        end
                    end

                    S_LOAD: begin
                        if (input_accept) begin
                            data_re_mem[bitrev_load_addr] <= input_re_ext;
                            data_im_mem[bitrev_load_addr] <= input_im_ext;
                            if (load_count_q == LAST_ADDR) begin
                                load_count_q <= '0;
                                stage_q <= {{P{1'b0}}, 1'b1};
                                base_q <= '0;
                                j_q <= '0;
                                state_q <= S_COMPUTE;
                            end else begin
                                load_count_q <= load_count_q + {{(ADDR_W-1){1'b0}}, 1'b1};
                            end
                        end
                    end

                    S_COMPUTE: begin
                        data_re_mem[addr_lo_comb] <= stage_y0_re;
                        data_im_mem[addr_lo_comb] <= stage_y0_im;
                        data_re_mem[addr_hi_comb] <= stage_y1_re;
                        data_im_mem[addr_hi_comb] <= stage_y1_im;
                        saturation_sticky_q <= saturation_sticky_q | stage_sat_any;
                        protocol_error_sticky_q <= protocol_error_sticky_q | tw_oob | !tw_valid | !stage_valid;

                        if (compute_last_j_comb) begin
                            j_q <= '0;
                            if (compute_last_base_comb) begin
                                base_q <= '0;
                                if (compute_last_stage_comb) begin
                                    stage_q <= '0;
                                    output_count_q <= '0;
                                    state_q <= S_OUTPUT;
                                end else begin
                                    stage_q <= stage_q + {{P{1'b0}}, 1'b1};
                                end
                            end else begin
                                base_q <= base_q + span_comb[ADDR_W-1:0];
                            end
                        end else begin
                            j_q <= j_q + {{(ADDR_W-1){1'b0}}, 1'b1};
                        end
                    end

                    S_OUTPUT: begin
                        if (output_accept) begin
                            if (out_last_o) begin
                                output_count_q <= '0;
                                frame_done_pulse_o <= 1'b1;
                                state_q <= S_IDLE;
                            end else begin
                                output_count_q <= output_count_q + {{(ADDR_W-1){1'b0}}, 1'b1};
                            end
                        end
                    end

                    default: begin
                        state_q <= S_IDLE;
                        protocol_error_sticky_q <= 1'b1;
                    end
                endcase
            end
        end
    end

    logic unused_stage_handshake;
    always_comb begin
        unused_stage_handshake = bitrev_valid ^ tw_inverse ^ ^tw_index ^ stage_ready ^
                                 stage_input_accept ^ stage_output_accept;
    end

`ifndef SYNTHESIS
    initial begin
        if (L != 256) begin
            $fatal(1, "trecap_ifft256: this implementation expects L=256, got %0d", L);
        end
        if (P != 8) begin
            $fatal(1, "trecap_ifft256: this implementation expects P=8, got %0d", P);
        end
        if (DATA_W < IN_W) begin
            $fatal(1, "trecap_ifft256: DATA_W must be >= IN_W");
        end
    end
`endif

endmodule : trecap_ifft256

`default_nettype wire
