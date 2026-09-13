// SPDX-License-Identifier: MIT
// File class: [1] hand-written RTL interface.
// Layer: rtl/interfaces/
// Owner: T-RECAP Phase 2 implementation.
// Purpose: Avalon-MM-style write-master boundary for the FPGA DDR-ring writer.
// Contract: Keep bus timing explicit at the platform boundary. This interface does not own DDR
//           ring pointers, WRAP records, packet headers, HPS software, Ethernet, or core math.
// Generated dependencies: none. Widths are intentionally parameterized by the integration layer.

`default_nettype none

// T-RECAP Avalon-MM-style write interface.
//
// Timing contract:
//   - write && !waitrequest accepts one write beat.
//   - write-channel signals remain stable while write && waitrequest.
//   - byteenable is nonzero for asserted writes.
//   - Packet and ring-record atomicity live above this interface.
interface trecap_avmm_if #(
    parameter int unsigned ADDR_W       = 64,
    parameter int unsigned DATA_W       = 64,
    parameter int unsigned BYTEEN_W     = (DATA_W + 7) / 8,
    parameter int unsigned BURSTCOUNT_W = 1
) (
    input logic clk,
    input logic rst_n
);

    logic [ADDR_W-1:0]       address;
    logic                    write;
    logic [DATA_W-1:0]       writedata;
    logic [BYTEEN_W-1:0]     byteenable;
    logic [BURSTCOUNT_W-1:0] burstcount;
    logic                    waitrequest;
    logic                    writeresponsevalid;
    logic [1:0]              response;

    logic                    write_accepted;
    logic                    write_stalled;
    logic                    response_error;

    assign write_accepted = write && !waitrequest;
    assign write_stalled  = write &&  waitrequest;
    assign response_error = writeresponsevalid && (response != 2'b00);

    function automatic logic byteenable_nonzero(input logic [BYTEEN_W-1:0] be);
        return |be;
    endfunction

    function automatic logic byteenable_low_contiguous(input logic [BYTEEN_W-1:0] be);
        logic seen_zero;
        logic ok;
        seen_zero = 1'b0;
        ok = 1'b1;
        for (int unsigned i = 0; i < BYTEEN_W; i++) begin
            if (!be[i]) begin
                seen_zero = 1'b1;
            end else if (seen_zero) begin
                ok = 1'b0;
            end
        end
        return ok;
    endfunction

    modport master (
        input  clk,
        input  rst_n,
        output address,
        output write,
        output writedata,
        output byteenable,
        output burstcount,
        input  waitrequest,
        input  writeresponsevalid,
        input  response,
        input  write_accepted,
        input  write_stalled,
        input  response_error
    );

    modport slave (
        input  clk,
        input  rst_n,
        input  address,
        input  write,
        input  writedata,
        input  byteenable,
        input  burstcount,
        output waitrequest,
        output writeresponsevalid,
        output response,
        input  write_accepted,
        input  write_stalled,
        input  response_error
    );

    modport monitor (
        input clk,
        input rst_n,
        input address,
        input write,
        input writedata,
        input byteenable,
        input burstcount,
        input waitrequest,
        input writeresponsevalid,
        input response,
        input write_accepted,
        input write_stalled,
        input response_error
    );

`ifndef SYNTHESIS
    logic [ADDR_W-1:0]       address_hold_q;
    logic [DATA_W-1:0]       writedata_hold_q;
    logic [BYTEEN_W-1:0]     byteenable_hold_q;
    logic [BURSTCOUNT_W-1:0] burstcount_hold_q;
    logic                    stalled_q;

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            address_hold_q    <= '0;
            writedata_hold_q  <= '0;
            byteenable_hold_q <= '0;
            burstcount_hold_q <= '0;
            stalled_q         <= 1'b0;
        end else begin
            if (write && !byteenable_nonzero(byteenable)) begin
                $error("trecap_avmm_if: write asserted with zero byteenable");
            end
            if (write && !byteenable_low_contiguous(byteenable)) begin
                $error("trecap_avmm_if: byteenable is not low-contiguous");
            end
            if (write && (burstcount == '0)) begin
                $error("trecap_avmm_if: write asserted with zero burstcount");
            end
            if (stalled_q && write_stalled) begin
                if ((address != address_hold_q) ||
                    (writedata != writedata_hold_q) ||
                    (byteenable != byteenable_hold_q) ||
                    (burstcount != burstcount_hold_q)) begin
                    $error("trecap_avmm_if: write channel changed while waitrequest was asserted");
                end
            end
            if (write_stalled && !stalled_q) begin
                address_hold_q    <= address;
                writedata_hold_q  <= writedata;
                byteenable_hold_q <= byteenable;
                burstcount_hold_q <= burstcount;
            end
            stalled_q <= write_stalled;
        end
    end
`endif

endinterface : trecap_avmm_if

`default_nettype wire
