// SPDX-License-Identifier: MIT
// Simulator capability probe. Deliberate failures qualify the harness.
`timescale 1ns/1ps
`default_nettype none

module verification_environment_probe;
    import trecap_core_pkg::*;
    typedef struct packed {
        logic [55:0] threshold;
        logic signed [16:0] coefficient;
    } probe_payload_t;
    logic clk = 0;
    logic reset_n = 0;
    logic valid = 0;
    logic ready = 0;
    logic [63:0] count;
    logic [7:0] unknown_value;
    logic [63:0] input_words [0:1];
    probe_payload_t payload;
    string mode;
    string trace_path;
    string input_path;
    integer trace_file;
    integer cycles = 0;

    always #5 clk = ~clk;
    always @(posedge clk) begin
        cycles <= cycles + 1;
        if (!reset_n) count <= 0;
        else if (valid && ready) count <= count + 1;
    end

    initial begin
        if (!$value$plusargs("MODE=%s", mode)) mode = "positive";
        if (!$value$plusargs("TRACE=%s", trace_path))
            $fatal(1, "ENV_SETUP_MISSING_TRACE");
        if (!$value$plusargs("INPUT=%s", input_path))
            $fatal(1, "ENV_SETUP_MISSING_INPUT");
        if (T_FFT_L != 256 || T_HOP_H != 128) $fatal(1, "ENV_PACKAGE_CONSTANT");
        $readmemh(input_path, input_words);
        if (input_words[0] !== 64'hfedcba9876543210 ||
            input_words[1] !== 64'h8000000000000001)
            $fatal(1, "ENV_INPUT_FILE_MISMATCH");
        if (!$isunknown(unknown_value)) $fatal(1, "ENV_X_SEMANTICS");
        unknown_value = 'z;
        if (!$isunknown(unknown_value)) $fatal(1, "ENV_Z_SEMANTICS");
        payload.threshold = 56'hffffffffffffff;
        payload.coefficient = 17'sd32768;
        if ($signed(payload.coefficient) != 32768)
            $fatal(1, "ENV_POSITIVE_COEFFICIENT");
        payload.coefficient = -17'sd32768;
        @(posedge clk);
        #1;
        if (count !== 0) $fatal(1, "ENV_RESET_NBA");
        @(negedge clk);
        reset_n = 1;
        valid = 1;
        ready = 0;
        repeat (2) begin
            @(posedge clk);
            if (count !== 0) $fatal(1, "ENV_STALLED_ACCEPTANCE");
            #1;
        end
        @(negedge clk);
        ready = 1;
        @(posedge clk);
        if (count !== 0) $fatal(1, "ENV_PRE_EDGE_PHASE");
        #1;
        if (count !== 1) $fatal(1, "ENV_POST_UPDATE_PHASE");
        @(posedge clk);
        #1;
        if (count !== 2) $fatal(1, "ENV_IDENTICAL_CONSECUTIVE_BEATS");
        @(negedge clk);
        valid = 0;
        if (mode == "assert") begin
            assert (count == 99) else $error("ENV_EXPECTED_ASSERT");
        end
        else if (mode == "error") $error("ENV_EXPECTED_ERROR");
        else if (mode == "fatal") $fatal(1, "ENV_EXPECTED_FATAL");
        else if (mode == "x") begin
            unknown_value = 'x;
            if ($isunknown(unknown_value)) $fatal(1, "ENV_EXPECTED_X_REJECT");
        end
        else if (mode == "z") begin
            unknown_value = 'z;
            if ($isunknown(unknown_value)) $fatal(1, "ENV_EXPECTED_Z_REJECT");
        end
        else if (mode == "sim_timeout") begin
            repeat (10) @(posedge clk);
            $fatal(1, "ENV_EXPECTED_CYCLE_WATCHDOG");
        end
        else if (mode == "missing_completion") begin
            $finish;
        end
        else if (mode == "host_timeout") begin
            forever @(posedge clk);
        end
        else if (mode != "positive") $fatal(1, "ENV_SETUP_UNKNOWN_MODE");

        trace_file = $fopen(trace_path, "w");
        if (!trace_file) $fatal(1, "ENV_TRACE_OPEN_FAILED");
        $fdisplay(trace_file, "TRECAP_ENV_TRACE_V1");
        $fdisplay(trace_file, "payload %016h %014h %0d",
                  input_words[0], payload.threshold, $signed(payload.coefficient));
        $fdisplay(trace_file, "accepts %0d", count);
        $fdisplay(trace_file, "complete");
        $fclose(trace_file);
        $display("TRECAP_ENV_COMPLETED");
        $finish;
    end
endmodule
`default_nettype wire
