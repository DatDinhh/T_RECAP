// SPDX-License-Identifier: MIT
// File class: [1] hand-written RTL integration source.
// Layer: rtl/top/
// Owner: T-RECAP Phase 2 implementation.
// Purpose: Qualify one BRAM replay epoch through core completion and an HPS-visible DDR commit.

`default_nettype none

module trecap_bram_replay_e2e_supervisor (
    input  logic        clk,
    input  logic        rst_n,
    input  logic        clear_i,

    input  logic        replay_start_accept_pulse_i,
    input  logic        replay_path_busy_i,
    input  logic        replay_path_done_i,
    input  logic        replay_path_done_pulse_i,
    input  logic        replay_completion_error_sticky_i,
    input  logic        completion_fault_i,

    input  logic        transport_ready_i,
    input  logic        transport_clear_pulse_i,
    input  logic        transport_fault_i,
    input  logic        writer_idle_i,
    input  logic        writer_busy_i,
    input  logic        normal_commit_pulse_i,
    input  logic [63:0] producer_ptr_i,
    input  logic [31:0] dma_packet_count_i,
    input  logic [31:0] dma_drop_count_i,
    input  logic [31:0] packet_fifo_drop_count_i,

    output logic        replay_e2e_busy_o,
    output logic        replay_e2e_done_o,
    output logic        replay_e2e_done_pulse_o,
    output logic        replay_e2e_error_sticky_o
);

    logic        replay_e2e_inflight_q;
    logic        replay_e2e_done_q;
    logic        replay_e2e_done_pulse_q;
    logic        replay_e2e_error_sticky_q;
    logic        core_done_seen_q;
    logic        post_core_commit_seen_q;
    logic        baseline_valid_q;
    logic [63:0] post_core_producer_ptr_q;
    logic [31:0] post_core_dma_packet_count_q;
    logic [31:0] start_dma_drop_count_q;
    logic [31:0] start_packet_fifo_drop_count_q;

    logic transport_counter_fault_w;
    logic epoch_fault_w;
    logic post_core_progress_w;

    assign transport_counter_fault_w = baseline_valid_q &&
        ((dma_drop_count_i != start_dma_drop_count_q) ||
         (packet_fifo_drop_count_i != start_packet_fifo_drop_count_q));
    assign epoch_fault_w = replay_completion_error_sticky_i || completion_fault_i ||
                           transport_fault_i || transport_counter_fault_w ||
                           transport_clear_pulse_i ||
                           (core_done_seen_q && !replay_path_done_i);
    assign post_core_progress_w =
        (producer_ptr_i != post_core_producer_ptr_q) &&
        // Modular change remains correct across the 32-bit packet-counter wrap; the separate
        // normal_commit pulse proves that this change is a successful normal record commit.
        (dma_packet_count_i != post_core_dma_packet_count_q);

    assign replay_e2e_busy_o = rst_n &&
                               (replay_e2e_inflight_q || replay_path_busy_i);
    assign replay_e2e_done_o = replay_e2e_done_q && replay_path_done_i &&
                               !replay_e2e_busy_o && !replay_e2e_error_sticky_q;
    assign replay_e2e_done_pulse_o = replay_e2e_done_pulse_q;
    assign replay_e2e_error_sticky_o = replay_e2e_error_sticky_q;

    always_ff @(posedge clk or negedge rst_n) begin : p_replay_e2e_completion
        if (!rst_n) begin
            replay_e2e_inflight_q            <= 1'b0;
            replay_e2e_done_q                <= 1'b0;
            replay_e2e_done_pulse_q          <= 1'b0;
            replay_e2e_error_sticky_q        <= 1'b0;
            core_done_seen_q                 <= 1'b0;
            post_core_commit_seen_q          <= 1'b0;
            baseline_valid_q                 <= 1'b0;
            post_core_producer_ptr_q         <= 64'd0;
            post_core_dma_packet_count_q     <= 32'd0;
            start_dma_drop_count_q           <= 32'd0;
            start_packet_fifo_drop_count_q   <= 32'd0;
        end else begin
            replay_e2e_done_pulse_q <= 1'b0;

            if (clear_i) begin
                replay_e2e_inflight_q            <= 1'b0;
                replay_e2e_done_q                <= 1'b0;
                replay_e2e_error_sticky_q        <= 1'b0;
                core_done_seen_q                 <= 1'b0;
                post_core_commit_seen_q          <= 1'b0;
                baseline_valid_q                 <= 1'b0;
                post_core_producer_ptr_q         <= producer_ptr_i;
                post_core_dma_packet_count_q     <= dma_packet_count_i;
                start_dma_drop_count_q           <= dma_drop_count_i;
                start_packet_fifo_drop_count_q   <= packet_fifo_drop_count_i;
            end else if (replay_start_accept_pulse_i) begin
                replay_e2e_inflight_q            <= 1'b1;
                replay_e2e_done_q                <= 1'b0;
                // The integration clears partial telemetry/writer state on this same accepted
                // start edge. Sample transport counters/faults on the following cycle, after that
                // synchronous clear has taken effect.
                // Admission normally makes these false, but a CSR soft reset or fault can arrive
                // on the same edge as the accepted start.  Latch it here so the baseline-delay
                // window cannot erase a one-cycle failure indication.
                replay_e2e_error_sticky_q        <= !transport_ready_i ||
                                                    transport_clear_pulse_i ||
                                                    transport_fault_i ||
                                                    replay_completion_error_sticky_i ||
                                                    completion_fault_i;
                core_done_seen_q                 <= 1'b0;
                post_core_commit_seen_q          <= 1'b0;
                baseline_valid_q                 <= 1'b0;
                post_core_producer_ptr_q         <= producer_ptr_i;
                post_core_dma_packet_count_q     <= dma_packet_count_i;
                start_dma_drop_count_q           <= dma_drop_count_i;
                start_packet_fifo_drop_count_q   <= packet_fifo_drop_count_i;
            end else if (replay_e2e_inflight_q) begin
                if (!baseline_valid_q) begin
                    baseline_valid_q               <= 1'b1;
                    post_core_producer_ptr_q       <= producer_ptr_i;
                    post_core_dma_packet_count_q   <= dma_packet_count_i;
                    start_dma_drop_count_q         <= dma_drop_count_i;
                    start_packet_fifo_drop_count_q <= packet_fifo_drop_count_i;
                    // Counter baselines are deliberately sampled after the synchronous replay
                    // flush, but all level/pulse faults remain authoritative in this cycle.
                    if (!transport_ready_i || epoch_fault_w) begin
                        replay_e2e_error_sticky_q <= 1'b1;
                    end
                end else if (!transport_ready_i || epoch_fault_w) begin
                    replay_e2e_error_sticky_q <= 1'b1;
                end

                if (replay_path_done_pulse_i && baseline_valid_q) begin
                    core_done_seen_q             <= 1'b1;
                    post_core_producer_ptr_q     <= producer_ptr_i;
                    post_core_dma_packet_count_q <= dma_packet_count_i;
                end

                if (normal_commit_pulse_i && baseline_valid_q &&
                    (core_done_seen_q || replay_path_done_pulse_i)) begin
                    post_core_commit_seen_q <= 1'b1;
                end

                if (baseline_valid_q && core_done_seen_q && replay_path_done_i &&
                    post_core_commit_seen_q &&
                    post_core_progress_w && writer_idle_i && !writer_busy_i &&
                    transport_ready_i && !epoch_fault_w &&
                    !replay_e2e_error_sticky_q) begin
                    replay_e2e_inflight_q   <= 1'b0;
                    replay_e2e_done_q       <= 1'b1;
                    replay_e2e_done_pulse_q <= 1'b1;
                end

                // A retained failure is terminal only after the source/core path and writer are
                // quiescent. Drop actual E2E busy ownership at that point while preserving ERROR /
                // REARM_REQUIRED, so software can legally pulse the dedicated replay-only clear.
                if (replay_e2e_error_sticky_q && !replay_path_busy_i &&
                    writer_idle_i && !writer_busy_i) begin
                    replay_e2e_inflight_q <= 1'b0;
                end
            end
        end
    end

`ifndef SYNTHESIS
    always_ff @(posedge clk) begin
        if (rst_n && !clear_i && replay_e2e_done_o) begin
            if (!replay_path_done_i || !core_done_seen_q ||
                !post_core_commit_seen_q || !post_core_progress_w ||
                !writer_idle_i || writer_busy_i || replay_e2e_error_sticky_q) begin
                $error("trecap_bram_replay_e2e_supervisor: done without exact core and DDR completion");
            end
        end
    end
`endif

endmodule : trecap_bram_replay_e2e_supervisor

`default_nettype wire
