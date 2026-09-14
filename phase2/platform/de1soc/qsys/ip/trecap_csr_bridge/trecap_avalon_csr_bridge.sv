// SPDX-License-Identifier: MIT
// Fixed T-RECAP CSR boundary for Quartus Platform Designer.
// One 21-bit byte-addressed, 32-bit, single-beat Avalon transaction at a time.
// Commands and both response-valid roles pass through without pipeline state.
// The downstream CSR adapter owns serialization, reset, and completion status.
`default_nettype none

module trecap_avalon_csr_bridge (
    input  wire        clk,
    input  wire        reset,
    input  wire [20:0] s0_address,
    input  wire        s0_burstcount,
    input  wire [3:0]  s0_byteenable,
    input  wire        s0_read,
    input  wire        s0_write,
    input  wire [31:0] s0_writedata,
    output wire        s0_waitrequest,
    output wire [31:0] s0_readdata,
    output wire        s0_readdatavalid,
    output wire        s0_writeresponsevalid,
    output wire [1:0]  s0_response,
    output wire [20:0] m0_address,
    output wire        m0_burstcount,
    output wire [3:0]  m0_byteenable,
    output wire        m0_read,
    output wire        m0_write,
    output wire [31:0] m0_writedata,
    input  wire        m0_waitrequest,
    input  wire [31:0] m0_readdata,
    input  wire        m0_readdatavalid,
    input  wire        m0_writeresponsevalid,
    input  wire [1:0]  m0_response
);
    assign m0_address = s0_address;
    assign m0_burstcount = s0_burstcount;
    assign m0_byteenable = s0_byteenable;
    assign m0_read = s0_read;
    assign m0_write = s0_write;
    assign m0_writedata = s0_writedata;
    assign s0_waitrequest = m0_waitrequest;
    assign s0_readdata = m0_readdata;
    assign s0_readdatavalid = m0_readdatavalid;
    assign s0_writeresponsevalid = m0_writeresponsevalid;
    assign s0_response = m0_response;

    // These ports associate both Avalon interfaces with the fabric domain.
    // There is no local state to clock or reset; the CSR adapter handles reset.
    wire unused_clock_reset = clk ^ reset;
endmodule

`default_nettype wire
