// SPDX-License-Identifier: MIT
// File class: [1] hand-written RTL.
// Layer: rtl/common/
// Owner: T-RECAP Phase 2 implementation.
// Purpose: Same-clock ready/valid FIFO for bounded local buffering.
// Contract: Preserve order, avoid silent drops, and expose attempted overflow/underflow status.
// Generated dependencies: none; this reusable primitive is intentionally package-independent.

`default_nettype none

// Same-clock first-word-fall-through FIFO.
//
// This block is for ready/valid boundaries inside one clock domain. It is not a CDC primitive;
// use trecap_async_fifo for clock crossing and use trecap_sync_bus_snapshot for atomic multi-bit
// snapshots. The FIFO never accepts data when full unless an output beat is consumed in the same
// cycle, so a well-behaved upstream source sees backpressure instead of silent loss.
//
// Transfer rules:
//   - Input transfer:  in_valid_i && in_ready_o.
//   - Output transfer: out_valid_o && out_ready_i.
//   - Ordering is strictly FIFO.
//   - When the FIFO is full and a pop occurs, one push may be accepted in the same cycle.
module trecap_sync_fifo #(
    parameter int unsigned DATA_W                  = 32,
    parameter int unsigned DEPTH                   = 16,
    parameter int unsigned ADDR_W                  = (DEPTH <= 1) ? 1 : $clog2(DEPTH),
    parameter int unsigned ALMOST_FULL_LEVEL       = (DEPTH <= 1) ? 1 : (DEPTH - 1),
    parameter bit          CLEAR_DATA_ON_RESET     = 1'b0,
    parameter bit          CLEAR_DATA_ON_EMPTY     = 1'b0
) (
    input  logic                clk,
    input  logic                rst_n,
    input  logic                clear_sticky_i,

    input  logic                in_valid_i,
    output logic                in_ready_o,
    input  logic [DATA_W-1:0]   in_payload_i,

    output logic                out_valid_o,
    input  logic                out_ready_i,
    output logic [DATA_W-1:0]   out_payload_o,

    output logic                full_o,
    output logic                almost_full_o,
    output logic                empty_o,
    output logic [((DEPTH <= 1) ? 1 : $clog2(DEPTH + 1))-1:0] level_o,

    output logic                overflow_attempt_pulse_o,
    output logic                underflow_attempt_pulse_o,
    output logic                overflow_sticky_o,
    output logic                underflow_sticky_o
);

    localparam int unsigned DEPTH_SAFE = (DEPTH < 1) ? 1 : DEPTH;
    localparam int unsigned COUNT_W = (DEPTH_SAFE <= 1) ? 1 : $clog2(DEPTH_SAFE + 1);
    localparam int unsigned ALMOST_FULL_LEVEL_SAFE =
        (ALMOST_FULL_LEVEL > DEPTH_SAFE) ? DEPTH_SAFE : ALMOST_FULL_LEVEL;
    localparam longint unsigned ADDR_SPACE = (ADDR_W >= 63)
        ? 64'hffff_ffff_ffff_ffff
        : (64'd1 << ADDR_W);

    logic [DATA_W-1:0] mem [0:DEPTH_SAFE-1];

    logic [ADDR_W-1:0] wr_ptr_q;
    logic [ADDR_W-1:0] rd_ptr_q;
    logic [COUNT_W-1:0] count_q;

    logic push;
    logic pop;
    logic full_q;
    logic empty_q;

    function automatic logic [ADDR_W-1:0] ptr_inc(input logic [ADDR_W-1:0] ptr);
        if (DEPTH_SAFE <= 1) begin
            return '0;
        end else if (ptr == ADDR_W'(DEPTH_SAFE - 1)) begin
            return '0;
        end else begin
            return ptr + ADDR_W'(1);
        end
    endfunction : ptr_inc

    assign full_q = (count_q == COUNT_W'(DEPTH_SAFE));
    assign empty_q = (count_q == '0);

    assign pop = out_valid_o & out_ready_i;
    assign in_ready_o = !full_q | pop;
    assign push = in_valid_i & in_ready_o;

    assign out_valid_o = !empty_q;
    assign out_payload_o = empty_q ? '0 : mem[rd_ptr_q];

    assign full_o = full_q;
    assign empty_o = empty_q;
    assign almost_full_o = (count_q >= COUNT_W'(ALMOST_FULL_LEVEL_SAFE));
    assign level_o = count_q;

    assign overflow_attempt_pulse_o = in_valid_i & !in_ready_o;
    assign underflow_attempt_pulse_o = out_ready_i & !out_valid_o;

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            wr_ptr_q <= '0;
            rd_ptr_q <= '0;
            count_q <= '0;
            overflow_sticky_o <= 1'b0;
            underflow_sticky_o <= 1'b0;
            if (CLEAR_DATA_ON_RESET) begin
                for (int unsigned i = 0; i < DEPTH_SAFE; i++) begin
                    mem[i] <= '0;
                end
            end
        end else begin
            if (clear_sticky_i) begin
                overflow_sticky_o <= 1'b0;
                underflow_sticky_o <= 1'b0;
            end
            if (overflow_attempt_pulse_o) begin
                overflow_sticky_o <= 1'b1;
            end
            if (underflow_attempt_pulse_o) begin
                underflow_sticky_o <= 1'b1;
            end

            if (push) begin
                mem[wr_ptr_q] <= in_payload_i;
                wr_ptr_q <= ptr_inc(wr_ptr_q);
            end

            if (pop) begin
                rd_ptr_q <= ptr_inc(rd_ptr_q);
            end

            unique case ({push, pop})
                2'b10: count_q <= count_q + COUNT_W'(1);
                2'b01: count_q <= count_q - COUNT_W'(1);
                default: count_q <= count_q;
            endcase

            if (CLEAR_DATA_ON_EMPTY && (count_q == COUNT_W'(1)) && pop && !push) begin
                mem[rd_ptr_q] <= '0;
            end
        end
    end

`ifndef SYNTHESIS
    logic              hold_payload_check_valid_q;
    logic [DATA_W-1:0] hold_payload_check_q;

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            hold_payload_check_valid_q <= 1'b0;
            hold_payload_check_q <= '0;
        end else begin
            if (in_valid_i && !in_ready_o) begin
                if (hold_payload_check_valid_q && (in_payload_i !== hold_payload_check_q)) begin
                    $error("trecap_sync_fifo: in_payload_i changed while stalled");
                end
                hold_payload_check_valid_q <= 1'b1;
                hold_payload_check_q <= in_payload_i;
            end else begin
                hold_payload_check_valid_q <= 1'b0;
                hold_payload_check_q <= in_payload_i;
            end

            if (count_q > COUNT_W'(DEPTH_SAFE)) begin
                $error("trecap_sync_fifo: count exceeded DEPTH");
            end
        end
    end

    initial begin
        if (DATA_W < 1) begin
            $fatal(1, "trecap_sync_fifo: DATA_W must be at least 1, got %0d", DATA_W);
        end
        if (DEPTH < 1) begin
            $fatal(1, "trecap_sync_fifo: DEPTH must be at least 1, got %0d", DEPTH);
        end
        if (ADDR_W < 1) begin
            $fatal(1, "trecap_sync_fifo: ADDR_W must be at least 1, got %0d", ADDR_W);
        end
        if (DEPTH > ADDR_SPACE) begin
            $fatal(1, "trecap_sync_fifo: ADDR_W=%0d cannot address DEPTH=%0d", ADDR_W, DEPTH);
        end
    end
`endif

endmodule : trecap_sync_fifo

`default_nettype wire
