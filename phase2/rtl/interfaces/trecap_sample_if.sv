// SPDX-License-Identifier: MIT
// File class: [1] hand-written RTL interface.
// Layer: rtl/interfaces/
// Owner: T-RECAP Phase 2 implementation.
// Purpose: Ready/valid signed sample-stream interface for source adapters and core input logic.
// Contract: Carry signed N-bit samples with absolute sample indices without encoding board,
//           telemetry, DDR, HPS, Ethernet, or algorithm-side policy in the interface itself.

`default_nettype none

// T-RECAP sample interface.
//
// This interface is the normal ready/valid stream used outside the mathematical core boundary:
// source adapters, source muxes, BRAM replay, diagnostic source, and core input staging may use it.
// It is not a telemetry tap and it is not a CDC primitive. If a sample stream crosses clock
// domains, place an async FIFO or documented CDC wrapper above this interface.
//
// Signal policy:
//   - sample.valid marks a live sample beat.
//   - ready is driven by the sink.
//   - accept/sample_accept is true when sample.valid && ready.
//   - sample.data is a signed T_SAMPLE_W value produced after source-specific scaling.
//   - sample.sample_idx is the absolute sample index used by replay, telemetry, and debug logic.
interface trecap_sample_if #(
    parameter int unsigned SAMPLE_W = trecap_core_pkg::T_SAMPLE_W
) (
    input logic clk,
    input logic rst_n
);

    import trecap_core_pkg::*;
    import trecap_iface_pkg::*;

    trecap_sample_t sample;
    logic           ready;

    wire                         valid = sample.valid;
    wire                         sample_valid = sample.valid;
    wire signed [SAMPLE_W-1:0]   sample_data = sample.data[SAMPLE_W-1:0];
    wire [63:0]                  sample_idx = sample.sample_idx;
    wire                         accept = sample.valid && ready;
    wire                         sample_accept = accept;
    wire                         stalled = sample.valid && !ready;

    modport source (
        input  clk,
        input  rst_n,
        output sample,
        input  ready,
        input  valid,
        input  sample_valid,
        input  sample_data,
        input  sample_idx,
        input  accept,
        input  sample_accept,
        input  stalled
    );

    modport sink (
        input  clk,
        input  rst_n,
        input  sample,
        output ready,
        input  valid,
        input  sample_valid,
        input  sample_data,
        input  sample_idx,
        input  accept,
        input  sample_accept,
        input  stalled
    );

    modport monitor (
        input clk,
        input rst_n,
        input sample,
        input ready,
        input valid,
        input sample_valid,
        input sample_data,
        input sample_idx,
        input accept,
        input sample_accept,
        input stalled
    );

`ifndef SYNTHESIS
    initial begin
        if (SAMPLE_W != T_SAMPLE_W) begin
            $error("trecap_sample_if: SAMPLE_W must match generated T_SAMPLE_W");
        end
        if (T_SAMPLE_W == 0) begin
            $error("trecap_sample_if: T_SAMPLE_W must be nonzero");
        end
    end

    trecap_sample_t hold_sample_q;
    logic           hold_active_q;

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            hold_sample_q <= '0;
            hold_active_q <= 1'b0;
        end else begin
            if (sample.valid && !ready && !hold_active_q) begin
                hold_active_q <= 1'b1;
                hold_sample_q <= sample;
            end else if (!sample.valid || ready) begin
                hold_active_q <= 1'b0;
            end

            if (hold_active_q && sample.valid && !ready && (sample !== hold_sample_q)) begin
                $error("trecap_sample_if: sample payload changed while stalled");
            end
            if (sample.valid && (^sample.sample_idx === 1'bx)) begin
                $error("trecap_sample_if: sample_idx is X while sample is valid");
            end
            if (sample.valid && (^sample.data === 1'bx)) begin
                $error("trecap_sample_if: sample data is X while sample is valid");
            end
        end
    end
`endif

endinterface : trecap_sample_if

`default_nettype wire
