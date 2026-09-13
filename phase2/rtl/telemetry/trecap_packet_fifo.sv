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
//   * The FIFO captures the full record into a temporary buffer and admits it atomically at the
//     record boundary. Malformed or oversized records are drained and counted as one drop.
//
// Output side:
//   * The HPS-bridge record builder sees a ready/valid byte stream with metadata stable for all
//     beats of one record.
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
  import trecap_packet_pkg::*;
  import trecap_iface_pkg::*;
  import trecap_build_pkg::*;
#(
    parameter int unsigned PAYLOAD_DATA_W    = 32,
    parameter int unsigned PAYLOAD_KEEP_W    = (PAYLOAD_DATA_W + 7) / 8,
    parameter int unsigned RECORD_DEPTH      = 8,
    parameter int unsigned PAYLOAD_BYTES_MAX = TPKT_UDP_MAX_BYTES
) (
    input  logic                       clk,
    input  logic                       rst_n,
    // Synchronous FIFO flush in clk domain. It discards partial capture and all resident records;
    // it is intentionally not converted into a derived asynchronous reset.
    input  logic                       flush_i,

    input  logic                       in_valid_i,
    output logic                       in_ready_o,
    input  trecap_record_meta_t        in_meta_i,
    input  logic [PAYLOAD_DATA_W-1:0]  in_payload_data_i,
    input  logic [PAYLOAD_KEEP_W-1:0]  in_payload_keep_i,
    input  logic                       in_payload_last_i,

    output logic                       out_valid_o,
    input  logic                       out_ready_i,
    output trecap_record_meta_t        out_meta_o,
    output logic [PAYLOAD_DATA_W-1:0]  out_payload_data_o,
    output logic [PAYLOAD_KEEP_W-1:0]  out_payload_keep_o,
    output logic                       out_payload_last_o,

    output logic                       drop_pulse_o,
    output logic                       full_o,
    output logic                       overflow_sticky_o
);

    localparam int unsigned BEAT_BYTES = PAYLOAD_KEEP_W;
    localparam int unsigned STORE_BYTES = (PAYLOAD_BYTES_MAX < 1) ? 1 : PAYLOAD_BYTES_MAX;
    localparam int unsigned STORE_W = STORE_BYTES * 8;
    localparam int unsigned COUNT_W = (RECORD_DEPTH <= 1) ? 1 : $clog2(RECORD_DEPTH + 1);
    localparam int unsigned IDX_W = (RECORD_DEPTH <= 1) ? 1 : $clog2(RECORD_DEPTH);
    localparam int unsigned LEN_W = (STORE_BYTES <= 1) ? 1 : $clog2(STORE_BYTES + 1);
    localparam logic [15:0] BEAT_BYTES_U16 = BEAT_BYTES;
    localparam logic [15:0] STORE_BYTES_U16 = (STORE_BYTES > 65535) ? 16'hffff : STORE_BYTES;
    localparam logic [COUNT_W-1:0] RECORD_DEPTH_COUNT = RECORD_DEPTH;

    typedef logic [STORE_W-1:0] payload_store_t;

    typedef enum logic [1:0] {
        FSTATE_IDLE    = 2'd0,
        FSTATE_CAPTURE = 2'd1,
        FSTATE_ADMIT   = 2'd2
    } fifo_state_e;

    fifo_state_e fifo_state_q;

    trecap_record_meta_t q_meta [RECORD_DEPTH];
    logic [15:0]         q_payload_len [RECORD_DEPTH];
    payload_store_t      q_payload [RECORD_DEPTH];
    logic [COUNT_W-1:0]  q_count_q;

    trecap_record_meta_t tmp_meta_q;
    logic [15:0]         tmp_payload_len_q;
    payload_store_t      tmp_payload_q;
    logic                tmp_bad_q;

    logic [15:0]         out_offset_q;

    logic [RECORD_DEPTH-1:0]              resident_valid;
    logic [RECORD_DEPTH-1:0]              resident_evictable;
    logic [(RECORD_DEPTH*2)-1:0]          resident_priority_flat;

    logic                                 tmp_meta_legal;
    logic                                 tmp_malformed;
    logic [1:0]                           tmp_priority;
    logic                                 storage_available;
    logic                                 dropper_admit;
    logic                                 dropper_admit_without_evict;
    logic                                 dropper_admit_with_evict;
    logic                                 dropper_evict_valid;
    logic [IDX_W-1:0]                     dropper_evict_index;
    logic [1:0]                           dropper_evict_priority;
    logic                                 dropper_drop_incoming;
    logic                                 dropper_lower_priority_available;

    logic                                 output_accept;
    logic                                 output_last_accept;
    logic [15:0]                          output_beat_bytes;

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

    function automatic payload_store_t insert_payload_beat(
        input payload_store_t                  current_payload,
        input logic [15:0]                     byte_offset,
        input logic [PAYLOAD_DATA_W-1:0]       beat_data,
        input logic [PAYLOAD_KEEP_W-1:0]       beat_keep
    );
        payload_store_t next_payload;
        int unsigned write_count;
        int unsigned target_index;

        next_payload = current_payload;
        write_count = 0;
        for (int unsigned i = 0; i < PAYLOAD_KEEP_W; i++) begin
            if (beat_keep[i]) begin
                target_index = int'(byte_offset) + write_count;
                if (target_index < STORE_BYTES) begin
                    next_payload[(target_index * 8) +: 8] = beat_data[(i * 8) +: 8];
                end
                write_count++;
            end
        end
        return next_payload;
    endfunction : insert_payload_beat

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

    function automatic logic [15:0] min_u16(input logic [15:0] a, input logic [15:0] b);
        return (a < b) ? a : b;
    endfunction : min_u16

    function automatic logic [PAYLOAD_DATA_W-1:0] payload_data_at(
        input payload_store_t payload,
        input logic [15:0]    offset,
        input logic [15:0]    payload_len
    );
        logic [PAYLOAD_DATA_W-1:0] data;
        int unsigned source_index;

        data = '0;
        for (int unsigned i = 0; i < PAYLOAD_KEEP_W; i++) begin
            source_index = int'(offset) + i;
            if (source_index < int'(payload_len)) begin
                data[(i * 8) +: 8] = payload[(source_index * 8) +: 8];
            end
        end
        return data;
    endfunction : payload_data_at

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

    assign in_ready_o = !flush_i &&
                        ((fifo_state_q == FSTATE_IDLE) || (fifo_state_q == FSTATE_CAPTURE));
    assign storage_available = (q_count_q < RECORD_DEPTH_COUNT);
    assign full_o = !flush_i && !storage_available;

    assign out_valid_o = !flush_i && (q_count_q != '0);
    assign out_meta_o = out_valid_o ? q_meta[0] : '0;
    assign out_payload_data_o = out_valid_o ? payload_data_at(q_payload[0], out_offset_q, q_payload_len[0]) : '0;
    assign out_payload_keep_o = out_valid_o ? payload_keep_at(out_offset_q, q_payload_len[0]) : '0;
    assign out_payload_last_o = out_valid_o ? ((q_payload_len[0] - out_offset_q) <= BEAT_BYTES_U16) : 1'b0;
    assign output_beat_bytes = out_valid_o ? min_u16(BEAT_BYTES_U16, q_payload_len[0] - out_offset_q) : 16'd0;
    assign output_accept = out_valid_o && out_ready_i;
    assign output_last_accept = output_accept && out_payload_last_o;

    always_comb begin
        for (int unsigned i = 0; i < RECORD_DEPTH; i++) begin
            resident_valid[i] = (i < q_count_q);
            resident_evictable[i] = resident_valid[i] && !(out_valid_o && (i == 0));
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

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            fifo_state_q <= FSTATE_IDLE;
            q_count_q <= '0;
            out_offset_q <= 16'd0;
            tmp_meta_q <= '0;
            tmp_payload_len_q <= 16'd0;
            tmp_payload_q <= '0;
            tmp_bad_q <= 1'b0;
            drop_pulse_o <= 1'b0;
            overflow_sticky_o <= 1'b0;

            for (int unsigned i = 0; i < RECORD_DEPTH; i++) begin
                q_meta[i] <= '0;
                q_payload_len[i] <= 16'd0;
                q_payload[i] <= '0;
            end
        end else if (flush_i) begin
            fifo_state_q <= FSTATE_IDLE;
            q_count_q <= '0;
            out_offset_q <= 16'd0;
            tmp_meta_q <= '0;
            tmp_payload_len_q <= 16'd0;
            tmp_payload_q <= '0;
            tmp_bad_q <= 1'b0;
            drop_pulse_o <= 1'b0;
            overflow_sticky_o <= 1'b0;

            for (int unsigned i = 0; i < RECORD_DEPTH; i++) begin
                q_meta[i] <= '0;
                q_payload_len[i] <= 16'd0;
                q_payload[i] <= '0;
            end
        end else begin
            drop_pulse_o <= 1'b0;

            // Downstream consumption. This block owns output record stability; record eviction never
            // targets queue entry 0 while out_valid_o is asserted.
            if (output_accept) begin
                if (out_payload_last_o) begin
                    for (int unsigned i = 0; i < RECORD_DEPTH - 1; i++) begin
                        if (i < (q_count_q - 1'b1)) begin
                            q_meta[i] <= q_meta[i + 1];
                            q_payload_len[i] <= q_payload_len[i + 1];
                            q_payload[i] <= q_payload[i + 1];
                        end
                    end
                    if (q_count_q != '0) begin
                        q_meta[q_count_q - 1'b1] <= '0;
                        q_payload_len[q_count_q - 1'b1] <= 16'd0;
                        q_payload[q_count_q - 1'b1] <= '0;
                        q_count_q <= q_count_q - 1'b1;
                    end
                    out_offset_q <= 16'd0;
                end else begin
                    out_offset_q <= out_offset_q + output_beat_bytes;
                end
            end

            unique case (fifo_state_q)
                FSTATE_IDLE: begin
                    if (in_valid_i && in_ready_o) begin
                        tmp_meta_q <= in_meta_i;
                        tmp_payload_q <= insert_payload_beat('0, 16'd0, in_payload_data_i, in_payload_keep_i);
                        tmp_payload_len_q <= count_keep_bytes(in_payload_keep_i);
                        tmp_bad_q <= !beat_keep_legal(in_payload_keep_i, in_payload_last_i) ||
                                     (count_keep_bytes(in_payload_keep_i) > STORE_BYTES_U16);
                        fifo_state_q <= in_payload_last_i ? FSTATE_ADMIT : FSTATE_CAPTURE;
                    end
                end

                FSTATE_CAPTURE: begin
                    if (in_valid_i && in_ready_o) begin
                        tmp_payload_q <= insert_payload_beat(
                            tmp_payload_q,
                            tmp_payload_len_q,
                            in_payload_data_i,
                            in_payload_keep_i
                        );
                        tmp_bad_q <= tmp_bad_q ||
                                     !beat_keep_legal(in_payload_keep_i, in_payload_last_i) ||
                                     ((tmp_payload_len_q + count_keep_bytes(in_payload_keep_i)) > STORE_BYTES_U16);
                        tmp_payload_len_q <= tmp_payload_len_q + count_keep_bytes(in_payload_keep_i);
                        if (in_payload_last_i) begin
                            fifo_state_q <= FSTATE_ADMIT;
                        end
                    end
                end

                FSTATE_ADMIT: begin
                    // If the output head is being popped this cycle, wait one cycle so admission sees
                    // the post-pop queue state. This avoids falsely evicting or dropping when a slot is
                    // about to become free.
                    if (!output_last_accept) begin
                        if (dropper_admit_without_evict) begin
                            q_meta[q_count_q] <= sanitized_meta(tmp_meta_q);
                            q_payload_len[q_count_q] <= tmp_payload_len_q;
                            q_payload[q_count_q] <= tmp_payload_q;
                            q_count_q <= q_count_q + 1'b1;
                        end else if (dropper_admit_with_evict && dropper_evict_valid) begin
                            // Remove the selected resident, compact the queue, and append the incoming
                            // record at the tail. The evicted resident counts as one pre-writer drop.
                            for (int unsigned i = 0; i < RECORD_DEPTH - 1; i++) begin
                                if ((i >= dropper_evict_index) && (i < (q_count_q - 1'b1))) begin
                                    q_meta[i] <= q_meta[i + 1];
                                    q_payload_len[i] <= q_payload_len[i + 1];
                                    q_payload[i] <= q_payload[i + 1];
                                end
                            end
                            q_meta[q_count_q - 1'b1] <= sanitized_meta(tmp_meta_q);
                            q_payload_len[q_count_q - 1'b1] <= tmp_payload_len_q;
                            q_payload[q_count_q - 1'b1] <= tmp_payload_q;
                            drop_pulse_o <= 1'b1;
                            overflow_sticky_o <= 1'b1;
                        end else begin
                            // Malformed record, oversized record, or no lower-priority resident could
                            // be evicted. The completed incoming record is shed as one telemetry drop.
                            drop_pulse_o <= 1'b1;
                            overflow_sticky_o <= 1'b1;
                        end

                        tmp_meta_q <= '0;
                        tmp_payload_len_q <= 16'd0;
                        tmp_payload_q <= '0;
                        tmp_bad_q <= 1'b0;
                        fifo_state_q <= FSTATE_IDLE;
                    end
                end

                default: begin
                    fifo_state_q <= FSTATE_IDLE;
                end
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
