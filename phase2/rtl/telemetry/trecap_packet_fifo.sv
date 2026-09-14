// SPDX-License-Identifier: MIT
// File class: [1] hand-written RTL.
// Layer: rtl/telemetry/
// Owner: T-RECAP Phase 2 implementation.
// Purpose: Priority-aware formatted telemetry record FIFO.
// Contract: Buffers trecap_record_meta_t plus payload bytes before rtl/hps_bridge/. It may shed
//           telemetry, but it shall not implement DDR writes, WRAP records, HPS, Ethernet, or core
//           signal-processing behavior.

`default_nettype none

// Priority-aware packet FIFO for complete telemetry records.
//
// Input side:
//   * The upstream scheduler provides one payload beat stream per record.
//   * in_meta_i is sampled on the first accepted beat and must describe the full record.
//   * Payload bytes are packed according to in_payload_keep_i, low byte first.
//   * The FIFO captures the full record into a reserved RAM slot and admits it atomically at the
//     record boundary. Malformed or oversized records are drained and counted as one drop.
//
// Output side:
//   * The HPS-bridge record builder sees a ready/valid byte stream with metadata stable for all
//     valid beats of one record. When out_valid_o is low, out_meta_o.valid is low and the other
//     metadata fields are inactive values from the output register; consumers must ignore them.
//   * No DDR header, sequence allocation, 64-byte padding, WRAP marker, Avalon, HPS, or UDP logic
//     is implemented here; those belong in rtl/hps_bridge/ and sw/hps/.
//
// Priority policy:
//   * If space is available, admit the completed incoming record.
//   * If full, evict the oldest resident among the lowest-priority residents below the incoming
//     priority, then append the incoming record at the tail.
//   * If no lower-priority resident is evictable, drop the incoming record.
//   * The output head is not evictable while it is being presented to the downstream ready/valid
//     interface, preserving output stability.
module trecap_packet_fifo
#(
    parameter int unsigned PAYLOAD_DATA_W    = 32,
    parameter int unsigned PAYLOAD_KEEP_W    = (PAYLOAD_DATA_W + 7) / 8,
    parameter int unsigned RECORD_DEPTH      = 8,
    parameter int unsigned PAYLOAD_BYTES_MAX = trecap_packet_pkg::TPKT_UDP_MAX_BYTES
) (
    input  logic                       clk,
    input  logic                       rst_n,
    // Synchronous FIFO flush in clk domain. It discards partial capture and all resident records;
    // it is intentionally not converted into a derived asynchronous reset.
    input  logic                       flush_i,

    input  logic                       in_valid_i,
    output logic                       in_ready_o,
    input  trecap_iface_pkg::trecap_record_meta_t        in_meta_i,
    input  logic [PAYLOAD_DATA_W-1:0]  in_payload_data_i,
    input  logic [PAYLOAD_KEEP_W-1:0]  in_payload_keep_i,
    input  logic                       in_payload_last_i,

    output logic                       out_valid_o,
    input  logic                       out_ready_i,
    output trecap_iface_pkg::trecap_record_meta_t        out_meta_o,
    output logic [PAYLOAD_DATA_W-1:0]  out_payload_data_o,
    output logic [PAYLOAD_KEEP_W-1:0]  out_payload_keep_o,
    output logic                       out_payload_last_o,

    output logic                       drop_pulse_o,
    output logic                       full_o,
    output logic                       overflow_sticky_o
);
  import trecap_packet_pkg::*;
  import trecap_iface_pkg::*;
  import trecap_build_pkg::*;


    localparam int unsigned BEAT_BYTES = PAYLOAD_KEEP_W;
    localparam int unsigned STORE_BYTES = (PAYLOAD_BYTES_MAX < 1) ? 1 : PAYLOAD_BYTES_MAX;
    localparam int unsigned WORDS_PER_SLOT = (STORE_BYTES + BEAT_BYTES - 1) / BEAT_BYTES;
    localparam int unsigned SLOT_COUNT = RECORD_DEPTH + 1;
    localparam int unsigned SLOT_W = (SLOT_COUNT <= 1) ? 1 : $clog2(SLOT_COUNT);
    localparam int unsigned STORE_WORDS = SLOT_COUNT * WORDS_PER_SLOT;
    localparam int unsigned RAM_ADDR_W = (STORE_WORDS <= 1) ? 1 : $clog2(STORE_WORDS);
    localparam int unsigned COUNT_W = (RECORD_DEPTH <= 1) ? 1 : $clog2(RECORD_DEPTH + 1);
    localparam int unsigned IDX_W = (RECORD_DEPTH <= 1) ? 1 : $clog2(RECORD_DEPTH);
    localparam logic [15:0] BEAT_BYTES_U16 = 16'(BEAT_BYTES);
    localparam logic [COUNT_W-1:0] RECORD_DEPTH_COUNT = COUNT_W'(RECORD_DEPTH);

    typedef enum logic [1:0] {
        FSTATE_IDLE, FSTATE_CAPTURE, FSTATE_ADMIT
    } fifo_state_e;
    fifo_state_e fifo_state_q;

    // One flat simple-dual-port M10K payload store: RECORD_DEPTH resident
    // slots plus one reserved capture slot. Admission and eviction move only
    // metadata/slot identifiers; no record payload is copied or shifted.
    (* ramstyle = "M10K" *) logic [PAYLOAD_DATA_W-1:0] payload_mem [0:STORE_WORDS-1];
    logic [PAYLOAD_DATA_W-1:0] payload_read_q;
    logic [SLOT_COUNT-1:0] slot_used_q;
    logic free_slot_valid;
    logic [SLOT_W-1:0] free_slot;
    logic [SLOT_W-1:0] tmp_slot_q;
    logic [SLOT_W-1:0] q_slot [RECORD_DEPTH];
    trecap_record_meta_t q_meta [RECORD_DEPTH];
    logic [15:0] q_payload_len [RECORD_DEPTH];
    logic [COUNT_W-1:0] q_count_q;

    trecap_record_meta_t tmp_meta_q;
    logic [15:0] tmp_payload_len_q;
    logic tmp_bad_q;
    logic input_accept;
    logic [15:0] input_beat_bytes;
    logic [15:0] input_byte_offset;
    logic [16:0] input_total_bytes;
    logic input_store_enable;
    logic [RAM_ADDR_W-1:0] input_store_addr;

    logic [15:0] out_offset_q;
    logic output_read_request;
    logic [15:0] output_read_offset;
    logic [RAM_ADDR_W-1:0] output_read_addr;
    logic output_read_pending_q;
    trecap_record_meta_t read_meta_q;
    logic [PAYLOAD_KEEP_W-1:0] read_keep_q;
    logic read_last_q;
    logic output_valid_q;
    trecap_record_meta_t output_meta_q;
    logic [PAYLOAD_DATA_W-1:0] output_data_q;
    logic [PAYLOAD_KEEP_W-1:0] output_keep_q;
    logic output_last_q;
    logic output_accept;
    logic output_last_accept;
    logic [15:0] output_beat_bytes;

    logic [RECORD_DEPTH-1:0] resident_valid;
    logic [RECORD_DEPTH-1:0] resident_evictable;
    logic [(RECORD_DEPTH*2)-1:0] resident_priority_flat;
    logic tmp_meta_legal;
    logic tmp_malformed;
    logic [1:0] tmp_priority;
    logic storage_available;
    logic dropper_admit;
    logic dropper_admit_without_evict;
    logic dropper_admit_with_evict;
    logic dropper_evict_valid;
    logic [IDX_W-1:0] dropper_evict_index;
    logic [1:0] dropper_evict_priority;
    logic dropper_drop_incoming;
    logic dropper_lower_priority_available;
    function automatic logic [15:0] count_keep_bytes(input logic [PAYLOAD_KEEP_W-1:0] keep);
        logic [15:0] count;

        count = 16'd0;
        for (int unsigned i = 0; i < PAYLOAD_KEEP_W; i++) begin
            count = count + (keep[i] ? 16'd1 : 16'd0);
        end
        return count;
    endfunction : count_keep_bytes

    function automatic bit keep_is_low_contiguous(input logic [PAYLOAD_KEEP_W-1:0] keep);
        bit seen_zero;

        seen_zero = 1'b0;
        for (int unsigned i = 0; i < PAYLOAD_KEEP_W; i++) begin
            if (!keep[i]) begin
                seen_zero = 1'b1;
            end else if (seen_zero) begin
                return 1'b0;
            end
        end
        return 1'b1;
    endfunction : keep_is_low_contiguous

    function automatic bit keep_is_full(input logic [PAYLOAD_KEEP_W-1:0] keep);
        return keep == {PAYLOAD_KEEP_W{1'b1}};
    endfunction : keep_is_full

    function automatic bit beat_keep_legal(
        input logic [PAYLOAD_KEEP_W-1:0] keep,
        input logic                       last
    );
        if (!keep_is_low_contiguous(keep)) begin
            return 1'b0;
        end
        if (count_keep_bytes(keep) == 16'd0) begin
            return 1'b0;
        end
        if (!last && !keep_is_full(keep)) begin
            return 1'b0;
        end
        return 1'b1;
    endfunction : beat_keep_legal

    function automatic bit meta_legal_for_fifo(
        input trecap_record_meta_t meta,
        input logic [15:0]          captured_payload_bytes
    );
        int unsigned payload_bytes_u;

        payload_bytes_u = int'(meta.payload_bytes);

        if (!meta.valid) begin
            return 1'b0;
        end
        if (!trecap_packet_type_known(meta.packet_type)) begin
            return 1'b0;
        end
        if (trecap_packet_type_reserved_disabled(meta.packet_type)) begin
            return 1'b0;
        end
        if (meta.packet_type == TPKT_WRAP) begin
            // WRAP is a DDR-ring control record. It is generated only by rtl/hps_bridge/.
            return 1'b0;
        end
        if (payload_bytes_u > STORE_BYTES) begin
            return 1'b0;
        end
        if ((TPKT_HEADER_BYTES + payload_bytes_u) > TPKT_UDP_MAX_BYTES) begin
            return 1'b0;
        end
        if (!trecap_payload_bytes_valid(meta.packet_type, payload_bytes_u)) begin
            return 1'b0;
        end
        if (captured_payload_bytes != meta.payload_bytes) begin
            return 1'b0;
        end
        if (meta.drop_priority != trecap_packet_drop_priority(meta.packet_type)) begin
            return 1'b0;
        end
        return 1'b1;
    endfunction : meta_legal_for_fifo

    function automatic trecap_record_meta_t sanitized_meta(input trecap_record_meta_t meta);
        trecap_record_meta_t fixed;

        fixed = meta;
        fixed.valid = 1'b1;
        fixed.drop_priority = trecap_packet_drop_priority(meta.packet_type);
        return fixed;
    endfunction : sanitized_meta

    function automatic logic [PAYLOAD_KEEP_W-1:0] payload_keep_at(
        input logic [15:0] offset,
        input logic [15:0] payload_len
    );
        logic [PAYLOAD_KEEP_W-1:0] keep;
        int unsigned source_index;

        keep = '0;
        for (int unsigned i = 0; i < PAYLOAD_KEEP_W; i++) begin
            source_index = int'(offset) + i;
            if (source_index < int'(payload_len)) begin
                keep[i] = 1'b1;
            end
        end
        return keep;
    endfunction : payload_keep_at

    function automatic logic [RAM_ADDR_W-1:0] slot_word_address(
        input logic [SLOT_W-1:0] slot,
        input logic [15:0] byte_offset
    );
        return RAM_ADDR_W'(int'(slot) * WORDS_PER_SLOT + int'(byte_offset) / BEAT_BYTES);
    endfunction

    always_comb begin
        free_slot_valid = 1'b0;
        free_slot = '0;
        for (int unsigned i = 0; i < SLOT_COUNT; i++) begin
            if (!slot_used_q[i] && !free_slot_valid) begin
                free_slot_valid = 1'b1;
                free_slot = SLOT_W'(i);
            end
        end
    end

    assign in_ready_o = rst_n && !flush_i &&
                        (((fifo_state_q == FSTATE_IDLE) && free_slot_valid) ||
                         (fifo_state_q == FSTATE_CAPTURE));
    assign input_accept = in_valid_i && in_ready_o;
    assign input_beat_bytes = count_keep_bytes(in_payload_keep_i);
    assign input_byte_offset = (fifo_state_q == FSTATE_IDLE) ? 16'd0 : tmp_payload_len_q;
    assign input_total_bytes = {1'b0, input_byte_offset} + {1'b0, input_beat_bytes};
    assign input_store_enable = input_accept &&
                                ((fifo_state_q == FSTATE_IDLE) || !tmp_bad_q) &&
                                beat_keep_legal(in_payload_keep_i, in_payload_last_i) &&
                                (input_total_bytes <= STORE_BYTES);
    assign input_store_addr = slot_word_address(
        (fifo_state_q == FSTATE_IDLE) ? free_slot : tmp_slot_q, input_byte_offset);
    assign storage_available = (q_count_q < RECORD_DEPTH_COUNT);
    assign full_o = rst_n && !flush_i && !storage_available;

    assign out_valid_o = rst_n && !flush_i && output_valid_q;
    // Keep late flush/valid control out of downstream payload-length arithmetic. Only the
    // validity field is qualified; inactive metadata cannot authorize a record transaction.
    always_comb begin
        out_meta_o = output_meta_q;
        out_meta_o.valid = out_valid_o && output_meta_q.valid;
    end
    assign out_payload_data_o = out_valid_o ? output_data_q : '0;
    assign out_payload_keep_o = out_valid_o ? output_keep_q : '0;
    assign out_payload_last_o = out_valid_o && output_last_q;
    assign output_beat_bytes = count_keep_bytes(output_keep_q);
    assign output_accept = out_valid_o && out_ready_i;
    assign output_last_accept = output_accept && output_last_q;

    // A RAM read reserves the output register before it can stall. A nonlast
    // accepted beat can issue its successor on the same edge. The queue head
    // stays protected during both read latency and downstream backpressure.
    assign output_read_request = rst_n && !flush_i && (q_count_q != '0) &&
                                 !output_read_pending_q &&
                                 (!output_valid_q || (output_accept && !output_last_q));
    assign output_read_offset = output_valid_q
                                ? out_offset_q + output_beat_bytes : out_offset_q;
    assign output_read_addr = slot_word_address(q_slot[0], output_read_offset);

    always_ff @(posedge clk) begin : p_payload_storage
        if (input_store_enable) payload_mem[input_store_addr] <= in_payload_data_i;
        if (output_read_request) payload_read_q <= payload_mem[output_read_addr];
    end

    always_comb begin
        for (int unsigned i = 0; i < RECORD_DEPTH; i++) begin
            resident_valid[i] = (i < q_count_q);
            resident_evictable[i] = resident_valid[i] && (i != 0);
            resident_priority_flat[(i * 2) +: 2] = q_meta[i].drop_priority;
        end
    end
    assign tmp_meta_legal = meta_legal_for_fifo(tmp_meta_q, tmp_payload_len_q);
    assign tmp_malformed = tmp_bad_q || !tmp_meta_legal;
    assign tmp_priority = trecap_packet_drop_priority(tmp_meta_q.packet_type);
    trecap_priority_dropper #(
        .RECORD_DEPTH(RECORD_DEPTH),
        .PRIORITY_W(2)
    ) u_priority_dropper (
        .request_i(fifo_state_q == FSTATE_ADMIT),
        .incoming_malformed_i(tmp_malformed),
        .storage_available_i(storage_available),
        .incoming_priority_i(tmp_priority),
        .resident_valid_i(resident_valid),
        .resident_evictable_i(resident_evictable),
        .resident_priority_flat_i(resident_priority_flat),
        .admit_o(dropper_admit),
        .admit_without_evict_o(dropper_admit_without_evict),
        .admit_with_evict_o(dropper_admit_with_evict),
        .evict_valid_o(dropper_evict_valid),
        .evict_index_o(dropper_evict_index),
        .evict_priority_o(dropper_evict_priority),
        .drop_incoming_o(dropper_drop_incoming),
        .lower_priority_available_o(dropper_lower_priority_available)
    );

    always_ff @(posedge clk or negedge rst_n) begin : p_packet_fifo
        if (!rst_n) begin
            fifo_state_q <= FSTATE_IDLE;
            slot_used_q <= '0;
            q_count_q <= '0;
            tmp_slot_q <= '0;
            tmp_meta_q <= '0;
            tmp_payload_len_q <= '0;
            tmp_bad_q <= 1'b0;
            out_offset_q <= '0;
            output_read_pending_q <= 1'b0;
            read_meta_q <= '0;
            read_keep_q <= '0;
            read_last_q <= 1'b0;
            output_valid_q <= 1'b0;
            output_meta_q <= '0;
            output_data_q <= '0;
            output_keep_q <= '0;
            output_last_q <= 1'b0;
            drop_pulse_o <= 1'b0;
            overflow_sticky_o <= 1'b0;
            for (int unsigned i = 0; i < RECORD_DEPTH; i++) begin
                q_meta[i] <= '0;
                q_payload_len[i] <= '0;
                q_slot[i] <= '0;
            end
        end else if (flush_i) begin
            // Slot ownership and response validity define the epoch. RAM is
            // deliberately untouched; a slot is published only after all of
            // its declared payload bytes have been written in the new epoch.
            fifo_state_q <= FSTATE_IDLE;
            slot_used_q <= '0;
            q_count_q <= '0;
            tmp_slot_q <= '0;
            tmp_meta_q <= '0;
            tmp_payload_len_q <= '0;
            tmp_bad_q <= 1'b0;
            out_offset_q <= '0;
            output_read_pending_q <= 1'b0;
            output_valid_q <= 1'b0;
            output_meta_q <= '0;
            output_data_q <= '0;
            output_keep_q <= '0;
            output_last_q <= 1'b0;
            drop_pulse_o <= 1'b0;
            overflow_sticky_o <= 1'b0;
        end else begin
            drop_pulse_o <= 1'b0;
            if (output_accept) begin
                output_valid_q <= 1'b0;
                if (output_last_q) begin
                    slot_used_q[q_slot[0]] <= 1'b0;
                    for (int unsigned i = 0; i < RECORD_DEPTH - 1; i++) begin
                        if (i < (q_count_q - 1'b1)) begin
                            q_meta[i] <= q_meta[i + 1];
                            q_payload_len[i] <= q_payload_len[i + 1];
                            q_slot[i] <= q_slot[i + 1];
                        end
                    end
                    q_count_q <= q_count_q - 1'b1;
                    out_offset_q <= '0;
                end else out_offset_q <= out_offset_q + output_beat_bytes;
            end

            if (output_read_request) begin
                output_read_pending_q <= 1'b1;
                read_meta_q <= q_meta[0];
                read_keep_q <= payload_keep_at(output_read_offset, q_payload_len[0]);
                read_last_q <= ((q_payload_len[0] - output_read_offset) <= BEAT_BYTES_U16);
            end
            if (output_read_pending_q) begin
                output_read_pending_q <= 1'b0;
                output_valid_q <= 1'b1;
                output_meta_q <= read_meta_q;
                output_keep_q <= read_keep_q;
                output_last_q <= read_last_q;
                for (int unsigned i = 0; i < BEAT_BYTES; i++) begin
                    output_data_q[(i * 8) +: 8] <= read_keep_q[i]
                                                  ? payload_read_q[(i * 8) +: 8] : 8'd0;
                end
            end

            case (fifo_state_q)
                FSTATE_IDLE: begin
                    if (input_accept) begin
                        tmp_slot_q <= free_slot;
                        slot_used_q[free_slot] <= 1'b1;
                        tmp_meta_q <= in_meta_i;
                        tmp_payload_len_q <= input_beat_bytes;
                        tmp_bad_q <= !beat_keep_legal(in_payload_keep_i, in_payload_last_i) ||
                                     (input_total_bytes > STORE_BYTES);
                        fifo_state_q <= in_payload_last_i ? FSTATE_ADMIT : FSTATE_CAPTURE;
                    end
                end
                FSTATE_CAPTURE: begin
                    if (input_accept) begin
                        tmp_payload_len_q <= input_total_bytes[16] ? 16'hffff : input_total_bytes[15:0];
                        tmp_bad_q <= tmp_bad_q ||
                                     !beat_keep_legal(in_payload_keep_i, in_payload_last_i) ||
                                     (input_total_bytes > STORE_BYTES);
                        if (in_payload_last_i) fifo_state_q <= FSTATE_ADMIT;
                    end
                end
                FSTATE_ADMIT: begin
                    // Observe a coincident head pop before making the admission
                    // decision. Only small queue metadata is compacted here.
                    if (!output_last_accept) begin
                        if (dropper_admit_without_evict) begin
                            q_meta[q_count_q] <= sanitized_meta(tmp_meta_q);
                            q_payload_len[q_count_q] <= tmp_payload_len_q;
                            q_slot[q_count_q] <= tmp_slot_q;
                            q_count_q <= q_count_q + 1'b1;
                        end else if (dropper_admit_with_evict && dropper_evict_valid) begin
                            slot_used_q[q_slot[dropper_evict_index]] <= 1'b0;
                            for (int unsigned i = 0; i < RECORD_DEPTH - 1; i++) begin
                                if ((i >= dropper_evict_index) && (i < (q_count_q - 1'b1))) begin
                                    q_meta[i] <= q_meta[i + 1];
                                    q_payload_len[i] <= q_payload_len[i + 1];
                                    q_slot[i] <= q_slot[i + 1];
                                end
                            end
                            q_meta[q_count_q - 1'b1] <= sanitized_meta(tmp_meta_q);
                            q_payload_len[q_count_q - 1'b1] <= tmp_payload_len_q;
                            q_slot[q_count_q - 1'b1] <= tmp_slot_q;
                            drop_pulse_o <= 1'b1;
                            overflow_sticky_o <= 1'b1;
                        end else begin
                            slot_used_q[tmp_slot_q] <= 1'b0;
                            drop_pulse_o <= 1'b1;
                            overflow_sticky_o <= 1'b1;
                        end
                        tmp_meta_q <= '0;
                        tmp_payload_len_q <= '0;
                        tmp_bad_q <= 1'b0;
                        fifo_state_q <= FSTATE_IDLE;
                    end
                end
                default: fifo_state_q <= FSTATE_IDLE;
            endcase
        end
    end
`ifndef SYNTHESIS
    initial begin
        if (PAYLOAD_DATA_W < 8) begin
            $fatal(1, "trecap_packet_fifo: PAYLOAD_DATA_W must be at least 8");
        end
        if ((PAYLOAD_DATA_W % 8) != 0) begin
            $fatal(1, "trecap_packet_fifo: PAYLOAD_DATA_W must be byte-aligned");
        end
        if (PAYLOAD_KEEP_W != ((PAYLOAD_DATA_W + 7) / 8)) begin
            $fatal(1, "trecap_packet_fifo: PAYLOAD_KEEP_W must match PAYLOAD_DATA_W bytes");
        end
        if (RECORD_DEPTH < 1) begin
            $fatal(1, "trecap_packet_fifo: RECORD_DEPTH must be at least 1");
        end
        if ((PAYLOAD_BYTES_MAX < 1) || (PAYLOAD_BYTES_MAX > 65535)) begin
            $fatal(1, "trecap_packet_fifo: payload capacity must fit its 16-bit byte-count contract");
        end
        if (PAYLOAD_BYTES_MAX < (TPKT_UDP_MAX_BYTES - TPKT_HEADER_BYTES)) begin
            $warning(
                "trecap_packet_fifo: PAYLOAD_BYTES_MAX=%0d below Revision G legal UDP payload max %0d",
                PAYLOAD_BYTES_MAX,
                TPKT_UDP_MAX_BYTES - TPKT_HEADER_BYTES
            );
        end
    end

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            // No simulation state.
        end else if (!flush_i) begin
            if (out_valid_o && !out_meta_o.valid) begin
                $error("trecap_packet_fifo: output valid asserted with invalid metadata");
            end
            if (out_valid_o && !trecap_payload_bytes_valid(out_meta_o.packet_type, int'(out_meta_o.payload_bytes))) begin
                $error("trecap_packet_fifo: output metadata has illegal payload size");
            end
            if (in_valid_i && in_ready_o && !keep_is_low_contiguous(in_payload_keep_i)) begin
                $error("trecap_packet_fifo: input payload keep is not low-contiguous");
            end
        end
    end
`endif

endmodule : trecap_packet_fifo

`default_nettype wire
