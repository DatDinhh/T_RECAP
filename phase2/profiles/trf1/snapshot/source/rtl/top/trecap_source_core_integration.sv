// SPDX-License-Identifier: MIT
// File class: [1] hand-written RTL integration source.
// Layer: rtl/top/
// Owner: T-RECAP Phase 2 implementation.
// Purpose: Bind every normalized source through the safe source mux into the mathematical core.
// Contract: Own source pacing, source-epoch changes, finite BRAM-replay tail routing, and the
//           source/core safe-boundary signals consumed by the CSR layer. Telemetry remains a
//           valid-only observer and cannot drive any ready signal in this module.

`default_nettype none

module trecap_source_core_integration
#(
    parameter int unsigned SAMPLE_W                 = trecap_core_pkg::T_SAMPLE_W,
    parameter int unsigned L                        = trecap_core_pkg::T_FFT_L,
    parameter int unsigned P                        = trecap_core_pkg::T_FFT_P,
    parameter int unsigned BIN_IDX_W                = (trecap_core_pkg::T_UNIQUE_BINS <= 1) ? 1 : $clog2(trecap_core_pkg::T_UNIQUE_BINS),
    parameter              X_MEMH_FILE              = "artifacts/test_vectors/zero_Ns4096_thr0/x_in.memh",
    parameter int unsigned REPLAY_MEM_DEPTH         = 4096,
    parameter int unsigned REPLAY_INPUT_SAMPLES     = 4096,
    parameter bit          REPLAY_START_ON_RESET_RELEASE = 1'b0,
    parameter bit          REPLAY_RESTART_ALLOWED   = 1'b1,
    parameter int unsigned AUDIO_SAMPLE_W           = 16,
    parameter bit          AUDIO_SELECT_RIGHT       = 1'b0,
    parameter int unsigned ADC_BITS                 = 12,
    parameter trecap_iface_pkg::trecap_source_mode_e RESET_SOURCE_MODE = trecap_iface_pkg::TSRC_BRAM_REPLAY,
    parameter              WINDOW_FILE              = trecap_build_pkg::TBUILD_WINDOW_QW_MEMH,
    parameter              TWIDDLE_RE_FILE          = trecap_build_pkg::TBUILD_TWIDDLE_RE_MEMH,
    parameter              TWIDDLE_IM_FILE          = trecap_build_pkg::TBUILD_TWIDDLE_IM_MEMH,
    parameter              TWIDDLE_INV_RE_FILE      = trecap_build_pkg::TBUILD_TWIDDLE_INV_RE_MEMH,
    parameter              TWIDDLE_INV_IM_FILE      = trecap_build_pkg::TBUILD_TWIDDLE_INV_IM_MEMH,
    parameter int unsigned DIAGNOSTIC_PERIOD_FIXED  = 0,
    // Enable only when producer pulses equal current_count > previous_count in clk.
    // Default retains the generic counter-input contract for other integrations.
    parameter bit          USE_WRAPPER_DROP_ADVANCE = 1'b0
) (
    input  logic                         clk,
    input  logic                         rst_n,
    input  logic                         enable_i,
    // Datapath/source-epoch clear. It deliberately preserves the CSR-selected mux mode;
    // coordinated control-plane and mux-mode reset is owned by shared rst_n.
    input  logic                         clear_i,
    // Physical source readiness/stop acknowledgement and loss accounting are in clk.
    input  logic                         source_rearm_i,
    input  logic                         audio_ready_i,
    input  logic                         audio_stopped_i,
    input  logic                         adc_ready_i,
    input  logic                         adc_stopped_i,
    input  logic                         live_periodic_i,
    input  logic [31:0]                  live_sample_rate_hz_i,
    input  logic [63:0]                  audio_wrapper_drop_count_i,
    input  logic [63:0]                  adc_wrapper_drop_count_i,
    // Optional same-edge counter-advance evidence; requires the shared rst_n.
    input  logic                         audio_wrapper_drop_advanced_i,
    input  logic                         adc_wrapper_drop_advanced_i,
    input  logic                         audio_wrapper_protocol_i,
    input  logic                         adc_wrapper_protocol_i,
    output logic                         live_source_enable_o,
    output logic [991:0]                 source_health_o,

    // Active values and post-safe-boundary apply pulse from the CSR bank. The CSR layer has
    // already validated the enum and waited for source_safe_boundary_o before asserting apply.
    input  trecap_iface_pkg::trecap_thr2_t                 thr2_i,
    input  trecap_iface_pkg::trecap_source_mode_e          requested_source_mode_i,
    input  logic                         source_mode_apply_pulse_i,
    input  logic                         clear_metrics_pulse_i,
    input  logic [31:0]                  clear_sticky_flags_w1c_i,

    // Board-paced sources. BRAM replay and diagnostic data consume one beat only on this tick.
    // Live audio/ADC adapters are instead paced by their raw sample-valid events.
    input  logic                         source_tick_i,
    input  logic                         replay_start_i,
    // Integration-level admission (transport ready and prior E2E epoch complete). Keep the raw
    // request separate so every denied explicit start still produces reject evidence.
    input  logic                         replay_start_admit_i,
    input  logic [2:0]                   diagnostic_mode_i,
    input  logic signed [trecap_core_pkg::T_SAMPLE_W-1:0] diagnostic_constant_i,
    input  logic signed [trecap_core_pkg::T_SAMPLE_W-1:0] diagnostic_amplitude_i,
    input  logic [31:0]                  diagnostic_period_i,

    input  logic                         audio_sample_valid_i,
    input  logic signed [AUDIO_SAMPLE_W-1:0] audio_left_i,
    input  logic signed [AUDIO_SAMPLE_W-1:0] audio_right_i,
    input  logic [63:0]                  audio_sample_count_i,

    input  logic                         adc_sample_valid_i,
    input  logic [ADC_BITS-1:0]          adc_sample_raw_i,
    input  logic [63:0]                  adc_sample_count_i,
    input  logic                         adc_zero_code_valid_i,
    input  logic [ADC_BITS-1:0]          adc_zero_code_i,
    input  logic                         adc_dc_block_enable_i,

    // Core output is exposed for a future local monitor/signoff sink. A board integration shall
    // tie y_ready_i high unless it provides an explicitly non-telemetry core-output sink.
    output logic                         y_valid_o,
    input  logic                         y_ready_i,
    output trecap_iface_pkg::trecap_sample_t               y_sample_o,
    output logic signed [SAMPLE_W-1:0]   y_data_o,
    output logic [63:0]                  y_sample_idx_o,

    // Valid-only core observation taps. No ready/backpressure returns from telemetry.
    output trecap_iface_pkg::trecap_core_tap_sample_t      tap_sample_o,
    output trecap_iface_pkg::trecap_core_tap_frame_t       tap_frame_o,
    output logic                         tap_bin_valid_o,
    output logic [63:0]                  tap_bin_frame_idx_o,
    output logic [BIN_IDX_W-1:0]         tap_bin_idx_o,
    output logic signed [trecap_core_pkg::T_CAN_W-1:0]    tap_bin_re_o,
    output logic signed [trecap_core_pkg::T_CAN_W-1:0]    tap_bin_im_o,
    output logic [trecap_core_pkg::T_MAG2_W-1:0]          tap_bin_mag2_o,
    output logic                         tap_bin_pre_mask_o,
    output logic                         tap_bin_mask_o,
    output logic                         tap_bin_eligible_o,
    output logic                         tap_bin_last_o,

    // Safe-boundary/control return path.
    output logic                         frame_boundary_pulse_o,
    output logic                         core_config_safe_boundary_o,
    output logic                         source_safe_boundary_o,
    // Exact event applied to the core metric epoch after any required boundary wait. Telemetry
    // aggregate state must use this pulse, never the earlier raw CSR command pulse.
    output logic                         clear_metrics_apply_pulse_o,
    output trecap_iface_pkg::trecap_source_mode_e          active_source_mode_o,
    output trecap_iface_pkg::trecap_source_mode_e          pending_source_mode_o,
    output logic                         source_switch_pending_o,
    output logic                         source_switch_apply_pulse_o,
    output logic                         source_discontinuity_pulse_o,

    // Core status and counters consumed by the CSR/telemetry integration.
    output logic                         core_alive_o,
    output logic                         core_busy_o,
    output logic [63:0]                  core_sample_count_o,
    output logic [63:0]                  core_frame_count_o,
    output logic [63:0]                  core_error_sample_count_o,
    output logic [63:0]                  core_sum_abs_err_lo_o,
    output logic [63:0]                  core_sum_sq_err_lo_o,
    output logic [15:0]                  core_max_abs_err_o,
    output logic                         core_metric_overflow_sticky_o,
    output logic [31:0]                  core_overflow_flags_o,
    output logic                         core_saturation_sticky_o,
    output logic                         core_protocol_error_sticky_o,

    // Replay/source observability. replay_done_o remains the Step-7 source-token status: it goes
    // high after the final BRAM/flush token is accepted. The replay_path_* outputs below qualify
    // BRAM-to-core completion only: every public y sample, frame, WOLA output, and error-metric
    // sample count must be exact and the core quiescent. The separate system E2E supervisor adds
    // the required post-core telemetry/DDR commit before declaring Step-11 completion.
    output logic                         replay_active_o,
    output logic                         replay_done_o,
    output logic                         replay_input_phase_o,
    output logic                         replay_flush_phase_o,
    output logic                         replay_tail_drain_phase_o,
    output logic                         replay_start_accept_pulse_o,
    output logic                         replay_start_reject_pulse_o,
    output logic                         replay_start_ready_o,
    output logic [63:0]                  replay_output_accept_count_o,
    output logic [63:0]                  replay_expected_output_count_o,
    output logic                         replay_path_busy_o,
    output logic                         replay_path_done_o,
    output logic                         replay_path_done_pulse_o,
    output logic [63:0]                  replay_core_output_accept_count_o,
    output logic                         replay_completion_error_sticky_o,
    output logic                         source_fault_sticky_o,
    output logic                         build_contract_error_o,

    // These are one-cycle NEW-FAULT events. The CSR bank is set-dominant and its W1C owner pulse
    // is delayed, so persistent sticky levels must never be connected to this set interface.
    output logic [31:0]                  external_overflow_flags_set_o,
    output logic                         external_csr_reject_pulse_o
);
  import trecap_core_pkg::*;
  import trecap_csr_pkg::*;
  import trecap_iface_pkg::*;
  import trecap_build_pkg::*;


    // Widen before geometry arithmetic so parameter expressions cannot overflow at 32 bits.
    localparam longint unsigned REPLAY_INPUT_U64 = longint'(REPLAY_INPUT_SAMPLES);
    localparam longint unsigned REPLAY_NFRAMES_U64 =
        (REPLAY_INPUT_U64 + longint'(T_FFT_L) - 64'd2) / longint'(T_HOP_H);
    localparam longint unsigned REPLAY_TAU_LAST_U64 =
        REPLAY_NFRAMES_U64 * longint'(T_HOP_H);
    localparam longint unsigned REPLAY_OUTPUT_SAMPLES_U64 =
        REPLAY_TAU_LAST_U64 + longint'(T_CUSHION_G) + longint'(T_FFT_L);
    localparam longint unsigned REPLAY_FLUSH_SAMPLES_U64 =
        REPLAY_OUTPUT_SAMPLES_U64 - REPLAY_INPUT_U64;
    localparam longint unsigned REPLAY_DRAIN_SAMPLES_U64 =
        longint'(T_CUSHION_G) + longint'(T_FFT_L);
    localparam int unsigned REPLAY_FLUSH_SAMPLES = int'(REPLAY_FLUSH_SAMPLES_U64);
    localparam logic [63:0] REPLAY_NFRAMES = REPLAY_NFRAMES_U64[63:0];
    localparam logic [63:0] REPLAY_TAU_LAST = REPLAY_TAU_LAST_U64[63:0];
    localparam logic [63:0] REPLAY_OUTPUT_SAMPLES = REPLAY_OUTPUT_SAMPLES_U64[63:0];
    localparam logic [31:0] REPLAY_DRAIN_SAMPLES = REPLAY_DRAIN_SAMPLES_U64[31:0];
    localparam bit LOCAL_BUILD_CONTRACT_OK =
        TBUILD_CONTRACT_OK &&
        (SAMPLE_W == T_SAMPLE_W) &&
        (L == T_FFT_L) &&
        (P == T_FFT_P) &&
        (REPLAY_MEM_DEPTH != 0) &&
        (REPLAY_INPUT_SAMPLES != 0) &&
        (REPLAY_INPUT_SAMPLES <= REPLAY_MEM_DEPTH) &&
        (REPLAY_TAU_LAST_U64 >= REPLAY_INPUT_U64) &&
        (REPLAY_OUTPUT_SAMPLES_U64 != 0) &&
        (REPLAY_FLUSH_SAMPLES_U64 <= 64'h0000_0000_ffff_ffff) &&
        (REPLAY_DRAIN_SAMPLES_U64 <= 64'h0000_0000_ffff_ffff) &&
        (REPLAY_DRAIN_SAMPLES_U64 == T_DELAY_D);

    trecap_sample_t bram_sample_w;
    trecap_sample_t adc_sample_w;
    trecap_sample_t audio_sample_w;
    trecap_sample_t diagnostic_sample_w;
    trecap_sample_t mux_sample_w;
    trecap_sample_t core_sample_w;

    logic bram_sample_valid_w;
    logic adc_sample_valid_w;
    logic audio_sample_valid_w;
    logic diagnostic_sample_valid_w;
    logic mux_sample_valid_w;
    logic bram_sample_ready_w;
    logic adc_sample_ready_w;
    logic audio_sample_ready_w;
    logic diagnostic_sample_ready_w;
    logic mux_sample_ready_w;

    logic mode_is_bram_w;
    logic mode_is_adc_w;
    logic mode_is_audio_w;
    logic mode_is_diagnostic_w;
    logic mode_change_request_w;
    logic live_fault_q, live_started_q, live_wait_stop_q;
    logic live_ready_w, live_stopped_w, live_mode_w, live_raw_valid_w;
    logic [63:0] live_raw_sequence_w, live_expected_sequence_q;
    // Store last + 1 on the original raw-sample update edge, modulo 2^64.
    // The live fault path then compares directly without an incrementer.
    // Reset seeds 0 + 1; every guard/fault/idle branch retains this state.
    logic [31:0] live_fault_reason_q, live_fault_reason_w;
    logic live_fault_event_w, live_guard_reset_w;
    logic [25:0] live_timeout_q;
    logic [12:0] live_settle_q;
    logic [63:0] live_epoch_q;
    logic [63:0] health_audio_raw_q, health_adc_raw_q;
    logic [63:0] health_audio_admitted_q, health_adc_admitted_q;
    logic [63:0] health_audio_accepted_q, health_adc_accepted_q;
    logic [63:0] health_audio_drop_q, health_adc_drop_q;
    logic [63:0] health_audio_wrapper_drop_q, health_adc_wrapper_drop_q;
    logic [63:0] health_gap_q, health_ready_loss_q, health_timeout_q;
    logic [63:0] prior_audio_wrapper_drop_q, prior_adc_wrapper_drop_q;
    logic audio_adapter_admit_w, adc_adapter_admit_w;
    logic audio_wrapper_drop_advanced_w, adc_wrapper_drop_advanced_w;
    logic audio_adapter_drop_w, adc_adapter_drop_w;
    logic transition_guard_w;
    logic source_epoch_clear_w;
    logic datapath_epoch_clear_level_w;
    logic datapath_epoch_clear_prior_q;
    logic selected_source_pace_w;
    logic selected_bram_tail_w;
    logic core_sample_valid_w;
    logic core_sample_ready_w;
    logic tail_tick_valid_w;
    logic tail_tick_ready_w;
    logic tail_tick_last_w;
    logic source_handshake_w;

    logic mux_switch_accept_w;
    logic mux_switch_apply_w;
    logic mux_switch_reject_w;
    logic mux_discontinuity_w;
    logic mux_output_accept_w;
    logic mux_invalid_mode_w;
    logic mux_pending_sticky_w;
    logic mux_disabled_sticky_w;

    logic replay_start_request_w;
    logic replay_start_qualified_w;
    logic replay_start_local_reject_w;
    logic replay_start_accept_w;
    logic replay_start_reject_w;
    logic replay_done_pulse_w;
    logic replay_config_error_w;
    logic replay_mem_range_error_w;
    logic replay_overrun_w;
    logic replay_auto_start_pending_q;
    logic replay_start_reject_sticky_q;

    logic audio_discontinuity_w;
    logic audio_overflow_w;
    logic audio_disabled_drop_w;
    logic audio_clip_hi_w;
    logic audio_clip_lo_w;
    logic audio_config_error_w;
    logic adc_discontinuity_w;
    logic adc_overflow_w;
    logic adc_disabled_drop_w;
    logic adc_clip_hi_w;
    logic adc_clip_lo_w;
    logic adc_config_error_w;
    logic diagnostic_discontinuity_w;
    logic diagnostic_mode_error_w;
    logic diagnostic_disabled_w;

    logic metrics_clear_pending_q;
    logic core_clear_metrics_w;
    logic core_clear_sticky_w;
    logic source_clear_sticky_w;
    logic [31:0] externally_mapped_fault_levels_w;
    logic [31:0] prior_mapped_fault_levels_q;
    logic source_fault_level_w;

    logic tail_drain_active_w;
    logic tail_drain_accept_w;
    logic tail_drain_done_w;
    logic [63:0] wola_output_count_w;

    logic        replay_y_accept_w;
    logic        replay_path_structural_busy_w;
    logic        replay_path_quiescent_w;
    logic        replay_path_exact_counts_w;
    logic        replay_path_fault_w;
    logic        replay_path_inflight_q;
    logic        replay_path_done_q;
    logic        replay_path_done_pulse_q;
    logic [63:0] replay_core_output_accept_count_q;
    logic [63:0] replay_metric_commit_count_q;
    logic        replay_completion_error_sticky_q;

    // A physical-time stream cannot silently close a missing-sample gap. Stop,
    // invalidate the epoch, then require an explicit restart acknowledgement.
    function automatic logic [63:0] health_sat_add(input logic [63:0] a, b);
        logic [64:0] sum;
        sum = {1'b0, a} + {1'b0, b};
        return sum[64] ? 64'hffff_ffff_ffff_ffff : sum[63:0];
    endfunction
    assign live_mode_w = mode_is_audio_w || mode_is_adc_w;
    assign live_ready_w = mode_is_audio_w ? audio_ready_i : adc_ready_i;
    assign live_stopped_w = mode_is_audio_w ? audio_stopped_i : adc_stopped_i;
    assign live_raw_valid_w = mode_is_audio_w ? audio_sample_valid_i : adc_sample_valid_i;
    assign live_raw_sequence_w = mode_is_audio_w ? audio_sample_count_i : adc_sample_count_i;
    assign live_guard_reset_w = clear_i || mode_change_request_w || source_rearm_i || !enable_i;
    assign live_source_enable_o = rst_n && enable_i && live_mode_w && live_periodic_i &&
        !live_fault_q && !live_wait_stop_q && (live_settle_q == 0) && live_ready_w;
    always_comb begin
        live_fault_reason_w = 32'd0;
        if (live_mode_w && live_periodic_i && !live_guard_reset_w && !live_fault_q &&
            !live_wait_stop_q && (live_settle_q == 0)) begin
            if (live_started_q && live_raw_valid_w &&
                (live_raw_sequence_w != live_expected_sequence_q))
                live_fault_reason_w[TCSR_SOURCE_HEALTH_FAULT_SEQUENCE_GAP_LSB] = 1'b1;
            if ((mode_is_audio_w && audio_adapter_drop_w) ||
                (mode_is_adc_w && adc_adapter_drop_w)) live_fault_reason_w[TCSR_SOURCE_HEALTH_FAULT_ADAPTER_DROP_LSB] = 1'b1;
            if ((mode_is_audio_w && audio_wrapper_drop_advanced_w) ||
                (mode_is_adc_w && adc_wrapper_drop_advanced_w))
                live_fault_reason_w[TCSR_SOURCE_HEALTH_FAULT_WRAPPER_DROP_LSB] = 1'b1;
            if (live_started_q && !live_ready_w) live_fault_reason_w[TCSR_SOURCE_HEALTH_FAULT_READINESS_LOSS_LSB] = 1'b1;
            // Startup allows codec initialization; after the first sample the bound is 81.92 us.
            if ((!live_started_q && live_timeout_q >= 26'd50_000_000) ||
                (live_started_q && live_timeout_q >= 26'd4096))
                live_fault_reason_w[TCSR_SOURCE_HEALTH_FAULT_SAMPLE_TIMEOUT_LSB] = 1'b1;
            if ((mode_is_audio_w && audio_wrapper_protocol_i) ||
                (mode_is_adc_w && adc_wrapper_protocol_i)) live_fault_reason_w[TCSR_SOURCE_HEALTH_FAULT_WRAPPER_PROTOCOL_LSB] = 1'b1;
        end
    end
    assign live_fault_event_w = |live_fault_reason_w;

    // Board producers publish these flags on the counter-update edge. This avoids
    // a wide counter comparison before same-cycle fail-stop, without delaying it.
    // Counter deltas below remain the lifetime-accounting authority in both modes.
    assign audio_wrapper_drop_advanced_w = USE_WRAPPER_DROP_ADVANCE ?
        audio_wrapper_drop_advanced_i : (audio_wrapper_drop_count_i > prior_audio_wrapper_drop_q);
    assign adc_wrapper_drop_advanced_w = USE_WRAPPER_DROP_ADVANCE ?
        adc_wrapper_drop_advanced_i : (adc_wrapper_drop_count_i > prior_adc_wrapper_drop_q);

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            live_fault_q <= 1'b0; live_fault_reason_q <= 0; live_started_q <= 1'b0;
            live_wait_stop_q <= 1'b1; live_settle_q <= 13'd4096;
            live_timeout_q <= 0; live_expected_sequence_q <= 64'd1; live_epoch_q <= 0;
            prior_audio_wrapper_drop_q <= 0; prior_adc_wrapper_drop_q <= 0;
            health_audio_raw_q <= 0; health_adc_raw_q <= 0;
            health_audio_admitted_q <= 0; health_adc_admitted_q <= 0;
            health_audio_accepted_q <= 0; health_adc_accepted_q <= 0;
            health_audio_drop_q <= 0; health_adc_drop_q <= 0;
            health_audio_wrapper_drop_q <= 0; health_adc_wrapper_drop_q <= 0;
            health_gap_q <= 0; health_ready_loss_q <= 0; health_timeout_q <= 0;
        end else begin
            // Lifetime supervisor counters survive source, telemetry, and diagnostic clears.
            prior_audio_wrapper_drop_q <= audio_wrapper_drop_count_i;
            prior_adc_wrapper_drop_q <= adc_wrapper_drop_count_i;
            if (audio_wrapper_drop_count_i > prior_audio_wrapper_drop_q)
                health_audio_wrapper_drop_q <= health_sat_add(health_audio_wrapper_drop_q,
                    audio_wrapper_drop_count_i - prior_audio_wrapper_drop_q);
            if (adc_wrapper_drop_count_i > prior_adc_wrapper_drop_q)
                health_adc_wrapper_drop_q <= health_sat_add(health_adc_wrapper_drop_q,
                    adc_wrapper_drop_count_i - prior_adc_wrapper_drop_q);
            if (audio_sample_valid_i) health_audio_raw_q <= health_sat_add(health_audio_raw_q, 64'd1);
            if (adc_sample_valid_i) health_adc_raw_q <= health_sat_add(health_adc_raw_q, 64'd1);
            if (audio_adapter_admit_w) health_audio_admitted_q <= health_sat_add(health_audio_admitted_q, 64'd1);
            if (adc_adapter_admit_w) health_adc_admitted_q <= health_sat_add(health_adc_admitted_q, 64'd1);
            if (audio_adapter_drop_w) health_audio_drop_q <= health_sat_add(health_audio_drop_q, 64'd1);
            if (adc_adapter_drop_w) health_adc_drop_q <= health_sat_add(health_adc_drop_q, 64'd1);
            if (core_sample_valid_w && core_sample_ready_w && mode_is_audio_w)
                health_audio_accepted_q <= health_sat_add(health_audio_accepted_q, 64'd1);
            if (core_sample_valid_w && core_sample_ready_w && mode_is_adc_w)
                health_adc_accepted_q <= health_sat_add(health_adc_accepted_q, 64'd1);
            if (live_guard_reset_w) begin
                live_fault_q <= 1'b0; live_fault_reason_q <= 0; live_started_q <= 1'b0;
                live_wait_stop_q <= 1'b1; live_settle_q <= 13'd4096; live_timeout_q <= 0;
                if (source_rearm_i || mode_change_request_w || (datapath_epoch_clear_level_w && !datapath_epoch_clear_prior_q))
                    live_epoch_q <= health_sat_add(live_epoch_q, 64'd1);
            end else if (live_fault_event_w) begin
                live_fault_q <= 1'b1; live_fault_reason_q <= live_fault_reason_w;
                live_started_q <= 1'b0; live_wait_stop_q <= 1'b1;
                live_epoch_q <= health_sat_add(live_epoch_q, 64'd1);
                if (live_fault_reason_w[TCSR_SOURCE_HEALTH_FAULT_SEQUENCE_GAP_LSB]) health_gap_q <= health_sat_add(health_gap_q, 64'd1);
                if (live_fault_reason_w[TCSR_SOURCE_HEALTH_FAULT_READINESS_LOSS_LSB]) health_ready_loss_q <= health_sat_add(health_ready_loss_q, 64'd1);
                if (live_fault_reason_w[TCSR_SOURCE_HEALTH_FAULT_SAMPLE_TIMEOUT_LSB]) health_timeout_q <= health_sat_add(health_timeout_q, 64'd1);
            end else begin
                if (live_stopped_w) live_wait_stop_q <= 1'b0;
                if (!live_wait_stop_q && live_settle_q != 0)
                    live_settle_q <= live_settle_q - 1'b1;
                if (live_mode_w && live_periodic_i && !live_fault_q &&
                    !live_wait_stop_q && (live_settle_q == 0)) begin
                    if (live_raw_valid_w && live_ready_w) begin
                        live_started_q <= 1'b1;
                        live_expected_sequence_q <= live_raw_sequence_w + 64'd1;
                        live_timeout_q <= 0;
                    end else if (live_timeout_q != 26'h3ff_ffff) live_timeout_q <= live_timeout_q + 1'b1;
                end else live_timeout_q <= 0;
            end
        end
    end

    always_comb begin
        source_health_o = '0;
        source_health_o[TCSR_SOURCE_HEALTH_STATUS_PRESENT_LSB] = 1'b1;
        source_health_o[TCSR_SOURCE_HEALTH_STATUS_LIVE_LSB] = live_mode_w;
        source_health_o[TCSR_SOURCE_HEALTH_STATUS_PERIODIC_LSB] = live_periodic_i && live_mode_w;
        source_health_o[TCSR_SOURCE_HEALTH_STATUS_READY_LSB] = live_mode_w && live_ready_w;
        source_health_o[TCSR_SOURCE_HEALTH_STATUS_RUNNING_LSB] = live_source_enable_o && live_started_q;
        source_health_o[TCSR_SOURCE_HEALTH_STATUS_FAULT_LSB] = live_fault_q;
        source_health_o[TCSR_SOURCE_HEALTH_STATUS_WAITING_STOP_LSB] = live_wait_stop_q;
        source_health_o[TCSR_SOURCE_HEALTH_STATUS_SETTLING_LSB] = (live_settle_q != 0);
        source_health_o[TCSR_SOURCE_HEALTH_STATUS_SOURCE_MODE_MSB:TCSR_SOURCE_HEALTH_STATUS_SOURCE_MODE_LSB] = active_source_mode_o;
        source_health_o[32 +: 32] = live_fault_reason_q;
        source_health_o[64 +: 32] = live_source_enable_o ? live_sample_rate_hz_i : 32'd0;
        source_health_o[96 +: 64] = live_epoch_q;
        source_health_o[160 +: 64] = health_audio_raw_q;
        source_health_o[224 +: 64] = health_adc_raw_q;
        source_health_o[288 +: 64] = health_audio_admitted_q;
        source_health_o[352 +: 64] = health_adc_admitted_q;
        source_health_o[416 +: 64] = health_audio_accepted_q;
        source_health_o[480 +: 64] = health_adc_accepted_q;
        source_health_o[544 +: 64] = health_audio_drop_q;
        source_health_o[608 +: 64] = health_adc_drop_q;
        source_health_o[672 +: 64] = health_audio_wrapper_drop_q;
        source_health_o[736 +: 64] = health_adc_wrapper_drop_q;
        source_health_o[800 +: 64] = health_gap_q;
        source_health_o[864 +: 64] = health_ready_loss_q;
        source_health_o[928 +: 64] = health_timeout_q;
    end

    assign mode_is_bram_w = (active_source_mode_o == TSRC_BRAM_REPLAY);
    assign mode_is_adc_w = (active_source_mode_o == TSRC_ADC_LIVE);
    assign mode_is_audio_w = (active_source_mode_o == TSRC_AUDIO_WRAPPER);
    assign mode_is_diagnostic_w = (active_source_mode_o == TSRC_DIAGNOSTIC);

    // The CSR pulse is post-boundary. Block both directions immediately when it represents a real
    // change, then hold the guard through mux apply and adapter epoch-clear evidence.
    assign mode_change_request_w = source_mode_apply_pulse_i &&
                                   (requested_source_mode_i != active_source_mode_o);
    assign datapath_epoch_clear_level_w = clear_i || !enable_i;
    assign source_epoch_clear_w = datapath_epoch_clear_level_w || mode_change_request_w ||
                                  source_rearm_i || live_fault_event_w ||
                                  mux_switch_apply_w || mux_discontinuity_w;
    assign transition_guard_w = datapath_epoch_clear_level_w || mode_change_request_w ||
                                source_rearm_i || live_fault_event_w ||
                                (live_mode_w && !live_source_enable_o) ||
                                mux_switch_apply_w || mux_discontinuity_w ||
                                audio_discontinuity_w || adc_discontinuity_w ||
                                diagnostic_discontinuity_w || replay_start_accept_w;
    // mode_change_request_w is already the one-cycle post-CSR apply event. The mux emits its
    // registered discontinuity evidence on the following cycle; that evidence extends the guard
    // and source clear, but must not stretch the public/core discontinuity pulse to two cycles.
    assign source_discontinuity_pulse_o = mode_change_request_w || replay_start_accept_w ||
        source_rearm_i || live_fault_event_w ||
        (datapath_epoch_clear_level_w && !datapath_epoch_clear_prior_q);
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            // Reset already establishes a fresh global epoch; suppress a redundant pulse while
            // reset is held or enable starts low.
            datapath_epoch_clear_prior_q <= 1'b1;
        end else begin
            datapath_epoch_clear_prior_q <= datapath_epoch_clear_level_w;
        end
    end

    // Synthetic board sources obey the declared sample-rate tick. Live wrappers carry their own
    // sample-valid timing. Both valid and ready are gated together, so a held beat cannot be
    // skipped between ticks.
    assign selected_source_pace_w =
        (mode_is_bram_w || mode_is_diagnostic_w) ? source_tick_i : 1'b1;
    assign selected_bram_tail_w = mode_is_bram_w && mux_sample_valid_w &&
                                  (mux_sample_w.sample_idx >= REPLAY_TAU_LAST_U64);
    assign mux_sample_ready_w = !transition_guard_w && selected_source_pace_w &&
                                (selected_bram_tail_w ? tail_tick_ready_w : core_sample_ready_w);
    assign core_sample_valid_w = !transition_guard_w && selected_source_pace_w &&
                                 mux_sample_valid_w && !selected_bram_tail_w;
    assign tail_tick_valid_w = !transition_guard_w && selected_source_pace_w &&
                               mux_sample_valid_w && selected_bram_tail_w;
    assign tail_tick_last_w = tail_tick_valid_w &&
                              (mux_sample_w.sample_idx == (REPLAY_OUTPUT_SAMPLES_U64 - 64'd1));
    assign source_handshake_w = mux_sample_valid_w && mux_sample_ready_w;

    // A held beat makes the source boundary unsafe. An empty selected source or an actual accepted
    // beat is safe. A stopped live source is also switchable once its adapter is empty;
    // otherwise manual diagnostics or unavailable hardware could trap the selected source.
    assign source_safe_boundary_o = rst_n && !clear_i &&
        (!transition_guard_w || (live_mode_w && !live_source_enable_o)) &&
                                    !source_switch_pending_o &&
                                    (!mux_sample_valid_w || source_handshake_w);
    assign core_config_safe_boundary_o = rst_n && !clear_i &&
        (frame_boundary_pulse_o ||
         (!core_busy_o && !y_valid_o &&
          (!transition_guard_w || (live_mode_w && !live_source_enable_o))));

    // Queue a raw CLEAR_METRICS request until the true frame boundary or structural core idle.
    // Repeated requests while pending coalesce into one safe apply event.
    // Preserve one coherent metric epoch for a finite replay. A CLEAR_METRICS command accepted
    // while replay is active remains pending and is applied at the first core-safe boundary after
    // exact completion/abort. This keeps the user-visible aggregates meaningful for the complete
    // run without blocking the command path.
    assign core_clear_metrics_w = (metrics_clear_pending_q || clear_metrics_pulse_i) &&
                                  core_config_safe_boundary_o &&
                                  !replay_path_inflight_q && !replay_active_o;
    // A source discontinuity resets the core's metric state through source_discontinuity_i, so it
    // is also part of the shared metric-epoch clear observed by board telemetry.
    assign clear_metrics_apply_pulse_o = core_clear_metrics_w || source_discontinuity_pulse_o;
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            metrics_clear_pending_q <= 1'b0;
        end else if (clear_i || !enable_i || source_discontinuity_pulse_o) begin
            metrics_clear_pending_q <= 1'b0;
        end else if (core_clear_metrics_w) begin
            metrics_clear_pending_q <= 1'b0;
        end else if (clear_metrics_pulse_i) begin
            metrics_clear_pending_q <= 1'b1;
        end
    end

    assign core_clear_sticky_w =
        |(clear_sticky_flags_w1c_i &
          (TCSR_OVERFLOW_FLAGS_ARITHMETIC_OVERFLOW_MASK |
           TCSR_OVERFLOW_FLAGS_OLA_OVERFLOW_MASK |
           TCSR_OVERFLOW_FLAGS_RING_OVERFLOW_MASK));
    assign source_clear_sticky_w =
        |(clear_sticky_flags_w1c_i & TCSR_OVERFLOW_FLAGS_SOURCE_MODE_ERROR_MASK);

    // Integration owns reset-release auto-start qualification rather than letting an unselected
    // BRAM source start behind the mux. Explicit replay starts outside a safe BRAM idle state are
    // rejected and reported through the dedicated replay status output.
    assign replay_start_request_w = replay_start_i || replay_auto_start_pending_q;
    assign replay_start_ready_o = replay_start_admit_i && mode_is_bram_w &&
                                  !transition_guard_w && !source_switch_pending_o &&
                                  !replay_active_o && !mux_sample_valid_w &&
                                  !core_busy_o && !y_valid_o && !replay_path_inflight_q &&
                                  ((!replay_done_o && !replay_path_done_q) ||
                                   (REPLAY_RESTART_ALLOWED && replay_path_done_q)) &&
                                  LOCAL_BUILD_CONTRACT_OK;
    // Keep the qualification expression explicit as the source-contract authority. The ready
    // output above is the same predicate without the request term and is observability only.
    assign replay_start_qualified_w = replay_start_request_w && replay_start_admit_i &&
                                      mode_is_bram_w &&
                                      !transition_guard_w && !source_switch_pending_o &&
                                      !replay_active_o && !mux_sample_valid_w &&
                                      !core_busy_o && !y_valid_o && !replay_path_inflight_q &&
                                      ((!replay_done_o && !replay_path_done_q) ||
                                       (REPLAY_RESTART_ALLOWED && replay_path_done_q)) &&
                                      LOCAL_BUILD_CONTRACT_OK;
    assign replay_start_local_reject_w = replay_start_i && !replay_start_qualified_w;
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            replay_auto_start_pending_q <= REPLAY_START_ON_RESET_RELEASE;
            replay_start_reject_sticky_q <= 1'b0;
        end else if (clear_i || !enable_i) begin
            replay_auto_start_pending_q <= REPLAY_START_ON_RESET_RELEASE;
            replay_start_reject_sticky_q <= 1'b0;
        end else begin
            if (replay_start_qualified_w) begin
                replay_auto_start_pending_q <= 1'b0;
            end
            if (source_clear_sticky_w) begin
                replay_start_reject_sticky_q <= 1'b0;
            end
            if (replay_start_local_reject_w || replay_start_reject_w) begin
                replay_start_reject_sticky_q <= 1'b1;
            end
        end
    end

    trecap_bram_replay_source #(
        .INIT_FILE(X_MEMH_FILE),
        .MEM_DEPTH(REPLAY_MEM_DEPTH),
        .INPUT_SAMPLES(REPLAY_INPUT_SAMPLES),
        .FLUSH_SAMPLES(REPLAY_FLUSH_SAMPLES),
        .START_ON_RESET_RELEASE(1'b0),
        .RESTART_ALLOWED_WHILE_DONE(REPLAY_RESTART_ALLOWED)
    ) u_bram_replay_source (
        .clk(clk),
        .rst_n(rst_n),
        .enable_i(enable_i && mode_is_bram_w && !transition_guard_w),
        .start_i(replay_start_qualified_w),
        .clear_i(source_epoch_clear_w),
        .clear_sticky_i(source_clear_sticky_w),
        .sample_ready_i(bram_sample_ready_w),
        .sample_o(bram_sample_w),
        .sample_valid_o(bram_sample_valid_w),
        .sample_data_o(),
        .sample_idx_o(),
        .active_o(replay_active_o),
        .done_o(replay_done_o),
        .input_phase_o(replay_input_phase_o),
        .flush_phase_o(replay_flush_phase_o),
        .start_accept_pulse_o(replay_start_accept_w),
        .start_reject_pulse_o(replay_start_reject_w),
        .output_accept_pulse_o(),
        .last_sample_pulse_o(),
        .done_pulse_o(replay_done_pulse_w),
        .next_issue_idx_o(),
        .output_accept_count_o(replay_output_accept_count_o),
        .configured_input_samples_o(),
        .configured_flush_samples_o(),
        .config_error_sticky_o(replay_config_error_w),
        .mem_range_error_sticky_o(replay_mem_range_error_w),
        .replay_overrun_sticky_o(replay_overrun_w)
    );

    trecap_audio_adapter #(
        .AUDIO_SAMPLE_W(AUDIO_SAMPLE_W),
        .SELECT_RIGHT_CHANNEL(AUDIO_SELECT_RIGHT)
    ) u_audio_adapter (
        .clk(clk),
        .rst_n(rst_n),
        .enable_i(enable_i && mode_is_audio_w && !transition_guard_w),
        .clear_i(source_epoch_clear_w),
        .clear_sticky_i(source_clear_sticky_w),
        .audio_sample_valid_i(audio_sample_valid_i && mode_is_audio_w && !transition_guard_w),
        .audio_left_i(audio_left_i),
        .audio_right_i(audio_right_i),
        .audio_sample_count_i(audio_sample_count_i),
        .sample_ready_i(audio_sample_ready_w),
        .sample_o(audio_sample_w),
        .sample_valid_o(audio_sample_valid_w),
        .sample_data_o(),
        .sample_idx_o(),
        .input_accept_pulse_o(audio_adapter_admit_w),
        .input_drop_pulse_o(audio_adapter_drop_w),
        .output_accept_pulse_o(),
        .clipped_hi_pulse_o(),
        .clipped_lo_pulse_o(),
        .source_discontinuity_pulse_o(audio_discontinuity_w),
        .input_sample_count_o(),
        .output_sample_count_o(),
        .source_samples_admitted_o(),
        .dropped_sample_count_o(),
        .last_source_sample_count_o(),
        .overflow_sticky_o(audio_overflow_w),
        .disabled_drop_sticky_o(audio_disabled_drop_w),
        .clipped_hi_sticky_o(audio_clip_hi_w),
        .clipped_lo_sticky_o(audio_clip_lo_w),
        .config_error_sticky_o(audio_config_error_w)
    );

    trecap_adc_adapter #(
        .ADC_BITS(ADC_BITS)
    ) u_adc_adapter (
        .clk(clk),
        .rst_n(rst_n),
        .enable_i(enable_i && mode_is_adc_w && !transition_guard_w),
        .clear_i(source_epoch_clear_w),
        .clear_sticky_i(source_clear_sticky_w),
        .adc_sample_valid_i(adc_sample_valid_i && mode_is_adc_w && !transition_guard_w),
        .adc_sample_raw_i(adc_sample_raw_i),
        .adc_sample_count_i(adc_sample_count_i),
        .zero_code_valid_i(adc_zero_code_valid_i),
        .zero_code_i(adc_zero_code_i),
        .dc_block_enable_i(adc_dc_block_enable_i),
        .sample_ready_i(adc_sample_ready_w),
        .sample_o(adc_sample_w),
        .sample_valid_o(adc_sample_valid_w),
        .sample_data_o(),
        .sample_idx_o(),
        .input_accept_pulse_o(adc_adapter_admit_w),
        .input_drop_pulse_o(adc_adapter_drop_w),
        .output_accept_pulse_o(),
        .clipped_hi_pulse_o(),
        .clipped_lo_pulse_o(),
        .source_discontinuity_pulse_o(adc_discontinuity_w),
        .adc_samples_seen_o(),
        .source_samples_admitted_o(),
        .core_samples_accepted_o(),
        .dropped_sample_count_o(),
        .centered_preview_o(),
        .last_source_sample_count_o(),
        .dc_block_active_o(),
        .overflow_sticky_o(adc_overflow_w),
        .disabled_drop_sticky_o(adc_disabled_drop_w),
        .clipped_hi_sticky_o(adc_clip_hi_w),
        .clipped_lo_sticky_o(adc_clip_lo_w),
        .config_error_sticky_o(adc_config_error_w)
    );

    trecap_diagnostic_source #(
        .DIAGNOSTIC_PERIOD_FIXED(DIAGNOSTIC_PERIOD_FIXED)
    ) u_diagnostic_source (
        .clk(clk),
        .rst_n(rst_n),
        .enable_i(enable_i && mode_is_diagnostic_w && !transition_guard_w),
        .clear_i(source_epoch_clear_w),
        .clear_sticky_i(source_clear_sticky_w),
        .diag_mode_i(diagnostic_mode_i),
        .constant_i(diagnostic_constant_i),
        .amplitude_i(diagnostic_amplitude_i),
        .period_i(diagnostic_period_i),
        .sample_ready_i(diagnostic_sample_ready_w),
        .sample_o(diagnostic_sample_w),
        .sample_valid_o(diagnostic_sample_valid_w),
        .sample_data_o(),
        .sample_idx_o(),
        .output_accept_pulse_o(),
        .source_discontinuity_pulse_o(diagnostic_discontinuity_w),
        .samples_issued_o(),
        .samples_accepted_o(),
        .dropped_sample_count_o(),
        .lfsr_state_o(),
        .mode_error_sticky_o(diagnostic_mode_error_w),
        .disabled_sticky_o(diagnostic_disabled_w)
    );

    trecap_source_mux #(
        .RESET_SOURCE_MODE(RESET_SOURCE_MODE),
        .ACCEPT_SWITCH_WHEN_OUTPUT_IDLE(1'b1)
    ) u_source_mux (
        .clk(clk),
        .rst_n(rst_n),
        .enable_i(enable_i && !transition_guard_w),
        // Preserve the CSR-selected mode across a datapath clear. Shared rst_n is the only
        // coordinated control-plane/mux-mode reset.
        .clear_i(1'b0),
        .clear_sticky_i(source_clear_sticky_w),
        .requested_source_mode_i(requested_source_mode_i),
        .source_mode_commit_i(source_mode_apply_pulse_i),
        // The CSR bank already consumed source_safe_boundary_o. A second unrelated wait here would
        // split active CSR mode from the actual mux mode.
        .safe_to_switch_i(1'b1),
        .force_discontinuity_i(1'b0),
        .bram_sample_i(bram_sample_w),
        .bram_sample_valid_i(bram_sample_valid_w),
        .bram_sample_ready_o(bram_sample_ready_w),
        .adc_sample_i(adc_sample_w),
        .adc_sample_valid_i(adc_sample_valid_w),
        .adc_sample_ready_o(adc_sample_ready_w),
        .audio_sample_i(audio_sample_w),
        .audio_sample_valid_i(audio_sample_valid_w),
        .audio_sample_ready_o(audio_sample_ready_w),
        .diagnostic_sample_i(diagnostic_sample_w),
        .diagnostic_sample_valid_i(diagnostic_sample_valid_w),
        .diagnostic_sample_ready_o(diagnostic_sample_ready_w),
        .sample_ready_i(mux_sample_ready_w),
        .sample_o(mux_sample_w),
        .sample_valid_o(mux_sample_valid_w),
        .sample_data_o(),
        .sample_idx_o(),
        .active_source_mode_o(active_source_mode_o),
        .pending_source_mode_o(pending_source_mode_o),
        .pending_switch_o(source_switch_pending_o),
        .switch_accept_pulse_o(mux_switch_accept_w),
        .switch_apply_pulse_o(mux_switch_apply_w),
        .switch_reject_pulse_o(mux_switch_reject_w),
        .source_discontinuity_pulse_o(mux_discontinuity_w),
        .output_accept_pulse_o(mux_output_accept_w),
        .output_sample_count_o(),
        .switch_reject_count_o(),
        .invalid_source_mode_sticky_o(mux_invalid_mode_w),
        .switch_pending_sticky_o(mux_pending_sticky_w),
        .disabled_sticky_o(mux_disabled_sticky_w)
    );

    assign source_switch_apply_pulse_o = mux_switch_apply_w;
    assign replay_start_accept_pulse_o = replay_start_accept_w;
    assign replay_start_reject_pulse_o = replay_start_reject_w || replay_start_local_reject_w;
    // A phase/status level describes the held selected tail token even between sample ticks;
    // tail_tick_valid_w remains the tick-qualified handshake input to WOLA.
    assign replay_tail_drain_phase_o = selected_bram_tail_w;
    assign replay_expected_output_count_o =
        LOCAL_BUILD_CONTRACT_OK ? REPLAY_OUTPUT_SAMPLES : 64'd0;
    assign build_contract_error_o = !LOCAL_BUILD_CONTRACT_OK;

    // replay_done_o is intentionally not used as the public completion condition by itself. The
    // source can finish the final drain-token handshake while the WOLA/output skid path still owns
    // y[Ny-1]. Keep an independent accepted-output counter and wait one or more clocks for complete
    // structural quiescence before deciding PASS/FAIL for this replay epoch.
    assign replay_y_accept_w = y_valid_o && y_ready_i;
    assign replay_path_structural_busy_w = replay_active_o ||
        ((mode_is_bram_w || replay_path_inflight_q || replay_path_done_q) &&
         (mux_sample_valid_w || core_busy_o || y_valid_o));
    assign replay_path_quiescent_w = replay_done_o && !replay_path_structural_busy_w;
    assign replay_path_exact_counts_w = LOCAL_BUILD_CONTRACT_OK &&
        (replay_core_output_accept_count_q == REPLAY_OUTPUT_SAMPLES) &&
        (replay_output_accept_count_o == REPLAY_OUTPUT_SAMPLES) &&
        (wola_output_count_w == REPLAY_OUTPUT_SAMPLES) &&
        (core_sample_count_o == REPLAY_TAU_LAST) &&
        (core_frame_count_o == REPLAY_NFRAMES) &&
        (core_error_sample_count_o == REPLAY_OUTPUT_SAMPLES) &&
        // core_error_sample_count_o is a clearable aggregate. This replay-epoch counter observes
        // the same metric-commit event but is intentionally immune to CLEAR_METRICS.
        (replay_metric_commit_count_q == REPLAY_OUTPUT_SAMPLES);
    assign replay_path_fault_w = build_contract_error_o || replay_config_error_w ||
                                 replay_mem_range_error_w || replay_overrun_w ||
                                 core_protocol_error_sticky_o ||
                                 core_metric_overflow_sticky_o ||
                                 (core_overflow_flags_o != 32'd0);

    assign replay_path_busy_o = rst_n &&
        (replay_path_inflight_q || replay_path_structural_busy_w);
    assign replay_path_done_o = LOCAL_BUILD_CONTRACT_OK && replay_path_done_q &&
                                !replay_path_structural_busy_w;
    assign replay_path_done_pulse_o = replay_path_done_pulse_q;
    assign replay_core_output_accept_count_o = replay_core_output_accept_count_q;
    assign replay_completion_error_sticky_o = replay_completion_error_sticky_q;

    always_ff @(posedge clk or negedge rst_n) begin : p_replay_exact_completion
        if (!rst_n) begin
            replay_path_inflight_q                 <= 1'b0;
            replay_path_done_q                     <= 1'b0;
            replay_path_done_pulse_q               <= 1'b0;
            replay_core_output_accept_count_q      <= 64'd0;
            replay_metric_commit_count_q            <= 64'd0;
            replay_completion_error_sticky_q       <= 1'b0;
        end else begin
            replay_path_done_pulse_q <= 1'b0;

            if (clear_i || !enable_i) begin
                replay_path_inflight_q                 <= 1'b0;
                replay_path_done_q                     <= 1'b0;
                replay_core_output_accept_count_q      <= 64'd0;
                replay_metric_commit_count_q            <= 64'd0;
                replay_completion_error_sticky_q       <= 1'b0;
            end else if (replay_start_accept_w) begin
                replay_path_inflight_q                 <= 1'b1;
                replay_path_done_q                     <= 1'b0;
                replay_core_output_accept_count_q      <= 64'd0;
                replay_metric_commit_count_q            <= 64'd0;
                replay_completion_error_sticky_q       <= 1'b0;
            end else if (mode_change_request_w && replay_path_inflight_q) begin
                // A committed source change is an explicit replay abort. The common source
                // discontinuity path clears all source-dependent core state; terminate this replay
                // epoch with sticky failure instead of waiting forever for a source-done level that
                // the adapter clear intentionally removed.
                replay_path_inflight_q           <= 1'b0;
                replay_path_done_q               <= 1'b0;
                replay_completion_error_sticky_q <= 1'b1;
            end else begin
                if (mode_change_request_w && !replay_path_inflight_q) begin
                    replay_path_done_q <= 1'b0;
                    replay_core_output_accept_count_q <= 64'd0;
                    replay_metric_commit_count_q <= 64'd0;
                    replay_completion_error_sticky_q <= 1'b0;
                end else if (source_clear_sticky_w && !replay_path_inflight_q) begin
                    replay_completion_error_sticky_q <= 1'b0;
                end

                if (replay_path_inflight_q && replay_path_fault_w) begin
                    replay_completion_error_sticky_q <= 1'b1;
                end

                if (replay_y_accept_w &&
                    (replay_path_inflight_q || replay_path_done_q)) begin
                    if (!replay_path_inflight_q ||
                        (replay_core_output_accept_count_q >= REPLAY_OUTPUT_SAMPLES) ||
                        (y_sample_idx_o != replay_core_output_accept_count_q)) begin
                        replay_completion_error_sticky_q <= 1'b1;
                    end
                    if (replay_path_inflight_q &&
                        (replay_core_output_accept_count_q < REPLAY_OUTPUT_SAMPLES)) begin
                        replay_core_output_accept_count_q <=
                            replay_core_output_accept_count_q + 64'd1;
                    end
                end

                if (tap_sample_o.valid && replay_path_inflight_q) begin
                    if (replay_metric_commit_count_q >= REPLAY_OUTPUT_SAMPLES) begin
                        replay_completion_error_sticky_q <= 1'b1;
                    end else begin
                        replay_metric_commit_count_q <= replay_metric_commit_count_q + 64'd1;
                    end
                end

                if (replay_path_inflight_q && replay_path_quiescent_w) begin
                    if (replay_path_exact_counts_w && !replay_path_fault_w &&
                        !replay_completion_error_sticky_q) begin
                        replay_path_inflight_q   <= 1'b0;
                        replay_path_done_q       <= 1'b1;
                        replay_path_done_pulse_q <= 1'b1;
                    end else begin
                        // Early quiescence with an undercount, overcount, bad index, or stage fault
                        // is terminal for this epoch. End actual busy ownership but retain the
                        // error; START admission remains blocked by REARM_REQUIRED until the
                        // dedicated source/core/E2E clear owner is pulsed.
                        replay_path_inflight_q           <= 1'b0;
                        replay_path_done_q               <= 1'b0;
                        replay_completion_error_sticky_q <= 1'b1;
                    end
                end

                if (!replay_path_inflight_q && replay_path_done_q &&
                    replay_path_structural_busy_w) begin
                    replay_path_done_q <= 1'b0;
                    replay_completion_error_sticky_q <= 1'b1;
                end
            end
        end
    end

    always_comb begin
        core_sample_w = mux_sample_w;
        core_sample_w.valid = core_sample_valid_w;
    end

    trecap_core_top #(
        .SAMPLE_W(SAMPLE_W),
        .L(L),
        .P(P),
        .BIN_IDX_W(BIN_IDX_W),
        .WINDOW_FILE(WINDOW_FILE),
        .TWIDDLE_RE_FILE(TWIDDLE_RE_FILE),
        .TWIDDLE_IM_FILE(TWIDDLE_IM_FILE),
        .TWIDDLE_INV_RE_FILE(TWIDDLE_INV_RE_FILE),
        .TWIDDLE_INV_IM_FILE(TWIDDLE_INV_IM_FILE)
    ) u_core (
        .clk(clk),
        .rst_n(rst_n),
        .enable_i(enable_i),
        .clear_i(clear_i || !enable_i),
        .clear_sticky_i(core_clear_sticky_w),
        .clear_metrics_i(core_clear_metrics_w),
        .sample_i(core_sample_w),
        .sample_valid_i(core_sample_valid_w),
        .sample_ready_o(core_sample_ready_w),
        .thr2_i(thr2_i),
        .source_discontinuity_i(source_discontinuity_pulse_o),
        .finite_stream_i(mode_is_bram_w),
        .active_frame_count_i(REPLAY_NFRAMES),
        .tail_tick_valid_i(tail_tick_valid_w),
        .tail_tick_ready_o(tail_tick_ready_w),
        .tail_tick_sample_idx_i(mux_sample_w.sample_idx),
        .tail_tick_last_i(tail_tick_last_w),
        .tail_tick_count_i(REPLAY_DRAIN_SAMPLES),
        .y_valid_o(y_valid_o),
        .y_ready_i(y_ready_i),
        .y_sample_o(y_sample_o),
        .y_data_o(y_data_o),
        .y_sample_idx_o(y_sample_idx_o),
        .tap_sample_o(tap_sample_o),
        .tap_frame_o(tap_frame_o),
        .tap_bin_valid_o(tap_bin_valid_o),
        .tap_bin_frame_idx_o(tap_bin_frame_idx_o),
        .tap_bin_idx_o(tap_bin_idx_o),
        .tap_bin_re_o(tap_bin_re_o),
        .tap_bin_im_o(tap_bin_im_o),
        .tap_bin_mag2_o(tap_bin_mag2_o),
        .tap_bin_pre_mask_o(tap_bin_pre_mask_o),
        .tap_bin_mask_o(tap_bin_mask_o),
        .tap_bin_eligible_o(tap_bin_eligible_o),
        .tap_bin_last_o(tap_bin_last_o),
        .frame_boundary_pulse_o(frame_boundary_pulse_o),
        .core_alive_o(core_alive_o),
        .core_busy_o(core_busy_o),
        .core_sample_count_o(core_sample_count_o),
        .core_frame_count_o(core_frame_count_o),
        .core_error_sample_count_o(core_error_sample_count_o),
        .core_sum_abs_err_lo_o(core_sum_abs_err_lo_o),
        .core_sum_sq_err_lo_o(core_sum_sq_err_lo_o),
        .core_max_abs_err_o(core_max_abs_err_o),
        .core_metric_overflow_sticky_o(core_metric_overflow_sticky_o),
        .tail_drain_active_o(tail_drain_active_w),
        .tail_drain_accept_pulse_o(tail_drain_accept_w),
        .tail_drain_done_pulse_o(tail_drain_done_w),
        .wola_output_count_o(wola_output_count_w),
        .overflow_flags_o(core_overflow_flags_o),
        .saturation_sticky_o(core_saturation_sticky_o),
        .protocol_error_sticky_o(core_protocol_error_sticky_o)
    );

    // Only generated bits with exact semantic matches are projected into OVERFLOW_FLAGS. Other
    // source/replay faults remain on dedicated outputs until the CSR contract assigns them.
    always_comb begin
        externally_mapped_fault_levels_w = 32'd0;
        externally_mapped_fault_levels_w |=
            core_overflow_flags_o &
            (TCSR_OVERFLOW_FLAGS_ARITHMETIC_OVERFLOW_MASK |
             TCSR_OVERFLOW_FLAGS_RING_OVERFLOW_MASK);
        if (mux_invalid_mode_w || mux_switch_reject_w) begin
            externally_mapped_fault_levels_w |= TCSR_OVERFLOW_FLAGS_SOURCE_MODE_ERROR_MASK;
        end
    end

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            prior_mapped_fault_levels_q <= 32'd0;
        end else if (clear_i || !enable_i) begin
            prior_mapped_fault_levels_q <= 32'd0;
        end else begin
            // The CSR bank clears before its delayed W1C owner pulse reaches this hierarchy.
            // Re-arm each cleared owner bit so a still-high/refaulted owner emits a new event
            // after that owner-clear edge instead of being hidden behind stale edge history.
            prior_mapped_fault_levels_q <=
                externally_mapped_fault_levels_w & ~clear_sticky_flags_w1c_i;
        end
    end

    assign external_overflow_flags_set_o =
        externally_mapped_fault_levels_w & ~prior_mapped_fault_levels_q;
    // Only the CSR-owned source-mode path is projected here. Replay START also has a manual/KEY
    // origin, so the integration owner must correlate its accept/reject before incrementing the
    // CSR command counter. Manual rejects remain retained in replay_start_reject_sticky_q and the
    // public source-fault status without contaminating CSR command accounting.
    assign external_csr_reject_pulse_o = mux_switch_reject_w;

    assign source_fault_level_w = mux_invalid_mode_w || mux_pending_sticky_w ||
                                  mux_disabled_sticky_w || replay_start_reject_sticky_q ||
                                  replay_config_error_w || replay_mem_range_error_w ||
                                  replay_overrun_w || diagnostic_mode_error_w ||
                                  diagnostic_disabled_w || audio_overflow_w ||
                                  audio_disabled_drop_w || audio_clip_hi_w ||
                                  audio_clip_lo_w || audio_config_error_w ||
                                  adc_overflow_w || adc_disabled_drop_w ||
                                  adc_clip_hi_w || adc_clip_lo_w || adc_config_error_w ||
                                  build_contract_error_o ||
                                  replay_completion_error_sticky_o;
    assign source_fault_sticky_o = source_fault_level_w || live_fault_q;

    wire unused_source_events = mux_switch_accept_w ^ mux_output_accept_w ^ replay_done_pulse_w;
    wire unused_tail_status = tail_drain_active_w ^ tail_drain_accept_w ^ tail_drain_done_w ^
                              ^wola_output_count_w;
    wire unused_events = unused_source_events ^ unused_tail_status;

`ifndef SYNTHESIS
    initial begin
        if (!LOCAL_BUILD_CONTRACT_OK) begin
            $fatal(1, "trecap_source_core_integration: replay/core build contract is invalid");
        end
        if (REPLAY_START_ON_RESET_RELEASE && (RESET_SOURCE_MODE != TSRC_BRAM_REPLAY)) begin
            $fatal(1, "trecap_source_core_integration: auto-start requires BRAM reset mode");
        end
    end

    always_ff @(posedge clk) begin
        if (rst_n && !clear_i) begin
            if (core_sample_valid_w && tail_tick_valid_w) begin
                $error("trecap_source_core_integration: replay beat routed to analysis and tail together");
            end
            if (transition_guard_w && mux_sample_ready_w) begin
                $error("trecap_source_core_integration: ready asserted during source transition guard");
            end
            if (mode_is_diagnostic_w && source_handshake_w && !source_tick_i) begin
                $error("trecap_source_core_integration: diagnostic beat accepted without source tick");
            end
            if (mode_is_bram_w && source_handshake_w && !source_tick_i) begin
                $error("trecap_source_core_integration: BRAM beat accepted without source tick");
            end
            // done_o is retained history for the accepted epoch, so a later legal CLEAR_METRICS
            // may change the public aggregate count without revoking completion. The pulse edge is
            // where the exact live-count decision must hold.
            if (replay_path_done_pulse_o &&
                (!replay_path_exact_counts_w || replay_path_structural_busy_w ||
                 replay_completion_error_sticky_q)) begin
                $error("trecap_source_core_integration: replay path done without exact completion");
            end
            if (replay_core_output_accept_count_q > REPLAY_OUTPUT_SAMPLES) begin
                $error("trecap_source_core_integration: replay output count exceeded Ny");
            end
            if (replay_metric_commit_count_q > REPLAY_OUTPUT_SAMPLES) begin
                $error("trecap_source_core_integration: replay metric count exceeded Ny");
            end
        end
    end
`endif

endmodule : trecap_source_core_integration

`default_nettype wire
