// SPDX-License-Identifier: MIT
// File class: [1] hand-written RTL.
// Layer: rtl/hps_bridge/
// Owner: T-RECAP Phase 2 implementation.
// Purpose: DDR ring writer with WRAP/free-space policy, Avalon write master, producer commits,
//          DMA counters, and writer status for the HPS-visible CSR bank.
// Contract: Telemetry is dropped and counted when transport blocks; the STFT/WOLA core is never
//           backpressured through this module.

`default_nettype none

// T-RECAP DDR ring writer.
//
// This module is the only owner of the physical DDR write side of the telemetry path.  Telemetry
// packetizers produce formatted payload records; this writer schedules those records against the
// absolute-pointer ring, writes WRAP control records when a physical tail would be crossed, writes
// normal records through an Avalon-MM style master, and commits W only after all bus writes for the
// record have completed.
module trecap_ddr_ring_writer
  import trecap_csr_pkg::*;
  import trecap_packet_pkg::*;
  import trecap_iface_pkg::*;
  import trecap_build_pkg::*;
#(
    parameter int unsigned RECORD_DATA_W = 32,
    parameter int unsigned RECORD_KEEP_W = (RECORD_DATA_W + 7) / 8,
    parameter int unsigned AVMM_ADDR_W   = 64,
    parameter int unsigned AVMM_DATA_W   = 64,
    parameter int unsigned AVMM_BYTEEN_W = (AVMM_DATA_W + 7) / 8,
    parameter int unsigned AVMM_BURSTCOUNT_W = 1,
    parameter int unsigned RECORD_BYTES_MAX =
        (((TPKT_UDP_MAX_BYTES + TPKT_DDR_ALIGN_BYTES - 1) / TPKT_DDR_ALIGN_BYTES) *
         TPKT_DDR_ALIGN_BYTES),
    parameter int unsigned GUARD_BYTES = TCSR_RING_GUARD_BYTES_MIN,
    parameter logic [31:0] RING_SIZE_MIN_BYTES = 32'h0010_0000
) (
    input  logic                       clk,
    input  logic                       rst_n,

    input  logic                       clear_i,
    // Clear only transport diagnostic counters. Writer state, absolute W/Rd pointers, sequence,
    // and sticky fault evidence remain in the current transport epoch.
    input  logic                       counter_clear_i,
    input  trecap_hps_bridge_ctrl_t    ctrl_i,
    input  trecap_ring_config_t        ring_config_i,
    input  logic                       ring_config_commit_pulse_i,

    input  logic                       ring_rd_commit_valid_i,
    input  logic [63:0]                ring_rd_commit_ptr_i,
    output logic                       ring_rd_commit_ready_o,
    output logic                       ring_rd_accept_pulse_o,
    output logic                       ring_rd_reject_pulse_o,

    input  logic                       ring_wr_snapshot_req_i,
    output logic [63:0]                ring_wr_snapshot_o,
    output logic                       ring_wr_snapshot_valid_o,
    output logic                       ring_wr_snapshot_pulse_o,

    input  logic                       packet_fifo_full_i,

    // Formatted record payload stream from rtl/telemetry/trecap_packet_fifo.sv.
    input  logic                       record_valid_i,
    output logic                       record_ready_o,
    input  trecap_record_meta_t        record_meta_i,
    input  logic [RECORD_DATA_W-1:0]   record_payload_data_i,
    input  logic [RECORD_KEEP_W-1:0]   record_payload_keep_i,
    input  logic                       record_payload_last_i,

    // Avalon-MM write master boundary toward Platform Designer / HPS-visible DDR.
    output logic [AVMM_ADDR_W-1:0]     avm_address_o,
    output logic                       avm_write_o,
    output logic [AVMM_DATA_W-1:0]     avm_writedata_o,
    output logic [AVMM_BYTEEN_W-1:0]   avm_byteenable_o,
    output logic [AVMM_BURSTCOUNT_W-1:0] avm_burstcount_o,
    input  logic                       avm_waitrequest_i,
    input  logic                       avm_writeresponsevalid_i,
    input  logic [1:0]                 avm_response_i,

    // CSR/status visibility.
    output logic [63:0]                producer_ptr_o,
    output logic [63:0]                consumer_ptr_o,
    output logic [31:0]                sequence_o,
    output logic [63:0]                used_bytes_o,
    output logic [63:0]                free_bytes_o,
    output logic [63:0]                current_offset_o,
    output logic [63:0]                current_tail_bytes_o,

    output logic                       writer_idle_o,
    output logic                       writer_busy_o,
    output logic                       writer_no_space_o,
    output logic                       malformed_config_o,
    output logic                       ring_full_o,
    output logic                       ddr_wait_o,
    output logic                       drop_active_o,
    output logic                       ring_configured_o,
    output logic                       pointers_valid_o,
    output logic                       writer_fault_sticky_o,

    output logic [31:0]                dma_drop_count_o,
    output logic [31:0]                dma_packet_count_o,
    output logic [31:0]                overflow_flags_set_o,

    output logic                       normal_commit_pulse_o,
    output logic                       wrap_commit_pulse_o,
    output logic                       drop_pulse_o,
    output logic                       malformed_pulse_o,
    output logic                       oversized_pulse_o
);

    localparam logic [63:0] HEADER_BYTES_64 = TPKT_HEADER_BYTES;
    localparam logic [63:0] DDR_ALIGN_MASK_64 = TPKT_DDR_ALIGN_BYTES - 1;
    localparam logic [63:0] UDP_MAX_BYTES_64 = TPKT_UDP_MAX_BYTES;

    typedef enum logic [3:0] {
        WSTATE_IDLE            = 4'd0,
        WSTATE_DROP            = 4'd1,
        WSTATE_PASS_NORMAL     = 4'd2,
        WSTATE_ISSUE_WRAP      = 4'd3,
        WSTATE_ACTIVE_WRITE    = 4'd4,
        WSTATE_COMMIT_REQ      = 4'd5,
        WSTATE_WAIT_COMMIT_ACK = 4'd6,
        WSTATE_FAULT           = 4'd7
    } writer_state_e;

    writer_state_e state_q;

    logic [AVMM_ADDR_W-1:0] current_write_addr_q;
    logic [63:0]            current_advance_bytes_q;
    logic                   current_is_wrap_q;
    logic                   current_is_normal_q;
    logic                   normal_input_open_q;
    logic                   avmm_cmd_issued_q;
    logic                   commit_sent_q;
    logic                   no_space_q;
    logic                   writer_fault_q;
    logic [31:0]            dma_drop_count_q;
    logic [31:0]            dma_packet_count_q;
    logic [31:0]            overflow_flags_set_q;

    logic                   run_enable;
    logic                   writer_state_busy;
    logic                   keep_subblocks_enabled;

    logic                   meta_known_comb;
    logic                   meta_reserved_disabled_comb;
    logic                   meta_wrap_comb;
    logic                   flags_legal_comb;
    logic                   payload_size_valid_comb;
    logic                   metadata_legal_comb;
    logic                   metadata_malformed_comb;
    logic                   metadata_oversized_comb;
    logic [63:0]            normal_record_bytes_comb;
    logic                   idle_has_record;
    logic                   schedule_query_valid;
    logic                   idle_drop_no_space;
    logic                   idle_can_drop;
    logic                   idle_need_wrap;
    logic                   idle_can_pass;
    logic                   idle_accept_drop;
    logic                   idle_accept_pass;
    logic                   pass_accept;
    logic                   pass_last_accept;
    logic                   drop_accept;
    logic                   drop_last_accept;

    logic                   schedule_fits;
    logic                   schedule_needs_wrap;
    logic [63:0]            schedule_offset;
    logic [63:0]            schedule_tail_bytes;
    logic [63:0]            schedule_required_bytes;
    logic [63:0]            schedule_free_bytes;
    logic [63:0]            schedule_normal_addr;
    logic [63:0]            schedule_wrap_addr;
    logic                   ptr_producer_advance_ready;
    logic                   ptr_producer_accept_pulse;
    logic                   ptr_producer_reject_pulse;
    logic                   ptr_pointer_error_sticky;
    logic                   ptr_malformed_config;
    logic                   ptr_ring_full;
    logic                   ptr_no_space;
    logic                   ptr_ring_configured;
    logic                   ptr_pointers_valid;

    logic                   producer_advance_valid;
    logic                   producer_advance_is_normal;
    logic                   producer_advance_is_wrap;
    logic [63:0]            producer_advance_bytes;

    logic                   builder_clear;
    logic                   builder_enable;
    logic                   builder_in_valid;
    logic                   builder_in_ready;
    logic                   builder_wrap_valid;
    logic                   builder_wrap_ready;
    logic [63:0]            builder_wrap_bytes;
    logic                   builder_out_valid;
    logic                   builder_out_ready;
    logic [AVMM_DATA_W-1:0] builder_out_data;
    logic [AVMM_BYTEEN_W-1:0] builder_out_keep;
    logic                   builder_out_last;
    logic                   builder_start_pulse;
    logic                   builder_done_pulse;
    logic                   builder_is_wrap;
    trecap_record_meta_t    builder_meta;
    logic [31:0]            builder_seq;
    logic [15:0]            builder_payload_bytes;
    logic [63:0]            builder_record_bytes;
    logic                   builder_busy;
    logic                   builder_drop_pulse;
    logic                   builder_malformed_pulse;
    logic                   builder_oversized_pulse;

    logic                   avmm_clear;
    logic                   avmm_enable;
    logic                   avmm_cmd_valid;
    logic                   avmm_cmd_ready;
    logic                   avmm_cmd_accept_pulse;
    logic                   avmm_cmd_reject_pulse;
    logic                   avmm_stream_valid;
    logic                   avmm_stream_ready;
    logic                   avmm_busy;
    logic                   avmm_done_pulse;
    logic                   avmm_protocol_error_pulse;
    logic                   avmm_wait_active;
    logic                   avmm_wait_seen_sticky;
    logic                   avmm_response_error_sticky;
    logic                   avmm_response_error_now;
    logic [63:0]            avmm_bytes_written;
    logic [63:0]            avmm_bytes_remaining;
    logic [AVMM_ADDR_W-1:0] avmm_current_addr;

    logic [AVMM_ADDR_W-1:0] schedule_normal_addr_trunc;
    logic [AVMM_ADDR_W-1:0] schedule_wrap_addr_trunc;

    function automatic logic [63:0] align64(input logic [63:0] value);
        return (value + DDR_ALIGN_MASK_64) & ~DDR_ALIGN_MASK_64;
    endfunction : align64

    function automatic bit flags_legal_for_packet(
        input trecap_packet_type_e packet_type,
        input logic [15:0]         flags
    );
        logic aggregate_metrics;
        logic per_frame_metrics;

        if ((flags & TPKT_FLAG_RESERVED_15_6_MASK) != 16'h0000) begin
            return 1'b0;
        end
        if ((flags & TPKT_FLAG_CRC_ENABLED_MASK) != 16'h0000) begin
            return 1'b0;
        end
        if ((flags & TPKT_FLAG_STATUS_DIAGNOSTIC_MASK) != 16'h0000) begin
            return 1'b0;
        end

        aggregate_metrics = ((flags & TPKT_FLAG_AGGREGATE_METRICS_MASK) != 16'h0000);
        per_frame_metrics = ((flags & TPKT_FLAG_PER_FRAME_METRICS_MASK) != 16'h0000);

        if (packet_type == TPKT_METRICS) begin
            if (aggregate_metrics == per_frame_metrics) begin
                return 1'b0;
            end
            if ((flags & TPKT_FLAG_PAYLOAD_SCALED_MASK) != 16'h0000) begin
                return 1'b0;
            end
        end else if (aggregate_metrics || per_frame_metrics) begin
            return 1'b0;
        end

        return 1'b1;
    endfunction : flags_legal_for_packet

    generate
        if (AVMM_ADDR_W == 64) begin : g_addr64
            assign schedule_normal_addr_trunc = schedule_normal_addr;
            assign schedule_wrap_addr_trunc = schedule_wrap_addr;
        end else if (AVMM_ADDR_W > 64) begin : g_addr_gt64
            assign schedule_normal_addr_trunc = {{(AVMM_ADDR_W - 64){1'b0}}, schedule_normal_addr};
            assign schedule_wrap_addr_trunc = {{(AVMM_ADDR_W - 64){1'b0}}, schedule_wrap_addr};
        end else begin : g_addr_lt64
            assign schedule_normal_addr_trunc = schedule_normal_addr[AVMM_ADDR_W-1:0];
            assign schedule_wrap_addr_trunc = schedule_wrap_addr[AVMM_ADDR_W-1:0];
        end
    endgenerate

    assign run_enable = ctrl_i.telemetry_enable && ctrl_i.ring_writer_enable;
    assign writer_state_busy = (state_q != WSTATE_IDLE);
    assign keep_subblocks_enabled = !clear_i && (run_enable || writer_state_busy || builder_busy || avmm_busy);

    assign meta_known_comb = trecap_packet_type_known(record_meta_i.packet_type);
    assign meta_reserved_disabled_comb = trecap_packet_type_reserved_disabled(record_meta_i.packet_type);
    assign meta_wrap_comb = (record_meta_i.packet_type == TPKT_WRAP);
    assign flags_legal_comb = flags_legal_for_packet(record_meta_i.packet_type, record_meta_i.flags);
    assign payload_size_valid_comb = trecap_payload_bytes_valid(
        record_meta_i.packet_type,
        int'({16'd0, record_meta_i.payload_bytes})
    );
    assign metadata_oversized_comb = (HEADER_BYTES_64 + {48'd0, record_meta_i.payload_bytes}) > UDP_MAX_BYTES_64;
    assign metadata_legal_comb = record_meta_i.valid &&
                                 meta_known_comb &&
                                 !meta_reserved_disabled_comb &&
                                 !meta_wrap_comb &&
                                 flags_legal_comb &&
                                 payload_size_valid_comb &&
                                 !metadata_oversized_comb &&
                                 (record_meta_i.drop_priority == trecap_packet_drop_priority(record_meta_i.packet_type));
    assign metadata_malformed_comb = !metadata_legal_comb && !metadata_oversized_comb;
    assign normal_record_bytes_comb = align64(HEADER_BYTES_64 + {48'd0, record_meta_i.payload_bytes});

    assign idle_has_record = (state_q == WSTATE_IDLE) && record_valid_i && run_enable &&
                             ptr_ring_configured && ptr_pointers_valid && !ptr_malformed_config;
    assign schedule_query_valid = idle_has_record && metadata_legal_comb;
    assign idle_drop_no_space = schedule_query_valid && !schedule_fits;
    assign idle_can_drop = idle_has_record && (metadata_malformed_comb || metadata_oversized_comb || idle_drop_no_space);
    assign idle_need_wrap = schedule_query_valid && schedule_fits && schedule_needs_wrap;
    assign idle_can_pass = schedule_query_valid && schedule_fits && !schedule_needs_wrap;

    assign builder_in_valid = ((state_q == WSTATE_IDLE) && idle_can_pass && record_valid_i && record_ready_o) ||
                              ((state_q == WSTATE_PASS_NORMAL) && record_valid_i && record_ready_o);
    assign builder_wrap_valid = (state_q == WSTATE_ISSUE_WRAP);
    assign builder_wrap_bytes = current_advance_bytes_q;

    assign record_ready_o = ((state_q == WSTATE_IDLE) && idle_can_drop) ? 1'b1 :
                            ((state_q == WSTATE_IDLE) && idle_can_pass) ? builder_in_ready :
                            ((state_q == WSTATE_PASS_NORMAL) && normal_input_open_q) ? builder_in_ready :
                            (state_q == WSTATE_DROP) ? 1'b1 :
                            1'b0;

    assign idle_accept_drop = (state_q == WSTATE_IDLE) && idle_can_drop && record_valid_i && record_ready_o;
    assign idle_accept_pass = (state_q == WSTATE_IDLE) && idle_can_pass && record_valid_i && record_ready_o;
    assign pass_accept = (state_q == WSTATE_PASS_NORMAL) && record_valid_i && record_ready_o;
    assign pass_last_accept = (idle_accept_pass || pass_accept) && record_payload_last_i;
    assign drop_accept = ((state_q == WSTATE_DROP) && record_valid_i && record_ready_o) || idle_accept_drop;
    assign drop_last_accept = drop_accept && record_payload_last_i;

    trecap_ring_pointer_ctrl #(
        .GUARD_BYTES(GUARD_BYTES),
        .RING_SIZE_MIN_BYTES(RING_SIZE_MIN_BYTES)
    ) u_ring_pointer_ctrl (
        .clk(clk),
        .rst_n(rst_n),
        .soft_reset_i(clear_i),
        .ring_config_i(ring_config_i),
        .ring_config_commit_pulse_i(ring_config_commit_pulse_i),
        .telemetry_enable_i(ctrl_i.telemetry_enable),
        .ring_writer_enable_i(ctrl_i.ring_writer_enable),
        .schedule_valid_i(schedule_query_valid),
        .scheduled_record_bytes_i(normal_record_bytes_comb),
        .schedule_fits_o(schedule_fits),
        .schedule_needs_wrap_o(schedule_needs_wrap),
        .schedule_offset_o(schedule_offset),
        .schedule_tail_bytes_o(schedule_tail_bytes),
        .schedule_required_bytes_o(schedule_required_bytes),
        .schedule_free_bytes_o(schedule_free_bytes),
        .schedule_normal_addr_o(schedule_normal_addr),
        .schedule_wrap_addr_o(schedule_wrap_addr),
        .producer_advance_valid_i(producer_advance_valid),
        .producer_advance_is_normal_i(producer_advance_is_normal),
        .producer_advance_is_wrap_i(producer_advance_is_wrap),
        .producer_advance_bytes_i(producer_advance_bytes),
        .producer_advance_ready_o(ptr_producer_advance_ready),
        .producer_advance_accept_pulse_o(ptr_producer_accept_pulse),
        .producer_advance_reject_pulse_o(ptr_producer_reject_pulse),
        .ring_rd_commit_valid_i(ring_rd_commit_valid_i),
        .ring_rd_commit_ptr_i(ring_rd_commit_ptr_i),
        .ring_rd_commit_ready_o(ring_rd_commit_ready_o),
        .ring_rd_accept_pulse_o(ring_rd_accept_pulse_o),
        .ring_rd_reject_pulse_o(ring_rd_reject_pulse_o),
        .ring_wr_snapshot_req_i(ring_wr_snapshot_req_i),
        .ring_wr_snapshot_o(ring_wr_snapshot_o),
        .ring_wr_snapshot_valid_o(ring_wr_snapshot_valid_o),
        .ring_wr_snapshot_pulse_o(ring_wr_snapshot_pulse_o),
        .producer_ptr_o(producer_ptr_o),
        .consumer_ptr_o(consumer_ptr_o),
        .sequence_o(sequence_o),
        .used_bytes_o(used_bytes_o),
        .free_bytes_o(free_bytes_o),
        .current_offset_o(current_offset_o),
        .current_tail_bytes_o(current_tail_bytes_o),
        .ring_configured_o(ptr_ring_configured),
        .ring_full_o(ptr_ring_full),
        .no_space_o(ptr_no_space),
        .pointers_valid_o(ptr_pointers_valid),
        .malformed_config_o(ptr_malformed_config),
        .pointer_error_sticky_o(ptr_pointer_error_sticky)
    );

    assign builder_clear = clear_i || (state_q == WSTATE_FAULT);
    assign builder_enable = keep_subblocks_enabled;

    trecap_ddr_record_builder #(
        .IN_DATA_W(RECORD_DATA_W),
        .IN_KEEP_W(RECORD_KEEP_W),
        .OUT_DATA_W(AVMM_DATA_W),
        .OUT_KEEP_W(AVMM_BYTEEN_W),
        .RECORD_BYTES_MAX(RECORD_BYTES_MAX)
    ) u_record_builder (
        .clk(clk),
        .rst_n(rst_n),
        .clear_i(builder_clear),
        .enable_i(builder_enable),
        .sequence_i(sequence_o),
        .in_valid_i(builder_in_valid),
        .in_ready_o(builder_in_ready),
        .in_meta_i(record_meta_i),
        .in_payload_data_i(record_payload_data_i),
        .in_payload_keep_i(record_payload_keep_i),
        .in_payload_last_i(record_payload_last_i),
        .wrap_valid_i(builder_wrap_valid),
        .wrap_ready_o(builder_wrap_ready),
        .wrap_effective_bytes_i(builder_wrap_bytes),
        .out_valid_o(builder_out_valid),
        .out_ready_i(builder_out_ready),
        .out_data_o(builder_out_data),
        .out_keep_o(builder_out_keep),
        .out_last_o(builder_out_last),
        .out_record_start_pulse_o(builder_start_pulse),
        .out_record_done_pulse_o(builder_done_pulse),
        .out_is_wrap_o(builder_is_wrap),
        .out_meta_o(builder_meta),
        .out_seq_o(builder_seq),
        .out_payload_bytes_o(builder_payload_bytes),
        .out_record_bytes_o(builder_record_bytes),
        .busy_o(builder_busy),
        .drop_pulse_o(builder_drop_pulse),
        .malformed_pulse_o(builder_malformed_pulse),
        .oversized_pulse_o(builder_oversized_pulse)
    );

    assign avmm_clear = clear_i || (state_q == WSTATE_FAULT);
    assign avmm_enable = keep_subblocks_enabled;
    assign avmm_cmd_valid = (state_q == WSTATE_ACTIVE_WRITE) && builder_out_valid && !avmm_cmd_issued_q;
    assign avmm_stream_valid = (state_q == WSTATE_ACTIVE_WRITE) && builder_out_valid && avmm_cmd_issued_q;
    assign builder_out_ready = avmm_cmd_issued_q && avmm_stream_ready;

    trecap_avmm_write_master #(
        .ADDR_W(AVMM_ADDR_W),
        .DATA_W(AVMM_DATA_W),
        .BYTEEN_W(AVMM_BYTEEN_W),
        .BURSTCOUNT_W(AVMM_BURSTCOUNT_W),
        .CHECK_RESPONSES(1'b1)
    ) u_avmm_write_master (
        .clk(clk),
        .rst_n(rst_n),
        .clear_i(avmm_clear),
        .enable_i(avmm_enable),
        .cmd_valid_i(avmm_cmd_valid),
        .cmd_ready_o(avmm_cmd_ready),
        .cmd_addr_i(current_write_addr_q),
        .cmd_bytes_i(builder_record_bytes),
        .stream_valid_i(avmm_stream_valid),
        .stream_ready_o(avmm_stream_ready),
        .stream_data_i(builder_out_data),
        .stream_keep_i(builder_out_keep),
        .stream_last_i(builder_out_last),
        .avm_address_o(avm_address_o),
        .avm_writedata_o(avm_writedata_o),
        .avm_byteenable_o(avm_byteenable_o),
        .avm_write_o(avm_write_o),
        .avm_burstcount_o(avm_burstcount_o),
        .avm_waitrequest_i(avm_waitrequest_i),
        .avm_writeresponsevalid_i(avm_writeresponsevalid_i),
        .avm_response_i(avm_response_i),
        .cmd_accept_pulse_o(avmm_cmd_accept_pulse),
        .cmd_reject_pulse_o(avmm_cmd_reject_pulse),
        .beat_accept_pulse_o(),
        .write_done_pulse_o(avmm_done_pulse),
        .protocol_error_pulse_o(avmm_protocol_error_pulse),
        .busy_o(avmm_busy),
        .waitrequest_active_o(avmm_wait_active),
        .waitrequest_seen_sticky_o(avmm_wait_seen_sticky),
        .response_error_sticky_o(avmm_response_error_sticky),
        .bytes_written_o(avmm_bytes_written),
        .bytes_remaining_o(avmm_bytes_remaining),
        .current_addr_o(avmm_current_addr)
    );

    // The conservative write master permits one outstanding beat and raises done only after the
    // final successful response.  Keep the raw/sticky response guards here as a second fail-closed
    // boundary: a malformed integration or rejected-address response must never transition into
    // commit or advance the producer before the registered protocol-error pulse reaches FAULT.
    assign avmm_response_error_now = avm_writeresponsevalid_i && (avm_response_i != 2'b00);
    assign producer_advance_valid = (state_q == WSTATE_COMMIT_REQ) && !commit_sent_q &&
                                    !avmm_response_error_now && !avmm_response_error_sticky;
    assign producer_advance_is_normal = current_is_normal_q;
    assign producer_advance_is_wrap = current_is_wrap_q;
    assign producer_advance_bytes = current_advance_bytes_q;

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state_q <= WSTATE_IDLE;
            current_write_addr_q <= '0;
            current_advance_bytes_q <= 64'd0;
            current_is_wrap_q <= 1'b0;
            current_is_normal_q <= 1'b0;
            normal_input_open_q <= 1'b0;
            avmm_cmd_issued_q <= 1'b0;
            commit_sent_q <= 1'b0;
            no_space_q <= 1'b0;
            writer_fault_q <= 1'b0;
            dma_drop_count_q <= 32'd0;
            dma_packet_count_q <= 32'd0;
            overflow_flags_set_q <= 32'h0000_0000;
            normal_commit_pulse_o <= 1'b0;
            wrap_commit_pulse_o <= 1'b0;
            drop_pulse_o <= 1'b0;
            malformed_pulse_o <= 1'b0;
            oversized_pulse_o <= 1'b0;
        end else begin
            overflow_flags_set_q <= 32'h0000_0000;
            normal_commit_pulse_o <= 1'b0;
            wrap_commit_pulse_o <= 1'b0;
            drop_pulse_o <= 1'b0;
            malformed_pulse_o <= 1'b0;
            oversized_pulse_o <= 1'b0;

            if (clear_i) begin
                state_q <= WSTATE_IDLE;
                current_write_addr_q <= '0;
                current_advance_bytes_q <= 64'd0;
                current_is_wrap_q <= 1'b0;
                current_is_normal_q <= 1'b0;
                normal_input_open_q <= 1'b0;
                avmm_cmd_issued_q <= 1'b0;
                commit_sent_q <= 1'b0;
                no_space_q <= 1'b0;
                writer_fault_q <= 1'b0;
                dma_drop_count_q <= 32'd0;
                dma_packet_count_q <= 32'd0;
            end else begin
                if (avmm_cmd_accept_pulse) begin
                    avmm_cmd_issued_q <= 1'b1;
                end

                if (builder_drop_pulse) begin
                    dma_drop_count_q <= dma_drop_count_q + 32'd1;
                    drop_pulse_o <= 1'b1;
                    overflow_flags_set_q <= overflow_flags_set_q | TCSR_OVERFLOW_FLAGS_MALFORMED_PACKET_MASK;
                    if (builder_malformed_pulse) begin
                        malformed_pulse_o <= 1'b1;
                    end
                    if (builder_oversized_pulse) begin
                        oversized_pulse_o <= 1'b1;
                        overflow_flags_set_q <= overflow_flags_set_q | TCSR_OVERFLOW_FLAGS_OVERSIZED_RECORD_MASK;
                    end
                    state_q <= WSTATE_IDLE;
                    avmm_cmd_issued_q <= 1'b0;
                    normal_input_open_q <= 1'b0;
                end

                if (avmm_cmd_reject_pulse || avmm_protocol_error_pulse) begin
                    dma_drop_count_q <= dma_drop_count_q + 32'd1;
                    drop_pulse_o <= 1'b1;
                    malformed_pulse_o <= 1'b1;
                    overflow_flags_set_q <= overflow_flags_set_q | TCSR_OVERFLOW_FLAGS_MALFORMED_PACKET_MASK;
                    writer_fault_q <= 1'b1;
                    state_q <= WSTATE_FAULT;
                    avmm_cmd_issued_q <= 1'b0;
                end

                unique case (state_q)
                    WSTATE_IDLE: begin
                        current_is_wrap_q <= 1'b0;
                        current_is_normal_q <= 1'b0;
                        normal_input_open_q <= 1'b0;
                        avmm_cmd_issued_q <= 1'b0;
                        commit_sent_q <= 1'b0;

                        if (idle_need_wrap) begin
                            current_write_addr_q <= schedule_wrap_addr_trunc;
                            current_advance_bytes_q <= schedule_tail_bytes;
                            current_is_wrap_q <= 1'b1;
                            current_is_normal_q <= 1'b0;
                            state_q <= WSTATE_ISSUE_WRAP;
                        end else if (idle_accept_pass) begin
                            current_write_addr_q <= schedule_normal_addr_trunc;
                            current_advance_bytes_q <= normal_record_bytes_comb;
                            current_is_wrap_q <= 1'b0;
                            current_is_normal_q <= 1'b1;
                            normal_input_open_q <= !record_payload_last_i;
                            state_q <= WSTATE_PASS_NORMAL;
                        end else if (idle_accept_drop) begin
                            dma_drop_count_q <= dma_drop_count_q + 32'd1;
                            drop_pulse_o <= 1'b1;
                            no_space_q <= idle_drop_no_space;
                            if (idle_drop_no_space) begin
                                overflow_flags_set_q <= overflow_flags_set_q | TCSR_OVERFLOW_FLAGS_RING_OVERFLOW_MASK;
                            end
                            if (metadata_malformed_comb) begin
                                malformed_pulse_o <= 1'b1;
                                overflow_flags_set_q <= overflow_flags_set_q | TCSR_OVERFLOW_FLAGS_MALFORMED_PACKET_MASK;
                            end
                            if (metadata_oversized_comb) begin
                                oversized_pulse_o <= 1'b1;
                                overflow_flags_set_q <= overflow_flags_set_q | TCSR_OVERFLOW_FLAGS_OVERSIZED_RECORD_MASK;
                            end
                            state_q <= record_payload_last_i ? WSTATE_IDLE : WSTATE_DROP;
                        end
                    end

                    WSTATE_DROP: begin
                        if (drop_last_accept) begin
                            state_q <= WSTATE_IDLE;
                        end
                    end

                    WSTATE_PASS_NORMAL: begin
                        if (pass_last_accept) begin
                            normal_input_open_q <= 1'b0;
                        end
                        if (builder_start_pulse) begin
                            current_advance_bytes_q <= builder_record_bytes;
                            state_q <= WSTATE_ACTIVE_WRITE;
                        end
                    end

                    WSTATE_ISSUE_WRAP: begin
                        if (builder_wrap_valid && builder_wrap_ready) begin
                            state_q <= WSTATE_ACTIVE_WRITE;
                        end
                    end

                    WSTATE_ACTIVE_WRITE: begin
                        if (builder_start_pulse) begin
                            current_advance_bytes_q <= builder_record_bytes;
                        end
                        if (avmm_done_pulse && !avmm_response_error_now) begin
                            avmm_cmd_issued_q <= 1'b0;
                            state_q <= WSTATE_COMMIT_REQ;
                        end
                    end

                    WSTATE_COMMIT_REQ: begin
                        if (!commit_sent_q && ptr_producer_advance_ready) begin
                            commit_sent_q <= 1'b1;
                        end
                        if (ptr_producer_accept_pulse) begin
                            if (current_is_normal_q) begin
                                dma_packet_count_q <= dma_packet_count_q + 32'd1;
                                normal_commit_pulse_o <= 1'b1;
                                no_space_q <= 1'b0;
                            end
                            if (current_is_wrap_q) begin
                                wrap_commit_pulse_o <= 1'b1;
                            end
                            current_is_wrap_q <= 1'b0;
                            current_is_normal_q <= 1'b0;
                            current_advance_bytes_q <= 64'd0;
                            commit_sent_q <= 1'b0;
                            state_q <= WSTATE_IDLE;
                        end else if (ptr_producer_reject_pulse) begin
                            dma_drop_count_q <= dma_drop_count_q + 32'd1;
                            drop_pulse_o <= 1'b1;
                            malformed_pulse_o <= 1'b1;
                            overflow_flags_set_q <= overflow_flags_set_q |
                                                    TCSR_OVERFLOW_FLAGS_RING_OVERFLOW_MASK |
                                                    TCSR_OVERFLOW_FLAGS_CDC_ERROR_MASK;
                            writer_fault_q <= 1'b1;
                            current_is_wrap_q <= 1'b0;
                            current_is_normal_q <= 1'b0;
                            current_advance_bytes_q <= 64'd0;
                            commit_sent_q <= 1'b0;
                            state_q <= WSTATE_FAULT;
                        end
                    end

                    WSTATE_FAULT: begin
                        if (!run_enable) begin
                            state_q <= WSTATE_IDLE;
                        end
                    end

                    default: begin
                        writer_fault_q <= 1'b1;
                        state_q <= WSTATE_FAULT;
                    end
                endcase

                if (ring_rd_reject_pulse_o || ptr_pointer_error_sticky) begin
                    overflow_flags_set_q <= overflow_flags_set_q | TCSR_OVERFLOW_FLAGS_CDC_ERROR_MASK;
                end

                // This command is intentionally independent of clear_i. Keep it last so a
                // coincident diagnostic event cannot make a just-cleared counter read as one.
                if (counter_clear_i) begin
                    dma_drop_count_q <= 32'd0;
                    dma_packet_count_q <= 32'd0;
                end
            end
        end
    end

    assign writer_idle_o = (state_q == WSTATE_IDLE) && !builder_busy && !avmm_busy;
    assign writer_busy_o = !writer_idle_o;
    assign writer_no_space_o = no_space_q || ptr_no_space;
    assign malformed_config_o = ptr_malformed_config;
    assign ring_full_o = ptr_ring_full || writer_no_space_o;
    assign ddr_wait_o = avmm_wait_active;
    assign drop_active_o = (state_q == WSTATE_DROP) || drop_pulse_o;
    assign ring_configured_o = ptr_ring_configured;
    assign pointers_valid_o = ptr_pointers_valid;
    assign writer_fault_sticky_o = writer_fault_q;
    assign dma_drop_count_o = dma_drop_count_q;
    assign dma_packet_count_o = dma_packet_count_q;
    assign overflow_flags_set_o = overflow_flags_set_q;

    wire unused_builder_debug = builder_done_pulse ^ builder_is_wrap ^ builder_meta.valid ^
                                builder_seq[0] ^ builder_payload_bytes[0];
    wire unused_schedule_debug = schedule_offset[0] ^ schedule_required_bytes[0] ^
                                 schedule_free_bytes[0] ^ packet_fifo_full_i ^
                                 avmm_wait_seen_sticky ^ avmm_response_error_sticky ^
                                 avmm_bytes_written[0] ^ avmm_bytes_remaining[0] ^
                                 avmm_current_addr[0];

`ifndef SYNTHESIS
    initial begin
        if ((RECORD_DATA_W < 8) || ((RECORD_DATA_W % 8) != 0)) begin
            $fatal(1, "trecap_ddr_ring_writer: RECORD_DATA_W must be byte aligned");
        end
        if ((AVMM_DATA_W < 8) || ((AVMM_DATA_W % 8) != 0)) begin
            $fatal(1, "trecap_ddr_ring_writer: AVMM_DATA_W must be byte aligned");
        end
        if (AVMM_BYTEEN_W != (AVMM_DATA_W / 8)) begin
            $fatal(1, "trecap_ddr_ring_writer: AVMM_BYTEEN_W must match AVMM_DATA_W/8");
        end
    end

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            // No simulation-only state.
        end else begin
            if ((state_q == WSTATE_IDLE) && idle_need_wrap && record_ready_o) begin
                $error("trecap_ddr_ring_writer: normal record consumed while WRAP is pending");
            end
            if ((state_q == WSTATE_COMMIT_REQ) && producer_advance_valid && commit_sent_q) begin
                $error("trecap_ddr_ring_writer: duplicate producer-advance request");
            end
        end
    end
`endif

endmodule : trecap_ddr_ring_writer

`default_nettype wire
