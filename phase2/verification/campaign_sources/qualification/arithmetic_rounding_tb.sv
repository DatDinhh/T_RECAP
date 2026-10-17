// SPDX-License-Identifier: MIT
// Independent vector-driven checks of the production round/saturate primitive.
`timescale 1ns/1ps
`default_nettype none

module arithmetic_rounding_tb;
    import trecap_math_pkg::*;
    trecap_math_swide_t helper_result;
    integer helper_shift;
    logic signed [63:0] value;
    wire signed [11:0] actual [0:3];
    wire hi [0:3], lo [0:3], any_sat [0:3];
    logic [11:0] expected [0:3];
    integer flags [0:3];
    string vector_path, trace_path, extra;
    integer fd, out_fd, count, parsed, rows, i;
    bit inject_helper_error;

    for (genvar g = 0; g < 4; g++) begin : shifts
        localparam integer SHIFT_VALUE = g == 0 ? 0 : (g == 1 ? 1 : (g == 2 ? 4 : 15));
        trecap_round_sat #(.IN_W(64), .OUT_W(12), .SHIFT(SHIFT_VALUE)) dut (
            .value_i(value), .value_o(actual[g]), .sat_hi_o(hi[g]),
            .sat_lo_o(lo[g]), .sat_any_o(any_sat[g])
        );
    end

    initial begin
        inject_helper_error = $test$plusargs("INJECT_HELPER_ERROR");
        if (!$value$plusargs("VECTORS=%s", vector_path) ||
            !$value$plusargs("TRACE=%s", trace_path)) $fatal(1, "ROUND_SETUP");
        fd = $fopen(vector_path, "r");
        out_fd = $fopen(trace_path, "w");
        if (!fd || !out_fd) $fatal(1, "ROUND_FILE_OPEN");
        parsed = $fscanf(fd, "%d", count);
        if (parsed != 1 || count < 1 || count > 100000) $fatal(1, "ROUND_BAD_COUNT");
        $fdisplay(out_fd, "TRECAP_ROUND_TRACE_V1 %0d", count);
        for (rows = 0; rows < count; rows++) begin
            parsed = $fscanf(fd, "%h %h %d %h %d %h %d %h %d",
                value, expected[0], flags[0], expected[1], flags[1],
                expected[2], flags[2], expected[3], flags[3]);
            if (parsed != 9) $fatal(1, "ROUND_TRUNCATED row=%0d", rows);
            #2;
            if (trecap_sgn(trecap_math_swide_t'(value)) != (value[63] ? -1 : (value == 0 ? 0 : 1)))
                $fatal(1, "ROUND_HELPER_SIGN row=%0d", rows);
            if (trecap_abs_mag(trecap_math_swide_t'(value)) !==
                (value[63] ? trecap_math_uwide_t'(-trecap_math_swide_t'(value)) : trecap_math_uwide_t'(value)))
                $fatal(1, "ROUND_HELPER_ABS row=%0d", rows);
            if (trecap_asr(trecap_math_swide_t'(value), 128) !==
                (value[63] ? trecap_math_swide_t'(-1) : trecap_math_swide_t'(0)))
                $fatal(1, "ROUND_HELPER_ASR row=%0d", rows);
            for (i = 0; i < 4; i++) begin
                if (actual[i] !== expected[i] ||
                    hi[i] !== ((flags[i] & 1) != 0) ||
                    lo[i] !== ((flags[i] & 2) != 0) ||
                    any_sat[i] !== (flags[i] != 0)) begin
                    $fatal(1, "ROUND_MISMATCH row=%0d shift_slot=%0d input=%h actual=%h expected=%h hi=%b lo=%b any=%b",
                        rows, i, value, actual[i], expected[i], hi[i], lo[i], any_sat[i]);
                end
                helper_shift = i == 0 ? 0 : (i == 1 ? 1 : (i == 2 ? 4 : 15));
                helper_result = trecap_sat_signed(trecap_rnd_shr(trecap_math_swide_t'(value), helper_shift), 12);
                if (inject_helper_error && rows == 0 && i == 0)
                    helper_result = helper_result ^ trecap_math_swide_t'(1);
                if (helper_result !== trecap_math_swide_t'($signed(expected[i])))
                    $fatal(1, "ROUND_HELPER_MISMATCH row=%0d shift_slot=%0d", rows, i);
            end
            $fdisplay(out_fd, "%016h %03h %0d %03h %0d %03h %0d %03h %0d", value,
                actual[0], (lo[0]*2)+hi[0], actual[1], (lo[1]*2)+hi[1],
                actual[2], (lo[2]*2)+hi[2], actual[3], (lo[3]*2)+hi[3]);
        end
        parsed = $fscanf(fd, "%s", extra);
        if (parsed == 1) $fatal(1, "ROUND_EXTRA_INPUT");
        $fdisplay(out_fd, "complete %0d", rows);
        $fclose(fd);
        $fclose(out_fd);
        $display("TRECAP_ROUND_COMPLETED rows=%0d comparisons=%0d", rows, rows*4);
        $finish;
    end
    initial begin
        #1000000;
        $fatal(1, "ROUND_CYCLE_WATCHDOG");
    end
endmodule
`default_nettype wire
