// SPDX-License-Identifier: MIT
// File class: [1] hand-written RTL.
// Layer: rtl/platform/de1soc/
// Owner: T-RECAP Phase 2 implementation.
// Purpose: DE1-SoC LTC2308 conversion controller and raw-sample scheduler.
// Contract: Produce unsigned LTC2308 samples for rtl/sources/trecap_adc_adapter.sv.  This module
//           does not perform core scaling/DC blocking, compute STFT/WOLA, or implement telemetry,
//           HPS software, Ethernet, or dashboard behavior.
// Generated dependencies: trecap_core_pkg only for baseline-width assertions/documentation.

`default_nettype none

// DE1-SoC LTC2308 controller.
//
// Physical-pin policy:
//   The repository retains the legacy Terasic/SystemBuilder top-level name ADC_CS_N for FPGA pin
//   AJ4.  Electrically this pin is the LTC2308 CONVST input: idle is low and a high pulse starts a
//   conversion.  The `_N` suffix must not be interpreted as an active-low chip select.
//
// Transaction policy (LTC2308 datasheet serial mode):
//   1. Pulse ADC_CS_N high for CONVST_PULSE_CYCLES.
//   2. Return it low and wait at least the LTC2308 maximum conversion time.
//   3. Emit exactly twelve SCLK pulses. DOUT is sampled on each rising edge. The six-bit next-
//      conversion command is held before the corresponding rising edges and advanced on falling
//      edges in the order S/D, O/S, S1, S0, UNI, SLP.
//   4. Keep an acquisition guard before another conversion may start.
//
// ADC_DOUT is an off-chip source-synchronous return.  It is first passed through an explicitly
// identified synchronizer and is sampled only after at least DOUT_SYNC_STAGES+1 fabric cycles
// have elapsed since the preceding ADC_SCLK falling edge.  ADC_SCLK is never an RTL clock; the
// entire controller and the published valid/data pair remain in the clk fabric domain.
//
// The command shifted during a transaction configures the following conversion. Therefore the
// first result after reset, an aborted transaction, or a command change is discarded. Publishing
// it as though it belonged to the newly requested channel would silently mislabel the source.
module adc_wrapper
  import trecap_core_pkg::*;
#(
    parameter int unsigned CLK_HZ                    = 50_000_000,
    parameter int unsigned SAMPLE_RATE_HZ            = 100_000,
    parameter int unsigned SCLK_HALF_DIV             = 10,
    parameter int unsigned FRAME_BITS                = 12,
    parameter int unsigned COMMAND_BITS              = 6,
    parameter int unsigned ADC_BITS                  = 12,
    parameter int unsigned DOUT_SYNC_STAGES          = 2,
    parameter int unsigned CONVST_PULSE_CYCLES       = 2,
    parameter int unsigned CONVERSION_WAIT_CYCLES    = 80,
    parameter int unsigned ACQUISITION_GUARD_CYCLES  = 12,
    // Single-ended channel 0, unipolar, awake: {S/D,O/S,S1,S0,UNI,SLP}.
    parameter logic [COMMAND_BITS-1:0] DEFAULT_COMMAND = 6'b100010
) (
    input  logic                         clk,
    input  logic                         rst_n,
    input  logic                         enable_i,
    input  logic                         clear_sticky_i,

    // One-shot request and optional continuous scheduler. Requests are accepted only while idle;
    // any request that arrives during a conversion is reported as an overrun.
    input  logic                         continuous_enable_i,
    input  logic                         sample_request_i,
    input  logic [COMMAND_BITS-1:0]       command_i,
    input  logic                         command_valid_i,

    output logic                         sample_valid_o,
    output logic [ADC_BITS-1:0]           sample_raw_o,
    output logic signed [ADC_BITS:0]      sample_centered_preview_o,
    output logic [63:0]                  sample_count_o,

    output logic                         busy_o,
    output logic                         transaction_done_pulse_o,
    output logic                         request_overrun_sticky_o,
    output logic                         protocol_error_sticky_o,

    output logic                         ADC_CS_N,
    output logic                         ADC_DIN,
    input  wire                          ADC_DOUT,
    output logic                         ADC_SCLK
);

    localparam int unsigned SAMPLE_ACCUM_W =
        (CLK_HZ <= 1) ? 1 : $clog2(CLK_HZ);
    localparam int unsigned DOUT_SYNC_SAFE =
        (DOUT_SYNC_STAGES < 2) ? 2 : DOUT_SYNC_STAGES;
    localparam int unsigned HALF_DIV_SAFE = (SCLK_HALF_DIV < 1) ? 1 : SCLK_HALF_DIV;
    localparam int unsigned HALF_DIV_W =
        (HALF_DIV_SAFE <= 1) ? 1 : $clog2(HALF_DIV_SAFE);
    localparam int unsigned BIT_COUNT_W =
        (FRAME_BITS <= 1) ? 1 : $clog2(FRAME_BITS);
    localparam int unsigned CONVST_SAFE =
        (CONVST_PULSE_CYCLES < 1) ? 1 : CONVST_PULSE_CYCLES;
    localparam int unsigned CONVST_CNT_W =
        (CONVST_SAFE <= 1) ? 1 : $clog2(CONVST_SAFE);
    localparam int unsigned CONVERT_SAFE =
        (CONVERSION_WAIT_CYCLES < 1) ? 1 : CONVERSION_WAIT_CYCLES;
    localparam int unsigned CONVERT_CNT_W =
        (CONVERT_SAFE <= 1) ? 1 : $clog2(CONVERT_SAFE);
    localparam int unsigned ACQUIRE_SAFE =
        (ACQUISITION_GUARD_CYCLES < 1) ? 1 : ACQUISITION_GUARD_CYCLES;
    localparam int unsigned ACQUIRE_CNT_W =
        (ACQUIRE_SAFE <= 1) ? 1 : $clog2(ACQUIRE_SAFE);
    localparam int unsigned REENTRY_RECOVERY_CYCLES =
        CONVST_PULSE_CYCLES + CONVERSION_WAIT_CYCLES + SCLK_HALF_DIV;
    localparam int unsigned REENTRY_RECOVERY_SAFE =
        (REENTRY_RECOVERY_CYCLES < 1) ? 1 : REENTRY_RECOVERY_CYCLES;
    localparam int unsigned REENTRY_RECOVERY_CNT_W =
        (REENTRY_RECOVERY_SAFE <= 1) ? 1 : $clog2(REENTRY_RECOVERY_SAFE);
    localparam int unsigned CENTER_W = ADC_BITS + 1;

    // Wide constant arithmetic keeps the datasheet timing proofs valid when CLK_HZ or any cycle
    // parameter is overridden.  Each time comparison is cross-multiplied by CLK_HZ, avoiding
    // truncating integer nanosecond division during elaboration.
    localparam logic [63:0] CLK_HZ_U64                   = CLK_HZ;
    localparam logic [63:0] SAMPLE_INTERVAL_MIN_CYCLES_U64 =
        (SAMPLE_RATE_HZ == 0) ? 64'd1 : (CLK_HZ / SAMPLE_RATE_HZ);
    localparam logic [63:0] SCLK_HALF_DIV_U64            = SCLK_HALF_DIV;
    localparam logic [63:0] FRAME_BITS_U64               = FRAME_BITS;
    localparam logic [63:0] CONVST_PULSE_CYCLES_U64      = CONVST_PULSE_CYCLES;
    localparam logic [63:0] CONVERSION_WAIT_CYCLES_U64   = CONVERSION_WAIT_CYCLES;
    localparam logic [63:0] ACQUISITION_GUARD_CYCLES_U64 = ACQUISITION_GUARD_CYCLES;
    localparam logic [63:0] NS_PER_SECOND_U64            = 64'd1_000_000_000;

    localparam logic [63:0] CONVST_HIGH_TIME_SCALED =
        CONVST_PULSE_CYCLES_U64 * NS_PER_SECOND_U64;
    localparam logic [63:0] CONVERSION_TO_FIRST_SCLK_CYCLES_U64 =
        CONVST_PULSE_CYCLES_U64 + CONVERSION_WAIT_CYCLES_U64 + SCLK_HALF_DIV_U64;
    localparam logic [63:0] CONVERSION_TO_FIRST_SCLK_TIME_SCALED =
        CONVERSION_TO_FIRST_SCLK_CYCLES_U64 * NS_PER_SECOND_U64;
    // After rising edge seven there are one falling half-period for bit seven, five complete
    // clocks for bits eight through twelve, then the explicit acquisition guard.
    localparam logic [63:0] ACQUISITION_FROM_SEVENTH_RISE_CYCLES_U64 =
        (((FRAME_BITS_U64 - 64'd7) * 64'd2) + 64'd1) * SCLK_HALF_DIV_U64 +
        ACQUISITION_GUARD_CYCLES_U64;
    localparam logic [63:0] ACQUISITION_FROM_SEVENTH_RISE_TIME_SCALED =
        ACQUISITION_FROM_SEVENTH_RISE_CYCLES_U64 * NS_PER_SECOND_U64;
    localparam logic [63:0] TRANSACTION_CYCLES_U64 =
        CONVST_PULSE_CYCLES_U64 + CONVERSION_WAIT_CYCLES_U64 +
        (64'd2 * FRAME_BITS_U64 * SCLK_HALF_DIV_U64) +
        ACQUISITION_GUARD_CYCLES_U64;

    // Unsupported structurally well-formed parameter combinations synthesize to an inert
    // peripheral rather than generating malformed board traffic. Degenerate zero-width overrides
    // are outside the module ABI and may be rejected by elaboration. The simulation-only
    // assertions below retain precise failure messages for supported-width elaborations.
    localparam bit PROTOCOL_CONFIG_SUPPORTED =
        (CLK_HZ != 0) &&
        (ADC_BITS == 12) &&
        (FRAME_BITS == ADC_BITS) &&
        (COMMAND_BITS == 6) &&
        ((DEFAULT_COMMAND & 6'b100011) == 6'b100010) &&
        (DOUT_SYNC_STAGES >= 2) &&
        (SCLK_HALF_DIV >= (DOUT_SYNC_STAGES + 1)) &&
        (SAMPLE_RATE_HZ != 0) &&
        (SAMPLE_RATE_HZ < CLK_HZ) &&
        (CONVST_PULSE_CYCLES != 0) &&
        (CONVERSION_WAIT_CYCLES != 0) &&
        (ACQUISITION_GUARD_CYCLES != 0) &&
        (CONVST_HIGH_TIME_SCALED >= (CLK_HZ_U64 * 64'd20)) &&
        (CONVST_HIGH_TIME_SCALED <= (CLK_HZ_U64 * 64'd40)) &&
        (CONVERSION_TO_FIRST_SCLK_TIME_SCALED >= (CLK_HZ_U64 * 64'd1_600)) &&
        (CLK_HZ_U64 <= (SCLK_HALF_DIV_U64 * 64'd80_000_000)) &&
        (ACQUISITION_FROM_SEVENTH_RISE_TIME_SCALED >= (CLK_HZ_U64 * 64'd240)) &&
        (TRANSACTION_CYCLES_U64 < SAMPLE_INTERVAL_MIN_CYCLES_U64);

    localparam logic [SAMPLE_ACCUM_W:0] SAMPLE_CLK_RATE = CLK_HZ;
    localparam logic [SAMPLE_ACCUM_W:0] SAMPLE_EVENT_RATE = SAMPLE_RATE_HZ;
    localparam logic [HALF_DIV_W-1:0]    HALF_DIV_LAST   = HALF_DIV_SAFE - 1;
    localparam logic [BIT_COUNT_W-1:0]   FRAME_LAST      = FRAME_BITS - 1;
    localparam logic [CONVST_CNT_W-1:0]  CONVST_LAST     = CONVST_SAFE - 1;
    localparam logic [CONVERT_CNT_W-1:0] CONVERT_LAST    = CONVERT_SAFE - 1;
    localparam logic [ACQUIRE_CNT_W-1:0] ACQUIRE_LAST    = ACQUIRE_SAFE - 1;
    localparam logic [REENTRY_RECOVERY_CNT_W-1:0] REENTRY_RECOVERY_LAST =
        REENTRY_RECOVERY_SAFE - 1;

    typedef enum logic [2:0] {
        ADC_IDLE,
        ADC_CONVST,
        ADC_CONVERT,
        ADC_SHIFT,
        ADC_ACQUIRE
    } adc_state_e;

    adc_state_e                   state_q;
    logic [SAMPLE_ACCUM_W-1:0]    sample_rate_accum_q;
    logic [SAMPLE_ACCUM_W:0]      sample_rate_sum;
    logic                         internal_sample_tick;
    logic [HALF_DIV_W-1:0]        sclk_half_cnt_q;
    logic [BIT_COUNT_W-1:0]       bit_idx_q;
    logic [CONVST_CNT_W-1:0]      convst_cnt_q;
    logic [CONVERT_CNT_W-1:0]     conversion_cnt_q;
    logic [ACQUIRE_CNT_W-1:0]     acquisition_cnt_q;
    logic [COMMAND_BITS-1:0]      transaction_command_q;
    logic [COMMAND_BITS-1:0]      tx_command_q;
    logic [FRAME_BITS-1:0]        rx_shift_q;
    logic [COMMAND_BITS-1:0]      configured_command_q;
    logic                         configured_valid_q;
    logic                         result_eligible_q;
    logic [REENTRY_RECOVERY_CNT_W-1:0] reentry_recovery_cnt_q;
    logic                         reentry_recovery_ready_q;
    logic                         request_attempt;
    logic                         request_now;
    logic [COMMAND_BITS-1:0]      requested_command;
    logic                         requested_command_supported;
    logic                         state_q_legal;
    logic [CENTER_W-1:0]          centered_midpoint;

    (* async_reg = "true" *)
    (* preserve = "true" *)
    (* altera_attribute = "-name SYNCHRONIZER_IDENTIFICATION FORCED" *)
    logic [DOUT_SYNC_SAFE-1:0]    adc_dout_sync_q;

    function automatic logic [63:0] sat_inc64(input logic [63:0] value);
        if (&value) begin
            sat_inc64 = value;
        end else begin
            sat_inc64 = value + 64'd1;
        end
    endfunction : sat_inc64

    assign requested_command = command_valid_i ? command_i : DEFAULT_COMMAND;
    assign sample_rate_sum = {1'b0, sample_rate_accum_q} + SAMPLE_EVENT_RATE;
    assign request_attempt = enable_i && PROTOCOL_CONFIG_SUPPORTED &&
        (sample_request_i || (continuous_enable_i && internal_sample_tick));
    assign request_now = request_attempt && reentry_recovery_ready_q;
    assign centered_midpoint = {{ADC_BITS{1'b0}}, 1'b1} << (ADC_BITS - 1);
    assign sample_centered_preview_o =
        $signed({1'b0, sample_raw_o}) - $signed(centered_midpoint);
    assign busy_o = PROTOCOL_CONFIG_SUPPORTED && enable_i &&
        (!reentry_recovery_ready_q || (state_q != ADC_IDLE));

    // A plain four-state case makes X/Z command-control bits take the default path in simulation,
    // while synthesizing to the same masked mode comparator in hardware. Channel-select bits remain
    // unrestricted because all eight single-ended channels are supported. The masked expression
    // also keeps structurally well-formed non-six-bit parameter overrides elaboration-safe.
    always_comb begin
        requested_command_supported = 1'b0;
        case (requested_command & 6'b100011)
            6'b100010: requested_command_supported = 1'b1;
            default: requested_command_supported = 1'b0;
        endcase
    end

    // Keep the recovery owner separate from the protocol FSM, but make an illegal/X state an
    // explicit abort boundary. This case also fails closed under four-state simulation semantics.
    always_comb begin
        state_q_legal = 1'b0;
        case (state_q)
            ADC_IDLE,
            ADC_CONVST,
            ADC_CONVERT,
            ADC_SHIFT,
            ADC_ACQUIRE: state_q_legal = 1'b1;
            default: state_q_legal = 1'b0;
        endcase
    end

    // The external return is the only asynchronous input at this wrapper boundary.  Complete
    // samples and sample_valid_o are then registered together in clk, so no multi-bit CDC follows.
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            adc_dout_sync_q <= '0;
        end else begin
            adc_dout_sync_q <= {adc_dout_sync_q[DOUT_SYNC_SAFE-2:0], ADC_DOUT};
        end
    end

    // An abort can occur immediately after CONVST rises. On every re-entry, wait at least the
    // frozen CONVST-to-first-SCLK interval before accepting either a manual or scheduled request.
    // This prevents a rapid source-mode leave/re-enter sequence from restarting the converter
    // before the preceding conversion has completed. Requests during recovery are rejected and
    // attributed through request_overrun_sticky_o rather than disappearing silently.
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            reentry_recovery_cnt_q <= '0;
            reentry_recovery_ready_q <= 1'b0;
        end else if (!PROTOCOL_CONFIG_SUPPORTED || !enable_i || !state_q_legal) begin
            reentry_recovery_cnt_q <= '0;
            reentry_recovery_ready_q <= 1'b0;
        end else if (!reentry_recovery_ready_q) begin
            if (reentry_recovery_cnt_q == REENTRY_RECOVERY_LAST) begin
                reentry_recovery_ready_q <= 1'b1;
            end else begin
                reentry_recovery_cnt_q <= reentry_recovery_cnt_q +
                    {{(REENTRY_RECOVERY_CNT_W-1){1'b0}}, 1'b1};
            end
        end
    end

    // Exact-average fractional scheduler.  The interval may dither by one clk cycle when CLK_HZ is
    // not divisible by SAMPLE_RATE_HZ.  Resetting phase while disabled preserves the existing
    // fresh-period-on-enable behavior.
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            sample_rate_accum_q <= '0;
            internal_sample_tick <= 1'b0;
        end else begin
            internal_sample_tick <= 1'b0;
            if (!PROTOCOL_CONFIG_SUPPORTED || !enable_i || !continuous_enable_i) begin
                sample_rate_accum_q <= '0;
            end else if (sample_rate_sum >= SAMPLE_CLK_RATE) begin
                sample_rate_accum_q <= sample_rate_sum - SAMPLE_CLK_RATE;
                internal_sample_tick <= 1'b1;
            end else begin
                sample_rate_accum_q <= sample_rate_sum[SAMPLE_ACCUM_W-1:0];
            end
        end
    end

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state_q <= ADC_IDLE;
            sclk_half_cnt_q <= '0;
            bit_idx_q <= '0;
            convst_cnt_q <= '0;
            conversion_cnt_q <= '0;
            acquisition_cnt_q <= '0;
            transaction_command_q <= DEFAULT_COMMAND;
            tx_command_q <= DEFAULT_COMMAND;
            rx_shift_q <= '0;
            configured_command_q <= DEFAULT_COMMAND;
            configured_valid_q <= 1'b0;
            result_eligible_q <= 1'b0;
            sample_valid_o <= 1'b0;
            sample_raw_o <= '0;
            sample_count_o <= 64'd0;
            transaction_done_pulse_o <= 1'b0;
            request_overrun_sticky_o <= 1'b0;
            protocol_error_sticky_o <= 1'b0;
            ADC_CS_N <= 1'b0;
            ADC_DIN <= 1'b0;
            ADC_SCLK <= 1'b0;
        end else begin
            sample_valid_o <= 1'b0;
            transaction_done_pulse_o <= 1'b0;

            if (clear_sticky_i) begin
                request_overrun_sticky_o <= 1'b0;
                protocol_error_sticky_o <= 1'b0;
            end

            if (request_attempt &&
                (!reentry_recovery_ready_q || (state_q != ADC_IDLE))) begin
                request_overrun_sticky_o <= 1'b1;
            end
            if (request_attempt && !requested_command_supported) begin
                protocol_error_sticky_o <= 1'b1;
            end

            // A bad static timing/width configuration is a synthesizable fail-closed condition.
            // Do not emit CONVST/SCLK activity even if enable_i is asserted, and make the fault
            // visible instead of relying only on simulation assertions.
            if (!PROTOCOL_CONFIG_SUPPORTED) begin
                state_q <= ADC_IDLE;
                sclk_half_cnt_q <= '0;
                bit_idx_q <= '0;
                convst_cnt_q <= '0;
                conversion_cnt_q <= '0;
                acquisition_cnt_q <= '0;
                configured_valid_q <= 1'b0;
                result_eligible_q <= 1'b0;
                ADC_CS_N <= 1'b0;
                ADC_DIN <= 1'b0;
                ADC_SCLK <= 1'b0;
                if (enable_i) begin
                    protocol_error_sticky_o <= 1'b1;
                end
            // A source-mode change may remove enable_i at any point. Abort the physical transfer,
            // return every pin to its idle level, and force one priming conversion on re-entry.
            end else if (!enable_i) begin
                state_q <= ADC_IDLE;
                sclk_half_cnt_q <= '0;
                bit_idx_q <= '0;
                convst_cnt_q <= '0;
                conversion_cnt_q <= '0;
                acquisition_cnt_q <= '0;
                configured_valid_q <= 1'b0;
                result_eligible_q <= 1'b0;
                ADC_CS_N <= 1'b0;
                ADC_DIN <= 1'b0;
                ADC_SCLK <= 1'b0;
            end else begin
                unique case (state_q)
                    ADC_IDLE: begin
                        ADC_CS_N <= 1'b0;
                        ADC_SCLK <= 1'b0;
                        ADC_DIN <= 1'b0;
                        sclk_half_cnt_q <= '0;
                        bit_idx_q <= '0;
                        convst_cnt_q <= '0;
                        conversion_cnt_q <= '0;
                        acquisition_cnt_q <= '0;

                        if (request_now) begin
                            if (!requested_command_supported) begin
                                protocol_error_sticky_o <= 1'b1;
                            end else begin
                                state_q <= ADC_CONVST;
                                ADC_CS_N <= 1'b1;
                                transaction_command_q <= requested_command;
                                tx_command_q <= requested_command;
                                result_eligible_q <= configured_valid_q &&
                                    (configured_command_q == requested_command);
                                ADC_DIN <= requested_command[COMMAND_BITS-1];
                            end
                        end
                    end

                    ADC_CONVST: begin
                        ADC_CS_N <= 1'b1;
                        ADC_SCLK <= 1'b0;
                        ADC_DIN <= tx_command_q[COMMAND_BITS-1];

                        if (convst_cnt_q == CONVST_LAST) begin
                            convst_cnt_q <= '0;
                            conversion_cnt_q <= '0;
                            ADC_CS_N <= 1'b0;
                            state_q <= ADC_CONVERT;
                        end else begin
                            convst_cnt_q <= convst_cnt_q +
                                {{(CONVST_CNT_W-1){1'b0}}, 1'b1};
                        end
                    end

                    ADC_CONVERT: begin
                        ADC_CS_N <= 1'b0;
                        ADC_SCLK <= 1'b0;
                        ADC_DIN <= tx_command_q[COMMAND_BITS-1];

                        if (conversion_cnt_q == CONVERT_LAST) begin
                            conversion_cnt_q <= '0;
                            sclk_half_cnt_q <= '0;
                            bit_idx_q <= '0;
                            rx_shift_q <= '0;
                            state_q <= ADC_SHIFT;
                        end else begin
                            conversion_cnt_q <= conversion_cnt_q +
                                {{(CONVERT_CNT_W-1){1'b0}}, 1'b1};
                        end
                    end

                    ADC_SHIFT: begin
                        ADC_CS_N <= 1'b0;

                        if (sclk_half_cnt_q == HALF_DIV_LAST) begin
                            sclk_half_cnt_q <= '0;

                            if (!ADC_SCLK) begin
                                // The synchronized DOUT value is stable before the rising edge;
                                // subsequent device bits change only after falling SCLK edges.
                                ADC_SCLK <= 1'b1;
                                rx_shift_q <= {
                                    rx_shift_q[FRAME_BITS-2:0],
                                    adc_dout_sync_q[DOUT_SYNC_SAFE-1]
                                };
                            end else begin
                                // Create the falling edge, then advance DIN for the next rising
                                // edge. Six command bits are followed by zeros through clock 12.
                                ADC_SCLK <= 1'b0;
                                if (bit_idx_q == FRAME_LAST) begin
                                    ADC_DIN <= 1'b0;
                                    configured_command_q <= transaction_command_q;
                                    configured_valid_q <= 1'b1;
                                    transaction_done_pulse_o <= 1'b1;
                                    if (result_eligible_q) begin
                                        sample_raw_o <= rx_shift_q[ADC_BITS-1:0];
                                        sample_valid_o <= 1'b1;
                                        sample_count_o <= sat_inc64(sample_count_o);
                                    end
                                    acquisition_cnt_q <= '0;
                                    state_q <= ADC_ACQUIRE;
                                end else begin
                                    bit_idx_q <= bit_idx_q +
                                        {{(BIT_COUNT_W-1){1'b0}}, 1'b1};
                                    tx_command_q <= {tx_command_q[COMMAND_BITS-2:0], 1'b0};
                                    ADC_DIN <= tx_command_q[COMMAND_BITS-2];
                                end
                            end
                        end else begin
                            sclk_half_cnt_q <= sclk_half_cnt_q +
                                {{(HALF_DIV_W-1){1'b0}}, 1'b1};
                        end
                    end

                    ADC_ACQUIRE: begin
                        ADC_CS_N <= 1'b0;
                        ADC_SCLK <= 1'b0;
                        ADC_DIN <= 1'b0;

                        if (acquisition_cnt_q == ACQUIRE_LAST) begin
                            acquisition_cnt_q <= '0;
                            state_q <= ADC_IDLE;
                        end else begin
                            acquisition_cnt_q <= acquisition_cnt_q +
                                {{(ACQUIRE_CNT_W-1){1'b0}}, 1'b1};
                        end
                    end

                    default: begin
                        state_q <= ADC_IDLE;
                        configured_valid_q <= 1'b0;
                        result_eligible_q <= 1'b0;
                        protocol_error_sticky_o <= 1'b1;
                        ADC_CS_N <= 1'b0;
                        ADC_SCLK <= 1'b0;
                        ADC_DIN <= 1'b0;
                    end
                endcase
            end
        end
    end

`ifndef SYNTHESIS
    initial begin
        if (CLK_HZ == 0) begin
            $fatal(1, "adc_wrapper: CLK_HZ must be nonzero");
        end
        if (ADC_BITS != 12) begin
            $fatal(1, "adc_wrapper: DE1-SoC LTC2308 ADC_BITS must be 12");
        end
        if (FRAME_BITS != ADC_BITS) begin
            $fatal(1, "adc_wrapper: LTC2308 requires exactly twelve serial data clocks");
        end
        if (COMMAND_BITS != 6) begin
            $fatal(1, "adc_wrapper: LTC2308 command width must be six bits");
        end
        if ((DEFAULT_COMMAND & 6'b100011) != 6'b100010) begin
            $fatal(1, "adc_wrapper: default command must be single-ended, unipolar, and awake");
        end
        if (DOUT_SYNC_STAGES < 2) begin
            $fatal(1, "adc_wrapper: ADC_DOUT synchronizer requires at least two stages");
        end
        if (ADC_BITS < T_SAMPLE_W) begin
            $warning("adc_wrapper: ADC_BITS=%0d is less than core T_SAMPLE_W=%0d; freeze an adapter policy before use", ADC_BITS, T_SAMPLE_W);
        end
        if (SCLK_HALF_DIV == 0) begin
            $fatal(1, "adc_wrapper: SCLK_HALF_DIV must be nonzero");
        end
        if (SCLK_HALF_DIV < (DOUT_SYNC_STAGES + 1)) begin
            $fatal(1, "adc_wrapper: SCLK half-period must exceed ADC_DOUT synchronizer latency");
        end
        if (SAMPLE_RATE_HZ == 0) begin
            $fatal(1, "adc_wrapper: SAMPLE_RATE_HZ must be nonzero");
        end
        if (SAMPLE_RATE_HZ >= CLK_HZ) begin
            $fatal(1, "adc_wrapper: SAMPLE_RATE_HZ must be below CLK_HZ");
        end
        if (CONVST_PULSE_CYCLES == 0) begin
            $fatal(1, "adc_wrapper: CONVST_PULSE_CYCLES must be nonzero");
        end
        if (CONVERSION_WAIT_CYCLES == 0) begin
            $fatal(1, "adc_wrapper: CONVERSION_WAIT_CYCLES must be nonzero");
        end
        if (ACQUISITION_GUARD_CYCLES == 0) begin
            $fatal(1, "adc_wrapper: ACQUISITION_GUARD_CYCLES must be nonzero");
        end
        if (CONVST_HIGH_TIME_SCALED < (CLK_HZ_U64 * 64'd20)) begin
            $fatal(1, "adc_wrapper: LTC2308 CONVST high time must be at least 20 ns");
        end
        if (CONVST_HIGH_TIME_SCALED > (CLK_HZ_U64 * 64'd40)) begin
            $fatal(1, "adc_wrapper: LTC2308 best-performance CONVST high time must not exceed 40 ns");
        end
        if (CONVERSION_TO_FIRST_SCLK_TIME_SCALED < (CLK_HZ_U64 * 64'd1_600)) begin
            $fatal(1, "adc_wrapper: first SCLK rise must be at least 1.6 us after CONVST rises");
        end
        if (CLK_HZ_U64 > (SCLK_HALF_DIV_U64 * 64'd80_000_000)) begin
            $fatal(1, "adc_wrapper: LTC2308 SCLK must not exceed 40 MHz");
        end
        if (ACQUISITION_FROM_SEVENTH_RISE_TIME_SCALED < (CLK_HZ_U64 * 64'd240)) begin
            $fatal(1, "adc_wrapper: next CONVST must be at least 240 ns after SCLK rising edge seven");
        end
        if (TRANSACTION_CYCLES_U64 >= SAMPLE_INTERVAL_MIN_CYCLES_U64) begin
            $fatal(1, "adc_wrapper: complete LTC2308 transaction must fit within the shortest fractional scheduler interval");
        end
    end
`endif

endmodule : adc_wrapper

`default_nettype wire
