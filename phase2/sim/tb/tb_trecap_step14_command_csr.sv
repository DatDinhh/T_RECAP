// SPDX-License-Identifier: MIT
// Step-14 directed CSR test: source readback/gating, diagnostic counter clear, and retained replay
// command results. This source is simulator-ready but is not claimed as executed when no native
// SystemVerilog simulator is installed.

`timescale 1ns/1ps
`default_nettype none

module tb_trecap_step14_command_csr;
    import trecap_core_pkg::*;
    import trecap_csr_pkg::*;
    import trecap_packet_pkg::*;
    import trecap_iface_pkg::*;
    import trecap_build_pkg::*;

    localparam int unsigned CSR_ADDR_W = 12;
    localparam logic [31:0] CONTROL_RUN =
        TCSR_CONTROL_TELEMETRY_ENABLE_MASK | TCSR_CONTROL_RING_WRITER_ENABLE_MASK;

    logic clk;
    logic rst_n;
    logic csr_valid;
    logic csr_write;
    logic [CSR_ADDR_W-1:0] csr_addr;
    logic [31:0] csr_wdata;
    logic csr_ready;
    logic csr_rvalid;
    logic [31:0] csr_rdata;
    logic csr_error;

    trecap_source_mode_e actual_source_mode;
    logic source_transition_busy;
    logic transport_epoch_idle;
    logic replay_start_ready;
    logic replay_request_busy;
    logic replay_start_accept;
    logic replay_start_reject;
    logic replay_active;
    logic replay_path_busy;
    logic replay_path_done;
    logic replay_e2e_busy;
    logic replay_e2e_done;
    logic replay_error;
    logic replay_rearm_required;

    trecap_hps_bridge_ctrl_t ctrl;
    trecap_ring_config_t ring_config;
    logic [63:0] ring_rd_committed;
    logic ring_rd_commit_pending;
    logic telemetry_soft_reset_pulse;
    logic clear_metrics_pulse;
    logic counter_clear_pulse;
    logic replay_start_pulse;
    logic replay_rearm_pulse;
    logic thr2_apply_pulse;
    logic source_mode_apply_pulse;
    logic ring_config_commit_pulse;
    logic ring_wr_snapshot_pulse;
    logic ring_rd_commit_pulse;
    logic core_count_snapshot_pulse;
    logic [31:0] clear_sticky_flags_w1c;
    logic [31:0] status;
    logic [31:0] dma_status;
    logic [31:0] overflow_flags;
    logic [31:0] csr_reject_count;
    logic csr_reject_pulse;
    logic malformed_config;

    task automatic fail(input string message);
        begin
            $display("STEP14_COMMAND_CSR_FAIL: %s", message);
            $fatal(1, "STEP14_COMMAND_CSR_FAIL: %s", message);
        end
    endtask

    task automatic require_true(input logic condition, input string message);
        begin
            if (condition !== 1'b1) begin
                fail(message);
            end
        end
    endtask

    task automatic csr_write32(
        input logic [31:0] offset,
        input logic [31:0] value,
        input logic expected_error
    );
        begin
            @(negedge clk);
            csr_valid = 1'b1;
            csr_write = 1'b1;
            csr_addr = offset[CSR_ADDR_W-1:0];
            csr_wdata = value;
            @(posedge clk);
            #1;
            require_true(csr_ready, "CSR write was not accepted by timing contract");
            if (csr_error !== expected_error) begin
                fail("CSR write error response mismatch");
            end
            @(negedge clk);
            csr_valid = 1'b0;
            csr_write = 1'b0;
            csr_addr = '0;
            csr_wdata = '0;
        end
    endtask

    task automatic csr_read32(input logic [31:0] offset, output logic [31:0] value);
        begin
            @(negedge clk);
            csr_valid = 1'b1;
            csr_write = 1'b0;
            csr_addr = offset[CSR_ADDR_W-1:0];
            csr_wdata = '0;
            @(posedge clk);
            #1;
            require_true(csr_ready && csr_rvalid && !csr_error,
                         "CSR read timing/error contract failed");
            value = csr_rdata;
            @(negedge clk);
            csr_valid = 1'b0;
            csr_addr = '0;
        end
    endtask

    task automatic pulse_replay_feedback(input logic accept_result);
        begin
            @(negedge clk);
            replay_start_accept = accept_result;
            replay_start_reject = !accept_result;
            @(posedge clk);
            #1;
            @(negedge clk);
            replay_start_accept = 1'b0;
            replay_start_reject = 1'b0;
        end
    endtask

    trecap_csr_bank #(
        .CSR_ADDR_W(CSR_ADDR_W),
        .RING_SIZE_MIN_BYTES(32'd64)
    ) dut (
        .clk(clk),
        .rst_n(rst_n),
        .external_transport_clear_i(1'b0),
        .csr_valid_i(csr_valid),
        .csr_write_i(csr_write),
        .csr_addr_i(csr_addr),
        .csr_wdata_i(csr_wdata),
        .csr_ready_o(csr_ready),
        .csr_rvalid_o(csr_rvalid),
        .csr_rdata_o(csr_rdata),
        .csr_error_o(csr_error),
        .frame_boundary_i(1'b1),
        .source_safe_boundary_i(1'b1),
        .ring_rd_commit_ready_i(1'b1),
        .actual_source_mode_i(actual_source_mode),
        .source_transition_busy_i(source_transition_busy),
        .transport_epoch_idle_i(transport_epoch_idle),
        .replay_start_ready_i(replay_start_ready),
        .replay_request_busy_i(replay_request_busy),
        .replay_start_accept_pulse_i(replay_start_accept),
        .replay_start_reject_pulse_i(replay_start_reject),
        .replay_active_i(replay_active),
        .replay_path_busy_i(replay_path_busy),
        .replay_path_done_i(replay_path_done),
        .replay_e2e_busy_i(replay_e2e_busy),
        .replay_e2e_done_i(replay_e2e_done),
        .replay_error_i(replay_error),
        .replay_rearm_required_i(replay_rearm_required),
        .core_alive_i(1'b1),
        .ring_wr_ptr_i(64'd0),
        .core_frame_count_i(64'h1122),
        .core_sample_count_i(64'h3344),
        .writer_idle_i(1'b1),
        .writer_busy_i(1'b0),
        .writer_no_space_i(1'b0),
        .malformed_config_i(1'b0),
        .ring_full_i(1'b0),
        .packet_fifo_full_i(1'b0),
        .ddr_wait_i(1'b0),
        .writer_drop_active_i(1'b0),
        .ring_pointers_valid_i(1'b1),
        .dma_drop_count_i(32'd17),
        .dma_packet_count_i(32'd23),
        .packet_fifo_drop_count_i(32'd5),
        .overflow_flags_set_i(32'd0),
        .csr_command_reject_pulse_i(1'b0),
        .csr_adapter_reject_pulse_i(1'b0),
        .ctrl_o(ctrl),
        .ring_config_o(ring_config),
        .ring_rd_committed_o(ring_rd_committed),
        .ring_rd_commit_pending_o(ring_rd_commit_pending),
        .telemetry_soft_reset_pulse_o(telemetry_soft_reset_pulse),
        .clear_metrics_pulse_o(clear_metrics_pulse),
        .counter_clear_pulse_o(counter_clear_pulse),
        .replay_start_pulse_o(replay_start_pulse),
        .replay_rearm_pulse_o(replay_rearm_pulse),
        .thr2_apply_pulse_o(thr2_apply_pulse),
        .source_mode_apply_pulse_o(source_mode_apply_pulse),
        .ring_config_commit_pulse_o(ring_config_commit_pulse),
        .ring_wr_snapshot_pulse_o(ring_wr_snapshot_pulse),
        .ring_rd_commit_pulse_o(ring_rd_commit_pulse),
        .core_count_snapshot_pulse_o(core_count_snapshot_pulse),
        .clear_sticky_flags_w1c_o(clear_sticky_flags_w1c),
        .status_o(status),
        .dma_status_o(dma_status),
        .overflow_flags_o(overflow_flags),
        .csr_command_reject_count_o(csr_reject_count),
        .csr_reject_pulse_o(csr_reject_pulse),
        .malformed_config_o(malformed_config)
    );

    always #5 clk = ~clk;

    initial begin : p_test
        logic [31:0] value;
        logic [15:0] epoch_before_rearm;

        clk = 1'b0;
        rst_n = 1'b0;
        csr_valid = 1'b0;
        csr_write = 1'b0;
        csr_addr = '0;
        csr_wdata = '0;
        actual_source_mode = TSRC_BRAM_REPLAY;
        source_transition_busy = 1'b0;
        transport_epoch_idle = 1'b1;
        replay_start_ready = 1'b0;
        replay_request_busy = 1'b0;
        replay_start_accept = 1'b0;
        replay_start_reject = 1'b0;
        replay_active = 1'b0;
        replay_path_busy = 1'b0;
        replay_path_done = 1'b0;
        replay_e2e_busy = 1'b0;
        replay_e2e_done = 1'b0;
        replay_error = 1'b0;
        replay_rearm_required = 1'b0;

        repeat (3) @(posedge clk);
        rst_n = 1'b1;
        repeat (2) @(posedge clk);

        csr_read32(TCSR_VERSION_OFFSET, value);
        if (value !== 32'h0001_0008) begin
            fail("VERSION is not CSR contract 1.8");
        end

        // Establish a legal ring/Rd epoch so CONTROL failures below isolate source-transition
        // gating rather than ring configuration prerequisites.
        csr_write32(TCSR_RING_BASE_LO_OFFSET, 32'h0000_1000, 1'b0);
        csr_write32(TCSR_RING_BASE_HI_OFFSET, 32'd0, 1'b0);
        csr_write32(TCSR_RING_SIZE_BYTES_OFFSET, 32'd64, 1'b0);
        csr_write32(TCSR_RING_CONFIG_COMMIT_OFFSET, 32'd1, 1'b0);
        csr_write32(TCSR_RING_RD_LO_SHADOW_OFFSET, 32'd0, 1'b0);
        csr_write32(TCSR_RING_RD_HI_SHADOW_OFFSET, 32'd0, 1'b0);
        csr_write32(TCSR_RING_RD_COMMIT_OFFSET, 32'd1, 1'b0);
        repeat (3) @(posedge clk);

        actual_source_mode = TSRC_ADC_LIVE;
        csr_read32(TCSR_STATUS_OFFSET, value);
        require_true(value[TCSR_STATUS_SOURCE_COMMIT_PENDING_LSB],
                     "requested/actual mismatch did not hold source pending");
        require_true(value[TCSR_STATUS_SOURCE_TRANSITION_BUSY_LSB],
                     "requested/actual mismatch did not report transition busy");
        if (value[TCSR_STATUS_ACTUAL_SOURCE_MODE_MSB:
                  TCSR_STATUS_ACTUAL_SOURCE_MODE_LSB] !== TSRC_ADC_LIVE) begin
            fail("STATUS actual source readback is not the physical mux source");
        end
        csr_write32(TCSR_CONTROL_OFFSET, CONTROL_RUN, 1'b1);

        actual_source_mode = TSRC_BRAM_REPLAY;
        csr_write32(TCSR_CONTROL_OFFSET, CONTROL_RUN, 1'b0);

        // Live telemetry/source mutation is fail-closed until both controls are off, transport is
        // drained, replay is quiescent, and the physical source transition is idle.
        csr_write32(TCSR_PACKET_ENABLE_OFFSET, TCSR_PACKET_ENABLE_RESET, 1'b1);
        csr_write32(TCSR_SOURCE_MODE_SHADOW_OFFSET, TCSR_SOURCE_MODE_ADC_LIVE, 1'b1);
        csr_write32(TCSR_CONTROL_OFFSET, 32'd0, 1'b0);
        replay_request_busy = 1'b1;
        csr_write32(TCSR_CONTROL_OFFSET, CONTROL_RUN, 1'b1);
        csr_write32(TCSR_PACKET_ENABLE_OFFSET, TCSR_PACKET_ENABLE_RESET, 1'b1);
        replay_start_ready = 1'b1;
        csr_read32(TCSR_REPLAY_STATUS_OFFSET, value);
        require_true(!value[TCSR_REPLAY_STATUS_START_READY_LSB],
                     "universal replay owner did not suppress START_READY");
        replay_start_ready = 1'b0;
        replay_request_busy = 1'b0;
        transport_epoch_idle = 1'b0;
        csr_write32(TCSR_WAVE_DECIM_OFFSET, 32'd2, 1'b1);
        transport_epoch_idle = 1'b1;
        replay_active = 1'b1;
        csr_write32(TCSR_SPEC_SHIFT_OFFSET, 32'd1, 1'b1);
        replay_active = 1'b0;
        source_transition_busy = 1'b1;
        csr_write32(TCSR_SPEC_MODE_OFFSET, TCSR_SPEC_MODE_SPEC_DISABLED, 1'b1);
        source_transition_busy = 1'b0;
        csr_read32(TCSR_SOURCE_MODE_SHADOW_OFFSET, value);
        if (value[1:0] !== TCSR_SOURCE_MODE_BRAM_REPLAY) begin
            fail("rejected source mutation escaped the quiescent configuration gate");
        end
        csr_write32(TCSR_WAVE_DECIM_OFFSET, 32'd2, 1'b0);
        csr_read32(TCSR_WAVE_DECIM_OFFSET, value);
        if (value !== 32'd2) begin
            fail("quiescent live telemetry configuration write did not apply");
        end

        // Diagnostic clear produces its own pulse and clears the CSR reject counter without
        // invalidating ring configuration or any retained sticky evidence.
        require_true(csr_reject_count != 32'd0, "directed rejected CONTROL was not counted");
        csr_write32(TCSR_COUNTER_CLEAR_OFFSET,
                    TCSR_COUNTER_CLEAR_TRANSPORT_COUNTERS_MASK, 1'b0);
        require_true(counter_clear_pulse, "COUNTER_CLEAR did not emit one W1P pulse");
        csr_read32(TCSR_CSR_COMMAND_REJECT_COUNT_OFFSET, value);
        if (value !== 32'd0 || !ring_config.configured) begin
            fail("COUNTER_CLEAR reset non-counter transport state or did not clear reject count");
        end

        // START must leave the CSR bank even when the current admission status says unready.
        replay_start_ready = 1'b0;
        csr_write32(TCSR_REPLAY_CONTROL_OFFSET, TCSR_REPLAY_CONTROL_START_MASK, 1'b0);
        require_true(replay_start_pulse, "unready START was pre-filtered before FPGA admission");
        csr_read32(TCSR_REPLAY_STATUS_OFFSET, value);
        require_true(value[TCSR_REPLAY_STATUS_PENDING_LSB], "START did not retain pending state");
        pulse_replay_feedback(1'b0);
        csr_read32(TCSR_REPLAY_STATUS_OFFSET, value);
        require_true(value[TCSR_REPLAY_STATUS_LAST_REJECT_LSB] &&
                     !value[TCSR_REPLAY_STATUS_LAST_ACCEPT_LSB],
                     "rejected START did not retain an exclusive result");
        if (value[TCSR_REPLAY_STATUS_RESULT_EPOCH_MSB:
                  TCSR_REPLAY_STATUS_RESULT_EPOCH_LSB] !== 16'd1) begin
            fail("rejected START did not increment result epoch exactly once");
        end

        // Feedback without a CSR pending request represents board-key activity and must not mutate
        // host command correlation state.
        pulse_replay_feedback(1'b1);
        csr_read32(TCSR_REPLAY_STATUS_OFFSET, value);
        if (value[TCSR_REPLAY_STATUS_RESULT_EPOCH_MSB:
                  TCSR_REPLAY_STATUS_RESULT_EPOCH_LSB] !== 16'd1) begin
            fail("board-only replay feedback changed CSR result epoch");
        end

        replay_start_ready = 1'b1;
        csr_write32(TCSR_REPLAY_CONTROL_OFFSET, TCSR_REPLAY_CONTROL_START_MASK, 1'b0);
        require_true(replay_start_pulse, "ready START did not emit raw pulse");
        pulse_replay_feedback(1'b1);
        csr_read32(TCSR_REPLAY_STATUS_OFFSET, value);
        require_true(value[TCSR_REPLAY_STATUS_LAST_ACCEPT_LSB] &&
                     !value[TCSR_REPLAY_STATUS_LAST_REJECT_LSB],
                     "accepted START did not retain an exclusive result");
        if (value[TCSR_REPLAY_STATUS_RESULT_EPOCH_MSB:
                  TCSR_REPLAY_STATUS_RESULT_EPOCH_LSB] !== 16'd2) begin
            fail("accepted START did not increment result epoch exactly once");
        end

        // A second CSR START while the first is pending is rejected and cannot generate a duplicate
        // raw request. Settle the original with a reject afterward.
        csr_write32(TCSR_REPLAY_CONTROL_OFFSET, TCSR_REPLAY_CONTROL_START_MASK, 1'b0);
        require_true(replay_start_pulse, "first pending-test START did not pulse");
        csr_write32(TCSR_REPLAY_CONTROL_OFFSET, TCSR_REPLAY_CONTROL_START_MASK, 1'b1);
        require_true(!replay_start_pulse, "duplicate pending START emitted a second raw pulse");
        pulse_replay_feedback(1'b0);
        csr_read32(TCSR_REPLAY_STATUS_OFFSET, value);
        epoch_before_rearm = value[TCSR_REPLAY_STATUS_RESULT_EPOCH_MSB:
                                   TCSR_REPLAY_STATUS_RESULT_EPOCH_LSB];

        // REARM is legal only for a quiescent failed epoch. It clears retained terminal bits and
        // leaves the result epoch unchanged.
        csr_write32(TCSR_REPLAY_CONTROL_OFFSET, TCSR_REPLAY_CONTROL_REARM_MASK, 1'b1);
        csr_write32(TCSR_REPLAY_CONTROL_OFFSET,
                    TCSR_REPLAY_CONTROL_START_MASK | TCSR_REPLAY_CONTROL_REARM_MASK, 1'b1);
        require_true(!replay_start_pulse && !replay_rearm_pulse,
                     "combined START+REARM write did not reject atomically");
        replay_error = 1'b1;
        replay_rearm_required = 1'b1;
        replay_path_busy = 1'b1;
        csr_write32(TCSR_REPLAY_CONTROL_OFFSET, TCSR_REPLAY_CONTROL_REARM_MASK, 1'b1);
        replay_path_busy = 1'b0;
        replay_request_busy = 1'b1;
        csr_write32(TCSR_REPLAY_CONTROL_OFFSET, TCSR_REPLAY_CONTROL_REARM_MASK, 1'b1);
        require_true(!replay_rearm_pulse,
                     "raw START/request-busy did not deterministically reject REARM");
        replay_request_busy = 1'b0;
        csr_write32(TCSR_REPLAY_CONTROL_OFFSET, TCSR_REPLAY_CONTROL_REARM_MASK, 1'b0);
        require_true(replay_rearm_pulse, "quiescent failed REARM did not pulse owner clear");
        replay_error = 1'b0;
        replay_rearm_required = 1'b0;
        csr_read32(TCSR_REPLAY_STATUS_OFFSET, value);
        require_true(!value[TCSR_REPLAY_STATUS_PENDING_LSB] &&
                     !value[TCSR_REPLAY_STATUS_LAST_ACCEPT_LSB] &&
                     !value[TCSR_REPLAY_STATUS_LAST_REJECT_LSB],
                     "REARM did not clear retained replay result bits");
        if (value[TCSR_REPLAY_STATUS_RESULT_EPOCH_MSB:
                  TCSR_REPLAY_STATUS_RESULT_EPOCH_LSB] !== epoch_before_rearm) begin
            fail("REARM incorrectly advanced result epoch");
        end

        replay_start_ready = 1'b1;
        csr_write32(TCSR_REPLAY_CONTROL_OFFSET, TCSR_REPLAY_CONTROL_START_MASK, 1'b0);
        require_true(replay_start_pulse, "START after successful REARM remained blocked");
        pulse_replay_feedback(1'b1);
        csr_read32(TCSR_REPLAY_STATUS_OFFSET, value);
        require_true(value[TCSR_REPLAY_STATUS_LAST_ACCEPT_LSB],
                     "post-REARM START did not retain accept result");
        if (value[TCSR_REPLAY_STATUS_RESULT_EPOCH_MSB:
                  TCSR_REPLAY_STATUS_RESULT_EPOCH_LSB] !== (epoch_before_rearm + 16'd1)) begin
            fail("post-REARM START did not advance a fresh result epoch");
        end

        $display("STEP14_COMMAND_CSR_PASS");
        $finish;
    end

`ifndef SYNTHESIS
    always_ff @(posedge clk) begin
        if (rst_n && replay_start_accept && replay_start_reject) begin
            fail("replay owner asserted accept and reject together");
        end
    end
`endif

    wire unused_outputs = ctrl.clear_metrics_w1p ^ ^ring_rd_committed ^
                          ring_rd_commit_pending ^ telemetry_soft_reset_pulse ^
                          clear_metrics_pulse ^ thr2_apply_pulse ^ source_mode_apply_pulse ^
                          ring_config_commit_pulse ^ ring_wr_snapshot_pulse ^
                          ring_rd_commit_pulse ^ core_count_snapshot_pulse ^
                          ^clear_sticky_flags_w1c ^ ^status ^ ^dma_status ^ ^overflow_flags ^
                          csr_reject_pulse ^ malformed_config;

endmodule : tb_trecap_step14_command_csr

`default_nettype wire
