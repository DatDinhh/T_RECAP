// SPDX-License-Identifier: MIT
// File class: [1] hand-written RTL interface.
// Layer: rtl/interfaces/
// Owner: T-RECAP Phase 2 implementation.
// Purpose: Ready/valid frame-event interface for scheduler and core-stage boundaries.
// Contract: Carry frame index and trigger-sample metadata without carrying telemetry, DDR, CSR,
//           HPS, Ethernet, or dashboard behavior.

`default_nettype none

// T-RECAP frame interface.
//
// This interface carries frame events at ready/valid boundaries outside the valid-only core tap
// path. It is suitable for source/core scheduling and replay harness logic. It is not the
// non-stalling telemetry frame tap; telemetry observation uses trecap_core_tap_if or explicit
// trecap_core_tap_frame_t ports.
//
// Signal policy:
//   - frame.valid marks a frame event.
//   - ready is driven by the sink.
//   - accept/frame_accept is true when frame.valid && ready.
//   - frame.frame_idx is monotonic per frame source.
//   - frame.trigger_sample_idx identifies the input sample index that opened the frame.
interface trecap_frame_if (
    input logic clk,
    input logic rst_n
);

    import trecap_iface_pkg::*;

    trecap_frame_event_t frame;
    logic                ready;

    wire        valid = frame.valid;
    wire        frame_valid = frame.valid;
    wire [63:0] frame_idx = frame.frame_idx;
    wire [63:0] trigger_sample_idx = frame.trigger_sample_idx;
    wire        accept = frame.valid && ready;
    wire        frame_accept = accept;
    wire        stalled = frame.valid && !ready;

    modport source (
        input  clk,
        input  rst_n,
        output frame,
        input  ready,
        input  valid,
        input  frame_valid,
        input  frame_idx,
        input  trigger_sample_idx,
        input  accept,
        input  frame_accept,
        input  stalled
    );

    modport sink (
        input  clk,
        input  rst_n,
        input  frame,
        output ready,
        input  valid,
        input  frame_valid,
        input  frame_idx,
        input  trigger_sample_idx,
        input  accept,
        input  frame_accept,
        input  stalled
    );

    modport monitor (
        input clk,
        input rst_n,
        input frame,
        input ready,
        input valid,
        input frame_valid,
        input frame_idx,
        input trigger_sample_idx,
        input accept,
        input frame_accept,
        input stalled
    );

`ifndef SYNTHESIS
    trecap_frame_event_t hold_frame_q;
    logic                hold_active_q;

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            hold_frame_q <= '0;
            hold_active_q <= 1'b0;
        end else begin
            if (frame.valid && !ready && !hold_active_q) begin
                hold_active_q <= 1'b1;
                hold_frame_q <= frame;
            end else if (!frame.valid || ready) begin
                hold_active_q <= 1'b0;
            end

            if (hold_active_q && frame.valid && !ready && (frame !== hold_frame_q)) begin
                $error("trecap_frame_if: frame payload changed while stalled");
            end
            if (frame.valid && (^frame.frame_idx === 1'bx)) begin
                $error("trecap_frame_if: frame_idx is X while frame is valid");
            end
            if (frame.valid && (^frame.trigger_sample_idx === 1'bx)) begin
                $error("trecap_frame_if: trigger_sample_idx is X while frame is valid");
            end
        end
    end
`endif

endinterface : trecap_frame_if

`default_nettype wire
