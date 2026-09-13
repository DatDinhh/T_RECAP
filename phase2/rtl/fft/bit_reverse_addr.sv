// SPDX-License-Identifier: MIT
// File class: [1] hand-written RTL.
// Layer: rtl/fft/
// Owner: T-RECAP Phase 2 implementation.
// Purpose: Parameterized bit-reversal address helper for FFT/IFFT memory and reorder stages.
// Contract: Pure address permutation. It does not perform FFT arithmetic, does not touch
//           telemetry, DDR, HPS, Ethernet, or dashboard state.

`default_nettype none

module trecap_bit_reverse_addr
  import trecap_core_pkg::*;
#(
    parameter int unsigned ADDR_W          = T_FFT_P,
    parameter bit          REGISTER_OUTPUT = 1'b0
) (
    input  logic                clk,
    input  logic                rst_n,
    input  logic                clear_i,

    input  logic                valid_i,
    input  logic [ADDR_W-1:0]   addr_i,

    output logic                valid_o,
    output logic [ADDR_W-1:0]   addr_o
);

    function automatic logic [ADDR_W-1:0] reverse_bits(input logic [ADDR_W-1:0] value);
        logic [ADDR_W-1:0] reversed;
        for (int unsigned bit_idx = 0; bit_idx < ADDR_W; bit_idx++) begin
            reversed[bit_idx] = value[ADDR_W-1-bit_idx];
        end
        return reversed;
    endfunction : reverse_bits

    logic [ADDR_W-1:0] reversed_addr;
    logic              valid_q;
    logic [ADDR_W-1:0] addr_q;

    assign reversed_addr = reverse_bits(addr_i);

    generate
        if (REGISTER_OUTPUT) begin : gen_registered_output
            always_ff @(posedge clk or negedge rst_n) begin
                if (!rst_n) begin
                    valid_q <= 1'b0;
                    addr_q  <= '0;
                end else begin
                    if (clear_i) begin
                        valid_q <= 1'b0;
                        addr_q  <= '0;
                    end else begin
                        valid_q <= valid_i;
                        addr_q  <= reversed_addr;
                    end
                end
            end

            assign valid_o = valid_q;
            assign addr_o  = addr_q;
        end else begin : gen_comb_output
            assign valid_o = valid_i;
            assign addr_o  = reversed_addr;

            // Keep unused clock/reset inputs intentionally connected at the module boundary so
            // callers may switch REGISTER_OUTPUT without changing port maps.
            logic unused_seq_inputs;
            always_comb begin
                unused_seq_inputs = clk ^ rst_n ^ clear_i;
            end
        end
    endgenerate

`ifndef SYNTHESIS
    initial begin
        if (ADDR_W == 0) begin
            $error("trecap_bit_reverse_addr: ADDR_W must be at least 1");
        end
    end
`endif

endmodule : trecap_bit_reverse_addr

`default_nettype wire
