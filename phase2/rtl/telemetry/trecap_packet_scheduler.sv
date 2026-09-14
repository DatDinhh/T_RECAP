// SPDX-License-Identifier: MIT
// File class: [1] hand-written RTL.
// Layer: rtl/telemetry/
// Owner: T-RECAP Phase 2 implementation.
// Purpose: Priority scheduler/arbitration stage for formatted telemetry records.
// Contract: Select one packetizer record stream at a time; preserve record atomicity;
//           do not create DDR records and do not backpressure the STFT/WOLA core.
// Generated dependencies: trecap_core_pkg, trecap_csr_pkg, trecap_packet_pkg,
//                         trecap_iface_pkg.

`default_nettype none

// Record-stream packet scheduler.
//
// This block arbitrates between already formatted packetizer streams. The packetizers own payload
// construction. The scheduler owns only admission ordering, packet-enable gating, basic metadata
// validation, and record-atomic selection. It deliberately has no DDR-ring, WRAP, pointer, or bus
// write logic; those belong in rtl/hps_bridge/.
//
// Priority policy follows the Revision G telemetry contract:
//   STATUS  -> priority 3, highest, dropped last
//   METRICS -> priority 2
//   SPEC    -> priority 1
//   WAVE    -> priority 0, lowest, dropped first
//
// Ready/valid contract:
//   - Each source presents one complete record as a beat stream.
//   - The source keeps its metadata stable for the entire record.
//   - Once a source is selected, this scheduler locks that source until the selected beat with
//     *_payload_last_i is accepted. This prevents interleaving payload beats from different packet
//     types.
//   - Disabled or illegal candidate records are drained locally and reported through drop pulses so
//     packetizers cannot wedge the telemetry layer after a runtime packet-enable change.
//
// Non-stall boundary:
//   The ready signals here go only back to packetizers. They shall never be connected to core
//   sample/frame/FFT/IFFT/WOLA/metrics logic. A packetizer that cannot buffer an event must drop
//   that telemetry event and increment PACKET_FIFO_DROP_COUNT through the telemetry top.
module trecap_packet_scheduler
#(
    parameter bit STATUS_PREEMPTS_WHEN_IDLE = 1'b1
) (
    input  logic                clk,
    input  logic                rst_n,
    // Synchronous formatter clear in clk domain. Arbitration/drain state is abandoned together
    // with the packetizers and FIFO, without deriving an asynchronous reset.
    input  logic                formatter_reset_i,

    input  logic                telemetry_enable_i,
    input  logic [31:0]         packet_enable_i,
    input  trecap_iface_pkg::trecap_spec_mode_e   spec_mode_i,

    input  logic                wave_valid_i,
    output logic                wave_ready_o,
    input  trecap_iface_pkg::trecap_record_meta_t wave_meta_i,
    input  logic                wave_payload_last_i,

    input  logic                spec_valid_i,
    output logic                spec_ready_o,
    input  trecap_iface_pkg::trecap_record_meta_t spec_meta_i,
    input  logic                spec_payload_last_i,

    input  logic                metrics_valid_i,
    output logic                metrics_ready_o,
    input  trecap_iface_pkg::trecap_record_meta_t metrics_meta_i,
    input  logic                metrics_payload_last_i,

    input  logic                status_valid_i,
    output logic                status_ready_o,
    input  trecap_iface_pkg::trecap_record_meta_t status_meta_i,
    input  logic                status_payload_last_i,

    output logic                out_valid_o,
    input  logic                out_ready_i,
    output logic [3:0]          out_sel_onehot_o,
    output trecap_iface_pkg::trecap_record_meta_t out_meta_o,

    // Per-candidate terminal drain events preserve exact drop counting when multiple disabled or
    // malformed records complete local draining on the same clock. Bit order is
    // {STATUS, METRICS, SPEC, WAVE}; aggregate outputs remain convenient fault pulses.
    output logic [3:0]          disabled_candidate_drop_events_o,
    output logic [3:0]          illegal_candidate_drop_events_o,
    output logic                disabled_candidate_drop_o,
    output logic                illegal_candidate_drop_o,
    output logic                scheduler_backpressure_o
);
  import trecap_core_pkg::*;
  import trecap_csr_pkg::*;
  import trecap_packet_pkg::*;
  import trecap_iface_pkg::*;
  import trecap_build_pkg::*;


    typedef enum logic [2:0] {
        SEL_NONE    = 3'd0,
        SEL_WAVE    = 3'd1,
        SEL_SPEC    = 3'd2,
        SEL_METRICS = 3'd3,
        SEL_STATUS  = 3'd4
    } trecap_sched_sel_e;

    trecap_sched_sel_e active_sel_q;
    logic              active_q;

    logic wave_gate;
    logic spec_gate;
    logic metrics_gate;
    logic status_gate;

    logic wave_allowed;
    logic spec_allowed;
    logic metrics_allowed;
    logic status_allowed;

    logic wave_meta_legal;
    logic spec_meta_legal;
    logic metrics_meta_legal;
    logic status_meta_legal;

    logic wave_legal;
    logic spec_legal;
    logic metrics_legal;
    logic status_legal;

    logic wave_disabled;
    logic spec_disabled;
    logic metrics_disabled;
    logic status_disabled;

    logic wave_illegal;
    logic spec_illegal;
    logic metrics_illegal;
    logic status_illegal;

    logic active_wave;
    logic active_spec;
    logic active_metrics;
    logic active_status;
    // Local drain ownership is latched per candidate. A one-cycle runtime disable/config change
    // may consume the first beat, but the remaining beats must continue to drain locally even if
    // the gate becomes legal again on the next clock.
    logic [3:0] disabled_drain_q;
    logic [3:0] illegal_drain_q;
    logic [3:0] disabled_start_w;
    logic [3:0] illegal_start_w;

    trecap_sched_sel_e idle_sel;
    trecap_sched_sel_e current_sel;
    logic              idle_has_legal;
    logic              current_valid;
    logic              current_last;
    logic              current_accept;

    function automatic bit packet_flags_legal(
        input trecap_packet_type_e packet_type,
        input logic [15:0]         flags
    );
        logic metric_aggregate;
        logic metric_per_frame;

        if ((flags & TPKT_FLAG_RESERVED_15_6_MASK) != 16'h0000) begin
            return 1'b0;
        end
        if ((flags & TPKT_FLAG_CRC_ENABLED_MASK) != 16'h0000) begin
            return 1'b0;
        end
        if ((flags & TPKT_FLAG_STATUS_DIAGNOSTIC_MASK) != 16'h0000) begin
            // FPGA-originated scheduled telemetry shall not set status_diagnostic. HPS may
            // synthesize diagnostic STATUS packets outside the DDR-ring stream.
            return 1'b0;
        end

        metric_aggregate = ((flags & TPKT_FLAG_AGGREGATE_METRICS_MASK) != 16'h0000);
        metric_per_frame = ((flags & TPKT_FLAG_PER_FRAME_METRICS_MASK) != 16'h0000);

        if (packet_type == TPKT_METRICS) begin
            if (metric_aggregate == metric_per_frame) begin
                return 1'b0;
            end
            if ((flags & TPKT_FLAG_PAYLOAD_SCALED_MASK) != 16'h0000) begin
                return 1'b0;
            end
        end else begin
            if (metric_aggregate || metric_per_frame) begin
                return 1'b0;
            end
        end

        return 1'b1;
    endfunction : packet_flags_legal

    function automatic bit packet_meta_legal(input trecap_record_meta_t meta);
        if (!meta.valid) begin
            return 1'b0;
        end
        if (!trecap_packet_type_known(meta.packet_type)) begin
            return 1'b0;
        end
        if (trecap_packet_type_reserved_disabled(meta.packet_type)) begin
            return 1'b0;
        end
        if (!trecap_payload_bytes_valid(meta.packet_type, int'(meta.payload_bytes))) begin
            return 1'b0;
        end
        if (!packet_flags_legal(meta.packet_type, meta.flags)) begin
            return 1'b0;
        end
        return 1'b1;
    endfunction : packet_meta_legal

    function automatic trecap_record_meta_t sanitize_meta(input trecap_record_meta_t meta);
        trecap_record_meta_t fixed;

        fixed = meta;
        fixed.valid = 1'b1;
        fixed.drop_priority = trecap_packet_drop_priority(meta.packet_type);
        return fixed;
    endfunction : sanitize_meta

    function automatic logic [3:0] sel_to_onehot(input trecap_sched_sel_e sel);
        unique case (sel)
            SEL_WAVE: begin
                return 4'b0001;
            end
            SEL_SPEC: begin
                return 4'b0010;
            end
            SEL_METRICS: begin
                return 4'b0100;
            end
            SEL_STATUS: begin
                return 4'b1000;
            end
            default: begin
                return 4'b0000;
            end
        endcase
    endfunction : sel_to_onehot

    // Packet-enable and SPEC_MODE gating. These expressions intentionally derive from generated
    // CSR and interface constants rather than duplicating bit positions or type IDs.
    always_comb begin
        wave_gate = telemetry_enable_i &&
                    ((packet_enable_i & TCSR_PACKET_ENABLE_WAVE_EN_MASK) != 32'h0000);
        spec_gate = telemetry_enable_i &&
                    ((packet_enable_i & TCSR_PACKET_ENABLE_SPEC_EN_MASK) != 32'h0000) &&
                    (spec_mode_i != TSPEC_DISABLED);
        metrics_gate = telemetry_enable_i &&
                       ((packet_enable_i & TCSR_PACKET_ENABLE_METRICS_EN_MASK) != 32'h0000);
        status_gate = telemetry_enable_i &&
                      ((packet_enable_i & TCSR_PACKET_ENABLE_STATUS_EN_MASK) != 32'h0000);

        wave_allowed = wave_gate && (wave_meta_i.packet_type == TPKT_WAVE);

        spec_allowed = spec_gate;
        unique case (spec_mode_i)
            TSPEC_SPEC64: begin
                spec_allowed = spec_allowed && (spec_meta_i.packet_type == TPKT_SPEC64);
            end
            TSPEC_SPEC129: begin
                spec_allowed = spec_allowed && (spec_meta_i.packet_type == TPKT_SPEC129);
            end
            default: begin
                spec_allowed = 1'b0;
            end
        endcase

        metrics_allowed = metrics_gate && (metrics_meta_i.packet_type == TPKT_METRICS);

        status_allowed = status_gate && (status_meta_i.packet_type == TPKT_STATUS);
    end

    always_comb begin
        wave_meta_legal = packet_meta_legal(wave_meta_i);
        spec_meta_legal = packet_meta_legal(spec_meta_i);
        metrics_meta_legal = packet_meta_legal(metrics_meta_i);
        status_meta_legal = packet_meta_legal(status_meta_i);

        wave_legal = wave_valid_i && wave_allowed && wave_meta_legal &&
                     !disabled_drain_q[0] && !illegal_drain_q[0];
        spec_legal = spec_valid_i && spec_allowed && spec_meta_legal &&
                     !disabled_drain_q[1] && !illegal_drain_q[1];
        metrics_legal = metrics_valid_i && metrics_allowed && metrics_meta_legal &&
                        !disabled_drain_q[2] && !illegal_drain_q[2];
        status_legal = status_valid_i && status_allowed && status_meta_legal &&
                       !disabled_drain_q[3] && !illegal_drain_q[3];

        wave_disabled = !formatter_reset_i && wave_valid_i && !wave_gate;
        spec_disabled = !formatter_reset_i && spec_valid_i && !spec_gate;
        metrics_disabled = !formatter_reset_i && metrics_valid_i && !metrics_gate;
        status_disabled = !formatter_reset_i && status_valid_i && !status_gate;

        wave_illegal = !formatter_reset_i && wave_valid_i && wave_gate &&
                       (!wave_allowed || !wave_meta_legal);
        spec_illegal = !formatter_reset_i && spec_valid_i && spec_gate &&
                       (!spec_allowed || !spec_meta_legal);
        metrics_illegal = !formatter_reset_i && metrics_valid_i && metrics_gate &&
                          (!metrics_allowed || !metrics_meta_legal);
        status_illegal = !formatter_reset_i && status_valid_i && status_gate &&
                         (!status_allowed || !status_meta_legal);
    end

    // Idle arbitration. This block chooses only at record boundary. Once a source wins, active_q
    // locks the selection until the accepted final payload beat.
    always_comb begin
        idle_sel = SEL_NONE;
        idle_has_legal = 1'b0;

        if (STATUS_PREEMPTS_WHEN_IDLE && status_legal) begin
            idle_sel = SEL_STATUS;
            idle_has_legal = 1'b1;
        end else if (metrics_legal) begin
            idle_sel = SEL_METRICS;
            idle_has_legal = 1'b1;
        end else if (spec_legal) begin
            idle_sel = SEL_SPEC;
            idle_has_legal = 1'b1;
        end else if (wave_legal) begin
            idle_sel = SEL_WAVE;
            idle_has_legal = 1'b1;
        end else if (!STATUS_PREEMPTS_WHEN_IDLE && status_legal) begin
            idle_sel = SEL_STATUS;
            idle_has_legal = 1'b1;
        end
    end

    always_comb begin
        current_sel = active_q ? active_sel_q : idle_sel;
        current_valid = 1'b0;
        current_last = 1'b0;
        out_meta_o = '0;

        unique case (current_sel)
            SEL_WAVE: begin
                current_valid = active_q ? wave_valid_i : wave_legal;
                current_last = wave_payload_last_i;
                out_meta_o = sanitize_meta(wave_meta_i);
            end
            SEL_SPEC: begin
                current_valid = active_q ? spec_valid_i : spec_legal;
                current_last = spec_payload_last_i;
                out_meta_o = sanitize_meta(spec_meta_i);
            end
            SEL_METRICS: begin
                current_valid = active_q ? metrics_valid_i : metrics_legal;
                current_last = metrics_payload_last_i;
                out_meta_o = sanitize_meta(metrics_meta_i);
            end
            SEL_STATUS: begin
                current_valid = active_q ? status_valid_i : status_legal;
                current_last = status_payload_last_i;
                out_meta_o = sanitize_meta(status_meta_i);
            end
            default: begin
                current_valid = 1'b0;
                current_last = 1'b0;
                out_meta_o = '0;
            end
        endcase
    end

    assign out_valid_o = !formatter_reset_i &&
                         (active_q ? current_valid : (idle_has_legal && current_valid));
    assign out_sel_onehot_o = out_valid_o ? sel_to_onehot(current_sel) : 4'b0000;
    assign current_accept = out_valid_o & out_ready_i;
    assign active_wave = active_q && (active_sel_q == SEL_WAVE);
    assign active_spec = active_q && (active_sel_q == SEL_SPEC);
    assign active_metrics = active_q && (active_sel_q == SEL_METRICS);
    assign active_status = active_q && (active_sel_q == SEL_STATUS);
    assign disabled_start_w = {
        status_disabled && !active_status && !disabled_drain_q[3] && !illegal_drain_q[3],
        metrics_disabled && !active_metrics && !disabled_drain_q[2] && !illegal_drain_q[2],
        spec_disabled && !active_spec && !disabled_drain_q[1] && !illegal_drain_q[1],
        wave_disabled && !active_wave && !disabled_drain_q[0] && !illegal_drain_q[0]
    };
    assign illegal_start_w = {
        status_illegal && !active_status && !disabled_drain_q[3] && !illegal_drain_q[3],
        metrics_illegal && !active_metrics && !disabled_drain_q[2] && !illegal_drain_q[2],
        spec_illegal && !active_spec && !disabled_drain_q[1] && !illegal_drain_q[1],
        wave_illegal && !active_wave && !disabled_drain_q[0] && !illegal_drain_q[0]
    };

    always_comb begin
        wave_ready_o = 1'b0;
        spec_ready_o = 1'b0;
        metrics_ready_o = 1'b0;
        status_ready_o = 1'b0;

        if (!formatter_reset_i) begin
            // Drain disabled or illegal records locally. Legal records are backpressured only by
            // the packet FIFO/HPS-bridge side, never by the core tap side.
            if (disabled_start_w[0] || illegal_start_w[0] ||
                disabled_drain_q[0] || illegal_drain_q[0]) begin
                wave_ready_o = 1'b1;
            end
            if (disabled_start_w[1] || illegal_start_w[1] ||
                disabled_drain_q[1] || illegal_drain_q[1]) begin
                spec_ready_o = 1'b1;
            end
            if (disabled_start_w[2] || illegal_start_w[2] ||
                disabled_drain_q[2] || illegal_drain_q[2]) begin
                metrics_ready_o = 1'b1;
            end
            if (disabled_start_w[3] || illegal_start_w[3] ||
                disabled_drain_q[3] || illegal_drain_q[3]) begin
                status_ready_o = 1'b1;
            end

            if (out_valid_o) begin
                unique case (current_sel)
                    SEL_WAVE: begin
                        wave_ready_o = out_ready_i;
                    end
                    SEL_SPEC: begin
                        spec_ready_o = out_ready_i;
                    end
                    SEL_METRICS: begin
                        metrics_ready_o = out_ready_i;
                    end
                    SEL_STATUS: begin
                        status_ready_o = out_ready_i;
                    end
                    default: begin
                        // No selected source.
                    end
                endcase
            end
        end
    end

    assign disabled_candidate_drop_events_o = {
        (disabled_start_w[3] || disabled_drain_q[3]) && status_valid_i &&
            status_ready_o && status_payload_last_i,
        (disabled_start_w[2] || disabled_drain_q[2]) && metrics_valid_i &&
            metrics_ready_o && metrics_payload_last_i,
        (disabled_start_w[1] || disabled_drain_q[1]) && spec_valid_i &&
            spec_ready_o && spec_payload_last_i,
        (disabled_start_w[0] || disabled_drain_q[0]) && wave_valid_i &&
            wave_ready_o && wave_payload_last_i
    };
    assign illegal_candidate_drop_events_o = {
        (illegal_start_w[3] || illegal_drain_q[3]) && status_valid_i &&
            status_ready_o && status_payload_last_i,
        (illegal_start_w[2] || illegal_drain_q[2]) && metrics_valid_i &&
            metrics_ready_o && metrics_payload_last_i,
        (illegal_start_w[1] || illegal_drain_q[1]) && spec_valid_i &&
            spec_ready_o && spec_payload_last_i,
        (illegal_start_w[0] || illegal_drain_q[0]) && wave_valid_i &&
            wave_ready_o && wave_payload_last_i
    };
    assign disabled_candidate_drop_o = |disabled_candidate_drop_events_o;
    assign illegal_candidate_drop_o = |illegal_candidate_drop_events_o;

    assign scheduler_backpressure_o = out_valid_o & !out_ready_i;

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            active_q <= 1'b0;
            active_sel_q <= SEL_NONE;
            disabled_drain_q <= 4'b0000;
            illegal_drain_q <= 4'b0000;
        end else if (formatter_reset_i) begin
            active_q <= 1'b0;
            active_sel_q <= SEL_NONE;
            disabled_drain_q <= 4'b0000;
            illegal_drain_q <= 4'b0000;
        end else begin
            for (int unsigned candidate = 0; candidate < 4; candidate++) begin
                if (disabled_candidate_drop_events_o[candidate]) begin
                    disabled_drain_q[candidate] <= 1'b0;
                end else if (disabled_start_w[candidate]) begin
                    disabled_drain_q[candidate] <= 1'b1;
                end

                if (illegal_candidate_drop_events_o[candidate]) begin
                    illegal_drain_q[candidate] <= 1'b0;
                end else if (illegal_start_w[candidate]) begin
                    illegal_drain_q[candidate] <= 1'b1;
                end
            end

            if (active_q) begin
                if (current_accept && current_last) begin
                    active_q <= 1'b0;
                    active_sel_q <= SEL_NONE;
                end
            end else if (idle_has_legal && current_valid) begin
                // Lock if the first beat is not accepted immediately or if the record has more
                // beats after this accepted beat.
                if (!(out_ready_i && current_last)) begin
                    active_q <= 1'b1;
                    active_sel_q <= idle_sel;
                end
            end
        end
    end

`ifndef SYNTHESIS
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            // No simulation state.
        end else if (!formatter_reset_i) begin
            if (active_q && !current_valid) begin
                $error("trecap_packet_scheduler: selected source deasserted valid before record last");
            end
            if ((disabled_drain_q[0] || illegal_drain_q[0]) && !wave_valid_i) begin
                $error("trecap_packet_scheduler: WAVE drain source retracted valid before record last");
            end
            if ((disabled_drain_q[1] || illegal_drain_q[1]) && !spec_valid_i) begin
                $error("trecap_packet_scheduler: SPEC drain source retracted valid before record last");
            end
            if ((disabled_drain_q[2] || illegal_drain_q[2]) && !metrics_valid_i) begin
                $error("trecap_packet_scheduler: METRICS drain source retracted valid before record last");
            end
            if ((disabled_drain_q[3] || illegal_drain_q[3]) && !status_valid_i) begin
                $error("trecap_packet_scheduler: STATUS drain source retracted valid before record last");
            end
            if (out_valid_o && (out_meta_o.payload_bytes > (TPKT_UDP_MAX_BYTES - TPKT_HEADER_BYTES))) begin
                $error("trecap_packet_scheduler: selected payload exceeds Revision G UDP bound");
            end
        end
    end
`endif

endmodule : trecap_packet_scheduler

`default_nettype wire
