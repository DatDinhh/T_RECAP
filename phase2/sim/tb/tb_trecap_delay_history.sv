// SPDX-License-Identifier: MIT
// File class: [1] hand-written verification RTL.
// Layer: sim/tb/
// Purpose: Directed fail-closed regression for the Phase-2 delayed-x history and metrics stage.

`timescale 1ns/1ps
`default_nettype none

module tb_trecap_delay_history
  import trecap_core_pkg::*;
  import trecap_iface_pkg::*;
();

    localparam int unsigned HISTORY_DEPTH = 1024;
    localparam int unsigned HISTORY_ADDR_W = $clog2(HISTORY_DEPTH);
    localparam int unsigned STRESS_X_SAMPLES = 2304;
    localparam int unsigned STRESS_Y_SAMPLES = STRESS_X_SAMPLES + T_DELAY_D;
    localparam int unsigned RESTART_X_SAMPLES = 64;
    localparam int unsigned RESTART_Y_SAMPLES = RESTART_X_SAMPLES + T_DELAY_D;
    localparam int unsigned WATCHDOG_CYCLES = 100000;

    logic clk;
    logic rst_n;
    logic enable_i;
    logic clear_i;
    logic clear_metrics_i;
    logic clear_sticky_i;

    logic x_valid_i;
    logic x_ready_o;
    logic signed [T_SAMPLE_W-1:0] x_sample_i;
    logic [63:0] x_sample_idx_i;

    logic y_valid_i;
    logic y_ready_o;
    logic signed [T_SAMPLE_W-1:0] y_sample_i;
    logic [63:0] y_sample_idx_i;

    logic y_out_valid_o;
    logic y_out_ready_i;
    trecap_sample_t y_sample_o;
    logic signed [T_SAMPLE_W-1:0] y_sample_data_o;
    logic [63:0] y_sample_idx_o;

    trecap_core_tap_sample_t tap_sample_o;
    logic tap_sample_valid_o;
    logic [63:0] accepted_x_count_o;
    logic [63:0] accepted_y_count_o;
    logic [HISTORY_ADDR_W:0] history_occupancy_o;
    logic history_full_o;
    logic history_empty_o;
    logic busy_o;
    logic [63:0] sum_abs_err_lo_o;
    logic [63:0] sum_sq_err_lo_o;
    logic [15:0] max_abs_err_o;
    logic [31:0] overflow_flags_o;
    logic delay_not_full_sticky_o;
    logic metric_overflow_sticky_o;
    logic protocol_error_sticky_o;
    logic output_backpressure_sticky_o;

    logic force_output_stall_q;
    logic check_epoch_q;
    integer epoch_mode_q;
    logic full_seen_q;
    logic full_backpressure_seen_q;
    logic prior_output_stall_q;
    logic signed [T_SAMPLE_W-1:0] prior_output_data_q;
    logic [63:0] prior_output_idx_q;

    longint unsigned tap_count_q;
    longint unsigned output_count_q;
    longint unsigned expected_sum_abs_q;
    longint unsigned expected_sum_sq_q;
    longint unsigned expected_max_abs_q;
    longint unsigned cycle_count_q;

    longint signed monitor_x_q;
    longint signed monitor_y_q;
    longint signed monitor_err_q;
    longint unsigned monitor_abs_q;

    always #5ns clk = ~clk;
    assign y_out_ready_i = !force_output_stall_q;

    function automatic logic signed [T_SAMPLE_W-1:0] x_value(
        input longint unsigned idx,
        input integer mode
    );
        longint signed value;
        begin
            if (mode == 0) begin
                value = (idx == 0) ? -2048 : 0;
            end else begin
                value = longint'((idx * 37 + 11) % 3001) - 1500;
            end
            x_value = T_SAMPLE_W'(value);
        end
    endfunction : x_value

    function automatic logic signed [T_SAMPLE_W-1:0] y_value(
        input longint unsigned idx,
        input integer mode
    );
        longint signed value;
        begin
            if (mode == 0) begin
                value = (idx == T_DELAY_D) ? 2047 : 0;
            end else begin
                value = longint'((idx * 19 + 7) % 2801) - 1400;
            end
            y_value = T_SAMPLE_W'(value);
        end
    endfunction : y_value

    task automatic drive_x_range(
        input longint unsigned first_idx,
        input longint unsigned count,
        input integer mode
    );
        longint unsigned idx;
        begin
            for (idx = first_idx; idx < (first_idx + count); idx = idx + 1) begin
                @(negedge clk);
                x_valid_i = 1'b1;
                x_sample_i = x_value(idx, mode);
                x_sample_idx_i = idx;
                do begin
                    @(posedge clk);
                end while (!x_ready_o);
            end
            @(negedge clk);
            x_valid_i = 1'b0;
            x_sample_i = '0;
            x_sample_idx_i = 64'd0;
        end
    endtask : drive_x_range

    task automatic drive_y_range(
        input longint unsigned first_idx,
        input longint unsigned count,
        input integer mode
    );
        longint unsigned idx;
        begin
            for (idx = first_idx; idx < (first_idx + count); idx = idx + 1) begin
                @(negedge clk);
                y_valid_i = 1'b1;
                y_sample_i = y_value(idx, mode);
                y_sample_idx_i = idx;
                do begin
                    @(posedge clk);
                end while (!y_ready_o);
            end
            @(negedge clk);
            y_valid_i = 1'b0;
            y_sample_i = '0;
            y_sample_idx_i = 64'd0;
        end
    endtask : drive_y_range

    task automatic pulse_clear;
        begin
            @(negedge clk);
            clear_i = 1'b1;
            @(posedge clk);
            @(negedge clk);
            clear_i = 1'b0;
            repeat (2) @(posedge clk);
        end
    endtask : pulse_clear

    task automatic start_checked_epoch(input integer mode);
        begin
            @(negedge clk);
            epoch_mode_q = mode;
            tap_count_q = 0;
            output_count_q = 0;
            expected_sum_abs_q = 0;
            expected_sum_sq_q = 0;
            expected_max_abs_q = 0;
            full_seen_q = 1'b0;
            full_backpressure_seen_q = 1'b0;
            prior_output_stall_q = 1'b0;
            check_epoch_q = 1'b1;
        end
    endtask : start_checked_epoch

    task automatic finish_checked_epoch(
        input longint unsigned expected_x_count,
        input longint unsigned expected_y_count,
        input logic expect_backpressure
    );
        begin
            wait ((accepted_x_count_o == expected_x_count) &&
                  (accepted_y_count_o == expected_y_count) &&
                  (tap_count_q == expected_y_count) &&
                  (output_count_q == expected_y_count) &&
                  history_empty_o && !busy_o);
            repeat (3) @(posedge clk);

            if (history_occupancy_o != 0) begin
                $fatal(1, "C0_DELAY_HISTORY_MISMATCH final occupancy=%0d",
                       history_occupancy_o);
            end
            if ((sum_abs_err_lo_o != expected_sum_abs_q) ||
                (sum_sq_err_lo_o != expected_sum_sq_q) ||
                (max_abs_err_o != expected_max_abs_q[15:0])) begin
                $fatal(
                    1,
                    "C0_DELAY_HISTORY_MISMATCH metrics abs=%0d/%0d sq=%0d/%0d max=%0d/%0d",
                    sum_abs_err_lo_o, expected_sum_abs_q,
                    sum_sq_err_lo_o, expected_sum_sq_q,
                    max_abs_err_o, expected_max_abs_q
                );
            end
            if (delay_not_full_sticky_o || metric_overflow_sticky_o ||
                protocol_error_sticky_o || (overflow_flags_o != 0)) begin
                $fatal(1, "C0_DELAY_HISTORY_MISMATCH unexpected status flags");
            end
            if (expect_backpressure && !output_backpressure_sticky_o) begin
                $fatal(1, "C0_DELAY_HISTORY_MISMATCH output stall was not recorded");
            end
            @(negedge clk);
            check_epoch_q = 1'b0;
        end
    endtask : finish_checked_epoch

    trecap_delay_error_metrics #(
        .SAMPLE_W( T_SAMPLE_W ),
        .DELAY_D( T_DELAY_D ),
        .ERR_W( 16 ),
        .DEPTH( HISTORY_DEPTH )
    ) dut (
        .clk( clk ),
        .rst_n( rst_n ),
        .enable_i( enable_i ),
        .clear_i( clear_i ),
        .clear_metrics_i( clear_metrics_i ),
        .clear_sticky_i( clear_sticky_i ),
        .x_valid_i( x_valid_i ),
        .x_ready_o( x_ready_o ),
        .x_sample_i( x_sample_i ),
        .x_sample_idx_i( x_sample_idx_i ),
        .y_valid_i( y_valid_i ),
        .y_ready_o( y_ready_o ),
        .y_sample_i( y_sample_i ),
        .y_sample_idx_i( y_sample_idx_i ),
        .y_out_valid_o( y_out_valid_o ),
        .y_out_ready_i( y_out_ready_i ),
        .y_sample_o( y_sample_o ),
        .y_sample_data_o( y_sample_data_o ),
        .y_sample_idx_o( y_sample_idx_o ),
        .tap_sample_o( tap_sample_o ),
        .tap_sample_valid_o( tap_sample_valid_o ),
        .accepted_x_count_o( accepted_x_count_o ),
        .accepted_y_count_o( accepted_y_count_o ),
        .history_occupancy_o( history_occupancy_o ),
        .history_full_o( history_full_o ),
        .history_empty_o( history_empty_o ),
        .busy_o( busy_o ),
        .sum_abs_err_lo_o( sum_abs_err_lo_o ),
        .sum_sq_err_lo_o( sum_sq_err_lo_o ),
        .max_abs_err_o( max_abs_err_o ),
        .overflow_flags_o( overflow_flags_o ),
        .delay_not_full_sticky_o( delay_not_full_sticky_o ),
        .metric_overflow_sticky_o( metric_overflow_sticky_o ),
        .protocol_error_sticky_o( protocol_error_sticky_o ),
        .output_backpressure_sticky_o( output_backpressure_sticky_o )
    );

    always @(posedge clk) begin : p_monitor
        if (!rst_n || clear_i) begin
            cycle_count_q = 0;
            prior_output_stall_q = 1'b0;
        end else begin
            cycle_count_q = cycle_count_q + 1;
            if (cycle_count_q > WATCHDOG_CYCLES) begin
                $fatal(1, "C0_DELAY_HISTORY_MISMATCH watchdog timeout");
            end

            if (history_full_o) begin
                full_seen_q = 1'b1;
            end
            if (history_full_o && x_valid_i && !x_ready_o) begin
                full_backpressure_seen_q = 1'b1;
            end
            if (history_occupancy_o > HISTORY_DEPTH) begin
                $fatal(1, "C0_DELAY_HISTORY_MISMATCH occupancy exceeded depth");
            end
            if (history_full_o && history_empty_o) begin
                $fatal(1, "C0_DELAY_HISTORY_MISMATCH full and empty simultaneously");
            end

            if (prior_output_stall_q) begin
                if (!y_out_valid_o ||
                    (y_sample_data_o !== prior_output_data_q) ||
                    (y_sample_idx_o !== prior_output_idx_q)) begin
                    $fatal(1, "C0_DELAY_HISTORY_MISMATCH output changed while stalled");
                end
            end
            prior_output_stall_q = y_out_valid_o && !y_out_ready_i;
            prior_output_data_q = y_sample_data_o;
            prior_output_idx_q = y_sample_idx_o;

            if (check_epoch_q && tap_sample_o.valid) begin
                if (!tap_sample_valid_o) begin
                    $fatal(1, "C0_DELAY_HISTORY_MISMATCH tap valid outputs disagree");
                end
                if (tap_sample_o.sample_idx != tap_count_q) begin
                    $fatal(1, "C0_DELAY_HISTORY_MISMATCH tap index=%0d expected=%0d",
                           tap_sample_o.sample_idx, tap_count_q);
                end
                monitor_y_q = y_value(tap_count_q, epoch_mode_q);
                monitor_x_q = (tap_count_q < T_DELAY_D) ?
                              0 : x_value(tap_count_q - T_DELAY_D, epoch_mode_q);
                monitor_err_q = monitor_x_q - monitor_y_q;
                monitor_abs_q = (monitor_err_q < 0) ?
                                -monitor_err_q : monitor_err_q;

                if (tap_sample_o.x_delayed !== T_SAMPLE_W'(monitor_x_q)) begin
                    $fatal(1, "C0_DELAY_HISTORY_MISMATCH delayed x at y[%0d]",
                           tap_count_q);
                end
                if (tap_sample_o.y_out !== T_SAMPLE_W'(monitor_y_q)) begin
                    $fatal(1, "C0_DELAY_HISTORY_MISMATCH tap y at y[%0d]",
                           tap_count_q);
                end
                if (tap_sample_o.error_i16 !== 16'(monitor_err_q)) begin
                    $fatal(1, "C0_DELAY_HISTORY_MISMATCH error at y[%0d]",
                           tap_count_q);
                end

                expected_sum_abs_q = expected_sum_abs_q + monitor_abs_q;
                expected_sum_sq_q =
                    expected_sum_sq_q + (monitor_abs_q * monitor_abs_q);
                if (monitor_abs_q > expected_max_abs_q) begin
                    expected_max_abs_q = monitor_abs_q;
                end
                tap_count_q = tap_count_q + 1;
            end

            if (check_epoch_q && y_out_valid_o && y_out_ready_i) begin
                if (y_sample_idx_o != output_count_q) begin
                    $fatal(1, "C0_DELAY_HISTORY_MISMATCH output index=%0d expected=%0d",
                           y_sample_idx_o, output_count_q);
                end
                if (y_sample_data_o !== y_value(output_count_q, epoch_mode_q)) begin
                    $fatal(1, "C0_DELAY_HISTORY_MISMATCH output data at y[%0d]",
                           output_count_q);
                end
                output_count_q = output_count_q + 1;
            end
        end
    end

    initial begin : p_test
        clk = 1'b0;
        rst_n = 1'b0;
        enable_i = 1'b0;
        clear_i = 1'b0;
        clear_metrics_i = 1'b0;
        clear_sticky_i = 1'b0;
        x_valid_i = 1'b0;
        x_sample_i = '0;
        x_sample_idx_i = 64'd0;
        y_valid_i = 1'b0;
        y_sample_i = '0;
        y_sample_idx_i = 64'd0;
        force_output_stall_q = 1'b0;
        check_epoch_q = 1'b0;
        epoch_mode_q = 0;
        full_seen_q = 1'b0;
        full_backpressure_seen_q = 1'b0;
        prior_output_stall_q = 1'b0;
        tap_count_q = 0;
        output_count_q = 0;
        expected_sum_abs_q = 0;
        expected_sum_sq_q = 0;
        expected_max_abs_q = 0;
        cycle_count_q = 0;

        repeat (5) @(posedge clk);
        @(negedge clk);
        rst_n = 1'b1;
        enable_i = 1'b1;
        repeat (2) @(posedge clk);

        if (!history_empty_o || busy_o || (accepted_x_count_o != 0) ||
            (accepted_y_count_o != 0) || y_out_valid_o) begin
            $fatal(1, "C0_DELAY_HISTORY_MISMATCH reset state");
        end

        // Startup zero extension and normal producer lag: y[384] must wait without raising a
        // fault until x[0] exists, then it must use the exact extreme value x[0]=-2048.
        start_checked_epoch(0);
        drive_y_range(0, T_DELAY_D, 0);
        wait ((accepted_y_count_o == T_DELAY_D) &&
              (tap_count_q == T_DELAY_D) &&
              (output_count_q == T_DELAY_D));
        @(negedge clk);
        y_valid_i = 1'b1;
        y_sample_i = y_value(T_DELAY_D, 0);
        y_sample_idx_i = T_DELAY_D;
        repeat (8) begin
            @(posedge clk);
            if (y_ready_o || (accepted_y_count_o != T_DELAY_D) ||
                delay_not_full_sticky_o || protocol_error_sticky_o) begin
                $fatal(1, "C0_DELAY_HISTORY_MISMATCH y[D] did not wait cleanly for x[0]");
            end
        end
        fork
            drive_x_range(0, 1, 0);
            begin
                do begin
                    @(posedge clk);
                end while (!y_ready_o);
                @(negedge clk);
                y_valid_i = 1'b0;
                y_sample_i = '0;
                y_sample_idx_i = 64'd0;
            end
        join
        finish_checked_epoch(1, T_DELAY_D + 1, 1'b0);
        if ((sum_abs_err_lo_o != 64'd4095) ||
            (sum_sq_err_lo_o != 64'd16769025) ||
            (max_abs_err_o != 16'd4095)) begin
            $fatal(1, "C0_DELAY_HISTORY_MISMATCH extreme arithmetic");
        end

        // A malformed first x index must never handshake. Generic sticky clear cannot unlock or
        // hide the hard alignment fault; only a full clear starts a new epoch.
        pulse_clear();
        @(negedge clk);
        x_valid_i = 1'b1;
        x_sample_i = 12'sd1;
        x_sample_idx_i = 64'd1;
        repeat (2) @(posedge clk);
        if (x_ready_o || !protocol_error_sticky_o || !busy_o) begin
            $fatal(1, "C0_DELAY_HISTORY_MISMATCH bad x index was not fail-stopped");
        end
        @(negedge clk);
        clear_sticky_i = 1'b1;
        @(posedge clk);
        @(negedge clk);
        clear_sticky_i = 1'b0;
        repeat (1) @(posedge clk);
        if (x_ready_o || !protocol_error_sticky_o || !busy_o) begin
            $fatal(1, "C0_DELAY_HISTORY_MISMATCH sticky clear hid hard fault");
        end
        @(negedge clk);
        x_valid_i = 1'b0;
        pulse_clear();

        // More than two address wraps, a completely full 1,024-entry history, and a long public
        // output stall. Full history must backpressure x for one cycle before reusing a freed slot.
        start_checked_epoch(1);
        force_output_stall_q = 1'b1;
        fork
            drive_x_range(0, STRESS_X_SAMPLES, 1);
            drive_y_range(0, STRESS_Y_SAMPLES, 1);
            begin
                wait (history_full_o && y_out_valid_o);
                repeat (41) @(posedge clk);
                if (!full_backpressure_seen_q) begin
                    $fatal(1, "C0_DELAY_HISTORY_MISMATCH full history did not backpressure x");
                end
                @(negedge clk);
                force_output_stall_q = 1'b0;
            end
        join
        finish_checked_epoch(STRESS_X_SAMPLES, STRESS_Y_SAMPLES, 1'b1);
        if (!full_seen_q || !full_backpressure_seen_q) begin
            $fatal(1, "C0_DELAY_HISTORY_MISMATCH wrap/full coverage missing");
        end

        // Clear with retained history and a stalled public output, then restart from index zero.
        pulse_clear();
        check_epoch_q = 1'b0;
        force_output_stall_q = 1'b1;
        fork : p_midrun_drivers
            drive_x_range(0, 200, 1);
            drive_y_range(0, 200, 1);
        join_none
        wait ((accepted_x_count_o >= 64) && y_out_valid_o &&
              (history_occupancy_o != 0));
        disable p_midrun_drivers;
        @(negedge clk);
        x_valid_i = 1'b0;
        y_valid_i = 1'b0;
        pulse_clear();
        force_output_stall_q = 1'b0;
        if (!history_empty_o || busy_o || y_out_valid_o ||
            (accepted_x_count_o != 0) || (accepted_y_count_o != 0) ||
            (sum_abs_err_lo_o != 0) || (sum_sq_err_lo_o != 0) ||
            (max_abs_err_o != 0)) begin
            $fatal(1, "C0_DELAY_HISTORY_MISMATCH midrun clear did not reset epoch");
        end

        // clear_metrics is a one-cycle admission barrier: a held y token is neither counted nor
        // silently omitted from the new metric epoch.
        @(negedge clk);
        clear_metrics_i = 1'b1;
        y_valid_i = 1'b1;
        y_sample_i = y_value(0, 1);
        y_sample_idx_i = 64'd0;
        @(posedge clk);
        if (y_ready_o || (accepted_y_count_o != 0)) begin
            $fatal(1, "C0_DELAY_HISTORY_MISMATCH clear_metrics accepted a y token");
        end
        @(negedge clk);
        clear_metrics_i = 1'b0;
        y_valid_i = 1'b0;

        start_checked_epoch(1);
        fork
            drive_x_range(0, RESTART_X_SAMPLES, 1);
            drive_y_range(0, RESTART_Y_SAMPLES, 1);
        join
        finish_checked_epoch(RESTART_X_SAMPLES, RESTART_Y_SAMPLES, 1'b0);

        $display(
            "C0_DELAY_HISTORY_PASS depth=%0d D=%0d wraps=%0d stress_x=%0d stress_y=%0d restart_y=%0d",
            HISTORY_DEPTH, T_DELAY_D, 2, STRESS_X_SAMPLES,
            STRESS_Y_SAMPLES, RESTART_Y_SAMPLES
        );
        $finish;
    end

endmodule : tb_trecap_delay_history

`default_nettype wire
