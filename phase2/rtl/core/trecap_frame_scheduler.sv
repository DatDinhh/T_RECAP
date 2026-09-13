// SPDX-License-Identifier: MIT
// File class: [1] hand-written RTL.
// Layer: rtl/core/
// Owner: T-RECAP Phase 2 implementation.
// Purpose: Generate reference-model-compatible hop-spaced frame requests from accepted samples.
// Contract: Frames are requested at positive multiples of H accepted samples. The first frame
//           therefore occurs at tau_0 = H, not at L. Startup zero padding is owned by
//           trecap_input_ring.sv. This block does not store samples, perform STFT/WOLA
//           arithmetic, format telemetry, write DDR, or interact with HPS/Ethernet/dashboard.

`default_nettype none

module trecap_frame_scheduler
  import trecap_core_pkg::*;
#(
    parameter int unsigned L = T_FFT_L,
    parameter int unsigned H = T_HOP_H
) (
    input  logic        clk,
    input  logic        rst_n,
    input  logic        enable_i,
    input  logic        clear_i,
    input  logic        clear_sticky_i,

    // One-cycle pulse when the upstream input ring accepted a source sample. sample_idx_i is
    // the absolute zero-based source-sample index of that accepted sample.
    input  logic        sample_accept_i,
    input  logic [63:0] sample_idx_i,
    input  logic        source_discontinuity_i,
    // In finite-stream mode, active_frame_count_i is the exact Revision-J Nframes limit.
    // Accepted zero-extension ticks may continue through tau_last, but no request may be
    // generated after this many frames. Live mode leaves finite_stream_i deasserted.
    input  logic        finite_stream_i,
    input  logic [63:0] active_frame_count_i,

    // Frame request toward trecap_input_ring. trigger_sample_idx_o is the newest sample in
    // the L-sample reference frame after the just-accepted sample has been pushed into the
    // ring. The input ring emits zero-extended samples for pre-stream indices.
    output logic        frame_valid_o,
    input  logic        frame_ready_i,
    output logic [63:0] frame_idx_o,
    output logic [63:0] trigger_sample_idx_o,

    // Safe-boundary pulse used by CSR shadow/commit controls. It fires only when a frame
    // request is accepted by the input ring.
    output logic        frame_boundary_pulse_o,
    output logic [63:0] frame_count_o,
    output logic        protocol_error_sticky_o
);

    localparam logic [63:0] H_U64 = 64'(H);

    logic        frame_valid_q;
    logic [63:0] frame_idx_q;
    logic [63:0] trigger_sample_idx_q;
    logic [63:0] accepted_sample_count_q;
    logic [63:0] generated_frame_count_q;
    logic [63:0] accepted_frame_count_q;
    logic        have_last_sample_idx_q;
    logic [63:0] last_sample_idx_q;

    logic        frame_accept;
    logic [63:0] next_sample_count;
    logic        frame_due;
    logic        frame_limit_reached;
    logic        reset_state;

    assign frame_accept = frame_valid_q && frame_ready_i;
    assign next_sample_count = accepted_sample_count_q + 64'd1;

    // Reference model loop:
    //   xring.push(x[n]);
    //   sample_count = n + 1;
    //   if (sample_count % H == 0) process frame.
    // Live mode continues indefinitely. Finite replay supplies the exact active-frame limit so
    // pure WOLA drain ticks can never create dummy FFT/mask/statistics work.
    assign frame_limit_reached = finite_stream_i &&
                                 (generated_frame_count_q >= active_frame_count_i);
    assign frame_due = enable_i && sample_accept_i && !frame_limit_reached &&
                       (H_U64 != 64'd0) &&
                       ((next_sample_count % H_U64) == 64'd0);
    assign reset_state = clear_i || source_discontinuity_i;

    assign frame_valid_o = frame_valid_q;
    assign frame_idx_o = frame_idx_q;
    assign trigger_sample_idx_o = trigger_sample_idx_q;
    assign frame_count_o = accepted_frame_count_q;

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            frame_valid_q             <= 1'b0;
            frame_idx_q               <= 64'd0;
            trigger_sample_idx_q      <= 64'd0;
            accepted_sample_count_q   <= 64'd0;
            generated_frame_count_q   <= 64'd0;
            accepted_frame_count_q    <= 64'd0;
            have_last_sample_idx_q    <= 1'b0;
            last_sample_idx_q         <= 64'd0;
            frame_boundary_pulse_o    <= 1'b0;
            protocol_error_sticky_o   <= 1'b0;
        end else begin
            frame_boundary_pulse_o <= 1'b0;

            if (reset_state) begin
                frame_valid_q           <= 1'b0;
                frame_idx_q             <= 64'd0;
                trigger_sample_idx_q    <= 64'd0;
                accepted_sample_count_q <= 64'd0;
                generated_frame_count_q <= 64'd0;
                accepted_frame_count_q  <= 64'd0;
                have_last_sample_idx_q  <= 1'b0;
                last_sample_idx_q       <= 64'd0;
                protocol_error_sticky_o <= 1'b0;
            end else begin
                if (clear_sticky_i) begin
                    protocol_error_sticky_o <= 1'b0;
                end

                if (sample_accept_i) begin
                    accepted_sample_count_q <= next_sample_count;
                    if (finite_stream_i && (active_frame_count_i == 64'd0)) begin
                        protocol_error_sticky_o <= 1'b1;
                    end
                    if (have_last_sample_idx_q && (sample_idx_i != (last_sample_idx_q + 64'd1))) begin
                        protocol_error_sticky_o <= 1'b1;
                    end
                    have_last_sample_idx_q <= 1'b1;
                    last_sample_idx_q <= sample_idx_i;
                end

                if (frame_accept) begin
                    frame_boundary_pulse_o <= 1'b1;
                    accepted_frame_count_q <= accepted_frame_count_q + 64'd1;
                    frame_valid_q <= 1'b0;
                end

                if (frame_due) begin
                    if (frame_valid_q && !frame_ready_i) begin
                        // The core did not accept the prior H-spaced frame before the next
                        // frame boundary. Keep the old request stable and report the loss.
                        protocol_error_sticky_o <= 1'b1;
                    end else begin
                        frame_valid_q <= 1'b1;
                        frame_idx_q <= generated_frame_count_q;
                        trigger_sample_idx_q <= sample_idx_i;
                        generated_frame_count_q <= generated_frame_count_q + 64'd1;
                    end
                end

                if (!enable_i && frame_valid_q) begin
                    frame_valid_q <= 1'b0;
                    protocol_error_sticky_o <= 1'b1;
                end

                if (finite_stream_i &&
                    (generated_frame_count_q > active_frame_count_i ||
                     accepted_frame_count_q > active_frame_count_i)) begin
                    protocol_error_sticky_o <= 1'b1;
                end
            end
        end
    end

`ifndef SYNTHESIS
    initial begin
        if (L != T_FFT_L) begin
            $fatal(1, "trecap_frame_scheduler: L must match generated T_FFT_L");
        end
        if (H != T_HOP_H) begin
            $fatal(1, "trecap_frame_scheduler: H must match generated T_HOP_H");
        end
        if (H == 0) begin
            $fatal(1, "trecap_frame_scheduler: H must be nonzero");
        end
        if (H > L) begin
            $fatal(1, "trecap_frame_scheduler: H must not exceed L");
        end
    end
`endif

endmodule : trecap_frame_scheduler

`default_nettype wire
