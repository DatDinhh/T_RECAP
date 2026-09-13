// SPDX-License-Identifier: MIT
// File class: [1] hand-written verification RTL.
// Layer: sim/tb/
// Purpose: Prove that canonical Re/Im squares are evaluated at the full 2*W width.

`timescale 1ns/1ps
`default_nettype none

module tb_trecap_mag2_width
  import trecap_core_pkg::*;
  import trecap_iface_pkg::*;
();

    localparam int unsigned P = T_FFT_P;

    logic clk;
    logic rst_n;
    logic enable_i;
    logic clear_i;
    logic clear_metrics_i;
    logic clear_sticky_i;
    logic [T_MAG2_W-1:0] thr2_i;

    logic in_valid_i;
    logic in_ready_o;
    logic [63:0] in_frame_idx_i;
    logic [P-1:0] in_bin_idx_i;
    logic signed [T_CAN_W-1:0] in_re_i;
    logic signed [T_CAN_W-1:0] in_im_i;
    logic in_unique_i;
    logic in_self_conj_i;
    logic in_last_i;

    logic out_valid_o;
    logic out_ready_i;
    logic [63:0] out_frame_idx_o;
    logic [P-1:0] out_bin_idx_o;
    logic signed [T_CAN_W-1:0] out_re_o;
    logic signed [T_CAN_W-1:0] out_im_o;
    logic [T_MAG2_W-1:0] out_mag2_o;
    logic out_pre_mask_o;
    logic out_mask_o;
    logic out_eligible_o;
    logic out_unique_o;
    logic out_last_o;

    logic frame_stats_valid_o;
    logic [63:0] frame_stats_frame_idx_o;
    trecap_frame_stats_t frame_stats_o;
    logic overflow_sticky_o;

    integer case_count_q;

    always #5ns clk = ~clk;

    trecap_mag2_mask dut (
        .clk( clk ),
        .rst_n( rst_n ),
        .enable_i( enable_i ),
        .clear_i( clear_i ),
        .clear_metrics_i( clear_metrics_i ),
        .clear_sticky_i( clear_sticky_i ),
        .thr2_i( thr2_i ),
        .in_valid_i( in_valid_i ),
        .in_ready_o( in_ready_o ),
        .in_frame_idx_i( in_frame_idx_i ),
        .in_bin_idx_i( in_bin_idx_i ),
        .in_re_i( in_re_i ),
        .in_im_i( in_im_i ),
        .in_unique_i( in_unique_i ),
        .in_self_conj_i( in_self_conj_i ),
        .in_last_i( in_last_i ),
        .out_valid_o( out_valid_o ),
        .out_ready_i( out_ready_i ),
        .out_frame_idx_o( out_frame_idx_o ),
        .out_bin_idx_o( out_bin_idx_o ),
        .out_re_o( out_re_o ),
        .out_im_o( out_im_o ),
        .out_mag2_o( out_mag2_o ),
        .out_pre_mask_o( out_pre_mask_o ),
        .out_mask_o( out_mask_o ),
        .out_eligible_o( out_eligible_o ),
        .out_unique_o( out_unique_o ),
        .out_last_o( out_last_o ),
        .frame_stats_valid_o( frame_stats_valid_o ),
        .frame_stats_frame_idx_o( frame_stats_frame_idx_o ),
        .frame_stats_o( frame_stats_o ),
        .overflow_sticky_o( overflow_sticky_o )
    );

    task automatic drive_and_check(
        input logic [P-1:0] bin_idx,
        input longint signed re_value,
        input longint signed im_value,
        input logic self_conj,
        input logic [T_MAG2_W-1:0] expected_mag2,
        input logic expected_eligible,
        input logic expected_pre_mask,
        input logic expected_mask
    );
        logic signed [T_CAN_W-1:0] expected_re;
        logic signed [T_CAN_W-1:0] expected_im;
        begin
            expected_re = re_value[T_CAN_W-1:0];
            expected_im = self_conj ? '0 : im_value[T_CAN_W-1:0];

            @(negedge clk);
            if (!in_ready_o) begin
                $fatal(1, "C0_MAG2_WIDTH_MISMATCH input not ready for bin=%0d", bin_idx);
            end

            in_valid_i = 1'b1;
            in_frame_idx_i = 64'd0;
            in_bin_idx_i = bin_idx;
            in_re_i = re_value[T_CAN_W-1:0];
            in_im_i = im_value[T_CAN_W-1:0];
            in_unique_i = 1'b1;
            in_self_conj_i = self_conj;
            in_last_i = 1'b0;

            @(posedge clk);
            @(negedge clk);
            in_valid_i = 1'b0;

            if (!out_valid_o ||
                (out_frame_idx_o !== 64'd0) ||
                (out_bin_idx_o !== bin_idx) ||
                (out_re_o !== expected_re) ||
                (out_im_o !== expected_im) ||
                (out_mag2_o !== expected_mag2) ||
                (out_eligible_o !== expected_eligible) ||
                (out_pre_mask_o !== expected_pre_mask) ||
                (out_mask_o !== expected_mask) ||
                !out_unique_o ||
                out_last_o) begin
                $fatal(
                    1,
                    {"C0_MAG2_WIDTH_MISMATCH bin=%0d ",
                     "actual(re=%0d im=%0d mag2=%0d eligible=%0b pre=%0b mask=%0b) ",
                     "expected(re=%0d im=%0d mag2=%0d eligible=%0b pre=%0b mask=%0b)"},
                    bin_idx,
                    out_re_o,
                    out_im_o,
                    out_mag2_o,
                    out_eligible_o,
                    out_pre_mask_o,
                    out_mask_o,
                    expected_re,
                    expected_im,
                    expected_mag2,
                    expected_eligible,
                    expected_pre_mask,
                    expected_mask
                );
            end

            case_count_q = case_count_q + 1;

            // Retire the checked output before issuing the next sequential bin.
            @(posedge clk);
            @(negedge clk);
            if (out_valid_o) begin
                $fatal(1, "C0_MAG2_WIDTH_MISMATCH output did not retire");
            end
        end
    endtask

    initial begin : p_test
        clk = 1'b0;
        rst_n = 1'b0;
        enable_i = 1'b1;
        clear_i = 1'b1;
        clear_metrics_i = 1'b0;
        clear_sticky_i = 1'b0;
        thr2_i = T_MAG2_W'(4096);
        in_valid_i = 1'b0;
        in_frame_idx_i = 64'd0;
        in_bin_idx_i = '0;
        in_re_i = '0;
        in_im_i = '0;
        in_unique_i = 1'b0;
        in_self_conj_i = 1'b0;
        in_last_i = 1'b0;
        out_ready_i = 1'b1;
        case_count_q = 0;

        repeat (4) @(negedge clk);
        rst_n = 1'b1;
        repeat (2) @(negedge clk);
        clear_i = 1'b0;

        // Exact native failure row from near_threshold_multitone_Ns1024_thr64.
        drive_and_check(
            P'(0), 193725, 0, 1'b1,
            T_MAG2_W'(37529375625), 1'b0, 1'b0, 1'b0
        );
        drive_and_check(
            P'(1), -193810, -87, 1'b0,
            T_MAG2_W'(37562323669), 1'b1, 1'b0, 1'b0
        );

        // Signed extrema prove that upper product bits survive.
        drive_and_check(
            P'(2), -134217728, 134217727, 1'b0,
            T_MAG2_W'(36028796750528513), 1'b1, 1'b0, 1'b0
        );
        drive_and_check(
            P'(3), -134217728, -134217728, 1'b0,
            T_MAG2_W'(36028797018963968), 1'b1, 1'b0, 1'b0
        );

        // Threshold decisions are based on the repaired full-width value.
        drive_and_check(
            P'(4), -1, -1, 1'b0,
            T_MAG2_W'(2), 1'b1, 1'b1, 1'b1
        );
        drive_and_check(
            P'(5), 64, 0, 1'b0,
            T_MAG2_W'(4096), 1'b1, 1'b0, 1'b0
        );

        if (overflow_sticky_o || frame_stats_valid_o) begin
            $fatal(
                1,
                "C0_MAG2_WIDTH_MISMATCH unexpected status overflow=%0b frame_valid=%0b",
                overflow_sticky_o,
                frame_stats_valid_o
            );
        end

        $display("C0_MAG2_WIDTH_PASS cases=%0d product_width=%0d", case_count_q, T_MAG2_W);
        $finish;
    end

endmodule : tb_trecap_mag2_width

`default_nettype wire
