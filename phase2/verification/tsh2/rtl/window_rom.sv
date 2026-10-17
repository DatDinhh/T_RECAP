// SPDX-License-Identifier: MIT
// File class: [1] hand-written RTL.
// Layer: rtl/core/
// Owner: T-RECAP Phase 2 implementation.
// Purpose: Unsigned analysis/synthesis window ROM wrapper backed by the frozen window_qw.memh artifact.
// Contract: Loads the reference-model coefficient artifact directly. This module shall not compute
//           sine, cosine, Hann, square-root Hann, or any other coefficient internally.

`default_nettype none

module window_rom
#(
    parameter int unsigned DEPTH           = trecap_core_pkg::T_FFT_L,
    parameter int unsigned ADDR_W          = (DEPTH <= 1) ? 1 : $clog2(DEPTH),
    parameter int unsigned DATA_W          = trecap_core_pkg::T_QW_W,
    parameter              INIT_FILE       = "artifacts/coefficients/window_qw.memh",
    parameter bit          REGISTER_OUTPUT = 1'b0
) (
    input  logic                    clk,
    input  logic                    rst_n,
    input  logic                    clear_i,

    input  logic                    valid_i,
    input  logic [ADDR_W-1:0]       addr_i,

    output logic                    valid_o,
    output logic [ADDR_W-1:0]       addr_o,
    output logic [DATA_W-1:0]       coeff_o,
    output logic                    addr_oob_o
);
  import trecap_core_pkg::*;


    localparam int unsigned DEPTH_SAFE = (DEPTH == 0) ? 1 : DEPTH;
    localparam logic [ADDR_W:0] DEPTH_LIMIT = DEPTH_SAFE;

    logic [DATA_W-1:0] coeff_mem [0:DEPTH_SAFE-1];

    logic              addr_oob_comb;
    logic [ADDR_W:0]   addr_ext;
    logic [ADDR_W-1:0] safe_addr;
    logic [DATA_W-1:0] coeff_comb;

    always_comb begin
        addr_ext      = {1'b0, addr_i};
        addr_oob_comb = (addr_ext >= DEPTH_LIMIT);
        safe_addr     = addr_oob_comb ? '0 : addr_i;
    end

    assign coeff_comb = coeff_mem[safe_addr];

    initial begin : init_window_rom
        int unsigned idx;

        for (idx = 0; idx < DEPTH_SAFE; idx++) begin
            coeff_mem[idx] = '0;
        end

        if (INIT_FILE != "") begin
            $readmemh(INIT_FILE, coeff_mem);
        end
    end

    generate
        if (REGISTER_OUTPUT) begin : gen_registered_output
            logic              valid_q;
            logic [ADDR_W-1:0] addr_q;
            logic [DATA_W-1:0] coeff_q;
            logic              addr_oob_q;

            always_ff @(posedge clk or negedge rst_n) begin
                if (!rst_n) begin
                    valid_q    <= 1'b0;
                    addr_q     <= '0;
                    coeff_q    <= '0;
                    addr_oob_q <= 1'b0;
                end else begin
                    if (clear_i) begin
                        valid_q    <= 1'b0;
                        addr_q     <= '0;
                        coeff_q    <= '0;
                        addr_oob_q <= 1'b0;
                    end else begin
                        valid_q    <= valid_i;
                        addr_q     <= addr_i;
                        coeff_q    <= coeff_comb;
                        addr_oob_q <= addr_oob_comb;
                    end
                end
            end

            assign valid_o    = valid_q;
            assign addr_o     = addr_q;
            assign coeff_o    = coeff_q;
            assign addr_oob_o = addr_oob_q;
        end else begin : gen_comb_output
            assign valid_o    = valid_i;
            assign addr_o     = addr_i;
            assign coeff_o    = coeff_comb;
            assign addr_oob_o = addr_oob_comb;

            logic unused_seq_inputs;
            always_comb begin
                unused_seq_inputs = clk ^ rst_n ^ clear_i;
            end
        end
    endgenerate

`ifndef SYNTHESIS
    initial begin
        if (DEPTH == 0) begin
            $fatal(1, "window_rom: DEPTH must be nonzero");
        end
        if (DATA_W == 0) begin
            $fatal(1, "window_rom: DATA_W must be nonzero");
        end
        if (DATA_W != T_QW_W) begin
            $fatal(1, "window_rom: DATA_W must match generated T_QW_W");
        end
    end
`endif

endmodule : window_rom

`default_nettype wire
