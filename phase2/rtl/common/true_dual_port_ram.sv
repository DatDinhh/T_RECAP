// SPDX-License-Identifier: MIT
// File class: [1] hand-written RTL.
// Layer: rtl/common/
// Owner: T-RECAP Phase 2 implementation.
// Purpose: Portable true dual-port RAM wrapper with independent clocks.
// Contract: Two symmetric synchronous ports; no generated constants and no board-specific IP.
// Generated dependencies: none; this reusable primitive is intentionally package-independent.

`default_nettype none

// True dual-port RAM wrapper.
//
// Port model:
//   - Port A and Port B each have independent clocks, enables, write-enables, addresses,
//     write data, synchronous read data, and one-cycle read-valid indicators.
//   - A port performs a synchronous read whenever <port>_en_i is high and the address is in
//     range. If <port>_we_i is also high, the port writes the same address in that cycle.
//
// Read-during-write policy on the same port:
//   - WRITE_FIRST_A/B = 0: the read data is the old memory value.
//   - WRITE_FIRST_A/B = 1: the read data is the same-cycle write data for that port.
//
// Cross-port same-address collisions:
//   - Simultaneous writes from both ports to the same address are intentionally illegal at the
//     integration level. FPGA vendor behavior is device/IP-specific. This wrapper reports the
//     condition in simulation; hardware users must prevent it by construction.
//   - Cross-port read-during-write to the same address is not bypassed here. Treat the returned
//     value as unspecified unless the caller has a documented schedule that avoids the hazard.
//
// Reset policy:
//   - Memory contents are not reset. Reset only clears output/status registers. This preserves
//     block-RAM inference and avoids hiding missing initialization.
module trecap_true_dual_port_ram #(
    parameter int unsigned DATA_W                 = 32,
    parameter int unsigned DEPTH                  = 256,
    parameter int unsigned ADDR_W                 = (DEPTH <= 1) ? 1 : $clog2(DEPTH),
    parameter bit          WRITE_FIRST_A          = 1'b0,
    parameter bit          WRITE_FIRST_B          = 1'b0,
    parameter bit          CLEAR_RD_DATA_ON_RESET = 1'b1,
    parameter bit          CLEAR_RD_DATA_ON_IDLE  = 1'b0,
    parameter string       INIT_FILE              = ""
) (
    input  logic              clk_a,
    input  logic              rst_a_n,
    input  logic              a_en_i,
    input  logic              a_we_i,
    input  logic [ADDR_W-1:0] a_addr_i,
    input  logic [DATA_W-1:0] a_wdata_i,
    output logic [DATA_W-1:0] a_rdata_o,
    output logic              a_rvalid_o,
    output logic              a_oob_o,

    input  logic              clk_b,
    input  logic              rst_b_n,
    input  logic              b_en_i,
    input  logic              b_we_i,
    input  logic [ADDR_W-1:0] b_addr_i,
    input  logic [DATA_W-1:0] b_wdata_i,
    output logic [DATA_W-1:0] b_rdata_o,
    output logic              b_rvalid_o,
    output logic              b_oob_o
);

    localparam int unsigned DEPTH_SAFE = (DEPTH < 1) ? 1 : DEPTH;
    localparam longint unsigned ADDR_SPACE = (ADDR_W >= 63)
        ? 64'hffff_ffff_ffff_ffff
        : (64'd1 << ADDR_W);

    logic [DATA_W-1:0] mem [0:DEPTH_SAFE-1];

    logic a_addr_in_range;
    logic b_addr_in_range;

    assign a_addr_in_range = (a_addr_i < DEPTH_SAFE);
    assign b_addr_in_range = (b_addr_i < DEPTH_SAFE);

    // Intentional always block instead of always_ff: true dual-clock RAM inference requires
    // two clocked processes writing the same memory array. Some tools flag that pattern as an
    // always_ff single-writer violation even though it is the standard RAM template.
    always @(posedge clk_a or negedge rst_a_n) begin
        if (!rst_a_n) begin
            a_rvalid_o <= 1'b0;
            a_oob_o <= 1'b0;
            if (CLEAR_RD_DATA_ON_RESET) begin
                a_rdata_o <= '0;
            end
        end else begin
            a_oob_o <= a_en_i & !a_addr_in_range;
            a_rvalid_o <= a_en_i & a_addr_in_range;

            if (a_en_i && a_addr_in_range) begin
                if (a_we_i) begin
                    mem[a_addr_i] <= a_wdata_i;
                end

                if (WRITE_FIRST_A && a_we_i) begin
                    a_rdata_o <= a_wdata_i;
                end else begin
                    a_rdata_o <= mem[a_addr_i];
                end
            end else if (CLEAR_RD_DATA_ON_IDLE) begin
                a_rdata_o <= '0;
            end
        end
    end

    // See the Port A process note above; this is the second physical memory port.
    always @(posedge clk_b or negedge rst_b_n) begin
        if (!rst_b_n) begin
            b_rvalid_o <= 1'b0;
            b_oob_o <= 1'b0;
            if (CLEAR_RD_DATA_ON_RESET) begin
                b_rdata_o <= '0;
            end
        end else begin
            b_oob_o <= b_en_i & !b_addr_in_range;
            b_rvalid_o <= b_en_i & b_addr_in_range;

            if (b_en_i && b_addr_in_range) begin
                if (b_we_i) begin
                    mem[b_addr_i] <= b_wdata_i;
                end

                if (WRITE_FIRST_B && b_we_i) begin
                    b_rdata_o <= b_wdata_i;
                end else begin
                    b_rdata_o <= mem[b_addr_i];
                end
            end else if (CLEAR_RD_DATA_ON_IDLE) begin
                b_rdata_o <= '0;
            end
        end
    end

    initial begin
        if (INIT_FILE != "") begin
            $readmemh(INIT_FILE, mem);
        end
    end

`ifndef SYNTHESIS
    always_ff @(posedge clk_a) begin
        if (rst_a_n && rst_b_n) begin
            if (a_en_i && a_we_i && a_addr_in_range &&
                b_en_i && b_we_i && b_addr_in_range &&
                (a_addr_i == b_addr_i)) begin
                $error(
                    "trecap_true_dual_port_ram: simultaneous cross-port write collision at address %0d",
                    a_addr_i
                );
            end
        end
    end

    initial begin
        if (DATA_W < 1) begin
            $fatal(1, "trecap_true_dual_port_ram: DATA_W must be at least 1, got %0d", DATA_W);
        end
        if (DEPTH < 1) begin
            $fatal(1, "trecap_true_dual_port_ram: DEPTH must be at least 1, got %0d", DEPTH);
        end
        if (ADDR_W < 1) begin
            $fatal(1, "trecap_true_dual_port_ram: ADDR_W must be at least 1, got %0d", ADDR_W);
        end
        if (DEPTH > ADDR_SPACE) begin
            $fatal(
                1,
                "trecap_true_dual_port_ram: ADDR_W=%0d cannot address DEPTH=%0d entries",
                ADDR_W,
                DEPTH
            );
        end
    end
`endif

endmodule : trecap_true_dual_port_ram

`default_nettype wire
