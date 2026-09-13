// SPDX-License-Identifier: MIT
// File class: [1] hand-written RTL.
// Layer: rtl/telemetry/
// Owner: T-RECAP Phase 2 implementation.
// Purpose: Non-stalling Revision G SPEC64/SPEC129 telemetry payload packetizer.
// Contract: Build exact little-endian spectrum-display payload beats from valid-only core bin taps;
//           do not drive ready into the core; do not write DDR; do not allocate sequence IDs.
// Generated dependencies: trecap_core_pkg, trecap_packet_pkg, trecap_iface_pkg,
//                         trecap_math_pkg, trecap_build_pkg.

`default_nettype none

// T-RECAP spectrum packetizer.
//
// This module observes a valid-only unique-bin stream from the core and emits one spectrum
// payload per complete frame. It supports the Revision G SPEC_MODE selector:
//   TSPEC_SPEC64  -> 64-bucket compressed magnitude plus suppressed/eligible counts
//   TSPEC_SPEC129 -> 129 unique-bin compressed magnitude plus final mask bits
//
// Payload fields are little endian and packed with no implicit padding. Magnitudes use
// clip16(mag2 >> spec_shift). The downstream HPS-bridge record builder owns the common header,
// DDR padding, WRAP records, sequence allocation, and DDR writes.
//
// The core-facing bin stream has no ready. If this module is busy, disabled, sees malformed bin
// order, or cannot complete a full 0..T_UNIQUE_BINS-1 frame, it drops that spectrum frame and
// reports one drop_pulse_o. The STFT/WOLA core keeps running.
module trecap_spec_packetizer
  import trecap_core_pkg::*;
  import trecap_packet_pkg::*;
  import trecap_iface_pkg::*;
  import trecap_math_pkg::*;
  import trecap_build_pkg::*;
#(
    parameter int unsigned PAYLOAD_DATA_W = 32,
    parameter int unsigned PAYLOAD_KEEP_W = (PAYLOAD_DATA_W + 7) / 8,
    parameter int unsigned BIN_IDX_W      = (T_UNIQUE_BINS <= 1) ? 1 : $clog2(T_UNIQUE_BINS)
) (
    input  logic                       clk,
    input  logic                       rst_n,
    // Synchronous formatter clear in clk domain. This aborts partial collection/emission without
    // deriving a second asynchronous reset from a software command.
    input  logic                       formatter_reset_i,

    input  logic                       enable_i,
    input  trecap_spec_mode_e          spec_mode_i,
    input  logic [5:0]                 spec_shift_i,
    input  trecap_core_tap_frame_t     tap_frame_i,

    input  logic                       tap_bin_valid_i,
    input  logic [63:0]                tap_bin_frame_idx_i,
    input  logic [BIN_IDX_W-1:0]       tap_bin_idx_i,
    input  logic [T_MAG2_W-1:0]        tap_bin_mag2_i,
    input  logic                       tap_bin_mask_i,
    input  logic                       tap_bin_eligible_i,
    input  logic                       tap_bin_last_i,

    output logic                       out_valid_o,
    input  logic                       out_ready_i,
    output trecap_record_meta_t        out_meta_o,
    output logic [PAYLOAD_DATA_W-1:0]  out_payload_data_o,
    output logic [PAYLOAD_KEEP_W-1:0]  out_payload_keep_o,
    output logic                       out_payload_last_o,

    output logic                       drop_pulse_o
);

    localparam int unsigned BYTES_PER_BEAT = PAYLOAD_KEEP_W;
    localparam int unsigned UNIQUE_BINS = T_UNIQUE_BINS;
    localparam int unsigned SPEC64_BUCKETS = 64;
    localparam int unsigned SPEC129_MASK_BYTES = (T_UNIQUE_BINS + 7) / 8;
    localparam int unsigned SPEC_PAYLOAD_MAX_BYTES =
        (TPKT_PAYLOAD_SPEC129_BYTES > TPKT_PAYLOAD_SPEC64_BYTES) ? TPKT_PAYLOAD_SPEC129_BYTES :
                                                                   TPKT_PAYLOAD_SPEC64_BYTES;
    localparam int unsigned PAYLOAD_OFF_W =
        (SPEC_PAYLOAD_MAX_BYTES <= 1) ? 1 : $clog2(SPEC_PAYLOAD_MAX_BYTES + 1);
    localparam int unsigned BIN_COUNT_W = (UNIQUE_BINS <= 1) ? 1 : $clog2(UNIQUE_BINS + 1);
    localparam int unsigned LAST_BIN_INDEX = UNIQUE_BINS - 1;
    localparam int unsigned SPEC_SHIFT_MAX_INT = T_MAG2_W - 1;

    typedef enum logic [1:0] {
        ST_IDLE    = 2'd0,
        ST_COLLECT = 2'd1,
        ST_SEND    = 2'd2,
        ST_DROP    = 2'd3
    } spec_state_e;

    spec_state_e state_q;

    logic [63:0]              frame_idx_q;
    trecap_spec_mode_e        mode_q;
    logic [5:0]               spec_shift_q;
    logic [BIN_COUNT_W-1:0]   expected_bin_q;
    logic [PAYLOAD_OFF_W-1:0] byte_offset_q;
    logic                     dropping_busy_frame_q;
    logic                     drop_pulse_q;

    logic [15:0] spec129_mag_q [0:UNIQUE_BINS-1];
    logic [7:0]  spec129_mask_byte_q [0:SPEC129_MASK_BYTES-1];

    logic [15:0] spec64_mag_q [0:SPEC64_BUCKETS-1];
    logic [7:0]  spec64_suppressed_q [0:SPEC64_BUCKETS-1];
    logic [7:0]  spec64_eligible_q [0:SPEC64_BUCKETS-1];

    logic                    mode_legal;
    logic [5:0]              shift_clamped;
    logic                    bin_index_valid;
    logic                    bin_order_valid;
    logic                    bin_frame_valid;
    logic                    bin_complete_valid;
    logic                    accepting_output_beat;
    logic                    output_last_beat;
    logic [PAYLOAD_OFF_W:0]  payload_bytes_comb;
    logic [PAYLOAD_OFF_W:0]  next_byte_offset;
    trecap_packet_type_e     packet_type_comb;
    logic [1:0]              packet_priority_comb;
    logic [15:0]             nbin_comb;
    logic [15:0]             compressed_bin;
    logic                    incoming_bin_observed;
    logic                    busy_frame_open_after_event;

    always_comb begin
        mode_legal = (spec_mode_i == TSPEC_SPEC64) || (spec_mode_i == TSPEC_SPEC129);
        shift_clamped = (int'(spec_shift_i) > SPEC_SHIFT_MAX_INT) ? 6'(SPEC_SHIFT_MAX_INT) : spec_shift_i;
        bin_index_valid = int'(tap_bin_idx_i) < UNIQUE_BINS;
        bin_order_valid = bin_index_valid && (int'(tap_bin_idx_i) == int'(expected_bin_q));
        bin_frame_valid = (state_q == ST_IDLE) ? 1'b1 : (tap_bin_frame_idx_i == frame_idx_q);
        bin_complete_valid = tap_bin_last_i && (int'(tap_bin_idx_i) == LAST_BIN_INDEX);
        compressed_bin = clip_mag2_to_u16(tap_bin_mag2_i, (state_q == ST_IDLE) ? shift_clamped : spec_shift_q);
        incoming_bin_observed = tap_bin_valid_i && enable_i && mode_legal;
        busy_frame_open_after_event = dropping_busy_frame_q;
        if ((state_q == ST_SEND) && incoming_bin_observed) begin
            busy_frame_open_after_event = !tap_bin_last_i;
        end
    end

    function automatic int unsigned bucket_for_bin(input int unsigned bin_idx);
        return (((bin_idx + 1) * SPEC64_BUCKETS) - 1) / UNIQUE_BINS;
    endfunction : bucket_for_bin

    function automatic logic [15:0] clip_mag2_to_u16(
        input logic [T_MAG2_W-1:0] mag2,
        input logic [5:0]          shift
    );
        return trecap_clip16_after_shift(trecap_math_uwide_t'(mag2), int'(shift));
    endfunction : clip_mag2_to_u16

    function automatic logic [7:0] get_u16_byte(
        input logic [15:0] value,
        input int unsigned byte_idx
    );
        return byte_idx[0] ? value[15:8] : value[7:0];
    endfunction : get_u16_byte

    function automatic logic [7:0] get_u64_byte(
        input logic [63:0] value,
        input int unsigned byte_idx
    );
        unique case (byte_idx[2:0])
            3'd0: return value[7:0];
            3'd1: return value[15:8];
            3'd2: return value[23:16];
            3'd3: return value[31:24];
            3'd4: return value[39:32];
            3'd5: return value[47:40];
            3'd6: return value[55:48];
            default: return value[63:56];
        endcase
    endfunction : get_u64_byte

    function automatic logic [7:0] spec129_payload_byte_at(input int unsigned off);
        int unsigned bin;
        int unsigned mask_byte;

        if (off < TPKT_SPEC129_NBIN_OFFSET) begin
            return get_u64_byte(frame_idx_q, off - TPKT_SPEC129_FRAME_IDX_OFFSET);
        end
        if (off < TPKT_SPEC129_SPEC_SHIFT_OFFSET) begin
            return get_u16_byte(16'(UNIQUE_BINS), off - TPKT_SPEC129_NBIN_OFFSET);
        end
        if (off < TPKT_SPEC129_SPEC129_OFFSET) begin
            return get_u16_byte({10'd0, spec_shift_q}, off - TPKT_SPEC129_SPEC_SHIFT_OFFSET);
        end
        if (off < TPKT_SPEC129_MASK_BITS_OFFSET) begin
            bin = (off - TPKT_SPEC129_SPEC129_OFFSET) / 2;
            if (bin < UNIQUE_BINS) begin
                return get_u16_byte(spec129_mag_q[bin], off - (TPKT_SPEC129_SPEC129_OFFSET + (2 * bin)));
            end
            return 8'h00;
        end

        mask_byte = off - TPKT_SPEC129_MASK_BITS_OFFSET;
        if (mask_byte < SPEC129_MASK_BYTES) begin
            return spec129_mask_byte_q[mask_byte];
        end
        return 8'h00;
    endfunction : spec129_payload_byte_at

    function automatic logic [7:0] spec64_payload_byte_at(input int unsigned off);
        int unsigned bucket;

        if (off < TPKT_SPEC64_NBIN_OFFSET) begin
            return get_u64_byte(frame_idx_q, off - TPKT_SPEC64_FRAME_IDX_OFFSET);
        end
        if (off < TPKT_SPEC64_SPEC_SHIFT_OFFSET) begin
            return get_u16_byte(16'(SPEC64_BUCKETS), off - TPKT_SPEC64_NBIN_OFFSET);
        end
        if (off < TPKT_SPEC64_SPEC64_OFFSET) begin
            return get_u16_byte({10'd0, spec_shift_q}, off - TPKT_SPEC64_SPEC_SHIFT_OFFSET);
        end
        if (off < TPKT_SPEC64_SUPPRESSED_COUNT_OFFSET) begin
            bucket = (off - TPKT_SPEC64_SPEC64_OFFSET) / 2;
            if (bucket < SPEC64_BUCKETS) begin
                return get_u16_byte(spec64_mag_q[bucket], off - (TPKT_SPEC64_SPEC64_OFFSET + (2 * bucket)));
            end
            return 8'h00;
        end
        if (off < TPKT_SPEC64_ELIGIBLE_COUNT_OFFSET) begin
            bucket = off - TPKT_SPEC64_SUPPRESSED_COUNT_OFFSET;
            if (bucket < SPEC64_BUCKETS) begin
                return spec64_suppressed_q[bucket];
            end
            return 8'h00;
        end

        bucket = off - TPKT_SPEC64_ELIGIBLE_COUNT_OFFSET;
        if (bucket < SPEC64_BUCKETS) begin
            return spec64_eligible_q[bucket];
        end
        return 8'h00;
    endfunction : spec64_payload_byte_at

    function automatic logic [7:0] payload_byte_at(input int unsigned off);
        if (mode_q == TSPEC_SPEC129) begin
            return spec129_payload_byte_at(off);
        end
        return spec64_payload_byte_at(off);
    endfunction : payload_byte_at

    task automatic clear_payload_state;
        begin
            for (int unsigned i = 0; i < UNIQUE_BINS; i++) begin
                spec129_mag_q[i] <= 16'd0;
            end
            for (int unsigned i = 0; i < SPEC129_MASK_BYTES; i++) begin
                spec129_mask_byte_q[i] <= 8'd0;
            end
            for (int unsigned i = 0; i < SPEC64_BUCKETS; i++) begin
                spec64_mag_q[i] <= 16'd0;
                spec64_suppressed_q[i] <= 8'd0;
                spec64_eligible_q[i] <= 8'd0;
            end
        end
    endtask : clear_payload_state

    task automatic capture_current_bin;
        int unsigned bin;
        int unsigned bucket;
        begin
            bin = int'(tap_bin_idx_i);
            bucket = bucket_for_bin(bin);

            spec129_mag_q[bin] <= compressed_bin;
            if (tap_bin_mask_i) begin
                spec129_mask_byte_q[bin / 8][bin % 8] <= 1'b1;
            end

            if (compressed_bin > spec64_mag_q[bucket]) begin
                spec64_mag_q[bucket] <= compressed_bin;
            end
            if (tap_bin_mask_i) begin
                spec64_suppressed_q[bucket] <= spec64_suppressed_q[bucket] + 8'd1;
            end
            if (tap_bin_eligible_i) begin
                spec64_eligible_q[bucket] <= spec64_eligible_q[bucket] + 8'd1;
            end
        end
    endtask : capture_current_bin

    always_comb begin
        unique case (mode_q)
            TSPEC_SPEC129: begin
                payload_bytes_comb = PAYLOAD_OFF_W'(TPKT_PAYLOAD_SPEC129_BYTES);
                packet_type_comb = TPKT_SPEC129;
                packet_priority_comb = TPKT_PRIORITY_SPEC129;
                nbin_comb = 16'(UNIQUE_BINS);
            end
            default: begin
                payload_bytes_comb = PAYLOAD_OFF_W'(TPKT_PAYLOAD_SPEC64_BYTES);
                packet_type_comb = TPKT_SPEC64;
                packet_priority_comb = TPKT_PRIORITY_SPEC64;
                nbin_comb = 16'(SPEC64_BUCKETS);
            end
        endcase

        next_byte_offset = byte_offset_q + PAYLOAD_OFF_W'(BYTES_PER_BEAT);
        accepting_output_beat = out_valid_o && out_ready_i;
        output_last_beat = out_valid_o && (next_byte_offset >= payload_bytes_comb);
    end

    always_comb begin
        out_payload_data_o = '0;
        out_payload_keep_o = '0;

        for (int unsigned lane = 0; lane < BYTES_PER_BEAT; lane++) begin
            if ((byte_offset_q + PAYLOAD_OFF_W'(lane)) < payload_bytes_comb) begin
                out_payload_data_o[(8*lane) +: 8] = payload_byte_at(byte_offset_q + lane);
                out_payload_keep_o[lane] = 1'b1;
            end
        end

        out_payload_last_o = output_last_beat;
    end

    assign out_valid_o = !formatter_reset_i && (state_q == ST_SEND);

    always_comb begin
        out_meta_o = '0;
        out_meta_o.valid = out_valid_o;
        out_meta_o.packet_type = packet_type_comb;
        out_meta_o.flags = TPKT_FLAG_PAYLOAD_SCALED_MASK;
        out_meta_o.seq = 32'd0;
        out_meta_o.timestamp = frame_idx_q;
        out_meta_o.payload_bytes = 16'(payload_bytes_comb);
        out_meta_o.drop_priority = packet_priority_comb;
    end

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state_q <= ST_IDLE;
            frame_idx_q <= 64'd0;
            mode_q <= TSPEC_SPEC64;
            spec_shift_q <= 6'd0;
            expected_bin_q <= '0;
            byte_offset_q <= '0;
            dropping_busy_frame_q <= 1'b0;
            drop_pulse_q <= 1'b0;
            clear_payload_state();
        end else if (formatter_reset_i) begin
            state_q <= ST_IDLE;
            frame_idx_q <= 64'd0;
            mode_q <= TSPEC_SPEC64;
            spec_shift_q <= 6'd0;
            expected_bin_q <= '0;
            byte_offset_q <= '0;
            dropping_busy_frame_q <= 1'b0;
            drop_pulse_q <= 1'b0;
            clear_payload_state();
        end else begin
            drop_pulse_q <= 1'b0;

            // A runtime disable or mode/config change may discard an uncommitted collection, but it
            // must not retract out_valid in ST_SEND. The already-started record drains atomically;
            // otherwise a downstream FIFO could retain a permanently unterminated record.
            if ((state_q != ST_SEND) && (!enable_i || !mode_legal)) begin
                // ST_DROP/dropping_busy_frame_q represents a frame whose loss was already counted
                // when the malformed or busy episode began. Disabling while locally draining that
                // frame only abandons the remainder; it must not count the same frame twice.
                if (state_q == ST_COLLECT) begin
                    drop_pulse_q <= 1'b1;
                end
                state_q <= ST_IDLE;
                expected_bin_q <= '0;
                byte_offset_q <= '0;
                dropping_busy_frame_q <= 1'b0;
            end else begin
                if (accepting_output_beat) begin
                    if (output_last_beat) begin
                        state_q <= busy_frame_open_after_event ? ST_DROP : ST_IDLE;
                        expected_bin_q <= '0;
                        byte_offset_q <= '0;
                    end else begin
                        byte_offset_q <= PAYLOAD_OFF_W'(next_byte_offset);
                    end
                end

                if (incoming_bin_observed) begin
                    unique case (state_q)
                        ST_IDLE: begin
                            if (bin_index_valid && (int'(tap_bin_idx_i) == 0) && bin_frame_valid) begin
                                frame_idx_q <= tap_bin_frame_idx_i;
                                mode_q <= spec_mode_i;
                                spec_shift_q <= shift_clamped;
                                expected_bin_q <= BIN_COUNT_W'(1);
                                byte_offset_q <= '0;
                                clear_payload_state();
                                capture_current_bin();

                                if (tap_bin_last_i) begin
                                    if (bin_complete_valid) begin
                                        state_q <= ST_SEND;
                                    end else begin
                                        drop_pulse_q <= 1'b1;
                                        state_q <= ST_IDLE;
                                    end
                                    expected_bin_q <= '0;
                                end else begin
                                    state_q <= ST_COLLECT;
                                end
                            end else begin
                                drop_pulse_q <= 1'b1;
                                state_q <= tap_bin_last_i ? ST_IDLE : ST_DROP;
                                expected_bin_q <= '0;
                            end
                        end

                        ST_COLLECT: begin
                            if (bin_frame_valid && bin_order_valid) begin
                                capture_current_bin();
                                if (tap_bin_last_i) begin
                                    if (bin_complete_valid) begin
                                        state_q <= ST_SEND;
                                    end else begin
                                        drop_pulse_q <= 1'b1;
                                        state_q <= ST_IDLE;
                                    end
                                    expected_bin_q <= '0;
                                    byte_offset_q <= '0;
                                end else begin
                                    expected_bin_q <= expected_bin_q + BIN_COUNT_W'(1);
                                end
                            end else begin
                                drop_pulse_q <= 1'b1;
                                state_q <= tap_bin_last_i ? ST_IDLE : ST_DROP;
                                expected_bin_q <= '0;
                            end
                        end

                        ST_SEND: begin
                            if (!dropping_busy_frame_q) begin
                                drop_pulse_q <= 1'b1;
                            end
                            dropping_busy_frame_q <= !tap_bin_last_i;
                        end

                        ST_DROP: begin
                            if (tap_bin_last_i) begin
                                state_q <= ST_IDLE;
                                expected_bin_q <= '0;
                                dropping_busy_frame_q <= 1'b0;
                            end
                        end

                        default: begin
                            state_q <= ST_IDLE;
                            expected_bin_q <= '0;
                        end
                    endcase
                end else if ((state_q != ST_SEND) && dropping_busy_frame_q) begin
                    state_q <= ST_DROP;
                end
            end
        end
    end

    assign drop_pulse_o = drop_pulse_q;

`ifndef SYNTHESIS
    initial begin
        if (PAYLOAD_DATA_W < 8) begin
            $fatal(1, "trecap_spec_packetizer: PAYLOAD_DATA_W must be at least 8");
        end
        if ((PAYLOAD_DATA_W % 8) != 0) begin
            $fatal(1, "trecap_spec_packetizer: PAYLOAD_DATA_W must be byte-aligned");
        end
        if (PAYLOAD_KEEP_W != (PAYLOAD_DATA_W / 8)) begin
            $fatal(1, "trecap_spec_packetizer: PAYLOAD_KEEP_W must equal PAYLOAD_DATA_W/8");
        end
        if (UNIQUE_BINS != 129) begin
            $warning("trecap_spec_packetizer: Revision G SPEC layouts assume L=256 and unique bins=129");
        end
        if (SPEC129_MASK_BYTES != 17) begin
            $warning("trecap_spec_packetizer: Revision G SPEC129 mask byte count is expected to be 17");
        end
    end

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            // No simulation state.
        end else begin
            if (out_valid_o && !trecap_payload_bytes_valid(out_meta_o.packet_type, int'(out_meta_o.payload_bytes))) begin
                $error("trecap_spec_packetizer: illegal SPEC payload size %0d for type %0h",
                       out_meta_o.payload_bytes,
                       out_meta_o.packet_type);
            end
            if (out_valid_o && (out_meta_o.timestamp != frame_idx_q)) begin
                $error("trecap_spec_packetizer: SPEC timestamp must equal frame_idx");
            end
            if (out_valid_o && ((out_meta_o.flags & TPKT_FLAG_RESERVED_15_6_MASK) != 16'h0000)) begin
                $error("trecap_spec_packetizer: reserved flag bits are set");
            end
            if (out_valid_o && ((out_meta_o.flags & TPKT_FLAG_PAYLOAD_SCALED_MASK) == 16'h0000)) begin
                $error("trecap_spec_packetizer: SPEC payloads must set payload_scaled");
            end
            if (out_valid_o && (mode_q == TSPEC_SPEC129) && (nbin_comb != 16'(UNIQUE_BINS))) begin
                $error("trecap_spec_packetizer: SPEC129 nbin mismatch");
            end
            if (out_valid_o && (mode_q == TSPEC_SPEC64) && (nbin_comb != 16'(SPEC64_BUCKETS))) begin
                $error("trecap_spec_packetizer: SPEC64 nbin mismatch");
            end
        end
    end
`endif

endmodule : trecap_spec_packetizer

`default_nettype wire
