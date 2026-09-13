// SPDX-License-Identifier: MIT
// File class: [1] hand-written RTL.
// Layer: rtl/platform/de1soc/
// Owner: T-RECAP Phase 2 implementation.
// Purpose: DE1-SoC board-facing top wrapper for the current T-RECAP full logical integration.
// Contract: Own physical board pins, board/HPS reset conditioning, the hand-written Platform
//           Designer boundary wrapper, and top-level logical integration.
// Generated dependencies: trecap_core_pkg, trecap_csr_pkg, trecap_packet_pkg, trecap_iface_pkg,
//                         trecap_build_pkg.

`default_nettype none

// Board-facing DE1-SoC top.
//
// Current stage:
//   This wrapper binds CLOCK/KEY/SW/LEDR/HEX, HPS DDR/peripheral pins, audio/ADC platform wrappers,
//   the source-to-core integration layer, and the logical telemetry/HPS top. Quartus-generated
//   system HDL remains a required build product, with no safe-idle substitute. All mathematical
//   processing stays in rtl/core/; this board file owns only physical and integration wiring.
module de1_soc_trecap_top
  import trecap_core_pkg::*;
  import trecap_csr_pkg::*;
  import trecap_packet_pkg::*;
  import trecap_iface_pkg::*;
  import trecap_build_pkg::*;
#(
    parameter int unsigned CSR_AVMM_ADDR_W     = 21,
    parameter int unsigned CSR_ADDR_W          = 12,
    parameter int unsigned CSR_BURSTCOUNT_W    = 1,
    parameter int unsigned PAYLOAD_DATA_W      = 32,
    parameter int unsigned PAYLOAD_KEEP_W      = (PAYLOAD_DATA_W + 7) / 8,
    parameter int unsigned PACKET_FIFO_RECORDS = 8,
    parameter int unsigned PACKET_FIFO_BYTES   = TPKT_UDP_MAX_BYTES,
    parameter int unsigned AVMM_ADDR_W         = 64,
    parameter int unsigned AVMM_DATA_W         = 64,
    parameter int unsigned AVMM_BYTEEN_W       = (AVMM_DATA_W + 7) / 8,
    parameter int unsigned AVMM_BURSTCOUNT_W   = 1,
    parameter int unsigned RESET_SYNC_STAGES   = 2,
    parameter int unsigned BOARD_RESET_RELEASE_CYCLES = 1_000_000,
    parameter int unsigned KEY_DEBOUNCE_CYCLES = 1_000_000,
    parameter int unsigned FABRIC_CLK_HZ       = 50_000_000,
    parameter int unsigned SAMPLE_TICK_HZ      = 48_000,
    parameter int unsigned SAMPLE_RATE_HZ      = SAMPLE_TICK_HZ,
    parameter int unsigned STATUS_TICK_HZ      = 10,
    parameter int unsigned METRICS_TICK_HZ     = 30,
    parameter int unsigned HEARTBEAT_TOGGLE_HZ = 2,
    parameter string       REPLAY_X_MEMH_FILE  = "artifacts/test_vectors/zero_Ns4096_thr0/x_in.memh",
    parameter int unsigned REPLAY_MEM_DEPTH    = 4096,
    parameter int unsigned REPLAY_INPUT_SAMPLES = 4096,
    parameter int unsigned AUDIO_SAMPLE_W      = 16,
    parameter int unsigned AUDIO_MCLK_HZ       = 12_288_000,
    parameter int unsigned AUDIO_I2C_BUS_HZ    = 100_000,
    parameter int unsigned ADC_BITS            = 12,
    // The board LTC2308 path has its own 100-kS/s contract.  It must not inherit the
    // 48-kHz audio/BRAM sample-rate parameter merely because all logic shares clk_fabric.
    parameter int unsigned ADC_SAMPLE_RATE_HZ  = 100_000,
    parameter int unsigned ADC_SCLK_HALF_DIV   = 10,
    parameter int unsigned ADC_CONVST_PULSE_CYCLES      = 2,
    parameter int unsigned ADC_CONVERSION_WAIT_CYCLES   = 80,
    parameter int unsigned ADC_ACQUISITION_GUARD_CYCLES = 12,
    parameter logic [2:0] ADC_DEFAULT_CHANNEL           = 3'd0,
    parameter int unsigned BIN_IDX_W           = (T_UNIQUE_BINS <= 1) ? 1 : $clog2(T_UNIQUE_BINS)
) (
    input  logic       CLOCK_50,
    input  logic       CLOCK2_50,
    input  logic       CLOCK3_50,
    input  logic       CLOCK4_50,
    input  logic [3:0] KEY,
    input  logic [9:0] SW,

    // HPS DDR3 pins owned by the generated Platform Designer HPS instance.
    output wire [14:0] HPS_DDR3_ADDR,
    output wire [2:0]  HPS_DDR3_BA,
    output wire        HPS_DDR3_CAS_N,
    output wire        HPS_DDR3_CKE,
    output wire        HPS_DDR3_CK_N,
    output wire        HPS_DDR3_CK_P,
    output wire        HPS_DDR3_CS_N,
    output wire [3:0]  HPS_DDR3_DM,
    inout  wire [31:0] HPS_DDR3_DQ,
    inout  wire [3:0]  HPS_DDR3_DQS_N,
    inout  wire [3:0]  HPS_DDR3_DQS_P,
    output wire        HPS_DDR3_ODT,
    output wire        HPS_DDR3_RAS_N,
    output wire        HPS_DDR3_RESET_N,
    input  wire        HPS_DDR3_RZQ,
    output wire        HPS_DDR3_WE_N,

    // HPS hard-peripheral pins selected by the frozen Terasic Rev-H pin-mux preset.
    output wire        HPS_ENET_GTX_CLK,
    inout  wire        HPS_ENET_INT_N,
    output wire        HPS_ENET_MDC,
    inout  wire        HPS_ENET_MDIO,
    input  wire        HPS_ENET_RX_CLK,
    input  wire [3:0]  HPS_ENET_RX_DATA,
    input  wire        HPS_ENET_RX_DV,
    output wire [3:0]  HPS_ENET_TX_DATA,
    output wire        HPS_ENET_TX_EN,
    inout  wire [3:0]  HPS_FLASH_DATA,
    output wire        HPS_FLASH_DCLK,
    output wire        HPS_FLASH_NCSO,
    inout  wire        HPS_GSENSOR_INT,
    inout  wire        HPS_I2C_CONTROL,
    inout  wire        HPS_I2C1_SCLK,
    inout  wire        HPS_I2C1_SDAT,
    inout  wire        HPS_I2C2_SCLK,
    inout  wire        HPS_I2C2_SDAT,
    inout  wire        HPS_KEY,
    inout  wire        HPS_LED,
    inout  wire        HPS_LTC_GPIO,
    output wire        HPS_SD_CLK,
    inout  wire        HPS_SD_CMD,
    inout  wire [3:0]  HPS_SD_DATA,
    output wire        HPS_SPIM_CLK,
    input  wire        HPS_SPIM_MISO,
    output wire        HPS_SPIM_MOSI,
    output wire        HPS_SPIM_SS,
    input  wire        HPS_UART_RX,
    output wire        HPS_UART_TX,
    inout  wire        HPS_CONV_USB_N,
    input  wire        HPS_USB_CLKOUT,
    inout  wire [7:0]  HPS_USB_DATA,
    input  wire        HPS_USB_DIR,
    input  wire        HPS_USB_NXT,
    output wire        HPS_USB_STP,

    output logic [9:0] LEDR,
    output logic [6:0] HEX0,
    output logic [6:0] HEX1,
    output logic [6:0] HEX2,
    output logic [6:0] HEX3,
    output logic [6:0] HEX4,
    output logic [6:0] HEX5,

    // Audio codec data/clock pins plus the FPGA side of the board codec-control I2C mux.
    // HPS_I2C_CONTROL must remain low while the FPGA owns codec initialization.
    input  wire        AUD_ADCDAT,
    inout  wire        AUD_ADCLRCK,
    inout  wire        AUD_BCLK,
    output logic       AUD_DACDAT,
    inout  wire        AUD_DACLRCK,
    output logic       AUD_XCK,
    output wire        FPGA_I2C_SCLK,
    inout  wire        FPGA_I2C_SDAT,

    // External LTC2308 serial pins.  ADC_CS_N is the legacy top-level alias for physical CONVST;
    // despite its suffix, idle is low and a high pulse starts conversion.
    output logic       ADC_CS_N,
    output logic       ADC_DIN,
    input  wire        ADC_DOUT,
    output logic       ADC_SCLK
);

    logic clk_fabric;
    logic rst_n_platform;
    logic h2f_reset_n;
    logic [3:0] key_level;
    logic [3:0] key_press_pulse;
    logic [3:0] key_release_pulse;
    logic [9:0] sw_sync;
    logic sample_tick;
    logic status_tick;
    logic metrics_tick;
    logic heartbeat_toggle;
    logic heartbeat;

    trecap_core_tap_sample_t tap_sample;
    trecap_core_tap_frame_t  tap_frame;

    logic                         tap_bin_valid;
    logic [63:0]                  tap_bin_frame_idx;
    logic [BIN_IDX_W-1:0]         tap_bin_idx;
    logic signed [T_CAN_W-1:0]    tap_bin_re;
    logic signed [T_CAN_W-1:0]    tap_bin_im;
    logic [T_MAG2_W-1:0]          tap_bin_mag2;
    logic                         tap_bin_pre_mask;
    logic                         tap_bin_mask;
    logic                         tap_bin_eligible;
    logic                         tap_bin_last;

    // Platform source wrappers emit raw samples in clk_fabric. Scaling and source selection live
    // exclusively in trecap_source_core_integration.
    logic                         audio_sample_valid;
    logic signed [AUDIO_SAMPLE_W-1:0] audio_left;
    logic signed [AUDIO_SAMPLE_W-1:0] audio_right;
    logic [63:0]                  audio_sample_count;
    logic                         audio_active;
    logic                         audio_frame_overrun_sticky;
    logic                         audio_lineout_overrun_sticky;
    logic                         audio_lineout_underflow_sticky;
    logic                         audio_bclk_seen_sticky;
    logic                         audio_lrck_seen_sticky;
    logic                         audio_lineout_ready;
    logic                         audio_capture_enable;
    logic                         audio_lineout_monitor_enable;
    logic signed [AUDIO_SAMPLE_W-1:0] core_y_audio_scaled;
    logic                         audio_mclk;
    logic                         audio_pll_locked;
    logic                         audio_pll_config_supported;
    (* async_reg = "true" *)
    (* preserve = "true" *)
    (* altera_attribute = "-name SYNCHRONIZER_IDENTIFICATION FORCED" *)
    logic [1:0]                   audio_i2c_bus_grant_sync_q;
    logic                         audio_i2c_bus_grant;
    logic                         audio_i2c_prerequisites;
    logic                         audio_i2c_prerequisites_d_q;
    logic                         audio_i2c_start;
    logic                         audio_i2c_start_ready;
    logic                         audio_i2c_start_accept;
    logic                         audio_i2c_start_reject;
    logic                         audio_i2c_busy;
    logic                         audio_codec_init_done;
    logic                         audio_codec_init_done_pulse;
    logic                         audio_codec_init_error_sticky;
    logic                         audio_codec_nack_sticky;
    logic                         audio_i2c_unsupported;
    logic [31:0]                  audio_i2c_ack_error_count;
    logic [31:0]                  audio_i2c_retry_count;
    logic [31:0]                  audio_i2c_bus_abort_count;
    logic [31:0]                  audio_i2c_config_write_count;
    logic [3:0]                   audio_i2c_register_index;
    logic                         audio_codec_ready;
    logic [63:0]                  audio_rx_overflow_count;
    logic [63:0]                  audio_tx_overflow_count;
    logic [63:0]                  audio_tx_underflow_count;

    logic                         adc_sample_valid;
    logic [ADC_BITS-1:0]          adc_sample_raw;
    logic signed [ADC_BITS:0]     adc_centered_preview;
    logic [63:0]                  adc_sample_count;
    logic                         adc_busy;
    logic                         adc_transaction_done;
    logic                         adc_request_overrun_sticky;
    logic                         adc_protocol_error_sticky;
    logic                         adc_source_enable;
    logic                         adc_source_enable_d_q;
    logic                         adc_epoch_ready;
    logic                         adc_continuous_enable;
    logic                         adc_manual_request;
    logic [2:0]                   adc_channel_active_q;
    logic [5:0]                   adc_command;

    trecap_sample_t               core_y_sample;
    logic                         core_y_valid;
    logic signed [T_SAMPLE_W-1:0] core_y_data;
    logic [63:0]                  core_y_sample_idx;
    logic                         core_frame_boundary;
    logic                         core_config_safe_boundary;
    logic                         source_core_safe_boundary;
    trecap_source_mode_e          active_source_mode;
    trecap_source_mode_e          pending_source_mode;
    logic                         source_switch_pending;
    logic                         source_switch_apply;
    logic                         source_discontinuity;
    logic                         core_alive;
    logic                         core_busy;
    logic [63:0]                  core_sample_count;
    logic [63:0]                  core_frame_count;
    logic [63:0]                  core_error_sample_count;
    logic [63:0]                  core_sum_abs_err_lo;
    logic [63:0]                  core_sum_sq_err_lo;
    logic [15:0]                  core_max_abs_err;
    logic                         core_metric_overflow_sticky;
    logic                         core_clear_metrics_apply_pulse;
    logic [31:0]                  core_overflow_flags;
    logic                         core_saturation_sticky;
    logic                         core_protocol_error_sticky;
    logic                         replay_active;
    logic                         replay_done;
    logic                         replay_input_phase;
    logic                         replay_flush_phase;
    logic                         replay_tail_drain_phase;
    logic                         replay_start_accept;
    logic                         replay_start_reject;
    logic                         replay_start_ready;
    logic [63:0]                  replay_output_accept_count;
    logic [63:0]                  replay_expected_output_count;
    logic                         replay_path_busy;
    logic                         replay_path_done;
    logic                         replay_path_done_pulse;
    logic [63:0]                  replay_core_output_accept_count;
    logic                         replay_completion_error_sticky;
    logic                         replay_e2e_busy;
    logic                         replay_e2e_done;
    logic                         replay_e2e_done_pulse;
    logic                         replay_e2e_error_sticky;
    logic                         replay_start_admit;
    logic                         status_tick_to_transport;
    logic                         replay_e2e_transport_ready;
    logic                         replay_e2e_completion_fault;
    logic                         replay_e2e_transport_fault;
    logic                         replay_error;
    logic                         replay_rearm_required;
    logic                         csr_counter_clear;
    logic                         csr_replay_start;
    logic                         csr_replay_rearm;
    logic                         replay_epoch_clear;
    logic [1:0]                   replay_request_origin_q;
    logic                         csr_replay_queued_q;
    logic                         csr_replay_forward;
    logic                         key_replay_forward;
    logic                         replay_owner_start;
    logic                         replay_owner_terminal;
    logic                         replay_request_busy;
    logic                         csr_replay_feedback_enable;
    logic                         csr_replay_accept_feedback;
    logic                         csr_replay_reject_feedback;
    logic                         csr_replay_abort_reject_q;
    logic                         csr_command_reject_event;
    logic                         source_fault_sticky;
    logic                         source_core_build_contract_error;
    logic [31:0]                  source_core_overflow_flags_set;
    logic                         source_core_csr_reject_pulse;

    // Typed Platform Designer/HPS boundary.  Qsys performs AXI3-to-Avalon adaptation before the
    // CSR signals reach this module; the hand-written wrapper performs only typed binding/policy.
    logic [CSR_AVMM_ADDR_W-1:0]   csr_avs_address;
    logic                         csr_avs_read;
    logic                         csr_avs_write;
    logic [31:0]                  csr_avs_writedata;
    logic [3:0]                   csr_avs_byteenable;
    logic [CSR_BURSTCOUNT_W-1:0]  csr_avs_burstcount;
    logic                         csr_avs_waitrequest;
    logic [31:0]                  csr_avs_readdata;
    logic                         csr_avs_readdatavalid;
    logic                         csr_avs_writeresponsevalid;
    logic [1:0]                   csr_avs_response;

    logic [AVMM_ADDR_W-1:0]       avm_address;
    logic                         avm_write;
    logic [AVMM_DATA_W-1:0]       avm_writedata;
    logic [AVMM_BYTEEN_W-1:0]     avm_byteenable;
    logic [AVMM_BURSTCOUNT_W-1:0] avm_burstcount;
    logic                         avm_waitrequest;
    logic                         avm_writeresponsevalid;
    logic [1:0]                   avm_response;

    trecap_hps_bridge_ctrl_t      ctrl;
    trecap_ring_config_t          ring_config;
    logic                         telemetry_soft_reset_pulse;
    logic                         clear_metrics_pulse;
    logic                         thr2_apply_pulse;
    logic                         source_mode_apply_pulse;
    logic [31:0]                  clear_sticky_flags_w1c;
    logic                         ring_config_commit_pulse;
    logic                         ring_wr_snapshot_req_pulse;
    logic                         ring_rd_commit_req_pulse;
    logic                         core_count_snapshot_pulse;

    logic [31:0]                  packet_fifo_drop_count;
    logic                         packet_fifo_drop_pulse;
    logic                         packet_fifo_full;
    logic                         packet_fifo_overflow;
    logic                         scheduler_backpressure;
    logic                         scheduler_disabled_drop;
    logic                         scheduler_illegal_drop;
    logic [31:0]                  status;
    logic [31:0]                  dma_status;
    logic [31:0]                  overflow_flags;
    logic [31:0]                  csr_command_reject_count;
    logic [31:0]                  dma_drop_count;
    logic [31:0]                  dma_packet_count;
    logic [63:0]                  producer_ptr;
    logic [63:0]                  consumer_ptr;
    logic [31:0]                  telemetry_sequence;
    logic [63:0]                  used_bytes;
    logic [63:0]                  free_bytes;
    logic [63:0]                  current_offset;
    logic [63:0]                  current_tail_bytes;
    logic                         writer_idle;
    logic                         writer_busy;
    logic                         writer_no_space;
    logic                         malformed_config;
    logic                         ring_full;
    logic                         ddr_wait;
    logic                         drop_active;
    logic                         ring_configured;
    logic                         pointers_valid;
    logic                         writer_fault_sticky;
    logic                         normal_commit_pulse;
    logic                         wrap_commit_pulse;
    logic                         writer_drop_pulse;
    logic                         writer_malformed_pulse;
    logic                         writer_oversized_pulse;
    logic                         ring_rd_accept_pulse;
    logic                         ring_rd_reject_pulse;
    logic                         writer_ring_wr_snapshot_valid;
    logic                         writer_ring_wr_snapshot_pulse;
    logic                         packet_fifo_full_status;
    logic                         packet_fifo_overflow_status;
    logic                         packet_enable_illegal;
    logic                         spec_mode_illegal;
    logic                         spec_shift_illegal;
    logic                         wave_decim_illegal;
    logic                         telemetry_config_illegal;
    logic                         telemetry_active;
    logic                         core_tap_seen;
    logic                         full_path_alive;
    logic                         transport_epoch_idle;
    logic                         transport_epoch_idle_stable;
    logic                         rst_n_sync_from_full_top;

    localparam logic [31:0]          SAMPLE_RATE_HZ_U32 = SAMPLE_RATE_HZ;
    localparam logic [31:0]          ADC_SAMPLE_RATE_HZ_U32 = ADC_SAMPLE_RATE_HZ;
    localparam logic [1:0]           REPLAY_ORIGIN_NONE = 2'd0;
    localparam logic [1:0]           REPLAY_ORIGIN_KEY  = 2'd1;
    localparam logic [1:0]           REPLAY_ORIGIN_CSR  = 2'd2;
    localparam logic signed [T_SAMPLE_W-1:0] DIAGNOSTIC_AMPLITUDE =
        T_SAMPLE_W'(1 << (T_SAMPLE_W - 2));

    logic [23:0] display_word;
    logic [31:0] telemetry_sample_rate_hz;

    function automatic logic [6:0] hex7seg_active_low(input logic [3:0] value);
        unique case (value)
            4'h0: hex7seg_active_low = 7'b100_0000;
            4'h1: hex7seg_active_low = 7'b111_1001;
            4'h2: hex7seg_active_low = 7'b010_0100;
            4'h3: hex7seg_active_low = 7'b011_0000;
            4'h4: hex7seg_active_low = 7'b001_1001;
            4'h5: hex7seg_active_low = 7'b001_0010;
            4'h6: hex7seg_active_low = 7'b000_0010;
            4'h7: hex7seg_active_low = 7'b111_1000;
            4'h8: hex7seg_active_low = 7'b000_0000;
            4'h9: hex7seg_active_low = 7'b001_0000;
            4'ha: hex7seg_active_low = 7'b000_1000;
            4'hb: hex7seg_active_low = 7'b000_0011;
            4'hc: hex7seg_active_low = 7'b100_0110;
            4'hd: hex7seg_active_low = 7'b010_0001;
            4'he: hex7seg_active_low = 7'b000_0110;
            4'hf: hex7seg_active_low = 7'b000_1110;
            default: hex7seg_active_low = 7'b111_1111;
        endcase
    endfunction : hex7seg_active_low

    // LTC2308 DIN order is {S/D,O/S,S1,S0,UNI,SLP}.  This mapping matches Terasic's
    // single-ended, unipolar, awake channel table: 8,C,9,D,A,E,B,F for channels 0..7.
    function automatic logic [5:0] ltc2308_single_ended_command(input logic [2:0] channel);
        ltc2308_single_ended_command =
            {1'b1, channel[0], channel[2], channel[1], 1'b1, 1'b0};
    endfunction : ltc2308_single_ended_command

    localparam logic [5:0] ADC_DEFAULT_COMMAND =
        ltc2308_single_ended_command(ADC_DEFAULT_CHANNEL);

    clock_reset_ctrl #(
        .RESET_SYNC_STAGES(RESET_SYNC_STAGES),
        .BOARD_RESET_RELEASE_CYCLES(BOARD_RESET_RELEASE_CYCLES),
        .KEY_DEBOUNCE_CYCLES(KEY_DEBOUNCE_CYCLES),
        .FABRIC_CLK_HZ(FABRIC_CLK_HZ),
        .SAMPLE_TICK_HZ(SAMPLE_TICK_HZ),
        .STATUS_TICK_HZ(STATUS_TICK_HZ),
        .METRICS_TICK_HZ(METRICS_TICK_HZ),
        .HEARTBEAT_TOGGLE_HZ(HEARTBEAT_TOGGLE_HZ)
    ) u_clock_reset_ctrl (
        .CLOCK_50(CLOCK_50),
        .h2f_reset_n_i(h2f_reset_n),
        .KEY(KEY),
        .SW(SW),
        .clk_fabric_o(clk_fabric),
        .rst_n_platform_o(rst_n_platform),
        .key_level_o(key_level),
        .key_press_pulse_o(key_press_pulse),
        .key_release_pulse_o(key_release_pulse),
        .sw_sync_o(sw_sync),
        .sample_tick_o(sample_tick),
        .status_tick_o(status_tick),
        .metrics_tick_o(metrics_tick),
        .heartbeat_toggle_o(heartbeat_toggle),
        .heartbeat_o(heartbeat)
    );

    // clock_reset_ctrl is the sole owner of rst_n_platform.  It combines the qualified physical
    // reset request with H2F reset, asserts asynchronously, and synchronizes release once for this
    // single 50 MHz fabric domain.  Qsys reset_n_reset_n reaches clk_0 and the typed bridges; it
    // does not reset the HPS block that produces h2f_reset_n, so the connection is not a reset loop.
    platform_designer_wrapper #(
        .CSR_ADDR_W(CSR_AVMM_ADDR_W),
        .CSR_DATA_W(32),
        .CSR_BYTEEN_W(4),
        .CSR_BURSTCOUNT_W(CSR_BURSTCOUNT_W),
        .AVMM_ADDR_W(AVMM_ADDR_W),
        .AVMM_DATA_W(AVMM_DATA_W),
        .AVMM_BYTEEN_W(AVMM_BYTEEN_W),
        .AVMM_BURSTCOUNT_W(AVMM_BURSTCOUNT_W),
        .PD_DDR_ADDR_W(32),
        .PD_DDR_BURSTCOUNT_W(1)
    ) u_platform_designer_wrapper (
        .clk_50_i(clk_fabric),
        .bridge_reset_n_i(rst_n_platform),
        .h2f_reset_n_o(h2f_reset_n),
        .HPS_DDR3_ADDR(HPS_DDR3_ADDR),
        .HPS_DDR3_BA(HPS_DDR3_BA),
        .HPS_DDR3_CAS_N(HPS_DDR3_CAS_N),
        .HPS_DDR3_CKE(HPS_DDR3_CKE),
        .HPS_DDR3_CK_N(HPS_DDR3_CK_N),
        .HPS_DDR3_CK_P(HPS_DDR3_CK_P),
        .HPS_DDR3_CS_N(HPS_DDR3_CS_N),
        .HPS_DDR3_DM(HPS_DDR3_DM),
        .HPS_DDR3_DQ(HPS_DDR3_DQ),
        .HPS_DDR3_DQS_N(HPS_DDR3_DQS_N),
        .HPS_DDR3_DQS_P(HPS_DDR3_DQS_P),
        .HPS_DDR3_ODT(HPS_DDR3_ODT),
        .HPS_DDR3_RAS_N(HPS_DDR3_RAS_N),
        .HPS_DDR3_RESET_N(HPS_DDR3_RESET_N),
        .HPS_DDR3_RZQ(HPS_DDR3_RZQ),
        .HPS_DDR3_WE_N(HPS_DDR3_WE_N),
        .HPS_ENET_GTX_CLK(HPS_ENET_GTX_CLK),
        .HPS_ENET_INT_N(HPS_ENET_INT_N),
        .HPS_ENET_MDC(HPS_ENET_MDC),
        .HPS_ENET_MDIO(HPS_ENET_MDIO),
        .HPS_ENET_RX_CLK(HPS_ENET_RX_CLK),
        .HPS_ENET_RX_DATA(HPS_ENET_RX_DATA),
        .HPS_ENET_RX_DV(HPS_ENET_RX_DV),
        .HPS_ENET_TX_DATA(HPS_ENET_TX_DATA),
        .HPS_ENET_TX_EN(HPS_ENET_TX_EN),
        .HPS_FLASH_DATA(HPS_FLASH_DATA),
        .HPS_FLASH_DCLK(HPS_FLASH_DCLK),
        .HPS_FLASH_NCSO(HPS_FLASH_NCSO),
        .HPS_GSENSOR_INT(HPS_GSENSOR_INT),
        .HPS_I2C_CONTROL(HPS_I2C_CONTROL),
        .HPS_I2C1_SCLK(HPS_I2C1_SCLK),
        .HPS_I2C1_SDAT(HPS_I2C1_SDAT),
        .HPS_I2C2_SCLK(HPS_I2C2_SCLK),
        .HPS_I2C2_SDAT(HPS_I2C2_SDAT),
        .HPS_KEY(HPS_KEY),
        .HPS_LED(HPS_LED),
        .HPS_LTC_GPIO(HPS_LTC_GPIO),
        .HPS_SD_CLK(HPS_SD_CLK),
        .HPS_SD_CMD(HPS_SD_CMD),
        .HPS_SD_DATA(HPS_SD_DATA),
        .HPS_SPIM_CLK(HPS_SPIM_CLK),
        .HPS_SPIM_MISO(HPS_SPIM_MISO),
        .HPS_SPIM_MOSI(HPS_SPIM_MOSI),
        .HPS_SPIM_SS(HPS_SPIM_SS),
        .HPS_UART_RX(HPS_UART_RX),
        .HPS_UART_TX(HPS_UART_TX),
        .HPS_CONV_USB_N(HPS_CONV_USB_N),
        .HPS_USB_CLKOUT(HPS_USB_CLKOUT),
        .HPS_USB_DATA(HPS_USB_DATA),
        .HPS_USB_DIR(HPS_USB_DIR),
        .HPS_USB_NXT(HPS_USB_NXT),
        .HPS_USB_STP(HPS_USB_STP),
        .csr_avs_address_o(csr_avs_address),
        .csr_avs_read_o(csr_avs_read),
        .csr_avs_write_o(csr_avs_write),
        .csr_avs_writedata_o(csr_avs_writedata),
        .csr_avs_byteenable_o(csr_avs_byteenable),
        .csr_avs_burstcount_o(csr_avs_burstcount),
        .csr_avs_waitrequest_i(csr_avs_waitrequest),
        .csr_avs_readdata_i(csr_avs_readdata),
        .csr_avs_readdatavalid_i(csr_avs_readdatavalid),
        .csr_avs_writeresponsevalid_i(csr_avs_writeresponsevalid),
        .csr_avs_response_i(csr_avs_response),
        .avm_address_i(avm_address),
        .avm_write_i(avm_write),
        .avm_writedata_i(avm_writedata),
        .avm_byteenable_i(avm_byteenable),
        .avm_burstcount_i(avm_burstcount),
        .avm_waitrequest_o(avm_waitrequest),
        .avm_writeresponsevalid_o(avm_writeresponsevalid),
        .avm_response_o(avm_response)
    );

    // Board/platform source capture. These wrappers do not scale ingress samples and cannot bypass
    // the source mux. Step 16 owns a 12.288 MHz PLL output and deterministic WM8731 setup, but the
    // checked-in source still does not constitute PLL, I2C-ACK, timing, or physical audio evidence.
    // Until a later CSR revision allocates dedicated live-source diagnostic bits, the existing
    // SOURCE_MODE_ERROR W1C bit is used only as a local clear request for wrapper diagnostics;
    // those wrapper levels are deliberately not reported as SOURCE_MODE_ERROR set events.
    //
    // Board controls are deliberately disjoint: SW[2:0] selects diagnostic stimulus, SW[3]
    // enables the best-effort processed-output monitor, SW[6:4] selects the ADC channel, SW[7]
    // selects continuous (0) versus debounced KEY[2] one-shot (1) ADC requests, and SW[9:8]
    // selects the hexadecimal display page. The ADC channel is sampled only on entry to ADC mode;
    // changing switches within an ADC source epoch cannot mix channels in one core history.
    assign audio_capture_enable = (active_source_mode == TSRC_AUDIO_WRAPPER) &&
                                  audio_codec_ready;
    assign audio_lineout_monitor_enable = sw_sync[3] && !source_discontinuity &&
                                          audio_codec_ready;
    assign core_y_audio_scaled = $signed(AUDIO_SAMPLE_W'(core_y_data)) <<<
        ((AUDIO_SAMPLE_W > T_SAMPLE_W) ? (AUDIO_SAMPLE_W - T_SAMPLE_W) : 0);

    assign adc_source_enable = (active_source_mode == TSRC_ADC_LIVE);
    assign adc_epoch_ready = adc_source_enable && adc_source_enable_d_q;
    assign adc_continuous_enable = adc_epoch_ready && !sw_sync[7];
    assign adc_manual_request = adc_epoch_ready && sw_sync[7] && key_press_pulse[2];
    assign adc_command = ltc2308_single_ended_command(adc_channel_active_q);
    // STATUS/METRICS metadata must describe the selected physical source.  BRAM replay,
    // diagnostic, and codec LINE-IN use the canonical 48-kHz rate; LTC2308 uses 100 kS/s.
    assign telemetry_sample_rate_hz = adc_source_enable ?
                                      ADC_SAMPLE_RATE_HZ_U32 : SAMPLE_RATE_HZ_U32;

    always_ff @(posedge clk_fabric or negedge rst_n_platform) begin
        if (!rst_n_platform) begin
            adc_source_enable_d_q <= 1'b0;
            adc_channel_active_q <= ADC_DEFAULT_CHANNEL;
        end else begin
            adc_source_enable_d_q <= adc_source_enable;
            if (adc_source_enable && !adc_source_enable_d_q) begin
                adc_channel_active_q <= sw_sync[6:4];
            end
        end
    end

    // The board codec-control mux belongs to HPS GPIO48. Low selects the FPGA I2C pins; the FPGA
    // observes that grant but never drives HPS_I2C_CONTROL. Unknown/floating ownership therefore
    // fails closed and prevents both I2C activity and live-sample admission.
    always_ff @(posedge clk_fabric or negedge rst_n_platform) begin
        if (!rst_n_platform) begin
            audio_i2c_bus_grant_sync_q <= '0;
            audio_i2c_prerequisites_d_q <= 1'b0;
        end else begin
            audio_i2c_bus_grant_sync_q <= {
                audio_i2c_bus_grant_sync_q[0],
                ~HPS_I2C_CONTROL
            };
            if (clear_sticky_flags_w1c[TCSR_OVERFLOW_FLAGS_SOURCE_MODE_ERROR_LSB] ||
                !audio_i2c_prerequisites) begin
                audio_i2c_prerequisites_d_q <= 1'b0;
            end else begin
                audio_i2c_prerequisites_d_q <= 1'b1;
            end
        end
    end

    assign audio_i2c_bus_grant = audio_i2c_bus_grant_sync_q[1];
    assign audio_i2c_prerequisites = audio_pll_locked &&
                                      audio_pll_config_supported &&
                                      audio_i2c_bus_grant;
    assign audio_i2c_start = audio_i2c_prerequisites &&
                              !audio_i2c_prerequisites_d_q;
    assign audio_codec_ready = audio_i2c_prerequisites &&
                               audio_codec_init_done &&
                               !audio_i2c_start &&
                               !audio_i2c_busy &&
                               !audio_codec_init_error_sticky &&
                               !audio_i2c_unsupported;

    audio_pll_wrapper #(
        .REF_CLK_HZ(FABRIC_CLK_HZ),
        .AUDIO_MCLK_HZ(AUDIO_MCLK_HZ)
    ) u_audio_pll_wrapper (
        .ref_clk_i(clk_fabric),
        .rst_n_i(rst_n_platform),
        .audio_mclk_o(audio_mclk),
        .locked_o(audio_pll_locked),
        .config_supported_o(audio_pll_config_supported)
    );

    audio_codec_i2c_init #(
        .CLK_HZ(FABRIC_CLK_HZ),
        .I2C_BUS_HZ(AUDIO_I2C_BUS_HZ),
        .AUDIO_MCLK_HZ(AUDIO_MCLK_HZ),
        .AUDIO_SAMPLE_RATE_HZ(SAMPLE_RATE_HZ),
        .AUDIO_WORD_W(AUDIO_SAMPLE_W),
        .CODEC_I2C_ADDRESS(7'h1a)
    ) u_audio_codec_i2c_init (
        .clk(clk_fabric),
        .rst_n(rst_n_platform),
        .enable_i(audio_pll_locked && audio_pll_config_supported),
        .bus_grant_i(audio_i2c_bus_grant),
        .start_i(audio_i2c_start),
        .clear_sticky_i(clear_sticky_flags_w1c[TCSR_OVERFLOW_FLAGS_SOURCE_MODE_ERROR_LSB]),
        .start_ready_o(audio_i2c_start_ready),
        .start_accept_pulse_o(audio_i2c_start_accept),
        .start_reject_pulse_o(audio_i2c_start_reject),
        .busy_o(audio_i2c_busy),
        .config_done_o(audio_codec_init_done),
        .config_done_pulse_o(audio_codec_init_done_pulse),
        .config_error_sticky_o(audio_codec_init_error_sticky),
        .nack_seen_sticky_o(audio_codec_nack_sticky),
        .unsupported_config_o(audio_i2c_unsupported),
        .ack_error_count_o(audio_i2c_ack_error_count),
        .retry_count_o(audio_i2c_retry_count),
        .bus_abort_count_o(audio_i2c_bus_abort_count),
        .config_write_count_o(audio_i2c_config_write_count),
        .register_index_o(audio_i2c_register_index),
        .FPGA_I2C_SCLK(FPGA_I2C_SCLK),
        .FPGA_I2C_SDAT(FPGA_I2C_SDAT)
    );

    audio_codec_wrapper #(
        .AUDIO_SAMPLE_W(AUDIO_SAMPLE_W),
        .SAMPLE_RATE_HZ(SAMPLE_RATE_HZ),
        .AUDIO_MCLK_HZ(AUDIO_MCLK_HZ)
    ) u_audio_codec_wrapper (
        .clk(clk_fabric),
        .rst_n(rst_n_platform),
        .codec_ready_i(audio_codec_ready),
        .audio_mclk_i(audio_mclk),
        .enable_i(audio_capture_enable),
        .clear_sticky_i(clear_sticky_flags_w1c[TCSR_OVERFLOW_FLAGS_SOURCE_MODE_ERROR_LSB]),
        .lineout_enable_i(audio_lineout_monitor_enable),
        .lineout_flush_i(source_discontinuity),
        .lineout_left_i(core_y_audio_scaled),
        .lineout_right_i(core_y_audio_scaled),
        .lineout_valid_i(core_y_valid),
        .lineout_ready_o(audio_lineout_ready),
        .AUD_ADCDAT(AUD_ADCDAT),
        .AUD_ADCLRCK(AUD_ADCLRCK),
        .AUD_BCLK(AUD_BCLK),
        .AUD_DACDAT(AUD_DACDAT),
        .AUD_DACLRCK(AUD_DACLRCK),
        .AUD_XCK(AUD_XCK),
        .audio_sample_valid_o(audio_sample_valid),
        .audio_left_o(audio_left),
        .audio_right_o(audio_right),
        .audio_sample_count_o(audio_sample_count),
        .audio_active_o(audio_active),
        .frame_overrun_sticky_o(audio_frame_overrun_sticky),
        .lineout_overrun_sticky_o(audio_lineout_overrun_sticky),
        .lineout_underflow_sticky_o(audio_lineout_underflow_sticky),
        .bclk_seen_sticky_o(audio_bclk_seen_sticky),
        .lrck_seen_sticky_o(audio_lrck_seen_sticky),
        .audio_rx_overflow_count_o(audio_rx_overflow_count),
        .audio_tx_overflow_count_o(audio_tx_overflow_count),
        .audio_tx_underflow_count_o(audio_tx_underflow_count)
    );

    adc_wrapper #(
        .CLK_HZ(FABRIC_CLK_HZ),
        .SAMPLE_RATE_HZ(ADC_SAMPLE_RATE_HZ),
        .SCLK_HALF_DIV(ADC_SCLK_HALF_DIV),
        .FRAME_BITS(12),
        .COMMAND_BITS(6),
        .ADC_BITS(ADC_BITS),
        .CONVST_PULSE_CYCLES(ADC_CONVST_PULSE_CYCLES),
        .CONVERSION_WAIT_CYCLES(ADC_CONVERSION_WAIT_CYCLES),
        .ACQUISITION_GUARD_CYCLES(ADC_ACQUISITION_GUARD_CYCLES),
        .DEFAULT_COMMAND(ADC_DEFAULT_COMMAND)
    ) u_adc_wrapper (
        .clk(clk_fabric),
        .rst_n(rst_n_platform),
        .enable_i(adc_source_enable),
        .clear_sticky_i(clear_sticky_flags_w1c[TCSR_OVERFLOW_FLAGS_SOURCE_MODE_ERROR_LSB]),
        .continuous_enable_i(adc_continuous_enable),
        .sample_request_i(adc_manual_request),
        .command_i(adc_command),
        .command_valid_i(1'b1),
        .sample_valid_o(adc_sample_valid),
        .sample_raw_o(adc_sample_raw),
        .sample_centered_preview_o(adc_centered_preview),
        .sample_count_o(adc_sample_count),
        .busy_o(adc_busy),
        .transaction_done_pulse_o(adc_transaction_done),
        .request_overrun_sticky_o(adc_request_overrun_sticky),
        .protocol_error_sticky_o(adc_protocol_error_sticky),
        .ADC_CS_N(ADC_CS_N),
        .ADC_DIN(ADC_DIN),
        .ADC_DOUT(ADC_DOUT),
        .ADC_SCLK(ADC_SCLK)
    );

    // Serialize board KEY1 and CSR START through the sole replay owner. CSR wins when both arrive
    // idle. One CSR pulse may wait behind a KEY-origin request until its registered terminal result
    // is consumed, preventing adjacent KEY feedback from completing the host command epoch.
    assign replay_epoch_clear = key_press_pulse[3] || csr_replay_rearm;
    assign csr_replay_forward = !replay_epoch_clear &&
                                (replay_request_origin_q == REPLAY_ORIGIN_NONE) &&
                                (csr_replay_queued_q || csr_replay_start);
    assign key_replay_forward = !replay_epoch_clear &&
                                (replay_request_origin_q == REPLAY_ORIGIN_NONE) &&
                                !csr_replay_forward && key_press_pulse[1];
    assign replay_owner_start = csr_replay_forward || key_replay_forward;
    assign replay_owner_terminal = replay_start_accept || replay_start_reject;
    // Keep REARM admission loop-free: this term observes raw requests before
    // replay_epoch_clear gates the sole-owner forwarding path.
    assign replay_request_busy =
        (replay_request_origin_q != REPLAY_ORIGIN_NONE) || csr_replay_queued_q ||
        csr_replay_start || key_press_pulse[1];
    assign csr_replay_feedback_enable =
        (replay_request_origin_q == REPLAY_ORIGIN_CSR) ||
        ((replay_request_origin_q == REPLAY_ORIGIN_NONE) && csr_replay_forward);
    assign csr_replay_accept_feedback =
        !replay_epoch_clear && replay_start_accept && csr_replay_feedback_enable;
    assign csr_replay_reject_feedback =
        (!replay_epoch_clear && replay_start_reject && csr_replay_feedback_enable) ||
        csr_replay_abort_reject_q;
    assign csr_command_reject_event = source_core_csr_reject_pulse ||
                                      csr_replay_reject_feedback;

    always_ff @(posedge clk_fabric or negedge rst_n_platform) begin
        if (!rst_n_platform) begin
            replay_request_origin_q <= REPLAY_ORIGIN_NONE;
            csr_replay_queued_q <= 1'b0;
            csr_replay_abort_reject_q <= 1'b0;
        end else begin
            csr_replay_abort_reject_q <= 1'b0;
            if (replay_epoch_clear) begin
                // A board clear is an abort boundary. Delay the correlated host reject by one
                // cycle so a simultaneous CSR W1P is pending before the result is returned.
                csr_replay_abort_reject_q <=
                    (replay_request_origin_q == REPLAY_ORIGIN_CSR) ||
                    csr_replay_queued_q || csr_replay_start;
                replay_request_origin_q <= REPLAY_ORIGIN_NONE;
                csr_replay_queued_q <= 1'b0;
            end else begin
                if (csr_replay_start &&
                    (replay_request_origin_q != REPLAY_ORIGIN_NONE)) begin
                    csr_replay_queued_q <= 1'b1;
                end

                unique case (replay_request_origin_q)
                    REPLAY_ORIGIN_NONE: begin
                        if (csr_replay_forward) begin
                            csr_replay_queued_q <= 1'b0;
                            replay_request_origin_q <= replay_owner_terminal ?
                                                       REPLAY_ORIGIN_NONE : REPLAY_ORIGIN_CSR;
                        end else if (key_replay_forward) begin
                            replay_request_origin_q <= replay_owner_terminal ?
                                                       REPLAY_ORIGIN_NONE : REPLAY_ORIGIN_KEY;
                        end
                    end
                    REPLAY_ORIGIN_KEY,
                    REPLAY_ORIGIN_CSR: begin
                        if (replay_owner_terminal) begin
                            replay_request_origin_q <= REPLAY_ORIGIN_NONE;
                        end
                    end
                    default: begin
                        replay_request_origin_q <= REPLAY_ORIGIN_NONE;
                        csr_replay_queued_q <= 1'b0;
                    end
                endcase
            end
        end
    end

    // The one-clock Step-7 integration closes the real reverse control loop:
    // CSR active values -> source/core, and actual source/core boundaries/status -> CSR/telemetry.
    trecap_source_core_integration #(
        .SAMPLE_W(T_SAMPLE_W),
        .L(T_FFT_L),
        .P(T_FFT_P),
        .BIN_IDX_W(BIN_IDX_W),
        .X_MEMH_FILE(REPLAY_X_MEMH_FILE),
        .REPLAY_MEM_DEPTH(REPLAY_MEM_DEPTH),
        .REPLAY_INPUT_SAMPLES(REPLAY_INPUT_SAMPLES),
        .AUDIO_SAMPLE_W(AUDIO_SAMPLE_W),
        .ADC_BITS(ADC_BITS),
        .RESET_SOURCE_MODE(TSRC_BRAM_REPLAY)
    ) u_source_core_integration (
        .clk(clk_fabric),
        .rst_n(rst_n_platform),
        .enable_i(1'b1),
        // KEY[3] is the board-local replay/core/E2E abort and rearm. It does not flush telemetry:
        // doing so during a multi-beat record could strand the ring writer. The next admitted
        // replay performs its telemetry-only flush after transport_epoch_idle proves that safe.
        // KEY[2] remains the frozen ADC manual-request control; CSR telemetry soft reset remains
        // transport-only per the frozen control contract.
        .clear_i(key_press_pulse[3] || csr_replay_rearm),
        .thr2_i(ctrl.thr2_active),
        .requested_source_mode_i(ctrl.source_mode),
        .source_mode_apply_pulse_i(source_mode_apply_pulse),
        .clear_metrics_pulse_i(clear_metrics_pulse),
        .clear_sticky_flags_w1c_i(clear_sticky_flags_w1c),
        .source_tick_i(sample_tick),
        // KEY[0] remains board reset; debounced KEY[1] starts or restarts BRAM replay.
        .replay_start_i(replay_owner_start),
        .replay_start_admit_i(replay_start_admit),
        .diagnostic_mode_i(sw_sync[2:0]),
        .diagnostic_constant_i('0),
        .diagnostic_amplitude_i(DIAGNOSTIC_AMPLITUDE),
        .diagnostic_period_i(32'd256),
        .audio_sample_valid_i(audio_sample_valid),
        .audio_left_i(audio_left),
        .audio_right_i(audio_right),
        .audio_sample_count_i(audio_sample_count),
        .adc_sample_valid_i(adc_sample_valid),
        .adc_sample_raw_i(adc_sample_raw),
        .adc_sample_count_i(adc_sample_count),
        .adc_zero_code_valid_i(1'b0),
        .adc_zero_code_i('0),
        .adc_dc_block_enable_i(1'b0),
        .y_valid_o(core_y_valid),
        // Processed output is never backpressured by the optional audio monitor or telemetry.
        .y_ready_i(1'b1),
        .y_sample_o(core_y_sample),
        .y_data_o(core_y_data),
        .y_sample_idx_o(core_y_sample_idx),
        .tap_sample_o(tap_sample),
        .tap_frame_o(tap_frame),
        .tap_bin_valid_o(tap_bin_valid),
        .tap_bin_frame_idx_o(tap_bin_frame_idx),
        .tap_bin_idx_o(tap_bin_idx),
        .tap_bin_re_o(tap_bin_re),
        .tap_bin_im_o(tap_bin_im),
        .tap_bin_mag2_o(tap_bin_mag2),
        .tap_bin_pre_mask_o(tap_bin_pre_mask),
        .tap_bin_mask_o(tap_bin_mask),
        .tap_bin_eligible_o(tap_bin_eligible),
        .tap_bin_last_o(tap_bin_last),
        .frame_boundary_pulse_o(core_frame_boundary),
        .core_config_safe_boundary_o(core_config_safe_boundary),
        .source_safe_boundary_o(source_core_safe_boundary),
        .clear_metrics_apply_pulse_o(core_clear_metrics_apply_pulse),
        .active_source_mode_o(active_source_mode),
        .pending_source_mode_o(pending_source_mode),
        .source_switch_pending_o(source_switch_pending),
        .source_switch_apply_pulse_o(source_switch_apply),
        .source_discontinuity_pulse_o(source_discontinuity),
        .core_alive_o(core_alive),
        .core_busy_o(core_busy),
        .core_sample_count_o(core_sample_count),
        .core_frame_count_o(core_frame_count),
        .core_error_sample_count_o(core_error_sample_count),
        .core_sum_abs_err_lo_o(core_sum_abs_err_lo),
        .core_sum_sq_err_lo_o(core_sum_sq_err_lo),
        .core_max_abs_err_o(core_max_abs_err),
        .core_metric_overflow_sticky_o(core_metric_overflow_sticky),
        .core_overflow_flags_o(core_overflow_flags),
        .core_saturation_sticky_o(core_saturation_sticky),
        .core_protocol_error_sticky_o(core_protocol_error_sticky),
        .replay_active_o(replay_active),
        .replay_done_o(replay_done),
        .replay_input_phase_o(replay_input_phase),
        .replay_flush_phase_o(replay_flush_phase),
        .replay_tail_drain_phase_o(replay_tail_drain_phase),
        .replay_start_accept_pulse_o(replay_start_accept),
        .replay_start_reject_pulse_o(replay_start_reject),
        .replay_start_ready_o(replay_start_ready),
        .replay_output_accept_count_o(replay_output_accept_count),
        .replay_expected_output_count_o(replay_expected_output_count),
        .replay_path_busy_o(replay_path_busy),
        .replay_path_done_o(replay_path_done),
        .replay_path_done_pulse_o(replay_path_done_pulse),
        .replay_core_output_accept_count_o(replay_core_output_accept_count),
        .replay_completion_error_sticky_o(replay_completion_error_sticky),
        .source_fault_sticky_o(source_fault_sticky),
        .build_contract_error_o(source_core_build_contract_error),
        .external_overflow_flags_set_o(source_core_overflow_flags_set),
        .external_csr_reject_pulse_o(source_core_csr_reject_pulse)
    );

    // The board hierarchy already contains exactly one mathematical core inside
    // u_source_core_integration. The standalone trecap_core_telemetry_top variant is therefore
    // not instantiated here; this logical top consumes only the valid-only taps and authoritative
    // core counters/metrics, so DDR backpressure cannot reach the core ready path.
    trecap_de1soc_full_top #(
        .CSR_AVMM_ADDR_W(CSR_AVMM_ADDR_W),
        .CSR_ADDR_W(CSR_ADDR_W),
        .CSR_BURSTCOUNT_W(CSR_BURSTCOUNT_W),
        .PAYLOAD_DATA_W(PAYLOAD_DATA_W),
        .PAYLOAD_KEEP_W(PAYLOAD_KEEP_W),
        .PACKET_FIFO_RECORDS(PACKET_FIFO_RECORDS),
        .PACKET_FIFO_BYTES(PACKET_FIFO_BYTES),
        .AVMM_ADDR_W(AVMM_ADDR_W),
        .AVMM_DATA_W(AVMM_DATA_W),
        .AVMM_BYTEEN_W(AVMM_BYTEEN_W),
        .AVMM_BURSTCOUNT_W(AVMM_BURSTCOUNT_W),
        // rst_n_platform is already asynchronously asserted and synchronously deasserted in this
        // shared domain; avoid a second hidden reset-release delay inside the logical top.
        .SYNC_TOP_RESET_DEASSERTION(1'b0),
        .RESET_SYNC_STAGES(RESET_SYNC_STAGES),
        .BIN_IDX_W(BIN_IDX_W)
    ) u_full_top (
        .clk(clk_fabric),
        .rst_n(rst_n_platform),
        .rst_n_sync_o(rst_n_sync_from_full_top),
        .external_transport_clear_i(1'b0),
        .external_telemetry_flush_i(replay_start_accept),
        .csr_avs_address_i(csr_avs_address),
        .csr_avs_read_i(csr_avs_read),
        .csr_avs_write_i(csr_avs_write),
        .csr_avs_writedata_i(csr_avs_writedata),
        .csr_avs_byteenable_i(csr_avs_byteenable),
        .csr_avs_burstcount_i(csr_avs_burstcount),
        .csr_avs_waitrequest_o(csr_avs_waitrequest),
        .csr_avs_readdata_o(csr_avs_readdata),
        .csr_avs_readdatavalid_o(csr_avs_readdatavalid),
        .csr_avs_writeresponsevalid_o(csr_avs_writeresponsevalid),
        .csr_avs_response_o(csr_avs_response),
        .avm_address_o(avm_address),
        .avm_write_o(avm_write),
        .avm_writedata_o(avm_writedata),
        .avm_byteenable_o(avm_byteenable),
        .avm_burstcount_o(avm_burstcount),
        .avm_waitrequest_i(avm_waitrequest),
        .avm_writeresponsevalid_i(avm_writeresponsevalid),
        .avm_response_i(avm_response),
        .tap_sample_i(tap_sample),
        .tap_frame_i(tap_frame),
        .tap_bin_valid_i(tap_bin_valid),
        .tap_bin_frame_idx_i(tap_bin_frame_idx),
        .tap_bin_idx_i(tap_bin_idx),
        .tap_bin_mag2_i(tap_bin_mag2),
        .tap_bin_mask_i(tap_bin_mask),
        .tap_bin_eligible_i(tap_bin_eligible),
        .tap_bin_last_i(tap_bin_last),
        .frame_boundary_i(core_config_safe_boundary),
        .source_safe_boundary_i(source_core_safe_boundary),
        .source_discontinuity_i(source_discontinuity),
        .actual_source_mode_i(active_source_mode),
        .source_transition_busy_i(source_switch_pending || source_discontinuity),
        .replay_start_ready_i(replay_start_ready &&
                              (replay_request_origin_q == REPLAY_ORIGIN_NONE) &&
                              !csr_replay_queued_q),
        .replay_request_busy_i(replay_request_busy),
        .replay_start_accept_pulse_i(csr_replay_accept_feedback),
        .replay_start_reject_pulse_i(csr_replay_reject_feedback),
        .replay_active_i(replay_active),
        .replay_path_busy_i(replay_path_busy),
        .replay_path_done_i(replay_path_done),
        .replay_e2e_busy_i(replay_e2e_busy),
        .replay_e2e_done_i(replay_e2e_done),
        .replay_error_i(replay_error),
        .replay_rearm_required_i(replay_rearm_required),
        .core_alive_i(core_alive),
        .core_frame_count_i(core_frame_count),
        .core_sample_count_i(core_sample_count),
        .core_sum_abs_err_lo_i(core_sum_abs_err_lo),
        .core_sum_sq_err_lo_i(core_sum_sq_err_lo),
        .core_max_abs_err_i({16'd0, core_max_abs_err}),
        .core_metric_truncated_i(core_metric_overflow_sticky),
        .clear_metrics_apply_pulse_i(core_clear_metrics_apply_pulse),
        .status_tick_i(status_tick_to_transport),
        .metrics_tick_i(metrics_tick),
        .sample_rate_hz_i(telemetry_sample_rate_hz),
        .external_overflow_flags_set_i(source_core_overflow_flags_set),
        .external_csr_reject_pulse_i(csr_command_reject_event),
        .ctrl_o(ctrl),
        .ring_config_o(ring_config),
        .telemetry_soft_reset_pulse_o(telemetry_soft_reset_pulse),
        .clear_metrics_pulse_o(clear_metrics_pulse),
        .counter_clear_pulse_o(csr_counter_clear),
        .replay_start_pulse_o(csr_replay_start),
        .replay_rearm_pulse_o(csr_replay_rearm),
        .thr2_apply_pulse_o(thr2_apply_pulse),
        .source_mode_apply_pulse_o(source_mode_apply_pulse),
        .clear_sticky_flags_w1c_o(clear_sticky_flags_w1c),
        .ring_config_commit_pulse_o(ring_config_commit_pulse),
        .ring_wr_snapshot_req_pulse_o(ring_wr_snapshot_req_pulse),
        .ring_rd_commit_req_pulse_o(ring_rd_commit_req_pulse),
        .core_count_snapshot_pulse_o(core_count_snapshot_pulse),
        .packet_fifo_drop_count_o(packet_fifo_drop_count),
        .packet_fifo_drop_pulse_o(packet_fifo_drop_pulse),
        .packet_fifo_full_o(packet_fifo_full),
        .packet_fifo_overflow_o(packet_fifo_overflow),
        .scheduler_backpressure_o(scheduler_backpressure),
        .scheduler_disabled_drop_o(scheduler_disabled_drop),
        .scheduler_illegal_drop_o(scheduler_illegal_drop),
        .status_o(status),
        .dma_status_o(dma_status),
        .overflow_flags_o(overflow_flags),
        .csr_command_reject_count_o(csr_command_reject_count),
        .dma_drop_count_o(dma_drop_count),
        .dma_packet_count_o(dma_packet_count),
        .producer_ptr_o(producer_ptr),
        .consumer_ptr_o(consumer_ptr),
        .sequence_o(telemetry_sequence),
        .used_bytes_o(used_bytes),
        .free_bytes_o(free_bytes),
        .current_offset_o(current_offset),
        .current_tail_bytes_o(current_tail_bytes),
        .writer_idle_o(writer_idle),
        .writer_busy_o(writer_busy),
        .writer_no_space_o(writer_no_space),
        .malformed_config_o(malformed_config),
        .ring_full_o(ring_full),
        .ddr_wait_o(ddr_wait),
        .drop_active_o(drop_active),
        .ring_configured_o(ring_configured),
        .pointers_valid_o(pointers_valid),
        .writer_fault_sticky_o(writer_fault_sticky),
        .normal_commit_pulse_o(normal_commit_pulse),
        .wrap_commit_pulse_o(wrap_commit_pulse),
        .writer_drop_pulse_o(writer_drop_pulse),
        .writer_malformed_pulse_o(writer_malformed_pulse),
        .writer_oversized_pulse_o(writer_oversized_pulse),
        .ring_rd_accept_pulse_o(ring_rd_accept_pulse),
        .ring_rd_reject_pulse_o(ring_rd_reject_pulse),
        .writer_ring_wr_snapshot_valid_o(writer_ring_wr_snapshot_valid),
        .writer_ring_wr_snapshot_pulse_o(writer_ring_wr_snapshot_pulse),
        .packet_fifo_full_status_o(packet_fifo_full_status),
        .packet_fifo_overflow_status_o(packet_fifo_overflow_status),
        .packet_enable_illegal_o(packet_enable_illegal),
        .spec_mode_illegal_o(spec_mode_illegal),
        .spec_shift_illegal_o(spec_shift_illegal),
        .wave_decim_illegal_o(wave_decim_illegal),
        .telemetry_config_illegal_o(telemetry_config_illegal),
        .telemetry_active_o(telemetry_active),
        .core_tap_seen_o(core_tap_seen),
        .full_path_alive_o(full_path_alive),
        .transport_epoch_idle_o(transport_epoch_idle),
        .transport_epoch_idle_stable_o(transport_epoch_idle_stable)
    );

    assign replay_error = replay_completion_error_sticky || replay_e2e_error_sticky;
    assign replay_rearm_required = replay_error;
    assign replay_start_admit = replay_e2e_transport_ready && transport_epoch_idle &&
                                transport_epoch_idle_stable && !replay_e2e_busy &&
                                !replay_rearm_required;
    assign replay_e2e_transport_ready = ring_configured &&
        ctrl.telemetry_enable && ctrl.ring_writer_enable &&
        (ctrl.packet_enable == TCSR_PACKET_ENABLE_STATUS_EN_MASK) &&
        !telemetry_config_illegal;
    assign status_tick_to_transport = replay_path_done_pulse ||
        (status_tick && !replay_e2e_busy && !replay_path_busy && !replay_start_accept);
    assign replay_e2e_completion_fault = source_core_build_contract_error ||
        replay_completion_error_sticky || core_protocol_error_sticky ||
        core_metric_overflow_sticky || (core_overflow_flags != 32'd0);
    assign replay_e2e_transport_fault = packet_fifo_overflow ||
        packet_fifo_overflow_status || scheduler_illegal_drop || malformed_config ||
        writer_fault_sticky || writer_drop_pulse || writer_malformed_pulse ||
        writer_oversized_pulse;

    trecap_bram_replay_e2e_supervisor u_replay_e2e_supervisor (
        .clk(clk_fabric),
        .rst_n(rst_n_platform),
        .clear_i(key_press_pulse[3] || csr_replay_rearm),
        .replay_start_accept_pulse_i(replay_start_accept),
        .replay_path_busy_i(replay_path_busy),
        .replay_path_done_i(replay_path_done),
        .replay_path_done_pulse_i(replay_path_done_pulse),
        .replay_completion_error_sticky_i(replay_completion_error_sticky),
        .completion_fault_i(replay_e2e_completion_fault),
        .transport_ready_i(replay_e2e_transport_ready),
        .transport_clear_pulse_i(telemetry_soft_reset_pulse),
        .transport_fault_i(replay_e2e_transport_fault),
        .writer_idle_i(writer_idle),
        .writer_busy_i(writer_busy),
        .normal_commit_pulse_i(normal_commit_pulse),
        .producer_ptr_i(producer_ptr),
        .dma_packet_count_i(dma_packet_count),
        .dma_drop_count_i(dma_drop_count),
        .packet_fifo_drop_count_i(packet_fifo_drop_count),
        .replay_e2e_busy_o(replay_e2e_busy),
        .replay_e2e_done_o(replay_e2e_done),
        .replay_e2e_done_pulse_o(replay_e2e_done_pulse),
        .replay_e2e_error_sticky_o(replay_e2e_error_sticky)
    );

    always_comb begin
        unique case (sw_sync[9:8])
            2'b00: display_word = core_sample_count[23:0];
            2'b01: display_word = core_frame_count[23:0];
            2'b10: display_word = status[23:0];
            2'b11: display_word = {overflow_flags[7:0], packet_fifo_drop_count[15:0]};
            default: display_word = 24'h000000;
        endcase
    end

    assign HEX0 = hex7seg_active_low(display_word[3:0]);
    assign HEX1 = hex7seg_active_low(display_word[7:4]);
    assign HEX2 = hex7seg_active_low(display_word[11:8]);
    assign HEX3 = hex7seg_active_low(display_word[15:12]);
    assign HEX4 = hex7seg_active_low(display_word[19:16]);
    assign HEX5 = hex7seg_active_low(display_word[23:20]);

    assign LEDR[0] = rst_n_platform;
    assign LEDR[1] = heartbeat;
    assign LEDR[2] = core_tap_seen;
    assign LEDR[3] = telemetry_active;
    assign LEDR[4] = ring_configured;
    assign LEDR[5] = writer_busy;
    assign LEDR[6] = packet_fifo_overflow | packet_fifo_overflow_status;
    assign LEDR[7] = |overflow_flags | malformed_config | ring_full | writer_fault_sticky |
                     source_fault_sticky | source_core_build_contract_error |
                     replay_completion_error_sticky | core_protocol_error_sticky |
                     replay_e2e_error_sticky |
                     audio_frame_overrun_sticky | audio_lineout_overrun_sticky |
                     audio_lineout_underflow_sticky | audio_codec_init_error_sticky |
                     audio_codec_nack_sticky | audio_i2c_unsupported |
                     adc_request_overrun_sticky | adc_protocol_error_sticky;
    // Step-11 board-visible replay state. LEDR[9] requires exact core completion followed by a
    // later STATUS commit into the HPS-visible DDR ring; source-token/core-path done are earlier.
    assign LEDR[8] = replay_e2e_busy;
    assign LEDR[9] = replay_e2e_done;

    // Unused source/core and transport observability kept visible for SignalTap. The reduction
    // prevents aggressive lint from treating them as accidental omissions.
    wire unused_reserved_clocks = CLOCK2_50 ^ CLOCK3_50 ^ CLOCK4_50;
    wire unused_key_levels = ^key_level ^ ^key_release_pulse;
    wire unused_csr = csr_avs_waitrequest ^ csr_avs_readdatavalid ^
                      csr_avs_writeresponsevalid ^ ^csr_avs_readdata ^ ^csr_avs_response;
    wire unused_avmm = avm_write ^ ^avm_address ^ ^avm_writedata ^ ^avm_byteenable ^ ^avm_burstcount;
    wire unused_ctrl = ctrl.telemetry_enable ^ ctrl.ring_writer_enable ^ ctrl.clear_metrics_w1p;
    wire unused_ring_config = ring_config.configured ^ ^ring_config.base_addr ^ ^ring_config.size_bytes ^ ^ring_config.size_mask;
    wire unused_pulses = telemetry_soft_reset_pulse ^ thr2_apply_pulse ^ source_mode_apply_pulse ^
                         ^clear_sticky_flags_w1c ^ ring_config_commit_pulse ^ ring_wr_snapshot_req_pulse ^
                         ring_rd_commit_req_pulse ^ core_count_snapshot_pulse ^ packet_fifo_drop_pulse ^
                         scheduler_backpressure ^ scheduler_disabled_drop ^ scheduler_illegal_drop ^
                         ring_rd_accept_pulse ^ ring_rd_reject_pulse ^ writer_ring_wr_snapshot_valid ^
                         writer_ring_wr_snapshot_pulse ^ normal_commit_pulse ^ wrap_commit_pulse ^
                         writer_drop_pulse ^ writer_malformed_pulse ^ writer_oversized_pulse ^
                         csr_counter_clear ^ csr_replay_start ^ csr_replay_rearm ^
                         audio_i2c_start_accept ^ audio_i2c_start_reject ^
                         audio_codec_init_done_pulse;
    wire unused_status = ^dma_status ^ ^csr_command_reject_count ^ ^dma_drop_count ^ ^dma_packet_count ^
                         ^producer_ptr ^ ^consumer_ptr ^ ^telemetry_sequence ^ ^used_bytes ^ ^free_bytes ^
                         ^current_offset ^ ^current_tail_bytes ^ writer_idle ^ writer_no_space ^ ddr_wait ^
                         drop_active ^ pointers_valid ^ packet_fifo_full ^ packet_fifo_full_status ^
                         packet_enable_illegal ^ spec_mode_illegal ^ spec_shift_illegal ^ wave_decim_illegal ^
                         telemetry_config_illegal ^ full_path_alive;
    wire unused_core_status = ^core_y_sample ^ ^core_y_sample_idx ^
                              core_frame_boundary ^ core_busy ^ ^core_error_sample_count ^
                              ^core_sum_abs_err_lo ^ ^core_sum_sq_err_lo ^ ^core_max_abs_err ^
                              core_metric_overflow_sticky ^ ^core_overflow_flags ^
                              core_saturation_sticky ^ ^tap_bin_re ^ ^tap_bin_im ^
                              tap_bin_pre_mask;
    wire unused_source_status = ^pending_source_mode ^ source_switch_pending ^ source_switch_apply ^
                                source_discontinuity ^ replay_active ^ replay_done ^ replay_input_phase ^
                                replay_flush_phase ^ replay_tail_drain_phase ^ replay_start_accept ^
                                replay_start_reject ^ replay_start_ready ^ ^replay_output_accept_count ^
                                ^replay_expected_output_count ^ replay_path_done_pulse ^
                                ^replay_core_output_accept_count ^ replay_e2e_done_pulse;
    wire unused_platform_source_status = audio_lineout_ready ^ audio_active ^
                                         audio_bclk_seen_sticky ^ audio_lrck_seen_sticky ^
                                         audio_pll_locked ^ audio_pll_config_supported ^
                                         audio_i2c_start_ready ^ audio_i2c_busy ^
                                         audio_codec_init_done ^ audio_codec_ready ^
                                         ^audio_i2c_ack_error_count ^ ^audio_i2c_retry_count ^
                                         ^audio_i2c_bus_abort_count ^
                                         ^audio_i2c_config_write_count ^
                                         ^audio_i2c_register_index ^
                                         ^audio_rx_overflow_count ^
                                         ^audio_tx_overflow_count ^
                                         ^audio_tx_underflow_count ^
                                         ^adc_centered_preview ^ adc_busy ^ adc_transaction_done;
    wire unused_io = AUD_ADCDAT ^ AUD_ADCLRCK ^ AUD_BCLK ^ AUD_DACLRCK ^
                     FPGA_I2C_SDAT ^ ADC_DOUT;
    wire unused_full_reset = rst_n_sync_from_full_top ^ h2f_reset_n ^ heartbeat_toggle;
    wire unused_all = unused_reserved_clocks ^ unused_key_levels ^ unused_csr ^ unused_avmm ^
                      unused_ctrl ^ unused_ring_config ^ unused_pulses ^ unused_status ^ unused_io ^
                      unused_full_reset ^ unused_core_status ^ unused_source_status ^
                      unused_platform_source_status;

`ifndef SYNTHESIS
    initial begin
        if ((CSR_ADDR_W < 2) || (CSR_AVMM_ADDR_W < CSR_ADDR_W)) begin
            $fatal(1, "de1_soc_trecap_top: CSR address widths violate aperture/leaf contract");
        end
        if (CSR_BURSTCOUNT_W < 1) begin
            $fatal(1, "de1_soc_trecap_top: CSR_BURSTCOUNT_W must be at least 1");
        end
        if ((PAYLOAD_DATA_W % 8) != 0) begin
            $fatal(1, "de1_soc_trecap_top: PAYLOAD_DATA_W must be byte-aligned");
        end
        if (PAYLOAD_KEEP_W != ((PAYLOAD_DATA_W + 7) / 8)) begin
            $fatal(1, "de1_soc_trecap_top: PAYLOAD_KEEP_W mismatch");
        end
        if (SAMPLE_RATE_HZ == 0) begin
            $fatal(1, "de1_soc_trecap_top: SAMPLE_RATE_HZ must be nonzero");
        end
        if ((AUDIO_SAMPLE_W != 16) || (SAMPLE_RATE_HZ != 48_000) ||
            (AUDIO_MCLK_HZ != 12_288_000)) begin
            $fatal(1, "de1_soc_trecap_top: Step-16 audio profile requires 16-bit/48-kHz/12.288-MHz");
        end
        if (FABRIC_CLK_HZ != 50_000_000) begin
            $fatal(1, "de1_soc_trecap_top: direct-clock profile requires FABRIC_CLK_HZ=50000000");
        end
        if (SAMPLE_RATE_HZ >= FABRIC_CLK_HZ) begin
            $fatal(1, "de1_soc_trecap_top: SAMPLE_RATE_HZ must be below FABRIC_CLK_HZ");
        end
        if (SAMPLE_RATE_HZ != SAMPLE_TICK_HZ) begin
            $fatal(1, "de1_soc_trecap_top: BRAM/diagnostic sample rate and sample clock-enable must match");
        end
        if (AUDIO_SAMPLE_W < T_SAMPLE_W) begin
            $fatal(1, "de1_soc_trecap_top: lineout monitor requires AUDIO_SAMPLE_W >= T_SAMPLE_W");
        end
        if (ADC_BITS != 12) begin
            $fatal(1, "de1_soc_trecap_top: DE1-SoC LTC2308 requires ADC_BITS=12");
        end
        if ((ADC_SAMPLE_RATE_HZ != 100_000) || (ADC_SCLK_HALF_DIV != 10)) begin
            $fatal(1, "de1_soc_trecap_top: Step-17 LTC2308 profile requires 100-kS/s and 2.5-MHz SCLK");
        end
        if (ADC_SAMPLE_RATE_HZ >= FABRIC_CLK_HZ) begin
            $fatal(1, "de1_soc_trecap_top: ADC_SAMPLE_RATE_HZ must be below FABRIC_CLK_HZ");
        end
    end
`endif

endmodule : de1_soc_trecap_top

`default_nettype wire
