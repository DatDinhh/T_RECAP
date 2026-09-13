// SPDX-License-Identifier: MIT
// File class: [1] hand-written RTL.
// Layer: rtl/common/
// Owner: T-RECAP Phase 2 implementation.
// Purpose: Portable same-clock simple dual-port RAM wrapper.
// Contract: One write port, one synchronous read port, explicit read-during-write policy.
// Generated dependencies: none; this reusable primitive is intentionally package-independent.

`default_nettype none

// Same-clock simple dual-port RAM.
//
// Port model:
//   - Write port: wr_en_i, wr_addr_i, wr_data_i.
//   - Read port:  rd_en_i, rd_addr_i, rd_data_o, rd_valid_o.
//
// The read port is synchronous. rd_valid_o is the delayed acceptance marker for rd_en_i when the
// requested address is in range. When rd_en_i is low, rd_data_o holds its previous value unless
// CLEAR_RD_DATA_ON_IDLE is set.
//
// Read-during-write collision:
//   - WRITE_FIRST = 0: same-address read/write returns the old memory value.
//   - WRITE_FIRST = 1: same-address read/write returns wr_data_i by explicit output bypass.
//
// Memory contents are intentionally not reset. Reset controls only output/status registers. This
// keeps the wrapper suitable for FPGA block-RAM inference and avoids hiding reset-time memory
// initialization bugs.
module trecap_simple_dual_port_ram #(
    parameter int unsigned DATA_W                = 32,
    parameter int unsigned DEPTH                 = 256,
    parameter int unsigned ADDR_W                = (DEPTH <= 1) ? 1 : $clog2(DEPTH),
    parameter bit          WRITE_FIRST           = 1'b0,
    parameter bit          CLEAR_RD_DATA_ON_RESET = 1'b1,
    parameter bit          CLEAR_RD_DATA_ON_IDLE  = 1'b0,
    parameter string       INIT_FILE             = ""
) (
    input  logic                clk,
    input  logic                rst_n,

    input  logic                wr_en_i,
    input  logic [ADDR_W-1:0]   wr_addr_i,
    input  logic [DATA_W-1:0]   wr_data_i,

    input  logic                rd_en_i,
    input  logic [ADDR_W-1:0]   rd_addr_i,
    output logic [DATA_W-1:0]   rd_data_o,
    output logic                rd_valid_o,

    output logic                rd_wr_same_addr_o,
    output logic                wr_oob_o,
    output logic                rd_oob_o
);

    localparam int unsigned DEPTH_SAFE = (DEPTH < 1) ? 1 : DEPTH;
    localparam longint unsigned ADDR_SPACE = (ADDR_W >= 63)
        ? 64'hffff_ffff_ffff_ffff
        : (64'd1 << ADDR_W);

    logic [DATA_W-1:0] mem [0:DEPTH_SAFE-1];

    logic wr_addr_in_range;
    logic rd_addr_in_range;
    logic same_addr;
    logic rd_wr_collision;

    assign wr_addr_in_range = (wr_addr_i < DEPTH_SAFE);
    assign rd_addr_in_range = (rd_addr_i < DEPTH_SAFE);
    assign same_addr = (wr_addr_i == rd_addr_i);
    assign rd_wr_collision = wr_en_i & rd_en_i & wr_addr_in_range & rd_addr_in_range & same_addr;

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            rd_valid_o <= 1'b0;
            rd_wr_same_addr_o <= 1'b0;
            wr_oob_o <= 1'b0;
            rd_oob_o <= 1'b0;
            if (CLEAR_RD_DATA_ON_RESET) begin
                rd_data_o <= '0;
            end
        end else begin
            wr_oob_o <= wr_en_i & !wr_addr_in_range;
            rd_oob_o <= rd_en_i & !rd_addr_in_range;
            rd_wr_same_addr_o <= rd_wr_collision;
            rd_valid_o <= rd_en_i & rd_addr_in_range;

            if (wr_en_i && wr_addr_in_range) begin
                mem[wr_addr_i] <= wr_data_i;
            end

            if (rd_en_i) begin
                if (rd_addr_in_range) begin
                    if (WRITE_FIRST && rd_wr_collision) begin
                        rd_data_o <= wr_data_i;
                    end else begin
                        rd_data_o <= mem[rd_addr_i];
                    end
                end else begin
                    rd_data_o <= '0;
                end
            end else if (CLEAR_RD_DATA_ON_IDLE) begin
                rd_data_o <= '0;
            end
        end
    end

    initial begin
        if (INIT_FILE != "") begin
            $readmemh(INIT_FILE, mem);
        end
    end

`ifndef SYNTHESIS
    initial begin
        if (DATA_W < 1) begin
            $fatal(1, "trecap_simple_dual_port_ram: DATA_W must be at least 1, got %0d", DATA_W);
        end
        if (DEPTH < 1) begin
            $fatal(1, "trecap_simple_dual_port_ram: DEPTH must be at least 1, got %0d", DEPTH);
        end
        if (ADDR_W < 1) begin
            $fatal(1, "trecap_simple_dual_port_ram: ADDR_W must be at least 1, got %0d", ADDR_W);
        end
        if (DEPTH > ADDR_SPACE) begin
            $fatal(
                1,
                "trecap_simple_dual_port_ram: ADDR_W=%0d cannot address DEPTH=%0d entries",
                ADDR_W,
                DEPTH
            );
        end
    end
`endif

endmodule : trecap_simple_dual_port_ram

`default_nettype wire
