// SPDX-License-Identifier: MIT
// File class: [1] hand-written RTL.
// Layer: rtl/hps_bridge/
// Owner: T-RECAP Phase 2 implementation.
// Purpose: DDR ring producer/consumer pointer control and free-space scheduling helper.
// Contract: Own absolute 64-bit W/Rd state, coherent producer snapshots, consumer commit
//           acceptance, wrap-space accounting helpers, and normal-record sequence allocation.
// Generated dependencies: trecap_csr_pkg, trecap_packet_pkg, trecap_iface_pkg.

`default_nettype none

// T-RECAP DDR ring pointer controller.
//
// This module centralizes ring pointer arithmetic for the HPS bridge layer. It does not write DDR,
// build packet headers, parse payloads, or know anything about Ethernet. The DDR writer uses the
// schedule outputs to decide whether a normal record fits directly, requires a WRAP control record,
// or must be dropped for lack of space. The CSR bank or HPS bridge top uses the snapshot/commit
// ports to prevent torn 64-bit pointer transfers.
//
// Absolute-pointer contract:
//   W  = producer pointer owned by FPGA writer / this block.
//   Rd = consumer pointer committed by HPS through CSR shadow/commit.
//   used = W - Rd, valid only when 0 <= used <= ring_size.
//   off(p) = p & (ring_size - 1), because ring_size is power-of-two.
//
// Sequence contract:
//   seq_o is the sequence number to place in the next normal telemetry header. WRAP records do not
//   consume a sequence number. A sequence number advances only when a normal record commit is
//   reported through producer_advance_valid_i with producer_advance_is_normal_i asserted.
module trecap_ring_pointer_ctrl
  import trecap_csr_pkg::*;
  import trecap_packet_pkg::*;
  import trecap_iface_pkg::*;
  import trecap_build_pkg::*;
#(
    parameter int unsigned GUARD_BYTES = TCSR_RING_GUARD_BYTES_MIN,
    parameter logic [31:0] RING_SIZE_MIN_BYTES = 32'h0010_0000
) (
    input  logic                clk,
    input  logic                rst_n,

    // Synchronous reset for the transport/ring epoch. FPGA-owned W/sequence/configuration reset;
    // the HPS-owned stored Rd value is retained but is hidden until an exact Rd=0 epoch commit.
    input  logic                soft_reset_i,

    // Ring configuration from the CSR bank. ring_config_commit_pulse_i is expected only while the
    // writer is disabled; this block still validates the fields defensively.
    input  trecap_ring_config_t ring_config_i,
    input  logic                ring_config_commit_pulse_i,

    // Control-state hints used for status checks only. Policy ownership stays in csr_bank/writer.
    input  logic                telemetry_enable_i,
    input  logic                ring_writer_enable_i,

    // Record-size scheduling query for the next normal telemetry record. scheduled_record_bytes_i
    // shall already be align64(32 + payload_bytes) and shall not include a WRAP tail. The outputs
    // are combinational and are valid whenever schedule_valid_i is asserted.
    input  logic                schedule_valid_i,
    input  logic [63:0]         scheduled_record_bytes_i,
    output logic                schedule_fits_o,
    output logic                schedule_needs_wrap_o,
    output logic [63:0]         schedule_offset_o,
    output logic [63:0]         schedule_tail_bytes_o,
    output logic [63:0]         schedule_required_bytes_o,
    output logic [63:0]         schedule_free_bytes_o,
    output logic [63:0]         schedule_normal_addr_o,
    output logic [63:0]         schedule_wrap_addr_o,

    // Producer-pointer commit from the DDR writer after all bytes for a WRAP or normal record have
    // completed. producer_advance_bytes_i is the effective committed length: Ttail for WRAP, Lrec
    // for normal telemetry records. Exactly one kind bit shall be asserted for each commit.
    input  logic                producer_advance_valid_i,
    input  logic                producer_advance_is_normal_i,
    input  logic                producer_advance_is_wrap_i,
    input  logic [63:0]         producer_advance_bytes_i,
    output logic                producer_advance_ready_o,
    output logic                producer_advance_accept_pulse_o,
    output logic                producer_advance_reject_pulse_o,

    // HPS-owned consumer pointer commit. In an eventual split-clock integration, synchronize the
    // commit pulse/value before they reach this module or instantiate this block in the writer clock
    // domain after CDC handoff.
    input  logic                ring_rd_commit_valid_i,
    input  logic [63:0]         ring_rd_commit_ptr_i,
    output logic                ring_rd_commit_ready_o,
    output logic                ring_rd_accept_pulse_o,
    output logic                ring_rd_reject_pulse_o,

    // Coherent producer snapshot helper. CSR bank may either use this snapshot output or latch the
    // live producer_ptr_o under its own RING_WR_SNAPSHOT transaction.
    input  logic                ring_wr_snapshot_req_i,
    output logic [63:0]         ring_wr_snapshot_o,
    output logic                ring_wr_snapshot_valid_o,
    output logic                ring_wr_snapshot_pulse_o,

    // Live pointer and ring-state observability.
    output logic [63:0]         producer_ptr_o,
    output logic [63:0]         consumer_ptr_o,
    output logic [31:0]         sequence_o,
    output logic [63:0]         used_bytes_o,
    output logic [63:0]         free_bytes_o,
    output logic [63:0]         current_offset_o,
    output logic [63:0]         current_tail_bytes_o,
    output logic                ring_configured_o,
    output logic                ring_full_o,
    output logic                no_space_o,
    output logic                pointers_valid_o,
    output logic                malformed_config_o,
    output logic                pointer_error_sticky_o
);

    trecap_ring_config_t config_q;
    logic [63:0]         producer_ptr_q;
    logic [63:0]         consumer_ptr_q;
    logic [31:0]         sequence_q;
    logic [63:0]         snapshot_q;
    logic                snapshot_valid_q;
    logic                pointer_error_q;
    logic                rd_epoch_valid_q;

    logic                config_legal;
    localparam logic [63:0] HEADER_BYTES_64 = TPKT_HEADER_BYTES;
    localparam logic [63:0] DDR_ALIGN_BYTES_64 = TPKT_DDR_ALIGN_BYTES;
    localparam logic [63:0] DDR_ALIGN_MASK_64 = (TPKT_DDR_ALIGN_BYTES - 1);

    logic [63:0]         ring_size_64;
    logic [63:0]         ring_mask_64;
    logic [63:0]         guard_64;
    logic [63:0]         used_bytes_comb;
    logic [63:0]         free_bytes_comb;
    logic                pointers_valid_comb;
    logic [63:0]         current_offset_comb;
    logic [63:0]         current_tail_comb;
    logic                scheduled_len_legal;
    logic                schedule_crosses_tail;
    logic [63:0]         schedule_required_comb;
    logic                schedule_fits_comb;
    logic                producer_advance_kind_legal;
    logic                producer_advance_normal_legal;
    logic                producer_advance_wrap_legal;
    logic                producer_advance_bytes_legal;
    logic                producer_advance_accept;
    logic                ring_rd_commit_legal;
    logic                ring_rd_accept;
    logic                commit_used_valid_after;
    logic [63:0]         producer_next_comb;

    function automatic bit power_of_two64(input logic [63:0] value);
        return (value != 64'd0) && ((value & (value - 64'd1)) == 64'd0);
    endfunction : power_of_two64

    function automatic bit aligned64(input logic [63:0] value);
        return ((value & DDR_ALIGN_MASK_64) == 64'd0);
    endfunction : aligned64

    function automatic logic [63:0] sub_sat64(input logic [63:0] a, input logic [63:0] b);
        return (a >= b) ? (a - b) : 64'd0;
    endfunction : sub_sat64

    function automatic bit ring_config_legal_fn(input trecap_ring_config_t cfg);
        logic [63:0] size_ext;

        size_ext = {32'd0, cfg.size_bytes};
        return cfg.configured &&
               (cfg.base_addr[5:0] == 6'd0) &&
               (cfg.size_bytes >= RING_SIZE_MIN_BYTES) &&
               ((cfg.size_bytes & (TCSR_RING_ALIGNMENT_BYTES - 1)) == 32'd0) &&
               power_of_two64(size_ext) &&
               (cfg.size_mask == (cfg.size_bytes - 32'd1));
    endfunction : ring_config_legal_fn

    assign config_legal = ring_config_legal_fn(config_q);
    assign ring_size_64 = {32'd0, config_q.size_bytes};
    assign ring_mask_64 = {32'd0, config_q.size_mask};
    assign guard_64 = GUARD_BYTES;

    assign used_bytes_comb = producer_ptr_q - consumer_ptr_q;
    assign pointers_valid_comb = config_legal &&
                                  rd_epoch_valid_q &&
                                  (producer_ptr_q >= consumer_ptr_q) &&
                                  (used_bytes_comb <= ring_size_64);
    assign free_bytes_comb = pointers_valid_comb ?
                             sub_sat64(ring_size_64 - used_bytes_comb, guard_64) :
                             64'd0;
    assign current_offset_comb = config_legal ? (producer_ptr_q & ring_mask_64) : 64'd0;
    assign current_tail_comb = config_legal ? (ring_size_64 - current_offset_comb) : 64'd0;

    assign scheduled_len_legal = schedule_valid_i &&
                                 config_legal &&
                                 (scheduled_record_bytes_i != 64'd0) &&
                                 (scheduled_record_bytes_i <= ring_size_64) &&
                                 aligned64(scheduled_record_bytes_i) &&
                                 (HEADER_BYTES_64 <= scheduled_record_bytes_i);
    assign schedule_crosses_tail = scheduled_len_legal &&
                                   ((current_offset_comb + scheduled_record_bytes_i) > ring_size_64);
    assign schedule_required_comb = !scheduled_len_legal ? 64'd0 :
                                    (schedule_crosses_tail ?
                                     (current_tail_comb + scheduled_record_bytes_i) :
                                     scheduled_record_bytes_i);
    assign schedule_fits_comb = scheduled_len_legal &&
                                pointers_valid_comb &&
                                (free_bytes_comb >= schedule_required_comb) &&
                                (!schedule_crosses_tail ||
                                 ((current_offset_comb != 64'd0) &&
                                  (current_tail_comb >= DDR_ALIGN_BYTES_64)));

    assign schedule_fits_o = schedule_fits_comb;
    assign schedule_needs_wrap_o = schedule_crosses_tail;
    assign schedule_offset_o = current_offset_comb;
    assign schedule_tail_bytes_o = current_tail_comb;
    assign schedule_required_bytes_o = schedule_required_comb;
    assign schedule_free_bytes_o = free_bytes_comb;
    assign schedule_normal_addr_o = config_q.base_addr + (schedule_crosses_tail ? 64'd0 : current_offset_comb);
    assign schedule_wrap_addr_o = config_q.base_addr + current_offset_comb;

    assign producer_advance_kind_legal = producer_advance_is_normal_i ^ producer_advance_is_wrap_i;
    assign producer_advance_normal_legal = producer_advance_is_normal_i &&
                                           (producer_advance_bytes_i >= HEADER_BYTES_64) &&
                                           aligned64(producer_advance_bytes_i) &&
                                           (producer_advance_bytes_i <= current_tail_comb);
    assign producer_advance_wrap_legal = producer_advance_is_wrap_i &&
                                         (current_offset_comb != 64'd0) &&
                                         (current_tail_comb >= DDR_ALIGN_BYTES_64) &&
                                         (producer_advance_bytes_i == current_tail_comb);
    assign producer_advance_bytes_legal = producer_advance_kind_legal &&
                                          (producer_advance_normal_legal ||
                                           producer_advance_wrap_legal);
    assign producer_next_comb = producer_ptr_q + producer_advance_bytes_i;
    assign commit_used_valid_after = pointers_valid_comb &&
                                     (producer_next_comb >= producer_ptr_q) &&
                                     (producer_next_comb >= consumer_ptr_q) &&
                                     ((producer_next_comb - consumer_ptr_q) <= ring_size_64);
    assign producer_advance_accept = producer_advance_valid_i &&
                                     producer_advance_bytes_legal &&
                                     commit_used_valid_after;
    assign producer_advance_ready_o = pointers_valid_comb;

    assign ring_rd_commit_legal = config_legal &&
                                  aligned64(ring_rd_commit_ptr_i) &&
                                  ((!rd_epoch_valid_q && (ring_rd_commit_ptr_i == 64'd0)) ||
                                   (rd_epoch_valid_q &&
                                    (ring_rd_commit_ptr_i >= consumer_ptr_q))) &&
                                  (ring_rd_commit_ptr_i <= producer_ptr_q) &&
                                  ((producer_ptr_q - ring_rd_commit_ptr_i) <= ring_size_64);
    assign ring_rd_accept = ring_rd_commit_valid_i && ring_rd_commit_legal;
    assign ring_rd_commit_ready_o = config_legal;

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            config_q <= '0;
            producer_ptr_q <= 64'd0;
            consumer_ptr_q <= 64'd0;
            sequence_q <= 32'd0;
            snapshot_q <= 64'd0;
            snapshot_valid_q <= 1'b0;
            pointer_error_q <= 1'b0;
            rd_epoch_valid_q <= 1'b0;
            producer_advance_accept_pulse_o <= 1'b0;
            producer_advance_reject_pulse_o <= 1'b0;
            ring_rd_accept_pulse_o <= 1'b0;
            ring_rd_reject_pulse_o <= 1'b0;
            ring_wr_snapshot_pulse_o <= 1'b0;
        end else begin
            producer_advance_accept_pulse_o <= 1'b0;
            producer_advance_reject_pulse_o <= 1'b0;
            ring_rd_accept_pulse_o <= 1'b0;
            ring_rd_reject_pulse_o <= 1'b0;
            ring_wr_snapshot_pulse_o <= 1'b0;

            if (soft_reset_i) begin
                config_q <= '0;
                producer_ptr_q <= 64'd0;
                sequence_q <= 32'd0;
                snapshot_q <= 64'd0;
                snapshot_valid_q <= 1'b0;
                pointer_error_q <= 1'b0;
                rd_epoch_valid_q <= 1'b0;
            end else if (ring_config_commit_pulse_i) begin
                config_q <= ring_config_i;
                producer_ptr_q <= 64'd0;
                sequence_q <= 32'd0;
                snapshot_q <= 64'd0;
                snapshot_valid_q <= 1'b0;
                pointer_error_q <= !ring_config_legal_fn(ring_config_i);
                rd_epoch_valid_q <= 1'b0;
            end

            if (!soft_reset_i && !ring_config_commit_pulse_i) begin
                if (producer_advance_valid_i) begin
                    if (producer_advance_accept) begin
                        producer_ptr_q <= producer_next_comb;
                        if (producer_advance_is_normal_i) begin
                            sequence_q <= sequence_q + 32'd1;
                        end
                        producer_advance_accept_pulse_o <= 1'b1;
                    end else begin
                        producer_advance_reject_pulse_o <= 1'b1;
                        pointer_error_q <= 1'b1;
                    end
                end

                if (ring_rd_commit_valid_i) begin
                    if (ring_rd_accept) begin
                        consumer_ptr_q <= ring_rd_commit_ptr_i;
                        rd_epoch_valid_q <= 1'b1;
                        ring_rd_accept_pulse_o <= 1'b1;
                    end else begin
                        ring_rd_reject_pulse_o <= 1'b1;
                        pointer_error_q <= 1'b1;
                    end
                end
            end

            // Reset/configuration commit owns snapshot and error state for this cycle. In
            // particular, a simultaneous snapshot request must not publish the pre-reset W value.
            if (!soft_reset_i && !ring_config_commit_pulse_i) begin
                if (ring_wr_snapshot_req_i) begin
                    snapshot_q <= producer_ptr_q;
                    snapshot_valid_q <= 1'b1;
                    ring_wr_snapshot_pulse_o <= 1'b1;
                end

                if (config_legal &&
                    ((telemetry_enable_i || ring_writer_enable_i) && !pointers_valid_comb)) begin
                    pointer_error_q <= 1'b1;
                end
            end
        end
    end

    assign producer_ptr_o = producer_ptr_q;
    assign consumer_ptr_o = rd_epoch_valid_q ? consumer_ptr_q : 64'd0;
    assign sequence_o = sequence_q;
    assign used_bytes_o = pointers_valid_comb ? used_bytes_comb : 64'd0;
    assign free_bytes_o = free_bytes_comb;
    assign current_offset_o = current_offset_comb;
    assign current_tail_bytes_o = current_tail_comb;
    assign ring_configured_o = config_legal;
    assign ring_full_o = pointers_valid_comb && (free_bytes_comb < DDR_ALIGN_BYTES_64);
    assign no_space_o = schedule_valid_i && !schedule_fits_comb;
    assign pointers_valid_o = pointers_valid_comb;
    assign malformed_config_o = config_q.configured && !config_legal;
    assign pointer_error_sticky_o = pointer_error_q;
    assign ring_wr_snapshot_o = snapshot_q;
    assign ring_wr_snapshot_valid_o = snapshot_valid_q;

    wire unused_status_hints = telemetry_enable_i ^ ring_writer_enable_i;

`ifndef SYNTHESIS
    initial begin
        if (GUARD_BYTES < TCSR_RING_GUARD_BYTES_MIN) begin
            $fatal(1, "trecap_ring_pointer_ctrl: GUARD_BYTES below Revision G minimum guard");
        end
        if ((GUARD_BYTES % TCSR_RING_ALIGNMENT_BYTES) != 0) begin
            $fatal(1, "trecap_ring_pointer_ctrl: GUARD_BYTES must be 64-byte aligned");
        end
        if (RING_SIZE_MIN_BYTES < 32'h0010_0000) begin
            $warning("trecap_ring_pointer_ctrl: RING_SIZE_MIN_BYTES below Revision G baseline 1 MiB");
        end
    end

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            // No simulation state.
        end else begin
            if (schedule_valid_i && scheduled_len_legal && !aligned64(scheduled_record_bytes_i)) begin
                $error("trecap_ring_pointer_ctrl: scheduled length is not 64-byte aligned");
            end
            if (producer_advance_valid_i && !producer_advance_kind_legal) begin
                $error("trecap_ring_pointer_ctrl: producer advance must be exactly one of normal/wrap");
            end
        end
    end
`endif

endmodule : trecap_ring_pointer_ctrl

`default_nettype wire
