// SPDX-License-Identifier: MIT
// File class: [1] hand-written RTL interface.
// Layer: rtl/interfaces/
// Owner: T-RECAP Phase 2 implementation.
// Purpose: HPS-to-FPGA 32-bit CSR request/response abstraction.
// Contract: Byte-offset CSR access, 32-bit little-endian data, explicit request acceptance and
//           read response. Multiword coherency is handled by CSR-bank snapshot/commit registers,
//           not by issuing torn live reads or writes.
// Generated dependencies: trecap_csr_pkg.

`default_nettype none

// T-RECAP CSR interface. addr is a byte offset inside the CSR window, not an HPS virtual address.
interface trecap_csr_if
#(
    parameter int unsigned ADDR_W = 12,
    parameter int unsigned DATA_W = 32
) (
    input logic clk,
    input logic rst_n
);
  import trecap_csr_pkg::*;


    localparam int unsigned DATA_BYTES       = DATA_W / 8;
    localparam int unsigned CSR_WINDOW_BYTES = TCSR_PACKET_FIFO_DROP_COUNT_OFFSET + 4;

    logic              valid;
    logic              write;
    logic [ADDR_W-1:0] addr;
    logic [DATA_W-1:0] wdata;
    logic              ready;
    logic              rvalid;
    logic [DATA_W-1:0] rdata;
    logic              error;

    logic              accepted;
    logic              read_accepted;
    logic              write_accepted;
    logic              stalled;

    assign accepted       = valid && ready;
    assign read_accepted  = accepted && !write;
    assign write_accepted = accepted &&  write;
    assign stalled        = valid && !ready;

    function automatic logic addr_word_aligned(input logic [ADDR_W-1:0] a);
        return (a[1:0] == 2'b00);
    endfunction

    function automatic logic addr_in_csr_window(input logic [ADDR_W-1:0] a);
        return (int'(a) < CSR_WINDOW_BYTES);
    endfunction

    function automatic logic request_is_read();
        return valid && !write;
    endfunction

    function automatic logic request_is_write();
        return valid && write;
    endfunction

    modport master (
        input  clk,
        input  rst_n,
        output valid,
        output write,
        output addr,
        output wdata,
        input  ready,
        input  rvalid,
        input  rdata,
        input  error,
        input  accepted,
        input  read_accepted,
        input  write_accepted,
        input  stalled
    );

    modport slave (
        input  clk,
        input  rst_n,
        input  valid,
        input  write,
        input  addr,
        input  wdata,
        output ready,
        output rvalid,
        output rdata,
        output error,
        input  accepted,
        input  read_accepted,
        input  write_accepted,
        input  stalled
    );

    modport monitor (
        input clk,
        input rst_n,
        input valid,
        input write,
        input addr,
        input wdata,
        input ready,
        input rvalid,
        input rdata,
        input error,
        input accepted,
        input read_accepted,
        input write_accepted,
        input stalled
    );

`ifndef SYNTHESIS
    logic              stalled_q;
    logic              write_hold_q;
    logic [ADDR_W-1:0] addr_hold_q;
    logic [DATA_W-1:0] wdata_hold_q;

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            stalled_q    <= 1'b0;
            write_hold_q <= 1'b0;
            addr_hold_q  <= '0;
            wdata_hold_q <= '0;
        end else begin
            if (valid && !addr_word_aligned(addr)) begin
                $error("trecap_csr_if: CSR request address is not 32-bit aligned");
            end
            if (valid && !addr_in_csr_window(addr)) begin
                $warning("trecap_csr_if: CSR request address is outside generated CSR window");
            end
            if (stalled_q && stalled) begin
                if ((write != write_hold_q) || (addr != addr_hold_q) || (wdata != wdata_hold_q)) begin
                    $error("trecap_csr_if: request changed while valid was held waiting for ready");
                end
            end
            if (stalled && !stalled_q) begin
                write_hold_q <= write;
                addr_hold_q  <= addr;
                wdata_hold_q <= wdata;
            end
            stalled_q <= stalled;
        end
    end
`endif

endinterface : trecap_csr_if

`default_nettype wire
