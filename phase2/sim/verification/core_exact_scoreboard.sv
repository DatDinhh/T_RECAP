// SPDX-License-Identifier: MIT
// File class: [1] hand-written verification RTL.
// Layer: sim/verification/
// Purpose: Exact finite-run scoreboard against a qualified independent oracle bundle.
//
// The generated expectation package is produced from a qualified independent
// oracle bundle before compilation.  This module compares live RTL events, writes canonical
// captures for an independent post-check, and permits no observer backpressure.

`timescale 1ns/1ps
`default_nettype none

module core_exact_scoreboard
  import trecap_core_pkg::*;
  import trecap_iface_pkg::*;
  import trecap_artifact_expectations_pkg::*;
#(
    parameter string X_GOLDEN_FILE =
        "artifacts/test_vectors/near_threshold_multitone_Ns1024_thr64/x_in.memh",
    parameter string Y_GOLDEN_FILE =
        "artifacts/reference_outputs/near_threshold_multitone_Ns1024_thr64/y_out.memh",
    parameter string FRAME_GOLDEN_FILE =
        "artifacts/reference_outputs/near_threshold_multitone_Ns1024_thr64/frame_stats.csv",
    parameter string BIN_GOLDEN_FILE =
        "artifacts/reference_outputs/near_threshold_multitone_Ns1024_thr64/bin_stats.csv",
    parameter string IFFT_GOLDEN_FILE = "",
    parameter string CAPTURE_DIR =
        "",
    parameter int unsigned QUIET_CYCLES = 1024,
    parameter int unsigned WATCHDOG_CYCLES = 500000
) (
    input  wire logic                         clk,
    input  wire logic                         rst_n,

    input  wire logic                         y_valid_i,
    input  wire logic                         y_ready_i,
    input  wire logic signed [T_SAMPLE_W-1:0] y_data_i,
    input  wire logic [63:0]                  y_sample_idx_i,

    input  wire trecap_core_tap_sample_t      tap_sample_i,
    input  wire trecap_core_tap_frame_t       tap_frame_i,
    input  wire logic                         tap_bin_valid_i,
    input  wire logic [63:0]                  tap_bin_frame_idx_i,
    input  wire logic [$clog2(T_UNIQUE_BINS)-1:0] tap_bin_idx_i,
    input  wire logic signed [T_CAN_W-1:0]    tap_bin_re_i,
    input  wire logic signed [T_CAN_W-1:0]    tap_bin_im_i,
    input  wire logic [T_MAG2_W-1:0]          tap_bin_mag2_i,
    input  wire logic                         tap_bin_pre_mask_i,
    input  wire logic                         tap_bin_mask_i,
    input  wire logic                         tap_bin_eligible_i,
    input  wire logic                         tap_bin_last_i,

    // Passive observation of the accepted complex IFFT output at WOLA input.
    input wire logic ifft_valid_i,
    input wire logic ifft_ready_i,
    input wire logic [63:0] ifft_frame_idx_i,
    input wire logic [T_FFT_P-1:0] ifft_sample_offset_i,
    input wire logic signed [T_IFFT_W-1:0] ifft_re_i,
    input wire logic signed [T_IFFT_W-1:0] ifft_im_i,
    input wire logic ifft_last_i,

    input  wire logic                         top_done_i,
    input  wire logic                         top_done_pulse_i,
    input  wire logic                         top_completion_error_sticky_i,
    input  wire logic [31:0]                  top_overflow_flags_i,
    input  wire logic [31:0]                  core_overflow_flags_i,
    input  wire logic                         core_saturation_sticky_i,
    input  wire logic                         core_protocol_error_sticky_i,

    input  wire logic [63:0]                  core_error_sample_count_i,
    input  wire logic [63:0]                  core_sum_abs_err_lo_i,
    input  wire logic [63:0]                  core_sum_sq_err_lo_i,
    input  wire logic [15:0]                  core_max_abs_err_i,
    input  wire logic                         core_metric_overflow_sticky_i,

    output logic                         scoreboard_done_o
);


    // Edge snapshots own y transfers and combinational accepted-bin taps.
    logic y_valid_edge;
    logic y_ready_edge;
    logic signed [T_SAMPLE_W-1:0] y_data_edge;
    logic [63:0] y_sample_idx_edge;
    logic tap_bin_valid_edge;
    logic [63:0] tap_bin_frame_idx_edge;
    logic [$clog2(T_UNIQUE_BINS)-1:0] tap_bin_idx_edge;
    logic signed [T_CAN_W-1:0] tap_bin_re_edge;
    logic signed [T_CAN_W-1:0] tap_bin_im_edge;
    logic [T_MAG2_W-1:0] tap_bin_mag2_edge;
    logic tap_bin_pre_mask_edge;
    logic tap_bin_mask_edge;
    logic tap_bin_eligible_edge;
    logic tap_bin_last_edge;

    localparam int unsigned IFFT_ROWS = TEXP_FRAMES * T_FFT_L;
    localparam string IFFT_HEADER = "frame_idx,offset,re,im";
    logic ifft_valid_edge, ifft_ready_edge, ifft_last_edge;
    logic [63:0] ifft_frame_idx_edge;
    logic [T_FFT_P-1:0] ifft_sample_offset_edge;
    logic signed [T_IFFT_W-1:0] ifft_re_edge, ifft_im_edge;
    logic signed [T_IFFT_W-1:0] expected_ifft_re [0:IFFT_ROWS-1];
    logic signed [T_IFFT_W-1:0] expected_ifft_im [0:IFFT_ROWS-1];
    integer ifft_capture_fd;
    integer ifft_count_q, ifft_nonzero_imag_count_q, expected_nonzero_imag_count;
    longint unsigned ifft_max_abs_imag_q, expected_max_abs_imag;

    localparam string FRAME_HEADER =
        "frame_idx,unique_bins,unique_suppressed_bins,eligible_unique_bins,eligible_suppressed_bins,eligible_kept_mag2,eligible_total_mag2";
    localparam string BIN_HEADER =
        "frame_idx,bin_idx,real,imag,mag2,eligible,pre_mask,mask";

    logic signed [T_SAMPLE_W-1:0] expected_x [0:TEXP_NS-1];
    logic signed [T_SAMPLE_W-1:0] expected_y [0:TEXP_NY-1];

    logic [63:0] expected_frame_idx [0:TEXP_FRAMES-1];
    logic [31:0] expected_frame_unique [0:TEXP_FRAMES-1];
    logic [31:0] expected_frame_unique_suppressed [0:TEXP_FRAMES-1];
    logic [31:0] expected_frame_eligible [0:TEXP_FRAMES-1];
    logic [31:0] expected_frame_eligible_suppressed [0:TEXP_FRAMES-1];
    logic [63:0] expected_frame_kept_mag2 [0:TEXP_FRAMES-1];
    logic [63:0] expected_frame_total_mag2 [0:TEXP_FRAMES-1];

    logic [63:0] expected_bin_frame_idx [0:TEXP_BIN_ROWS-1];
    logic [$clog2(T_UNIQUE_BINS)-1:0] expected_bin_idx [0:TEXP_BIN_ROWS-1];
    logic signed [T_CAN_W-1:0] expected_bin_re [0:TEXP_BIN_ROWS-1];
    logic signed [T_CAN_W-1:0] expected_bin_im [0:TEXP_BIN_ROWS-1];
    logic [T_MAG2_W-1:0] expected_bin_mag2 [0:TEXP_BIN_ROWS-1];
    logic expected_bin_eligible [0:TEXP_BIN_ROWS-1];
    logic expected_bin_pre_mask [0:TEXP_BIN_ROWS-1];
    logic expected_bin_mask [0:TEXP_BIN_ROWS-1];

    integer y_capture_fd;
    integer frame_capture_fd;
    integer bin_capture_fd;
    integer metrics_capture_fd;
    integer sample_capture_fd;
    integer y_accept_capture_fd;
    string capture_dir_q;
    logic expectations_loaded_q;

    logic [63:0] cycle_count_q;
    logic [63:0] y_count_q;
    logic [63:0] frame_count_q;
    logic [63:0] bin_count_q;
    logic [63:0] error_count_q;
    logic [63:0] done_pulse_count_q;

    logic [63:0] frame_unique_total_q;
    logic [63:0] frame_unique_suppressed_total_q;
    logic [63:0] frame_eligible_total_q;
    logic [63:0] frame_eligible_suppressed_total_q;
    logic [127:0] frame_kept_mag2_total_q;
    logic [127:0] frame_total_mag2_total_q;

    logic [63:0] bin_unique_total_q;
    logic [63:0] bin_unique_suppressed_total_q;
    logic [63:0] bin_eligible_total_q;
    logic [63:0] bin_eligible_suppressed_total_q;
    logic [127:0] bin_kept_mag2_total_q;
    logic [127:0] bin_total_mag2_total_q;

    logic [127:0] sum_abs_err_q;
    logic [127:0] sum_sq_err_q;
    logic [15:0] max_abs_err_q;

    logic prior_y_stall_q;
    logic signed [T_SAMPLE_W-1:0] prior_y_data_q;
    logic [63:0] prior_y_idx_q;
    logic completion_seen_q;
    logic [31:0] quiet_count_q;

    logic [2*T_CAN_W-1:0] bin_re_square_w;
    logic [2*T_CAN_W-1:0] bin_im_square_w;
    logic signed [2*T_CAN_W-1:0] bin_re_operand_wide_s;
    logic signed [2*T_CAN_W-1:0] bin_im_operand_wide_s;
    logic [2*T_CAN_W:0] bin_mag2_recomputed_w;
    logic signed [T_SAMPLE_W:0] tap_error_full_w;
    logic signed [15:0] tap_error_full_i16_w;
    logic signed [16:0] tap_error_i16_ext_w;
    logic [16:0] tap_abs_error_w;
    logic [33:0] tap_sq_error_w;

    // Keep this independent recomputation full-width.  A direct W*W
    // multiplication is only W bits wide in SystemVerilog unless the expression
    // is given a wider operand before evaluation.
    assign bin_re_operand_wide_s =
        {{T_CAN_W{tap_bin_re_edge[T_CAN_W-1]}}, tap_bin_re_edge};
    assign bin_im_operand_wide_s =
        {{T_CAN_W{tap_bin_im_edge[T_CAN_W-1]}}, tap_bin_im_edge};
    assign bin_re_square_w =
        $unsigned(bin_re_operand_wide_s * $signed(tap_bin_re_edge));
    assign bin_im_square_w =
        $unsigned(bin_im_operand_wide_s * $signed(tap_bin_im_edge));
    assign bin_mag2_recomputed_w =
        {1'b0, bin_re_square_w} + {1'b0, bin_im_square_w};
    assign tap_error_full_w =
        $signed({tap_sample_i.x_delayed[T_SAMPLE_W-1], tap_sample_i.x_delayed}) -
        $signed({tap_sample_i.y_out[T_SAMPLE_W-1], tap_sample_i.y_out});
    assign tap_error_full_i16_w =
        {{(15-T_SAMPLE_W){tap_error_full_w[T_SAMPLE_W]}}, tap_error_full_w};
    assign tap_error_i16_ext_w =
        {tap_sample_i.error_i16[15], tap_sample_i.error_i16};
    assign tap_abs_error_w =
        (tap_error_i16_ext_w < 0) ?
        $unsigned(-tap_error_i16_ext_w) : $unsigned(tap_error_i16_ext_w);
    assign tap_sq_error_w = tap_abs_error_w * tap_abs_error_w;

    function automatic string strip_line_end(input string value);
        int length;
        begin
            length = value.len();
            while ((length > 0) &&
                   ((value.getc(length - 1) == 10) ||
                    (value.getc(length - 1) == 13))) begin
                length = length - 1;
            end
            if (length == 0) begin
                strip_line_end = "";
            end else begin
                strip_line_end = value.substr(0, length - 1);
            end
        end
    endfunction

    task automatic require_file(input integer fd, input string path);
        begin
            if (fd == 0) begin
                $fatal(1, "CORE_MISMATCH cannot open file: %s", path);
            end
        end
    endtask

    task automatic load_sample_rows(input string path, input bit is_y);
        integer fd, status, row, column, expected_rows;
        integer code, parsed;
        logic [T_SAMPLE_W-1:0] value;
        string line;
        begin
            fd = $fopen(path, "r");
            require_file(fd, path);
            expected_rows = is_y ? TEXP_NY : TEXP_NS;
            for (row = 0; row < expected_rows; row = row + 1) begin
                status = $fgets(line, fd);
                line = strip_line_end(line);
                if (status == 0 || line.len() != 3)
                    $fatal(1, "CORE_MISMATCH short/noncanonical memh %s row=%0d", path, row);
                for (column = 0; column < 3; column = column + 1) begin
                    code = line.getc(column);
                    if (!((code >= 48 && code <= 57) || (code >= 97 && code <= 102)))
                        $fatal(1, "CORE_MISMATCH invalid memh digit %s row=%0d", path, row);
                end
                parsed = $sscanf(line, "%h", value);
                if (parsed != 1 || $isunknown(value))
                    $fatal(1, "CORE_MISMATCH unknown memh sample %s row=%0d", path, row);
                if (is_y) expected_y[row] = $signed(value);
                else expected_x[row] = $signed(value);
            end
            if ($fgets(line, fd) != 0)
                $fatal(1, "CORE_MISMATCH extra memh row %s", path);
            $fclose(fd);
        end
    endtask

    task automatic load_ifft_rows;
        integer fd, status, parsed, row;
        longint signed frame_idx, sample_offset, real_value, imag_value;
        string line;
        begin
            fd = $fopen(IFFT_GOLDEN_FILE, "r");
            require_file(fd, IFFT_GOLDEN_FILE);
            status = $fgets(line, fd);
            if (status == 0 || strip_line_end(line) != IFFT_HEADER)
                $fatal(1, "CORE_MISMATCH IFFT CSV header");
            expected_nonzero_imag_count = 0;
            expected_max_abs_imag = 0;
            for (row = 0; row < IFFT_ROWS; row = row + 1) begin
                status = $fgets(line, fd);
                parsed = $sscanf(line, "%d,%d,%d,%d", frame_idx, sample_offset, real_value, imag_value);
                if (status == 0 || parsed != 4 || frame_idx != row / T_FFT_L ||
                    sample_offset != row % T_FFT_L ||
                    real_value < -(64'sd1 << (T_IFFT_W-1)) ||
                    real_value >= (64'sd1 << (T_IFFT_W-1)) ||
                    imag_value < -(64'sd1 << (T_IFFT_W-1)) ||
                    imag_value >= (64'sd1 << (T_IFFT_W-1)))
                    $fatal(1, "CORE_MISMATCH invalid IFFT row=%0d", row);
                expected_ifft_re[row] = real_value[T_IFFT_W-1:0];
                expected_ifft_im[row] = imag_value[T_IFFT_W-1:0];
                if (imag_value != 0) expected_nonzero_imag_count = expected_nonzero_imag_count + 1;
                if ((imag_value < 0 ? -imag_value : imag_value) > expected_max_abs_imag)
                    expected_max_abs_imag = (imag_value < 0 ? -imag_value : imag_value);
            end
            if ($fgets(line, fd) != 0) $fatal(1, "CORE_MISMATCH extra IFFT CSV row");
            $fclose(fd);
            // Some short or symmetric inputs have an exactly real IFFT. Zero
            // residual is legal when the oracle expects it; every complex word,
            // residual count and maximum are still compared at completion.
        end
    endtask

    task automatic load_frame_rows;
        integer fd;
        integer status;
        integer parsed;
        integer row;
        string line;
        longint signed frame_idx;
        longint signed unique_bins;
        longint signed unique_suppressed;
        longint signed eligible_bins;
        longint signed eligible_suppressed;
        longint signed kept_mag2;
        longint signed total_mag2;
        begin
            fd = $fopen(FRAME_GOLDEN_FILE, "r");
            require_file(fd, FRAME_GOLDEN_FILE);
            status = $fgets(line, fd);
            if ((status == 0) || (strip_line_end(line) != FRAME_HEADER)) begin
                $fatal(1, "CORE_MISMATCH frame_stats.csv header");
            end
            for (row = 0; row < TEXP_FRAMES; row = row + 1) begin
                status = $fgets(line, fd);
                if (status == 0) begin
                    $fatal(1, "CORE_MISMATCH frame_stats.csv short at row %0d", row);
                end
                parsed = $sscanf(
                    line, "%d,%d,%d,%d,%d,%d,%d",
                    frame_idx,
                    unique_bins,
                    unique_suppressed,
                    eligible_bins,
                    eligible_suppressed,
                    kept_mag2,
                    total_mag2
                );
                if ((parsed != 7) || (frame_idx < 0) || (unique_bins < 0) ||
                    (unique_suppressed < 0) || (eligible_bins < 0) ||
                    (eligible_suppressed < 0) || (kept_mag2 < 0) ||
                    (total_mag2 < 0)) begin
                    $fatal(1, "CORE_MISMATCH invalid frame row %0d", row);
                end
                expected_frame_idx[row] = frame_idx[63:0];
                expected_frame_unique[row] = unique_bins[31:0];
                expected_frame_unique_suppressed[row] = unique_suppressed[31:0];
                expected_frame_eligible[row] = eligible_bins[31:0];
                expected_frame_eligible_suppressed[row] = eligible_suppressed[31:0];
                expected_frame_kept_mag2[row] = kept_mag2[63:0];
                expected_frame_total_mag2[row] = total_mag2[63:0];
            end
            status = $fgets(line, fd);
            if (status != 0) begin
                $fatal(1, "CORE_MISMATCH frame_stats.csv has extra rows");
            end
            $fclose(fd);
        end
    endtask

    task automatic load_bin_rows;
        integer fd;
        integer status;
        integer parsed;
        integer row;
        string line;
        longint signed frame_idx;
        longint signed bin_idx;
        longint signed real_value;
        longint signed imag_value;
        longint signed mag2_value;
        longint signed eligible_value;
        longint signed pre_mask_value;
        longint signed mask_value;
        begin
            fd = $fopen(BIN_GOLDEN_FILE, "r");
            require_file(fd, BIN_GOLDEN_FILE);
            status = $fgets(line, fd);
            if ((status == 0) || (strip_line_end(line) != BIN_HEADER)) begin
                $fatal(1, "CORE_MISMATCH bin_stats.csv header");
            end
            for (row = 0; row < TEXP_BIN_ROWS; row = row + 1) begin
                status = $fgets(line, fd);
                if (status == 0) begin
                    $fatal(1, "CORE_MISMATCH bin_stats.csv short at row %0d", row);
                end
                parsed = $sscanf(
                    line, "%d,%d,%d,%d,%d,%d,%d,%d",
                    frame_idx,
                    bin_idx,
                    real_value,
                    imag_value,
                    mag2_value,
                    eligible_value,
                    pre_mask_value,
                    mask_value
                );
                if ((parsed != 8) || (frame_idx < 0) || (bin_idx < 0) ||
                    (mag2_value < 0) || (eligible_value < 0) ||
                    (eligible_value > 1) || (pre_mask_value < 0) ||
                    (pre_mask_value > 1) || (mask_value < 0) ||
                    (mask_value > 1)) begin
                    $fatal(1, "CORE_MISMATCH invalid bin row %0d", row);
                end
                expected_bin_frame_idx[row] = frame_idx[63:0];
                expected_bin_idx[row] = bin_idx[$clog2(T_UNIQUE_BINS)-1:0];
                expected_bin_re[row] = real_value[T_CAN_W-1:0];
                expected_bin_im[row] = imag_value[T_CAN_W-1:0];
                expected_bin_mag2[row] = mag2_value[T_MAG2_W-1:0];
                expected_bin_eligible[row] = eligible_value[0];
                expected_bin_pre_mask[row] = pre_mask_value[0];
                expected_bin_mask[row] = mask_value[0];
            end
            status = $fgets(line, fd);
            if (status != 0) begin
                $fatal(1, "CORE_MISMATCH bin_stats.csv has extra rows");
            end
            $fclose(fd);
        end
    endtask

    task automatic check_completion;
        begin
            if (!top_done_i) begin
                $fatal(1, "CORE_MISMATCH done pulse without done level");
            end
            if ((y_count_q != TEXP_NY) ||
                (frame_count_q != TEXP_FRAMES) ||
                (bin_count_q != TEXP_BIN_ROWS) ||
                (error_count_q != TEXP_ERROR_SAMPLE_COUNT) ||
                (ifft_count_q != IFFT_ROWS) ||
                (ifft_nonzero_imag_count_q != expected_nonzero_imag_count) ||
                (ifft_max_abs_imag_q != expected_max_abs_imag)) begin
                $fatal(
                    1,
                    "CORE_MISMATCH completion counts y=%0d/%0d frame=%0d/%0d bin=%0d/%0d err=%0d/%0d",
                    y_count_q, TEXP_NY, frame_count_q, TEXP_FRAMES,
                    bin_count_q, TEXP_BIN_ROWS, error_count_q,
                    TEXP_ERROR_SAMPLE_COUNT
                );
            end
            if ((frame_unique_total_q != TEXP_UNIQUE_BINS_TOTAL) ||
                (frame_unique_suppressed_total_q != TEXP_UNIQUE_SUPPRESSED_TOTAL) ||
                (frame_eligible_total_q != TEXP_ELIGIBLE_UNIQUE_TOTAL) ||
                (frame_eligible_suppressed_total_q != TEXP_ELIGIBLE_SUPPRESSED_TOTAL) ||
                (frame_kept_mag2_total_q != TEXP_ELIGIBLE_KEPT_MAG2) ||
                (frame_total_mag2_total_q != TEXP_ELIGIBLE_TOTAL_MAG2)) begin
                $fatal(1, "CORE_MISMATCH frame aggregate vs metrics.json");
            end
            if ((bin_unique_total_q != TEXP_UNIQUE_BINS_TOTAL) ||
                (bin_unique_suppressed_total_q != TEXP_UNIQUE_SUPPRESSED_TOTAL) ||
                (bin_eligible_total_q != TEXP_ELIGIBLE_UNIQUE_TOTAL) ||
                (bin_eligible_suppressed_total_q != TEXP_ELIGIBLE_SUPPRESSED_TOTAL) ||
                (bin_kept_mag2_total_q != TEXP_ELIGIBLE_KEPT_MAG2) ||
                (bin_total_mag2_total_q != TEXP_ELIGIBLE_TOTAL_MAG2)) begin
                $fatal(1, "CORE_MISMATCH bin aggregate vs metrics.json");
            end
            if ((sum_abs_err_q != TEXP_SUM_ABS_ERR) ||
                (sum_sq_err_q != TEXP_SUM_SQ_ERR) ||
                (max_abs_err_q != TEXP_MAX_ABS_ERR)) begin
                $fatal(1, "CORE_MISMATCH time error aggregate vs metrics.json");
            end
            if ($isunknown({core_error_sample_count_i, core_sum_abs_err_lo_i,
                            core_sum_sq_err_lo_i, core_max_abs_err_i}))
                $fatal(1, "CORE_MISMATCH unknown internal metric accumulator");
            if ((core_error_sample_count_i != TEXP_ERROR_SAMPLE_COUNT) ||
                ({64'd0, core_sum_abs_err_lo_i} != TEXP_SUM_ABS_ERR) ||
                ({64'd0, core_sum_sq_err_lo_i} != TEXP_SUM_SQ_ERR) ||
                (core_max_abs_err_i != TEXP_MAX_ABS_ERR)) begin
                $fatal(1, "CORE_MISMATCH internal RTL metric accumulator");
            end
            if ((top_overflow_flags_i != 0) || (core_overflow_flags_i != 0) ||
                core_saturation_sticky_i || core_protocol_error_sticky_i ||
                top_completion_error_sticky_i || core_metric_overflow_sticky_i) begin
                $fatal(1, "CORE_MISMATCH sticky status/overflow at completion");
            end
        end
    endtask

    task automatic write_metrics_and_pass;
        begin
            metrics_capture_fd =
                $fopen({capture_dir_q, "/metrics_observed.json"}, "wb");
            require_file(metrics_capture_fd, {capture_dir_q, "/metrics_observed.json"});
            $fwrite(metrics_capture_fd, "{\n");
            $fwrite(metrics_capture_fd,
                    "  \"schema\": \"trecap_phase2_rtl_metrics_observed_v1\",\n");
            $fwrite(metrics_capture_fd,
                    "  \"vector_name\": \"%s\",\n", TEXP_VECTOR_NAME);
            $fwrite(metrics_capture_fd, "  \"counts\": {\n");
            $fwrite(metrics_capture_fd, "    \"y_rows\": %0d,\n", y_count_q);
            $fwrite(metrics_capture_fd, "    \"frame_rows\": %0d,\n", frame_count_q);
            $fwrite(metrics_capture_fd, "    \"bin_rows\": %0d,\n", bin_count_q);
            $fwrite(metrics_capture_fd, "    \"done_pulses\": 1\n");
            $fwrite(metrics_capture_fd, "  },\n");
            $fwrite(metrics_capture_fd, "  \"suppression_totals\": {\n");
            $fwrite(metrics_capture_fd,
                    "    \"eligible_suppressed_bins\": \"%0d\",\n",
                    frame_eligible_suppressed_total_q);
            $fwrite(metrics_capture_fd,
                    "    \"eligible_unique_bins\": \"%0d\",\n",
                    frame_eligible_total_q);
            $fwrite(metrics_capture_fd,
                    "    \"unique_bins\": \"%0d\",\n", frame_unique_total_q);
            $fwrite(metrics_capture_fd,
                    "    \"unique_suppressed_bins\": \"%0d\"\n",
                    frame_unique_suppressed_total_q);
            $fwrite(metrics_capture_fd, "  },\n");
            $fwrite(metrics_capture_fd, "  \"spectral_totals\": {\n");
            $fwrite(metrics_capture_fd,
                    "    \"eligible_kept_mag2\": \"%0d\",\n",
                    frame_kept_mag2_total_q);
            $fwrite(metrics_capture_fd,
                    "    \"eligible_total_mag2\": \"%0d\"\n",
                    frame_total_mag2_total_q);
            $fwrite(metrics_capture_fd, "  },\n");
            $fwrite(metrics_capture_fd, "  \"time_domain_errors\": {\n");
            $fwrite(metrics_capture_fd,
                    "    \"error_sample_count\": \"%0d\",\n", error_count_q);
            $fwrite(metrics_capture_fd,
                    "    \"max_abs_err\": \"%0d\",\n", max_abs_err_q);
            $fwrite(metrics_capture_fd,
                    "    \"sum_abs_err\": \"%0d\",\n", sum_abs_err_q);
            $fwrite(metrics_capture_fd,
                    "    \"sum_sq_err\": \"%0d\"\n", sum_sq_err_q);
            $fwrite(metrics_capture_fd, "  },\n");
            $fwrite(metrics_capture_fd, "  \"internal_metrics\": {\n");
            $fwrite(metrics_capture_fd,
                    "    \"error_sample_count\": \"%0d\",\n",
                    core_error_sample_count_i);
            $fwrite(metrics_capture_fd,
                    "    \"max_abs_err\": \"%0d\",\n", core_max_abs_err_i);
            $fwrite(metrics_capture_fd,
                    "    \"sum_abs_err\": \"%0d\",\n", core_sum_abs_err_lo_i);
            $fwrite(metrics_capture_fd,
                    "    \"sum_sq_err\": \"%0d\"\n", core_sum_sq_err_lo_i);
            $fwrite(metrics_capture_fd, "  },\n");
            $fwrite(metrics_capture_fd, "  \"status\": {\n");
            $fwrite(metrics_capture_fd,
                    "    \"completion_error_sticky\": %0d,\n",
                    top_completion_error_sticky_i);
            $fwrite(metrics_capture_fd,
                    "    \"core_overflow_flags\": \"%0d\",\n",
                    core_overflow_flags_i);
            $fwrite(metrics_capture_fd,
                    "    \"metric_overflow_sticky\": %0d,\n",
                    core_metric_overflow_sticky_i);
            $fwrite(metrics_capture_fd,
                    "    \"protocol_error_sticky\": %0d,\n",
                    core_protocol_error_sticky_i);
            $fwrite(metrics_capture_fd,
                    "    \"saturation_sticky\": %0d,\n",
                    core_saturation_sticky_i);
            $fwrite(metrics_capture_fd,
                    "    \"top_overflow_flags\": \"%0d\"\n",
                    top_overflow_flags_i);
            $fwrite(metrics_capture_fd, "  }\n");
            $fwrite(metrics_capture_fd, "}\n");

            $fclose(metrics_capture_fd);
            $fclose(y_capture_fd);
            $fclose(frame_capture_fd);
            $fclose(bin_capture_fd);
            $fclose(sample_capture_fd);
            $fclose(y_accept_capture_fd);
            $fclose(ifft_capture_fd);
            scoreboard_done_o = 1'b1;
            $display("CORE_IFFT_EXACT rows=%0d nonzero_imag_rows=%0d max_abs_imag=%0d", ifft_count_q, ifft_nonzero_imag_count_q, ifft_max_abs_imag_q);
            $display(
                "CORE_RTL_PASS vector=%s y=%0d frames=%0d bins=%0d quiet=%0d",
                TEXP_VECTOR_NAME, y_count_q, frame_count_q, bin_count_q,
                QUIET_CYCLES
            );
            $finish;
        end
    endtask

    initial begin : p_load_expectations
        integer probe_fd;
        expectations_loaded_q = 1'b0;
        scoreboard_done_o = 1'b0;
        capture_dir_q = CAPTURE_DIR;
        if (!$value$plusargs("CORE_CAPTURE_DIR=%s", capture_dir_q) || capture_dir_q == "")
            $fatal(1, "CORE_MISMATCH required +CORE_CAPTURE_DIR=<existing-directory>");

        probe_fd = $fopen(X_GOLDEN_FILE, "r");
        require_file(probe_fd, X_GOLDEN_FILE);
        $fclose(probe_fd);
        probe_fd = $fopen(Y_GOLDEN_FILE, "r");
        require_file(probe_fd, Y_GOLDEN_FILE);
        $fclose(probe_fd);
        load_sample_rows(X_GOLDEN_FILE, 1'b0);
        load_sample_rows(Y_GOLDEN_FILE, 1'b1);
        load_frame_rows();
        load_bin_rows();
        load_ifft_rows();

        // Binary mode prevents Windows CRT newline translation.  The frozen
        // evidence contract is canonical LF on every host.
        y_capture_fd = $fopen({capture_dir_q, "/y_out.memh"}, "wb");
        frame_capture_fd = $fopen({capture_dir_q, "/frame_stats.csv"}, "wb");
        bin_capture_fd = $fopen({capture_dir_q, "/bin_stats.csv"}, "wb");
        require_file(y_capture_fd, {capture_dir_q, "/y_out.memh"});
        require_file(frame_capture_fd, {capture_dir_q, "/frame_stats.csv"});
        require_file(bin_capture_fd, {capture_dir_q, "/bin_stats.csv"});
        $fwrite(frame_capture_fd, "%s\n", FRAME_HEADER);
        $fwrite(bin_capture_fd, "%s\n", BIN_HEADER);
        y_accept_capture_fd = $fopen({capture_dir_q, "/y_accepts.csv"}, "wb");
        require_file(y_accept_capture_fd, {capture_dir_q, "/y_accepts.csv"});
        $fwrite(y_accept_capture_fd, "cycle,sample_idx,y_out\n");
        sample_capture_fd = $fopen({capture_dir_q, "/sample_commits.csv"}, "wb");
        require_file(sample_capture_fd, {capture_dir_q, "/sample_commits.csv"});
        $fwrite(sample_capture_fd, "cycle,sample_idx,x_delayed,y_out,error_i16\n");
        ifft_capture_fd = $fopen({capture_dir_q, "/ifft_samples.csv"}, "wb");
        require_file(ifft_capture_fd, {capture_dir_q, "/ifft_samples.csv"});
        $fwrite(ifft_capture_fd, "%s\n", IFFT_HEADER);
        expectations_loaded_q = 1'b1;
    end

    always @(posedge clk) begin : p_scoreboard
        logic [127:0] weighted_mag2;
        longint signed ifft_im_wide;
        logic signed [T_SAMPLE_W-1:0] expected_x_delayed;
        logic [63:0] source_index;

        // Capture transfer-qualified signals in the active region. Then observe
        // registered frame/sample/done pulses after NBA and combinational settling.
        // A registered sample tap is a metric commit, not the public y handshake.
        y_valid_edge = y_valid_i;
        y_ready_edge = y_ready_i;
        y_data_edge = y_data_i;
        y_sample_idx_edge = y_sample_idx_i;
        tap_bin_valid_edge = tap_bin_valid_i;
        tap_bin_frame_idx_edge = tap_bin_frame_idx_i;
        tap_bin_idx_edge = tap_bin_idx_i;
        tap_bin_re_edge = tap_bin_re_i;
        tap_bin_im_edge = tap_bin_im_i;
        tap_bin_mag2_edge = tap_bin_mag2_i;
        tap_bin_pre_mask_edge = tap_bin_pre_mask_i;
        tap_bin_mask_edge = tap_bin_mask_i;
        tap_bin_eligible_edge = tap_bin_eligible_i;
        tap_bin_last_edge = tap_bin_last_i;
        ifft_valid_edge = ifft_valid_i;
        ifft_ready_edge = ifft_ready_i;
        ifft_frame_idx_edge = ifft_frame_idx_i;
        ifft_sample_offset_edge = ifft_sample_offset_i;
        ifft_re_edge = ifft_re_i;
        ifft_im_edge = ifft_im_i;
        ifft_last_edge = ifft_last_i;
        #1ps;
        if (!rst_n) begin
            cycle_count_q = 64'd0;
            y_count_q = 64'd0;
            frame_count_q = 64'd0;
            bin_count_q = 64'd0;
            error_count_q = 64'd0;
            done_pulse_count_q = 64'd0;
            ifft_count_q = 0;
            ifft_nonzero_imag_count_q = 0;
            ifft_max_abs_imag_q = 0;
            frame_unique_total_q = 64'd0;
            frame_unique_suppressed_total_q = 64'd0;
            frame_eligible_total_q = 64'd0;
            frame_eligible_suppressed_total_q = 64'd0;
            frame_kept_mag2_total_q = 128'd0;
            frame_total_mag2_total_q = 128'd0;
            bin_unique_total_q = 64'd0;
            bin_unique_suppressed_total_q = 64'd0;
            bin_eligible_total_q = 64'd0;
            bin_eligible_suppressed_total_q = 64'd0;
            bin_kept_mag2_total_q = 128'd0;
            bin_total_mag2_total_q = 128'd0;
            sum_abs_err_q = 128'd0;
            sum_sq_err_q = 128'd0;
            max_abs_err_q = 16'd0;
            prior_y_stall_q = 1'b0;
            prior_y_data_q = '0;
            prior_y_idx_q = 64'd0;
            completion_seen_q = 1'b0;
            quiet_count_q = 32'd0;
        end else if (expectations_loaded_q) begin
            cycle_count_q = cycle_count_q + 64'd1;
            if (cycle_count_q >= WATCHDOG_CYCLES) begin
                $fatal(
                    1,
                    "CORE_MISMATCH watchdog y=%0d frame=%0d bin=%0d",
                    y_count_q, frame_count_q, bin_count_q
                );
            end

            if ($isunknown({
                y_valid_edge,
                y_ready_edge, ifft_valid_edge, ifft_ready_edge,
                tap_sample_i.valid,
                tap_frame_i.valid,
                tap_bin_valid_edge,
                top_done_i,
                top_done_pulse_i, top_overflow_flags_i, core_overflow_flags_i,
                core_saturation_sticky_i, core_protocol_error_sticky_i,
                top_completion_error_sticky_i, core_metric_overflow_sticky_i
            })) begin
                $fatal(1, "CORE_MISMATCH X/Z on control observation");
            end

            if (prior_y_stall_q) begin
                if (!y_valid_edge || (y_data_edge !== prior_y_data_q) ||
                    (y_sample_idx_edge !== prior_y_idx_q)) begin
                    $fatal(1, "CORE_MISMATCH y payload changed while stalled");
                end
            end
            prior_y_stall_q = y_valid_edge && !y_ready_edge;
            prior_y_data_q = y_data_edge;
            prior_y_idx_q = y_sample_idx_edge;

            if (completion_seen_q) begin
                if (!top_done_i || y_valid_edge || tap_sample_i.valid ||
                    tap_frame_i.valid || tap_bin_valid_edge || ifft_valid_edge || top_done_pulse_i ||
                    (top_overflow_flags_i != 0) ||
                    (core_overflow_flags_i != 0) ||
                    core_saturation_sticky_i ||
                    core_protocol_error_sticky_i ||
                    top_completion_error_sticky_i ||
                    core_metric_overflow_sticky_i) begin
                    $fatal(
                        1,
                        "CORE_MISMATCH done/status/activity after completion"
                    );
                end
                quiet_count_q = quiet_count_q + 32'd1;
                if (quiet_count_q == QUIET_CYCLES) begin
                    write_metrics_and_pass();
                end
            end else begin
                if (y_valid_edge && y_ready_edge) begin
                    if (y_count_q >= TEXP_NY) begin
                        $fatal(1, "CORE_MISMATCH extra y output");
                    end
                    if ($isunknown({y_sample_idx_edge, y_data_edge})) begin
                        $fatal(1, "CORE_MISMATCH X/Z in y output");
                    end
                    if ((y_sample_idx_edge !== y_count_q) ||
                        (y_data_edge !== expected_y[y_count_q])) begin
                        $fatal(
                            1,
                            "CORE_MISMATCH y row=%0d idx=%0d actual=%0d expected=%0d",
                            y_count_q, y_sample_idx_edge, y_data_edge,
                            expected_y[y_count_q]
                        );
                    end
                    $fwrite(y_capture_fd, "%03x\n", $unsigned(y_data_edge));
                    $fwrite(y_accept_capture_fd, "%0d,%0d,%0d\n", cycle_count_q,
                            y_sample_idx_edge, $signed(y_data_edge));
                    y_count_q = y_count_q + 64'd1;
                end

                if (ifft_valid_edge && ifft_ready_edge) begin
                    if (ifft_count_q >= IFFT_ROWS)
                        $fatal(1, "CORE_MISMATCH extra IFFT sample");
                    if ($isunknown({ifft_frame_idx_edge, ifft_sample_offset_edge,
                                    ifft_re_edge, ifft_im_edge, ifft_last_edge}))
                        $fatal(1, "CORE_MISMATCH unknown accepted IFFT sample");
                    if (ifft_frame_idx_edge !== 64'(ifft_count_q / T_FFT_L) ||
                        ifft_sample_offset_edge !== T_FFT_P'(ifft_count_q % T_FFT_L) ||
                        ifft_last_edge !== ((ifft_count_q % T_FFT_L) == T_FFT_L-1) ||
                        ifft_re_edge !== expected_ifft_re[ifft_count_q] ||
                        ifft_im_edge !== expected_ifft_im[ifft_count_q])
                        $fatal(1, "CORE_MISMATCH IFFT row=%0d frame=%0d offset=%0d actual=(%0d,%0d) expected=(%0d,%0d)",
                               ifft_count_q, ifft_frame_idx_edge, ifft_sample_offset_edge,
                               $signed(ifft_re_edge), $signed(ifft_im_edge),
                               $signed(expected_ifft_re[ifft_count_q]), $signed(expected_ifft_im[ifft_count_q]));
                    if (ifft_im_edge != 0) ifft_nonzero_imag_count_q = ifft_nonzero_imag_count_q + 1;
                    ifft_im_wide = $signed(ifft_im_edge);
                    if ((ifft_im_wide < 0 ? -ifft_im_wide : ifft_im_wide) > ifft_max_abs_imag_q)
                        ifft_max_abs_imag_q = (ifft_im_wide < 0 ? -ifft_im_wide : ifft_im_wide);
                    $fwrite(ifft_capture_fd, "%0d,%0d,%0d,%0d\n",
                            ifft_frame_idx_edge, ifft_sample_offset_edge,
                            $signed(ifft_re_edge), $signed(ifft_im_edge));
                    ifft_count_q = ifft_count_q + 1;
                end

                if (tap_frame_i.valid) begin
                    if (frame_count_q >= TEXP_FRAMES) begin
                        $fatal(1, "CORE_MISMATCH extra frame_stats row");
                    end
                    if ($isunknown(tap_frame_i)) begin
                        $fatal(1, "CORE_MISMATCH X/Z in frame_stats");
                    end
                    if ((tap_frame_i.frame_idx !==
                         expected_frame_idx[frame_count_q]) ||
                        (tap_frame_i.stats.unique_bins !==
                         expected_frame_unique[frame_count_q]) ||
                        (tap_frame_i.stats.unique_suppressed_bins !==
                         expected_frame_unique_suppressed[frame_count_q]) ||
                        (tap_frame_i.stats.eligible_unique_bins !==
                         expected_frame_eligible[frame_count_q]) ||
                        (tap_frame_i.stats.eligible_suppressed_bins !==
                         expected_frame_eligible_suppressed[frame_count_q]) ||
                        (tap_frame_i.stats.eligible_kept_mag2_lo !==
                         expected_frame_kept_mag2[frame_count_q]) ||
                        (tap_frame_i.stats.eligible_total_mag2_lo !==
                         expected_frame_total_mag2[frame_count_q]) ||
                        tap_frame_i.stats.mag2_truncated) begin
                        $fatal(
                            1,
                            "CORE_MISMATCH frame_stats row=%0d frame=%0d",
                            frame_count_q, tap_frame_i.frame_idx
                        );
                    end
                    $fwrite(
                        frame_capture_fd,
                        "%0d,%0d,%0d,%0d,%0d,%0d,%0d\n",
                        tap_frame_i.frame_idx,
                        tap_frame_i.stats.unique_bins,
                        tap_frame_i.stats.unique_suppressed_bins,
                        tap_frame_i.stats.eligible_unique_bins,
                        tap_frame_i.stats.eligible_suppressed_bins,
                        tap_frame_i.stats.eligible_kept_mag2_lo,
                        tap_frame_i.stats.eligible_total_mag2_lo
                    );
                    frame_unique_total_q =
                        frame_unique_total_q + tap_frame_i.stats.unique_bins;
                    frame_unique_suppressed_total_q =
                        frame_unique_suppressed_total_q +
                        tap_frame_i.stats.unique_suppressed_bins;
                    frame_eligible_total_q =
                        frame_eligible_total_q +
                        tap_frame_i.stats.eligible_unique_bins;
                    frame_eligible_suppressed_total_q =
                        frame_eligible_suppressed_total_q +
                        tap_frame_i.stats.eligible_suppressed_bins;
                    frame_kept_mag2_total_q =
                        frame_kept_mag2_total_q +
                        tap_frame_i.stats.eligible_kept_mag2_lo;
                    frame_total_mag2_total_q =
                        frame_total_mag2_total_q +
                        tap_frame_i.stats.eligible_total_mag2_lo;
                    frame_count_q = frame_count_q + 64'd1;
                end

                if (tap_bin_valid_edge) begin
                    if (bin_count_q >= TEXP_BIN_ROWS) begin
                        $fatal(1, "CORE_MISMATCH extra bin_stats row");
                    end
                    if ($isunknown({
                        tap_bin_frame_idx_edge,
                        tap_bin_idx_edge,
                        tap_bin_re_edge,
                        tap_bin_im_edge,
                        tap_bin_mag2_edge,
                        tap_bin_eligible_edge,
                        tap_bin_pre_mask_edge,
                        tap_bin_mask_edge,
                        tap_bin_last_edge
                    })) begin
                        $fatal(1, "CORE_MISMATCH X/Z in bin_stats");
                    end
                    if ((tap_bin_frame_idx_edge !==
                         expected_bin_frame_idx[bin_count_q]) ||
                        (tap_bin_idx_edge !== expected_bin_idx[bin_count_q]) ||
                        (tap_bin_re_edge !== expected_bin_re[bin_count_q]) ||
                        (tap_bin_im_edge !== expected_bin_im[bin_count_q]) ||
                        (tap_bin_mag2_edge !== expected_bin_mag2[bin_count_q]) ||
                        (tap_bin_eligible_edge !==
                         expected_bin_eligible[bin_count_q]) ||
                        (tap_bin_pre_mask_edge !==
                         expected_bin_pre_mask[bin_count_q]) ||
                        (tap_bin_mask_edge !== expected_bin_mask[bin_count_q])) begin
                        $fatal(
                            1,
                            {"CORE_MISMATCH bin row=%0d ",
                             "actual(frame=%0d bin=%0d re=%0d im=%0d mag2=%0d ",
                             "eligible=%0b pre_mask=%0b mask=%0b) ",
                             "expected(frame=%0d bin=%0d re=%0d im=%0d mag2=%0d ",
                             "eligible=%0b pre_mask=%0b mask=%0b)"},
                            bin_count_q,
                            tap_bin_frame_idx_edge,
                            tap_bin_idx_edge,
                            tap_bin_re_edge,
                            tap_bin_im_edge,
                            tap_bin_mag2_edge,
                            tap_bin_eligible_edge,
                            tap_bin_pre_mask_edge,
                            tap_bin_mask_edge,
                            expected_bin_frame_idx[bin_count_q],
                            expected_bin_idx[bin_count_q],
                            expected_bin_re[bin_count_q],
                            expected_bin_im[bin_count_q],
                            expected_bin_mag2[bin_count_q],
                            expected_bin_eligible[bin_count_q],
                            expected_bin_pre_mask[bin_count_q],
                            expected_bin_mask[bin_count_q]
                        );
                    end
                    if (tap_bin_last_edge !==
                        (tap_bin_idx_edge == TEXP_UNIQUE_BINS - 1)) begin
                        $fatal(1, "CORE_MISMATCH unique-bin last marker");
                    end
                    if (bin_mag2_recomputed_w[2*T_CAN_W] ||
                        (bin_mag2_recomputed_w[T_MAG2_W-1:0] !==
                         tap_bin_mag2_edge)) begin
                        $fatal(1, "CORE_MISMATCH recomputed bin mag2");
                    end
                    if (tap_bin_pre_mask_edge !== (tap_bin_mag2_edge < TEXP_THR2)) begin
                        $fatal(1, "CORE_MISMATCH strict pre_mask decision");
                    end
                    if (tap_bin_mask_edge !==
                        (tap_bin_eligible_edge && tap_bin_pre_mask_edge)) begin
                        $fatal(1, "CORE_MISMATCH final mask protection");
                    end
                    $fwrite(
                        bin_capture_fd,
                        "%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d\n",
                        tap_bin_frame_idx_edge,
                        tap_bin_idx_edge,
                        $signed(tap_bin_re_edge),
                        $signed(tap_bin_im_edge),
                        tap_bin_mag2_edge,
                        tap_bin_eligible_edge,
                        tap_bin_pre_mask_edge,
                        tap_bin_mask_edge
                    );
                    weighted_mag2 =
                        ((tap_bin_idx_edge == 0) ||
                         (tap_bin_idx_edge == TEXP_UNIQUE_BINS - 1)) ?
                        {72'd0, tap_bin_mag2_edge} :
                        ({72'd0, tap_bin_mag2_edge} << 1);
                    bin_unique_total_q = bin_unique_total_q + 64'd1;
                    if (tap_bin_mask_edge) begin
                        bin_unique_suppressed_total_q =
                            bin_unique_suppressed_total_q + 64'd1;
                    end
                    if (tap_bin_eligible_edge) begin
                        bin_eligible_total_q = bin_eligible_total_q + 64'd1;
                        bin_total_mag2_total_q =
                            bin_total_mag2_total_q + weighted_mag2;
                        if (tap_bin_mask_edge) begin
                            bin_eligible_suppressed_total_q =
                                bin_eligible_suppressed_total_q + 64'd1;
                        end else begin
                            bin_kept_mag2_total_q =
                                bin_kept_mag2_total_q + weighted_mag2;
                        end
                    end
                    bin_count_q = bin_count_q + 64'd1;
                end

                if (tap_sample_i.valid) begin
                    if (error_count_q >= TEXP_ERROR_SAMPLE_COUNT) begin
                        $fatal(1, "CORE_MISMATCH extra error sample");
                    end
                    if ($isunknown(tap_sample_i)) begin
                        $fatal(1, "CORE_MISMATCH X/Z in sample tap");
                    end
                    if (tap_sample_i.sample_idx !== error_count_q) begin
                        $fatal(1, "CORE_MISMATCH sample tap index");
                    end
                    if (tap_sample_i.y_out !== expected_y[error_count_q]) begin
                        $fatal(1, "CORE_MISMATCH sample tap y value");
                    end
                    if (error_count_q < T_DELAY_D) begin
                        expected_x_delayed = '0;
                    end else begin
                        source_index = error_count_q - T_DELAY_D;
                        expected_x_delayed =
                            (source_index < TEXP_NS) ? expected_x[source_index] : '0;
                    end
                    if (tap_sample_i.x_delayed !== expected_x_delayed) begin
                        $fatal(1, "CORE_MISMATCH delayed x at sample %0d",
                               error_count_q);
                    end
                    if (tap_error_full_i16_w !== tap_sample_i.error_i16) begin
                        $fatal(1, "CORE_MISMATCH error_i16 arithmetic");
                    end
                    sum_abs_err_q = sum_abs_err_q + tap_abs_error_w;
                    sum_sq_err_q = sum_sq_err_q + tap_sq_error_w;
                    if (tap_abs_error_w > max_abs_err_q) begin
                        max_abs_err_q = tap_abs_error_w[15:0];
                    end
                    $fwrite(sample_capture_fd, "%0d,%0d,%0d,%0d,%0d\n",
                            cycle_count_q, tap_sample_i.sample_idx,
                            $signed(tap_sample_i.x_delayed), $signed(tap_sample_i.y_out),
                            $signed(tap_sample_i.error_i16));
                    error_count_q = error_count_q + 64'd1;
                end

                if (top_done_pulse_i) begin
                    if (done_pulse_count_q != 0) begin
                        $fatal(1, "CORE_MISMATCH duplicate done pulse");
                    end
                    check_completion();
                    done_pulse_count_q = 64'd1;
                    completion_seen_q = 1'b1;
                    quiet_count_q = 32'd0;
                end
            end
        end
    end

`ifdef SYNTHESIS
    initial $fatal(1, "CORE_MISMATCH SYNTHESIS define is forbidden");
`endif
    initial begin
        if (TEXP_NS == 0 || TEXP_NY == 0 || TEXP_FRAMES == 0 ||
            TEXP_BIN_ROWS != (TEXP_FRAMES * TEXP_UNIQUE_BINS)) begin
            $fatal(1, "core_exact_scoreboard: invalid generated geometry");
        end
        if (QUIET_CYCLES == 0 || WATCHDOG_CYCLES == 0) begin
            $fatal(1, "core_exact_scoreboard: invalid watchdog/quiet parameter");
        end
    end

endmodule : core_exact_scoreboard

`default_nettype wire
