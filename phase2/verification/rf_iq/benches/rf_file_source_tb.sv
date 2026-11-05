// SPDX-License-Identifier: MIT
// Compare the file wrapper with a separately instantiated raw adapter.
// Numerical correctness of that adapter is tested by its independent scoreboard.
`timescale 1ns/1ps
`default_nettype none
module rf_file_source_tb;
    integer checker_done=0;
    logic clk = 0;
    always #5 clk = ~clk;
    logic rst_n = 0, clear_i = 0, start_valid_i = 0;
    logic start_ready_o, iq_ready_o, iq_valid_i = 0;
    logic [31:0] pair_count_i = 0;
    logic [1:0] gain_shift_i = 0;
    logic [7:0] iq_i_i = 0, iq_q_i = 0;
    logic sample_valid_o, sample_ready_i = 0;
    logic signed [11:0] sample_data_o;
    logic [31:0] sample_index_o;
    logic sample_last_o, sample_clipped_o, busy_o, done_o, config_error_o;
    logic [31:0] input_count_o, output_count_o, clip_count_o;
    logic clip_sticky_o;
    logic [31:0] valid_sample_count_o, adapter_output_count_o;
    logic raw_start_ready, raw_iq_ready, raw_valid, raw_last, raw_clipped;
    logic signed [11:0] raw_data;
    logic [31:0] raw_index;
    logic raw_config_error;
    integer expected_pairs = 0, accepted_pairs = 0, accepted_samples = 0;
    integer checked_samples = 0, transactions = 0, aborted = 0;
    integer clip_observed = 0, stall_cycles = 0, cycle_number = 0;
    bit checking = 0, holding = 0, iq_holding = 0;
    logic [45:0] held_payload;
    logic [31:0] rng = 32'h51fd182b;

    trecap_rf_file_source #(.TRANSACTION_SAMPLES(64)) dut (.*);
    trecap_rf_iq_adapter #(.MAX_PAIRS(16)) raw (
        .clk(clk), .rst_n(rst_n), .clear_i(clear_i),
        .start_valid_i(start_valid_i), .start_ready_o(raw_start_ready),
        .pair_count_i(pair_count_i), .gain_shift_i(gain_shift_i),
        .iq_valid_i(iq_valid_i), .iq_ready_o(raw_iq_ready),
        .iq_i_i(iq_i_i), .iq_q_i(iq_q_i),
        .sample_valid_o(raw_valid), .sample_ready_i(sample_ready_i),
        .sample_data_o(raw_data), .sample_index_o(raw_index),
        .sample_last_o(raw_last), .sample_clipped_o(raw_clipped),
        .busy_o(), .done_o(), .config_error_o(raw_config_error),
        .input_count_o(), .output_count_o(), .clip_count_o(), .clip_sticky_o()
    );

    always @(posedge clk) begin
        if (!rst_n || clear_i) begin
            holding = 0;
            iq_holding = 0;
        end else if (checking) begin
            iq_holding = iq_valid_i && !iq_ready_o;
            if (holding && (!sample_valid_o ||
                {sample_data_o, sample_index_o, sample_last_o, sample_clipped_o} !== held_payload))
                $fatal(1, "Wrapper changed stalled output");
            holding = sample_valid_o && !sample_ready_i;
            if (holding) begin
                held_payload = {sample_data_o, sample_index_o, sample_last_o, sample_clipped_o};
                stall_cycles = stall_cycles + 1;
            end
            if (accepted_pairs < expected_pairs && iq_ready_o !== raw_iq_ready)
                $fatal(1, "Wrapper changed IQ admission");
            if (iq_valid_i && iq_ready_o) accepted_pairs = accepted_pairs + 1;
            if (sample_valid_o && sample_ready_i) begin
                if (sample_index_o !== accepted_samples || sample_last_o !== (accepted_samples == 63))
                    $fatal(1, "Index or transaction last mismatch at %0d", accepted_samples);
                if (accepted_samples < expected_pairs * 4) begin
                    if (!raw_valid || sample_data_o !== raw_data ||
                        sample_index_o !== raw_index || sample_clipped_o !== raw_clipped ||
                        raw_last !== (accepted_samples == expected_pairs * 4 - 1))
                        $fatal(1, "RF prefix differs from raw adapter at %0d", accepted_samples);
                end else if (raw_valid || sample_data_o !== 12'sd0 || sample_clipped_o)
                    $fatal(1, "Transaction padding is not exact zero");
                if (sample_clipped_o) clip_observed = clip_observed + 1;
                accepted_samples = accepted_samples + 1;
                checked_samples = checked_samples + 1;
            end
        end
    end

    task automatic launch(input integer pairs, input integer gain);
        begin
            @(negedge clk);
            if (!start_ready_o || !raw_start_ready) $fatal(1, "Start not ready");
            pair_count_i = pairs;
            gain_shift_i = gain;
            start_valid_i = 1;
            accepted_pairs = 0;
            accepted_samples = 0;
            clip_observed = 0;
            expected_pairs = pairs;
            checking = 1;
            @(posedge clk); #1;
            if (!busy_o || valid_sample_count_o !== pairs * 4)
                $fatal(1, "Valid start was not latched");
            @(negedge clk);
            start_valid_i = 0;
            // Changing pins after admission must not change the transaction.
            pair_count_i = 0;
            gain_shift_i = ~gain;
        end
    endtask

    task automatic feed_cycle;
        begin
            @(negedge clk);
            rng = {rng[30:0], rng[31] ^ rng[21] ^ rng[1] ^ rng[0]};
            cycle_number = cycle_number + 1;
            // Burst stalls plus random stalls exercise payload stability.
            sample_ready_i = rng[0] && ((cycle_number % 127) >= 23);
            if (!iq_holding) begin
                iq_valid_i = accepted_pairs < expected_pairs && rng[2];
                iq_i_i = (accepted_pairs * 97 + 11) & 255;
                iq_q_i = (accepted_pairs * 53 + 211) & 255;
            end
            @(posedge clk); #1;
        end
    endtask

    task automatic finish_case;
        integer cycles;
        begin
            cycles = 0;
            while (!done_o && cycles < 30000) begin
                feed_cycle();
                cycles = cycles + 1;
            end
            if (!done_o || busy_o || accepted_samples != 64 ||
                accepted_pairs != expected_pairs || output_count_o != 64 ||
                adapter_output_count_o != expected_pairs * 4 ||
                input_count_o != expected_pairs || clip_count_o != clip_observed ||
                clip_sticky_o != (clip_observed != 0) || config_error_o)
                $fatal(1, "Wrapper final counters/completion mismatch");
            @(negedge clk);
            iq_valid_i = 0;
            sample_ready_i = 1;
            @(posedge clk); #1;
            if (done_o || sample_valid_o) $fatal(1, "Completion not a single pulse");
            checking = 0;
            transactions = transactions + 1;
        end
    endtask

    task automatic abort_case;
        begin
            @(negedge clk);
            clear_i = 1;
            #1;
            if (start_ready_o || iq_ready_o || sample_valid_o)
                $fatal(1, "Handshake remained enabled during clear");
            @(posedge clk); #1;
            if (busy_o || done_o || output_count_o || input_count_o ||
                adapter_output_count_o || valid_sample_count_o || clip_count_o || clip_sticky_o)
                $fatal(1, "Abort did not clear transaction");
            @(negedge clk);
            checking = 0;
            iq_valid_i = 0;
            clear_i = 0;
            aborted = aborted + 1;
        end
    endtask

    task automatic reject_case(input integer bad_count);
        begin
            @(negedge clk);
            pair_count_i = bad_count;
            start_valid_i = 1;
            @(posedge clk); #1;
            if (!config_error_o || busy_o || iq_ready_o || sample_valid_o || start_ready_o)
                $fatal(1, "Invalid length not rejected");
            @(negedge clk);
            start_valid_i = 0;
            clear_i = 1;
            @(posedge clk); #1;
            @(negedge clk);
            clear_i = 0;
        end
    endtask

    initial begin
        repeat (3) @(posedge clk);
        @(negedge clk); rst_n = 1;
        launch(1, 2); finish_case();
        launch(9, 3); finish_case();
        launch(16, 1); finish_case();
        launch(16, 2);
        repeat (31) feed_cycle();
        abort_case();
        launch(1, 2);
        while (accepted_samples < 8) feed_cycle();
        abort_case();
        reject_case(0);
        reject_case(17);
        launch(9, 0); finish_case();
        if (stall_cycles == 0) $fatal(1, "Backpressure coverage missing");
        checker_done=1;
        $display("RF_FILE_SOURCE_PASS completed=%0d aborted=%0d checked_samples=%0d stalled_cycles=%0d", transactions, aborted, checked_samples, stall_cycles);
        $finish;
    end
    initial begin
        #5000000;
        $fatal(1, "Wrapper test timeout");
    end
endmodule
`default_nettype wire
