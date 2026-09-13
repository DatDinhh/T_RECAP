// SPDX-License-Identifier: MIT
// File class: [1] hand-written RTL interface.
// Layer: rtl/interfaces/
// Owner: T-RECAP Phase 2 implementation.
// Purpose: Ready/valid formatted-record payload stream between telemetry and HPS bridge layers.
// Contract: Carry record metadata and payload beats without owning DDR ring pointers, WRAP
//           insertion policy, HPS software, UDP sockets, or signal-processing behavior.

`default_nettype none

// T-RECAP record interface.
//
// This interface models the flattened record_* ports used between rtl/telemetry/ and
// rtl/hps_bridge/. The payload stream does not include the common 32-byte transport header and
// does not include 64-byte DDR padding; those are built by rtl/hps_bridge/trecap_ddr_record_builder.
//
// Stream policy:
//   - valid/ready is per payload beat.
//   - meta is stable for every beat of one record.
//   - payload_last marks the final payload beat.
//   - payload_keep is byte-enable style and must be nonzero on valid beats.
//   - non-final beats must use a full keep mask; only the final beat may be partial.
//
// This interface is not a CDC primitive. If the record stream crosses clock domains, use an
// async FIFO or a documented packet/record CDC wrapper above this interface.
interface trecap_record_if #(
    parameter int unsigned DATA_W = 32,
    parameter int unsigned KEEP_W = (DATA_W + 7) / 8
) (
    input logic clk,
    input logic rst_n
);

    import trecap_packet_pkg::*;
    import trecap_iface_pkg::*;

    logic                    valid;
    logic                    ready;
    trecap_record_meta_t     meta;
    logic [DATA_W-1:0]       payload_data;
    logic [KEEP_W-1:0]       payload_keep;
    logic                    payload_last;

    wire beat_accept = valid && ready;
    wire record_last_accept = beat_accept && payload_last;
    wire stalled = valid && !ready;
    wire [KEEP_W-1:0] full_keep = {KEEP_W{1'b1}};

    modport source (
        input  clk,
        input  rst_n,
        output valid,
        input  ready,
        output meta,
        output payload_data,
        output payload_keep,
        output payload_last,
        input  beat_accept,
        input  record_last_accept,
        input  stalled
    );

    modport sink (
        input  clk,
        input  rst_n,
        input  valid,
        output ready,
        input  meta,
        input  payload_data,
        input  payload_keep,
        input  payload_last,
        input  beat_accept,
        input  record_last_accept,
        input  stalled
    );

    modport monitor (
        input clk,
        input rst_n,
        input valid,
        input ready,
        input meta,
        input payload_data,
        input payload_keep,
        input payload_last,
        input beat_accept,
        input record_last_accept,
        input stalled
    );

`ifndef SYNTHESIS
    initial begin
        if (DATA_W == 0) begin
            $error("trecap_record_if: DATA_W must be nonzero");
        end
        if ((DATA_W % 8) != 0) begin
            $error("trecap_record_if: DATA_W must be byte-addressable");
        end
        if (KEEP_W != ((DATA_W + 7) / 8)) begin
            $error("trecap_record_if: KEEP_W must match DATA_W/8 baseline");
        end
    end

    function automatic logic keep_low_contiguous(input logic [KEEP_W-1:0] keep);
        logic seen_zero;
        keep_low_contiguous = 1'b1;
        seen_zero = 1'b0;
        for (int unsigned i = 0; i < KEEP_W; i++) begin
            if (!keep[i]) begin
                seen_zero = 1'b1;
            end else if (seen_zero) begin
                keep_low_contiguous = 1'b0;
            end
        end
    endfunction : keep_low_contiguous

    logic                    hold_active_q;
    trecap_record_meta_t     hold_meta_q;
    logic [DATA_W-1:0]       hold_payload_data_q;
    logic [KEEP_W-1:0]       hold_payload_keep_q;
    logic                    hold_payload_last_q;

    logic                    record_active_q;
    trecap_record_meta_t     record_meta_q;

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            hold_active_q <= 1'b0;
            hold_meta_q <= '0;
            hold_payload_data_q <= '0;
            hold_payload_keep_q <= '0;
            hold_payload_last_q <= 1'b0;
            record_active_q <= 1'b0;
            record_meta_q <= '0;
        end else begin
            if (valid && !ready && !hold_active_q) begin
                hold_active_q <= 1'b1;
                hold_meta_q <= meta;
                hold_payload_data_q <= payload_data;
                hold_payload_keep_q <= payload_keep;
                hold_payload_last_q <= payload_last;
            end else if (!valid || ready) begin
                hold_active_q <= 1'b0;
            end

            if (hold_active_q && valid && !ready) begin
                if (meta !== hold_meta_q) begin
                    $error("trecap_record_if: meta changed while stalled");
                end
                if (payload_data !== hold_payload_data_q) begin
                    $error("trecap_record_if: payload_data changed while stalled");
                end
                if (payload_keep !== hold_payload_keep_q) begin
                    $error("trecap_record_if: payload_keep changed while stalled");
                end
                if (payload_last !== hold_payload_last_q) begin
                    $error("trecap_record_if: payload_last changed while stalled");
                end
            end

            if (valid) begin
                if (!meta.valid) begin
                    $error("trecap_record_if: valid beat presented with meta.valid deasserted");
                end
                if (payload_keep == '0) begin
                    $error("trecap_record_if: valid beat has zero payload_keep");
                end
                if (!keep_low_contiguous(payload_keep)) begin
                    $error("trecap_record_if: payload_keep is not low-contiguous");
                end
                if (!payload_last && (payload_keep != full_keep)) begin
                    $error("trecap_record_if: non-final payload beat must have full keep");
                end
                if (meta.payload_bytes > (TPKT_UDP_MAX_BYTES - TPKT_HEADER_BYTES)) begin
                    $error("trecap_record_if: payload_bytes exceeds UDP single-record limit");
                end
            end

            if (beat_accept && !record_active_q) begin
                record_active_q <= !payload_last;
                record_meta_q <= meta;
            end else if (beat_accept && record_active_q && payload_last) begin
                record_active_q <= 1'b0;
                record_meta_q <= '0;
            end

            if (record_active_q && valid && (meta !== record_meta_q)) begin
                $error("trecap_record_if: metadata changed before record payload_last");
            end
            if (record_active_q && beat_accept && !valid) begin
                $error("trecap_record_if: internal impossible state: accepted inactive beat");
            end
        end
    end
`endif

endinterface : trecap_record_if

`default_nettype wire
