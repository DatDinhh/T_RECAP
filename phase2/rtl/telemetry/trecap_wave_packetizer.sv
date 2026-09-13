// SPDX-License-Identifier: MIT
// File class: [1] hand-written RTL.
// Layer: rtl/telemetry/
// Owner: T-RECAP Phase 2 implementation.
// Purpose: Non-stalling Revision G WAVE telemetry payload packetizer.
// Contract: Build exact little-endian WAVE payload beats from valid-only core sample taps;
//           do not drive ready into the core; do not write DDR; do not allocate sequence IDs.
// Generated dependencies: trecap_core_pkg, trecap_packet_pkg, trecap_iface_pkg,
//                         trecap_build_pkg.

`default_nettype none

// T-RECAP WAVE packetizer.
//
// This module observes the core sample tap and emits WAVE payload bytes toward the telemetry
// scheduler/FIFO boundary. The downstream HPS bridge owns the common 32-byte telemetry header,
// sequence number allocation, 64-byte DDR alignment padding, WRAP records, and DDR writes.
//
// Payload layout, little endian, packed with no padding:
//   byte  0: uint64 sample_base, equal to packet timestamp
//   byte  8: uint16 nsamp
//   byte 10: uint16 channels = 3
//   byte 12: uint16 stride, equal to active WAVE_DECIM latched with sample_base
//   byte 14: uint16 reserved = 0
//   byte 16 + 6*i: int16 xdel, int16 yout, int16 err
//
// The input tap is valid-only. This module never returns a ready signal to the STFT/WOLA core.
// If the packetizer is busy when a selected WAVE sample arrives, the sample is dropped and
// drop_pulse_o reports that pre-writer telemetry loss.
module trecap_wave_packetizer
  import trecap_core_pkg::*;
  import trecap_packet_pkg::*;
  import trecap_iface_pkg::*;
  import trecap_build_pkg::*;
#(
    parameter int unsigned PAYLOAD_DATA_W           = 32,
    parameter int unsigned PAYLOAD_KEEP_W           = (PAYLOAD_DATA_W + 7) / 8,
    parameter int unsigned WAVE_NSAMP_TARGET        = 128,
    parameter bit          DROP_PARTIAL_ON_DISABLE  = 1'b1
) (
    input  logic                       clk,
    input  logic                       rst_n,
    // Synchronous formatter clear in clk domain. This discards any partial or in-flight WAVE
    // record without creating a second reset tree.
    input  logic                       formatter_reset_i,

    input  logic                       enable_i,
    input  logic [15:0]                wave_decim_i,
    input  trecap_core_tap_sample_t    tap_sample_i,

    output logic                       out_valid_o,
    input  logic                       out_ready_i,
    output trecap_record_meta_t        out_meta_o,
    output logic [PAYLOAD_DATA_W-1:0]  out_payload_data_o,
    output logic [PAYLOAD_KEEP_W-1:0]  out_payload_keep_o,
    output logic                       out_payload_last_o,

    output logic                       drop_pulse_o
);

    localparam int unsigned BYTES_PER_BEAT = PAYLOAD_KEEP_W;
    localparam int unsigned WAVE_TRIPLET_BYTES = 6;
    localparam int unsigned WAVE_HEADER_BYTES = TPKT_WAVE_SAMPLE_OFFSET;
    localparam int unsigned NSAMP_MAX = TPKT_PAYLOAD_WAVE_NSAMP_MAX;
    localparam int unsigned NSAMP_TARGET_CLAMP =
        (WAVE_NSAMP_TARGET < TPKT_PAYLOAD_WAVE_NSAMP_MIN) ? TPKT_PAYLOAD_WAVE_NSAMP_MIN :
        ((WAVE_NSAMP_TARGET > TPKT_PAYLOAD_WAVE_NSAMP_MAX) ? TPKT_PAYLOAD_WAVE_NSAMP_MAX :
                                                               WAVE_NSAMP_TARGET);
    localparam int unsigned NSAMP_W = (NSAMP_MAX <= 1) ? 1 : $clog2(NSAMP_MAX + 1);
    localparam int unsigned PAYLOAD_OFF_W =
        (TPKT_PAYLOAD_WAVE_MAX_BYTES <= 1) ? 1 : $clog2(TPKT_PAYLOAD_WAVE_MAX_BYTES + 1);

    typedef enum logic [0:0] {
        ST_COLLECT = 1'b0,
        ST_SEND    = 1'b1
    } wave_state_e;

    wave_state_e state_q;

    logic [63:0]              sample_base_q;
    logic [15:0]              stride_q;
    logic [15:0]              decim_count_q;
    logic [NSAMP_W-1:0]       nsamp_q;
    logic [PAYLOAD_OFF_W-1:0] byte_offset_q;

    logic signed [15:0] xdel_buf [0:NSAMP_MAX-1];
    logic signed [15:0] yout_buf [0:NSAMP_MAX-1];
    logic signed [15:0] err_buf  [0:NSAMP_MAX-1];

    logic [15:0]             decim_eff;
    logic [15:0]             decim_active;
    logic                    sample_selected;
    logic                    can_store_selected;
    logic                    accepting_output_beat;
    logic                    output_last_beat;
    logic [PAYLOAD_OFF_W:0]  payload_bytes_comb;
    logic [PAYLOAD_OFF_W:0]  next_byte_offset;
    logic                    start_send_after_store;
    logic                    drop_pulse_q;

    assign decim_eff = (wave_decim_i == 16'd0) ? 16'd1 : wave_decim_i;
    // A WAVE record represents a uniform time axis. Latch stride on its first selected sample and
    // keep using that value until the record is completed or a partial collection is discarded.
    assign decim_active = (nsamp_q != '0) ? stride_q : decim_eff;
    assign sample_selected = enable_i && tap_sample_i.valid && (decim_count_q == 16'd0);
    assign can_store_selected = (state_q == ST_COLLECT) && (nsamp_q < NSAMP_W'(NSAMP_TARGET_CLAMP));

    function automatic logic signed [15:0] sext_sample16(
        input logic signed [T_SAMPLE_W-1:0] value
    );
        return {{(16-T_SAMPLE_W){value[T_SAMPLE_W-1]}}, value};
    endfunction : sext_sample16

    function automatic logic [7:0] get_u16_byte(
        input logic [15:0] value,
        input int unsigned byte_idx
    );
        return byte_idx[0] ? value[15:8] : value[7:0];
    endfunction : get_u16_byte

    function automatic logic [7:0] get_i16_byte(
        input logic signed [15:0] value,
        input int unsigned byte_idx
    );
        return byte_idx[0] ? value[15:8] : value[7:0];
    endfunction : get_i16_byte

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

    function automatic logic [7:0] payload_byte_at(input int unsigned off);
        int unsigned sample_i;
        int unsigned field_off;
        logic [15:0] nsamp_u16;

        nsamp_u16 = 16'(nsamp_q);

        if (off < TPKT_WAVE_NSAMP_OFFSET) begin
            return get_u64_byte(sample_base_q, off - TPKT_WAVE_SAMPLE_BASE_OFFSET);
        end
        if (off < TPKT_WAVE_CHANNELS_OFFSET) begin
            return get_u16_byte(nsamp_u16, off - TPKT_WAVE_NSAMP_OFFSET);
        end
        if (off < TPKT_WAVE_STRIDE_OFFSET) begin
            return get_u16_byte(16'd3, off - TPKT_WAVE_CHANNELS_OFFSET);
        end
        if (off < TPKT_WAVE_RESERVED_OFFSET) begin
            return get_u16_byte(stride_q, off - TPKT_WAVE_STRIDE_OFFSET);
        end
        if (off < TPKT_WAVE_SAMPLE_OFFSET) begin
            return 8'h00;
        end

        sample_i = (off - WAVE_HEADER_BYTES) / WAVE_TRIPLET_BYTES;
        field_off = (off - WAVE_HEADER_BYTES) % WAVE_TRIPLET_BYTES;

        if (sample_i >= NSAMP_MAX) begin
            return 8'h00;
        end

        unique case (field_off)
            0: return get_i16_byte(xdel_buf[sample_i], 0);
            1: return get_i16_byte(xdel_buf[sample_i], 1);
            2: return get_i16_byte(yout_buf[sample_i], 0);
            3: return get_i16_byte(yout_buf[sample_i], 1);
            4: return get_i16_byte(err_buf[sample_i], 0);
            default: return get_i16_byte(err_buf[sample_i], 1);
        endcase
    endfunction : payload_byte_at

    always_comb begin
        payload_bytes_comb = PAYLOAD_OFF_W'(trecap_wave_payload_bytes(int'(nsamp_q)));
        next_byte_offset = byte_offset_q + PAYLOAD_OFF_W'(BYTES_PER_BEAT);
        accepting_output_beat = out_valid_o && out_ready_i;
        output_last_beat = out_valid_o && (next_byte_offset >= payload_bytes_comb);
        start_send_after_store = sample_selected && can_store_selected &&
                                 ((nsamp_q + NSAMP_W'(1)) >= NSAMP_W'(NSAMP_TARGET_CLAMP));
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
        out_meta_o.packet_type = TPKT_WAVE;
        out_meta_o.flags = 16'h0000;
        out_meta_o.seq = 32'd0;
        out_meta_o.timestamp = sample_base_q;
        out_meta_o.payload_bytes = 16'(payload_bytes_comb);
        out_meta_o.drop_priority = TPKT_PRIORITY_WAVE;
    end

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state_q <= ST_COLLECT;
            sample_base_q <= 64'd0;
            stride_q <= 16'd1;
            decim_count_q <= 16'd0;
            nsamp_q <= '0;
            byte_offset_q <= '0;
            drop_pulse_q <= 1'b0;
        end else if (formatter_reset_i) begin
            state_q <= ST_COLLECT;
            sample_base_q <= 64'd0;
            stride_q <= 16'd1;
            decim_count_q <= 16'd0;
            nsamp_q <= '0;
            byte_offset_q <= '0;
            drop_pulse_q <= 1'b0;
        end else begin
            drop_pulse_q <= 1'b0;

            // Never retract valid in the middle of a record. Runtime disable/config changes may
            // discard a not-yet-emitted partial collection, but ST_SEND must drain atomically so a
            // downstream FIFO cannot be left forever waiting for the missing final beat.
            if (!enable_i && (state_q != ST_SEND)) begin
                decim_count_q <= 16'd0;
                byte_offset_q <= '0;
                if (DROP_PARTIAL_ON_DISABLE && ((state_q == ST_SEND) || (nsamp_q != '0))) begin
                    drop_pulse_q <= 1'b1;
                end
                state_q <= ST_COLLECT;
                nsamp_q <= '0;
            end else begin
                if (accepting_output_beat) begin
                    if (output_last_beat) begin
                        state_q <= ST_COLLECT;
                        byte_offset_q <= '0;
                        nsamp_q <= '0;
                    end else begin
                        byte_offset_q <= PAYLOAD_OFF_W'(next_byte_offset);
                    end
                end

                if (enable_i && tap_sample_i.valid) begin
                    if (decim_count_q == 16'd0) begin
                        decim_count_q <= decim_active - 16'd1;
                    end else begin
                        decim_count_q <= decim_count_q - 16'd1;
                    end
                end

                if (sample_selected) begin
                    if (can_store_selected) begin
                        if (nsamp_q == '0) begin
                            sample_base_q <= tap_sample_i.sample_idx;
                            stride_q <= decim_active;
                        end

                        xdel_buf[int'(nsamp_q)] <= sext_sample16(tap_sample_i.x_delayed);
                        yout_buf[int'(nsamp_q)] <= sext_sample16(tap_sample_i.y_out);
                        err_buf[int'(nsamp_q)] <= tap_sample_i.error_i16;
                        nsamp_q <= nsamp_q + NSAMP_W'(1);

                        if (start_send_after_store) begin
                            state_q <= ST_SEND;
                            byte_offset_q <= '0;
                        end
                    end else begin
                        drop_pulse_q <= 1'b1;
                    end
                end
            end
        end
    end

    assign drop_pulse_o = drop_pulse_q;

`ifndef SYNTHESIS
    initial begin
        if (PAYLOAD_DATA_W < 8) begin
            $fatal(1, "trecap_wave_packetizer: PAYLOAD_DATA_W must be at least 8");
        end
        if ((PAYLOAD_DATA_W % 8) != 0) begin
            $fatal(1, "trecap_wave_packetizer: PAYLOAD_DATA_W must be byte-aligned");
        end
        if (PAYLOAD_KEEP_W != (PAYLOAD_DATA_W / 8)) begin
            $fatal(1, "trecap_wave_packetizer: PAYLOAD_KEEP_W must equal PAYLOAD_DATA_W/8");
        end
        if (T_SAMPLE_W > 15) begin
            $warning("trecap_wave_packetizer: Revision G WAVE i16 fields are intended for N<=15");
        end
    end

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            // No simulation state.
        end else begin
            if (out_valid_o && !trecap_wave_payload_bytes_valid(int'(out_meta_o.payload_bytes))) begin
                $error("trecap_wave_packetizer: illegal WAVE payload size %0d", out_meta_o.payload_bytes);
            end
            if (out_valid_o && (out_meta_o.timestamp != sample_base_q)) begin
                $error("trecap_wave_packetizer: WAVE timestamp must equal sample_base");
            end
            if (out_valid_o && (out_meta_o.flags != 16'h0000)) begin
                $error("trecap_wave_packetizer: WAVE flags must be zero in Revision G baseline");
            end
        end
    end
`endif

endmodule : trecap_wave_packetizer

`default_nettype wire
