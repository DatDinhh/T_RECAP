// SPDX-License-Identifier: MIT
// File class: [1] hand-written verification RTL.
// Layer: sim/tb/
// Purpose: Step-11 BRAM replay -> core -> STATUS telemetry -> DDR-ring end-to-end regression.

`timescale 1ns/1ps
`default_nettype none

module tb_trecap_step11_bram_e2e
  import trecap_core_pkg::*;
  import trecap_csr_pkg::*;
  import trecap_packet_pkg::*;
  import trecap_iface_pkg::*;
();

    localparam int unsigned EXPECTED_NS             = 1024;
    localparam int unsigned EXPECTED_NY             = 1536;
    localparam int unsigned EXPECTED_TAU_LAST       = 1152;
    localparam int unsigned EXPECTED_FRAMES         = 9;
    localparam int unsigned WATCHDOG_CYCLES         = 1_200_000;
    localparam int unsigned DDR_CAPTURE_BYTES       = 256;
    localparam int unsigned STATUS_RECORD_BYTES     = 128;
    localparam int unsigned EXPECTED_DDR_BEATS      = STATUS_RECORD_BYTES / 8;
    localparam logic [63:0] RING_BASE               = 64'h0000_0000_1000_0000;
    localparam logic [31:0] RING_SIZE_BYTES         = 32'h0010_0000;
    localparam logic [63:0] EXPECTED_PRODUCER_PTR   = STATUS_RECORD_BYTES;
    localparam logic [1:0]  AVMM_RESPONSE_OKAY      = 2'b00;
    localparam logic [1:0]  AVMM_RESPONSE_SLVERR    = 2'b10;
    localparam logic [3:0]  EXPECTED_LATENCY_MASK   = 4'b1111;
    localparam string X_MEMH_FILE =
        "artifacts/test_vectors/impulse_Ns1024_thr0/x_in.memh";
    localparam string Y_MEMH_FILE =
        "artifacts/reference_outputs/impulse_Ns1024_thr0/y_out.memh";

    logic clk;
    logic rst_n;
    logic enable_i;
    logic clear_i;
    logic source_tick_i;
    logic replay_start_i;
    logic status_tick_i;
    logic metrics_tick_i;

    logic [20:0] csr_avs_address_i;
    logic        csr_avs_read_i;
    logic        csr_avs_write_i;
    logic [31:0] csr_avs_writedata_i;
    logic [3:0]  csr_avs_byteenable_i;
    logic [0:0]  csr_avs_burstcount_i;
    logic        csr_avs_waitrequest_o;
    logic [31:0] csr_avs_readdata_o;
    logic        csr_avs_readdatavalid_o;
    logic        csr_avs_writeresponsevalid_o;
    logic [1:0]  csr_avs_response_o;

    logic [63:0] avm_address_o;
    logic        avm_write_o;
    logic [63:0] avm_writedata_o;
    logic [7:0]  avm_byteenable_o;
    logic [0:0]  avm_burstcount_o;
    logic        avm_waitrequest_i;
    logic        avm_writeresponsevalid_i;
    logic [1:0]  avm_response_i;

    logic                         y_valid_o;
    logic                         y_ready_i;
    trecap_sample_t               y_sample_o;
    logic signed [T_SAMPLE_W-1:0] y_data_o;
    logic [63:0]                  y_sample_idx_o;

    logic        replay_source_active_o;
    logic        replay_source_done_o;
    logic        replay_path_busy_o;
    logic        replay_path_done_o;
    logic        replay_path_done_pulse_o;
    logic [63:0] replay_source_accept_count_o;
    logic [63:0] replay_core_output_accept_count_o;
    logic [63:0] replay_expected_output_count_o;
    logic        replay_completion_error_sticky_o;
    logic        replay_e2e_busy_o;
    logic        replay_e2e_done_o;
    logic        replay_e2e_done_pulse_o;
    logic        replay_e2e_error_sticky_o;
    logic [63:0] core_sample_count_o;
    logic [63:0] core_frame_count_o;
    logic [63:0] core_error_sample_count_o;
    logic [31:0] core_overflow_flags_o;
    logic        core_protocol_error_sticky_o;
    logic        source_fault_sticky_o;
    logic        build_contract_error_o;

    trecap_hps_bridge_ctrl_t ctrl_o;
    trecap_ring_config_t     ring_config_o;
    logic [31:0] status_o;
    logic [31:0] dma_status_o;
    logic [31:0] overflow_flags_o;
    logic [31:0] packet_fifo_drop_count_o;
    logic [31:0] dma_drop_count_o;
    logic [31:0] dma_packet_count_o;
    logic [63:0] producer_ptr_o;
    logic [63:0] consumer_ptr_o;
    logic [31:0] sequence_o;
    logic        ring_configured_o;
    logic        writer_busy_o;
    logic        normal_commit_pulse_o;
    logic        wrap_commit_pulse_o;
    logic        full_path_alive_o;

    logic signed [T_SAMPLE_W-1:0] expected_y [0:EXPECTED_NY-1];
    logic [7:0] ddr_mem [0:DDR_CAPTURE_BYTES-1];
    logic       ddr_byte_written [0:DDR_CAPTURE_BYTES-1];

    logic [31:0] sim_cycle_q;
    logic        ddr_response_pending_q;
    logic        ddr_response_valid_q;
    logic [1:0]  ddr_response_code_q;
    logic [3:0]  ddr_response_delay_q;
    logic [1:0]  ddr_response_latency_slot_q;
    logic        normal_commit_seen_q;
    logic [31:0] normal_commit_count_q;
    logic [31:0] ddr_accepted_beats_q;
    logic [31:0] ddr_wait_cycles_q;
    logic [31:0] ddr_response_count_q;
    logic [31:0] ddr_ok_response_count_q;
    logic [31:0] ddr_error_response_count_q;
    logic [31:0] ddr_response_delay_cycles_q;
    logic [3:0]  ddr_response_latency_mask_q;
    logic [63:0] y_accept_count_q;
    logic [31:0] y_stall_cycles_q;
    logic [31:0] done_pulse_count_q;
    logic [31:0] e2e_done_pulse_count_q;
    logic        prior_y_stall_q;
    logic signed [T_SAMPLE_W-1:0] prior_y_data_q;
    logic [63:0] prior_y_idx_q;
    logic        prior_avm_stall_q;
    logic [63:0] prior_avm_address_q;
    logic [63:0] prior_avm_writedata_q;
    logic [7:0]  prior_avm_byteenable_q;
    logic        prior_avm_write_q;
    logic        inject_final_response_error_q;
    logic        negative_fault_window_q;
    logic        negative_epoch_proved_q;

    always #5ns clk = ~clk;

    // Independent deterministic sink pressure. This checks that exact completion is tied to
    // accepted y samples and not merely to source-token exhaustion.
    assign y_ready_i = rst_n && enable_i && !clear_i &&
                       (sim_cycle_q[3:0] != 4'h3) &&
                       (sim_cycle_q[3:0] != 4'hb);

    // Deterministic request backpressure is independent of the delayed response channel below.
    // The write master must hold every request stable and must not commit before all responses.
    assign avm_waitrequest_i = rst_n && !clear_i && avm_write_o &&
        (!prior_avm_write_q || (sim_cycle_q[2:0] == 3'd2) ||
         (sim_cycle_q[2:0] == 3'd5));
    assign avm_writeresponsevalid_i = ddr_response_valid_q;
    assign avm_response_i = ddr_response_code_q;

    trecap_bram_replay_system_top #(
        .X_MEMH_FILE(X_MEMH_FILE),
        .REPLAY_MEM_DEPTH(EXPECTED_NS),
        .REPLAY_INPUT_SAMPLES(EXPECTED_NS),
        .REPLAY_START_ON_RESET_RELEASE(1'b0),
        .REPLAY_RESTART_ALLOWED(1'b0),
        .SAMPLE_RATE_HZ(48_000),
        .RING_SIZE_MIN_BYTES(RING_SIZE_BYTES)
    ) dut (
        .clk(clk),
        .rst_n(rst_n),
        .enable_i(enable_i),
        .clear_i(clear_i),
        .source_tick_i(source_tick_i),
        .replay_start_i(replay_start_i),
        .status_tick_i(status_tick_i),
        .metrics_tick_i(metrics_tick_i),
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
        .avm_address_o(avm_address_o),
        .avm_write_o(avm_write_o),
        .avm_writedata_o(avm_writedata_o),
        .avm_byteenable_o(avm_byteenable_o),
        .avm_burstcount_o(avm_burstcount_o),
        .avm_waitrequest_i(avm_waitrequest_i),
        .avm_writeresponsevalid_i(avm_writeresponsevalid_i),
        .avm_response_i(avm_response_i),
        .y_valid_o(y_valid_o),
        .y_ready_i(y_ready_i),
        .y_sample_o(y_sample_o),
        .y_data_o(y_data_o),
        .y_sample_idx_o(y_sample_idx_o),
        .replay_source_active_o(replay_source_active_o),
        .replay_source_done_o(replay_source_done_o),
        .replay_path_busy_o(replay_path_busy_o),
        .replay_path_done_o(replay_path_done_o),
        .replay_path_done_pulse_o(replay_path_done_pulse_o),
        .replay_source_accept_count_o(replay_source_accept_count_o),
        .replay_core_output_accept_count_o(replay_core_output_accept_count_o),
        .replay_expected_output_count_o(replay_expected_output_count_o),
        .replay_completion_error_sticky_o(replay_completion_error_sticky_o),
        .replay_e2e_busy_o(replay_e2e_busy_o),
        .replay_e2e_done_o(replay_e2e_done_o),
        .replay_e2e_done_pulse_o(replay_e2e_done_pulse_o),
        .replay_e2e_error_sticky_o(replay_e2e_error_sticky_o),
        .core_sample_count_o(core_sample_count_o),
        .core_frame_count_o(core_frame_count_o),
        .core_error_sample_count_o(core_error_sample_count_o),
        .core_overflow_flags_o(core_overflow_flags_o),
        .core_protocol_error_sticky_o(core_protocol_error_sticky_o),
        .source_fault_sticky_o(source_fault_sticky_o),
        .build_contract_error_o(build_contract_error_o),
        .ctrl_o(ctrl_o),
        .ring_config_o(ring_config_o),
        .status_o(status_o),
        .dma_status_o(dma_status_o),
        .overflow_flags_o(overflow_flags_o),
        .packet_fifo_drop_count_o(packet_fifo_drop_count_o),
        .dma_drop_count_o(dma_drop_count_o),
        .dma_packet_count_o(dma_packet_count_o),
        .producer_ptr_o(producer_ptr_o),
        .consumer_ptr_o(consumer_ptr_o),
        .sequence_o(sequence_o),
        .ring_configured_o(ring_configured_o),
        .writer_busy_o(writer_busy_o),
        .normal_commit_pulse_o(normal_commit_pulse_o),
        .wrap_commit_pulse_o(wrap_commit_pulse_o),
        .full_path_alive_o(full_path_alive_o)
    );

    function automatic logic [15:0] ddr_u16_le(input int unsigned off);
        return {ddr_mem[off + 1], ddr_mem[off + 0]};
    endfunction

    function automatic logic [31:0] ddr_u32_le(input int unsigned off);
        return {ddr_mem[off + 3], ddr_mem[off + 2],
                ddr_mem[off + 1], ddr_mem[off + 0]};
    endfunction

    function automatic logic [63:0] ddr_u64_le(input int unsigned off);
        return {ddr_mem[off + 7], ddr_mem[off + 6],
                ddr_mem[off + 5], ddr_mem[off + 4],
                ddr_mem[off + 3], ddr_mem[off + 2],
                ddr_mem[off + 1], ddr_mem[off + 0]};
    endfunction

    // Four deterministic, non-unit response latencies exercise WAIT_RESPONSE for every beat and
    // make it impossible for a request-accept pulse to masquerade as a completed DDR write.
    function automatic logic [3:0] response_delay_for_beat(input logic [31:0] beat_ordinal);
        unique case (beat_ordinal[1:0])
            2'd0: return 4'd2;
            2'd1: return 4'd5;
            2'd2: return 4'd3;
            default: return 4'd7;
        endcase
    endfunction

    task automatic load_expected_y;
        integer fd;
        integer status;
        integer parsed;
        integer row;
        string line;
        logic [T_SAMPLE_W-1:0] value;
        begin
            fd = $fopen(Y_MEMH_FILE, "r");
            if (fd == 0) begin
                $fatal(1, "STEP11_BRAM_E2E_FAIL cannot open %s", Y_MEMH_FILE);
            end
            for (row = 0; row < EXPECTED_NY; row = row + 1) begin
                status = $fgets(line, fd);
                if (status == 0) begin
                    $fatal(1, "STEP11_BRAM_E2E_FAIL y_out.memh short at row %0d", row);
                end
                parsed = $sscanf(line, "%h", value);
                if (parsed != 1) begin
                    $fatal(1, "STEP11_BRAM_E2E_FAIL invalid y_out.memh row %0d", row);
                end
                expected_y[row] = value;
            end
            status = $fgets(line, fd);
            if (status != 0) begin
                $fatal(1, "STEP11_BRAM_E2E_FAIL y_out.memh has extra rows");
            end
            $fclose(fd);
        end
    endtask

    task automatic csr_write32(
        input logic [31:0] offset,
        input logic [31:0] value
    );
        integer wait_cycles;
        begin
            @(negedge clk);
            csr_avs_address_i = offset[20:0];
            csr_avs_writedata_i = value;
            csr_avs_write_i = 1'b1;
            csr_avs_read_i = 1'b0;

            wait_cycles = 0;
            do begin
                @(posedge clk);
                wait_cycles = wait_cycles + 1;
                if (wait_cycles > 32) begin
                    $fatal(1, "STEP11_BRAM_E2E_FAIL CSR write request timeout offset=%08x", offset);
                end
            end while (csr_avs_waitrequest_o !== 1'b0);

            @(negedge clk);
            csr_avs_write_i = 1'b0;
            csr_avs_address_i = '0;
            csr_avs_writedata_i = '0;

            wait_cycles = 0;
            while (csr_avs_writeresponsevalid_o !== 1'b1) begin
                @(negedge clk);
                wait_cycles = wait_cycles + 1;
                if (wait_cycles > 32) begin
                    $fatal(1, "STEP11_BRAM_E2E_FAIL CSR write response timeout offset=%08x", offset);
                end
            end
            if (csr_avs_response_o !== 2'b00) begin
                $fatal(1, "STEP11_BRAM_E2E_FAIL CSR write SLV error offset=%08x response=%b",
                       offset, csr_avs_response_o);
            end
            @(posedge clk);
        end
    endtask

    task automatic csr_read32(
        input  logic [31:0] offset,
        output logic [31:0] value
    );
        integer wait_cycles;
        begin
            @(negedge clk);
            csr_avs_address_i = offset[20:0];
            csr_avs_read_i = 1'b1;
            csr_avs_write_i = 1'b0;

            wait_cycles = 0;
            do begin
                @(posedge clk);
                wait_cycles = wait_cycles + 1;
                if (wait_cycles > 32) begin
                    $fatal(1, "STEP11_BRAM_E2E_FAIL CSR read request timeout offset=%08x", offset);
                end
            end while (csr_avs_waitrequest_o !== 1'b0);

            @(negedge clk);
            csr_avs_read_i = 1'b0;
            csr_avs_address_i = '0;

            wait_cycles = 0;
            while (csr_avs_readdatavalid_o !== 1'b1) begin
                @(negedge clk);
                wait_cycles = wait_cycles + 1;
                if (wait_cycles > 32) begin
                    $fatal(1, "STEP11_BRAM_E2E_FAIL CSR read response timeout offset=%08x", offset);
                end
            end
            if (csr_avs_response_o !== 2'b00) begin
                $fatal(1, "STEP11_BRAM_E2E_FAIL CSR read SLV error offset=%08x response=%b",
                       offset, csr_avs_response_o);
            end
            value = csr_avs_readdata_o;
            @(posedge clk);
        end
    endtask

    task automatic require_csr_value(
        input logic [31:0] offset,
        input logic [31:0] expected
    );
        logic [31:0] observed;
        begin
            csr_read32(offset, observed);
            if (observed !== expected) begin
                $fatal(1,
                       "STEP11_BRAM_E2E_FAIL CSR mismatch offset=%08x got=%08x expected=%08x",
                       offset, observed, expected);
            end
        end
    endtask

    task automatic configure_revision_g_status_ring;
        logic [31:0] observed;
        begin
            require_csr_value(TCSR_ID_OFFSET, TCSR_ID_VALUE);
            require_csr_value(TCSR_VERSION_OFFSET, TCSR_VERSION_VALUE);

            csr_write32(TCSR_CONTROL_OFFSET, 32'd0);
            csr_write32(TCSR_CONTROL_OFFSET, TCSR_CONTROL_TELEMETRY_SOFT_RESET_MASK);
            csr_write32(TCSR_RING_BASE_LO_OFFSET, RING_BASE[31:0]);
            csr_write32(TCSR_RING_BASE_HI_OFFSET, RING_BASE[63:32]);
            csr_write32(TCSR_RING_SIZE_BYTES_OFFSET, RING_SIZE_BYTES);
            csr_write32(TCSR_RING_CONFIG_COMMIT_OFFSET, 32'd1);
            csr_write32(TCSR_RING_RD_LO_SHADOW_OFFSET, 32'd0);
            csr_write32(TCSR_RING_RD_HI_SHADOW_OFFSET, 32'd0);
            csr_write32(TCSR_RING_RD_COMMIT_OFFSET, 32'd1);
            csr_write32(TCSR_RING_WR_SNAPSHOT_OFFSET, 32'd1);
            require_csr_value(TCSR_RING_WR_LO_SNAP_OFFSET, 32'd0);
            require_csr_value(TCSR_RING_WR_HI_SNAP_OFFSET, 32'd0);

            // Make the impulse test's THR2=0 and STATUS-only telemetry explicit through the
            // Revision-G programming model rather than relying on reset values.
            csr_write32(TCSR_THR2_LO_OFFSET, 32'd0);
            csr_write32(TCSR_THR2_HI_OFFSET, 32'd0);
            csr_write32(TCSR_THR2_COMMIT_OFFSET, 32'd1);
            csr_write32(TCSR_PACKET_ENABLE_OFFSET, TCSR_PACKET_ENABLE_STATUS_EN_MASK);
            csr_write32(TCSR_WAVE_DECIM_OFFSET, 32'd1);
            csr_write32(TCSR_SPEC_MODE_OFFSET, TCSR_SPEC_MODE_SPEC_DISABLED);
            csr_write32(TCSR_SPEC_SHIFT_OFFSET, 32'd0);
            csr_write32(
                TCSR_CONTROL_OFFSET,
                TCSR_CONTROL_TELEMETRY_ENABLE_MASK |
                TCSR_CONTROL_RING_WRITER_ENABLE_MASK
            );

            require_csr_value(
                TCSR_CONTROL_OFFSET,
                TCSR_CONTROL_TELEMETRY_ENABLE_MASK |
                TCSR_CONTROL_RING_WRITER_ENABLE_MASK
            );
            require_csr_value(TCSR_PACKET_ENABLE_OFFSET, TCSR_PACKET_ENABLE_STATUS_EN_MASK);
            csr_read32(TCSR_STATUS_OFFSET, observed);
            if ((observed & (TCSR_STATUS_TELEMETRY_ENABLED_MASK |
                             TCSR_STATUS_RING_WRITER_ENABLED_MASK |
                             TCSR_STATUS_RING_CONFIGURED_MASK)) !==
                (TCSR_STATUS_TELEMETRY_ENABLED_MASK |
                 TCSR_STATUS_RING_WRITER_ENABLED_MASK |
                 TCSR_STATUS_RING_CONFIGURED_MASK)) begin
                $fatal(1, "STEP11_BRAM_E2E_FAIL CSR status did not enable/configure ring: %08x",
                       observed);
            end
        end
    endtask

    task automatic check_exact_completion;
        begin
            if ((replay_source_done_o !== 1'b1) ||
                (replay_source_active_o !== 1'b0) ||
                (replay_path_done_o !== 1'b1) || (replay_path_busy_o !== 1'b0)) begin
                $fatal(1, "STEP11_BRAM_E2E_FAIL source/path done/busy completion state");
            end
            if ((y_accept_count_q !== 64'(EXPECTED_NY)) ||
                (replay_core_output_accept_count_o !== 64'(EXPECTED_NY)) ||
                (replay_source_accept_count_o !== 64'(EXPECTED_NY)) ||
                (replay_expected_output_count_o !== 64'(EXPECTED_NY)) ||
                (core_error_sample_count_o !== 64'(EXPECTED_NY)) ||
                (core_sample_count_o !== 64'(EXPECTED_TAU_LAST)) ||
                (core_frame_count_o !== 64'(EXPECTED_FRAMES))) begin
                $fatal(1,
                       "STEP11_BRAM_E2E_FAIL exact counts y=%0d core_y=%0d source=%0d expected=%0d err=%0d sample=%0d frame=%0d",
                       y_accept_count_q, replay_core_output_accept_count_o,
                       replay_source_accept_count_o, replay_expected_output_count_o,
                       core_error_sample_count_o, core_sample_count_o, core_frame_count_o);
            end
            if ((y_stall_cycles_q === 32'd0) || (^y_stall_cycles_q === 1'bx)) begin
                $fatal(1, "STEP11_BRAM_E2E_FAIL y backpressure was not exercised");
            end
            // The STATUS request is injected from replay_path_done_pulse_o. No transport commit
            // may precede this exact core-completion boundary.
            if ((ddr_accepted_beats_q !== 32'd0) || (ddr_response_count_q !== 32'd0) ||
                (normal_commit_count_q !== 32'd0) || (producer_ptr_o !== 64'd0) ||
                (sequence_o !== 32'd0) || (dma_packet_count_o !== 32'd0)) begin
                $fatal(1, "STEP11_BRAM_E2E_FAIL DDR transport started before exact replay completion");
            end
            if ((replay_completion_error_sticky_o !== 1'b0) ||
                (core_protocol_error_sticky_o !== 1'b0) ||
                (source_fault_sticky_o !== 1'b0) ||
                (build_contract_error_o !== 1'b0) ||
                (core_overflow_flags_o !== 32'd0) ||
                (overflow_flags_o !== 32'd0) ||
                (packet_fifo_drop_count_o !== 32'd0) ||
                (dma_drop_count_o !== 32'd0)) begin
                $fatal(1,
                       "STEP11_BRAM_E2E_FAIL replay/core/telemetry fault completion=%b protocol=%b source=%b build=%b core_of=%08x csr_of=%08x fifo_drop=%0d dma_drop=%0d",
                       replay_completion_error_sticky_o, core_protocol_error_sticky_o,
                       source_fault_sticky_o, build_contract_error_o,
                       core_overflow_flags_o,
                       overflow_flags_o, packet_fifo_drop_count_o, dma_drop_count_o);
            end
        end
    endtask

    task automatic check_status_record;
        integer byte_idx;
        logic [31:0] wr_lo;
        logic [31:0] wr_hi;
        logic [31:0] status_required;
        logic [31:0] status_forbidden;
        logic [31:0] dma_forbidden;
        begin
            if ((normal_commit_seen_q !== 1'b1) ||
                (^normal_commit_count_q === 1'bx) ||
                (normal_commit_count_q != 32'd1)) begin
                $fatal(1, "STEP11_BRAM_E2E_FAIL expected exactly one normal DDR commit");
            end
            if ((wrap_commit_pulse_o !== 1'b0) ||
                (producer_ptr_o !== EXPECTED_PRODUCER_PTR) ||
                (consumer_ptr_o !== 64'd0) || (sequence_o !== 32'd1) ||
                (^dma_packet_count_o === 1'bx) ||
                (dma_packet_count_o != 32'd1)) begin
                $fatal(1,
                       "STEP11_BRAM_E2E_FAIL DDR commit state W=%0d Rd=%0d seq=%0d packets=%0d",
                       producer_ptr_o, consumer_ptr_o, sequence_o, dma_packet_count_o);
            end
            if ((ddr_accepted_beats_q !== 32'(EXPECTED_DDR_BEATS)) ||
                (ddr_wait_cycles_q === 32'd0) || (^ddr_wait_cycles_q === 1'bx)) begin
                $fatal(1, "STEP11_BRAM_E2E_FAIL DDR model coverage beats=%0d waits=%0d",
                       ddr_accepted_beats_q, ddr_wait_cycles_q);
            end
            if ((ddr_response_count_q !== 32'(EXPECTED_DDR_BEATS)) ||
                (ddr_ok_response_count_q !== 32'(EXPECTED_DDR_BEATS)) ||
                (ddr_error_response_count_q !== 32'd0) ||
                (ddr_response_latency_mask_q !== EXPECTED_LATENCY_MASK) ||
                (ddr_response_delay_cycles_q <= 32'(EXPECTED_DDR_BEATS)) ||
                (ddr_response_pending_q !== 1'b0) || (ddr_response_valid_q !== 1'b0)) begin
                $fatal(1,
                       "STEP11_BRAM_E2E_FAIL delayed OK response coverage rsp=%0d ok=%0d err=%0d latency_mask=%b delay_cycles=%0d",
                       ddr_response_count_q, ddr_ok_response_count_q,
                       ddr_error_response_count_q, ddr_response_latency_mask_q,
                       ddr_response_delay_cycles_q);
            end
            status_required = TCSR_STATUS_TELEMETRY_ENABLED_MASK |
                              TCSR_STATUS_RING_WRITER_ENABLED_MASK |
                              TCSR_STATUS_RING_CONFIGURED_MASK;
            status_forbidden = TCSR_STATUS_WRITER_BUSY_MASK |
                               TCSR_STATUS_MALFORMED_CONFIG_MASK |
                               TCSR_STATUS_RING_FULL_MASK |
                               TCSR_STATUS_PACKET_FIFO_FULL_MASK |
                               TCSR_STATUS_THR2_COMMIT_PENDING_MASK |
                               TCSR_STATUS_SOURCE_COMMIT_PENDING_MASK;
            dma_forbidden = TCSR_DMA_STATUS_WRITER_BUSY_MASK |
                            TCSR_DMA_STATUS_NO_SPACE_MASK |
                            TCSR_DMA_STATUS_MALFORMED_CONFIG_MASK |
                            TCSR_DMA_STATUS_RING_FULL_MASK |
                            TCSR_DMA_STATUS_PACKET_FIFO_FULL_MASK |
                            TCSR_DMA_STATUS_DDR_WAIT_MASK |
                            TCSR_DMA_STATUS_DROP_ACTIVE_MASK;
            if (((status_o & status_required) !== status_required) ||
                ((status_o & status_forbidden) !== 32'd0) ||
                ((dma_status_o & TCSR_DMA_STATUS_WRITER_IDLE_MASK) !==
                 TCSR_DMA_STATUS_WRITER_IDLE_MASK) ||
                ((dma_status_o & dma_forbidden) !== 32'd0)) begin
                $fatal(1, "STEP11_BRAM_E2E_FAIL terminal CSR/DMA status status=%08x dma=%08x",
                       status_o, dma_status_o);
            end
            for (byte_idx = 0; byte_idx < STATUS_RECORD_BYTES; byte_idx = byte_idx + 1) begin
                if (ddr_byte_written[byte_idx] !== 1'b1) begin
                    $fatal(1, "STEP11_BRAM_E2E_FAIL unwritten committed DDR byte %0d", byte_idx);
                end
            end

            if ((ddr_u32_le(TPKT_HDR_MAGIC_OFFSET) !== TPKT_TELEMETRY_MAGIC) ||
                (ddr_u16_le(TPKT_HDR_VERSION_OFFSET) !== 16'(TPKT_HEADER_VERSION)) ||
                (ddr_u16_le(TPKT_HDR_HEADER_BYTES_OFFSET) !== 16'(TPKT_HEADER_BYTES)) ||
                (ddr_u16_le(TPKT_HDR_PACKET_TYPE_OFFSET) !== TPKT_TYPE_STATUS) ||
                (ddr_u16_le(TPKT_HDR_FLAGS_OFFSET) !== 16'd0) ||
                (ddr_u32_le(TPKT_HDR_SEQ_OFFSET) !== 32'd0) ||
                (ddr_u64_le(TPKT_HDR_TIMESTAMP_OFFSET) !== 64'(EXPECTED_TAU_LAST)) ||
                (ddr_u32_le(TPKT_HDR_PAYLOAD_BYTES_OFFSET) !==
                 32'(TPKT_PAYLOAD_STATUS_BYTES)) ||
                (ddr_u32_le(TPKT_HDR_HEADER_CRC_OFFSET) !== 32'd0)) begin
                $fatal(1, "STEP11_BRAM_E2E_FAIL malformed committed STATUS header");
            end

            // Full STATUS payload parsing is intentionally part of this regression. These two
            // authoritative fields prove the post-replay tick observed tau_last=1152 and 9 frames.
            if ((ddr_u64_le(TPKT_HEADER_BYTES + TPKT_STATUS_SAMPLE_COUNT_OFFSET) !==
                 64'(EXPECTED_TAU_LAST)) ||
                (ddr_u64_le(TPKT_HEADER_BYTES + TPKT_STATUS_FRAME_COUNT_OFFSET) !==
                 64'(EXPECTED_FRAMES)) ||
                (ddr_u32_le(TPKT_HEADER_BYTES + TPKT_STATUS_SOURCE_MODE_OFFSET) !==
                 32'(TCSR_SOURCE_MODE_BRAM_REPLAY)) ||
                (ddr_u32_le(TPKT_HEADER_BYTES + TPKT_STATUS_SAMPLE_RATE_OFFSET) !== 32'd48_000) ||
                (ddr_u32_le(TPKT_HEADER_BYTES + TPKT_STATUS_PACKET_ENABLE_OFFSET) !==
                 TCSR_PACKET_ENABLE_STATUS_EN_MASK) ||
                (ddr_u32_le(TPKT_HEADER_BYTES + TPKT_STATUS_DMA_DROP_COUNT_OFFSET) !== 32'd0) ||
                (ddr_u32_le(TPKT_HEADER_BYTES + TPKT_STATUS_UDP_SEND_ERROR_COUNT_OFFSET) !==
                 32'd0) ||
                (ddr_u32_le(TPKT_HEADER_BYTES + TPKT_STATUS_MALFORMED_RECORD_COUNT_OFFSET) !==
                 32'd0) ||
                (ddr_u32_le(TPKT_HEADER_BYTES + TPKT_STATUS_OVERSIZED_RECORD_COUNT_OFFSET) !==
                 32'd0) ||
                (ddr_u32_le(TPKT_HEADER_BYTES + TPKT_STATUS_COMMAND_REJECT_COUNT_OFFSET) !== 32'd0) ||
                (ddr_u32_le(TPKT_HEADER_BYTES + TPKT_STATUS_SEQUENCE_GAP_COUNT_OFFSET) !==
                 32'd0) ||
                (ddr_u32_le(TPKT_HEADER_BYTES + TPKT_STATUS_OVERFLOW_FLAGS_OFFSET) !== 32'd0) ||
                (ddr_u32_le(TPKT_HEADER_BYTES + TPKT_STATUS_THR2_LO_OFFSET) !== 32'd0) ||
                (ddr_u32_le(TPKT_HEADER_BYTES + TPKT_STATUS_THR2_HI_OFFSET) !== 32'd0) ||
                (ddr_u32_le(TPKT_HEADER_BYTES + TPKT_STATUS_PACKET_FIFO_DROP_COUNT_OFFSET) !==
                 32'd0) ||
                (ddr_u32_le(TPKT_HEADER_BYTES + TPKT_STATUS_RESERVED_OFFSET) !== 32'd0)) begin
                $fatal(1, "STEP11_BRAM_E2E_FAIL committed STATUS payload mismatch");
            end
            for (byte_idx = TPKT_HEADER_BYTES + TPKT_PAYLOAD_STATUS_BYTES;
                 byte_idx < STATUS_RECORD_BYTES; byte_idx = byte_idx + 1) begin
                if (ddr_mem[byte_idx] !== 8'd0) begin
                    $fatal(1, "STEP11_BRAM_E2E_FAIL nonzero DDR padding byte %0d", byte_idx);
                end
            end

            csr_write32(TCSR_RING_WR_SNAPSHOT_OFFSET, 32'd1);
            csr_read32(TCSR_RING_WR_LO_SNAP_OFFSET, wr_lo);
            csr_read32(TCSR_RING_WR_HI_SNAP_OFFSET, wr_hi);
            if ({wr_hi, wr_lo} !== EXPECTED_PRODUCER_PTR) begin
                $fatal(1, "STEP11_BRAM_E2E_FAIL HPS-visible producer snapshot=%016x",
                       {wr_hi, wr_lo});
            end
        end
    endtask

    task automatic check_negative_final_response_error;
        integer wait_cycles;
        integer byte_idx;
        logic [31:0] expected_fault_flags;
        begin
            wait_cycles = 0;
            while (((ddr_error_response_count_q !== 32'd1) ||
                    (replay_e2e_error_sticky_o !== 1'b1)) &&
                   (wait_cycles < 4096)) begin
                @(negedge clk);
                wait_cycles = wait_cycles + 1;
            end
            if (wait_cycles >= 4096) begin
                $fatal(1, "STEP11_BRAM_E2E_FAIL delayed final SLVERR timeout");
            end
            repeat (4) @(negedge clk);

            expected_fault_flags = TCSR_OVERFLOW_FLAGS_RING_OVERFLOW_MASK |
                                   TCSR_OVERFLOW_FLAGS_MALFORMED_PACKET_MASK |
                                   TCSR_OVERFLOW_FLAGS_CDC_ERROR_MASK;
            if ((replay_path_done_o !== 1'b1) || (done_pulse_count_q !== 32'd1) ||
                (replay_e2e_done_o !== 1'b0) || (e2e_done_pulse_count_q !== 32'd0) ||
                (replay_e2e_error_sticky_o !== 1'b1)) begin
                $fatal(1, "STEP11_BRAM_E2E_FAIL negative epoch E2E terminal state");
            end
            if ((normal_commit_seen_q !== 1'b0) || (normal_commit_count_q !== 32'd0) ||
                (producer_ptr_o !== 64'd0) || (consumer_ptr_o !== 64'd0) ||
                (sequence_o !== 32'd0) || (dma_packet_count_o !== 32'd0)) begin
                $fatal(1, "STEP11_BRAM_E2E_FAIL delayed SLVERR allowed producer commit");
            end
            if ((ddr_accepted_beats_q !== 32'(EXPECTED_DDR_BEATS)) ||
                (ddr_response_count_q !== 32'(EXPECTED_DDR_BEATS)) ||
                (ddr_ok_response_count_q !== 32'(EXPECTED_DDR_BEATS - 1)) ||
                (ddr_error_response_count_q !== 32'd1) ||
                (ddr_response_latency_mask_q !== EXPECTED_LATENCY_MASK) ||
                (ddr_response_delay_cycles_q <= 32'(EXPECTED_DDR_BEATS)) ||
                (ddr_wait_cycles_q === 32'd0) ||
                (ddr_response_pending_q !== 1'b0) || (ddr_response_valid_q !== 1'b0)) begin
                $fatal(1,
                       "STEP11_BRAM_E2E_FAIL delayed SLVERR coverage beats=%0d rsp=%0d ok=%0d err=%0d latency_mask=%b delays=%0d waits=%0d",
                       ddr_accepted_beats_q, ddr_response_count_q,
                       ddr_ok_response_count_q, ddr_error_response_count_q,
                       ddr_response_latency_mask_q, ddr_response_delay_cycles_q,
                       ddr_wait_cycles_q);
            end
            if ((dma_drop_count_o !== 32'd1) ||
                ((overflow_flags_o & expected_fault_flags) !== expected_fault_flags) ||
                (packet_fifo_drop_count_o !== 32'd0)) begin
                $fatal(1,
                       "STEP11_BRAM_E2E_FAIL delayed SLVERR fault evidence overflow=%08x dma_drop=%0d fifo_drop=%0d",
                       overflow_flags_o, dma_drop_count_o, packet_fifo_drop_count_o);
            end
            for (byte_idx = 0; byte_idx < STATUS_RECORD_BYTES; byte_idx = byte_idx + 1) begin
                if (ddr_byte_written[byte_idx] !== 1'b1) begin
                    $fatal(1,
                           "STEP11_BRAM_E2E_FAIL final SLVERR was not delayed past byte %0d",
                           byte_idx);
                end
            end

            $display("STEP11_BRAM_E2E_NEGATIVE_PASS final_delayed_slverr=1 normal_commits=0 producer_ptr=0 e2e_error_sticky=1");
        end
    endtask

    always_ff @(posedge clk or negedge rst_n) begin : p_ddr_model
        integer lane;
        integer offset;
        if (!rst_n) begin
            sim_cycle_q <= 32'd0;
            ddr_response_pending_q <= 1'b0;
            ddr_response_valid_q <= 1'b0;
            ddr_response_code_q <= AVMM_RESPONSE_OKAY;
            ddr_response_delay_q <= 4'd0;
            ddr_response_latency_slot_q <= 2'd0;
            normal_commit_seen_q <= 1'b0;
            normal_commit_count_q <= 32'd0;
            ddr_accepted_beats_q <= 32'd0;
            ddr_wait_cycles_q <= 32'd0;
            ddr_response_count_q <= 32'd0;
            ddr_ok_response_count_q <= 32'd0;
            ddr_error_response_count_q <= 32'd0;
            ddr_response_delay_cycles_q <= 32'd0;
            ddr_response_latency_mask_q <= 4'd0;
            prior_avm_stall_q <= 1'b0;
            prior_avm_address_q <= 64'd0;
            prior_avm_writedata_q <= 64'd0;
            prior_avm_byteenable_q <= 8'd0;
            prior_avm_write_q <= 1'b0;
            for (lane = 0; lane < DDR_CAPTURE_BYTES; lane = lane + 1) begin
                ddr_mem[lane] <= 8'd0;
                ddr_byte_written[lane] <= 1'b0;
            end
        end else if (clear_i) begin
            sim_cycle_q <= 32'd0;
            ddr_response_pending_q <= 1'b0;
            ddr_response_valid_q <= 1'b0;
            ddr_response_code_q <= AVMM_RESPONSE_OKAY;
            ddr_response_delay_q <= 4'd0;
            ddr_response_latency_slot_q <= 2'd0;
            normal_commit_seen_q <= 1'b0;
            normal_commit_count_q <= 32'd0;
            ddr_accepted_beats_q <= 32'd0;
            ddr_wait_cycles_q <= 32'd0;
            ddr_response_count_q <= 32'd0;
            ddr_ok_response_count_q <= 32'd0;
            ddr_error_response_count_q <= 32'd0;
            ddr_response_delay_cycles_q <= 32'd0;
            ddr_response_latency_mask_q <= 4'd0;
            prior_avm_stall_q <= 1'b0;
            prior_avm_address_q <= 64'd0;
            prior_avm_writedata_q <= 64'd0;
            prior_avm_byteenable_q <= 8'd0;
            prior_avm_write_q <= 1'b0;
            for (lane = 0; lane < DDR_CAPTURE_BYTES; lane = lane + 1) begin
                ddr_mem[lane] <= 8'd0;
                ddr_byte_written[lane] <= 1'b0;
            end
        end else begin
            sim_cycle_q <= sim_cycle_q + 32'd1;
            ddr_response_valid_q <= 1'b0;

            if (ddr_response_pending_q) begin
                ddr_response_delay_cycles_q <= ddr_response_delay_cycles_q + 32'd1;
                if (avm_write_o) begin
                    $fatal(1, "STEP11_BRAM_E2E_FAIL write issued with response outstanding");
                end
                if (ddr_response_delay_q == 4'd0) begin
                    ddr_response_pending_q <= 1'b0;
                    ddr_response_valid_q <= 1'b1;
                    ddr_response_count_q <= ddr_response_count_q + 32'd1;
                    ddr_response_latency_mask_q[ddr_response_latency_slot_q] <= 1'b1;
                    if (ddr_response_code_q == AVMM_RESPONSE_OKAY) begin
                        ddr_ok_response_count_q <= ddr_ok_response_count_q + 32'd1;
                    end else begin
                        ddr_error_response_count_q <= ddr_error_response_count_q + 32'd1;
                    end
                end else begin
                    ddr_response_delay_q <= ddr_response_delay_q - 4'd1;
                end
            end

            if (avm_write_o && avm_waitrequest_i) begin
                ddr_wait_cycles_q <= ddr_wait_cycles_q + 32'd1;
            end
            if (prior_avm_stall_q &&
                (!avm_write_o || (avm_address_o !== prior_avm_address_q) ||
                 (avm_writedata_o !== prior_avm_writedata_q) ||
                 (avm_byteenable_o !== prior_avm_byteenable_q))) begin
                $fatal(1, "STEP11_BRAM_E2E_FAIL Avalon write changed while waitrequest asserted");
            end
            prior_avm_stall_q <= avm_write_o && avm_waitrequest_i;
            prior_avm_address_q <= avm_address_o;
            prior_avm_writedata_q <= avm_writedata_o;
            prior_avm_byteenable_q <= avm_byteenable_o;
            prior_avm_write_q <= avm_write_o;

            if (avm_write_o && !avm_waitrequest_i) begin
                if (ddr_response_pending_q || ddr_response_valid_q) begin
                    $fatal(1, "STEP11_BRAM_E2E_FAIL accepted write before prior response retired");
                end
                if ((^avm_address_o === 1'bx) || (^avm_writedata_o === 1'bx) ||
                    (^avm_byteenable_o === 1'bx) || (avm_burstcount_o !== 1'b1) ||
                    (avm_address_o < RING_BASE) ||
                    (avm_address_o >= (RING_BASE + DDR_CAPTURE_BYTES))) begin
                    $fatal(1, "STEP11_BRAM_E2E_FAIL illegal accepted DDR write addr=%016x",
                           avm_address_o);
                end
                offset = int'(avm_address_o - RING_BASE);
                for (lane = 0; lane < 8; lane = lane + 1) begin
                    if (avm_byteenable_o[lane]) begin
                        if ((offset + lane) >= DDR_CAPTURE_BYTES) begin
                            $fatal(1, "STEP11_BRAM_E2E_FAIL DDR byte lane outside capture");
                        end
                        if (ddr_byte_written[offset + lane]) begin
                            $fatal(1, "STEP11_BRAM_E2E_FAIL duplicate DDR byte write %0d",
                                   offset + lane);
                        end
                        ddr_mem[offset + lane] <= avm_writedata_o[8*lane +: 8];
                        ddr_byte_written[offset + lane] <= 1'b1;
                    end
                end
                ddr_accepted_beats_q <= ddr_accepted_beats_q + 32'd1;
                ddr_response_pending_q <= 1'b1;
                ddr_response_delay_q <= response_delay_for_beat(ddr_accepted_beats_q);
                ddr_response_latency_slot_q <= ddr_accepted_beats_q[1:0];
                if (inject_final_response_error_q &&
                    (ddr_accepted_beats_q == 32'(EXPECTED_DDR_BEATS - 1))) begin
                    ddr_response_code_q <= AVMM_RESPONSE_SLVERR;
                end else begin
                    ddr_response_code_q <= AVMM_RESPONSE_OKAY;
                end
            end

            if (normal_commit_pulse_o) begin
                normal_commit_seen_q <= 1'b1;
                normal_commit_count_q <= normal_commit_count_q + 32'd1;
            end
            if (wrap_commit_pulse_o) begin
                $fatal(1, "STEP11_BRAM_E2E_FAIL unexpected WRAP commit");
            end
        end
    end

    always_ff @(posedge clk or negedge rst_n) begin : p_y_scoreboard
        if (!rst_n) begin
            y_accept_count_q <= 64'd0;
            y_stall_cycles_q <= 32'd0;
            done_pulse_count_q <= 32'd0;
            e2e_done_pulse_count_q <= 32'd0;
            prior_y_stall_q <= 1'b0;
            prior_y_data_q <= '0;
            prior_y_idx_q <= 64'd0;
        end else if (clear_i) begin
            y_accept_count_q <= 64'd0;
            y_stall_cycles_q <= 32'd0;
            done_pulse_count_q <= 32'd0;
            e2e_done_pulse_count_q <= 32'd0;
            prior_y_stall_q <= 1'b0;
            prior_y_data_q <= '0;
            prior_y_idx_q <= 64'd0;
        end else begin
            if ((y_sample_o.valid !== y_valid_o) ||
                (y_sample_o.data !== y_data_o) ||
                (y_sample_o.sample_idx !== y_sample_idx_o)) begin
                $fatal(1, "STEP11_BRAM_E2E_FAIL y struct/breakout divergence");
            end
            if (prior_y_stall_q &&
                (!y_valid_o || (y_data_o !== prior_y_data_q) ||
                 (y_sample_idx_o !== prior_y_idx_q))) begin
                $fatal(1, "STEP11_BRAM_E2E_FAIL y payload changed under backpressure");
            end
            prior_y_stall_q <= y_valid_o && !y_ready_i;
            prior_y_data_q <= y_data_o;
            prior_y_idx_q <= y_sample_idx_o;

            if (y_valid_o && !y_ready_i) begin
                y_stall_cycles_q <= y_stall_cycles_q + 32'd1;
            end

            if (y_valid_o && y_ready_i) begin
                if ((^y_data_o === 1'bx) || (^y_sample_idx_o === 1'bx) ||
                    (y_accept_count_q >= EXPECTED_NY)) begin
                    $fatal(1, "STEP11_BRAM_E2E_FAIL invalid/extra accepted y sample");
                end
                if (y_sample_idx_o !== y_accept_count_q) begin
                    $fatal(1, "STEP11_BRAM_E2E_FAIL y index got=%0d expected=%0d",
                           y_sample_idx_o, y_accept_count_q);
                end
                if (y_data_o !== expected_y[y_accept_count_q]) begin
                    $fatal(1, "STEP11_BRAM_E2E_FAIL y[%0d] got=%0d expected=%0d",
                           y_accept_count_q, y_data_o, expected_y[y_accept_count_q]);
                end
                y_accept_count_q <= y_accept_count_q + 64'd1;
            end

            if (replay_path_done_pulse_o) begin
                done_pulse_count_q <= done_pulse_count_q + 32'd1;
                if (done_pulse_count_q !== 32'd0) begin
                    $fatal(1, "STEP11_BRAM_E2E_FAIL duplicate replay done pulse");
                end
            end
            if (replay_e2e_done_pulse_o) begin
                e2e_done_pulse_count_q <= e2e_done_pulse_count_q + 32'd1;
                if (e2e_done_pulse_count_q !== 32'd0) begin
                    $fatal(1, "STEP11_BRAM_E2E_FAIL duplicate E2E done pulse");
                end
            end
        end
    end

    // Unknowns on valid/control/status signals are failures, not don't-cares. Payload buses are
    // checked whenever their valid/write qualifier is asserted so an X cannot evade a scoreboard
    // comparison through four-state if-expression semantics.
    always @(posedge clk) begin : p_fail_closed_health
        if (rst_n && !clear_i) begin
            if ((^{y_valid_o, replay_source_active_o, replay_source_done_o,
                   replay_path_busy_o, replay_path_done_o,
                   replay_path_done_pulse_o, replay_completion_error_sticky_o,
                   replay_e2e_busy_o, replay_e2e_done_o,
                   replay_e2e_done_pulse_o, replay_e2e_error_sticky_o,
                   core_protocol_error_sticky_o, source_fault_sticky_o,
                   build_contract_error_o, ring_configured_o, writer_busy_o,
                   normal_commit_pulse_o, wrap_commit_pulse_o, avm_write_o,
                   ddr_response_pending_q, ddr_response_valid_q}
                 === 1'bx) ||
                (^replay_source_accept_count_o === 1'bx) ||
                (^replay_core_output_accept_count_o === 1'bx) ||
                (^replay_expected_output_count_o === 1'bx) ||
                (^core_sample_count_o === 1'bx) || (^core_frame_count_o === 1'bx) ||
                (^core_error_sample_count_o === 1'bx) ||
                (^core_overflow_flags_o === 1'bx) || (^overflow_flags_o === 1'bx) ||
                (^packet_fifo_drop_count_o === 1'bx) || (^dma_drop_count_o === 1'bx) ||
                (^dma_packet_count_o === 1'bx) || (^producer_ptr_o === 1'bx) ||
                (^consumer_ptr_o === 1'bx) || (^sequence_o === 1'bx) ||
                (^ddr_response_count_q === 1'bx) ||
                (^ddr_ok_response_count_q === 1'bx) ||
                (^ddr_error_response_count_q === 1'bx) ||
                (^ddr_response_latency_mask_q === 1'bx) ||
                (^ddr_accepted_beats_q === 1'bx) || (^ddr_wait_cycles_q === 1'bx) ||
                (^ddr_response_delay_cycles_q === 1'bx) ||
                (^y_stall_cycles_q === 1'bx)) begin
                $fatal(1, "STEP11_BRAM_E2E_FAIL X/Z in control, counter, or status output");
            end
            if ((y_valid_o === 1'b1) &&
                ((^y_data_o === 1'bx) || (^y_sample_idx_o === 1'bx))) begin
                $fatal(1, "STEP11_BRAM_E2E_FAIL X/Z in valid y payload");
            end
            if ((avm_write_o === 1'b1) &&
                ((^avm_address_o === 1'bx) || (^avm_writedata_o === 1'bx) ||
                 (^avm_byteenable_o === 1'bx) || (^avm_burstcount_o === 1'bx))) begin
                $fatal(1, "STEP11_BRAM_E2E_FAIL X/Z in active Avalon DDR write");
            end
            if ((ddr_response_valid_q === 1'b1) && (^ddr_response_code_q === 1'bx)) begin
                $fatal(1, "STEP11_BRAM_E2E_FAIL X/Z in DDR response code");
            end
            if ((ddr_response_pending_q === 1'b1) &&
                ((^ddr_response_delay_q === 1'bx) ||
                 (^ddr_response_latency_slot_q === 1'bx) ||
                 (^ddr_response_code_q === 1'bx))) begin
                $fatal(1, "STEP11_BRAM_E2E_FAIL X/Z in pending DDR response state");
            end
            if ((status_tick_i !== 1'b0) || (metrics_tick_i !== 1'b0)) begin
                $fatal(1, "STEP11_BRAM_E2E_FAIL periodic telemetry tick asserted in replay epoch");
            end
            if (negative_fault_window_q) begin
                if ((replay_completion_error_sticky_o !== 1'b0) ||
                    (core_protocol_error_sticky_o !== 1'b0) ||
                    (source_fault_sticky_o !== 1'b0) || (build_contract_error_o !== 1'b0) ||
                    (core_overflow_flags_o !== 32'd0) ||
                    (packet_fifo_drop_count_o !== 32'd0)) begin
                    $fatal(1, "STEP11_BRAM_E2E_FAIL non-DDR fault during negative epoch");
                end
                if ((normal_commit_pulse_o !== 1'b0) || (replay_e2e_done_o !== 1'b0) ||
                    (replay_e2e_done_pulse_o !== 1'b0)) begin
                    $fatal(1, "STEP11_BRAM_E2E_FAIL negative DDR-error epoch reached commit/E2E done");
                end
            end else if ((replay_completion_error_sticky_o !== 1'b0) ||
                         (replay_e2e_error_sticky_o !== 1'b0) ||
                         (core_protocol_error_sticky_o !== 1'b0) ||
                         (source_fault_sticky_o !== 1'b0) ||
                         (build_contract_error_o !== 1'b0) ||
                         (core_overflow_flags_o !== 32'd0) ||
                         (overflow_flags_o !== 32'd0) ||
                         (packet_fifo_drop_count_o !== 32'd0) ||
                         (dma_drop_count_o !== 32'd0)) begin
                $fatal(1, "STEP11_BRAM_E2E_FAIL fault/drop asserted before terminal check");
            end
        end
    end

    initial begin : p_test
        clk = 1'b0;
        rst_n = 1'b0;
        enable_i = 1'b1;
        clear_i = 1'b1;
        source_tick_i = 1'b0;
        replay_start_i = 1'b0;
        status_tick_i = 1'b0;
        metrics_tick_i = 1'b0;
        csr_avs_address_i = '0;
        csr_avs_read_i = 1'b0;
        csr_avs_write_i = 1'b0;
        csr_avs_writedata_i = '0;
        csr_avs_byteenable_i = 4'b1111;
        csr_avs_burstcount_i = 1'b1;
        inject_final_response_error_q = 1'b1;
        negative_fault_window_q = 1'b1;
        negative_epoch_proved_q = 1'b0;

        load_expected_y();
        repeat (8) @(negedge clk);
        rst_n = 1'b1;
        repeat (3) @(negedge clk);
        clear_i = 1'b0;
        source_tick_i = 1'b1;

        configure_revision_g_status_ring();
        if ((ring_configured_o !== 1'b1) ||
            (ring_config_o.configured !== 1'b1) ||
            (ring_config_o.base_addr !== RING_BASE) ||
            (ring_config_o.size_bytes !== RING_SIZE_BYTES)) begin
            $fatal(1, "STEP11_BRAM_E2E_FAIL active ring configuration mismatch");
        end
        if ((ctrl_o.source_mode !== TSRC_BRAM_REPLAY) ||
            (ctrl_o.thr2_active !== '0) ||
            (ctrl_o.packet_enable !== TCSR_PACKET_ENABLE_STATUS_EN_MASK)) begin
            $fatal(1, "STEP11_BRAM_E2E_FAIL active BRAM/THR2/STATUS controls mismatch");
        end

        // Negative control: all 16 physical writes are accepted, but the final response is a
        // deliberately delayed SLVERR. Exact core completion must remain valid while the writer
        // refuses producer commit and the E2E supervisor latches a transport fault.
        @(negedge clk);
        replay_start_i = 1'b1;
        @(negedge clk);
        replay_start_i = 1'b0;

        wait (replay_path_done_pulse_o);
        @(negedge clk);
        check_exact_completion();
        if ((replay_e2e_busy_o !== 1'b1) || (replay_e2e_done_o !== 1'b0) ||
            (replay_e2e_error_sticky_o !== 1'b0)) begin
            $fatal(1, "STEP11_BRAM_E2E_FAIL E2E completed before post-core STATUS commit");
        end
        check_negative_final_response_error();
        negative_epoch_proved_q = 1'b1;

        // Clear/rearm proves the response fault is sticky for its epoch but recoverable only via
        // the explicit system clear. The transport clear invalidates the ring configuration and
        // Rd epoch, so software must reconfigure and commit the exact Rd=0 epoch before re-enable.
        @(negedge clk);
        clear_i = 1'b1;
        repeat (4) @(negedge clk);
        inject_final_response_error_q = 1'b0;
        clear_i = 1'b0;
        repeat (3) @(negedge clk);
        csr_write32(TCSR_CLEAR_STICKY_FLAGS_OFFSET, 32'h0000_03ff);
        configure_revision_g_status_ring();
        repeat (3) @(negedge clk);
        if ((replay_source_active_o !== 1'b0) || (replay_source_done_o !== 1'b0) ||
            (replay_path_busy_o !== 1'b0) || (replay_path_done_o !== 1'b0) ||
            (replay_e2e_busy_o !== 1'b0) || (replay_e2e_done_o !== 1'b0) ||
            (replay_e2e_error_sticky_o !== 1'b0) || (writer_busy_o !== 1'b0) ||
            (normal_commit_count_q !== 32'd0) || (producer_ptr_o !== 64'd0) ||
            (consumer_ptr_o !== 64'd0) || (sequence_o !== 32'd0) ||
            (dma_packet_count_o !== 32'd0) || (dma_drop_count_o !== 32'd0) ||
            (packet_fifo_drop_count_o !== 32'd0) || (overflow_flags_o !== 32'd0) ||
            (ring_configured_o !== 1'b1)) begin
            $fatal(1, "STEP11_BRAM_E2E_FAIL clear/rearm did not restore clean configured state");
        end
        negative_fault_window_q = 1'b0;

        // Positive epoch: status_tick_i remains zero throughout. The system top must auto-inject
        // exactly one STATUS request from replay_path_done_pulse_o, and E2E done must wait for all
        // 16 variably delayed OK responses plus the normal producer commit.
        @(negedge clk);
        replay_start_i = 1'b1;
        @(negedge clk);
        replay_start_i = 1'b0;

        wait (replay_path_done_pulse_o);
        @(negedge clk);
        check_exact_completion();
        if ((replay_e2e_busy_o !== 1'b1) || (replay_e2e_done_o !== 1'b0) ||
            (replay_e2e_error_sticky_o !== 1'b0) || (status_tick_i !== 1'b0)) begin
            $fatal(1, "STEP11_BRAM_E2E_FAIL positive epoch pre-commit E2E state");
        end

        wait (normal_commit_seen_q);
        wait (replay_e2e_done_o);
        repeat (3) @(negedge clk);
        check_status_record();
        if ((full_path_alive_o !== 1'b0) && (full_path_alive_o !== 1'b1)) begin
            $fatal(1, "STEP11_BRAM_E2E_FAIL full-path-alive is X/Z after commit");
        end
        if (!full_path_alive_o) begin
            $fatal(1, "STEP11_BRAM_E2E_FAIL full path did not report alive after commit");
        end
        if ((done_pulse_count_q !== 32'd1) ||
            (e2e_done_pulse_count_q !== 32'd1) ||
            (replay_e2e_done_o !== 1'b1) || (replay_e2e_busy_o !== 1'b0) ||
            (replay_e2e_error_sticky_o !== 1'b0) || (writer_busy_o !== 1'b0) ||
            (negative_epoch_proved_q !== 1'b1) || (status_tick_i !== 1'b0)) begin
            $fatal(1, "STEP11_BRAM_E2E_FAIL terminal pulse/writer state");
        end

        $display("STEP11_BRAM_E2E_PASS impulse_Ns1024_thr0 y=1536 sample_count=1152 frame_count=9 status_commits=1 producer_ptr=128 delayed_ok_responses=16 negative_final_slverr=1 rearm=1 auto_status_only=1");
        $finish;
    end

    initial begin : p_watchdog
        repeat (WATCHDOG_CYCLES) @(posedge clk);
        $fatal(1,
               "STEP11_BRAM_E2E_FAIL watchdog y=%0d path_done=%b e2e_done=%b e2e_busy=%b W=%0d commits=%0d",
               y_accept_count_q, replay_path_done_o, replay_e2e_done_o, replay_e2e_busy_o,
               producer_ptr_o, normal_commit_count_q);
    end

endmodule : tb_trecap_step11_bram_e2e

`default_nettype wire
