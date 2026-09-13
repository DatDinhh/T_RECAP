// SPDX-License-Identifier: MIT
// File class: [1] hand-written RTL.
// Layer: rtl/hps_bridge/
// Owner: T-RECAP Phase 2 implementation.
// Purpose: Revision G HPS-visible CSR bank for telemetry/control/status.
// Contract: Implement generated CSR offsets, W1P controls, W1C sticky flags, VERSION reporting,
//           command-reject accounting, coherent snapshots, and safe shadow/commit controls.
// Generated dependencies: trecap_core_pkg, trecap_csr_pkg, trecap_packet_pkg, trecap_iface_pkg.

`default_nettype none

// T-RECAP Phase 2 CSR bank.
//
// This block owns the memory-mapped control/status register behavior. It does not own DDR record
// building, WRAP handling, Avalon/DDR writes, HPS software, Ethernet, or signal-processing
// arithmetic. Those are separate ownership layers.
//
// Bus timing model:
//   - csr_addr_i is a byte offset into the CSR window.
//   - All legal accesses are 32-bit aligned.
//   - csr_ready_o pulses in the same cycle as csr_valid_i.
//   - csr_rvalid_o/csr_rdata_o are registered and valid one cycle after an accepted read request.
//   - csr_error_o is registered and reports invalid read/write or rejected write requests.
module trecap_csr_bank
  import trecap_core_pkg::*;
  import trecap_csr_pkg::*;
  import trecap_packet_pkg::*;
  import trecap_iface_pkg::*;
  import trecap_build_pkg::*;
#(
    parameter int unsigned CSR_ADDR_W = 12,
    parameter logic [31:0] RING_SIZE_MIN_BYTES = 32'h0010_0000
) (
    input  logic                    clk,
    input  logic                    rst_n,
    input  logic                    external_transport_clear_i,

    input  logic                    csr_valid_i,
    input  logic                    csr_write_i,
    input  logic [CSR_ADDR_W-1:0]   csr_addr_i,
    input  logic [31:0]             csr_wdata_i,
    output logic                    csr_ready_o,
    output logic                    csr_rvalid_o,
    output logic [31:0]             csr_rdata_o,
    output logic                    csr_error_o,

    // Safe-boundary inputs for committed controls. These must already be synchronized to clk.
    input  logic                    frame_boundary_i,
    input  logic                    source_safe_boundary_i,
    input  logic                    ring_rd_commit_ready_i,

    // Actual source/transport state. The requested CSR source and the physical mux selection are
    // intentionally separate so software cannot re-enable telemetry during the one-cycle handoff.
    input  trecap_source_mode_e      actual_source_mode_i,
    input  logic                    source_transition_busy_i,
    input  logic                    transport_epoch_idle_i,

    // Replay admission/result feedback from the existing source/core and E2E owners.
    input  logic                    replay_start_ready_i,
    // Universal arbiter ownership, including KEY/manual admission before replay_active rises.
    input  logic                    replay_request_busy_i,
    input  logic                    replay_start_accept_pulse_i,
    input  logic                    replay_start_reject_pulse_i,
    input  logic                    replay_active_i,
    input  logic                    replay_path_busy_i,
    input  logic                    replay_path_done_i,
    input  logic                    replay_e2e_busy_i,
    input  logic                    replay_e2e_done_i,
    input  logic                    replay_error_i,
    input  logic                    replay_rearm_required_i,

    // Live observations and snapshot sources. A split-clock integration shall feed these through
    // explicit CDC/snapshot blocks before connecting this CSR bank.
    input  logic                    core_alive_i,
    input  logic [63:0]             ring_wr_ptr_i,
    input  logic [63:0]             core_frame_count_i,
    input  logic [63:0]             core_sample_count_i,

    input  logic                    writer_idle_i,
    input  logic                    writer_busy_i,
    input  logic                    writer_no_space_i,
    input  logic                    malformed_config_i,
    input  logic                    ring_full_i,
    input  logic                    packet_fifo_full_i,
    input  logic                    ddr_wait_i,
    input  logic                    writer_drop_active_i,
    input  logic                    ring_pointers_valid_i,

    input  logic [31:0]             dma_drop_count_i,
    input  logic [31:0]             dma_packet_count_i,
    input  logic [31:0]             packet_fifo_drop_count_i,
    input  logic [31:0]             overflow_flags_set_i,
    input  logic                    csr_command_reject_pulse_i,
    input  logic                    csr_adapter_reject_pulse_i,

    output trecap_hps_bridge_ctrl_t ctrl_o,
    output trecap_ring_config_t     ring_config_o,
    output logic [63:0]             ring_rd_committed_o,
    output logic                    ring_rd_commit_pending_o,

    output logic                    telemetry_soft_reset_pulse_o,
    output logic                    clear_metrics_pulse_o,
    output logic                    counter_clear_pulse_o,
    output logic                    replay_start_pulse_o,
    output logic                    replay_rearm_pulse_o,
    output logic                    thr2_apply_pulse_o,
    output logic                    source_mode_apply_pulse_o,
    output logic                    ring_config_commit_pulse_o,
    output logic                    ring_wr_snapshot_pulse_o,
    output logic                    ring_rd_commit_pulse_o,
    output logic                    core_count_snapshot_pulse_o,
    output logic [31:0]             clear_sticky_flags_w1c_o,

    output logic [31:0]             status_o,
    output logic [31:0]             dma_status_o,
    output logic [31:0]             overflow_flags_o,
    output logic [31:0]             csr_command_reject_count_o,
    output logic                    csr_reject_pulse_o,
    output logic                    malformed_config_o
);

    localparam int unsigned ADDR_PAD_W = 32 - CSR_ADDR_W;
    localparam logic [31:0] CONTROL_LEVEL_MASK =
        TCSR_CONTROL_TELEMETRY_ENABLE_MASK | TCSR_CONTROL_RING_WRITER_ENABLE_MASK;
    localparam logic [31:0] CONTROL_W1P_MASK =
        TCSR_CONTROL_TELEMETRY_SOFT_RESET_MASK | TCSR_CONTROL_CLEAR_METRICS_MASK;
    localparam logic [31:0] CONTROL_LEGAL_WRITE_MASK = CONTROL_LEVEL_MASK | CONTROL_W1P_MASK;
    localparam logic [31:0] PACKET_ENABLE_LEGAL_MASK =
        TCSR_PACKET_ENABLE_WAVE_EN_MASK |
        TCSR_PACKET_ENABLE_SPEC_EN_MASK |
        TCSR_PACKET_ENABLE_METRICS_EN_MASK |
        TCSR_PACKET_ENABLE_STATUS_EN_MASK;
    localparam logic [31:0] OVERFLOW_VALID_MASK = ~TCSR_OVERFLOW_FLAGS_RESERVED_31_10_MASK;
    localparam logic [TCSR_THR2_WIDTH_BITS-1:0] THR2_LO_MASK =
        {{(TCSR_THR2_WIDTH_BITS-32){1'b0}}, 32'hffff_ffff};
    localparam logic [TCSR_THR2_WIDTH_BITS-1:0] THR2_HI_MASK =
        {{(TCSR_THR2_WIDTH_BITS-32){1'b1}}, 32'h0000_0000};

    logic [31:0] csr_offset;
    logic        read_req;
    logic        write_req;
    logic        addr_aligned;
    logic        known_addr;
    logic        write_known;
    logic        write_reject;
    logic        write_accept;
    logic [31:0] write_reject_flags;

    logic telemetry_enable_q;
    logic ring_writer_enable_q;
    logic [31:0] packet_enable_q;
    logic [15:0] wave_decim_q;
    trecap_spec_mode_e spec_mode_q;
    logic [5:0] spec_shift_q;

    logic [63:0] ring_base_shadow_q;
    logic [31:0] ring_size_shadow_q;
    logic [63:0] ring_base_q;
    logic [31:0] ring_size_q;
    logic [31:0] ring_size_mask_q;
    logic        ring_configured_q;
    logic        malformed_config_q;

    logic [63:0] ring_wr_snap_q;
    logic [63:0] frame_count_snap_q;
    logic [63:0] sample_count_snap_q;

    logic [31:0] overflow_flags_q;
    logic [31:0] csr_command_reject_count_q;
    logic [31:0] status_comb;
    logic [31:0] dma_status_comb;
    logic [31:0] replay_status_comb;
    logic [31:0] read_data_comb;
    logic [31:0] overflow_set_comb;
    logic [31:0] clear_mask_comb;
    logic [1:0]  reject_increment_comb;

    logic                         thr2_shadow_we;
    logic [TCSR_THR2_WIDTH_BITS-1:0] thr2_shadow_wdata;
    logic [TCSR_THR2_WIDTH_BITS-1:0] thr2_shadow_wmask;
    logic                         thr2_commit_pulse;
    logic [TCSR_THR2_WIDTH_BITS-1:0] thr2_shadow;
    logic [TCSR_THR2_WIDTH_BITS-1:0] thr2_active;
    logic [TCSR_THR2_WIDTH_BITS-1:0] thr2_pending_value;
    logic                         thr2_pending;
    logic                         thr2_write_reject;
    logic                         thr2_commit_reject;

    logic                         source_shadow_we;
    logic [1:0]                   source_shadow_wdata;
    logic [1:0]                   source_shadow_wmask;
    logic                         source_commit_pulse;
    logic [1:0]                   source_shadow;
    logic [1:0]                   source_active;
    logic [1:0]                   source_pending_value;
    logic                         source_pending;
    logic                         source_write_reject;
    logic                         source_commit_reject;

    logic                         ring_rd_shadow_we;
    logic [63:0]                  ring_rd_shadow_wdata;
    logic [63:0]                  ring_rd_shadow_wmask;
    logic                         ring_rd_commit_pulse_int;
    logic [63:0]                  ring_rd_shadow;
    logic [63:0]                  ring_rd_active;
    logic [63:0]                  ring_rd_pending_value;
    logic                         ring_rd_pending;
    logic                         ring_rd_epoch_valid_q;
    logic                         ring_rd_write_reject;
    logic                         ring_rd_commit_reject;

    logic                         soft_reset_req;
    logic                         counter_clear_req;
    logic                         replay_start_req;
    logic                         replay_rearm_req;
    logic                         ring_config_commit_req;
    logic                         ring_rd_commit_value_legal;
    logic                         ring_rd_state_clear;

    logic                         source_actual_mismatch;
    logic                         source_transition_busy_comb;
    logic                         config_mutation_allowed;
    logic                         replay_request_pending_q;
    logic                         replay_last_accept_q;
    logic                         replay_last_reject_q;
    logic [15:0]                  replay_result_epoch_q;

    assign csr_ready_o = csr_valid_i;
    assign read_req = csr_valid_i && !csr_write_i;
    assign write_req = csr_valid_i && csr_write_i;
    assign addr_aligned = (csr_addr_i[1:0] == 2'b00);
    assign csr_offset = {{ADDR_PAD_W{1'b0}}, csr_addr_i};
    assign known_addr = csr_offset_known(csr_offset);
    assign write_known = csr_offset_write_known(csr_offset);
    assign write_accept = write_req && addr_aligned && write_known && !write_reject;

    function automatic bit csr_offset_known(input logic [31:0] offset);
        unique case (offset)
            TCSR_ID_OFFSET, TCSR_VERSION_OFFSET, TCSR_CONTROL_OFFSET, TCSR_STATUS_OFFSET,
            TCSR_THR2_LO_OFFSET, TCSR_THR2_HI_OFFSET, TCSR_THR2_COMMIT_OFFSET,
            TCSR_PACKET_ENABLE_OFFSET, TCSR_WAVE_DECIM_OFFSET, TCSR_SPEC_MODE_OFFSET,
            TCSR_SPEC_SHIFT_OFFSET, TCSR_SOURCE_MODE_SHADOW_OFFSET,
            TCSR_SOURCE_MODE_COMMIT_OFFSET, TCSR_RING_BASE_LO_OFFSET,
            TCSR_RING_BASE_HI_OFFSET, TCSR_RING_SIZE_BYTES_OFFSET,
            TCSR_RING_CONFIG_COMMIT_OFFSET, TCSR_RING_WR_SNAPSHOT_OFFSET,
            TCSR_RING_WR_LO_SNAP_OFFSET, TCSR_RING_WR_HI_SNAP_OFFSET,
            TCSR_RING_RD_LO_SHADOW_OFFSET, TCSR_RING_RD_HI_SHADOW_OFFSET,
            TCSR_RING_RD_COMMIT_OFFSET, TCSR_DMA_DROP_COUNT_OFFSET,
            TCSR_DMA_PACKET_COUNT_OFFSET, TCSR_DMA_STATUS_OFFSET,
            TCSR_CORE_COUNT_SNAPSHOT_OFFSET, TCSR_FRAME_COUNT_SNAP_LO_OFFSET,
            TCSR_FRAME_COUNT_SNAP_HI_OFFSET, TCSR_SAMPLE_COUNT_SNAP_LO_OFFSET,
            TCSR_SAMPLE_COUNT_SNAP_HI_OFFSET, TCSR_OVERFLOW_FLAGS_OFFSET,
            TCSR_CLEAR_STICKY_FLAGS_OFFSET, TCSR_CSR_COMMAND_REJECT_COUNT_OFFSET,
            TCSR_PACKET_FIFO_DROP_COUNT_OFFSET, TCSR_COUNTER_CLEAR_OFFSET,
            TCSR_REPLAY_CONTROL_OFFSET, TCSR_REPLAY_STATUS_OFFSET: begin
                return 1'b1;
            end
            default: begin
                return 1'b0;
            end
        endcase
    endfunction : csr_offset_known

    function automatic bit csr_offset_write_known(input logic [31:0] offset);
        unique case (offset)
            TCSR_CONTROL_OFFSET, TCSR_THR2_LO_OFFSET, TCSR_THR2_HI_OFFSET,
            TCSR_THR2_COMMIT_OFFSET, TCSR_PACKET_ENABLE_OFFSET, TCSR_WAVE_DECIM_OFFSET,
            TCSR_SPEC_MODE_OFFSET, TCSR_SPEC_SHIFT_OFFSET, TCSR_SOURCE_MODE_SHADOW_OFFSET,
            TCSR_SOURCE_MODE_COMMIT_OFFSET, TCSR_RING_BASE_LO_OFFSET,
            TCSR_RING_BASE_HI_OFFSET, TCSR_RING_SIZE_BYTES_OFFSET,
            TCSR_RING_CONFIG_COMMIT_OFFSET, TCSR_RING_WR_SNAPSHOT_OFFSET,
            TCSR_RING_RD_LO_SHADOW_OFFSET, TCSR_RING_RD_HI_SHADOW_OFFSET,
            TCSR_RING_RD_COMMIT_OFFSET, TCSR_CORE_COUNT_SNAPSHOT_OFFSET,
            TCSR_CLEAR_STICKY_FLAGS_OFFSET, TCSR_COUNTER_CLEAR_OFFSET,
            TCSR_REPLAY_CONTROL_OFFSET: begin
                return 1'b1;
            end
            default: begin
                return 1'b0;
            end
        endcase
    endfunction : csr_offset_write_known

    function automatic bit power_of_two32(input logic [31:0] value);
        return (value != 32'd0) && ((value & (value - 32'd1)) == 32'd0);
    endfunction : power_of_two32

    function automatic bit packet_enable_legal(input logic [31:0] value);
        return ((value & ~PACKET_ENABLE_LEGAL_MASK) == 32'h0000_0000);
    endfunction : packet_enable_legal

    function automatic bit spec_mode_legal(input logic [31:0] value);
        return (value == TCSR_SPEC_MODE_SPEC_DISABLED) ||
               (value == TCSR_SPEC_MODE_SPEC64) ||
               (value == TCSR_SPEC_MODE_SPEC129);
    endfunction : spec_mode_legal

    function automatic bit source_mode_legal(input logic [31:0] value);
        return (value == TCSR_SOURCE_MODE_BRAM_REPLAY) ||
               (value == TCSR_SOURCE_MODE_ADC_LIVE) ||
               (value == TCSR_SOURCE_MODE_AUDIO_WRAPPER) ||
               (value == TCSR_SOURCE_MODE_DIAGNOSTIC);
    endfunction : source_mode_legal

    function automatic bit w1p_value_legal(input logic [31:0] value);
        return ((value & 32'hffff_fffe) == 32'h0000_0000);
    endfunction : w1p_value_legal

    function automatic bit ring_config_legal(input logic [63:0] base_addr,
                                             input logic [31:0] size_bytes);
        return (base_addr[5:0] == 6'd0) &&
               ((size_bytes & (TCSR_RING_ALIGNMENT_BYTES - 1)) == 32'd0) &&
               power_of_two32(size_bytes) &&
               (size_bytes >= RING_SIZE_MIN_BYTES);
    endfunction : ring_config_legal

    function automatic bit ring_rd_value_legal(input logic [63:0] value);
        if ((value & (TCSR_RING_ALIGNMENT_BYTES - 1)) != 64'd0) begin
            return 1'b0;
        end
        if (value > ring_wr_ptr_i) begin
            return 1'b0;
        end
        if ((ring_wr_ptr_i - value) > {32'd0, ring_size_q}) begin
            return 1'b0;
        end
        if (!ring_rd_epoch_valid_q) begin
            return value == 64'd0;
        end
        if (!ring_pointers_valid_i) begin
            return 1'b0;
        end
        return value >= ring_rd_active;
    endfunction : ring_rd_value_legal

    function automatic trecap_spec_mode_e spec_mode_from_u2(input logic [1:0] value);
        unique case (value)
            2'd1: begin
                return TSPEC_SPEC64;
            end
            2'd2: begin
                return TSPEC_SPEC129;
            end
            default: begin
                return TSPEC_DISABLED;
            end
        endcase
    endfunction : spec_mode_from_u2

    function automatic trecap_source_mode_e source_mode_from_u2(input logic [1:0] value);
        unique case (value)
            2'd1: begin
                return TSRC_ADC_LIVE;
            end
            2'd2: begin
                return TSRC_AUDIO_WRAPPER;
            end
            2'd3: begin
                return TSRC_DIAGNOSTIC;
            end
            default: begin
                return TSRC_BRAM_REPLAY;
            end
        endcase
    endfunction : source_mode_from_u2

    assign source_actual_mismatch = (source_active != actual_source_mode_i);
    assign source_transition_busy_comb = source_transition_busy_i || source_pending ||
                                         source_actual_mismatch;
    // Live formatter/source controls may change only after HPS has disabled both producers and
    // drained the complete transport/replay epoch. THR2 keeps its independent frame-boundary
    // shadow/commit policy and is intentionally not included in this gate.
    assign config_mutation_allowed = !telemetry_enable_q && !ring_writer_enable_q &&
                                     transport_epoch_idle_i &&
                                     !replay_request_pending_q && !replay_request_busy_i &&
                                     !replay_active_i &&
                                     !replay_path_busy_i && !replay_e2e_busy_i &&
                                     !source_transition_busy_comb;

    always_comb begin
        status_comb = 32'h0000_0000;
        status_comb[TCSR_STATUS_TELEMETRY_ENABLED_LSB] = telemetry_enable_q;
        status_comb[TCSR_STATUS_RING_WRITER_ENABLED_LSB] = ring_writer_enable_q;
        status_comb[TCSR_STATUS_RING_CONFIGURED_LSB] = ring_configured_q;
        status_comb[TCSR_STATUS_WRITER_BUSY_LSB] = writer_busy_i;
        status_comb[TCSR_STATUS_CORE_ALIVE_LSB] = core_alive_i;
        status_comb[TCSR_STATUS_MALFORMED_CONFIG_LSB] = malformed_config_q | malformed_config_i;
        status_comb[TCSR_STATUS_RING_FULL_LSB] = ring_full_i;
        status_comb[TCSR_STATUS_PACKET_FIFO_FULL_LSB] = packet_fifo_full_i;
        status_comb[TCSR_STATUS_THR2_COMMIT_PENDING_LSB] = thr2_pending;
        status_comb[TCSR_STATUS_SOURCE_COMMIT_PENDING_LSB] = source_pending ||
                                                             source_actual_mismatch;
        status_comb[TCSR_STATUS_ACTUAL_SOURCE_MODE_MSB:
                    TCSR_STATUS_ACTUAL_SOURCE_MODE_LSB] = actual_source_mode_i;
        status_comb[TCSR_STATUS_TRANSPORT_EPOCH_IDLE_LSB] = transport_epoch_idle_i;
        status_comb[TCSR_STATUS_SOURCE_TRANSITION_BUSY_LSB] = source_transition_busy_comb;
    end

    always_comb begin
        replay_status_comb = 32'h0000_0000;
        replay_status_comb[TCSR_REPLAY_STATUS_PENDING_LSB] = replay_request_pending_q;
        replay_status_comb[TCSR_REPLAY_STATUS_LAST_ACCEPT_LSB] = replay_last_accept_q;
        replay_status_comb[TCSR_REPLAY_STATUS_LAST_REJECT_LSB] = replay_last_reject_q;
        replay_status_comb[TCSR_REPLAY_STATUS_START_READY_LSB] = replay_start_ready_i &&
                                                                 !replay_request_pending_q &&
                                                                 !replay_request_busy_i &&
                                                                 !replay_rearm_required_i;
        replay_status_comb[TCSR_REPLAY_STATUS_REPLAY_ACTIVE_LSB] = replay_active_i;
        replay_status_comb[TCSR_REPLAY_STATUS_REPLAY_PATH_BUSY_LSB] = replay_path_busy_i;
        replay_status_comb[TCSR_REPLAY_STATUS_REPLAY_PATH_DONE_LSB] = replay_path_done_i;
        replay_status_comb[TCSR_REPLAY_STATUS_E2E_BUSY_LSB] = replay_e2e_busy_i;
        replay_status_comb[TCSR_REPLAY_STATUS_E2E_DONE_LSB] = replay_e2e_done_i;
        replay_status_comb[TCSR_REPLAY_STATUS_ERROR_LSB] = replay_error_i;
        replay_status_comb[TCSR_REPLAY_STATUS_REARM_REQUIRED_LSB] = replay_rearm_required_i;
        replay_status_comb[TCSR_REPLAY_STATUS_RESULT_EPOCH_MSB:
                           TCSR_REPLAY_STATUS_RESULT_EPOCH_LSB] = replay_result_epoch_q;
    end

    always_comb begin
        dma_status_comb = 32'h0000_0000;
        dma_status_comb[TCSR_DMA_STATUS_WRITER_IDLE_LSB] = writer_idle_i;
        dma_status_comb[TCSR_DMA_STATUS_WRITER_BUSY_LSB] = writer_busy_i;
        dma_status_comb[TCSR_DMA_STATUS_NO_SPACE_LSB] = writer_no_space_i;
        dma_status_comb[TCSR_DMA_STATUS_MALFORMED_CONFIG_LSB] = malformed_config_q | malformed_config_i;
        dma_status_comb[TCSR_DMA_STATUS_RING_FULL_LSB] = ring_full_i;
        dma_status_comb[TCSR_DMA_STATUS_PACKET_FIFO_FULL_LSB] = packet_fifo_full_i;
        dma_status_comb[TCSR_DMA_STATUS_DDR_WAIT_LSB] = ddr_wait_i;
        dma_status_comb[TCSR_DMA_STATUS_DROP_ACTIVE_LSB] = writer_drop_active_i;
    end

    always_comb begin
        read_data_comb = 32'h0000_0000;
        unique case (csr_offset)
            TCSR_ID_OFFSET: begin
                read_data_comb = TCSR_ID_VALUE;
            end
            TCSR_VERSION_OFFSET: begin
                read_data_comb = TCSR_VERSION_VALUE;
            end
            TCSR_CONTROL_OFFSET: begin
                read_data_comb = (telemetry_enable_q ? TCSR_CONTROL_TELEMETRY_ENABLE_MASK : 32'd0) |
                                 (ring_writer_enable_q ? TCSR_CONTROL_RING_WRITER_ENABLE_MASK : 32'd0);
            end
            TCSR_STATUS_OFFSET: begin
                read_data_comb = status_comb;
            end
            TCSR_THR2_LO_OFFSET: begin
                read_data_comb = thr2_shadow[31:0];
            end
            TCSR_THR2_HI_OFFSET: begin
                read_data_comb = {8'd0, thr2_shadow[55:32]};
            end
            TCSR_PACKET_ENABLE_OFFSET: begin
                read_data_comb = packet_enable_q;
            end
            TCSR_WAVE_DECIM_OFFSET: begin
                read_data_comb = {16'd0, wave_decim_q};
            end
            TCSR_SPEC_MODE_OFFSET: begin
                read_data_comb = {30'd0, spec_mode_q};
            end
            TCSR_SPEC_SHIFT_OFFSET: begin
                read_data_comb = {26'd0, spec_shift_q};
            end
            TCSR_SOURCE_MODE_SHADOW_OFFSET: begin
                read_data_comb = {30'd0, source_shadow};
            end
            TCSR_RING_BASE_LO_OFFSET: begin
                read_data_comb = ring_base_shadow_q[31:0];
            end
            TCSR_RING_BASE_HI_OFFSET: begin
                read_data_comb = ring_base_shadow_q[63:32];
            end
            TCSR_RING_SIZE_BYTES_OFFSET: begin
                read_data_comb = ring_size_shadow_q;
            end
            TCSR_RING_WR_LO_SNAP_OFFSET: begin
                read_data_comb = ring_wr_snap_q[31:0];
            end
            TCSR_RING_WR_HI_SNAP_OFFSET: begin
                read_data_comb = ring_wr_snap_q[63:32];
            end
            TCSR_RING_RD_LO_SHADOW_OFFSET: begin
                read_data_comb = ring_rd_shadow[31:0];
            end
            TCSR_RING_RD_HI_SHADOW_OFFSET: begin
                read_data_comb = ring_rd_shadow[63:32];
            end
            TCSR_DMA_DROP_COUNT_OFFSET: begin
                read_data_comb = dma_drop_count_i;
            end
            TCSR_DMA_PACKET_COUNT_OFFSET: begin
                read_data_comb = dma_packet_count_i;
            end
            TCSR_DMA_STATUS_OFFSET: begin
                read_data_comb = dma_status_comb;
            end
            TCSR_FRAME_COUNT_SNAP_LO_OFFSET: begin
                read_data_comb = frame_count_snap_q[31:0];
            end
            TCSR_FRAME_COUNT_SNAP_HI_OFFSET: begin
                read_data_comb = frame_count_snap_q[63:32];
            end
            TCSR_SAMPLE_COUNT_SNAP_LO_OFFSET: begin
                read_data_comb = sample_count_snap_q[31:0];
            end
            TCSR_SAMPLE_COUNT_SNAP_HI_OFFSET: begin
                read_data_comb = sample_count_snap_q[63:32];
            end
            TCSR_OVERFLOW_FLAGS_OFFSET: begin
                read_data_comb = overflow_flags_q;
            end
            TCSR_CSR_COMMAND_REJECT_COUNT_OFFSET: begin
                read_data_comb = csr_command_reject_count_q;
            end
            TCSR_PACKET_FIFO_DROP_COUNT_OFFSET: begin
                read_data_comb = packet_fifo_drop_count_i;
            end
            TCSR_REPLAY_STATUS_OFFSET: begin
                read_data_comb = replay_status_comb;
            end
            default: begin
                read_data_comb = 32'h0000_0000;
            end
        endcase
    end

    always_comb begin
        write_reject = 1'b0;
        write_reject_flags = 32'h0000_0000;

        if (write_req) begin
            // An integration clear owns the CSR ring epoch. Reject concurrent writes so a
            // transaction cannot report success while its configuration/Rd update is discarded,
            // or emit a delayed commit pulse after the clear has invalidated the epoch.
            if (external_transport_clear_i) begin
                write_reject = 1'b1;
                write_reject_flags = TCSR_OVERFLOW_FLAGS_ILLEGAL_COMMAND_MASK;
            end else if (!addr_aligned || !write_known) begin
                write_reject = 1'b1;
                write_reject_flags = TCSR_OVERFLOW_FLAGS_ILLEGAL_COMMAND_MASK;
            end else begin
                unique case (csr_offset)
                    TCSR_CONTROL_OFFSET: begin
                        if ((csr_wdata_i & ~CONTROL_LEGAL_WRITE_MASK) != 32'd0) begin
                            write_reject = 1'b1;
                            write_reject_flags = TCSR_OVERFLOW_FLAGS_ILLEGAL_COMMAND_MASK;
                        end else if (((csr_wdata_i & CONTROL_W1P_MASK) != 32'd0) &&
                                     ((csr_wdata_i & CONTROL_LEVEL_MASK) != 32'd0)) begin
                            write_reject = 1'b1;
                            write_reject_flags = TCSR_OVERFLOW_FLAGS_ILLEGAL_COMMAND_MASK;
                        end else if (((csr_wdata_i & TCSR_CONTROL_TELEMETRY_SOFT_RESET_MASK) !=
                                      32'd0) &&
                                     (telemetry_enable_q || ring_writer_enable_q ||
                                      !writer_idle_i)) begin
                            write_reject = 1'b1;
                            write_reject_flags = TCSR_OVERFLOW_FLAGS_ILLEGAL_COMMAND_MASK;
                        end else if (((csr_wdata_i & CONTROL_LEVEL_MASK) != 32'd0) &&
                                     (!config_mutation_allowed || !ring_configured_q ||
                                      !ring_rd_epoch_valid_q || !ring_pointers_valid_i)) begin
                            write_reject = 1'b1;
                            write_reject_flags = TCSR_OVERFLOW_FLAGS_ILLEGAL_COMMAND_MASK;
                        end
                    end
                    TCSR_THR2_LO_OFFSET: begin
                        if (thr2_pending) begin
                            write_reject = 1'b1;
                            write_reject_flags = TCSR_OVERFLOW_FLAGS_ILLEGAL_COMMAND_MASK;
                        end
                    end
                    TCSR_THR2_HI_OFFSET: begin
                        if ((csr_wdata_i[31:24] != 8'd0) || thr2_pending) begin
                            write_reject = 1'b1;
                            write_reject_flags = TCSR_OVERFLOW_FLAGS_ILLEGAL_COMMAND_MASK |
                                                 TCSR_OVERFLOW_FLAGS_THRESHOLD_RANGE_ERROR_MASK;
                        end
                    end
                    TCSR_THR2_COMMIT_OFFSET: begin
                        if (!w1p_value_legal(csr_wdata_i) || (csr_wdata_i[0] && thr2_pending)) begin
                            write_reject = 1'b1;
                            write_reject_flags = TCSR_OVERFLOW_FLAGS_ILLEGAL_COMMAND_MASK;
                        end
                    end
                    TCSR_PACKET_ENABLE_OFFSET: begin
                        if (!config_mutation_allowed || !packet_enable_legal(csr_wdata_i)) begin
                            write_reject = 1'b1;
                            write_reject_flags = TCSR_OVERFLOW_FLAGS_ILLEGAL_COMMAND_MASK;
                        end
                    end
                    TCSR_WAVE_DECIM_OFFSET: begin
                        if (!config_mutation_allowed ||
                            (csr_wdata_i < TCSR_WAVE_DECIM_MIN) ||
                            (csr_wdata_i > TCSR_WAVE_DECIM_MAX)) begin
                            write_reject = 1'b1;
                            write_reject_flags = TCSR_OVERFLOW_FLAGS_ILLEGAL_COMMAND_MASK;
                        end
                    end
                    TCSR_SPEC_MODE_OFFSET: begin
                        if (!config_mutation_allowed || !spec_mode_legal(csr_wdata_i)) begin
                            write_reject = 1'b1;
                            write_reject_flags = TCSR_OVERFLOW_FLAGS_ILLEGAL_COMMAND_MASK;
                        end
                    end
                    TCSR_SPEC_SHIFT_OFFSET: begin
                        if (!config_mutation_allowed || csr_wdata_i > TCSR_SPEC_SHIFT_MAX) begin
                            write_reject = 1'b1;
                            write_reject_flags = TCSR_OVERFLOW_FLAGS_ILLEGAL_COMMAND_MASK;
                        end
                    end
                    TCSR_SOURCE_MODE_SHADOW_OFFSET: begin
                        if (!config_mutation_allowed || source_pending ||
                            !source_mode_legal(csr_wdata_i)) begin
                            write_reject = 1'b1;
                            write_reject_flags = TCSR_OVERFLOW_FLAGS_ILLEGAL_COMMAND_MASK |
                                                 TCSR_OVERFLOW_FLAGS_SOURCE_MODE_ERROR_MASK;
                        end
                    end
                    TCSR_SOURCE_MODE_COMMIT_OFFSET: begin
                        if (!config_mutation_allowed || !w1p_value_legal(csr_wdata_i) ||
                            (csr_wdata_i[0] && source_pending)) begin
                            write_reject = 1'b1;
                            write_reject_flags = TCSR_OVERFLOW_FLAGS_ILLEGAL_COMMAND_MASK |
                                                 TCSR_OVERFLOW_FLAGS_SOURCE_MODE_ERROR_MASK;
                        end
                    end
                    TCSR_RING_BASE_LO_OFFSET,
                    TCSR_RING_BASE_HI_OFFSET,
                    TCSR_RING_SIZE_BYTES_OFFSET: begin
                        if (telemetry_enable_q || ring_writer_enable_q || !writer_idle_i) begin
                            write_reject = 1'b1;
                            write_reject_flags = TCSR_OVERFLOW_FLAGS_ILLEGAL_COMMAND_MASK;
                        end
                    end
                    TCSR_RING_CONFIG_COMMIT_OFFSET: begin
                        if (!w1p_value_legal(csr_wdata_i)) begin
                            write_reject = 1'b1;
                            write_reject_flags = TCSR_OVERFLOW_FLAGS_ILLEGAL_COMMAND_MASK;
                        end else if (csr_wdata_i[0] &&
                                     (telemetry_enable_q || ring_writer_enable_q ||
                                      !writer_idle_i ||
                                      !ring_config_legal(ring_base_shadow_q, ring_size_shadow_q))) begin
                            write_reject = 1'b1;
                            write_reject_flags = TCSR_OVERFLOW_FLAGS_ILLEGAL_COMMAND_MASK;
                        end
                    end
                    TCSR_RING_WR_SNAPSHOT_OFFSET,
                    TCSR_CORE_COUNT_SNAPSHOT_OFFSET: begin
                        if (!w1p_value_legal(csr_wdata_i)) begin
                            write_reject = 1'b1;
                            write_reject_flags = TCSR_OVERFLOW_FLAGS_ILLEGAL_COMMAND_MASK;
                        end
                    end
                    TCSR_RING_RD_COMMIT_OFFSET: begin
                        if (!w1p_value_legal(csr_wdata_i) ||
                            (csr_wdata_i[0] && (!ring_configured_q || !ring_rd_commit_ready_i ||
                                                ring_rd_pending ||
                                                !ring_rd_commit_value_legal))) begin
                            write_reject = 1'b1;
                            write_reject_flags = TCSR_OVERFLOW_FLAGS_ILLEGAL_COMMAND_MASK;
                        end
                    end
                    TCSR_COUNTER_CLEAR_OFFSET: begin
                        if ((csr_wdata_i & TCSR_COUNTER_CLEAR_RESERVED_31_1_MASK) != 32'd0) begin
                            write_reject = 1'b1;
                            write_reject_flags = TCSR_OVERFLOW_FLAGS_ILLEGAL_COMMAND_MASK;
                        end
                    end
                    TCSR_REPLAY_CONTROL_OFFSET: begin
                        if ((csr_wdata_i & TCSR_REPLAY_CONTROL_RESERVED_31_2_MASK) != 32'd0 ||
                            ((csr_wdata_i & TCSR_REPLAY_CONTROL_START_MASK) != 32'd0 &&
                             (csr_wdata_i & TCSR_REPLAY_CONTROL_REARM_MASK) != 32'd0)) begin
                            write_reject = 1'b1;
                            write_reject_flags = TCSR_OVERFLOW_FLAGS_ILLEGAL_COMMAND_MASK;
                        end else if (csr_wdata_i[TCSR_REPLAY_CONTROL_START_LSB] &&
                                     replay_request_pending_q) begin
                            // Never manufacture a second raw pulse while the retained result owner
                            // is still waiting for admission feedback from the first request.
                            write_reject = 1'b1;
                            write_reject_flags = TCSR_OVERFLOW_FLAGS_ILLEGAL_COMMAND_MASK;
                        end else if (csr_wdata_i[TCSR_REPLAY_CONTROL_REARM_LSB] &&
                                     (replay_request_pending_q || replay_request_busy_i ||
                                      replay_active_i ||
                                      replay_path_busy_i || replay_e2e_busy_i ||
                                      !transport_epoch_idle_i ||
                                      !replay_rearm_required_i)) begin
                            // REARM is a quiescent failed-epoch operation, not a mid-run abort.
                            write_reject = 1'b1;
                            write_reject_flags = TCSR_OVERFLOW_FLAGS_ILLEGAL_COMMAND_MASK;
                        end
                    end
                    default: begin
                        write_reject = 1'b0;
                        write_reject_flags = 32'h0000_0000;
                    end
                endcase
            end
        end
    end

    assign soft_reset_req = write_accept &&
                            (csr_offset == TCSR_CONTROL_OFFSET) &&
                            csr_wdata_i[TCSR_CONTROL_TELEMETRY_SOFT_RESET_LSB];
    assign counter_clear_req = write_accept &&
                               (csr_offset == TCSR_COUNTER_CLEAR_OFFSET) &&
                               csr_wdata_i[TCSR_COUNTER_CLEAR_TRANSPORT_COUNTERS_LSB];
    assign replay_start_req = write_accept &&
                              (csr_offset == TCSR_REPLAY_CONTROL_OFFSET) &&
                              csr_wdata_i[TCSR_REPLAY_CONTROL_START_LSB];
    assign replay_rearm_req = write_accept &&
                              (csr_offset == TCSR_REPLAY_CONTROL_OFFSET) &&
                              csr_wdata_i[TCSR_REPLAY_CONTROL_REARM_LSB];
    assign ring_config_commit_req = write_accept &&
                                    (csr_offset == TCSR_RING_CONFIG_COMMIT_OFFSET) &&
                                    csr_wdata_i[0];

    assign thr2_shadow_we = write_accept &&
                            ((csr_offset == TCSR_THR2_LO_OFFSET) ||
                             (csr_offset == TCSR_THR2_HI_OFFSET));
    assign thr2_shadow_wdata = (csr_offset == TCSR_THR2_HI_OFFSET) ?
                               {csr_wdata_i[23:0], 32'd0} :
                               {{(TCSR_THR2_WIDTH_BITS-32){1'b0}}, csr_wdata_i};
    assign thr2_shadow_wmask = (csr_offset == TCSR_THR2_HI_OFFSET) ? THR2_HI_MASK : THR2_LO_MASK;
    assign thr2_commit_pulse = write_accept &&
                               (csr_offset == TCSR_THR2_COMMIT_OFFSET) && csr_wdata_i[0];

    assign source_shadow_we = write_accept && (csr_offset == TCSR_SOURCE_MODE_SHADOW_OFFSET);
    assign source_shadow_wdata = csr_wdata_i[1:0];
    assign source_shadow_wmask = 2'b11;
    assign source_commit_pulse = write_accept &&
                                 (csr_offset == TCSR_SOURCE_MODE_COMMIT_OFFSET) && csr_wdata_i[0];

    assign ring_rd_shadow_we = write_accept &&
                               ((csr_offset == TCSR_RING_RD_LO_SHADOW_OFFSET) ||
                                (csr_offset == TCSR_RING_RD_HI_SHADOW_OFFSET));
    assign ring_rd_shadow_wdata = (csr_offset == TCSR_RING_RD_HI_SHADOW_OFFSET) ?
                                  {csr_wdata_i, 32'd0} :
                                  {32'd0, csr_wdata_i};
    assign ring_rd_shadow_wmask = (csr_offset == TCSR_RING_RD_HI_SHADOW_OFFSET) ?
                                  64'hffff_ffff_0000_0000 :
                                  64'h0000_0000_ffff_ffff;
    assign ring_rd_commit_pulse_int = write_accept &&
                                      (csr_offset == TCSR_RING_RD_COMMIT_OFFSET) && csr_wdata_i[0];
    assign ring_rd_commit_value_legal = ring_rd_value_legal(ring_rd_shadow);
    assign ring_rd_state_clear = soft_reset_req || external_transport_clear_i ||
                                 ring_config_commit_req;

    trecap_csr_shadow_commit #(
        .WIDTH(TCSR_THR2_WIDTH_BITS),
        .RESET_VALUE({TCSR_THR2_WIDTH_BITS{1'b0}}),
        .APPLY_ON_SAFE_BOUNDARY(1'b1),
        .REJECT_WRITES_WHILE_PENDING(1'b1)
    ) u_thr2_commit (
        .clk(clk),
        .rst_n(rst_n),
        .clear_i(soft_reset_req),
        .shadow_we_i(thr2_shadow_we),
        .shadow_wdata_i(thr2_shadow_wdata),
        .shadow_wmask_i(thr2_shadow_wmask),
        .commit_pulse_i(thr2_commit_pulse),
        .safe_boundary_i(frame_boundary_i),
        .commit_allowed_i(1'b1),
        .shadow_value_valid_i(1'b1),
        .shadow_value_o(thr2_shadow),
        .active_value_o(thr2_active),
        .pending_value_o(thr2_pending_value),
        .pending_o(thr2_pending),
        .shadow_accept_pulse_o(),
        .shadow_reject_pulse_o(thr2_write_reject),
        .commit_accept_pulse_o(),
        .commit_reject_pulse_o(thr2_commit_reject),
        .active_update_pulse_o(thr2_apply_pulse_o)
    );

    trecap_csr_shadow_commit #(
        .WIDTH(2),
        .RESET_VALUE(2'd0),
        .APPLY_ON_SAFE_BOUNDARY(1'b1),
        .REJECT_WRITES_WHILE_PENDING(1'b1)
    ) u_source_commit (
        .clk(clk),
        .rst_n(rst_n),
        .clear_i(soft_reset_req),
        .shadow_we_i(source_shadow_we),
        .shadow_wdata_i(source_shadow_wdata),
        .shadow_wmask_i(source_shadow_wmask),
        .commit_pulse_i(source_commit_pulse),
        .safe_boundary_i(source_safe_boundary_i),
        .commit_allowed_i(1'b1),
        .shadow_value_valid_i(1'b1),
        .shadow_value_o(source_shadow),
        .active_value_o(source_active),
        .pending_value_o(source_pending_value),
        .pending_o(source_pending),
        .shadow_accept_pulse_o(),
        .shadow_reject_pulse_o(source_write_reject),
        .commit_accept_pulse_o(),
        .commit_reject_pulse_o(source_commit_reject),
        .active_update_pulse_o(source_mode_apply_pulse_o)
    );

    trecap_csr_shadow_commit #(
        .WIDTH(64),
        .RESET_VALUE(64'd0),
        .APPLY_ON_SAFE_BOUNDARY(1'b0),
        .REJECT_WRITES_WHILE_PENDING(1'b1),
        .CLEAR_VALUES_ON_CLEAR(1'b1)
    ) u_ring_rd_commit (
        .clk(clk),
        .rst_n(rst_n),
        .clear_i(ring_rd_state_clear),
        .shadow_we_i(ring_rd_shadow_we),
        .shadow_wdata_i(ring_rd_shadow_wdata),
        .shadow_wmask_i(ring_rd_shadow_wmask),
        .commit_pulse_i(ring_rd_commit_pulse_int),
        .safe_boundary_i(1'b1),
        .commit_allowed_i(ring_rd_commit_ready_i && ring_configured_q),
        .shadow_value_valid_i(1'b1),
        .shadow_value_o(ring_rd_shadow),
        .active_value_o(ring_rd_active),
        .pending_value_o(ring_rd_pending_value),
        .pending_o(ring_rd_pending),
        .shadow_accept_pulse_o(),
        .shadow_reject_pulse_o(ring_rd_write_reject),
        .commit_accept_pulse_o(),
        .commit_reject_pulse_o(ring_rd_commit_reject),
        .active_update_pulse_o(ring_rd_commit_pulse_o)
    );

    always_comb begin
        overflow_set_comb = overflow_flags_set_i & OVERFLOW_VALID_MASK;
        if (write_reject) begin
            overflow_set_comb |= write_reject_flags;
        end
        if (thr2_write_reject || thr2_commit_reject) begin
            overflow_set_comb |= TCSR_OVERFLOW_FLAGS_ILLEGAL_COMMAND_MASK |
                                 TCSR_OVERFLOW_FLAGS_THRESHOLD_RANGE_ERROR_MASK;
        end
        if (source_write_reject || source_commit_reject) begin
            overflow_set_comb |= TCSR_OVERFLOW_FLAGS_ILLEGAL_COMMAND_MASK |
                                 TCSR_OVERFLOW_FLAGS_SOURCE_MODE_ERROR_MASK;
        end
        if (ring_rd_write_reject || ring_rd_commit_reject || csr_command_reject_pulse_i ||
            csr_adapter_reject_pulse_i) begin
            overflow_set_comb |= TCSR_OVERFLOW_FLAGS_ILLEGAL_COMMAND_MASK;
        end
    end

    always_comb begin
        clear_mask_comb = 32'h0000_0000;
        if (write_accept && (csr_offset == TCSR_CLEAR_STICKY_FLAGS_OFFSET)) begin
            clear_mask_comb = csr_wdata_i & OVERFLOW_VALID_MASK;
        end
    end

    always_comb begin
        reject_increment_comb = 2'd0;
        if (write_reject) begin
            reject_increment_comb = reject_increment_comb + 2'd1;
        end
        if (thr2_write_reject || thr2_commit_reject || source_write_reject ||
            source_commit_reject || ring_rd_write_reject || ring_rd_commit_reject ||
            csr_command_reject_pulse_i) begin
            reject_increment_comb = reject_increment_comb + 2'd1;
        end
        // Keep the serialized adapter-local rejection as a separate event so it cannot be
        // coalesced with an unrelated external/writer rejection in the same cycle.
        if (csr_adapter_reject_pulse_i) begin
            reject_increment_comb = reject_increment_comb + 2'd1;
        end
    end

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            csr_rvalid_o <= 1'b0;
            csr_rdata_o <= 32'd0;
            csr_error_o <= 1'b0;
            telemetry_enable_q <= 1'b0;
            ring_writer_enable_q <= 1'b0;
            packet_enable_q <= TCSR_PACKET_ENABLE_RESET;
            wave_decim_q <= TCSR_WAVE_DECIM_RESET[15:0];
            spec_mode_q <= TSPEC_DISABLED;
            spec_shift_q <= TCSR_SPEC_SHIFT_RESET[5:0];
            ring_base_shadow_q <= 64'd0;
            ring_size_shadow_q <= TCSR_RING_SIZE_BYTES_RESET;
            ring_base_q <= 64'd0;
            ring_size_q <= 32'd0;
            ring_size_mask_q <= 32'd0;
            ring_configured_q <= 1'b0;
            malformed_config_q <= 1'b0;
            ring_rd_epoch_valid_q <= 1'b0;
            ring_wr_snap_q <= 64'd0;
            frame_count_snap_q <= 64'd0;
            sample_count_snap_q <= 64'd0;
            overflow_flags_q <= TCSR_OVERFLOW_FLAGS_RESET;
            csr_command_reject_count_q <= TCSR_CSR_COMMAND_REJECT_COUNT_RESET;
            telemetry_soft_reset_pulse_o <= 1'b0;
            clear_metrics_pulse_o <= 1'b0;
            counter_clear_pulse_o <= 1'b0;
            replay_start_pulse_o <= 1'b0;
            replay_rearm_pulse_o <= 1'b0;
            ring_config_commit_pulse_o <= 1'b0;
            ring_wr_snapshot_pulse_o <= 1'b0;
            core_count_snapshot_pulse_o <= 1'b0;
            clear_sticky_flags_w1c_o <= 32'd0;
            replay_request_pending_q <= 1'b0;
            replay_last_accept_q <= 1'b0;
            replay_last_reject_q <= 1'b0;
            replay_result_epoch_q <= 16'd0;
        end else begin
            csr_rvalid_o <= read_req && addr_aligned && known_addr;
            csr_rdata_o <= (read_req && addr_aligned && known_addr) ? read_data_comb : 32'd0;
            csr_error_o <= (read_req && (!addr_aligned || !known_addr)) || write_reject;

            telemetry_soft_reset_pulse_o <= 1'b0;
            clear_metrics_pulse_o <= 1'b0;
            counter_clear_pulse_o <= counter_clear_req;
            replay_start_pulse_o <= replay_start_req;
            replay_rearm_pulse_o <= replay_rearm_req;
            ring_config_commit_pulse_o <= 1'b0;
            ring_wr_snapshot_pulse_o <= 1'b0;
            core_count_snapshot_pulse_o <= 1'b0;
            clear_sticky_flags_w1c_o <= clear_mask_comb;

            if (write_accept) begin
                unique case (csr_offset)
                    TCSR_CONTROL_OFFSET: begin
                        telemetry_soft_reset_pulse_o <= csr_wdata_i[TCSR_CONTROL_TELEMETRY_SOFT_RESET_LSB];
                        clear_metrics_pulse_o <= csr_wdata_i[TCSR_CONTROL_CLEAR_METRICS_LSB];
                        if ((csr_wdata_i & CONTROL_W1P_MASK) == 32'd0) begin
                            telemetry_enable_q <= csr_wdata_i[TCSR_CONTROL_TELEMETRY_ENABLE_LSB];
                            ring_writer_enable_q <= csr_wdata_i[TCSR_CONTROL_RING_WRITER_ENABLE_LSB];
                        end
                    end
                    TCSR_PACKET_ENABLE_OFFSET: begin
                        packet_enable_q <= csr_wdata_i;
                    end
                    TCSR_WAVE_DECIM_OFFSET: begin
                        wave_decim_q <= csr_wdata_i[15:0];
                    end
                    TCSR_SPEC_MODE_OFFSET: begin
                        spec_mode_q <= spec_mode_from_u2(csr_wdata_i[1:0]);
                    end
                    TCSR_SPEC_SHIFT_OFFSET: begin
                        spec_shift_q <= csr_wdata_i[5:0];
                    end
                    TCSR_RING_BASE_LO_OFFSET: begin
                        ring_base_shadow_q[31:0] <= csr_wdata_i;
                        ring_configured_q <= 1'b0;
                    end
                    TCSR_RING_BASE_HI_OFFSET: begin
                        ring_base_shadow_q[63:32] <= csr_wdata_i;
                        ring_configured_q <= 1'b0;
                    end
                    TCSR_RING_SIZE_BYTES_OFFSET: begin
                        ring_size_shadow_q <= csr_wdata_i;
                        ring_configured_q <= 1'b0;
                    end
                    TCSR_RING_CONFIG_COMMIT_OFFSET: begin
                        if (csr_wdata_i[0]) begin
                            ring_base_q <= ring_base_shadow_q;
                            ring_size_q <= ring_size_shadow_q;
                            ring_size_mask_q <= ring_size_shadow_q - 32'd1;
                            ring_configured_q <= 1'b1;
                            malformed_config_q <= 1'b0;
                            ring_config_commit_pulse_o <= 1'b1;
                            ring_wr_snap_q <= 64'd0;
                        end
                    end
                    TCSR_RING_WR_SNAPSHOT_OFFSET: begin
                        if (csr_wdata_i[0]) begin
                            ring_wr_snap_q <= ring_wr_ptr_i;
                            ring_wr_snapshot_pulse_o <= 1'b1;
                        end
                    end
                    TCSR_CORE_COUNT_SNAPSHOT_OFFSET: begin
                        if (csr_wdata_i[0]) begin
                            frame_count_snap_q <= core_frame_count_i;
                            sample_count_snap_q <= core_sample_count_i;
                            core_count_snapshot_pulse_o <= 1'b1;
                        end
                    end
                    default: begin
                        // Multiword shadow writes, ring consumer pointer commit, and W1C clear are
                        // handled by helper modules or combinational clear masks.
                    end
                endcase
            end

            if (soft_reset_req || external_transport_clear_i) begin
                ring_configured_q <= 1'b0;
                malformed_config_q <= 1'b0;
                ring_wr_snap_q <= 64'd0;
                if (external_transport_clear_i) begin
                    telemetry_enable_q <= 1'b0;
                    ring_writer_enable_q <= 1'b0;
                end
            end

            // The CSR-side epoch bit closes the one-cycle stale-pointer window between an
            // accepted configuration commit and the registered pointer-controller reset pulse.
            // It is raised only after the Rd helper has emitted the accepted commit pulse; the
            // pointer controller consumes that same pulse in the same cycle.
            if (soft_reset_req || external_transport_clear_i || ring_config_commit_req) begin
                ring_rd_epoch_valid_q <= 1'b0;
            end else if (ring_rd_commit_pulse_o) begin
                ring_rd_epoch_valid_q <= 1'b1;
            end

            if (write_req && write_reject && (csr_offset == TCSR_RING_CONFIG_COMMIT_OFFSET)) begin
                malformed_config_q <= 1'b1;
            end

            // Retain a host-correlatable replay decision. Board-key replay activity is ignored
            // unless a CSR request is pending, so it cannot advance the command result epoch.
            if (replay_rearm_req) begin
                replay_request_pending_q <= 1'b0;
                replay_last_accept_q <= 1'b0;
                replay_last_reject_q <= 1'b0;
            end else begin
                if (replay_start_req) begin
                    replay_request_pending_q <= 1'b1;
                end
                if (replay_request_pending_q &&
                    (replay_start_accept_pulse_i || replay_start_reject_pulse_i)) begin
                    replay_request_pending_q <= 1'b0;
                    replay_last_accept_q <= replay_start_accept_pulse_i &&
                                            !replay_start_reject_pulse_i;
                    replay_last_reject_q <= replay_start_reject_pulse_i ||
                                            !replay_start_accept_pulse_i;
                    replay_result_epoch_q <= replay_result_epoch_q + 16'd1;
                end
            end

            overflow_flags_q <= (overflow_flags_q & ~clear_mask_comb) | overflow_set_comb;
            if (counter_clear_req) begin
                csr_command_reject_count_q <= TCSR_CSR_COMMAND_REJECT_COUNT_RESET;
            end else if (reject_increment_comb != 2'd0) begin
                csr_command_reject_count_q <= csr_command_reject_count_q + {30'd0, reject_increment_comb};
            end
        end
    end

    always_comb begin
        ctrl_o = '0;
        ctrl_o.telemetry_enable = telemetry_enable_q;
        ctrl_o.ring_writer_enable = ring_writer_enable_q;
        ctrl_o.clear_metrics_w1p = clear_metrics_pulse_o;
        ctrl_o.thr2_active = thr2_active;
        ctrl_o.packet_enable = packet_enable_q;
        ctrl_o.wave_decim = wave_decim_q;
        ctrl_o.spec_mode = spec_mode_q;
        ctrl_o.spec_shift = spec_shift_q;
        ctrl_o.source_mode = source_mode_from_u2(source_active);
    end

    always_comb begin
        ring_config_o = '0;
        ring_config_o.configured = ring_configured_q;
        ring_config_o.base_addr = ring_base_q;
        ring_config_o.size_bytes = ring_size_q;
        ring_config_o.size_mask = ring_configured_q ? ring_size_mask_q : 32'd0;
    end

    assign status_o = status_comb;
    assign dma_status_o = dma_status_comb;
    assign overflow_flags_o = overflow_flags_q;
    assign csr_command_reject_count_o = csr_command_reject_count_q;
    assign csr_reject_pulse_o = (reject_increment_comb != 2'd0);
    assign ring_rd_committed_o = ring_rd_active;
    assign ring_rd_commit_pending_o = ring_rd_pending;
    assign malformed_config_o = malformed_config_q || malformed_config_i;

    // Keep otherwise useful debug nets from becoming mistaken for unconnected design intent.
    wire unused_commit_debug = |thr2_pending_value | |source_pending_value | |ring_rd_pending_value;

`ifndef SYNTHESIS
    initial begin
        if ((CSR_ADDR_W < 9) || (CSR_ADDR_W > 32)) begin
            $fatal(1, "trecap_csr_bank: CSR_ADDR_W must be in [9, 32]");
        end
    end
`endif

endmodule : trecap_csr_bank

`default_nettype wire
