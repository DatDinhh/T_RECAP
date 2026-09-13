// SPDX-License-Identifier: MIT
// File class: [1] hand-written RTL.
// Layer: rtl/common/
// Owner: T-RECAP Phase 2 implementation.
// Purpose: CDC-safe atomic snapshot of a multi-bit source-domain bus into a destination domain.
// Contract: Multi-bit values cross by request/snapshot/acknowledge; independent bit synchronizers
//           are forbidden by the Phase 2 CDC contract.
// Generated dependencies: none; this reusable CDC primitive is intentionally package-independent.

`default_nettype none

// Multi-cycle-path snapshot synchronizer with feedback acknowledgement.
//
// Use this module when the destination domain needs a coherent snapshot of a multi-bit source
// value, such as a source-domain counter, pointer, or status bus. The destination raises dst_req_i.
// The source captures src_bus_i atomically into an internal holding register. After the capture
// toggle has safely crossed to dst_clk, the destination samples that stable holding register into
// dst_snapshot_o and pulses dst_valid_o.
//
// CDC method:
//   dst request toggle -> synchronized into source domain
//   source captures bus and toggles data-ready
//   data-ready toggle -> synchronized into destination domain
//   destination samples held bus and toggles acknowledgement
//   acknowledgement toggle -> synchronized into source domain
//
// The multi-bit source holding register is intentionally sampled in dst_clk only after the source
// data-ready toggle has spent SYNC_STAGES cycles crossing into dst_clk. The source holds the
// snapshot stable until the destination acknowledgement returns. This is a standard feedback MCP
// pattern; top-level timing constraints shall treat the held bus path according to the CDC plan.
//
// This module is not a streaming CDC primitive. Use async_fifo.sv for streams.
module trecap_sync_bus_snapshot #(
    parameter int unsigned WIDTH       = 64,
    parameter int unsigned SYNC_STAGES = 2
) (
    input  logic             src_clk,
    input  logic             src_rst_n,
    input  logic [WIDTH-1:0] src_bus_i,

    output logic             src_capture_pulse_o,
    output logic             src_busy_o,

    input  logic             dst_clk,
    input  logic             dst_rst_n,
    input  logic             dst_req_i,

    output logic             dst_ready_o,
    output logic             dst_busy_o,
    output logic             dst_accept_o,
    output logic             dst_drop_o,
    output logic [WIDTH-1:0] dst_snapshot_o,
    output logic             dst_valid_o
);

    localparam int unsigned STAGES_SAFE = (SYNC_STAGES < 2) ? 2 : SYNC_STAGES;

    // Destination-domain request state.
    logic dst_req_toggle_q;
    logic dst_done_seen_q;
    logic dst_ack_toggle_q;

    // Source-domain state.
    logic src_req_seen_q;
    logic src_done_toggle_q;
    logic [WIDTH-1:0] src_snapshot_q;

    (* async_reg = "true" *)
    (* preserve = "true" *)
    (* altera_attribute = "-name SYNCHRONIZER_IDENTIFICATION FORCED" *)
    logic [STAGES_SAFE-1:0] src_req_sync_q;

    (* async_reg = "true" *)
    (* preserve = "true" *)
    (* altera_attribute = "-name SYNCHRONIZER_IDENTIFICATION FORCED" *)
    logic [STAGES_SAFE-1:0] src_ack_sync_q;

    (* async_reg = "true" *)
    (* preserve = "true" *)
    (* altera_attribute = "-name SYNCHRONIZER_IDENTIFICATION FORCED" *)
    logic [STAGES_SAFE-1:0] dst_done_sync_q;

    wire src_req_synchronized;
    wire src_ack_synchronized;
    wire dst_done_synchronized;
    wire src_ready_for_capture;
    wire dst_response_pending;

    assign src_req_synchronized = src_req_sync_q[STAGES_SAFE-1];
    assign src_ack_synchronized = src_ack_sync_q[STAGES_SAFE-1];
    assign dst_done_synchronized = dst_done_sync_q[STAGES_SAFE-1];

    assign src_ready_for_capture = (src_done_toggle_q == src_ack_synchronized);
    assign src_busy_o = !src_ready_for_capture;

    assign dst_response_pending = (dst_done_synchronized != dst_done_seen_q);
    assign dst_ready_o = (dst_req_toggle_q == dst_done_synchronized) && !dst_response_pending;
    assign dst_busy_o = !dst_ready_o;
    assign dst_accept_o = dst_req_i & dst_ready_o;
    assign dst_drop_o = dst_req_i & dst_busy_o;

    // Destination-domain request and sample side.
    always_ff @(posedge dst_clk or negedge dst_rst_n) begin
        if (!dst_rst_n) begin
            dst_req_toggle_q <= 1'b0;
            dst_done_seen_q <= 1'b0;
            dst_ack_toggle_q <= 1'b0;
            dst_done_sync_q <= '0;
            dst_snapshot_o <= '0;
            dst_valid_o <= 1'b0;
        end else begin
            dst_done_sync_q <= {dst_done_sync_q[STAGES_SAFE-2:0], src_done_toggle_q};
            dst_valid_o <= 1'b0;

            if (dst_accept_o) begin
                dst_req_toggle_q <= ~dst_req_toggle_q;
            end

            if (dst_done_synchronized != dst_done_seen_q) begin
                // src_snapshot_q has been held stable while the data-ready toggle crossed.
                dst_snapshot_o <= src_snapshot_q;
                dst_done_seen_q <= dst_done_synchronized;
                dst_ack_toggle_q <= ~dst_ack_toggle_q;
                dst_valid_o <= 1'b1;
            end
        end
    end

    // Source-domain request consume, atomic bus capture, and source-side busy tracking.
    always_ff @(posedge src_clk or negedge src_rst_n) begin
        if (!src_rst_n) begin
            src_req_sync_q <= '0;
            src_ack_sync_q <= '0;
            src_req_seen_q <= 1'b0;
            src_done_toggle_q <= 1'b0;
            src_snapshot_q <= '0;
            src_capture_pulse_o <= 1'b0;
        end else begin
            src_req_sync_q <= {src_req_sync_q[STAGES_SAFE-2:0], dst_req_toggle_q};
            src_ack_sync_q <= {src_ack_sync_q[STAGES_SAFE-2:0], dst_ack_toggle_q};
            src_capture_pulse_o <= 1'b0;

            if ((src_req_synchronized != src_req_seen_q) && src_ready_for_capture) begin
                src_snapshot_q <= src_bus_i;
                src_req_seen_q <= src_req_synchronized;
                src_done_toggle_q <= ~src_done_toggle_q;
                src_capture_pulse_o <= 1'b1;
            end
        end
    end

`ifndef SYNTHESIS
    initial begin
        if (WIDTH < 1) begin
            $fatal(1, "trecap_sync_bus_snapshot: WIDTH must be at least 1, got %0d", WIDTH);
        end
        if (SYNC_STAGES < 2) begin
            $warning(
                "trecap_sync_bus_snapshot: SYNC_STAGES=%0d requested; using STAGES_SAFE=%0d",
                SYNC_STAGES,
                STAGES_SAFE
            );
        end
    end
`endif

endmodule : trecap_sync_bus_snapshot

`default_nettype wire
