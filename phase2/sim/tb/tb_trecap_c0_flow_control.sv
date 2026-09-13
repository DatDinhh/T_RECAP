// SPDX-License-Identifier: MIT
// File class: [1] hand-written verification.
// Purpose: Exercise C0 accepted-sample and frame conservation with the real BRAM replay source
//          and prolonged downstream backpressure.
//
// This regression targets the source -> input ring -> frame scheduler boundary only. It does
// not claim FFT/IFFT/WOLA arithmetic signoff.

`timescale 1ns/1ps
`default_nettype none

module tb_trecap_c0_flow_control;
    import trecap_core_pkg::*;
    import trecap_iface_pkg::*;

    localparam int unsigned L = T_FFT_L;
    localparam int unsigned H = T_HOP_H;
    localparam int unsigned P = T_FFT_P;
    // Six hops force the 512-entry ring to wrap while preserving enough distinct sample data to
    // detect a stale-tag/new-data substitution.
    localparam int unsigned TARGET_SAMPLES = 6 * H;
    localparam int unsigned EXPECTED_FRAMES = TARGET_SAMPLES / H;
    localparam int unsigned WATCHDOG_CYCLES = 40000;

    logic clk;
    logic rst_n;
    logic enable_i;
    logic clear_i;
    logic clear_sticky_i;
    logic start_i;

    logic                               source_valid_w;
    logic                               source_ready_w;
    trecap_sample_t                     source_sample_record_w;
    logic signed [T_SAMPLE_W-1:0]       source_sample_w;
    logic [63:0]                        source_idx_w;
    logic                               source_active_w;
    logic                               source_done_w;
    logic                               source_start_accept_w;
    logic [63:0]                        source_output_accept_count_w;
    logic                               source_config_error_w;
    logic                               source_mem_range_error_w;
    logic                               source_overrun_w;

    logic                               sample_accept_pulse_w;
    logic signed [T_SAMPLE_W-1:0]       accepted_sample_w;
    logic [63:0]                        accepted_sample_idx_w;

    logic                               frame_valid_w;
    logic                               frame_ready_w;
    logic [63:0]                        frame_idx_w;
    logic [63:0]                        frame_trigger_idx_w;
    logic                               frame_boundary_pulse_w;
    logic [63:0]                        scheduler_frame_count_w;
    logic                               scheduler_error_w;

    logic                               frame_sample_valid_w;
    logic                               frame_sample_ready_w;
    logic signed [T_SAMPLE_W-1:0]       frame_sample_w;
    logic [63:0]                        frame_sample_idx_w;
    logic [P-1:0]                       frame_sample_offset_w;
    logic [63:0]                        frame_sample_frame_idx_w;
    logic                               frame_sample_last_w;
    logic                               ring_busy_w;
    logic                               ring_overflow_w;

    logic [63:0]                        trigger_by_frame [0:EXPECTED_FRAMES-1];
    integer unsigned                    cycle_count_q;
    integer unsigned                    source_accept_count_q;
    integer unsigned                    ring_accept_count_q;
    integer unsigned                    frame_request_count_q;
    integer unsigned                    frame_boundary_count_q;
    integer unsigned                    frame_beat_count_q;
    integer unsigned                    frame_complete_count_q;
    integer unsigned                    source_start_accept_count_q;
    integer unsigned                    source_stall_cycle_count_q;
    integer unsigned                    long_frame_stall_cycle_count_q;
    integer unsigned                    expected_extract_frame_q;
    integer unsigned                    expected_extract_offset_q;
    integer unsigned                    post_boundary_accept_count_q;
    integer unsigned                    max_post_boundary_accept_count_q;
    logic                               awaiting_frame_request_q;

    logic                               prior_source_stall_q;
    logic signed [T_SAMPLE_W-1:0]       prior_source_sample_q;
    logic [63:0]                        prior_source_idx_q;
    logic                               prior_frame_stall_q;
    logic signed [T_SAMPLE_W-1:0]       prior_frame_sample_q;
    logic [63:0]                        prior_frame_sample_idx_q;
    logic [P-1:0]                       prior_frame_sample_offset_q;
    logic [63:0]                        prior_frame_sample_frame_idx_q;
    logic                               prior_frame_sample_last_q;

    function automatic logic signed [T_SAMPLE_W-1:0] sample_pattern(
        input logic [63:0] sample_idx
    );
        logic [63:0] value;
        begin
            // Nonzero and non-repeating over this test's accepted-sample range.
            value = (sample_idx % 64'd2047) + 64'd1;
            sample_pattern = $signed(value[T_SAMPLE_W-1:0]);
        end
    endfunction : sample_pattern

    initial begin
        clk = 1'b0;
        forever #5 clk = ~clk;
    end

    initial begin
        rst_n = 1'b0;
        enable_i = 1'b1;
        clear_i = 1'b0;
        clear_sticky_i = 1'b0;
        start_i = 1'b0;
        repeat (8) @(posedge clk);
        // Release reset and drive start away from the DUT sampling edge.
        @(negedge clk);
        rst_n = 1'b1;
        @(negedge clk);
        start_i = 1'b1;
        @(negedge clk);
        start_i = 1'b0;
    end

    // Use the real C0 replay producer. Its internal BRAM is filled after its time-zero
    // initialization and while reset is still asserted, avoiding an external test-vector file
    // while retaining distinctive sample data across the physical ring wrap.
    integer preload_idx;
    initial begin : p_preload_replay
        #1;
        for (preload_idx = 0; preload_idx < TARGET_SAMPLES; preload_idx = preload_idx + 1) begin
            u_bram_replay.x_mem[preload_idx] = sample_pattern(preload_idx);
        end
    end

    trecap_bram_replay_source #(
        .INIT_FILE( "" ),
        .MEM_DEPTH( TARGET_SAMPLES ),
        .INPUT_SAMPLES( TARGET_SAMPLES ),
        .FLUSH_SAMPLES( 0 ),
        .START_ON_RESET_RELEASE( 1'b0 ),
        .RESTART_ALLOWED_WHILE_DONE( 1'b0 )
    ) u_bram_replay (
        .clk( clk ),
        .rst_n( rst_n ),
        .enable_i( enable_i ),
        .start_i( start_i ),
        .clear_i( clear_i ),
        .clear_sticky_i( clear_sticky_i ),
        .sample_ready_i( source_ready_w ),
        .sample_o( source_sample_record_w ),
        .sample_valid_o( source_valid_w ),
        .sample_data_o( source_sample_w ),
        .sample_idx_o( source_idx_w ),
        .active_o( source_active_w ),
        .done_o( source_done_w ),
        .input_phase_o(),
        .flush_phase_o(),
        .start_accept_pulse_o( source_start_accept_w ),
        .start_reject_pulse_o(),
        .output_accept_pulse_o(),
        .last_sample_pulse_o(),
        .done_pulse_o(),
        .next_issue_idx_o(),
        .output_accept_count_o( source_output_accept_count_w ),
        .configured_input_samples_o(),
        .configured_flush_samples_o(),
        .config_error_sticky_o( source_config_error_w ),
        .mem_range_error_sticky_o( source_mem_range_error_w ),
        .replay_overrun_sticky_o( source_overrun_w )
    );

    // Force the first extraction to stop for 720 clocks, then retain periodic backpressure.
    // The pre-fix design accepts all 768 source samples while extraction falls behind and
    // deterministically drops four frames. The fixed design holds the replay output until
    // storage is free.
    assign frame_sample_ready_w =
        !((cycle_count_q >= 180) && (cycle_count_q < 900)) &&
        ((cycle_count_q % 5) != 0);

    trecap_input_ring #(
        .SAMPLE_W( T_SAMPLE_W ),
        .L( L ),
        .DEPTH( 2*L )
    ) u_input_ring (
        .clk( clk ),
        .rst_n( rst_n ),
        .enable_i( enable_i ),
        .clear_i( clear_i ),
        .clear_sticky_i( clear_sticky_i ),
        .sample_valid_i( source_valid_w ),
        .sample_ready_o( source_ready_w ),
        .sample_i( source_sample_record_w.data ),
        .sample_idx_i( source_sample_record_w.sample_idx ),
        .sample_accept_pulse_o( sample_accept_pulse_w ),
        .accepted_sample_o( accepted_sample_w ),
        .accepted_sample_idx_o( accepted_sample_idx_w ),
        .frame_req_valid_i( frame_valid_w ),
        .frame_req_ready_o( frame_ready_w ),
        .frame_req_frame_idx_i( frame_idx_w ),
        .frame_req_trigger_sample_idx_i( frame_trigger_idx_w ),
        .frame_sample_valid_o( frame_sample_valid_w ),
        .frame_sample_ready_i( frame_sample_ready_w ),
        .frame_sample_o( frame_sample_w ),
        .frame_sample_idx_o( frame_sample_idx_w ),
        .frame_sample_offset_o( frame_sample_offset_w ),
        .frame_sample_frame_idx_o( frame_sample_frame_idx_w ),
        .frame_sample_last_o( frame_sample_last_w ),
        .busy_o( ring_busy_w ),
        .overflow_sticky_o( ring_overflow_w )
    );

    trecap_frame_scheduler #(
        .L( L ),
        .H( H )
    ) u_frame_scheduler (
        .clk( clk ),
        .rst_n( rst_n ),
        .enable_i( enable_i ),
        .clear_i( clear_i ),
        .clear_sticky_i( clear_sticky_i ),
        .sample_accept_i( sample_accept_pulse_w ),
        .sample_idx_i( accepted_sample_idx_w ),
        .source_discontinuity_i( 1'b0 ),
        .finite_stream_i( 1'b0 ),
        .active_frame_count_i( 64'd0 ),
        .frame_valid_o( frame_valid_w ),
        .frame_ready_i( frame_ready_w ),
        .frame_idx_o( frame_idx_w ),
        .trigger_sample_idx_o( frame_trigger_idx_w ),
        .frame_boundary_pulse_o( frame_boundary_pulse_w ),
        .frame_count_o( scheduler_frame_count_w ),
        .protocol_error_sticky_o( scheduler_error_w )
    );

    always @(posedge clk or negedge rst_n) begin : p_scoreboard
        longint signed expected_abs_idx;
        logic signed [T_SAMPLE_W-1:0] expected_sample;
        logic [63:0] expected_trigger;

        if (!rst_n) begin
            cycle_count_q          <= 0;
            source_accept_count_q  <= 0;
            ring_accept_count_q    <= 0;
            frame_request_count_q  <= 0;
            frame_boundary_count_q <= 0;
            frame_beat_count_q     <= 0;
            frame_complete_count_q <= 0;
            source_start_accept_count_q <= 0;
            source_stall_cycle_count_q <= 0;
            long_frame_stall_cycle_count_q <= 0;
            expected_extract_frame_q  <= 0;
            expected_extract_offset_q <= 0;
            post_boundary_accept_count_q <= 0;
            max_post_boundary_accept_count_q <= 0;
            awaiting_frame_request_q <= 1'b0;
            prior_source_stall_q   <= 1'b0;
            prior_source_sample_q  <= '0;
            prior_source_idx_q     <= 64'd0;
            prior_frame_stall_q    <= 1'b0;
            prior_frame_sample_q   <= '0;
            prior_frame_sample_idx_q <= 64'd0;
            prior_frame_sample_offset_q <= '0;
            prior_frame_sample_frame_idx_q <= 64'd0;
            prior_frame_sample_last_q <= 1'b0;
        end else begin
            cycle_count_q <= cycle_count_q + 1;

            if ($isunknown({
                source_valid_w,
                source_ready_w,
                sample_accept_pulse_w,
                frame_valid_w,
                frame_ready_w,
                frame_boundary_pulse_w,
                frame_sample_valid_w,
                frame_sample_ready_w,
                ring_overflow_w,
                scheduler_error_w,
                source_active_w,
                source_done_w,
                source_start_accept_w,
                source_config_error_w,
                source_mem_range_error_w,
                source_overrun_w
            })) begin
                $fatal(1, "C0 control signal became X/Z");
            end
            if (source_valid_w &&
                $isunknown({
                    source_sample_record_w,
                    source_sample_w,
                    source_idx_w
                })) begin
                $fatal(1, "BRAM replay source payload became X/Z while valid");
            end
            if ((source_sample_record_w.valid !== source_valid_w) ||
                (source_sample_record_w.data !== source_sample_w) ||
                (source_sample_record_w.sample_idx !== source_idx_w)) begin
                $fatal(1, "BRAM replay struct and breakout outputs diverged");
            end
            if (frame_valid_w &&
                $isunknown({frame_idx_w, frame_trigger_idx_w})) begin
                $fatal(1, "frame request payload became X/Z while valid");
            end
            if (frame_sample_valid_w &&
                $isunknown({
                    frame_sample_w,
                    frame_sample_idx_w,
                    frame_sample_offset_w,
                    frame_sample_frame_idx_w,
                    frame_sample_last_w
                })) begin
                $fatal(1, "frame extractor payload became X/Z while valid");
            end

            if (prior_source_stall_q) begin
                if (!source_valid_w ||
                    (source_sample_record_w.data !== prior_source_sample_q) ||
                    (source_sample_record_w.sample_idx !== prior_source_idx_q)) begin
                    $fatal(1, "C0 source payload changed while ready was low");
                end
            end
            prior_source_stall_q  <= source_valid_w && !source_ready_w;
            prior_source_sample_q <= source_sample_record_w.data;
            prior_source_idx_q    <= source_sample_record_w.sample_idx;

            if (prior_frame_stall_q) begin
                if (!frame_sample_valid_w ||
                    (frame_sample_w !== prior_frame_sample_q) ||
                    (frame_sample_idx_w !== prior_frame_sample_idx_q) ||
                    (frame_sample_offset_w !== prior_frame_sample_offset_q) ||
                    (frame_sample_frame_idx_w !== prior_frame_sample_frame_idx_q) ||
                    (frame_sample_last_w !== prior_frame_sample_last_q)) begin
                    $fatal(1, "frame extractor payload changed while ready was low");
                end
            end
            prior_frame_stall_q <= frame_sample_valid_w && !frame_sample_ready_w;
            prior_frame_sample_q <= frame_sample_w;
            prior_frame_sample_idx_q <= frame_sample_idx_w;
            prior_frame_sample_offset_q <= frame_sample_offset_w;
            prior_frame_sample_frame_idx_q <= frame_sample_frame_idx_w;
            prior_frame_sample_last_q <= frame_sample_last_w;

            if (source_valid_w && !source_ready_w) begin
                source_stall_cycle_count_q <= source_stall_cycle_count_q + 1;
            end
            if ((cycle_count_q >= 180) && (cycle_count_q < 900) &&
                frame_sample_valid_w && !frame_sample_ready_w) begin
                long_frame_stall_cycle_count_q <= long_frame_stall_cycle_count_q + 1;
            end

            if (source_start_accept_w) begin
                source_start_accept_count_q <= source_start_accept_count_q + 1;
            end

            if (source_valid_w && source_ready_w) begin
                if (source_sample_record_w.sample_idx !== source_accept_count_q) begin
                    $fatal(1,
                           "accepted source index gap/duplicate: got=%0d expected=%0d",
                           source_sample_record_w.sample_idx, source_accept_count_q);
                end
                source_accept_count_q <= source_accept_count_q + 1;

                if (((source_accept_count_q + 1) % H) == 0) begin
                    if (awaiting_frame_request_q) begin
                        $fatal(1, "next hop boundary arrived before prior frame request");
                    end
                    awaiting_frame_request_q <= 1'b1;
                    post_boundary_accept_count_q <= 0;
                end else if (awaiting_frame_request_q) begin
                    post_boundary_accept_count_q <= post_boundary_accept_count_q + 1;
                    if ((post_boundary_accept_count_q + 1) >
                        max_post_boundary_accept_count_q) begin
                        max_post_boundary_accept_count_q <=
                            post_boundary_accept_count_q + 1;
                    end
                    if ((post_boundary_accept_count_q + 1) > 1) begin
                        $fatal(1,
                               "more than one look-ahead sample accepted before frame request");
                    end
                end
            end

            if (sample_accept_pulse_w) begin
                if (accepted_sample_idx_w !== ring_accept_count_q) begin
                    $fatal(1,
                           "ring acceptance index gap/duplicate: got=%0d expected=%0d",
                           accepted_sample_idx_w, ring_accept_count_q);
                end
                if (accepted_sample_w !== sample_pattern(accepted_sample_idx_w)) begin
                    $fatal(1, "ring accepted wrong sample at index %0d", accepted_sample_idx_w);
                end
                ring_accept_count_q <= ring_accept_count_q + 1;
            end

            if (frame_valid_w && frame_ready_w) begin
                if (!awaiting_frame_request_q) begin
                    $fatal(1, "frame request arrived without a preceding hop boundary");
                end
                if (frame_request_count_q >= EXPECTED_FRAMES) begin
                    $fatal(1, "unexpected extra frame request idx=%0d", frame_idx_w);
                end
                expected_trigger = ((frame_request_count_q + 1) * H) - 1;
                if (frame_idx_w !== frame_request_count_q) begin
                    $fatal(1,
                           "frame index mismatch: got=%0d expected=%0d",
                           frame_idx_w, frame_request_count_q);
                end
                if (frame_trigger_idx_w !== expected_trigger) begin
                    $fatal(1,
                           "frame trigger mismatch: got=%0d expected=%0d",
                           frame_trigger_idx_w, expected_trigger);
                end
                trigger_by_frame[frame_request_count_q] <= frame_trigger_idx_w;
                frame_request_count_q <= frame_request_count_q + 1;
                awaiting_frame_request_q <= 1'b0;
            end

            if (frame_boundary_pulse_w) begin
                frame_boundary_count_q <= frame_boundary_count_q + 1;
            end

            if (frame_sample_valid_w && frame_sample_ready_w) begin
                if (frame_sample_frame_idx_w >= EXPECTED_FRAMES) begin
                    $fatal(1,
                           "frame extractor emitted unexpected frame idx=%0d",
                           frame_sample_frame_idx_w);
                end
                if (frame_sample_frame_idx_w !== expected_extract_frame_q) begin
                    $fatal(1,
                           "frame extraction order mismatch: got frame=%0d expected frame=%0d",
                           frame_sample_frame_idx_w, expected_extract_frame_q);
                end
                if (frame_sample_offset_w !== expected_extract_offset_q) begin
                    $fatal(1,
                           "frame offset gap/duplicate: frame=%0d got=%0d expected=%0d",
                           frame_sample_frame_idx_w, frame_sample_offset_w,
                           expected_extract_offset_q);
                end

                expected_abs_idx =
                    $signed({1'b0, trigger_by_frame[frame_sample_frame_idx_w]}) -
                    longint'(L - 1) +
                    longint'(frame_sample_offset_w);
                expected_sample =
                    (expected_abs_idx < 0) ? '0 : sample_pattern(expected_abs_idx[63:0]);

                if (frame_sample_idx_w !== expected_abs_idx[63:0]) begin
                    $fatal(1,
                           "frame sample index mismatch: frame=%0d offset=%0d got=%0d expected=%0d",
                           frame_sample_frame_idx_w, frame_sample_offset_w,
                           frame_sample_idx_w, expected_abs_idx);
                end
                if (frame_sample_w !== expected_sample) begin
                    $fatal(1,
                           "frame data mismatch: frame=%0d offset=%0d got=%0d expected=%0d",
                           frame_sample_frame_idx_w, frame_sample_offset_w,
                           frame_sample_w, expected_sample);
                end
                if (frame_sample_last_w !== (frame_sample_offset_w == (L - 1))) begin
                    $fatal(1,
                           "frame last mismatch: frame=%0d offset=%0d last=%0b",
                           frame_sample_frame_idx_w, frame_sample_offset_w,
                           frame_sample_last_w);
                end

                frame_beat_count_q <= frame_beat_count_q + 1;
                if (frame_sample_last_w) begin
                    frame_complete_count_q <= frame_complete_count_q + 1;
                    expected_extract_frame_q <= expected_extract_frame_q + 1;
                    expected_extract_offset_q <= 0;
                end else begin
                    expected_extract_offset_q <= expected_extract_offset_q + 1;
                end
            end

            if (ring_overflow_w) begin
                $fatal(1, "input ring reported a missing/overwritten sample");
            end
            if (scheduler_error_w) begin
                $fatal(1, "frame scheduler reported a dropped or malformed request");
            end
            if (source_config_error_w || source_mem_range_error_w || source_overrun_w) begin
                $fatal(1, "BRAM replay source reported a configuration/protocol error");
            end
        end
    end

    initial begin : p_test_control
        wait (rst_n);
        fork
            begin : p_watchdog
                repeat (WATCHDOG_CYCLES) @(posedge clk);
                $fatal(1,
                       "watchdog: accepted=%0d requests=%0d completed=%0d beats=%0d",
                       source_accept_count_q, frame_request_count_q,
                       frame_complete_count_q, frame_beat_count_q);
            end

            begin : p_completion
                wait (frame_complete_count_q == EXPECTED_FRAMES);
                repeat (5) @(posedge clk);

                if (source_accept_count_q != TARGET_SAMPLES) begin
                    $fatal(1,
                           "source conservation failed: got=%0d expected=%0d",
                           source_accept_count_q, TARGET_SAMPLES);
                end
                if (ring_accept_count_q != TARGET_SAMPLES) begin
                    $fatal(1,
                           "ring conservation failed: got=%0d expected=%0d",
                           ring_accept_count_q, TARGET_SAMPLES);
                end
                if (frame_request_count_q != EXPECTED_FRAMES) begin
                    $fatal(1,
                           "frame request conservation failed: got=%0d expected=%0d",
                           frame_request_count_q, EXPECTED_FRAMES);
                end
                if (frame_boundary_count_q != EXPECTED_FRAMES) begin
                    $fatal(1,
                           "frame boundary conservation failed: got=%0d expected=%0d",
                           frame_boundary_count_q, EXPECTED_FRAMES);
                end
                if (scheduler_frame_count_w !== EXPECTED_FRAMES) begin
                    $fatal(1,
                           "scheduler count mismatch: got=%0d expected=%0d",
                           scheduler_frame_count_w, EXPECTED_FRAMES);
                end
                if (frame_beat_count_q != (EXPECTED_FRAMES * L)) begin
                    $fatal(1,
                           "frame beat conservation failed: got=%0d expected=%0d",
                           frame_beat_count_q, EXPECTED_FRAMES * L);
                end
                if (!source_done_w || source_active_w) begin
                    $fatal(1,
                           "BRAM replay source did not finish cleanly: active=%0b done=%0b",
                           source_active_w, source_done_w);
                end
                if (source_output_accept_count_w !== TARGET_SAMPLES) begin
                    $fatal(1,
                           "BRAM replay acceptance count mismatch: got=%0d expected=%0d",
                           source_output_accept_count_w, TARGET_SAMPLES);
                end
                if (source_start_accept_count_q != 1) begin
                    $fatal(1,
                           "BRAM replay start acceptance mismatch: got=%0d expected=1",
                           source_start_accept_count_q);
                end
                if (awaiting_frame_request_q) begin
                    $fatal(1, "final frame boundary never produced a frame request");
                end
                if (max_post_boundary_accept_count_q != 1) begin
                    $fatal(1,
                           "look-ahead bound was not exercised exactly once: max=%0d",
                           max_post_boundary_accept_count_q);
                end
                if (source_stall_cycle_count_q == 0) begin
                    $fatal(1, "BRAM replay source was never backpressured");
                end
                if (long_frame_stall_cycle_count_q != 720) begin
                    $fatal(1,
                           "directed 720-cycle frame stall was not fully exercised: got=%0d",
                           long_frame_stall_cycle_count_q);
                end

                $display(
                    "C0_FLOW_CONTROL_PASS samples=%0d frames=%0d beats=%0d cycles=%0d",
                    source_accept_count_q, frame_request_count_q,
                    frame_beat_count_q, cycle_count_q
                );
                $finish;
            end
        join_any
        disable fork;
    end

endmodule : tb_trecap_c0_flow_control

`default_nettype wire
