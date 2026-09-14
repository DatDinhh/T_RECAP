// SPDX-License-Identifier: MIT
// File class: [1] hand-written RTL.
// Layer: rtl/hps_bridge/
// Owner: T-RECAP Phase 2 implementation.
// Purpose: Build Revision G DDR/UDP record headers, payload bodies, and 64-byte padding.
// Contract: Convert formatted telemetry payload records into byte streams ready for DDR writes;
//           do not decide ring free space, do not commit pointers, and do not own Ethernet/HPS.
// Generated dependencies: trecap_packet_pkg, trecap_iface_pkg.

`default_nettype none

// T-RECAP DDR record builder.
//
// The telemetry layer emits metadata plus payload bytes. This block adds the 32-byte Revision G
// common header, reads the captured payload, streams zero padding to 64-byte DDR alignment, and emits a byte-lane
// ready/valid stream to the DDR writer. It can also build a WRAP control record when explicitly
// requested by the DDR writer, but it does not decide when wrapping is required.
//
// Normal record sequence numbers are supplied by the ring-pointer/writer side through sequence_i.
// Packetizer-provided meta.seq is ignored for normal records because Revision G allocates sequence
// numbers only after a normal telemetry record is accepted for DDR commit. The writer shall advance
// the sequence only after the normal record has actually committed.
module trecap_ddr_record_builder
#(
    parameter int unsigned IN_DATA_W  = 32,
    parameter int unsigned IN_KEEP_W  = (IN_DATA_W + 7) / 8,
    parameter int unsigned OUT_DATA_W = 64,
    parameter int unsigned OUT_KEEP_W = (OUT_DATA_W + 7) / 8,
    parameter int unsigned RECORD_BYTES_MAX =
        (((trecap_packet_pkg::TPKT_UDP_MAX_BYTES + trecap_packet_pkg::TPKT_DDR_ALIGN_BYTES - 1) / trecap_packet_pkg::TPKT_DDR_ALIGN_BYTES) *
         trecap_packet_pkg::TPKT_DDR_ALIGN_BYTES)
) (
    input  logic                      clk,
    input  logic                      rst_n,

    input  logic                      clear_i,
    input  logic                      enable_i,

    // Sequence number to place in the next normal telemetry header. Ignored for WRAP records.
    input  logic [31:0]               sequence_i,

    // Normal formatted payload stream from rtl/telemetry/trecap_packet_fifo.sv.
    input  logic                      in_valid_i,
    output logic                      in_ready_o,
    input  trecap_iface_pkg::trecap_record_meta_t       in_meta_i,
    input  logic [IN_DATA_W-1:0]      in_payload_data_i,
    input  logic [IN_KEEP_W-1:0]      in_payload_keep_i,
    input  logic                      in_payload_last_i,

    // Explicit WRAP request from the DDR writer. The effective length is the physical tail length
    // R - off(W). It must be 64-byte aligned and at least 64 bytes. WRAP has payload_bytes = 0.
    input  logic                      wrap_valid_i,
    output logic                      wrap_ready_o,
    input  logic [63:0]               wrap_effective_bytes_i,

    // DDR-write byte stream. out_keep_o is low-contiguous. Padding bytes are zero and are included
    // in this stream; HPS software strips DDR padding before forwarding UDP.
    output logic                      out_valid_o,
    input  logic                      out_ready_i,
    output logic [OUT_DATA_W-1:0]     out_data_o,
    output logic [OUT_KEEP_W-1:0]     out_keep_o,
    output logic                      out_last_o,

    // Stable while a record is emitted.
    output logic                      out_record_start_pulse_o,
    output logic                      out_record_done_pulse_o,
    output logic                      out_is_wrap_o,
    output trecap_iface_pkg::trecap_record_meta_t       out_meta_o,
    output logic [31:0]               out_seq_o,
    output logic [15:0]               out_payload_bytes_o,
    output logic [63:0]               out_record_bytes_o,

    // Builder-local drops/errors. These are not DDR ring-space drops; the top-level bridge shall
    // map them to malformed/oversized sticky flags and counters as required.
    output logic                      busy_o,
    output logic                      drop_pulse_o,
    output logic                      malformed_pulse_o,
    output logic                      oversized_pulse_o
);
  import trecap_packet_pkg::*;
  import trecap_iface_pkg::*;
  import trecap_build_pkg::*;


    localparam int unsigned IN_BEAT_BYTES = IN_KEEP_W;
    localparam int unsigned OUT_BEAT_BYTES = OUT_KEEP_W;
    localparam int unsigned PAYLOAD_BYTES_MAX = TPKT_UDP_MAX_BYTES - TPKT_HEADER_BYTES;
    localparam int unsigned PAYLOAD_WORDS = (PAYLOAD_BYTES_MAX + IN_BEAT_BYTES - 1) / IN_BEAT_BYTES;
    localparam int unsigned PAYLOAD_ADDR_W = (PAYLOAD_WORDS <= 1) ? 1 : $clog2(PAYLOAD_WORDS);
    localparam int unsigned OUT_LANE_W = (OUT_BEAT_BYTES <= 1) ? 1 : $clog2(OUT_BEAT_BYTES);
    localparam logic [15:0] TPKT_HEADER_VERSION_U16 = 16'(TPKT_HEADER_VERSION);
    localparam logic [15:0] TPKT_HEADER_BYTES_U16 = 16'(TPKT_HEADER_BYTES);
    localparam logic [63:0] HEADER_BYTES_64 = TPKT_HEADER_BYTES;
    localparam logic [63:0] UDP_MAX_BYTES_64 = TPKT_UDP_MAX_BYTES;
    localparam logic [63:0] DDR_ALIGN_MASK_64 = (TPKT_DDR_ALIGN_BYTES - 1);
    localparam int unsigned RECORD_STORE_BYTES = (RECORD_BYTES_MAX < TPKT_DDR_ALIGN_BYTES) ?
                                                TPKT_DDR_ALIGN_BYTES : RECORD_BYTES_MAX;
    localparam logic [15:0] OUT_BEAT_BYTES_U16 = 16'(OUT_BEAT_BYTES);
    // Both normal and WRAP lengths pass the full-width RECORD_STORE_BYTES
    // bound in BSTATE_BUILD before these registers are loaded. The emit offset
    // starts at zero and advances only for a nonterminal accepted beat.
    localparam int unsigned RECORD_OFFSET_W =
        (RECORD_STORE_BYTES < 1) ? 1 : $clog2(64'(RECORD_STORE_BYTES) + 64'd1);
    typedef logic [(TPKT_HEADER_BYTES*8)-1:0] header_store_t;

    typedef enum logic [2:0] {
        BSTATE_IDLE, BSTATE_CAPTURE, BSTATE_BUILD,
        BSTATE_ASSEMBLE, BSTATE_READ_WAIT, BSTATE_EMIT
    } builder_state_e;
    builder_state_e state_q;
    trecap_record_meta_t meta_q;
    logic [15:0] payload_len_q;
    logic capture_bad_q;
    logic pending_wrap_q;
    logic [63:0] pending_wrap_bytes_q;

    // One capture workspace. No payload or RAM read-data register reset:
    // only a fully captured, validated record is allowed into the emit phase.
    (* ramstyle = "M10K" *) logic [IN_DATA_W-1:0] payload_mem [0:PAYLOAD_WORDS-1];
    logic [IN_DATA_W-1:0] payload_read_q;
    logic input_accept;
    logic [15:0] input_beat_bytes;
    logic [15:0] input_byte_offset;
    logic [16:0] input_total_bytes;
    logic payload_write_enable;
    logic [PAYLOAD_ADDR_W-1:0] payload_write_addr;
    logic payload_read_enable;
    logic [PAYLOAD_ADDR_W-1:0] payload_read_addr;

    header_store_t header_q;
    logic [RECORD_OFFSET_W-1:0] record_bytes_q;
    logic [15:0] record_payload_bytes_q;
    logic [31:0] record_seq_q;
    trecap_record_meta_t record_meta_q;
    logic record_is_wrap_q;
    logic [RECORD_OFFSET_W-1:0] emit_offset_q;
    logic [OUT_LANE_W-1:0] assemble_lane_q;
    logic [OUT_DATA_W-1:0] output_data_q;
    logic cache_valid_q;
    logic [PAYLOAD_ADDR_W-1:0] cache_addr_q;
    logic [IN_DATA_W-1:0] cache_data_q;
    logic [63:0] assemble_byte_offset;
    logic [63:0] assemble_payload_offset;
    logic assemble_needs_payload;
    logic cache_hit;
    logic [7:0] assemble_byte;
    logic output_accept;
    logic output_last_accept;

    logic normal_meta_valid;
    logic normal_flags_valid;
    logic normal_size_valid;
    logic normal_oversized;
    logic normal_malformed;
    logic [63:0] normal_record_bytes;
    logic wrap_size_valid;
    logic wrap_oversized;
    function automatic logic [15:0] count_keep_bytes(input logic [IN_KEEP_W-1:0] keep);
        logic [15:0] count;

        count = 16'd0;
        for (int unsigned i = 0; i < IN_KEEP_W; i++) begin
            count = count + (keep[i] ? 16'd1 : 16'd0);
        end
        return count;
    endfunction : count_keep_bytes

    function automatic bit keep_is_low_contiguous(input logic [IN_KEEP_W-1:0] keep);
        bit seen_zero;

        seen_zero = 1'b0;
        for (int unsigned i = 0; i < IN_KEEP_W; i++) begin
            if (!keep[i]) begin
                seen_zero = 1'b1;
            end else if (seen_zero) begin
                return 1'b0;
            end
        end
        return 1'b1;
    endfunction : keep_is_low_contiguous

    function automatic bit keep_is_full(input logic [IN_KEEP_W-1:0] keep);
        return keep == {IN_KEEP_W{1'b1}};
    endfunction : keep_is_full

    function automatic bit input_keep_legal(
        input logic [IN_KEEP_W-1:0] keep,
        input logic                  last
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
    endfunction : input_keep_legal

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
        end else begin
            if (aggregate_metrics || per_frame_metrics) begin
                return 1'b0;
            end
        end

        return 1'b1;
    endfunction : flags_legal_for_packet

    function automatic bit meta_legal_for_normal(input trecap_record_meta_t meta);
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
            return 1'b0;
        end
        if (!flags_legal_for_packet(meta.packet_type, meta.flags)) begin
            return 1'b0;
        end
        if (meta.drop_priority != trecap_packet_drop_priority(meta.packet_type)) begin
            return 1'b0;
        end
        return 1'b1;
    endfunction : meta_legal_for_normal

    function automatic logic [63:0] align64(input logic [63:0] value);
        return (value + DDR_ALIGN_MASK_64) & ~DDR_ALIGN_MASK_64;
    endfunction : align64

    function automatic bit is_aligned64(input logic [63:0] value);
        return ((value & DDR_ALIGN_MASK_64) == 64'd0);
    endfunction : is_aligned64

    function automatic header_store_t put_byte(
        input header_store_t current_record,
        input int unsigned   byte_offset,
        input logic [7:0]    value
    );
        header_store_t next_record;

        next_record = current_record;
        if (byte_offset < TPKT_HEADER_BYTES) begin
            next_record[(byte_offset * 8) +: 8] = value;
        end
        return next_record;
    endfunction : put_byte

    function automatic header_store_t put_u16_le(
        input header_store_t current_record,
        input int unsigned   byte_offset,
        input logic [15:0]   value
    );
        header_store_t next_record;

        next_record = current_record;
        next_record = put_byte(next_record, byte_offset + 0, value[7:0]);
        next_record = put_byte(next_record, byte_offset + 1, value[15:8]);
        return next_record;
    endfunction : put_u16_le

    function automatic header_store_t put_u32_le(
        input header_store_t current_record,
        input int unsigned   byte_offset,
        input logic [31:0]   value
    );
        header_store_t next_record;

        next_record = current_record;
        for (int unsigned i = 0; i < 4; i++) begin
            next_record = put_byte(next_record, byte_offset + i, value[(i * 8) +: 8]);
        end
        return next_record;
    endfunction : put_u32_le

    function automatic header_store_t put_u64_le(
        input header_store_t current_record,
        input int unsigned   byte_offset,
        input logic [63:0]   value
    );
        header_store_t next_record;

        next_record = current_record;
        for (int unsigned i = 0; i < 8; i++) begin
            next_record = put_byte(next_record, byte_offset + i, value[(i * 8) +: 8]);
        end
        return next_record;
    endfunction : put_u64_le

    function automatic header_store_t put_common_header(
        input header_store_t       current_record,
        input trecap_packet_type_e packet_type,
        input logic [15:0]         flags,
        input logic [31:0]         seq,
        input logic [63:0]         timestamp,
        input logic [31:0]         payload_bytes
    );
        header_store_t next_record;
        logic [15:0] packet_type_bits;

        packet_type_bits = packet_type;
        next_record = current_record;
        next_record = put_u32_le(next_record, TPKT_HDR_MAGIC_OFFSET, TPKT_TELEMETRY_MAGIC);
        next_record = put_u16_le(next_record, TPKT_HDR_VERSION_OFFSET, TPKT_HEADER_VERSION_U16);
        next_record = put_u16_le(next_record, TPKT_HDR_HEADER_BYTES_OFFSET, TPKT_HEADER_BYTES_U16);
        next_record = put_u16_le(next_record, TPKT_HDR_PACKET_TYPE_OFFSET, packet_type_bits);
        next_record = put_u16_le(next_record, TPKT_HDR_FLAGS_OFFSET, flags);
        next_record = put_u32_le(next_record, TPKT_HDR_SEQ_OFFSET, seq);
        next_record = put_u64_le(next_record, TPKT_HDR_TIMESTAMP_OFFSET, timestamp);
        next_record = put_u32_le(next_record, TPKT_HDR_PAYLOAD_BYTES_OFFSET, payload_bytes);
        next_record = put_u32_le(next_record, TPKT_HDR_HEADER_CRC_OFFSET, 32'h0000_0000);
        return next_record;
    endfunction : put_common_header

    function automatic header_store_t build_wrap_record();
        header_store_t next_record;
        next_record = '0;
        next_record = put_common_header(
            next_record,
            TPKT_WRAP,
            16'h0000,
            32'h0000_0000,
            64'h0000_0000_0000_0000,
            32'h0000_0000
        );
        return next_record;
    endfunction : build_wrap_record


    function automatic trecap_record_meta_t meta_with_sequence(
        input trecap_record_meta_t meta,
        input logic [31:0]         seq
    );
        trecap_record_meta_t fixed;

        fixed = meta;
        fixed.seq = seq;
        return fixed;
    endfunction : meta_with_sequence

    function automatic logic [OUT_KEEP_W-1:0] record_keep_at(
        input logic [63:0] offset,
        input logic [63:0] record_len
    );
        logic [OUT_KEEP_W-1:0] keep;

        keep = '0;
        for (int unsigned i = 0; i < OUT_KEEP_W; i++) begin
            if ((offset + i) < record_len) begin
                keep[i] = 1'b1;
            end
        end
        return keep;
    endfunction : record_keep_at

    assign normal_meta_valid = meta_legal_for_normal(meta_q);
    assign normal_flags_valid = flags_legal_for_packet(meta_q.packet_type, meta_q.flags);
    assign normal_size_valid = trecap_payload_bytes_valid(meta_q.packet_type, int'(meta_q.payload_bytes)) &&
                               (payload_len_q == meta_q.payload_bytes) &&
                               ((TPKT_HEADER_BYTES + int'(meta_q.payload_bytes)) <= TPKT_UDP_MAX_BYTES);
    assign normal_record_bytes = align64(HEADER_BYTES_64 + {48'd0, payload_len_q});
    assign normal_oversized = (HEADER_BYTES_64 + {48'd0, payload_len_q}) > UDP_MAX_BYTES_64 ||
                              (normal_record_bytes > RECORD_STORE_BYTES);
    assign normal_malformed = capture_bad_q || !normal_meta_valid || !normal_flags_valid ||
                              !normal_size_valid || normal_oversized;

    assign wrap_size_valid = (pending_wrap_bytes_q >= TPKT_DDR_ALIGN_BYTES) &&
                             (pending_wrap_bytes_q <= RECORD_STORE_BYTES) &&
                             is_aligned64(pending_wrap_bytes_q);
    assign wrap_oversized = pending_wrap_bytes_q > RECORD_STORE_BYTES;

    assign in_ready_o = rst_n && !clear_i && enable_i && !wrap_valid_i &&
                        ((state_q == BSTATE_IDLE) || (state_q == BSTATE_CAPTURE));
    assign wrap_ready_o = rst_n && !clear_i && enable_i && (state_q == BSTATE_IDLE);
    assign input_accept = in_valid_i && in_ready_o;
    assign input_beat_bytes = count_keep_bytes(in_payload_keep_i);
    assign input_byte_offset = (state_q == BSTATE_IDLE) ? 16'd0 : payload_len_q;
    assign input_total_bytes = {1'b0, input_byte_offset} + {1'b0, input_beat_bytes};
    assign payload_write_enable = input_accept &&
                                  ((state_q == BSTATE_IDLE) || !capture_bad_q) &&
                                  input_keep_legal(in_payload_keep_i, in_payload_last_i) &&
                                  (input_total_bytes <= PAYLOAD_BYTES_MAX);
    assign payload_write_addr = PAYLOAD_ADDR_W'(int'(input_byte_offset) / IN_BEAT_BYTES);

    assign assemble_byte_offset = 64'(emit_offset_q) + 64'(assemble_lane_q);
    assign assemble_payload_offset = assemble_byte_offset - HEADER_BYTES_64;
    assign assemble_needs_payload = !record_is_wrap_q &&
                                    (assemble_byte_offset >= HEADER_BYTES_64) &&
                                    (assemble_payload_offset < {48'd0, record_payload_bytes_q});
    assign payload_read_addr = PAYLOAD_ADDR_W'(assemble_payload_offset / IN_BEAT_BYTES);
    assign cache_hit = cache_valid_q && (cache_addr_q == payload_read_addr);
    assign payload_read_enable = rst_n && !clear_i && enable_i &&
                                 (state_q == BSTATE_ASSEMBLE) &&
                                 assemble_needs_payload && !cache_hit;

    // Data accesses are phase exclusive. One enabled write stores each legal
    // input beat; one synchronous read fills the small output assembly cache.
    always_ff @(posedge clk) begin : p_payload_storage
        if (payload_write_enable) payload_mem[payload_write_addr] <= in_payload_data_i;
        if (payload_read_enable) payload_read_q <= payload_mem[payload_read_addr];
    end

    always_comb begin
        assemble_byte = 8'd0;
        if (assemble_byte_offset < HEADER_BYTES_64)
            assemble_byte = header_q[(int'(assemble_byte_offset) * 8) +: 8];
        else if (assemble_needs_payload && cache_hit)
            assemble_byte = cache_data_q[((int'(assemble_payload_offset) % IN_BEAT_BYTES) * 8) +: 8];
    end

    assign out_valid_o = rst_n && !clear_i && enable_i && (state_q == BSTATE_EMIT);
    assign out_data_o = out_valid_o ? output_data_q : '0;
    assign out_keep_o = out_valid_o ? record_keep_at(64'(emit_offset_q), 64'(record_bytes_q)) : '0;
    assign out_last_o = out_valid_o && ((64'(emit_offset_q) + OUT_BEAT_BYTES_U16) >= record_bytes_q);
    assign output_accept = out_valid_o && out_ready_i;
    assign output_last_accept = output_accept && out_last_o;
    assign out_is_wrap_o = record_is_wrap_q;
    assign out_meta_o = record_meta_q;
    assign out_seq_o = record_seq_q;
    assign out_payload_bytes_o = record_payload_bytes_q;
    assign out_record_bytes_o = 64'(record_bytes_q);
    assign busy_o = (state_q != BSTATE_IDLE);

    always_ff @(posedge clk or negedge rst_n) begin : p_record_builder
        if (!rst_n) begin
            state_q <= BSTATE_IDLE;
            meta_q <= '0;
            payload_len_q <= '0;
            capture_bad_q <= 1'b0;
            pending_wrap_q <= 1'b0;
            pending_wrap_bytes_q <= '0;
            header_q <= '0;
            record_bytes_q <= '0;
            record_payload_bytes_q <= '0;
            record_seq_q <= '0;
            record_meta_q <= '0;
            record_is_wrap_q <= 1'b0;
            emit_offset_q <= '0;
            assemble_lane_q <= '0;
            output_data_q <= '0;
            cache_valid_q <= 1'b0;
            cache_addr_q <= '0;
            cache_data_q <= '0;
            out_record_start_pulse_o <= 1'b0;
            out_record_done_pulse_o <= 1'b0;
            drop_pulse_o <= 1'b0;
            malformed_pulse_o <= 1'b0;
            oversized_pulse_o <= 1'b0;
        end else begin
            out_record_start_pulse_o <= 1'b0;
            out_record_done_pulse_o <= 1'b0;
            drop_pulse_o <= 1'b0;
            malformed_pulse_o <= 1'b0;
            oversized_pulse_o <= 1'b0;
            if (clear_i || !enable_i) begin
                state_q <= BSTATE_IDLE;
                meta_q <= '0;
                payload_len_q <= '0;
                capture_bad_q <= 1'b0;
                pending_wrap_q <= 1'b0;
                pending_wrap_bytes_q <= '0;
                header_q <= '0;
                record_bytes_q <= '0;
                record_payload_bytes_q <= '0;
                record_seq_q <= '0;
                record_meta_q <= '0;
                record_is_wrap_q <= 1'b0;
                emit_offset_q <= '0;
                assemble_lane_q <= '0;
                output_data_q <= '0;
                cache_valid_q <= 1'b0;
            end else begin
                case (state_q)
                    BSTATE_IDLE: begin
                        if (wrap_valid_i && wrap_ready_o) begin
                            meta_q <= '0;
                            payload_len_q <= '0;
                            capture_bad_q <= 1'b0;
                            pending_wrap_q <= 1'b1;
                            pending_wrap_bytes_q <= wrap_effective_bytes_i;
                            state_q <= BSTATE_BUILD;
                        end else if (input_accept) begin
                            meta_q <= in_meta_i;
                            payload_len_q <= input_beat_bytes;
                            capture_bad_q <= !input_keep_legal(in_payload_keep_i, in_payload_last_i) ||
                                             (input_total_bytes > PAYLOAD_BYTES_MAX);
                            pending_wrap_q <= 1'b0;
                            pending_wrap_bytes_q <= '0;
                            state_q <= in_payload_last_i ? BSTATE_BUILD : BSTATE_CAPTURE;
                        end
                    end
                    BSTATE_CAPTURE: begin
                        if (input_accept) begin
                            payload_len_q <= input_total_bytes[16] ? 16'hffff : input_total_bytes[15:0];
                            capture_bad_q <= capture_bad_q ||
                                             !input_keep_legal(in_payload_keep_i, in_payload_last_i) ||
                                             (input_total_bytes > PAYLOAD_BYTES_MAX);
                            if (in_payload_last_i) state_q <= BSTATE_BUILD;
                        end
                    end
                    BSTATE_BUILD: begin
                        emit_offset_q <= '0;
                        assemble_lane_q <= '0;
                        output_data_q <= '0;
                        cache_valid_q <= 1'b0;
                        if (pending_wrap_q) begin
                            if (wrap_size_valid) begin
                                header_q <= build_wrap_record();
                                record_bytes_q <= RECORD_OFFSET_W'(pending_wrap_bytes_q);
                                record_payload_bytes_q <= '0;
                                record_seq_q <= '0;
                                record_meta_q <= '{valid: 1'b1, packet_type: TPKT_WRAP,
                                    flags: 16'd0, seq: 32'd0, timestamp: 64'd0,
                                    payload_bytes: 16'd0, drop_priority: 2'd0};
                                record_is_wrap_q <= 1'b1;
                                out_record_start_pulse_o <= 1'b1;
                                state_q <= BSTATE_ASSEMBLE;
                            end else begin
                                drop_pulse_o <= 1'b1;
                                malformed_pulse_o <= !wrap_oversized;
                                oversized_pulse_o <= wrap_oversized;
                                pending_wrap_q <= 1'b0;
                                pending_wrap_bytes_q <= '0;
                                state_q <= BSTATE_IDLE;
                            end
                        end else if (!normal_malformed) begin
                            header_q <= put_common_header('0, meta_q.packet_type, meta_q.flags,
                                                         sequence_i, meta_q.timestamp,
                                                         {16'd0, payload_len_q});
                            record_bytes_q <= RECORD_OFFSET_W'(normal_record_bytes);
                            record_payload_bytes_q <= payload_len_q;
                            record_seq_q <= sequence_i;
                            record_meta_q <= meta_with_sequence(meta_q, sequence_i);
                            record_is_wrap_q <= 1'b0;
                            out_record_start_pulse_o <= 1'b1;
                            state_q <= BSTATE_ASSEMBLE;
                        end else begin
                            drop_pulse_o <= 1'b1;
                            malformed_pulse_o <= !normal_oversized;
                            oversized_pulse_o <= normal_oversized;
                            meta_q <= '0;
                            payload_len_q <= '0;
                            capture_bad_q <= 1'b0;
                            state_q <= BSTATE_IDLE;
                        end
                    end
                    BSTATE_ASSEMBLE: begin
                        if (assemble_needs_payload && !cache_hit) begin
                            cache_addr_q <= payload_read_addr;
                            state_q <= BSTATE_READ_WAIT;
                        end else begin
                            output_data_q[(int'(assemble_lane_q) * 8) +: 8] <= assemble_byte;
                            if ((assemble_lane_q == OUT_LANE_W'(OUT_BEAT_BYTES - 1)) ||
                                ((assemble_byte_offset + 64'd1) >= record_bytes_q)) begin
                                state_q <= BSTATE_EMIT;
                            end else assemble_lane_q <= assemble_lane_q + 1'b1;
                        end
                    end
                    BSTATE_READ_WAIT: begin
                        cache_data_q <= payload_read_q;
                        cache_valid_q <= 1'b1;
                        state_q <= BSTATE_ASSEMBLE;
                    end
                    BSTATE_EMIT: begin
                        // The assembled beat and all record metadata remain
                        // unchanged until the downstream writer accepts it.
                        if (output_accept) begin
                            if (out_last_o) begin
                                out_record_done_pulse_o <= 1'b1;
                                meta_q <= '0;
                                payload_len_q <= '0;
                                capture_bad_q <= 1'b0;
                                pending_wrap_q <= 1'b0;
                                pending_wrap_bytes_q <= '0;
                                emit_offset_q <= '0;
                                cache_valid_q <= 1'b0;
                                state_q <= BSTATE_IDLE;
                            end else begin
                                emit_offset_q <= emit_offset_q + OUT_BEAT_BYTES_U16;
                                assemble_lane_q <= '0;
                                output_data_q <= '0;
                                state_q <= BSTATE_ASSEMBLE;
                            end
                        end
                    end
                    default: begin
                        state_q <= BSTATE_IDLE;
                        cache_valid_q <= 1'b0;
                    end
                endcase
            end
        end
    end
`ifndef SYNTHESIS
    initial begin
        if ((IN_DATA_W < 8) || ((IN_DATA_W % 8) != 0)) begin
            $fatal(1, "trecap_ddr_record_builder: IN_DATA_W must be positive and byte-aligned");
        end
        if ((OUT_DATA_W < 8) || ((OUT_DATA_W % 8) != 0)) begin
            $fatal(1, "trecap_ddr_record_builder: OUT_DATA_W must be positive and byte-aligned");
        end
        if (IN_KEEP_W != ((IN_DATA_W + 7) / 8)) begin
            $fatal(1, "trecap_ddr_record_builder: IN_KEEP_W must match IN_DATA_W bytes");
        end
        if (OUT_KEEP_W != ((OUT_DATA_W + 7) / 8)) begin
            $fatal(1, "trecap_ddr_record_builder: OUT_KEEP_W must match OUT_DATA_W bytes");
        end
        if (RECORD_BYTES_MAX < align64(TPKT_UDP_MAX_BYTES)) begin
            $fatal(1, "trecap_ddr_record_builder: RECORD_BYTES_MAX is below Revision G max record");
        end
    end

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            // No simulation state.
        end else begin
            if (out_valid_o && (out_keep_o == '0)) begin
                $error("trecap_ddr_record_builder: out_valid with empty byte keep");
            end
            if (out_valid_o && out_is_wrap_o && (out_payload_bytes_o != 16'd0)) begin
                $error("trecap_ddr_record_builder: WRAP record must have zero payload bytes");
            end
            if (out_valid_o && !out_is_wrap_o && (out_record_bytes_o != align64(HEADER_BYTES_64 + {48'd0, out_payload_bytes_o}))) begin
                $error("trecap_ddr_record_builder: normal record length is not align64(header+payload)");
            end
        end
    end
`endif

endmodule : trecap_ddr_record_builder

`default_nettype wire
