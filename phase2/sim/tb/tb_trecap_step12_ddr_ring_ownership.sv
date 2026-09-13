// SPDX-License-Identifier: MIT
// Step-12 directed regression for the HPS-owned Rd / FPGA-owned W DDR-ring contract.

`timescale 1ns/1ps
`default_nettype none

module tb_trecap_step12_ddr_ring_ownership;
    import trecap_core_pkg::*;
    import trecap_csr_pkg::*;
    import trecap_packet_pkg::*;
    import trecap_iface_pkg::*;
    import trecap_build_pkg::*;

    localparam int unsigned CSR_AVMM_ADDR_W = 21;
    localparam int unsigned CSR_ADDR_W = 12;
    localparam int unsigned RING_BYTES = 512;
    localparam int unsigned GUARD_BYTES = 64;
    localparam logic [63:0] RING_BASE = 64'h0000_0000_1000_0000;
    localparam logic [31:0] CONTROL_RUN =
        TCSR_CONTROL_TELEMETRY_ENABLE_MASK | TCSR_CONTROL_RING_WRITER_ENABLE_MASK;
    localparam logic [1:0] AVMM_OKAY = 2'b00;
    localparam logic [1:0] AVMM_SLVERR = 2'b10;
    localparam int unsigned MAX_BEATS = 4096;
    localparam int unsigned MAX_TRACE_BEATS = 512;

    logic clk;
    logic rst_n;
    logic external_transport_clear_i;

    logic [CSR_AVMM_ADDR_W-1:0] csr_avs_address_i;
    logic csr_avs_read_i;
    logic csr_avs_write_i;
    logic [31:0] csr_avs_writedata_i;
    logic [3:0] csr_avs_byteenable_i;
    logic [0:0] csr_avs_burstcount_i;
    logic csr_avs_waitrequest_o;
    logic [31:0] csr_avs_readdata_o;
    logic csr_avs_readdatavalid_o;
    logic csr_avs_writeresponsevalid_o;
    logic [1:0] csr_avs_response_o;

    logic frame_boundary_i;
    logic source_safe_boundary_i;
    logic core_alive_i;
    logic [63:0] core_frame_count_i;
    logic [63:0] core_sample_count_i;

    logic record_valid_i;
    logic record_ready_o;
    trecap_record_meta_t record_meta_i;
    logic [31:0] record_payload_data_i;
    logic [3:0] record_payload_keep_i;
    logic record_payload_last_i;

    logic [31:0] packet_fifo_drop_count_i;
    logic packet_fifo_drop_pulse_i;
    logic packet_fifo_full_i;
    logic packet_fifo_overflow_i;
    logic [31:0] external_overflow_flags_set_i;
    logic external_csr_reject_pulse_i;

    logic [63:0] avm_address_o;
    logic avm_write_o;
    logic [63:0] avm_writedata_o;
    logic [7:0] avm_byteenable_o;
    logic [0:0] avm_burstcount_o;
    logic avm_waitrequest_i;
    logic avm_writeresponsevalid_i;
    logic [1:0] avm_response_i;

    trecap_hps_bridge_ctrl_t ctrl_o;
    trecap_ring_config_t ring_config_o;
    logic telemetry_soft_reset_pulse_o;
    logic clear_metrics_pulse_o;
    logic thr2_apply_pulse_o;
    logic source_mode_apply_pulse_o;
    logic [31:0] clear_sticky_flags_w1c_o;
    logic ring_config_commit_pulse_o;
    logic ring_wr_snapshot_req_pulse_o;
    logic ring_rd_commit_req_pulse_o;
    logic core_count_snapshot_pulse_o;
    logic ring_rd_accept_pulse_o;
    logic ring_rd_reject_pulse_o;
    logic writer_ring_wr_snapshot_valid_o;
    logic writer_ring_wr_snapshot_pulse_o;
    logic [31:0] status_o;
    logic [31:0] dma_status_o;
    logic [31:0] overflow_flags_o;
    logic [31:0] csr_command_reject_count_o;
    logic [31:0] dma_drop_count_o;
    logic [31:0] dma_packet_count_o;
    logic [63:0] producer_ptr_o;
    logic [63:0] consumer_ptr_o;
    logic [31:0] sequence_o;
    logic [63:0] used_bytes_o;
    logic [63:0] free_bytes_o;
    logic [63:0] current_offset_o;
    logic [63:0] current_tail_bytes_o;
    logic writer_idle_o;
    logic writer_busy_o;
    logic writer_no_space_o;
    logic malformed_config_o;
    logic ring_full_o;
    logic ddr_wait_o;
    logic drop_active_o;
    logic ring_configured_o;
    logic pointers_valid_o;
    logic writer_fault_sticky_o;
    logic normal_commit_pulse_o;
    logic wrap_commit_pulse_o;
    logic writer_drop_pulse_o;
    logic writer_malformed_pulse_o;
    logic writer_oversized_pulse_o;
    logic packet_fifo_full_status_o;
    logic packet_fifo_overflow_status_o;

    logic [7:0] ddr_mem [0:RING_BYTES-1];
    logic [63:0] beat_addr_log [0:MAX_BEATS-1];
    logic [63:0] beat_data_log [0:MAX_BEATS-1];
    logic [7:0] beat_byteen_log [0:MAX_BEATS-1];
    logic [63:0] trace_addr [0:MAX_TRACE_BEATS-1];
    logic [63:0] trace_data [0:MAX_TRACE_BEATS-1];
    logic [7:0] trace_byteen [0:MAX_TRACE_BEATS-1];

    integer cycle_count;
    integer accepted_beat_count;
    integer okay_response_count;
    integer error_response_count;
    integer delayed_response_count;
    integer response_delay_q;
    integer response_delay_max;
    integer normal_commit_count;
    integer wrap_commit_count;
    integer drop_pulse_count;
    integer rd_accept_count;
    integer rd_reject_count;
    integer trace_mode;
    integer trace_saved_count;
    integer trace_compare_count;
    logic response_pending_q;
    logic pending_response_error_q;
    logic inject_response_error_i;

    logic stalled_write_q;
    logic [63:0] stalled_address_q;
    logic [63:0] stalled_data_q;
    logic [7:0] stalled_byteen_q;

    logic [63:0] observed_w_q;
    logic [63:0] observed_rd_q;
    logic [31:0] observed_sequence_q;
    logic w_commit_pending_q;
    logic w_commit_pending_normal_q;
    integer w_commit_pending_age_q;
    logic [63:0] last_wrap_w_q;
    logic [31:0] last_wrap_sequence_q;

    task automatic fail(input string message);
        begin
            $display("STEP12_DDR_RING_OWNERSHIP_FAIL: %s", message);
            $fatal(1, "STEP12_DDR_RING_OWNERSHIP_FAIL: %s", message);
        end
    endtask

    task automatic require_true(input logic condition, input string message);
        begin
            if (condition !== 1'b1) begin
                fail(message);
            end
        end
    endtask

    function automatic logic [15:0] mem_u16_le(input integer byte_offset);
        return {ddr_mem[byte_offset + 1], ddr_mem[byte_offset]};
    endfunction

    function automatic logic [31:0] mem_u32_le(input integer byte_offset);
        return {ddr_mem[byte_offset + 3], ddr_mem[byte_offset + 2],
                ddr_mem[byte_offset + 1], ddr_mem[byte_offset]};
    endfunction

    function automatic logic [63:0] mem_u64_le(input integer byte_offset);
        return {ddr_mem[byte_offset + 7], ddr_mem[byte_offset + 6],
                ddr_mem[byte_offset + 5], ddr_mem[byte_offset + 4],
                ddr_mem[byte_offset + 3], ddr_mem[byte_offset + 2],
                ddr_mem[byte_offset + 1], ddr_mem[byte_offset]};
    endfunction

    trecap_hps_bridge_top #(
        .CSR_AVMM_ADDR_W(CSR_AVMM_ADDR_W),
        .CSR_ADDR_W(CSR_ADDR_W),
        .CSR_BURSTCOUNT_W(1),
        .RECORD_DATA_W(32),
        .RECORD_KEEP_W(4),
        .AVMM_ADDR_W(64),
        .AVMM_DATA_W(64),
        .AVMM_BYTEEN_W(8),
        .AVMM_BURSTCOUNT_W(1),
        .GUARD_BYTES(GUARD_BYTES),
        .RING_SIZE_MIN_BYTES(RING_BYTES)
    ) dut (
        .clk(clk),
        .rst_n(rst_n),
        .external_transport_clear_i(external_transport_clear_i),
        .csr_avs_address_i(csr_avs_address_i),
        .csr_avs_read_i(csr_avs_read_i),
        .csr_avs_write_i(csr_avs_write_i),
        .csr_avs_writedata_i(csr_avs_writedata_i),
        .csr_avs_byteenable_i(csr_avs_byteenable_i),
        .csr_avs_burstcount_i(csr_avs_burstcount_i),
        .csr_avs_waitrequest_o(csr_avs_waitrequest_o),
        .csr_avs_readdata_o(csr_avs_readdata_o),
        .csr_avs_readdatavalid_o(csr_avs_readdatavalid_o),
        .csr_avs_writeresponsevalid_o(csr_avs_writeresponsevalid_o),
        .csr_avs_response_o(csr_avs_response_o),
        .frame_boundary_i(frame_boundary_i),
        .source_safe_boundary_i(source_safe_boundary_i),
        .actual_source_mode_i(TSRC_BRAM_REPLAY),
        .source_transition_busy_i(1'b0),
        .transport_epoch_idle_i(1'b1),
        .replay_start_ready_i(1'b0),
        .replay_request_busy_i(1'b0),
        .replay_start_accept_pulse_i(1'b0),
        .replay_start_reject_pulse_i(1'b0),
        .replay_active_i(1'b0),
        .replay_path_busy_i(1'b0),
        .replay_path_done_i(1'b0),
        .replay_e2e_busy_i(1'b0),
        .replay_e2e_done_i(1'b0),
        .replay_error_i(1'b0),
        .replay_rearm_required_i(1'b0),
        .core_alive_i(core_alive_i),
        .core_frame_count_i(core_frame_count_i),
        .core_sample_count_i(core_sample_count_i),
        .record_valid_i(record_valid_i),
        .record_ready_o(record_ready_o),
        .record_meta_i(record_meta_i),
        .record_payload_data_i(record_payload_data_i),
        .record_payload_keep_i(record_payload_keep_i),
        .record_payload_last_i(record_payload_last_i),
        .packet_fifo_drop_count_i(packet_fifo_drop_count_i),
        .packet_fifo_drop_pulse_i(packet_fifo_drop_pulse_i),
        .packet_fifo_full_i(packet_fifo_full_i),
        .packet_fifo_overflow_i(packet_fifo_overflow_i),
        .external_overflow_flags_set_i(external_overflow_flags_set_i),
        .external_csr_reject_pulse_i(external_csr_reject_pulse_i),
        .avm_address_o(avm_address_o),
        .avm_write_o(avm_write_o),
        .avm_writedata_o(avm_writedata_o),
        .avm_byteenable_o(avm_byteenable_o),
        .avm_burstcount_o(avm_burstcount_o),
        .avm_waitrequest_i(avm_waitrequest_i),
        .avm_writeresponsevalid_i(avm_writeresponsevalid_i),
        .avm_response_i(avm_response_i),
        .ctrl_o(ctrl_o),
        .ring_config_o(ring_config_o),
        .telemetry_soft_reset_pulse_o(telemetry_soft_reset_pulse_o),
        .clear_metrics_pulse_o(clear_metrics_pulse_o),
        .counter_clear_pulse_o(),
        .replay_start_pulse_o(),
        .replay_rearm_pulse_o(),
        .thr2_apply_pulse_o(thr2_apply_pulse_o),
        .source_mode_apply_pulse_o(source_mode_apply_pulse_o),
        .clear_sticky_flags_w1c_o(clear_sticky_flags_w1c_o),
        .ring_config_commit_pulse_o(ring_config_commit_pulse_o),
        .ring_wr_snapshot_req_pulse_o(ring_wr_snapshot_req_pulse_o),
        .ring_rd_commit_req_pulse_o(ring_rd_commit_req_pulse_o),
        .core_count_snapshot_pulse_o(core_count_snapshot_pulse_o),
        .ring_rd_accept_pulse_o(ring_rd_accept_pulse_o),
        .ring_rd_reject_pulse_o(ring_rd_reject_pulse_o),
        .writer_ring_wr_snapshot_valid_o(writer_ring_wr_snapshot_valid_o),
        .writer_ring_wr_snapshot_pulse_o(writer_ring_wr_snapshot_pulse_o),
        .status_o(status_o),
        .dma_status_o(dma_status_o),
        .overflow_flags_o(overflow_flags_o),
        .csr_command_reject_count_o(csr_command_reject_count_o),
        .dma_drop_count_o(dma_drop_count_o),
        .dma_packet_count_o(dma_packet_count_o),
        .producer_ptr_o(producer_ptr_o),
        .consumer_ptr_o(consumer_ptr_o),
        .sequence_o(sequence_o),
        .used_bytes_o(used_bytes_o),
        .free_bytes_o(free_bytes_o),
        .current_offset_o(current_offset_o),
        .current_tail_bytes_o(current_tail_bytes_o),
        .writer_idle_o(writer_idle_o),
        .writer_busy_o(writer_busy_o),
        .writer_no_space_o(writer_no_space_o),
        .malformed_config_o(malformed_config_o),
        .ring_full_o(ring_full_o),
        .ddr_wait_o(ddr_wait_o),
        .drop_active_o(drop_active_o),
        .ring_configured_o(ring_configured_o),
        .pointers_valid_o(pointers_valid_o),
        .writer_fault_sticky_o(writer_fault_sticky_o),
        .normal_commit_pulse_o(normal_commit_pulse_o),
        .wrap_commit_pulse_o(wrap_commit_pulse_o),
        .writer_drop_pulse_o(writer_drop_pulse_o),
        .writer_malformed_pulse_o(writer_malformed_pulse_o),
        .writer_oversized_pulse_o(writer_oversized_pulse_o),
        .packet_fifo_full_status_o(packet_fifo_full_status_o),
        .packet_fifo_overflow_status_o(packet_fifo_overflow_status_o)
    );

    always #5 clk = ~clk;

    // Deterministic Avalon-MM DDR target: occasional waitrequest, delayed explicit
    // responses, and one directed SLVERR selected by the test sequence.
    always_ff @(posedge clk or negedge rst_n) begin : p_ddr_target
        integer lane;
        integer byte_offset;
        integer selected_delay;
        if (!rst_n) begin
            cycle_count <= 0;
            accepted_beat_count <= 0;
            okay_response_count <= 0;
            error_response_count <= 0;
            delayed_response_count <= 0;
            response_delay_q <= 0;
            response_delay_max <= 0;
            response_pending_q <= 1'b0;
            pending_response_error_q <= 1'b0;
            avm_waitrequest_i <= 1'b0;
            avm_writeresponsevalid_i <= 1'b0;
            avm_response_i <= AVMM_OKAY;
            trace_saved_count <= 0;
            trace_compare_count <= 0;
            for (lane = 0; lane < RING_BYTES; lane = lane + 1) begin
                ddr_mem[lane] <= 8'h00;
            end
        end else begin
            cycle_count <= cycle_count + 1;
            avm_waitrequest_i <= ((cycle_count % 19) == 5) || ((cycle_count % 19) == 6);
            avm_writeresponsevalid_i <= 1'b0;
            avm_response_i <= AVMM_OKAY;

            if (avm_write_o && !avm_waitrequest_i) begin
                if (response_pending_q) begin
                    fail("DDR master issued a second request while one response was pending");
                end
                if ((avm_address_o < RING_BASE) ||
                    (avm_address_o + 64'd8 > RING_BASE + RING_BYTES)) begin
                    fail("DDR write escaped the configured physical ring");
                end
                if (avm_byteenable_o !== 8'hff || avm_burstcount_o !== 1'b1) begin
                    fail("aligned DDR records must use full byte-enable and burstcount one");
                end
                if (accepted_beat_count >= MAX_BEATS) begin
                    fail("accepted beat log overflow");
                end

                byte_offset = int'(avm_address_o - RING_BASE);
                for (lane = 0; lane < 8; lane = lane + 1) begin
                    if (avm_byteenable_o[lane]) begin
                        ddr_mem[byte_offset + lane] <= avm_writedata_o[(lane * 8) +: 8];
                    end
                end
                beat_addr_log[accepted_beat_count] <= avm_address_o;
                beat_data_log[accepted_beat_count] <= avm_writedata_o;
                beat_byteen_log[accepted_beat_count] <= avm_byteenable_o;

                if (trace_mode == 1) begin
                    if (trace_saved_count >= MAX_TRACE_BEATS) begin
                        fail("deterministic reference trace overflow");
                    end
                    trace_addr[trace_saved_count] <= avm_address_o;
                    trace_data[trace_saved_count] <= avm_writedata_o;
                    trace_byteen[trace_saved_count] <= avm_byteenable_o;
                    trace_saved_count <= trace_saved_count + 1;
                end else if (trace_mode == 2) begin
                    if (trace_compare_count >= trace_saved_count) begin
                        fail("second trace emitted more DDR beats than the reference trace");
                    end
                    if ((avm_address_o !== trace_addr[trace_compare_count]) ||
                        (avm_writedata_o !== trace_data[trace_compare_count]) ||
                        (avm_byteenable_o !== trace_byteen[trace_compare_count])) begin
                        fail("second DDR trace differs from deterministic reference trace");
                    end
                    trace_compare_count <= trace_compare_count + 1;
                end

                accepted_beat_count <= accepted_beat_count + 1;
                selected_delay = 2 + (accepted_beat_count % 4);
                response_delay_q <= selected_delay;
                if (selected_delay > response_delay_max) begin
                    response_delay_max <= selected_delay;
                end
                response_pending_q <= 1'b1;
                pending_response_error_q <= inject_response_error_i;
            end else if (response_pending_q) begin
                if (response_delay_q == 0) begin
                    avm_writeresponsevalid_i <= 1'b1;
                    avm_response_i <= pending_response_error_q ? AVMM_SLVERR : AVMM_OKAY;
                    response_pending_q <= 1'b0;
                    pending_response_error_q <= 1'b0;
                    if (pending_response_error_q) begin
                        error_response_count <= error_response_count + 1;
                    end else begin
                        okay_response_count <= okay_response_count + 1;
                    end
                    delayed_response_count <= delayed_response_count + 1;
                end else begin
                    response_delay_q <= response_delay_q - 1;
                end
            end
        end
    end

    // Avalon requires address/data/byteenable to stay stable for a stalled request.
    always_ff @(posedge clk or negedge rst_n) begin : p_stall_stability
        if (!rst_n) begin
            stalled_write_q <= 1'b0;
            stalled_address_q <= 64'd0;
            stalled_data_q <= 64'd0;
            stalled_byteen_q <= 8'd0;
        end else begin
            if (stalled_write_q) begin
                if (!avm_write_o) begin
                    fail("DDR write deasserted before a stalled request was accepted");
                end else if ((avm_address_o !== stalled_address_q) ||
                             (avm_writedata_o !== stalled_data_q) ||
                             (avm_byteenable_o !== stalled_byteen_q)) begin
                    fail("DDR request changed while waitrequest was asserted");
                end
            end
            if (avm_write_o && avm_waitrequest_i) begin
                stalled_write_q <= 1'b1;
                stalled_address_q <= avm_address_o;
                stalled_data_q <= avm_writedata_o;
                stalled_byteen_q <= avm_byteenable_o;
            end else begin
                stalled_write_q <= 1'b0;
            end
        end
    end

    // Observe public commits. The pointer controller updates W one clock before the
    // writer's public commit pulse; no other W transition is permitted.
    always @(negedge clk) begin : p_ownership_monitor
        logic [63:0] delta;
        logic [63:0] expected_tail;
        if (!rst_n) begin
            observed_w_q = 64'd0;
            observed_rd_q = 64'd0;
            observed_sequence_q = 32'd0;
            w_commit_pending_q = 1'b0;
            w_commit_pending_normal_q = 1'b0;
            w_commit_pending_age_q = 0;
        end else if (telemetry_soft_reset_pulse_o || ring_config_commit_pulse_o ||
                     !ring_configured_o) begin
            observed_w_q = producer_ptr_o;
            observed_rd_q = consumer_ptr_o;
            observed_sequence_q = sequence_o;
            w_commit_pending_q = 1'b0;
            w_commit_pending_age_q = 0;
        end else begin
            if (producer_ptr_o !== observed_w_q) begin
                if (w_commit_pending_q) begin
                    fail("W changed twice without a completed public commit");
                end
                if (response_pending_q || avm_writeresponsevalid_i) begin
                    fail("W advanced before the final delayed OKAY response completed");
                end
                delta = producer_ptr_o - observed_w_q;
                expected_tail = RING_BYTES - (observed_w_q & (RING_BYTES - 1));
                if (sequence_o == (observed_sequence_q + 32'd1)) begin
                    if ((delta != 64'd64) && (delta != 64'd128)) begin
                        fail("normal commit advanced W by an unexpected record length");
                    end
                    w_commit_pending_normal_q = 1'b1;
                end else if (sequence_o == observed_sequence_q) begin
                    if (delta != expected_tail) begin
                        fail("WRAP commit did not advance W by the exact physical tail");
                    end
                    w_commit_pending_normal_q = 1'b0;
                end else begin
                    fail("sequence changed without exactly one normal record commit");
                end
                w_commit_pending_q = 1'b1;
                w_commit_pending_age_q = 0;
                observed_w_q = producer_ptr_o;
                observed_sequence_q = sequence_o;
            end else if (w_commit_pending_q) begin
                if ((w_commit_pending_normal_q && normal_commit_pulse_o) ||
                    (!w_commit_pending_normal_q && wrap_commit_pulse_o)) begin
                    w_commit_pending_q = 1'b0;
                    w_commit_pending_age_q = 0;
                end else begin
                    w_commit_pending_age_q = w_commit_pending_age_q + 1;
                    if (w_commit_pending_age_q > 2) begin
                        fail("W transition was not followed by its public commit pulse");
                    end
                end
            end else if (normal_commit_pulse_o || wrap_commit_pulse_o) begin
                fail("public commit pulse occurred without a corresponding W transition");
            end

            if (consumer_ptr_o !== observed_rd_q) begin
                if (!ring_rd_accept_pulse_o) begin
                    fail("effective Rd changed without an accepted HPS commit");
                end
                observed_rd_q = consumer_ptr_o;
            end
        end
    end

    always_ff @(posedge clk or negedge rst_n) begin : p_event_counters
        if (!rst_n) begin
            normal_commit_count <= 0;
            wrap_commit_count <= 0;
            drop_pulse_count <= 0;
            rd_accept_count <= 0;
            rd_reject_count <= 0;
            last_wrap_w_q <= 64'd0;
            last_wrap_sequence_q <= 32'd0;
        end else begin
            if (normal_commit_pulse_o) begin
                normal_commit_count <= normal_commit_count + 1;
            end
            if (wrap_commit_pulse_o) begin
                wrap_commit_count <= wrap_commit_count + 1;
                last_wrap_w_q <= producer_ptr_o;
                last_wrap_sequence_q <= sequence_o;
            end
            if (writer_drop_pulse_o) begin
                drop_pulse_count <= drop_pulse_count + 1;
            end
            if (ring_rd_accept_pulse_o) begin
                rd_accept_count <= rd_accept_count + 1;
            end
            if (ring_rd_reject_pulse_o) begin
                rd_reject_count <= rd_reject_count + 1;
            end
        end
    end

    task automatic csr_write_expect(
        input logic [31:0] byte_offset,
        input logic [31:0] value,
        input logic [1:0] expected_response
    );
        integer timeout;
        begin
            @(negedge clk);
            timeout = 0;
            while (csr_avs_waitrequest_o && timeout < 1000) begin
                @(negedge clk);
                timeout = timeout + 1;
            end
            if (timeout >= 1000) begin
                fail("timeout waiting for CSR request acceptance");
            end
            csr_avs_address_i = CSR_AVMM_ADDR_W'(byte_offset);
            csr_avs_writedata_i = value;
            csr_avs_byteenable_i = 4'hf;
            csr_avs_burstcount_i = 1'b1;
            csr_avs_read_i = 1'b0;
            csr_avs_write_i = 1'b1;
            @(negedge clk);
            csr_avs_write_i = 1'b0;
            csr_avs_address_i = '0;
            csr_avs_writedata_i = '0;

            timeout = 0;
            while (!csr_avs_writeresponsevalid_o && timeout < 1000) begin
                @(negedge clk);
                timeout = timeout + 1;
            end
            if (timeout >= 1000) begin
                fail("timeout waiting for CSR write response");
            end
            if (csr_avs_response_o !== expected_response) begin
                fail($sformatf("CSR write response mismatch offset=0x%08x got=%0b expected=%0b",
                               byte_offset, csr_avs_response_o, expected_response));
            end
        end
    endtask

    task automatic wait_writer_idle;
        integer timeout;
        begin
            timeout = 0;
            while (!writer_idle_o && timeout < 50000) begin
                @(posedge clk);
                timeout = timeout + 1;
            end
            if (timeout >= 50000) begin
                fail("timeout waiting for DDR writer idle");
            end
        end
    endtask

    task automatic wait_normal_count(input integer target);
        integer timeout;
        begin
            timeout = 0;
            while ((normal_commit_count < target) && timeout < 50000) begin
                @(posedge clk);
                timeout = timeout + 1;
            end
            if (timeout >= 50000) begin
                fail("timeout waiting for normal commit");
            end
        end
    endtask

    task automatic send_record(
        input trecap_packet_type_e packet_type,
        input integer payload_bytes,
        input logic [7:0] seed
    );
        integer payload_offset;
        integer lane;
        integer bytes_this_beat;
        integer timeout;
        logic [31:0] beat_data;
        logic [3:0] beat_keep;
        begin
            record_meta_i = '0;
            record_meta_i.valid = 1'b1;
            record_meta_i.packet_type = packet_type;
            record_meta_i.flags = 16'd0;
            record_meta_i.seq = 32'hffff_ffff;
            record_meta_i.timestamp = {56'd0, seed};
            record_meta_i.payload_bytes = payload_bytes[15:0];
            record_meta_i.drop_priority = trecap_packet_drop_priority(packet_type);

            payload_offset = 0;
            while (payload_offset < payload_bytes) begin
                bytes_this_beat = payload_bytes - payload_offset;
                if (bytes_this_beat > 4) begin
                    bytes_this_beat = 4;
                end
                beat_data = 32'd0;
                beat_keep = 4'd0;
                for (lane = 0; lane < bytes_this_beat; lane = lane + 1) begin
                    beat_data[(lane * 8) +: 8] = seed + payload_offset + lane;
                    beat_keep[lane] = 1'b1;
                end

                @(negedge clk);
                record_valid_i = 1'b1;
                record_payload_data_i = beat_data;
                record_payload_keep_i = beat_keep;
                record_payload_last_i = ((payload_offset + bytes_this_beat) == payload_bytes);
                timeout = 0;
                @(posedge clk);
                while (!record_ready_o && timeout < 50000) begin
                    @(posedge clk);
                    timeout = timeout + 1;
                end
                if (timeout >= 50000) begin
                    fail("timeout waiting for record_ready");
                end
                payload_offset = payload_offset + bytes_this_beat;
            end
            @(negedge clk);
            record_valid_i = 1'b0;
            record_payload_data_i = 32'd0;
            record_payload_keep_i = 4'd0;
            record_payload_last_i = 1'b0;
            record_meta_i = '0;
        end
    endtask

    task automatic configure_ring;
        logic [63:0] owned_rd_before;
        begin
            owned_rd_before = dut.u_ddr_ring_writer.u_ring_pointer_ctrl.consumer_ptr_q;
            csr_write_expect(TCSR_RING_BASE_LO_OFFSET, RING_BASE[31:0], AVMM_OKAY);
            csr_write_expect(TCSR_RING_BASE_HI_OFFSET, RING_BASE[63:32], AVMM_OKAY);
            csr_write_expect(TCSR_RING_SIZE_BYTES_OFFSET, RING_BYTES, AVMM_OKAY);
            csr_write_expect(TCSR_RING_CONFIG_COMMIT_OFFSET, 32'd1, AVMM_OKAY);
            repeat (4) @(posedge clk);
            require_true(ring_configured_o, "ring did not become configured");
            require_true(!pointers_valid_o, "config commit incorrectly established an Rd epoch");
            if (dut.u_ddr_ring_writer.u_ring_pointer_ctrl.consumer_ptr_q !== owned_rd_before) begin
                fail("FPGA config commit overwrote HPS-owned Rd storage");
            end
            if ((producer_ptr_o !== 64'd0) || (consumer_ptr_o !== 64'd0) ||
                (sequence_o !== 32'd0)) begin
                fail("new configuration did not expose deterministic invalid-pointer state");
            end
        end
    endtask

    task automatic commit_rd_expect(input logic [63:0] value, input logic accept);
        logic [63:0] rd_before;
        logic [63:0] w_before;
        logic [31:0] reject_before;
        integer accept_before;
        integer timeout;
        begin
            rd_before = consumer_ptr_o;
            w_before = producer_ptr_o;
            reject_before = csr_command_reject_count_o;
            accept_before = rd_accept_count;
            csr_write_expect(TCSR_RING_RD_LO_SHADOW_OFFSET, value[31:0], AVMM_OKAY);
            csr_write_expect(TCSR_RING_RD_HI_SHADOW_OFFSET, value[63:32], AVMM_OKAY);
            csr_write_expect(TCSR_RING_RD_COMMIT_OFFSET, 32'd1,
                             accept ? AVMM_OKAY : AVMM_SLVERR);
            if (accept) begin
                timeout = 0;
                while ((rd_accept_count == accept_before) && timeout < 1000) begin
                    @(posedge clk);
                    timeout = timeout + 1;
                end
                if (timeout >= 1000) begin
                    fail("accepted HPS Rd commit did not reach the pointer controller");
                end
                if (consumer_ptr_o !== value) begin
                    fail("accepted HPS Rd commit did not update effective Rd");
                end
            end else begin
                repeat (3) @(posedge clk);
                if (consumer_ptr_o !== rd_before) begin
                    fail("rejected HPS Rd commit changed effective Rd");
                end
                if (csr_command_reject_count_o <= reject_before) begin
                    fail("rejected HPS Rd commit was not command-accounted");
                end
            end
            if (producer_ptr_o !== w_before) begin
                fail("HPS Rd commit changed FPGA-owned W");
            end
        end
    endtask

    task automatic enable_writer;
        logic [63:0] w_before;
        logic [31:0] sequence_before;
        begin
            // Required bring-up order: enable the ring-writer level first, prove
            // that this alone cannot admit a record, then enable telemetry.
            csr_write_expect(TCSR_CONTROL_OFFSET,
                             TCSR_CONTROL_RING_WRITER_ENABLE_MASK, AVMM_OKAY);
            repeat (2) @(posedge clk);
            require_true(!ctrl_o.telemetry_enable && ctrl_o.ring_writer_enable,
                         "ring-writer-only control stage did not latch");
            w_before = producer_ptr_o;
            sequence_before = sequence_o;
            record_meta_i = '0;
            record_meta_i.valid = 1'b1;
            record_meta_i.packet_type = TPKT_STATUS;
            record_meta_i.payload_bytes = TPKT_PAYLOAD_STATUS_BYTES;
            record_meta_i.drop_priority = trecap_packet_drop_priority(TPKT_STATUS);
            @(negedge clk);
            record_valid_i = 1'b1;
            record_payload_data_i = 32'h1122_3344;
            record_payload_keep_i = 4'hf;
            record_payload_last_i = 1'b0;
            repeat (3) begin
                @(posedge clk);
                if (record_ready_o) begin
                    fail("ring-writer-only stage admitted a record before telemetry enable");
                end
            end
            @(negedge clk);
            record_valid_i = 1'b0;
            record_payload_data_i = 32'd0;
            record_payload_keep_i = 4'd0;
            record_payload_last_i = 1'b0;
            record_meta_i = '0;
            if ((producer_ptr_o !== w_before) || (sequence_o !== sequence_before)) begin
                fail("ring-writer-only stage changed W or sequence");
            end

            csr_write_expect(TCSR_CONTROL_OFFSET, CONTROL_RUN, AVMM_OKAY);
            repeat (3) @(posedge clk);
            require_true(ctrl_o.telemetry_enable && ctrl_o.ring_writer_enable,
                         "writer controls did not enable after a valid Rd epoch");
        end
    endtask

    task automatic disable_writer;
        begin
            csr_write_expect(TCSR_CONTROL_OFFSET, 32'd0, AVMM_OKAY);
            repeat (2) @(posedge clk);
            require_true(!ctrl_o.telemetry_enable && !ctrl_o.ring_writer_enable,
                         "writer controls did not disable");
        end
    endtask

    task automatic soft_reset_transport(input logic require_prior_nonzero_rd);
        logic [63:0] stored_rd_before;
        begin
            disable_writer();
            wait_writer_idle();
            stored_rd_before = dut.u_ddr_ring_writer.u_ring_pointer_ctrl.consumer_ptr_q;
            if (require_prior_nonzero_rd && (stored_rd_before == 64'd0)) begin
                fail("directed reset did not begin with nonzero stored HPS Rd");
            end
            csr_write_expect(TCSR_CONTROL_OFFSET,
                             TCSR_CONTROL_TELEMETRY_SOFT_RESET_MASK, AVMM_OKAY);
            repeat (5) @(posedge clk);
            if (response_pending_q) begin
                fail("transport reset executed with an outstanding DDR response");
            end
            require_true(!ring_configured_o && !pointers_valid_o,
                         "transport reset did not invalidate ring config/pointer epoch");
            if ((producer_ptr_o !== 64'd0) || (consumer_ptr_o !== 64'd0) ||
                (sequence_o !== 32'd0)) begin
                fail("transport reset did not expose deterministic W/Rd/sequence zeros");
            end
            if (dut.u_ddr_ring_writer.u_ring_pointer_ctrl.consumer_ptr_q !== stored_rd_before) begin
                fail("transport reset overwrote HPS-owned Rd storage");
            end
        end
    endtask

    task automatic run_exact_end_epoch;
        integer normal_before;
        integer wrap_before;
        integer beat_before;
        integer i;
        begin
            configure_ring();
            csr_write_expect(TCSR_CONTROL_OFFSET,
                             TCSR_CONTROL_RING_WRITER_ENABLE_MASK, AVMM_SLVERR);
            require_true(!ctrl_o.telemetry_enable && !ctrl_o.ring_writer_enable,
                         "enable-before-Rd=0 rejection changed control levels");
            commit_rd_expect(64'd0, 1'b1);
            enable_writer();

            normal_before = normal_commit_count;
            for (i = 0; i < 3; i = i + 1) begin
                send_record(TPKT_STATUS, TPKT_PAYLOAD_STATUS_BYTES, 8'h10 + i);
                wait_normal_count(normal_before + i + 1);
            end
            if ((producer_ptr_o !== 64'd384) || (sequence_o !== 32'd3)) begin
                fail("exact-end setup did not reach W=384 sequence=3");
            end
            commit_rd_expect(64'd384, 1'b1);

            wrap_before = wrap_commit_count;
            beat_before = accepted_beat_count;
            send_record(TPKT_STATUS, TPKT_PAYLOAD_STATUS_BYTES, 8'h20);
            wait_normal_count(normal_before + 4);
            wait_writer_idle();
            if ((producer_ptr_o !== 64'd512) || (sequence_o !== 32'd4)) begin
                fail("exact-end normal record did not commit at W=512");
            end
            if (wrap_commit_count != wrap_before) begin
                fail("exact-end record incorrectly emitted WRAP");
            end
            if ((accepted_beat_count - beat_before) != 16) begin
                fail("exact-end 128-byte record did not emit exactly 16 DDR beats");
            end
            for (i = 0; i < 16; i = i + 1) begin
                if (beat_addr_log[beat_before + i] !== (RING_BASE + 64'd384 + (i * 8))) begin
                    fail("exact-end record DDR address trace mismatch");
                end
            end
        end
    endtask

    task automatic run_invalid_rd_epoch;
        integer normal_before;
        begin
            configure_ring();
            commit_rd_expect(64'd0, 1'b1);
            enable_writer();
            normal_before = normal_commit_count;
            send_record(TPKT_STATUS, TPKT_PAYLOAD_STATUS_BYTES, 8'h31);
            wait_normal_count(normal_before + 1);
            commit_rd_expect(64'd64, 1'b1);
            commit_rd_expect(64'd65, 1'b0);
            commit_rd_expect(64'd0, 1'b0);
            commit_rd_expect(64'd192, 1'b0);
            if ((consumer_ptr_o !== 64'd64) || (producer_ptr_o !== 64'd128)) begin
                fail("invalid Rd cases changed ring ownership state");
            end
        end
    endtask

    task automatic run_no_space_epoch;
        integer normal_before;
        integer beat_before;
        integer wrap_before;
        integer drop_before;
        logic [31:0] dma_drop_before;
        begin
            configure_ring();
            commit_rd_expect(64'd0, 1'b1);
            enable_writer();
            normal_before = normal_commit_count;
            send_record(TPKT_STATUS, TPKT_PAYLOAD_STATUS_BYTES, 8'h40);
            wait_normal_count(normal_before + 1);
            commit_rd_expect(64'd128, 1'b1);
            send_record(TPKT_WAVE, TPKT_PAYLOAD_WAVE_MIN_BYTES, 8'h41);
            wait_normal_count(normal_before + 2);
            send_record(TPKT_STATUS, TPKT_PAYLOAD_STATUS_BYTES, 8'h42);
            wait_normal_count(normal_before + 3);
            send_record(TPKT_STATUS, TPKT_PAYLOAD_STATUS_BYTES, 8'h43);
            wait_normal_count(normal_before + 4);
            if ((producer_ptr_o !== 64'd448) || (consumer_ptr_o !== 64'd128) ||
                (free_bytes_o !== 64'd128) || (current_tail_bytes_o !== 64'd64)) begin
                fail("tail+normal no-space setup mismatch");
            end

            beat_before = accepted_beat_count;
            wrap_before = wrap_commit_count;
            drop_before = drop_pulse_count;
            dma_drop_before = dma_drop_count_o;
            send_record(TPKT_STATUS, TPKT_PAYLOAD_STATUS_BYTES, 8'h44);
            wait_writer_idle();
            repeat (5) @(posedge clk);
            if ((accepted_beat_count != beat_before) ||
                (wrap_commit_count != wrap_before) ||
                (normal_commit_count != normal_before + 4)) begin
                fail("insufficient tail+normal free space generated a DDR commit");
            end
            if ((producer_ptr_o !== 64'd448) || (sequence_o !== 32'd4)) begin
                fail("insufficient-space drop changed W or sequence");
            end
            if ((drop_pulse_count != drop_before + 1) ||
                (dma_drop_count_o !== dma_drop_before + 32'd1)) begin
                fail("insufficient-space drop was not counted exactly once");
            end
        end
    endtask

    task automatic run_busy_config_epoch;
        integer normal_before;
        integer timeout;
        logic [31:0] reject_before;
        begin
            configure_ring();
            commit_rd_expect(64'd0, 1'b1);
            enable_writer();
            normal_before = normal_commit_count;
            send_record(TPKT_STATUS, TPKT_PAYLOAD_STATUS_BYTES, 8'h50);
            timeout = 0;
            while (!(writer_busy_o && avm_write_o) && timeout < 50000) begin
                @(posedge clk);
                timeout = timeout + 1;
            end
            if (timeout >= 50000) begin
                fail("timeout waiting for active DDR write in busy-config test");
            end
            disable_writer();
            require_true(writer_busy_o, "writer completed before busy config/shadow rejection test");
            reject_before = csr_command_reject_count_o;
            csr_write_expect(TCSR_RING_BASE_LO_OFFSET, RING_BASE[31:0] + 32'h1000,
                             AVMM_SLVERR);
            require_true(writer_busy_o, "writer completed before busy config commit rejection");
            csr_write_expect(TCSR_RING_CONFIG_COMMIT_OFFSET, 32'd1, AVMM_SLVERR);
            if (csr_command_reject_count_o < reject_before + 32'd2) begin
                fail("busy config/shadow changes were not both command-accounted");
            end
            wait_normal_count(normal_before + 1);
            wait_writer_idle();
            if ((producer_ptr_o !== 64'd128) || !ring_configured_o) begin
                fail("busy config rejection disturbed the in-flight normal commit");
            end
        end
    endtask

    task automatic run_ddr_error_recovery_epoch;
        integer normal_before;
        integer drop_before;
        integer error_before;
        integer beat_before;
        integer timeout;
        logic [31:0] dma_drop_before;
        begin
            configure_ring();
            commit_rd_expect(64'd0, 1'b1);
            enable_writer();
            normal_before = normal_commit_count;
            drop_before = drop_pulse_count;
            error_before = error_response_count;
            beat_before = accepted_beat_count;
            dma_drop_before = dma_drop_count_o;

            @(negedge clk);
            inject_response_error_i = 1'b1;
            send_record(TPKT_STATUS, TPKT_PAYLOAD_STATUS_BYTES, 8'h58);
            timeout = 0;
            while ((error_response_count == error_before) && timeout < 50000) begin
                @(posedge clk);
                timeout = timeout + 1;
            end
            @(negedge clk);
            inject_response_error_i = 1'b0;
            if (timeout >= 50000) begin
                fail("timeout waiting for directed DDR SLVERR response");
            end
            timeout = 0;
            while (!writer_fault_sticky_o && timeout < 50000) begin
                @(posedge clk);
                timeout = timeout + 1;
            end
            if (timeout >= 50000) begin
                fail("DDR SLVERR did not place the writer in fail-closed fault state");
            end
            repeat (4) @(posedge clk);
            if ((producer_ptr_o !== 64'd0) || (sequence_o !== 32'd0) ||
                (normal_commit_count != normal_before)) begin
                fail("DDR SLVERR advanced W/sequence or emitted a normal commit");
            end
            if ((accepted_beat_count != beat_before + 1) ||
                (error_response_count != error_before + 1)) begin
                fail("directed DDR SLVERR was not correlated to exactly one accepted beat");
            end
            if ((drop_pulse_count != drop_before + 1) ||
                (dma_drop_count_o !== dma_drop_before + 32'd1)) begin
                fail("DDR SLVERR fault/drop accounting was not exactly once");
            end

            // Disabling lets the fault state drain to idle; the accepted soft reset
            // then clears the fault and invalidates the transport epoch.
            soft_reset_transport(1'b0);
            require_true(!writer_fault_sticky_o,
                         "transport reset did not clear DDR response fault state");

            configure_ring();
            commit_rd_expect(64'd0, 1'b1);
            enable_writer();
            normal_before = normal_commit_count;
            send_record(TPKT_STATUS, TPKT_PAYLOAD_STATUS_BYTES, 8'h59);
            wait_normal_count(normal_before + 1);
            wait_writer_idle();
            if ((producer_ptr_o !== 64'd128) || (sequence_o !== 32'd1) ||
                writer_fault_sticky_o) begin
                fail("writer did not recover deterministically after DDR SLVERR reset/re-arm");
            end
        end
    endtask

    task automatic check_crossing_bytes(input integer crossing_beat_start);
        integer i;
        begin
            if (mem_u32_le(448 + TPKT_HDR_MAGIC_OFFSET) !== TPKT_TELEMETRY_MAGIC ||
                mem_u16_le(448 + TPKT_HDR_VERSION_OFFSET) !== TPKT_HEADER_VERSION ||
                mem_u16_le(448 + TPKT_HDR_HEADER_BYTES_OFFSET) !== TPKT_HEADER_BYTES ||
                mem_u16_le(448 + TPKT_HDR_PACKET_TYPE_OFFSET) !== TPKT_TYPE_WRAP ||
                mem_u16_le(448 + TPKT_HDR_FLAGS_OFFSET) !== 16'd0 ||
                mem_u32_le(448 + TPKT_HDR_SEQ_OFFSET) !== 32'd0 ||
                mem_u64_le(448 + TPKT_HDR_TIMESTAMP_OFFSET) !== 64'd0 ||
                mem_u32_le(448 + TPKT_HDR_PAYLOAD_BYTES_OFFSET) !== 32'd0 ||
                mem_u32_le(448 + TPKT_HDR_HEADER_CRC_OFFSET) !== 32'd0) begin
                fail("WRAP tail header is not the exact canonical zero-valued WRAP record");
            end
            for (i = 32; i < 64; i = i + 1) begin
                if (ddr_mem[448 + i] !== 8'd0) begin
                    fail("WRAP physical tail padding was not zero-filled");
                end
            end
            for (i = 0; i < 8; i = i + 1) begin
                if (beat_addr_log[crossing_beat_start + i] !==
                    (RING_BASE + 64'd448 + (i * 8))) begin
                    fail("WRAP did not occupy the exact 64-byte tail");
                end
            end
            for (i = 0; i < 16; i = i + 1) begin
                if (beat_addr_log[crossing_beat_start + 8 + i] !==
                    (RING_BASE + (i * 8))) begin
                    fail("post-WRAP normal record did not restart at ring base");
                end
            end
        end
    endtask

    task automatic run_crossing_epoch;
        integer normal_before;
        integer wrap_before;
        integer crossing_beat_start;
        begin
            configure_ring();
            commit_rd_expect(64'd0, 1'b1);
            enable_writer();
            normal_before = normal_commit_count;
            wrap_before = wrap_commit_count;

            send_record(TPKT_STATUS, TPKT_PAYLOAD_STATUS_BYTES, 8'h60);
            wait_normal_count(normal_before + 1);
            send_record(TPKT_WAVE, TPKT_PAYLOAD_WAVE_MIN_BYTES, 8'h61);
            wait_normal_count(normal_before + 2);
            commit_rd_expect(64'd192, 1'b1);
            send_record(TPKT_STATUS, TPKT_PAYLOAD_STATUS_BYTES, 8'h62);
            wait_normal_count(normal_before + 3);
            send_record(TPKT_STATUS, TPKT_PAYLOAD_STATUS_BYTES, 8'h63);
            wait_normal_count(normal_before + 4);
            if ((producer_ptr_o !== 64'd448) || (consumer_ptr_o !== 64'd192) ||
                (free_bytes_o !== 64'd192) || (current_tail_bytes_o !== 64'd64)) begin
                fail("exact-free crossing setup mismatch");
            end

            crossing_beat_start = accepted_beat_count;
            send_record(TPKT_STATUS, TPKT_PAYLOAD_STATUS_BYTES, 8'h64);
            wait_normal_count(normal_before + 5);
            wait_writer_idle();
            if ((wrap_commit_count != wrap_before + 1) ||
                (accepted_beat_count != crossing_beat_start + 24)) begin
                fail("crossing did not emit one 64-byte WRAP plus one 128-byte normal record");
            end
            if ((last_wrap_w_q !== 64'd512) || (last_wrap_sequence_q !== 32'd4)) begin
                fail("WRAP changed sequence or committed the wrong tail pointer");
            end
            if ((producer_ptr_o !== 64'd640) || (sequence_o !== 32'd5)) begin
                fail("post-WRAP normal commit pointer/sequence mismatch");
            end
            check_crossing_bytes(crossing_beat_start);
        end
    endtask

    initial begin : p_test
        integer final_trace_count;
        clk = 1'b0;
        rst_n = 1'b0;
        external_transport_clear_i = 1'b0;
        csr_avs_address_i = '0;
        csr_avs_read_i = 1'b0;
        csr_avs_write_i = 1'b0;
        csr_avs_writedata_i = '0;
        csr_avs_byteenable_i = 4'hf;
        csr_avs_burstcount_i = 1'b1;
        frame_boundary_i = 1'b1;
        source_safe_boundary_i = 1'b1;
        core_alive_i = 1'b1;
        core_frame_count_i = 64'd0;
        core_sample_count_i = 64'd0;
        record_valid_i = 1'b0;
        record_meta_i = '0;
        record_payload_data_i = 32'd0;
        record_payload_keep_i = 4'd0;
        record_payload_last_i = 1'b0;
        packet_fifo_drop_count_i = 32'd0;
        packet_fifo_drop_pulse_i = 1'b0;
        packet_fifo_full_i = 1'b0;
        packet_fifo_overflow_i = 1'b0;
        external_overflow_flags_set_i = 32'd0;
        external_csr_reject_pulse_i = 1'b0;
        inject_response_error_i = 1'b0;
        trace_mode = 0;

        repeat (8) @(posedge clk);
        @(negedge clk);
        rst_n = 1'b1;
        repeat (6) @(posedge clk);
        if (ring_configured_o || pointers_valid_o ||
            (producer_ptr_o !== 64'd0) || (consumer_ptr_o !== 64'd0) ||
            (sequence_o !== 32'd0)) begin
            fail("hard reset did not clear initial ring state");
        end

        run_exact_end_epoch();
        soft_reset_transport(1'b1);

        run_invalid_rd_epoch();
        soft_reset_transport(1'b1);

        run_no_space_epoch();
        soft_reset_transport(1'b1);

        run_busy_config_epoch();
        soft_reset_transport(1'b0);

        run_ddr_error_recovery_epoch();
        soft_reset_transport(1'b0);

        trace_mode = 1;
        run_crossing_epoch();
        final_trace_count = trace_saved_count;
        if (final_trace_count <= 0) begin
            fail("first deterministic DDR trace was empty");
        end
        trace_mode = 0;
        soft_reset_transport(1'b1);

        trace_mode = 2;
        run_crossing_epoch();
        trace_mode = 0;
        if (trace_compare_count != final_trace_count) begin
            fail("second deterministic DDR trace ended at a different beat count");
        end
        wait_writer_idle();
        if (response_pending_q ||
            ((okay_response_count + error_response_count) != accepted_beat_count) ||
            (delayed_response_count != accepted_beat_count) || (response_delay_max < 5)) begin
            fail("delayed explicit DDR response model did not cover every accepted beat");
        end
        if (error_response_count != 1) begin
            fail("directed DDR response-error coverage did not execute exactly once");
        end
        if (writer_fault_sticky_o) begin
            fail("directed legal paths left the DDR writer faulted");
        end
        if (rd_reject_count != 0) begin
            fail("CSR-rejected invalid Rd values leaked into the pointer controller");
        end
        $display("STEP12_DDR_RING_OWNERSHIP_PASS beats=%0d normal=%0d wrap=%0d drops=%0d trace=%0d",
                 accepted_beat_count, normal_commit_count, wrap_commit_count,
                 drop_pulse_count, final_trace_count);
        $finish;
    end

    initial begin : p_watchdog
        repeat (2000000) @(posedge clk);
        fail("global watchdog timeout");
    end

endmodule : tb_trecap_step12_ddr_ring_ownership

`default_nettype wire
