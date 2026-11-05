// SPDX-License-Identifier: MIT
// File class: [1] hand-written RTL.
// Layer: rtl/common/
// Owner: T-RECAP Phase 2 implementation.
// Purpose: CDC-safe one-event pulse transfer between two clock domains.
// Contract: One destination pulse is generated for every accepted source pulse; back-to-back
//           requests use an explicit ready/accept/drop interface instead of relying on pulse width.
// Generated dependencies: none; this reusable CDC primitive is intentionally package-independent.

`default_nettype none

// Toggle/acknowledge pulse synchronizer.
//
// Use this module for one-cycle control pulses that must cross from src_clk into dst_clk, such as
// RING_WR_SNAPSHOT, CORE_COUNT_SNAPSHOT, RING_RD_COMMIT, clear_metrics, telemetry_soft_reset,
// or similar command events.
//
// This module is not a data-bus synchronizer. For multi-bit values, use shadow/commit logic,
// trecap_sync_bus_snapshot, or an async FIFO.
//
// Source-domain behavior:
//   - src_ready_o is high when the previous accepted event has been acknowledged by dst_clk.
//   - src_accept_o is high combinationally when src_pulse_i is accepted.
//   - src_drop_o is high combinationally when src_pulse_i is asserted while the synchronizer is busy.
//
// Destination-domain behavior:
//   - dst_pulse_o is a one-dst_clk-cycle pulse for each accepted source event.
//
// Reset behavior:
//   - Each side has its own active-low reset.
//   - After reset, in-flight events may be lost; higher-level CSR/control logic shall reissue any
//     required command after reset sequencing completes.
module trecap_sync_pulse #(
    parameter int unsigned SYNC_STAGES = 2
) (
    input  logic src_clk,
    input  logic src_rst_n,
    input  logic src_pulse_i,

    output logic src_ready_o,
    output logic src_busy_o,
    output logic src_accept_o,
    output logic src_drop_o,

    input  logic dst_clk,
    input  logic dst_rst_n,
    output logic dst_pulse_o
);

    localparam int unsigned STAGES_SAFE = (SYNC_STAGES < 2) ? 2 : SYNC_STAGES;

    logic src_event_toggle_q;

    (* async_reg = "true" *)
    (* preserve = "true" *)
    (* altera_attribute = "-name SYNCHRONIZER_IDENTIFICATION FORCED" *)
    logic [STAGES_SAFE-1:0] src_ack_sync_q;

    (* async_reg = "true" *)
    (* preserve = "true" *)
    (* altera_attribute = "-name SYNCHRONIZER_IDENTIFICATION FORCED" *)
    logic [STAGES_SAFE-1:0] dst_event_sync_q;

    logic dst_event_seen_q;

    wire src_ack_synchronized;
    wire dst_event_synchronized;

    assign src_ack_synchronized = src_ack_sync_q[STAGES_SAFE-1];
    assign dst_event_synchronized = dst_event_sync_q[STAGES_SAFE-1];

    assign src_ready_o = (src_ack_synchronized == src_event_toggle_q);
    assign src_busy_o = !src_ready_o;
    assign src_accept_o = src_pulse_i & src_ready_o;
    assign src_drop_o = src_pulse_i & src_busy_o;

    // Source-domain request toggle. The source toggles only for accepted pulses. A pulse asserted
    // while busy is not queued; src_drop_o makes the missed request explicit to the caller.
    always_ff @(posedge src_clk or negedge src_rst_n) begin
        if (!src_rst_n) begin
            src_event_toggle_q <= 1'b0;
            src_ack_sync_q <= '0;
        end else begin
            src_ack_sync_q <= {src_ack_sync_q[STAGES_SAFE-2:0], dst_event_seen_q};

            if (src_accept_o) begin
                src_event_toggle_q <= ~src_event_toggle_q;
            end
        end
    end

    // Destination-domain event detection and acknowledgement. The acknowledgement is the
    // dst_event_seen_q toggle itself; it is synchronized back into the source domain above.
    always_ff @(posedge dst_clk or negedge dst_rst_n) begin
        if (!dst_rst_n) begin
            dst_event_sync_q <= '0;
            dst_event_seen_q <= 1'b0;
            dst_pulse_o <= 1'b0;
        end else begin
            dst_event_sync_q <= {dst_event_sync_q[STAGES_SAFE-2:0], src_event_toggle_q};
            dst_pulse_o <= 1'b0;

            if (dst_event_synchronized != dst_event_seen_q) begin
                dst_event_seen_q <= dst_event_synchronized;
                dst_pulse_o <= 1'b1;
            end
        end
    end

`ifndef SYNTHESIS
    initial begin
        if (SYNC_STAGES < 2) begin
            $warning(
                "trecap_sync_pulse: SYNC_STAGES=%0d requested; using STAGES_SAFE=%0d",
                SYNC_STAGES,
                STAGES_SAFE
            );
        end
    end
`endif

endmodule : trecap_sync_pulse

`default_nettype wire
