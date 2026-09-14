// SPDX-License-Identifier: MIT
// File class: [1] hand-written RTL.
// Layer: rtl/telemetry/
// Owner: T-RECAP Phase 2 implementation.
// Purpose: Top-level non-stalling telemetry formatter boundary.
// Contract: Integrate packet scheduler, packetizers, and packet FIFO; expose formatted records to
//           rtl/hps_bridge/ without owning DDR writes or HPS/Ethernet behavior.
// Generated dependencies: trecap_core_pkg, trecap_csr_pkg, trecap_packet_pkg,
//                         trecap_iface_pkg.

`default_nettype none

// T-RECAP telemetry layer top.
//
// This module is the boundary between core observation taps and the HPS-bridge record stream.
// It intentionally does not instantiate any DDR writer, Avalon master, ring pointer controller, or
// Ethernet logic. Formatted records leave this block through a ready/valid stream and become the
// responsibility of rtl/hps_bridge/.
//
// Core tap rule:
//   Inputs from the core are valid-only observations. This block never returns ready into the
//   STFT/WOLA sample path, frame scheduler, FFT/IFFT path, WOLA output, or core metrics path.
//   Packetizers must either buffer or drop telemetry events when they cannot accept them.
//
// Payload stream convention:
//   record_valid_o/record_ready_i/record_payload_* is a beat stream after the packet FIFO. The
//   metadata is stable for all beats of one record. record_payload_last_o marks the final payload
//   beat. The downstream record builder adds the 32-byte DDR/UDP header and 64-byte DDR padding.
//
// Packetizer/FIFO module ports are frozen here so later packetizer files can be written against a
// stable top-level contract.
module trecap_telemetry_top
#(
    parameter int unsigned PAYLOAD_DATA_W       = 32,
    parameter int unsigned PAYLOAD_KEEP_W       = (PAYLOAD_DATA_W + 7) / 8,
    parameter int unsigned PACKET_FIFO_RECORDS  = 8,
    parameter int unsigned PACKET_FIFO_BYTES    = trecap_packet_pkg::TPKT_UDP_MAX_BYTES,
    parameter int unsigned BIN_IDX_W            = (trecap_core_pkg::T_UNIQUE_BINS <= 1) ? 1 : $clog2(trecap_core_pkg::T_UNIQUE_BINS),
    parameter bit          CLEAR_COUNTERS_ON_SOFT_RESET = 1'b1
) (
    input  logic                       clk,
    input  logic                       rst_n,

    // Synchronous pulse in this clock domain. The CSR bank is responsible for CDC-safe transfer
    // before driving this top.
    input  logic                       telemetry_soft_reset_i,

    // Formatter/discontinuity flush. This has the same structural effect on packetizers,
    // scheduler, and packet FIFO as a telemetry soft reset, but deliberately preserves all
    // diagnostic counters and sticky evidence.
    input  logic                       formatter_flush_i,

    // Diagnostic counter clear. This clears only the pre-writer packet-drop counter; it must not
    // flush formatter state or clear the packet-FIFO overflow sticky.
    input  logic                       counter_clear_i,

    // One-cycle observation-epoch boundary (for example a source discontinuity). Admission is
    // suppressed for this cycle so partial packetizer collections are discarded without resetting
    // the packet FIFO or retracting an already-started record.
    input  logic                       observation_epoch_reset_i,

    // Caller-qualified safe event. This clears only aggregate METRICS state; it does not reset
    // packetizers, the packet FIFO, the scheduler, or transport drop counters.
    input  logic                       metrics_clear_i,

    input  trecap_iface_pkg::trecap_hps_bridge_ctrl_t    ctrl_i,

    // Valid-only core sample and frame taps. No ready signal is returned.
    input  trecap_iface_pkg::trecap_core_tap_sample_t    tap_sample_i,
    input  trecap_iface_pkg::trecap_core_tap_frame_t     tap_frame_i,

    // Unique-bin stream for SPEC packetizers. This is valid-only and may be dropped by the
    // spectrum packetizer if its local buffer cannot accept the bin event.
    input  logic                       tap_bin_valid_i,
    input  logic [63:0]                tap_bin_frame_idx_i,
    input  logic [BIN_IDX_W-1:0]       tap_bin_idx_i,
    input  logic [trecap_core_pkg::T_MAG2_W-1:0]        tap_bin_mag2_i,
    input  logic                       tap_bin_mask_i,
    input  logic                       tap_bin_eligible_i,
    input  logic                       tap_bin_last_i,

    // External low-rate scheduler ticks. Platform/HPS bridge code owns converting desired rates
    // such as 5-10 Hz STATUS and 20-30 Hz METRICS into these pulses.
    input  logic                       status_tick_i,
    input  logic                       metrics_tick_i,

    // Authoritative coherent core counters. STATUS must not reconstruct these from delayed
    // output-tap indices. Core-owned error aggregates are snapshotted into METRICS records.
    input  logic [63:0]                core_sample_count_i,
    input  logic [63:0]                core_frame_count_i,
    input  logic [63:0]                core_sum_abs_err_lo_i,
    input  logic [63:0]                core_sum_sq_err_lo_i,
    input  logic [31:0]                core_max_abs_err_i,
    input  logic                       core_metric_truncated_i,

    // Status-payload inputs that are visible to FPGA-originated STATUS skeletons. HPS-owned UDP
    // counters may be patched only in the outgoing UDP copy, not in the committed DDR record.
    input  logic [31:0]                sample_rate_hz_i,
    input  logic [31:0]                overflow_flags_i,
    input  logic [31:0]                dma_drop_count_i,
    input  logic [31:0]                dma_packet_count_i,
    input  logic [31:0]                csr_command_reject_count_i,

    // Formatted record stream toward rtl/hps_bridge/.
    output logic                       record_valid_o,
    input  logic                       record_ready_i,
    output trecap_iface_pkg::trecap_record_meta_t        record_meta_o,
    output logic [PAYLOAD_DATA_W-1:0]  record_payload_data_o,
    output logic [PAYLOAD_KEEP_W-1:0]  record_payload_keep_o,
    output logic                       record_payload_last_o,

    // Pre-writer telemetry drops. This is the source for PACKET_FIFO_DROP_COUNT in the CSR bank.
    output logic [31:0]                packet_fifo_drop_count_o,
    output logic                       packet_fifo_drop_pulse_o,
    output logic                       packet_fifo_full_o,
    output logic                       packet_fifo_overflow_o,

    output logic                       scheduler_backpressure_o,
    output logic                       scheduler_disabled_drop_o,
    output logic                       scheduler_illegal_drop_o
);
  import trecap_core_pkg::*;
  import trecap_csr_pkg::*;
  import trecap_packet_pkg::*;
  import trecap_iface_pkg::*;
  import trecap_build_pkg::*;


    logic packet_enable_legal;
    logic spec_mode_legal;
    logic spec_shift_legal;
    logic wave_decim_legal;
    logic telemetry_config_legal;
    logic telemetry_runtime_enable;
    logic telemetry_admit_enable;
    logic formatter_reset;

    // Packetizer output streams.
    logic wave_valid;
    logic wave_ready;
    trecap_record_meta_t wave_meta;
    logic [PAYLOAD_DATA_W-1:0] wave_payload_data;
    logic [PAYLOAD_KEEP_W-1:0] wave_payload_keep;
    logic wave_payload_last;
    logic wave_drop_pulse;

    logic spec_valid;
    logic spec_ready;
    trecap_record_meta_t spec_meta;
    logic [PAYLOAD_DATA_W-1:0] spec_payload_data;
    logic [PAYLOAD_KEEP_W-1:0] spec_payload_keep;
    logic spec_payload_last;
    logic spec_drop_pulse;

    logic metrics_valid;
    logic metrics_ready;
    trecap_record_meta_t metrics_meta;
    logic [PAYLOAD_DATA_W-1:0] metrics_payload_data;
    logic [PAYLOAD_KEEP_W-1:0] metrics_payload_keep;
    logic metrics_payload_last;
    logic metrics_drop_pulse;

    logic status_valid;
    logic status_ready;
    trecap_record_meta_t status_meta;
    logic [PAYLOAD_DATA_W-1:0] status_payload_data;
    logic [PAYLOAD_KEEP_W-1:0] status_payload_keep;
    logic status_payload_last;
    logic status_drop_pulse;

    logic sched_valid;
    logic sched_ready;
    logic [3:0] sched_sel_onehot;
    logic [3:0] sched_disabled_drop_events;
    logic [3:0] sched_illegal_drop_events;
    trecap_record_meta_t sched_meta;

    logic [PAYLOAD_DATA_W-1:0] fifo_in_payload_data;
    logic [PAYLOAD_KEEP_W-1:0] fifo_in_payload_keep;
    logic fifo_in_payload_last;

    logic fifo_drop_pulse;
    logic fifo_overflow_sticky;
    logic fifo_full;

    logic [31:0] packet_fifo_drop_count_q;
    logic        packet_fifo_overflow_q;
    logic [12:0] drop_events;
    logic [31:0] drop_event_count;

    // The command/CSR layer is expected to reject malformed controls. This boundary still fails
    // closed if an illegal value escapes: existing records are drained atomically and no new event
    // is admitted until the complete control tuple is legal again.
    assign packet_enable_legal =
        ((ctrl_i.packet_enable & TCSR_PACKET_ENABLE_RESERVED_31_6_MASK) == 32'd0) &&
        ((ctrl_i.packet_enable & TCSR_PACKET_ENABLE_PEAKS_EN_MASK) == 32'd0) &&
        ((ctrl_i.packet_enable & TCSR_PACKET_ENABLE_DEBUG_EN_MASK) == 32'd0);
    assign spec_mode_legal = (ctrl_i.spec_mode == TSPEC_DISABLED) ||
                             (ctrl_i.spec_mode == TSPEC_SPEC64) ||
                             (ctrl_i.spec_mode == TSPEC_SPEC129);
    assign spec_shift_legal = (int'(ctrl_i.spec_shift) <= TCSR_SPEC_SHIFT_MAX);
    assign wave_decim_legal = (ctrl_i.wave_decim != 16'd0);
    assign telemetry_config_legal = packet_enable_legal && spec_mode_legal &&
                                    spec_shift_legal && wave_decim_legal;
    assign telemetry_runtime_enable = ctrl_i.telemetry_enable && telemetry_config_legal;
    assign formatter_reset = telemetry_soft_reset_i || formatter_flush_i;
    assign telemetry_admit_enable = telemetry_runtime_enable &&
                                    !telemetry_soft_reset_i &&
                                    !observation_epoch_reset_i;

    function automatic logic [31:0] count_drop_events(input logic [12:0] events);
        logic [31:0] count;
        int unsigned i;

        count = 32'd0;
        for (i = 0; i < 13; i++) begin
            count = count + (events[i] ? 32'd1 : 32'd0);
        end
        return count;
    endfunction : count_drop_events

    // A telemetry soft reset flushes formatter/FIFO state; discarded state is not reported as
    // congestion loss. Suppressing admission and drop accounting during the reset cycle also
    // prevents a stale registered drop pulse from being counted after the synchronous clear.
    assign drop_events = formatter_reset ? 13'd0 : {
        fifo_drop_pulse,
        status_drop_pulse,
        metrics_drop_pulse,
        spec_drop_pulse,
        wave_drop_pulse,
        sched_illegal_drop_events,
        sched_disabled_drop_events
    };
    assign drop_event_count = count_drop_events(drop_events);

    assign packet_fifo_drop_count_o = packet_fifo_drop_count_q;
    assign packet_fifo_drop_pulse_o = |drop_events;
    assign packet_fifo_full_o = fifo_full;
    assign packet_fifo_overflow_o = packet_fifo_overflow_q | fifo_overflow_sticky;

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            packet_fifo_drop_count_q <= 32'd0;
            packet_fifo_overflow_q <= 1'b0;
        end else begin
            if (telemetry_soft_reset_i && CLEAR_COUNTERS_ON_SOFT_RESET) begin
                packet_fifo_drop_count_q <= 32'd0;
                packet_fifo_overflow_q <= 1'b0;
            end else begin
                if (counter_clear_i) begin
                    packet_fifo_drop_count_q <= 32'd0;
                end else begin
                    packet_fifo_drop_count_q <= packet_fifo_drop_count_q + drop_event_count;
                end
                if (|drop_events) begin
                    packet_fifo_overflow_q <= 1'b1;
                end
            end
        end
    end

    // -------------------------------------------------------------------------
    // Packetizers. These modules are written in later files under rtl/telemetry/.
    // The top-level contract here fixes their integration boundary now.
    // -------------------------------------------------------------------------

    trecap_wave_packetizer #(
        .PAYLOAD_DATA_W(PAYLOAD_DATA_W),
        .PAYLOAD_KEEP_W(PAYLOAD_KEEP_W)
    ) u_wave_packetizer (
        .clk(clk),
        .rst_n(rst_n),
        .formatter_reset_i(formatter_reset),
        .enable_i(telemetry_admit_enable &&
                  ((ctrl_i.packet_enable & TCSR_PACKET_ENABLE_WAVE_EN_MASK) != 32'h0000)),
        .wave_decim_i(ctrl_i.wave_decim),
        .tap_sample_i(tap_sample_i),
        .out_valid_o(wave_valid),
        .out_ready_i(wave_ready),
        .out_meta_o(wave_meta),
        .out_payload_data_o(wave_payload_data),
        .out_payload_keep_o(wave_payload_keep),
        .out_payload_last_o(wave_payload_last),
        .drop_pulse_o(wave_drop_pulse)
    );

    trecap_spec_packetizer #(
        .PAYLOAD_DATA_W(PAYLOAD_DATA_W),
        .PAYLOAD_KEEP_W(PAYLOAD_KEEP_W),
        .BIN_IDX_W(BIN_IDX_W)
    ) u_spec_packetizer (
        .clk(clk),
        .rst_n(rst_n),
        .formatter_reset_i(formatter_reset),
        .enable_i(telemetry_admit_enable &&
                  ((ctrl_i.packet_enable & TCSR_PACKET_ENABLE_SPEC_EN_MASK) != 32'h0000) &&
                  (ctrl_i.spec_mode != TSPEC_DISABLED)),
        .spec_mode_i(ctrl_i.spec_mode),
        .spec_shift_i(ctrl_i.spec_shift),
        .tap_frame_i(tap_frame_i),
        .tap_bin_valid_i(tap_bin_valid_i),
        .tap_bin_frame_idx_i(tap_bin_frame_idx_i),
        .tap_bin_idx_i(tap_bin_idx_i),
        .tap_bin_mag2_i(tap_bin_mag2_i),
        .tap_bin_mask_i(tap_bin_mask_i),
        .tap_bin_eligible_i(tap_bin_eligible_i),
        .tap_bin_last_i(tap_bin_last_i),
        .out_valid_o(spec_valid),
        .out_ready_i(spec_ready),
        .out_meta_o(spec_meta),
        .out_payload_data_o(spec_payload_data),
        .out_payload_keep_o(spec_payload_keep),
        .out_payload_last_o(spec_payload_last),
        .drop_pulse_o(spec_drop_pulse)
    );

    trecap_metrics_packetizer #(
        .PAYLOAD_DATA_W(PAYLOAD_DATA_W),
        .PAYLOAD_KEEP_W(PAYLOAD_KEEP_W)
    ) u_metrics_packetizer (
        .clk(clk),
        .rst_n(rst_n),
        .enable_i(telemetry_admit_enable &&
                  ((ctrl_i.packet_enable & TCSR_PACKET_ENABLE_METRICS_EN_MASK) != 32'h0000)),
        .formatter_reset_i(formatter_reset),
        .clear_metrics_i(metrics_clear_i),
        .metrics_tick_i(metrics_tick_i),
        .tap_frame_i(tap_frame_i),
        .core_sum_abs_err_lo_i(core_sum_abs_err_lo_i),
        .core_sum_sq_err_lo_i(core_sum_sq_err_lo_i),
        .core_max_abs_err_i(core_max_abs_err_i),
        .core_metric_truncated_i(core_metric_truncated_i),
        .overflow_flags_i(overflow_flags_i),
        .out_valid_o(metrics_valid),
        .out_ready_i(metrics_ready),
        .out_meta_o(metrics_meta),
        .out_payload_data_o(metrics_payload_data),
        .out_payload_keep_o(metrics_payload_keep),
        .out_payload_last_o(metrics_payload_last),
        .drop_pulse_o(metrics_drop_pulse)
    );

    trecap_status_packetizer #(
        .PAYLOAD_DATA_W(PAYLOAD_DATA_W),
        .PAYLOAD_KEEP_W(PAYLOAD_KEEP_W)
    ) u_status_packetizer (
        .clk(clk),
        .rst_n(rst_n),
        .formatter_reset_i(formatter_reset),
        .enable_i(telemetry_admit_enable &&
                  ((ctrl_i.packet_enable & TCSR_PACKET_ENABLE_STATUS_EN_MASK) != 32'h0000)),
        .status_tick_i(status_tick_i),
        .ctrl_i(ctrl_i),
        .core_sample_count_i(core_sample_count_i),
        .core_frame_count_i(core_frame_count_i),
        .sample_rate_hz_i(sample_rate_hz_i),
        .overflow_flags_i(overflow_flags_i),
        .dma_drop_count_i(dma_drop_count_i),
        .dma_packet_count_i(dma_packet_count_i),
        .packet_fifo_drop_count_i(packet_fifo_drop_count_q),
        .csr_command_reject_count_i(csr_command_reject_count_i),
        .out_valid_o(status_valid),
        .out_ready_i(status_ready),
        .out_meta_o(status_meta),
        .out_payload_data_o(status_payload_data),
        .out_payload_keep_o(status_payload_keep),
        .out_payload_last_o(status_payload_last),
        .drop_pulse_o(status_drop_pulse)
    );

    // -------------------------------------------------------------------------
    // Scheduler and record-stream mux.
    // -------------------------------------------------------------------------

    trecap_packet_scheduler u_packet_scheduler (
        .clk(clk),
        .rst_n(rst_n),
        .formatter_reset_i(formatter_reset),
        .telemetry_enable_i(telemetry_admit_enable),
        .packet_enable_i(ctrl_i.packet_enable),
        .spec_mode_i(ctrl_i.spec_mode),

        .wave_valid_i(wave_valid),
        .wave_ready_o(wave_ready),
        .wave_meta_i(wave_meta),
        .wave_payload_last_i(wave_payload_last),

        .spec_valid_i(spec_valid),
        .spec_ready_o(spec_ready),
        .spec_meta_i(spec_meta),
        .spec_payload_last_i(spec_payload_last),

        .metrics_valid_i(metrics_valid),
        .metrics_ready_o(metrics_ready),
        .metrics_meta_i(metrics_meta),
        .metrics_payload_last_i(metrics_payload_last),

        .status_valid_i(status_valid),
        .status_ready_o(status_ready),
        .status_meta_i(status_meta),
        .status_payload_last_i(status_payload_last),

        .out_valid_o(sched_valid),
        .out_ready_i(sched_ready),
        .out_sel_onehot_o(sched_sel_onehot),
        .out_meta_o(sched_meta),

        .disabled_candidate_drop_events_o(sched_disabled_drop_events),
        .illegal_candidate_drop_events_o(sched_illegal_drop_events),
        .disabled_candidate_drop_o(scheduler_disabled_drop_o),
        .illegal_candidate_drop_o(scheduler_illegal_drop_o),
        .scheduler_backpressure_o(scheduler_backpressure_o)
    );

    always_comb begin
        fifo_in_payload_data = '0;
        fifo_in_payload_keep = '0;
        fifo_in_payload_last = 1'b0;

        unique case (1'b1)
            sched_sel_onehot[0]: begin
                fifo_in_payload_data = wave_payload_data;
                fifo_in_payload_keep = wave_payload_keep;
                fifo_in_payload_last = wave_payload_last;
            end
            sched_sel_onehot[1]: begin
                fifo_in_payload_data = spec_payload_data;
                fifo_in_payload_keep = spec_payload_keep;
                fifo_in_payload_last = spec_payload_last;
            end
            sched_sel_onehot[2]: begin
                fifo_in_payload_data = metrics_payload_data;
                fifo_in_payload_keep = metrics_payload_keep;
                fifo_in_payload_last = metrics_payload_last;
            end
            sched_sel_onehot[3]: begin
                fifo_in_payload_data = status_payload_data;
                fifo_in_payload_keep = status_payload_keep;
                fifo_in_payload_last = status_payload_last;
            end
            default: begin
                fifo_in_payload_data = '0;
                fifo_in_payload_keep = '0;
                fifo_in_payload_last = 1'b0;
            end
        endcase
    end

    trecap_packet_fifo #(
        .PAYLOAD_DATA_W(PAYLOAD_DATA_W),
        .PAYLOAD_KEEP_W(PAYLOAD_KEEP_W),
        .RECORD_DEPTH(PACKET_FIFO_RECORDS),
        .PAYLOAD_BYTES_MAX(PACKET_FIFO_BYTES)
    ) u_packet_fifo (
        .clk(clk),
        .rst_n(rst_n),
        .flush_i(formatter_reset),

        .in_valid_i(sched_valid),
        .in_ready_o(sched_ready),
        .in_meta_i(sched_meta),
        .in_payload_data_i(fifo_in_payload_data),
        .in_payload_keep_i(fifo_in_payload_keep),
        .in_payload_last_i(fifo_in_payload_last),

        .out_valid_o(record_valid_o),
        .out_ready_i(record_ready_i),
        .out_meta_o(record_meta_o),
        .out_payload_data_o(record_payload_data_o),
        .out_payload_keep_o(record_payload_keep_o),
        .out_payload_last_o(record_payload_last_o),

        .drop_pulse_o(fifo_drop_pulse),
        .full_o(fifo_full),
        .overflow_sticky_o(fifo_overflow_sticky)
    );

`ifndef SYNTHESIS
    initial begin
        if (PAYLOAD_DATA_W < 8) begin
            $fatal(1, "trecap_telemetry_top: PAYLOAD_DATA_W must be at least 8");
        end
        if ((PAYLOAD_DATA_W % 8) != 0) begin
            $fatal(1, "trecap_telemetry_top: PAYLOAD_DATA_W must be byte-aligned");
        end
        if (PACKET_FIFO_RECORDS < 1) begin
            $fatal(1, "trecap_telemetry_top: PACKET_FIFO_RECORDS must be at least 1");
        end
        if (PACKET_FIFO_BYTES < TPKT_UDP_MAX_BYTES) begin
            $warning(
                "trecap_telemetry_top: PACKET_FIFO_BYTES=%0d below Revision G UDP max %0d",
                PACKET_FIFO_BYTES,
                TPKT_UDP_MAX_BYTES
            );
        end
    end

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            // No simulation state.
        end else if (record_valid_o && !record_meta_o.valid) begin
            $error("trecap_telemetry_top: output record_valid_o asserted with invalid metadata");
        end
    end
`endif

endmodule : trecap_telemetry_top

`default_nettype wire
