// SPDX-License-Identifier: MIT
// File class: [1] hand-written RTL.
// Layer: rtl/fft/
// Owner: T-RECAP Phase 2 implementation.
// Purpose: Iterative 256-point unscaled radix-2 IFFT engine for the Phase 2 synthesis path.
// Contract: Matches the reference-model IFFT scheduling order: bit-reversed complex spectrum
//           load, radix-2 DIT butterflies, inverse twiddles, and no per-stage divide-by-two.
//           Synchronous dual-port work RAM and seven-clock butterfly transactions.
//           This module is core math only; it does not know telemetry, DDR, HPS, Ethernet, or PC UI.

`default_nettype none

module trecap_ifft256
#(
    parameter int unsigned L                  = trecap_core_pkg::T_FFT_L,
    parameter int unsigned P                  = trecap_core_pkg::T_FFT_P,
    parameter int unsigned IN_W               = trecap_core_pkg::T_CAN_W,
    parameter int unsigned DATA_W             = trecap_core_pkg::T_IFFT_W,
    parameter int unsigned TWIDDLE_W          = trecap_core_pkg::T_TWIDDLE_W,
    parameter              TWIDDLE_RE_FILE    = "artifacts/coefficients/twiddle_re.memh",
    parameter              TWIDDLE_IM_FILE    = "artifacts/coefficients/twiddle_im.memh",
    parameter              TWIDDLE_INV_RE_FILE = "artifacts/coefficients/twiddle_inv_re.memh",
    parameter              TWIDDLE_INV_IM_FILE = "artifacts/coefficients/twiddle_inv_im.memh"
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
  import trecap_core_pkg::*;


    localparam int unsigned ADDR_W = P;
    localparam int unsigned COMPLEX_W = 2 * DATA_W;
    localparam logic [ADDR_W-1:0] LAST_ADDR = ADDR_W'(L - 1);
    localparam logic [P:0] LAST_STAGE = (P+1)'(P);
    typedef enum logic [2:0] {
        S_IDLE, S_LOAD, S_READ, S_START, S_WAIT, S_OUT_READ, S_OUT_SEND
    } state_t;
    state_t state_q;
    logic [ADDR_W-1:0] load_count_q, output_count_q, base_q, j_q;
    logic [P:0] stage_q;
    logic [63:0] frame_idx_q;
    logic saturation_sticky_q, protocol_error_sticky_q;
    logic input_accept, output_accept;
    logic [ADDR_W-1:0] bitrev_load_addr;
    logic bitrev_valid;
    logic [ADDR_W:0] span_comb, half_comb;
    logic [ADDR_W-1:0] addr_lo_comb, addr_hi_comb, twiddle_index_comb;
    logic compute_last_j_comb, compute_last_base_comb, compute_last_stage_comb;
    logic [ADDR_W:0] base_plus_span_comb;

    // One packed complex true-dual-port M10K memory. Read data registers and
    // memory contents are deliberately not reset. Every address is loaded
    // before the first compute read. Port A serves load/output and operand a;
    // port B serves operand b. The FSM never reads and writes concurrently.
    // Reads occur only in S_READ/S_OUT_READ; writes occur only in
    // S_IDLE/S_LOAD (input) or S_WAIT (butterfly). Reset/clear gates all
    // enables, so neither port can read while either port writes. The two
    // butterfly write addresses differ by 2**(stage_q-1), for stages 1..P.
    // S_OUT_SEND holds the read register through output backpressure.
    // Quartus may choose any read-during-write result: no such result can
    // be observed by this schedule. Keep this waiver local to this RAM.
    (* ramstyle = "M10K, no_rw_check" *) logic [COMPLEX_W-1:0] work_mem [0:L-1];
    logic a_read_en, b_read_en, a_write_en, b_write_en;
    logic [ADDR_W-1:0] a_addr, b_addr;
    logic [COMPLEX_W-1:0] a_wdata, b_wdata, a_rdata_q, b_rdata_q;
    logic signed [DATA_W-1:0] input_re_ext, input_im_ext;
    logic stage_ready, stage_valid, stage_sat;
    logic signed [DATA_W-1:0] y0_re, y0_im, y1_re, y1_im;
    logic tw_valid, tw_inverse, tw_oob;
    logic [ADDR_W-1:0] tw_index;
    logic signed [TWIDDLE_W-1:0] tw_re, tw_im;
    logic butterfly_write;

    assign input_re_ext = {{(DATA_W-IN_W){in_re_i[IN_W-1]}}, in_re_i};
    assign input_im_ext = {{(DATA_W-IN_W){in_im_i[IN_W-1]}}, in_im_i};
    assign in_ready_o = rst_n && !clear_i && ((state_q == S_IDLE) || (state_q == S_LOAD));
    assign input_accept = in_valid_i && in_ready_o;
    assign out_valid_o = rst_n && !clear_i && (state_q == S_OUT_SEND);
    assign output_accept = out_valid_o && out_ready_i;
    assign out_re_o = $signed(a_rdata_q[COMPLEX_W-1:DATA_W]);
    assign out_im_o = $signed(a_rdata_q[DATA_W-1:0]);
    assign out_sample_offset_o = output_count_q;
    assign out_frame_idx_o = frame_idx_q;
    assign out_last_o = out_valid_o && (output_count_q == LAST_ADDR);
    assign busy_o = (state_q != S_IDLE);
    assign load_active_o = (state_q == S_LOAD);
    assign compute_active_o = (state_q == S_READ) || (state_q == S_START) || (state_q == S_WAIT);
    assign output_active_o = (state_q == S_OUT_READ) || (state_q == S_OUT_SEND);
    assign saturation_sticky_o = saturation_sticky_q;
    assign protocol_error_sticky_o = protocol_error_sticky_q;
    assign butterfly_write = rst_n && !clear_i && (state_q == S_WAIT) && stage_valid;

    trecap_bit_reverse_addr #(.ADDR_W(ADDR_W), .REGISTER_OUTPUT(1'b0)) u_load_bit_reverse (
        .clk(clk), .rst_n(rst_n), .clear_i(clear_i), .valid_i(input_accept),
        .addr_i(load_count_q), .valid_o(bitrev_valid), .addr_o(bitrev_load_addr)
    );

    always_comb begin
        span_comb = (stage_q == 0) ? (ADDR_W+1)'(1) : ((ADDR_W+1)'(1) << stage_q);
        half_comb = span_comb >> 1;
        addr_lo_comb = base_q + j_q;
        addr_hi_comb = base_q + j_q + half_comb[ADDR_W-1:0];
        twiddle_index_comb = (stage_q == 0) ? '0 : j_q << (P - int'(stage_q));
        compute_last_j_comb = (j_q == half_comb[ADDR_W-1:0] - ADDR_W'(1));
        base_plus_span_comb = {1'b0, base_q} + span_comb;
        compute_last_base_comb = (base_plus_span_comb >= (ADDR_W+1)'(L));
        compute_last_stage_comb = (stage_q == LAST_STAGE);

        a_read_en = rst_n && !clear_i && ((state_q == S_READ) || (state_q == S_OUT_READ));
        b_read_en = rst_n && !clear_i && (state_q == S_READ);
        a_write_en = input_accept || butterfly_write;
        b_write_en = butterfly_write;
        a_addr = input_accept ? bitrev_load_addr :
                 ((state_q == S_OUT_READ) || (state_q == S_OUT_SEND)) ? output_count_q : addr_lo_comb;
        b_addr = addr_hi_comb;
        a_wdata = input_accept ? {input_re_ext, input_im_ext} : {y0_re, y0_im};
        b_wdata = {y1_re, y1_im};
    end

    // Standard symmetric synchronous RAM port template. Two processes are
    // intentional: each process owns one physical port, with no cross-port bypass.
    always @(posedge clk) begin
        if (a_write_en) work_mem[a_addr] <= a_wdata;
        if (a_read_en) a_rdata_q <= work_mem[a_addr];
    end
    always @(posedge clk) begin
        if (b_write_en) work_mem[b_addr] <= b_wdata;
        if (b_read_en) b_rdata_q <= work_mem[b_addr];
    end

    trecap_twiddle_rom #(
        .DEPTH(L), .ADDR_W(ADDR_W), .TWIDDLE_W(TWIDDLE_W),
        .FWD_RE_FILE(TWIDDLE_RE_FILE), .FWD_IM_FILE(TWIDDLE_IM_FILE),
        .INV_RE_FILE(TWIDDLE_INV_RE_FILE), .INV_IM_FILE(TWIDDLE_INV_IM_FILE),
        .USE_INVERSE_FILES(1'b1), .REGISTER_OUTPUT(1'b1),
        .FIXED_DIRECTION(1'b1), .INVERSE_DIRECTION(1'b1)
    ) u_twiddle_rom (
        .clk(clk), .rst_n(rst_n), .clear_i(clear_i),
        .valid_i(rst_n && !clear_i && (state_q == S_READ)),
        .inverse_i(1'b1), .index_i(twiddle_index_comb),
        .valid_o(tw_valid), .inverse_o(tw_inverse), .index_o(tw_index),
        .tw_re_o(tw_re), .tw_im_o(tw_im), .index_oob_o(tw_oob)
    );

    trecap_fft_stage #(
        .DATA_W(DATA_W), .TWIDDLE_W(TWIDDLE_W), .OUT_W(DATA_W),
        .FRAC_SHIFT(T_FRAC_F), .NORMALIZE_BY_2(1'b0), .REGISTER_OUTPUT(1'b1)
    ) u_butterfly_stage (
        .clk(clk), .rst_n(rst_n), .clear_i(clear_i),
        .valid_i(rst_n && !clear_i && (state_q == S_START)), .ready_o(stage_ready),
        .a_re_i($signed(a_rdata_q[COMPLEX_W-1:DATA_W])),
        .a_im_i($signed(a_rdata_q[DATA_W-1:0])),
        .b_re_i($signed(b_rdata_q[COMPLEX_W-1:DATA_W])),
        .b_im_i($signed(b_rdata_q[DATA_W-1:0])),
        .tw_re_i(tw_re), .tw_im_i(tw_im),
        .valid_o(stage_valid), .ready_i(state_q == S_WAIT),
        .y0_re_o(y0_re), .y0_im_o(y0_im), .y1_re_o(y1_re), .y1_im_o(y1_im),
        .sat_any_o(stage_sat), .input_accept_pulse_o(), .output_accept_pulse_o()
    );

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state_q <= S_IDLE;
            load_count_q <= '0;
            output_count_q <= '0;
            stage_q <= '0;
            base_q <= '0;
            j_q <= '0;
            frame_idx_q <= '0;
            saturation_sticky_q <= 1'b0;
            protocol_error_sticky_q <= 1'b0;
            frame_done_pulse_o <= 1'b0;
        end else begin
            frame_done_pulse_o <= 1'b0;
            if (clear_sticky_i) begin
                saturation_sticky_q <= 1'b0;
                protocol_error_sticky_q <= 1'b0;
            end
            if (clear_i) begin
                state_q <= S_IDLE;
                load_count_q <= '0;
                output_count_q <= '0;
                stage_q <= '0;
                base_q <= '0;
                j_q <= '0;
                frame_idx_q <= '0;
            end else begin
                case (state_q)
                    S_IDLE: if (input_accept) begin
                        frame_idx_q <= in_frame_idx_i;
                        load_count_q <= ADDR_W'(1);
                        state_q <= S_LOAD;
                    end
                    S_LOAD: if (input_accept) begin
                        if (in_frame_idx_i != frame_idx_q) protocol_error_sticky_q <= 1'b1;
                        if (load_count_q == LAST_ADDR) begin
                            load_count_q <= '0;
                            stage_q <= (P+1)'(1);
                            base_q <= '0;
                            j_q <= '0;
                            state_q <= S_READ;
                        end else load_count_q <= load_count_q + ADDR_W'(1);
                    end
                    S_READ: state_q <= S_START;
                    S_START: if (stage_ready) begin
                        if (!tw_valid || tw_oob || (tw_index != twiddle_index_comb) ||
                            (tw_inverse != 1'b1)) protocol_error_sticky_q <= 1'b1;
                        state_q <= S_WAIT;
                    end
                    S_WAIT: if (butterfly_write) begin
                        if (stage_sat) saturation_sticky_q <= 1'b1;
                        if (compute_last_j_comb) begin
                            j_q <= '0;
                            if (compute_last_base_comb) begin
                                base_q <= '0;
                                if (compute_last_stage_comb) begin
                                    stage_q <= '0;
                                    output_count_q <= '0;
                                    state_q <= S_OUT_READ;
                                end else begin
                                    stage_q <= stage_q + (P+1)'(1);
                                    state_q <= S_READ;
                                end
                            end else begin
                                base_q <= base_q + span_comb[ADDR_W-1:0];
                                state_q <= S_READ;
                            end
                        end else begin
                            j_q <= j_q + ADDR_W'(1);
                            state_q <= S_READ;
                        end
                    end
                    S_OUT_READ: state_q <= S_OUT_SEND;
                    S_OUT_SEND: if (output_accept) begin
                        if (output_count_q == LAST_ADDR) begin
                            output_count_q <= '0;
                            frame_done_pulse_o <= 1'b1;
                            state_q <= S_IDLE;
                        end else begin
                            output_count_q <= output_count_q + ADDR_W'(1);
                            state_q <= S_OUT_READ;
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
