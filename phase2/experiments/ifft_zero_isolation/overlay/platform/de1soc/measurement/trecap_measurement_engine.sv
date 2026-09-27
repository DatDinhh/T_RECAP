// SPDX-License-Identifier: MIT
// HPS-independent finite replay measurement shell with optional IFFT zero-operand study.
// control_i is synchronous to clk. Mode/target are captured only on an idle start
// toggle: [1:0] 0=idle,1=dense,2=masked,3=masked+isolation (when supported);
// [2] start; [3] snapshot. Protocol2 reports isolation in status bit11.
// [15:4] reserved zero; [31:16] nonzero epoch count for active modes.
// Invalid busy commands are consumed/rejected; finish the current epoch, then halt.
// Numerical faults halt immediately and clear the core, preserving shell evidence.
// A new valid command in IDLE/FAULT clears retained evidence. A snapshot request
// alone never launches or clears work. Snapshot words are frozen until requested.
// After successful completion, unexpected core activity/fault revokes done and
// latches fault bit12; a new accepted command is exempt from that idle guard.
`default_nettype none
module trecap_measurement_engine #(
    parameter X_FILE = "artifacts/test_vectors/near_threshold_multitone_Ns1024_thr64/x_in.memh",
    parameter DENSE_FILE = "artifacts/measurement/multitone/y_dense.memh",
    parameter MASKED_FILE = "artifacts/measurement/multitone/y_masked.memh",
    parameter int unsigned WATCHDOG_CYCLES = 1_000_000,
    parameter bit SUPPORT_IFFT_ZERO_ISOLATION = 1'b0
) (
    input logic clk,
    input logic rst_n,
    input logic [31:0] control_i,
    output logic [479:0] probe_o,
    output logic busy_o,
    output logic done_o,
    output logic fault_o
);
    localparam logic [31:0] PROTOCOL_STATUS = SUPPORT_IFFT_ZERO_ISOLATION ? 32'h02000000 : 32'h01000000;
    localparam int unsigned NS = 1024;
    localparam int unsigned NY = 1536;
    localparam int unsigned NFRAMES = 9;
    localparam logic [55:0] MASKED_THR2 = 56'd100000000000;
    typedef enum logic [3:0] {IDLE, CLEAR_CORE, WAIT_INIT, ISSUE_START,
                             WAIT_ACCEPT, RUN_EPOCH, VERIFY_EPOCH, FAULT} state_t;
    state_t state_q;
    logic start_seen_q, snapshot_seen_q;
    logic [31:0] command_q;
    logic [1:0] mode_q;
    logic [15:0] target_q;
    logic done_q, numerical_fault_q, command_reject_q;
    logic [31:0] epochs_q, outputs_q, mismatches_q, inputs_q, frames_q;
    logic [63:0] elapsed_q;
    logic [31:0] first_bad_q, faults_q, last_outputs_q, last_cycles_q, checksum_q;
    logic [31:0] epoch_outputs_q, epoch_cycles_q, watchdog_q;
    logic [479:0] live_probe;
    logic [31:0] status_word;
    logic start_event, snapshot_event, command_legal, accept_command;
    logic core_clear, core_start;
    logic [55:0] thr2;

    logic y_valid;
    logic signed [11:0] y_data;
    logic [63:0] y_idx;
    logic source_valid, source_ready;
    logic [63:0] source_idx;
    trecap_iface_pkg::trecap_core_tap_frame_t tap_frame;
    logic core_busy, top_busy, top_done, start_accept, start_reject;
    logic completion_fault, build_fault, protocol_fault, saturation_fault, metric_fault;
    logic [31:0] overflow_flags;
    logic [63:0] core_sample_count, core_frame_count, core_error_count;
    logic [63:0] top_output_count;
    logic [31:0] core_fault_word;

    // Two physically separate synchronous ROMs, one read per accepted output.
    // Their outputs and the observed data form a one-cycle comparison pipeline.
    (* ramstyle = "M10K" *) logic [11:0] expected_dense [0:NY-1];
    (* ramstyle = "M10K" *) logic [11:0] expected_masked [0:NY-1];
    logic [11:0] dense_read_q, masked_read_q, observed_q;
    logic compare_valid_q, compare_idx_bad_q, compare_masked_q;
    logic [31:0] compare_ordinal_q;
    logic output_event, compare_bad;
    logic [10:0] expected_addr;
    initial begin
        $readmemh(DENSE_FILE, expected_dense);
        $readmemh(MASKED_FILE, expected_masked);
    end
    assign busy_o = (state_q != IDLE) && (state_q != FAULT);
    assign done_o = done_q;
    assign fault_o = numerical_fault_q || command_reject_q;
    assign start_event = control_i[2] != start_seen_q;
    assign snapshot_event = control_i[3] != snapshot_seen_q;
    assign command_legal = (control_i[15:4] == 12'd0) &&
        ((control_i[1:0] == 2'd0) ||
         (((control_i[1:0] == 2'd1) || (control_i[1:0] == 2'd2) ||
           (SUPPORT_IFFT_ZERO_ISOLATION && (control_i[1:0] == 2'd3))) &&
          (control_i[31:16] != 16'd0)));
    assign accept_command = start_event && !busy_o && command_legal;
    assign core_clear = (state_q == CLEAR_CORE) || (state_q == FAULT);
    assign core_start = state_q == ISSUE_START;
    assign thr2 = (mode_q >= 2'd2) ? MASKED_THR2 : 56'd0;
    assign output_event = y_valid && busy_o && !core_clear;
    assign expected_addr = (y_idx < 64'(NY)) ? y_idx[10:0] : 11'd0;
    assign compare_bad = compare_valid_q &&
        (compare_idx_bad_q ||
         (observed_q != (compare_masked_q ? masked_read_q : dense_read_q)));
    always_ff @(posedge clk) begin
        if (output_event) begin
            dense_read_q <= expected_dense[expected_addr];
            masked_read_q <= expected_masked[expected_addr];
            observed_q <= y_data;
            compare_idx_bad_q <= (y_idx != {32'd0, epoch_outputs_q}) ||
                                 (y_idx >= 64'(NY));
            compare_masked_q <= mode_q >= 2'd2;
            compare_ordinal_q <= outputs_q;
        end
    end
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) compare_valid_q <= 1'b0;
        else if (accept_command || core_clear) compare_valid_q <= 1'b0;
        else compare_valid_q <= output_event;
    end

    always_comb begin
        core_fault_word = 32'd0;
        core_fault_word[0] = completion_fault;
        core_fault_word[1] = protocol_fault;
        core_fault_word[2] = saturation_fault;
        core_fault_word[3] = metric_fault;
        core_fault_word[4] = overflow_flags != 32'd0;
        core_fault_word[5] = build_fault;
        core_fault_word[6] = start_reject;
    end

    // Counter maxima are bounded: <=65535 epochs *1536 outputs fits 32 bits.
    // elapsed counts clock differences from command acceptance to terminal edge;
    // last_cycles counts ISSUE_START through VERIFY_EPOCH inclusive.
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state_q <= IDLE;
            start_seen_q <= 1'b0;
            command_q <= 32'd0;
            mode_q <= 2'd0;
            target_q <= 16'd0;
            done_q <= 1'b0;
            numerical_fault_q <= 1'b0;
            command_reject_q <= 1'b0;
            epochs_q <= 32'd0;
            outputs_q <= 32'd0;
            mismatches_q <= 32'd0;
            inputs_q <= 32'd0;
            frames_q <= 32'd0;
            elapsed_q <= 64'd0;
            first_bad_q <= 32'hffffffff;
            faults_q <= 32'd0;
            last_outputs_q <= 32'd0;
            last_cycles_q <= 32'd0;
            checksum_q <= 32'd0;
            epoch_outputs_q <= 32'd0;
            epoch_cycles_q <= 32'd0;
            watchdog_q <= 32'd0;
        end else begin
            if (start_event) start_seen_q <= control_i[2];
            if (accept_command) begin
                command_q <= control_i;
                mode_q <= control_i[1:0];
                target_q <= control_i[31:16];
                state_q <= (control_i[1:0] == 2'd0) ? IDLE : CLEAR_CORE;
                done_q <= control_i[1:0] == 2'd0;
                numerical_fault_q <= 1'b0;
                command_reject_q <= 1'b0;
                epochs_q <= 32'd0;
                outputs_q <= 32'd0;
                mismatches_q <= 32'd0;
                inputs_q <= 32'd0;
                frames_q <= 32'd0;
                elapsed_q <= 64'd0;
                first_bad_q <= 32'hffffffff;
                faults_q <= 32'd0;
                last_outputs_q <= 32'd0;
                last_cycles_q <= 32'd0;
                checksum_q <= 32'd0;
                epoch_outputs_q <= 32'd0;
                epoch_cycles_q <= 32'd0;
                watchdog_q <= 32'd0;
            end else begin
                if (start_event) begin
                    command_reject_q <= 1'b1;
                    faults_q[11] <= 1'b1;
                    // A malformed idle command must not leave stale success visible.
                    if (!busy_o) begin
                        done_q <= 1'b0;
                        state_q <= FAULT;
                    end
                end
                if (busy_o) begin
                    elapsed_q <= elapsed_q + 64'd1;
                    watchdog_q <= watchdog_q + 32'd1;
                    if ((state_q == WAIT_ACCEPT) || (state_q == RUN_EPOCH) ||
                        (state_q == VERIFY_EPOCH))
                        epoch_cycles_q <= epoch_cycles_q + 32'd1;
                    if (source_valid && source_ready && (source_idx < 64'(NS)))
                        inputs_q <= inputs_q + 32'd1;
                    if (tap_frame.valid) frames_q <= frames_q + 32'd1;
                    if (output_event) begin
                        outputs_q <= outputs_q + 32'd1;
                        epoch_outputs_q <= epoch_outputs_q + 32'd1;
                        // Diagnostic rotate-XOR checksum; exact ROM comparison is authoritative.
                        checksum_q <= {checksum_q[26:0],checksum_q[31:27]} ^
                                      {20'd0,y_data} ^ y_idx[31:0];
                    end
                    if (compare_bad) begin
                        mismatches_q <= mismatches_q + 32'd1;
                        if (first_bad_q == 32'hffffffff) first_bad_q <= compare_ordinal_q;
                    end
                    case (state_q)
                        CLEAR_CORE: state_q <= WAIT_INIT;
                        WAIT_INIT: if (!top_busy) state_q <= ISSUE_START;
                        ISSUE_START: begin
                            state_q <= WAIT_ACCEPT;
                            epoch_outputs_q <= 32'd0;
                            epoch_cycles_q <= 32'd1;
                            watchdog_q <= 32'd0;
                        end
                        WAIT_ACCEPT: if (start_accept) state_q <= RUN_EPOCH;
                        RUN_EPOCH: if (top_done) state_q <= VERIFY_EPOCH;
                        VERIFY_EPOCH: if (!compare_valid_q && !output_event) begin
                            last_outputs_q <= epoch_outputs_q;
                            last_cycles_q <= epoch_cycles_q + 32'd1;
                            if ((epoch_outputs_q != NY) || (core_sample_count != 64'd1152) ||
                                (core_frame_count != 64'(NFRAMES)) ||
                                (core_error_count != 64'(NY)) || (top_output_count != 64'(NY))) begin
                                faults_q[10] <= 1'b1;
                                numerical_fault_q <= 1'b1;
                                done_q <= 1'b0;
                                state_q <= FAULT;
                            end else begin
                                epochs_q <= epochs_q + 32'd1;
                                if (command_reject_q || start_event) begin
                                    done_q <= 1'b0;
                                    state_q <= FAULT;
                                end else if ((epochs_q + 32'd1) == {16'd0,target_q}) begin
                                    done_q <= 1'b1;
                                    state_q <= IDLE;
                                end else state_q <= ISSUE_START;
                            end
                        end
                        default: begin end
                    endcase
                    // Gate stale previous-epoch status during the explicit new-batch clear.
                    if ((state_q != CLEAR_CORE) && (state_q != WAIT_INIT) &&
                        ((core_fault_word != 32'd0) || compare_bad ||
                         (watchdog_q >= WATCHDOG_CYCLES))) begin
                        faults_q <= faults_q | core_fault_word |
                            (compare_bad ? 32'h00000100 : 32'd0) |
                            ((compare_bad && compare_idx_bad_q) ? 32'h00000080 : 32'd0) |
                            ((watchdog_q >= WATCHDOG_CYCLES) ? 32'h00000200 : 32'd0) |
                            (start_event ? 32'h00000800 : 32'd0);
                        numerical_fault_q <= 1'b1;
                        done_q <= 1'b0;
                        state_q <= FAULT;
                        last_outputs_q <= epoch_outputs_q + (output_event ? 32'd1 : 32'd0);
                        last_cycles_q <= epoch_cycles_q + 32'd1;
                    end else if ((state_q == WAIT_INIT) && (watchdog_q >= WATCHDOG_CYCLES)) begin
                        faults_q[9] <= 1'b1;
                        numerical_fault_q <= 1'b1;
                        done_q <= 1'b0;
                        state_q <= FAULT;
                    end
                end
                // Keep the completed result valid only while the completed core
                // remains quiescent. A late output/activity or retained core fault
                // must not leave a stale successful shell result visible to JTAG.
                if ((state_q == IDLE) && done_q && (mode_q != 2'd0) &&
                    ((core_fault_word != 32'd0) || y_valid || core_busy || top_busy)) begin
                    faults_q <= faults_q | core_fault_word | 32'h00001000 |
                        (start_event ? 32'h00000800 : 32'd0);
                    numerical_fault_q <= 1'b1;
                    done_q <= 1'b0;
                    state_q <= FAULT;
                end
            end
        end
    end

    always_comb begin
        status_word = PROTOCOL_STATUS;
        status_word[0] = busy_o;
        status_word[1] = done_q;
        status_word[2] = numerical_fault_q;
        status_word[3] = command_reject_q;
        status_word[4] = mode_q == 2'd1;
        status_word[5] = mode_q >= 2'd2;
        status_word[6] = core_busy;
        status_word[7] = top_done;
        status_word[8] = start_seen_q;
        status_word[9] = snapshot_seen_q;
        status_word[10] = compare_valid_q;
        status_word[11] = SUPPORT_IFFT_ZERO_ISOLATION && (mode_q == 2'd3);
        status_word[15:12] = state_q;
        live_probe = 480'd0;
        live_probe[0*32 +:32] = 32'h54524350;
        live_probe[1*32 +:32] = status_word;
        live_probe[2*32 +:32] = command_q;
        live_probe[3*32 +:32] = epochs_q;
        live_probe[4*32 +:32] = outputs_q;
        live_probe[5*32 +:32] = mismatches_q;
        live_probe[6*32 +:32] = inputs_q;
        live_probe[7*32 +:32] = frames_q;
        live_probe[8*32 +:32] = elapsed_q[31:0];
        live_probe[9*32 +:32] = elapsed_q[63:32];
        live_probe[10*32 +:32] = first_bad_q;
        live_probe[11*32 +:32] = faults_q;
        live_probe[12*32 +:32] = last_outputs_q;
        live_probe[13*32 +:32] = last_cycles_q;
        live_probe[14*32 +:32] = checksum_q;
    end
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            snapshot_seen_q <= 1'b0;
            probe_o <= {416'd0,PROTOCOL_STATUS,32'h54524350};
        end else if (snapshot_event) begin
            snapshot_seen_q <= control_i[3];
            probe_o <= live_probe;
            probe_o[32+9] <= control_i[3];
        end
    end

    trecap_core_bram_replay_top #(
        .SUPPORT_IFFT_ZERO_ISOLATION(SUPPORT_IFFT_ZERO_ISOLATION),
        .X_MEMH_FILE(X_FILE), .REPLAY_MEM_DEPTH(NS), .INPUT_SAMPLES(NS),
        .START_ON_RESET_RELEASE(1'b0), .RESTART_ALLOWED_WHILE_DONE(1'b1)
    ) u_replay (
        .clk(clk), .rst_n(rst_n), .enable_i(1'b1), .clear_i(core_clear),
        .clear_sticky_i(1'b0), .clear_metrics_i(1'b0), .replay_start_i(core_start),
        .thr2_i(thr2),
        .ifft_zero_isolation_i(SUPPORT_IFFT_ZERO_ISOLATION && (mode_q == 2'd3)),
        .y_valid_o(y_valid), .y_ready_i(1'b1),
        .y_data_o(y_data), .y_sample_idx_o(y_idx),
        .source_sample_valid_o(source_valid), .source_sample_ready_o(source_ready),
        .source_sample_idx_o(source_idx), .tap_frame_o(tap_frame),
        .core_busy_o(core_busy), .core_sample_count_o(core_sample_count),
        .core_frame_count_o(core_frame_count), .core_error_sample_count_o(core_error_count),
        .core_metric_overflow_sticky_o(metric_fault), .core_saturation_sticky_o(saturation_fault),
        .core_protocol_error_sticky_o(protocol_fault),
        .replay_start_accept_pulse_o(start_accept), .replay_start_reject_pulse_o(start_reject),
        .top_busy_o(top_busy), .top_done_o(top_done), .top_output_accept_count_o(top_output_count),
        .top_completion_error_sticky_o(completion_fault), .top_overflow_flags_o(overflow_flags),
        .build_contract_error_o(build_fault)
    );
endmodule
`default_nettype wire
