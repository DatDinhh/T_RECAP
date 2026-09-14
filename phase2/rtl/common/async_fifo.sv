// SPDX-License-Identifier: MIT
// File class: [1] hand-written RTL.
// Layer: rtl/common/
// Owner: T-RECAP Phase 2 implementation.
// Purpose: Portable dual-clock ready/valid FIFO for CDC boundaries.
// Contract: Gray-coded pointer CDC; no independent multi-bit synchronization of payload data.
// Generated dependencies: none; this reusable primitive is intentionally package-independent.

`default_nettype none

// Asynchronous FIFO for moving a ready/valid byte/word stream between two unrelated clocks.
//
// CDC contract:
//   - Payload data is written into memory only in the write clock domain and read only by the read
//     pointer in the read clock domain.
//   - Only Gray-coded pointers cross clock domains.
//   - Pointer synchronizers use at least two stages.
//   - The FIFO does not provide packet-boundary semantics. If records must remain atomic, the
//     caller must keep full records in one clock domain or place packet metadata in the payload.
//
// Reset contract:
//   wr_rst_n resets the write-domain pointer and write-domain sticky flags.
//   rd_rst_n resets the read-domain pointer and read-domain sticky flags.
//   Both resets must be released through the reset plan for their respective clock domains.
//
// Storage note:
//   This implementation uses the classic Gray-pointer async FIFO structure with combinational
//   read of the current read pointer. It is appropriate for CDC control/telemetry FIFOs. If a
//   future high-capacity data path must force a vendor dual-clock block RAM, replace only the
//   storage primitive and keep the same pointer/CDC contract.
module trecap_async_fifo #(
    parameter int unsigned DATA_W             = 32,
    parameter int unsigned DEPTH              = 16,
    parameter int unsigned ADDR_W             = (DEPTH <= 2) ? 1 : $clog2(DEPTH),
    parameter int unsigned COUNT_W            = (DEPTH <= 1) ? 1 : $clog2(DEPTH + 1),
    parameter int unsigned SYNC_STAGES        = 2,
    parameter int unsigned ALMOST_FULL_LEVEL  = (DEPTH < 2) ? 1 : (DEPTH - 1),
    parameter int unsigned ALMOST_EMPTY_LEVEL = 1,
    parameter bit          CLEAR_ON_RESET     = 1'b0
) (
    input  logic                wr_clk,
    input  logic                wr_rst_n,
    input  logic                in_valid_i,
    output logic                in_ready_o,
    input  logic [DATA_W-1:0]   in_data_i,

    input  logic                rd_clk,
    input  logic                rd_rst_n,
    output logic                out_valid_o,
    input  logic                out_ready_i,
    output logic [DATA_W-1:0]   out_data_o,

    output logic [COUNT_W-1:0]  wr_level_o,
    output logic [COUNT_W-1:0]  rd_level_o,
    output logic                wr_full_o,
    output logic                rd_empty_o,
    output logic                wr_almost_full_o,
    output logic                rd_almost_empty_o,
    output logic                wr_push_pulse_o,
    output logic                rd_pop_pulse_o,
    output logic                wr_overflow_pulse_o,
    output logic                rd_underflow_pulse_o,
    output logic                wr_overflow_sticky_o,
    output logic                rd_underflow_sticky_o
);

    localparam int unsigned DEPTH_SAFE = (DEPTH < 2) ? 2 : DEPTH;
    localparam int unsigned ADDR_W_SAFE = (ADDR_W < 1) ? 1 : ADDR_W;
    localparam int unsigned PTR_W = ADDR_W_SAFE + 1;
    localparam int unsigned COUNT_W_SAFE = (COUNT_W < 1) ? 1 : COUNT_W;
    localparam int unsigned SYNC_STAGES_SAFE = (SYNC_STAGES < 2) ? 2 : SYNC_STAGES;
    localparam longint unsigned ADDR_SPACE = (ADDR_W_SAFE >= 63)
        ? 64'hffff_ffff_ffff_ffff
        : (64'd1 << ADDR_W_SAFE);

    (* ramstyle = "logic" *) logic [DATA_W-1:0] mem [0:DEPTH_SAFE-1];

    logic [PTR_W-1:0] wr_bin_q;
    logic [PTR_W-1:0] wr_gray_q;
    logic [PTR_W-1:0] rd_bin_q;
    logic [PTR_W-1:0] rd_gray_q;

    (* async_reg = "true" *)
    (* preserve = "true" *)
    (* altera_attribute = "-name SYNCHRONIZER_IDENTIFICATION FORCED" *)
    logic [PTR_W-1:0] rd_gray_sync_wr_q [0:SYNC_STAGES_SAFE-1];

    (* async_reg = "true" *)
    (* preserve = "true" *)
    (* altera_attribute = "-name SYNCHRONIZER_IDENTIFICATION FORCED" *)
    logic [PTR_W-1:0] wr_gray_sync_rd_q [0:SYNC_STAGES_SAFE-1];

    logic [PTR_W-1:0] rd_gray_sync_wr;
    logic [PTR_W-1:0] wr_gray_sync_rd;
    logic [PTR_W-1:0] rd_bin_sync_wr;
    logic [PTR_W-1:0] wr_bin_sync_rd;

    logic [PTR_W-1:0] wr_bin_inc;
    logic [PTR_W-1:0] wr_gray_inc;
    logic [PTR_W-1:0] rd_bin_inc;
    logic [PTR_W-1:0] rd_gray_inc;
    logic [PTR_W-1:0] wr_used_calc;
    logic [PTR_W-1:0] rd_used_calc;

    logic wr_full;
    logic rd_empty;
    logic push;
    logic pop;

    function automatic logic [PTR_W-1:0] bin_to_gray(
        input logic [PTR_W-1:0] bin_value
    );
    begin
        return (bin_value >> 1) ^ bin_value;
    end
    endfunction

    function automatic logic [PTR_W-1:0] gray_to_bin(
        input logic [PTR_W-1:0] gray_value
    );
        logic [PTR_W-1:0] bin_value;
    begin
        bin_value[PTR_W-1] = gray_value[PTR_W-1];
        for (int signed i = PTR_W - 2; i >= 0; i--) begin
            bin_value[i] = bin_value[i + 1] ^ gray_value[i];
        end
        return bin_value;
    end
    endfunction

    function automatic logic [PTR_W-1:0] invert_two_msb(
        input logic [PTR_W-1:0] gray_value
    );
        logic [PTR_W-1:0] result;
    begin
        result = gray_value;
        result[PTR_W-1] = ~gray_value[PTR_W-1];
        result[PTR_W-2] = ~gray_value[PTR_W-2];
        return result;
    end
    endfunction

    function automatic logic [COUNT_W_SAFE-1:0] count_cast(
        input logic [PTR_W-1:0] ptr_delta
    );
        logic [COUNT_W_SAFE-1:0] result;
    begin
        result = '0;
        for (int unsigned i = 0; i < COUNT_W_SAFE; i++) begin
            if (i < PTR_W) begin
                result[i] = ptr_delta[i];
            end
        end
        return result;
    end
    endfunction

    assign rd_gray_sync_wr = rd_gray_sync_wr_q[SYNC_STAGES_SAFE-1];
    assign wr_gray_sync_rd = wr_gray_sync_rd_q[SYNC_STAGES_SAFE-1];
    assign rd_bin_sync_wr  = gray_to_bin(rd_gray_sync_wr);
    assign wr_bin_sync_rd  = gray_to_bin(wr_gray_sync_rd);

    assign wr_bin_inc  = wr_bin_q + PTR_W'(1);
    assign wr_gray_inc = bin_to_gray(wr_bin_inc);
    assign rd_bin_inc  = rd_bin_q + PTR_W'(1);
    assign rd_gray_inc = bin_to_gray(rd_bin_inc);

    assign wr_full  = (wr_gray_q == invert_two_msb(rd_gray_sync_wr));
    assign rd_empty = (rd_gray_q == wr_gray_sync_rd);

    assign push = in_valid_i & !wr_full;
    assign pop  = out_ready_i & !rd_empty;

    assign in_ready_o  = !wr_full;
    assign out_valid_o = !rd_empty;
    assign out_data_o  = mem[rd_bin_q[ADDR_W_SAFE-1:0]];

    assign wr_used_calc = wr_bin_q - rd_bin_sync_wr;
    assign rd_used_calc = wr_bin_sync_rd - rd_bin_q;

    assign wr_level_o = count_cast(wr_used_calc);
    assign rd_level_o = count_cast(rd_used_calc);
    assign wr_full_o  = wr_full;
    assign rd_empty_o = rd_empty;
    assign wr_almost_full_o  = (count_cast(wr_used_calc) >= COUNT_W_SAFE'(ALMOST_FULL_LEVEL));
    assign rd_almost_empty_o = (count_cast(rd_used_calc) <= COUNT_W_SAFE'(ALMOST_EMPTY_LEVEL));
    assign wr_push_pulse_o = push;
    assign rd_pop_pulse_o  = pop;
    assign wr_overflow_pulse_o  = in_valid_i & wr_full;
    assign rd_underflow_pulse_o = out_ready_i & rd_empty;

    always_ff @(posedge wr_clk or negedge wr_rst_n) begin
        if (!wr_rst_n) begin
            wr_bin_q <= '0;
            wr_gray_q <= '0;
            wr_overflow_sticky_o <= 1'b0;
            for (int unsigned i = 0; i < SYNC_STAGES_SAFE; i++) begin
                rd_gray_sync_wr_q[i] <= '0;
            end
            if (CLEAR_ON_RESET) begin
                for (int unsigned i = 0; i < DEPTH_SAFE; i++) begin
                    mem[i] <= '0;
                end
            end
        end else begin
            rd_gray_sync_wr_q[0] <= rd_gray_q;
            for (int unsigned i = 1; i < SYNC_STAGES_SAFE; i++) begin
                rd_gray_sync_wr_q[i] <= rd_gray_sync_wr_q[i - 1];
            end

            if (push) begin
                mem[wr_bin_q[ADDR_W_SAFE-1:0]] <= in_data_i;
                wr_bin_q <= wr_bin_inc;
                wr_gray_q <= wr_gray_inc;
            end

            if (wr_overflow_pulse_o) begin
                wr_overflow_sticky_o <= 1'b1;
            end
        end
    end

    always_ff @(posedge rd_clk or negedge rd_rst_n) begin
        if (!rd_rst_n) begin
            rd_bin_q <= '0;
            rd_gray_q <= '0;
            rd_underflow_sticky_o <= 1'b0;
            for (int unsigned i = 0; i < SYNC_STAGES_SAFE; i++) begin
                wr_gray_sync_rd_q[i] <= '0;
            end
        end else begin
            wr_gray_sync_rd_q[0] <= wr_gray_q;
            for (int unsigned i = 1; i < SYNC_STAGES_SAFE; i++) begin
                wr_gray_sync_rd_q[i] <= wr_gray_sync_rd_q[i - 1];
            end

            if (pop) begin
                rd_bin_q <= rd_bin_inc;
                rd_gray_q <= rd_gray_inc;
            end

            if (rd_underflow_pulse_o) begin
                rd_underflow_sticky_o <= 1'b1;
            end
        end
    end

`ifndef SYNTHESIS
    function automatic bit is_power_of_two(input int unsigned value);
    begin
        return (value != 0) && ((value & (value - 1)) == 0);
    end
    endfunction

    initial begin
        if (DATA_W < 1) begin
            $fatal(1, "trecap_async_fifo: DATA_W must be at least 1, got %0d", DATA_W);
        end
        if (DEPTH < 2) begin
            $fatal(1, "trecap_async_fifo: DEPTH must be at least 2, got %0d", DEPTH);
        end
        if (!is_power_of_two(DEPTH)) begin
            $fatal(1, "trecap_async_fifo: DEPTH must be a power of two, got %0d", DEPTH);
        end
        if (ADDR_W < 1) begin
            $fatal(1, "trecap_async_fifo: ADDR_W must be at least 1, got %0d", ADDR_W);
        end
        if (DEPTH != (1 << ADDR_W)) begin
            $fatal(
                1,
                "trecap_async_fifo: DEPTH=%0d must equal 2**ADDR_W where ADDR_W=%0d",
                DEPTH,
                ADDR_W
            );
        end
        if (DEPTH > ADDR_SPACE) begin
            $fatal(
                1,
                "trecap_async_fifo: ADDR_W=%0d cannot address DEPTH=%0d entries",
                ADDR_W,
                DEPTH
            );
        end
        if (COUNT_W < 1) begin
            $fatal(1, "trecap_async_fifo: COUNT_W must be at least 1, got %0d", COUNT_W);
        end
        if (SYNC_STAGES < 2) begin
            $warning(
                "trecap_async_fifo: SYNC_STAGES=%0d requested; using SYNC_STAGES_SAFE=%0d",
                SYNC_STAGES,
                SYNC_STAGES_SAFE
            );
        end
    end

    always_ff @(posedge wr_clk) begin
        if (wr_rst_n && wr_overflow_pulse_o) begin
            $warning("trecap_async_fifo: write attempted while FIFO full");
        end
    end

    always_ff @(posedge rd_clk) begin
        if (rd_rst_n && rd_underflow_pulse_o) begin
            $warning("trecap_async_fifo: read attempted while FIFO empty");
        end
    end
`endif

endmodule : trecap_async_fifo

`default_nettype wire
