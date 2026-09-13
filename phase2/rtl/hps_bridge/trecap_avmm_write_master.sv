// SPDX-License-Identifier: MIT
// File class: [1] hand-written RTL.
// Layer: rtl/hps_bridge/
// Owner: T-RECAP Phase 2 implementation.
// Purpose: Avalon-MM style write master used by the DDR ring writer.
// Contract: Write an already-scheduled byte stream to an FPGA-visible DDR address.  This module
//           does not own ring-space policy, WRAP generation, producer-pointer commit, CSR state,
//           HPS software, Ethernet, UDP, or signal-processing arithmetic.

`default_nettype none

// T-RECAP Avalon-MM write master.
//
// The upstream DDR ring writer issues exactly one command per physical DDR record and then sends
// that record as a ready/valid byte-lane stream.  This conservative baseline emits one Avalon-MM
// write transaction per accepted data beat and drives burstcount=1.  It holds address, data,
// byteenable, and write stable while waitrequest is asserted.  When response checking is enabled,
// at most one write transaction is outstanding: the next stream beat is not accepted and record
// completion is not reported until the accepted beat receives an explicit successful response.
module trecap_avmm_write_master #(
    parameter int unsigned ADDR_W       = 64,
    parameter int unsigned DATA_W       = 64,
    parameter int unsigned BYTEEN_W     = (DATA_W + 7) / 8,
    parameter int unsigned BURSTCOUNT_W = 1,
    parameter bit          CHECK_RESPONSES = 1'b1
) (
    input  logic                      clk,
    input  logic                      rst_n,

    input  logic                      clear_i,
    input  logic                      enable_i,

    input  logic                      cmd_valid_i,
    output logic                      cmd_ready_o,
    input  logic [ADDR_W-1:0]         cmd_addr_i,
    input  logic [63:0]               cmd_bytes_i,

    input  logic                      stream_valid_i,
    output logic                      stream_ready_o,
    input  logic [DATA_W-1:0]         stream_data_i,
    input  logic [BYTEEN_W-1:0]       stream_keep_i,
    input  logic                      stream_last_i,

    output logic [ADDR_W-1:0]         avm_address_o,
    output logic [DATA_W-1:0]         avm_writedata_o,
    output logic [BYTEEN_W-1:0]       avm_byteenable_o,
    output logic                      avm_write_o,
    output logic [BURSTCOUNT_W-1:0]   avm_burstcount_o,
    input  logic                      avm_waitrequest_i,
    input  logic                      avm_writeresponsevalid_i,
    input  logic [1:0]                avm_response_i,

    output logic                      cmd_accept_pulse_o,
    output logic                      cmd_reject_pulse_o,
    output logic                      beat_accept_pulse_o,
    output logic                      write_done_pulse_o,
    output logic                      protocol_error_pulse_o,
    output logic                      busy_o,
    output logic                      waitrequest_active_o,
    output logic                      waitrequest_seen_sticky_o,
    output logic                      response_error_sticky_o,
    output logic [63:0]               bytes_written_o,
    output logic [63:0]               bytes_remaining_o,
    output logic [ADDR_W-1:0]         current_addr_o
);

    localparam int unsigned BEAT_BYTES = BYTEEN_W;
    localparam logic [ADDR_W-1:0] BEAT_BYTES_ADDR = BEAT_BYTES;

    typedef enum logic [1:0] {
        MSTATE_IDLE          = 2'd0,
        MSTATE_WRITE         = 2'd1,
        MSTATE_WAIT_RESPONSE = 2'd2,
        MSTATE_ERROR         = 2'd3
    } master_state_e;

    master_state_e       state_q;
    logic [ADDR_W-1:0]   current_addr_q;
    logic [63:0]         cmd_bytes_q;
    logic [63:0]         bytes_written_q;
    logic [63:0]         bytes_remaining_q;

    logic                hold_valid_q;
    logic [DATA_W-1:0]   hold_data_q;
    logic [BYTEEN_W-1:0] hold_keep_q;
    logic                hold_last_q;
    logic                response_completes_record_q;

    logic                command_legal;
    logic                cmd_accept;
    logic                cmd_reject;
    logic                stream_accept;
    logic                write_accept;
    logic [15:0]         stream_keep_count;
    logic [15:0]         hold_keep_count;
    logic                stream_keep_low_contiguous;
    logic                stream_keep_full;
    logic                stream_keep_legal;
    logic [63:0]         bytes_next;
    logic                write_too_many;
    logic                write_last_mismatch;
    logic                write_missing_last;
    logic                write_done_ok;
    logic                write_protocol_error;
    logic                response_error;
    logic                response_success;
    logic                response_unexpected;

    function automatic logic [15:0] count_keep_bytes(input logic [BYTEEN_W-1:0] keep);
        logic [15:0] count;

        count = 16'd0;
        for (int unsigned i = 0; i < BYTEEN_W; i++) begin
            count = count + (keep[i] ? 16'd1 : 16'd0);
        end
        return count;
    endfunction : count_keep_bytes

    function automatic bit keep_is_low_contiguous(input logic [BYTEEN_W-1:0] keep);
        bit seen_zero;

        seen_zero = 1'b0;
        for (int unsigned i = 0; i < BYTEEN_W; i++) begin
            if (!keep[i]) begin
                seen_zero = 1'b1;
            end else if (seen_zero) begin
                return 1'b0;
            end
        end
        return 1'b1;
    endfunction : keep_is_low_contiguous

    function automatic logic [BURSTCOUNT_W-1:0] burstcount_one();
        logic [BURSTCOUNT_W-1:0] value;

        value = '0;
        value[0] = 1'b1;
        return value;
    endfunction : burstcount_one

    assign command_legal = (cmd_bytes_i != 64'd0);
    assign cmd_ready_o = enable_i && (state_q == MSTATE_IDLE) && !hold_valid_q;
    assign cmd_accept = cmd_valid_i && cmd_ready_o && command_legal;
    assign cmd_reject = cmd_valid_i && cmd_ready_o && !command_legal;

    assign stream_keep_count = count_keep_bytes(stream_keep_i);
    assign stream_keep_low_contiguous = keep_is_low_contiguous(stream_keep_i);
    assign stream_keep_full = (stream_keep_i == {BYTEEN_W{1'b1}});
    assign stream_keep_legal = stream_keep_low_contiguous &&
                               (stream_keep_count != 16'd0) &&
                               (stream_last_i || stream_keep_full);
    assign stream_ready_o = enable_i && (state_q == MSTATE_WRITE) && !hold_valid_q;
    assign stream_accept = stream_valid_i && stream_ready_o;

    assign avm_address_o = current_addr_q;
    assign avm_writedata_o = hold_data_q;
    assign avm_byteenable_o = hold_keep_q;
    assign avm_write_o = enable_i && (state_q == MSTATE_WRITE) && hold_valid_q;
    assign avm_burstcount_o = burstcount_one();
    assign write_accept = avm_write_o && !avm_waitrequest_i;

    assign hold_keep_count = count_keep_bytes(hold_keep_q);
    assign bytes_next = bytes_written_q + {48'd0, hold_keep_count};
    assign write_too_many = write_accept && (bytes_next > cmd_bytes_q);
    assign write_last_mismatch = write_accept && hold_last_q && (bytes_next != cmd_bytes_q);
    assign write_missing_last = write_accept && !hold_last_q && (bytes_next >= cmd_bytes_q);
    assign write_done_ok = write_accept && hold_last_q && (bytes_next == cmd_bytes_q);
    assign write_protocol_error = write_too_many || write_last_mismatch || write_missing_last;
    assign response_error = CHECK_RESPONSES && avm_writeresponsevalid_i &&
                            (avm_response_i != 2'b00);
    assign response_success = CHECK_RESPONSES &&
                              (state_q == MSTATE_WAIT_RESPONSE) &&
                              avm_writeresponsevalid_i && (avm_response_i == 2'b00);
    // Avalon-MM responses must follow an accepted request and this conservative master permits
    // exactly one outstanding request.  A success/error response in any other state is therefore
    // stale, duplicated, or otherwise uncorrelated and must fail closed.
    assign response_unexpected = CHECK_RESPONSES && avm_writeresponsevalid_i &&
                                 (state_q != MSTATE_WAIT_RESPONSE);

    assign busy_o = (state_q != MSTATE_IDLE) || hold_valid_q;
    assign waitrequest_active_o = avm_write_o && avm_waitrequest_i;
    assign bytes_written_o = bytes_written_q;
    assign bytes_remaining_o = bytes_remaining_q;
    assign current_addr_o = current_addr_q;

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state_q <= MSTATE_IDLE;
            current_addr_q <= '0;
            cmd_bytes_q <= 64'd0;
            bytes_written_q <= 64'd0;
            bytes_remaining_q <= 64'd0;
            hold_valid_q <= 1'b0;
            hold_data_q <= '0;
            hold_keep_q <= '0;
            hold_last_q <= 1'b0;
            response_completes_record_q <= 1'b0;
            waitrequest_seen_sticky_o <= 1'b0;
            response_error_sticky_o <= 1'b0;
            cmd_accept_pulse_o <= 1'b0;
            cmd_reject_pulse_o <= 1'b0;
            beat_accept_pulse_o <= 1'b0;
            write_done_pulse_o <= 1'b0;
            protocol_error_pulse_o <= 1'b0;
        end else begin
            cmd_accept_pulse_o <= 1'b0;
            cmd_reject_pulse_o <= 1'b0;
            beat_accept_pulse_o <= 1'b0;
            write_done_pulse_o <= 1'b0;
            protocol_error_pulse_o <= 1'b0;

            if (clear_i || !enable_i) begin
                state_q <= MSTATE_IDLE;
                current_addr_q <= '0;
                cmd_bytes_q <= 64'd0;
                bytes_written_q <= 64'd0;
                bytes_remaining_q <= 64'd0;
                hold_valid_q <= 1'b0;
                hold_data_q <= '0;
                hold_keep_q <= '0;
                hold_last_q <= 1'b0;
                response_completes_record_q <= 1'b0;
                if (clear_i) begin
                    waitrequest_seen_sticky_o <= 1'b0;
                    response_error_sticky_o <= 1'b0;
                end
            end else if (response_error || response_unexpected) begin
                response_error_sticky_o <= 1'b1;
                protocol_error_pulse_o <= 1'b1;
                hold_valid_q <= 1'b0;
                response_completes_record_q <= 1'b0;
                state_q <= MSTATE_ERROR;
            end else begin
                unique case (state_q)
                    MSTATE_IDLE: begin
                        hold_valid_q <= 1'b0;
                        if (cmd_accept) begin
                            current_addr_q <= cmd_addr_i;
                            cmd_bytes_q <= cmd_bytes_i;
                            bytes_written_q <= 64'd0;
                            bytes_remaining_q <= cmd_bytes_i;
                            response_completes_record_q <= 1'b0;
                            waitrequest_seen_sticky_o <= 1'b0;
                            cmd_accept_pulse_o <= 1'b1;
                            state_q <= MSTATE_WRITE;
                        end else if (cmd_reject) begin
                            cmd_reject_pulse_o <= 1'b1;
                            protocol_error_pulse_o <= 1'b1;
                            state_q <= MSTATE_ERROR;
                        end
                    end

                    MSTATE_WRITE: begin
                        if (waitrequest_active_o) begin
                            waitrequest_seen_sticky_o <= 1'b1;
                        end

                        if (write_accept) begin
                            if (write_protocol_error) begin
                                protocol_error_pulse_o <= 1'b1;
                                hold_valid_q <= 1'b0;
                                state_q <= MSTATE_ERROR;
                            end else begin
                                beat_accept_pulse_o <= 1'b1;
                                bytes_written_q <= bytes_next;
                                bytes_remaining_q <= cmd_bytes_q - bytes_next;
                                current_addr_q <= current_addr_q + BEAT_BYTES_ADDR;
                                hold_valid_q <= 1'b0;
                                if (CHECK_RESPONSES) begin
                                    response_completes_record_q <= write_done_ok;
                                    state_q <= MSTATE_WAIT_RESPONSE;
                                end else if (write_done_ok) begin
                                    // Response-less integrations can only prove request
                                    // acceptance.  The DE1-SoC Step-11 path enables responses.
                                    write_done_pulse_o <= 1'b1;
                                    state_q <= MSTATE_IDLE;
                                end
                            end
                        end

                        if (stream_accept) begin
                            if (stream_keep_legal) begin
                                hold_valid_q <= 1'b1;
                                hold_data_q <= stream_data_i;
                                hold_keep_q <= stream_keep_i;
                                hold_last_q <= stream_last_i;
                            end else begin
                                protocol_error_pulse_o <= 1'b1;
                                hold_valid_q <= 1'b0;
                                state_q <= MSTATE_ERROR;
                            end
                        end
                    end

                    MSTATE_WAIT_RESPONSE: begin
                        // No write or stream-ready is asserted in this state, so there is exactly
                        // one outstanding single-beat transaction.  A response error is handled by
                        // the fail-closed priority branch above.
                        if (response_success) begin
                            if (response_completes_record_q) begin
                                write_done_pulse_o <= 1'b1;
                                state_q <= MSTATE_IDLE;
                            end else begin
                                state_q <= MSTATE_WRITE;
                            end
                            response_completes_record_q <= 1'b0;
                        end
                    end

                    MSTATE_ERROR: begin
                        hold_valid_q <= 1'b0;
                        response_completes_record_q <= 1'b0;
                        if (clear_i) begin
                            state_q <= MSTATE_IDLE;
                        end
                    end

                    default: begin
                        hold_valid_q <= 1'b0;
                        response_completes_record_q <= 1'b0;
                        protocol_error_pulse_o <= 1'b1;
                        state_q <= MSTATE_ERROR;
                    end
                endcase
            end
        end
    end

`ifndef SYNTHESIS
    initial begin
        if ((DATA_W < 8) || ((DATA_W % 8) != 0)) begin
            $fatal(1, "trecap_avmm_write_master: DATA_W must be positive and byte-aligned");
        end
        if (BYTEEN_W != (DATA_W / 8)) begin
            $fatal(1, "trecap_avmm_write_master: BYTEEN_W must match DATA_W/8");
        end
        if (BURSTCOUNT_W < 1) begin
            $fatal(1, "trecap_avmm_write_master: BURSTCOUNT_W must be at least 1");
        end
    end
`endif

endmodule : trecap_avmm_write_master

`default_nettype wire
