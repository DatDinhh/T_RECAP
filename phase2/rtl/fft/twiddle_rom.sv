// SPDX-License-Identifier: MIT
// File class: [1] hand-written RTL.
// Layer: rtl/fft/
// Owner: T-RECAP Phase 2 implementation.
// Purpose: Forward/inverse FFT twiddle ROM wrapper backed by reference artifact .memh files.
// Contract: Loads twiddle coefficients generated from the reference-model artifact flow. It does
//           not compute twiddles at run time, does not write DDR, and does not interact with HPS,
//           Ethernet, telemetry packet layout, or the PC dashboard.

`default_nettype none

module trecap_twiddle_rom
  import trecap_core_pkg::*;
#(
    parameter int unsigned DEPTH                  = T_FFT_L,
    parameter int unsigned ADDR_W                 = (DEPTH <= 1) ? 1 : $clog2(DEPTH),
    parameter int unsigned TWIDDLE_W              = T_TWIDDLE_W,
    parameter string       FWD_RE_FILE            = "artifacts/coefficients/twiddle_re.memh",
    parameter string       FWD_IM_FILE            = "artifacts/coefficients/twiddle_im.memh",
    parameter string       INV_RE_FILE            = "artifacts/coefficients/twiddle_inv_re.memh",
    parameter string       INV_IM_FILE            = "artifacts/coefficients/twiddle_inv_im.memh",
    parameter bit          USE_INVERSE_FILES      = 1'b1,
    parameter bit          REGISTER_OUTPUT        = 1'b1
) (
    input  logic                              clk,
    input  logic                              rst_n,
    input  logic                              clear_i,

    input  logic                              valid_i,
    input  logic                              inverse_i,
    input  logic [ADDR_W-1:0]                 index_i,

    output logic                              valid_o,
    output logic                              inverse_o,
    output logic [ADDR_W-1:0]                 index_o,
    output logic signed [TWIDDLE_W-1:0]       tw_re_o,
    output logic signed [TWIDDLE_W-1:0]       tw_im_o,
    output logic                              index_oob_o
);

    localparam int unsigned DEPTH_SAFE = (DEPTH == 0) ? 1 : DEPTH;
    localparam logic [ADDR_W:0] DEPTH_LIMIT = DEPTH_SAFE;

    logic signed [TWIDDLE_W-1:0] fwd_re_mem [0:DEPTH_SAFE-1];
    logic signed [TWIDDLE_W-1:0] fwd_im_mem [0:DEPTH_SAFE-1];
    logic signed [TWIDDLE_W-1:0] inv_re_mem [0:DEPTH_SAFE-1];
    logic signed [TWIDDLE_W-1:0] inv_im_mem [0:DEPTH_SAFE-1];

    logic                        index_oob_comb;
    logic [ADDR_W:0]             index_ext;
    logic [ADDR_W-1:0]           safe_index;
    logic signed [TWIDDLE_W-1:0] fwd_re_comb;
    logic signed [TWIDDLE_W-1:0] fwd_im_comb;
    logic signed [TWIDDLE_W-1:0] inv_re_file_comb;
    logic signed [TWIDDLE_W-1:0] inv_im_file_comb;
    logic signed [TWIDDLE_W-1:0] inv_re_comb;
    logic signed [TWIDDLE_W-1:0] inv_im_comb;
    logic signed [TWIDDLE_W-1:0] tw_re_comb;
    logic signed [TWIDDLE_W-1:0] tw_im_comb;

    always_comb begin
        index_ext      = {1'b0, index_i};
        index_oob_comb = (index_ext >= DEPTH_LIMIT);
        safe_index     = index_oob_comb ? '0 : index_i;
    end

    assign fwd_re_comb = fwd_re_mem[safe_index];
    assign fwd_im_comb = fwd_im_mem[safe_index];
    assign inv_re_file_comb = inv_re_mem[safe_index];
    assign inv_im_file_comb = inv_im_mem[safe_index];

    assign inv_re_comb = USE_INVERSE_FILES ? inv_re_file_comb : fwd_re_comb;
    assign inv_im_comb = USE_INVERSE_FILES ? inv_im_file_comb : -fwd_im_comb;
    assign tw_re_comb = inverse_i ? inv_re_comb : fwd_re_comb;
    assign tw_im_comb = inverse_i ? inv_im_comb : fwd_im_comb;

    initial begin : init_twiddle_roms
        int unsigned idx;
        for (idx = 0; idx < DEPTH_SAFE; idx++) begin
            fwd_re_mem[idx] = '0;
            fwd_im_mem[idx] = '0;
            inv_re_mem[idx] = '0;
            inv_im_mem[idx] = '0;
        end

        if (FWD_RE_FILE != "") begin
            $readmemh(FWD_RE_FILE, fwd_re_mem);
        end
        if (FWD_IM_FILE != "") begin
            $readmemh(FWD_IM_FILE, fwd_im_mem);
        end
        if (INV_RE_FILE != "") begin
            $readmemh(INV_RE_FILE, inv_re_mem);
        end
        if (INV_IM_FILE != "") begin
            $readmemh(INV_IM_FILE, inv_im_mem);
        end
    end

    generate
        if (REGISTER_OUTPUT) begin : gen_registered_output
            logic                        valid_q;
            logic                        inverse_q;
            logic [ADDR_W-1:0]           index_q;
            logic signed [TWIDDLE_W-1:0] tw_re_q;
            logic signed [TWIDDLE_W-1:0] tw_im_q;
            logic                        index_oob_q;

            always_ff @(posedge clk or negedge rst_n) begin
                if (!rst_n) begin
                    valid_q     <= 1'b0;
                    inverse_q   <= 1'b0;
                    index_q     <= '0;
                    tw_re_q     <= '0;
                    tw_im_q     <= '0;
                    index_oob_q <= 1'b0;
                end else begin
                    if (clear_i) begin
                        valid_q     <= 1'b0;
                        inverse_q   <= 1'b0;
                        index_q     <= '0;
                        tw_re_q     <= '0;
                        tw_im_q     <= '0;
                        index_oob_q <= 1'b0;
                    end else begin
                        valid_q     <= valid_i;
                        inverse_q   <= inverse_i;
                        index_q     <= index_i;
                        tw_re_q     <= tw_re_comb;
                        tw_im_q     <= tw_im_comb;
                        index_oob_q <= index_oob_comb;
                    end
                end
            end

            assign valid_o = valid_q;
            assign inverse_o = inverse_q;
            assign index_o = index_q;
            assign tw_re_o = tw_re_q;
            assign tw_im_o = tw_im_q;
            assign index_oob_o = index_oob_q;
        end else begin : gen_comb_output
            assign valid_o = valid_i;
            assign inverse_o = inverse_i;
            assign index_o = index_i;
            assign tw_re_o = tw_re_comb;
            assign tw_im_o = tw_im_comb;
            assign index_oob_o = index_oob_comb;

            logic unused_seq_inputs;
            always_comb begin
                unused_seq_inputs = clk ^ rst_n ^ clear_i;
            end
        end
    endgenerate

`ifndef SYNTHESIS
    initial begin
        if (DEPTH == 0) begin
            $error("trecap_twiddle_rom: DEPTH must be nonzero");
        end
        if (TWIDDLE_W == 0) begin
            $error("trecap_twiddle_rom: TWIDDLE_W must be nonzero");
        end
    end
`endif

endmodule : trecap_twiddle_rom

`default_nettype wire
