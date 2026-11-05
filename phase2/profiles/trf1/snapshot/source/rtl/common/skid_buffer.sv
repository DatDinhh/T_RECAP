// SPDX-License-Identifier: MIT
// File class: [1] hand-written RTL.
// Layer: rtl/common/
// Owner: T-RECAP Phase 2 implementation.
// Purpose: One-entry ready/valid skid buffer for same-clock flow-control boundaries.
// Contract: Preserve ordering and data integrity; never drop an accepted transfer.
// Generated dependencies: none; this reusable primitive is intentionally package-independent.

`default_nettype none

// Full-throughput same-clock ready/valid skid buffer.
//
// This block is intended for ready/valid streams outside the non-stalling core tap boundary,
// for example packetizer-to-FIFO or record-builder service boundaries. It is not a CDC primitive.
// Use async_fifo.sv or an explicit snapshot/commit helper when clocks differ.
//
// Interface contract:
//   - A transfer is accepted at the input when in_valid && in_ready.
//   - A transfer is consumed at the output when out_valid && out_ready.
//   - Accepted transfers appear at the output in the same order.
//   - If the downstream side stalls for one cycle, one extra input beat can be captured in the
//     skid register instead of being dropped.
//
// Storage:
//   - out_* is a registered output beat.
//   - buf_* is the one-beat skid slot used when out_valid is held and out_ready is low.
//
// Timing note:
//   in_ready has a short combinational dependency on out_ready to avoid a throughput bubble when
//   the skid slot drains. If a fully registered ready boundary is required for a particular timing
//   path, add a higher-level register slice or FIFO and document that timing cut.
module trecap_skid_buffer #(
    parameter int unsigned DATA_W         = 32,
    parameter bit          CLEAR_ON_RESET = 1'b1,
    parameter bit          CLEAR_ON_IDLE  = 1'b0
) (
    input  logic                clk,
    input  logic                rst_n,

    input  logic                in_valid,
    output logic                in_ready,
    input  logic [DATA_W-1:0]   in_payload,

    output logic                out_valid,
    input  logic                out_ready,
    output logic [DATA_W-1:0]   out_payload,

    output logic                buffered_o,
    output logic                full_o,
    output logic                empty_o
);

    logic              out_valid_q;
    logic [DATA_W-1:0] out_payload_q;
    logic              buf_valid_q;
    logic [DATA_W-1:0] buf_payload_q;

    logic advance_out;
    logic take_in;

    assign advance_out = out_ready | !out_valid_q;
    assign in_ready    = advance_out | !buf_valid_q;
    assign take_in     = in_valid & in_ready;

    assign out_valid   = out_valid_q;
    assign out_payload = out_payload_q;

    assign buffered_o  = buf_valid_q;
    assign full_o      = out_valid_q & buf_valid_q;
    assign empty_o     = !out_valid_q & !buf_valid_q;

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            out_valid_q <= 1'b0;
            buf_valid_q <= 1'b0;
            if (CLEAR_ON_RESET) begin
                out_payload_q <= '0;
                buf_payload_q <= '0;
            end
        end else begin
            if (advance_out) begin
                if (buf_valid_q) begin
                    // Drain the skid slot into the registered output. If a new input beat is
                    // accepted in the same cycle, refill the skid slot. This keeps throughput at
                    // one beat per cycle while recovering from a stall.
                    out_valid_q <= 1'b1;
                    out_payload_q <= buf_payload_q;

                    if (take_in) begin
                        buf_valid_q <= 1'b1;
                        buf_payload_q <= in_payload;
                    end else begin
                        buf_valid_q <= 1'b0;
                        if (CLEAR_ON_IDLE) begin
                            buf_payload_q <= '0;
                        end
                    end
                end else begin
                    // No buffered beat exists. Move an accepted input beat directly into the
                    // registered output, or mark the output invalid when no input is present.
                    out_valid_q <= take_in;
                    if (take_in) begin
                        out_payload_q <= in_payload;
                    end else if (CLEAR_ON_IDLE) begin
                        out_payload_q <= '0;
                    end

                    buf_valid_q <= 1'b0;
                    if (CLEAR_ON_IDLE) begin
                        buf_payload_q <= '0;
                    end
                end
            end else begin
                // The output is valid and downstream is stalled. Hold the registered output.
                // Capture one additional accepted input beat into the skid slot.
                if (take_in) begin
                    buf_valid_q <= 1'b1;
                    buf_payload_q <= in_payload;
                end
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
            if (in_valid && !in_ready) begin
                if (hold_payload_check_valid_q && (in_payload !== hold_payload_check_q)) begin
                    $error(
                        "trecap_skid_buffer: in_payload changed while in_valid=1 and in_ready=0"
                    );
                end
                hold_payload_check_valid_q <= 1'b1;
                hold_payload_check_q <= in_payload;
            end else begin
                hold_payload_check_valid_q <= 1'b0;
                hold_payload_check_q <= in_payload;
            end
        end
    end

    initial begin
        if (DATA_W < 1) begin
            $fatal(1, "trecap_skid_buffer: DATA_W must be at least 1, got %0d", DATA_W);
        end
    end
`endif

endmodule : trecap_skid_buffer

`default_nettype wire
