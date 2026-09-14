// SPDX-License-Identifier: MIT
// File class: [1] hand-written RTL.
// Layer: rtl/telemetry/
// Owner: T-RECAP Phase 2 implementation.
// Purpose: Build Revision G FPGA-originated STATUS skeleton records.
// Contract: Non-stalling packetizer. HPS may patch only the outgoing UDP copy.
// Generated dependencies: trecap_core_pkg, trecap_csr_pkg, trecap_packet_pkg,
//                         trecap_iface_pkg.

`default_nettype none

// Revision G STATUS packetizer.
//
// This block emits FPGA-originated STATUS skeleton records. HPS-owned fields that cannot be known
// in FPGA fabric are emitted as zero and may be patched by HPS in the local UDP transmit copy only.
// The committed DDR record is not modified by the HPS. This block does not synthesize diagnostic
// STATUS responses; diagnostic STATUS packets are an HPS software responsibility.
//
// Core-counter rule:
//   sample/frame counts are authoritative coherent counters supplied by the composition layer,
//   not reconstructed from delayed output taps. If another STATUS tick arrives while a previous
//   STATUS record is still being emitted, the new event is dropped through drop_pulse_o.
//
// Payload layout, little-endian, no implicit padding:
//   0   uint64 sample_count
//   8   uint64 frame_count
//   16  uint32 source_mode
//   20  uint32 sample_rate
//   24  uint32 packet_enable
//   28  uint32 dma_drop_count
//   32  uint32 udp_send_error_count       // HPS-owned, zero in FPGA skeleton
//   36  uint32 malformed_record_count     // HPS-owned, zero in FPGA skeleton
//   40  uint32 oversized_record_count     // HPS-owned, zero in FPGA skeleton
//   44  uint32 command_reject_count        // CSR-owned low word; HPS may patch combined count
//   48  uint32 sequence_gap_count          // HPS-owned, zero in FPGA skeleton
//   52  uint32 overflow_flags
//   56  uint32 thr2_lo
//   60  uint32 thr2_hi
//   64  uint32 packet_fifo_drop_count
//   68  uint32 reserved
module trecap_status_packetizer
#(
    parameter int unsigned PAYLOAD_DATA_W = 32,
    parameter int unsigned PAYLOAD_KEEP_W = (PAYLOAD_DATA_W + 7) / 8
) (
    input  logic                       clk,
    input  logic                       rst_n,
    // Synchronous formatter clear in clk domain; does not create or fan out an asynchronous reset.
    input  logic                       formatter_reset_i,

    input  logic                       enable_i,
    input  logic                       status_tick_i,
    input  trecap_iface_pkg::trecap_hps_bridge_ctrl_t    ctrl_i,
    input  logic [63:0]                core_sample_count_i,
    input  logic [63:0]                core_frame_count_i,
    input  logic [31:0]                sample_rate_hz_i,
    input  logic [31:0]                overflow_flags_i,
    input  logic [31:0]                dma_drop_count_i,
    input  logic [31:0]                dma_packet_count_i,
    input  logic [31:0]                packet_fifo_drop_count_i,
    input  logic [31:0]                csr_command_reject_count_i,

    output logic                       out_valid_o,
    input  logic                       out_ready_i,
    output trecap_iface_pkg::trecap_record_meta_t        out_meta_o,
    output logic [PAYLOAD_DATA_W-1:0]  out_payload_data_o,
    output logic [PAYLOAD_KEEP_W-1:0]  out_payload_keep_o,
    output logic                       out_payload_last_o,

    output logic                       drop_pulse_o
);
  import trecap_core_pkg::*;
  import trecap_csr_pkg::*;
  import trecap_packet_pkg::*;
  import trecap_iface_pkg::*;


    localparam int unsigned PAYLOAD_BYTE_W = PAYLOAD_KEEP_W;
    localparam int unsigned STATUS_BYTES   = TPKT_PAYLOAD_STATUS_BYTES;

    typedef enum logic [0:0] {
        ST_IDLE = 1'b0,
        ST_EMIT = 1'b1
    } status_state_e;

    status_state_e state_q;
    trecap_record_meta_t meta_q;
    logic [7:0] payload_mem [0:STATUS_BYTES-1];

    int unsigned emit_offset_q;
    logic drop_pulse_q;

    logic emit_accept;
    logic emit_last;
    int unsigned emit_remaining;

    assign emit_accept = out_valid_o && out_ready_i;
    assign emit_last = (emit_offset_q + PAYLOAD_BYTE_W) >= int'(meta_q.payload_bytes);
    assign emit_remaining = (int'(meta_q.payload_bytes) > emit_offset_q) ?
                            (int'(meta_q.payload_bytes) - emit_offset_q) : 0;

    function automatic logic [PAYLOAD_KEEP_W-1:0] keep_for_remaining(
        input int unsigned remaining_bytes
    );
        logic [PAYLOAD_KEEP_W-1:0] keep;
        begin
            keep = '0;
            for (int unsigned byte_idx = 0; byte_idx < PAYLOAD_KEEP_W; byte_idx++) begin
                keep[byte_idx] = (byte_idx < remaining_bytes);
            end
            return keep;
        end
    endfunction : keep_for_remaining

    task automatic write_u32(input int unsigned off, input logic [31:0] value);
        begin
            payload_mem[off + 0] <= value[7:0];
            payload_mem[off + 1] <= value[15:8];
            payload_mem[off + 2] <= value[23:16];
            payload_mem[off + 3] <= value[31:24];
        end
    endtask : write_u32

    task automatic write_u64(input int unsigned off, input logic [63:0] value);
        begin
            payload_mem[off + 0] <= value[7:0];
            payload_mem[off + 1] <= value[15:8];
            payload_mem[off + 2] <= value[23:16];
            payload_mem[off + 3] <= value[31:24];
            payload_mem[off + 4] <= value[39:32];
            payload_mem[off + 5] <= value[47:40];
            payload_mem[off + 6] <= value[55:48];
            payload_mem[off + 7] <= value[63:56];
        end
    endtask : write_u64

    task automatic write_status_payload(
        input logic [63:0] sample_count,
        input logic [63:0] frame_count
    );
        begin
            write_u64(TPKT_STATUS_SAMPLE_COUNT_OFFSET, sample_count);
            write_u64(TPKT_STATUS_FRAME_COUNT_OFFSET, frame_count);
            write_u32(TPKT_STATUS_SOURCE_MODE_OFFSET, {30'd0, ctrl_i.source_mode});
            write_u32(TPKT_STATUS_SAMPLE_RATE_OFFSET, sample_rate_hz_i);
            write_u32(TPKT_STATUS_PACKET_ENABLE_OFFSET, ctrl_i.packet_enable);
            write_u32(TPKT_STATUS_DMA_DROP_COUNT_OFFSET, dma_drop_count_i);
            write_u32(TPKT_STATUS_UDP_SEND_ERROR_COUNT_OFFSET, 32'd0);
            write_u32(TPKT_STATUS_MALFORMED_RECORD_COUNT_OFFSET, 32'd0);
            write_u32(TPKT_STATUS_OVERSIZED_RECORD_COUNT_OFFSET, 32'd0);
            write_u32(TPKT_STATUS_COMMAND_REJECT_COUNT_OFFSET, csr_command_reject_count_i);
            write_u32(TPKT_STATUS_SEQUENCE_GAP_COUNT_OFFSET, 32'd0);
            write_u32(TPKT_STATUS_OVERFLOW_FLAGS_OFFSET, overflow_flags_i);
            write_u32(TPKT_STATUS_THR2_LO_OFFSET, ctrl_i.thr2_active[31:0]);
            write_u32(TPKT_STATUS_THR2_HI_OFFSET, {8'd0, ctrl_i.thr2_active[55:32]});
            write_u32(TPKT_STATUS_PACKET_FIFO_DROP_COUNT_OFFSET, packet_fifo_drop_count_i);
            write_u32(TPKT_STATUS_RESERVED_OFFSET, 32'd0);
        end
    endtask : write_status_payload

    function automatic trecap_record_meta_t make_meta(input logic [63:0] sample_count);
        trecap_record_meta_t meta;
        begin
            meta = '0;
            meta.valid = 1'b1;
            meta.packet_type = TPKT_STATUS;
            meta.flags = 16'h0000;
            meta.seq = 32'h0000_0000;
            meta.timestamp = sample_count;
            meta.payload_bytes = STATUS_BYTES;
            meta.drop_priority = TPKT_PRIORITY_STATUS;
            return meta;
        end
    endfunction : make_meta

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state_q <= ST_IDLE;
            meta_q <= '0;
            emit_offset_q <= 0;
            drop_pulse_q <= 1'b0;
        end else if (formatter_reset_i) begin
            state_q <= ST_IDLE;
            meta_q <= '0;
            emit_offset_q <= 0;
            drop_pulse_q <= 1'b0;
        end else begin
            drop_pulse_q <= 1'b0;
            unique case (state_q)
                ST_IDLE: begin
                    emit_offset_q <= 0;
                    if (status_tick_i && enable_i) begin
                        write_status_payload(core_sample_count_i, core_frame_count_i);
                        meta_q <= make_meta(core_sample_count_i);
                        state_q <= ST_EMIT;
                    end
                end
                ST_EMIT: begin
                    if (status_tick_i && enable_i) begin
                        drop_pulse_q <= 1'b1;
                    end
                    if (emit_accept) begin
                        if (emit_last) begin
                            state_q <= ST_IDLE;
                            emit_offset_q <= 0;
                        end else begin
                            emit_offset_q <= emit_offset_q + PAYLOAD_BYTE_W;
                        end
                    end
                end
                default: begin
                    state_q <= ST_IDLE;
                    emit_offset_q <= 0;
                end
            endcase
        end
    end

    always_comb begin
        out_valid_o = !formatter_reset_i && (state_q == ST_EMIT);
        // Inactive fields are don't-care; consumers transact only when valid.
        // Keep valid/flush gating out of downstream payload-size arithmetic.
        out_meta_o = meta_q;
        out_meta_o.valid = out_valid_o && meta_q.valid;
        out_payload_data_o = '0;
        out_payload_keep_o = '0;
        out_payload_last_o = 1'b0;
        if (!formatter_reset_i && (state_q == ST_EMIT)) begin
            for (int unsigned byte_idx = 0; byte_idx < PAYLOAD_BYTE_W; byte_idx++) begin
                if ((emit_offset_q + byte_idx) < int'(meta_q.payload_bytes)) begin
                    out_payload_data_o[8*byte_idx +: 8] = payload_mem[emit_offset_q + byte_idx];
                end
            end
            out_payload_keep_o = keep_for_remaining(emit_remaining);
            out_payload_last_o = emit_last;
        end
    end

    assign drop_pulse_o = drop_pulse_q;

    wire unused_ctrl_fields = ctrl_i.ring_writer_enable ^ ctrl_i.clear_metrics_w1p ^
                              ctrl_i.wave_decim[0] ^ ctrl_i.spec_mode[0] ^
                              ctrl_i.spec_shift[0];
    wire unused_dma_packet_count = dma_packet_count_i[0];
    wire unused_silence = unused_ctrl_fields ^ unused_dma_packet_count;

`ifndef SYNTHESIS
    initial begin
        if (PAYLOAD_DATA_W < 8) begin
            $fatal(1, "trecap_status_packetizer: PAYLOAD_DATA_W must be at least 8");
        end
        if ((PAYLOAD_DATA_W % 8) != 0) begin
            $fatal(1, "trecap_status_packetizer: PAYLOAD_DATA_W must be byte-aligned");
        end
        if (PAYLOAD_KEEP_W != ((PAYLOAD_DATA_W + 7) / 8)) begin
            $fatal(1, "trecap_status_packetizer: PAYLOAD_KEEP_W does not match PAYLOAD_DATA_W");
        end
        if (TPKT_PAYLOAD_STATUS_BYTES != (TPKT_STATUS_RESERVED_OFFSET + 4)) begin
            $fatal(1, "trecap_status_packetizer: STATUS payload-size constant mismatch");
        end
    end
`endif

endmodule : trecap_status_packetizer

`default_nettype wire
