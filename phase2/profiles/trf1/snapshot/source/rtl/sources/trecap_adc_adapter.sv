// SPDX-License-Identifier: MIT
// File class: [1] hand-written RTL source adapter.
// Layer: rtl/sources/
// Owner: T-RECAP Phase 2 implementation.
// Purpose: Map unsigned live ADC samples into the signed T-RECAP core sample stream.
// Contract: The adapter owns ADC recentering/scaling only. It does not implement source-mode
//           commit, FFT/IFFT, WOLA, mask decisions, telemetry formatting, DDR writes, HPS
//           behavior, Ethernet behavior, or dashboard behavior.

`default_nettype none

module trecap_adc_adapter
#(
    parameter int unsigned ADC_BITS                     = 12,
    // If ADC_BITS is narrower than T_SAMPLE_W, the project profile must explicitly choose a rule.
    // Left shift preserves full-scale relation after unsigned recentering.
    parameter bit          ALLOW_NARROW_LEFT_SHIFT      = 1'b1,
    // Optional first-order DC estimator. Disabled by default because the source profile must
    // declare any DC-blocking behavior that changes live-source semantics.
    parameter int unsigned DC_BLOCK_SHIFT               = 10,
    parameter int unsigned DROP_COUNT_W                 = 32
) (
    input  logic                         clk,
    input  logic                         rst_n,
    input  logic                         enable_i,
    input  logic                         clear_i,
    input  logic                         clear_sticky_i,

    // Raw unsigned samples from rtl/platform/de1soc/adc_wrapper.sv. The wrapper cannot be
    // backpressured; this adapter has one output staging register and reports overruns.
    input  logic                         adc_sample_valid_i,
    input  logic [ADC_BITS-1:0]           adc_sample_raw_i,
    input  logic [63:0]                  adc_sample_count_i,

    // Optional runtime zero-code override. If invalid, the adapter uses unsigned midscale.
    input  logic                         zero_code_valid_i,
    input  logic [ADC_BITS-1:0]           zero_code_i,

    // Optional profile-declared DC blocker. Keep tied low unless the source profile documents it.
    input  logic                         dc_block_enable_i,

    // Ready/valid signed T-RECAP source stream. sample_idx counts samples admitted to this
    // adapter's core stream, not raw ADC transactions. Dropped raw ADC samples do not create gaps.
    input  logic                         sample_ready_i,
    output trecap_iface_pkg::trecap_sample_t               sample_o,
    output logic                         sample_valid_o,
    output logic signed [trecap_core_pkg::T_SAMPLE_W-1:0] sample_data_o,
    output logic [63:0]                  sample_idx_o,

    // Observability for source mux/platform bring-up.
    output logic                         input_accept_pulse_o,
    output logic                         input_drop_pulse_o,
    output logic                         output_accept_pulse_o,
    output logic                         clipped_hi_pulse_o,
    output logic                         clipped_lo_pulse_o,
    output logic                         source_discontinuity_pulse_o,
    output logic [63:0]                  adc_samples_seen_o,
    output logic [63:0]                  source_samples_admitted_o,
    output logic [63:0]                  core_samples_accepted_o,
    output logic [DROP_COUNT_W-1:0]      dropped_sample_count_o,
    output logic signed [trecap_core_pkg::T_SAMPLE_W-1:0] centered_preview_o,
    output logic [63:0]                  last_source_sample_count_o,
    output logic                         dc_block_active_o,
    output logic                         overflow_sticky_o,
    output logic                         disabled_drop_sticky_o,
    output logic                         clipped_hi_sticky_o,
    output logic                         clipped_lo_sticky_o,
    output logic                         config_error_sticky_o
);
  import trecap_core_pkg::*;
  import trecap_iface_pkg::*;
  import trecap_math_pkg::*;


    localparam int signed ADC_TO_CORE_SHIFT = ADC_BITS - T_SAMPLE_W;
    localparam int unsigned DROP_COUNT_SAFE_W = (DROP_COUNT_W == 0) ? 1 : DROP_COUNT_W;
    localparam int unsigned DC_BLOCK_SHIFT_SAFE = (DC_BLOCK_SHIFT == 0) ? 1 : DC_BLOCK_SHIFT;
    localparam bit ADC_CONFIG_OK = (ADC_BITS >= T_SAMPLE_W) || ALLOW_NARROW_LEFT_SHIFT;

    typedef logic [ADC_BITS-1:0] adc_raw_t;

    trecap_sample_t pending_sample_q;
    logic           pending_valid_q;
    logic [63:0]    next_sample_idx_q;
    logic [63:0]    adc_samples_seen_q;
    logic [63:0]    source_samples_admitted_q;
    logic [63:0]    core_samples_accepted_q;
    logic [DROP_COUNT_SAFE_W-1:0] dropped_sample_count_q;
    logic [63:0]    last_source_sample_count_q;
    trecap_math_swide_t dc_estimate_q;

    logic           output_accept;
    logic           can_capture_input;
    logic           capture_input;
    logic           drop_input;
    adc_raw_t       effective_zero_code;
    trecap_math_swide_t centered_raw;
    trecap_math_swide_t dc_error;
    trecap_math_swide_t adapted_wide;
    logic signed [T_SAMPLE_W-1:0] scaled_adc;
    logic signed [T_SAMPLE_W-1:0] centered_preview_comb;
    logic                         scaled_clip_hi;
    logic                         scaled_clip_lo;
    logic                         preview_clip_hi;
    logic                         preview_clip_lo;

    assign output_accept = pending_valid_q && sample_ready_i;
    assign can_capture_input = !pending_valid_q || output_accept;
    assign capture_input = enable_i && ADC_CONFIG_OK && adc_sample_valid_i && can_capture_input;
    assign drop_input = adc_sample_valid_i && (!enable_i || !ADC_CONFIG_OK || !can_capture_input);

    assign sample_o = pending_sample_q;
    assign sample_valid_o = pending_sample_q.valid;
    assign sample_data_o = pending_sample_q.data;
    assign sample_idx_o = pending_sample_q.sample_idx;

    assign adc_samples_seen_o = adc_samples_seen_q;
    assign source_samples_admitted_o = source_samples_admitted_q;
    assign core_samples_accepted_o = core_samples_accepted_q;
    assign dropped_sample_count_o = dropped_sample_count_q[DROP_COUNT_W-1:0];
    assign centered_preview_o = centered_preview_comb;
    assign last_source_sample_count_o = last_source_sample_count_q;
    assign dc_block_active_o = dc_block_enable_i;

    function automatic adc_raw_t default_zero_code();
        adc_raw_t result;
    begin
        result = '0;
        result[ADC_BITS-1] = 1'b1;
        return result;
    end
    endfunction : default_zero_code

    function automatic trecap_math_swide_t unsigned_adc_to_wide(input adc_raw_t value);
        trecap_math_swide_t wide_value;
    begin
        wide_value = '0;
        wide_value[ADC_BITS-1:0] = value;
        return wide_value;
    end
    endfunction : unsigned_adc_to_wide

    function automatic trecap_math_swide_t scale_centered_wide(input trecap_math_swide_t centered_value);
        trecap_math_swide_t scaled_value;
        int unsigned shift_abs;
    begin
        if (ADC_TO_CORE_SHIFT > 0) begin
            shift_abs = ADC_TO_CORE_SHIFT;
            scaled_value = trecap_rnd_shr(centered_value, shift_abs);
        end else if (ADC_TO_CORE_SHIFT < 0) begin
            shift_abs = -ADC_TO_CORE_SHIFT;
            if (ALLOW_NARROW_LEFT_SHIFT) begin
                scaled_value = centered_value <<< shift_abs;
            end else begin
                scaled_value = '0;
            end
        end else begin
            scaled_value = centered_value;
        end
        return scaled_value;
    end
    endfunction : scale_centered_wide

    function automatic logic signed [T_SAMPLE_W-1:0] clip_to_core(
        input trecap_math_swide_t value
    );
        trecap_math_swide_t clipped_value;
    begin
        clipped_value = trecap_sat_signed(value, T_SAMPLE_W);
        return clipped_value[T_SAMPLE_W-1:0];
    end
    endfunction : clip_to_core

    function automatic logic [DROP_COUNT_SAFE_W-1:0] inc_drop_count(
        input logic [DROP_COUNT_SAFE_W-1:0] value
    );
        if (&value) begin
            inc_drop_count = value;
        end else begin
            inc_drop_count = value + {{(DROP_COUNT_SAFE_W-1){1'b0}}, 1'b1};
        end
    endfunction : inc_drop_count

    always_comb begin
        trecap_math_swide_t zero_wide;
        trecap_math_swide_t scaled_wide;
        trecap_math_swide_t preview_wide;
        trecap_math_swide_t clipped_scaled;
        trecap_math_swide_t clipped_preview;
        trecap_math_swide_t sample_min_wide;
        trecap_math_swide_t sample_max_wide;

        effective_zero_code = zero_code_valid_i ? zero_code_i : default_zero_code();
        zero_wide = unsigned_adc_to_wide(effective_zero_code);
        centered_raw = unsigned_adc_to_wide(adc_sample_raw_i) - zero_wide;
        dc_error = centered_raw - dc_estimate_q;
        adapted_wide = dc_block_enable_i ? dc_error : centered_raw;

        scaled_wide = scale_centered_wide(adapted_wide);
        preview_wide = scale_centered_wide(centered_raw);
        clipped_scaled = trecap_sat_signed(scaled_wide, T_SAMPLE_W);
        clipped_preview = trecap_sat_signed(preview_wide, T_SAMPLE_W);
        scaled_adc = clipped_scaled[T_SAMPLE_W-1:0];
        centered_preview_comb = clipped_preview[T_SAMPLE_W-1:0];

        sample_min_wide = trecap_math_swide_t'(T_SAMPLE_MIN);
        sample_max_wide = trecap_math_swide_t'(T_SAMPLE_MAX);
        scaled_clip_lo = (scaled_wide < sample_min_wide);
        scaled_clip_hi = (scaled_wide > sample_max_wide);
        preview_clip_lo = (preview_wide < sample_min_wide);
        preview_clip_hi = (preview_wide > sample_max_wide);
    end

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            pending_sample_q             <= '0;
            pending_valid_q              <= 1'b0;
            next_sample_idx_q            <= 64'd0;
            adc_samples_seen_q           <= 64'd0;
            source_samples_admitted_q    <= 64'd0;
            core_samples_accepted_q      <= 64'd0;
            dropped_sample_count_q       <= '0;
            last_source_sample_count_q   <= 64'd0;
            dc_estimate_q                <= '0;
            input_accept_pulse_o         <= 1'b0;
            input_drop_pulse_o           <= 1'b0;
            output_accept_pulse_o        <= 1'b0;
            clipped_hi_pulse_o           <= 1'b0;
            clipped_lo_pulse_o           <= 1'b0;
            source_discontinuity_pulse_o <= 1'b0;
            overflow_sticky_o            <= 1'b0;
            disabled_drop_sticky_o       <= 1'b0;
            clipped_hi_sticky_o          <= 1'b0;
            clipped_lo_sticky_o          <= 1'b0;
            config_error_sticky_o        <= 1'b0;
        end else begin
            input_accept_pulse_o         <= 1'b0;
            input_drop_pulse_o           <= 1'b0;
            output_accept_pulse_o        <= 1'b0;
            clipped_hi_pulse_o           <= 1'b0;
            clipped_lo_pulse_o           <= 1'b0;
            source_discontinuity_pulse_o <= 1'b0;

            if (clear_i) begin
                pending_sample_q             <= '0;
                pending_valid_q              <= 1'b0;
                next_sample_idx_q            <= 64'd0;
                adc_samples_seen_q           <= 64'd0;
                source_samples_admitted_q    <= 64'd0;
                core_samples_accepted_q      <= 64'd0;
                dropped_sample_count_q       <= '0;
                last_source_sample_count_q   <= 64'd0;
                dc_estimate_q                <= '0;
                source_discontinuity_pulse_o <= 1'b1;
                overflow_sticky_o            <= 1'b0;
                disabled_drop_sticky_o       <= 1'b0;
                clipped_hi_sticky_o          <= 1'b0;
                clipped_lo_sticky_o          <= 1'b0;
                config_error_sticky_o        <= 1'b0;
            end else begin
                if (clear_sticky_i) begin
                    overflow_sticky_o       <= 1'b0;
                    disabled_drop_sticky_o  <= 1'b0;
                    clipped_hi_sticky_o     <= 1'b0;
                    clipped_lo_sticky_o     <= 1'b0;
                    config_error_sticky_o   <= 1'b0;
                end

                if (adc_sample_valid_i) begin
                    adc_samples_seen_q <= adc_samples_seen_q + 64'd1;
                    last_source_sample_count_q <= adc_sample_count_i;
                end

                if (!enable_i && pending_valid_q) begin
                    pending_valid_q <= 1'b0;
                    pending_sample_q.valid <= 1'b0;
                    source_discontinuity_pulse_o <= 1'b1;
                end else if (output_accept && !capture_input) begin
                    pending_valid_q <= 1'b0;
                    pending_sample_q.valid <= 1'b0;
                end

                if (output_accept) begin
                    output_accept_pulse_o <= 1'b1;
                    core_samples_accepted_q <= core_samples_accepted_q + 64'd1;
                end

                if (capture_input) begin
                    pending_valid_q <= 1'b1;
                    pending_sample_q.valid <= 1'b1;
                    pending_sample_q.data <= scaled_adc;
                    pending_sample_q.sample_idx <= next_sample_idx_q;
                    next_sample_idx_q <= next_sample_idx_q + 64'd1;
                    source_samples_admitted_q <= source_samples_admitted_q + 64'd1;
                    input_accept_pulse_o <= 1'b1;

                    if (dc_block_enable_i) begin
                        dc_estimate_q <= dc_estimate_q + (dc_error >>> DC_BLOCK_SHIFT_SAFE);
                    end else begin
                        dc_estimate_q <= '0;
                    end

                    if (scaled_clip_hi) begin
                        clipped_hi_pulse_o <= 1'b1;
                        clipped_hi_sticky_o <= 1'b1;
                    end
                    if (scaled_clip_lo) begin
                        clipped_lo_pulse_o <= 1'b1;
                        clipped_lo_sticky_o <= 1'b1;
                    end
                end

                if (drop_input) begin
                    input_drop_pulse_o <= 1'b1;
                    dropped_sample_count_q <= inc_drop_count(dropped_sample_count_q);
                    if (!enable_i) begin
                        disabled_drop_sticky_o <= 1'b1;
                    end else if (!ADC_CONFIG_OK) begin
                        config_error_sticky_o <= 1'b1;
                    end else begin
                        overflow_sticky_o <= 1'b1;
                    end
                end

                if (!ADC_CONFIG_OK) begin
                    config_error_sticky_o <= 1'b1;
                end
            end
        end
    end

`ifndef SYNTHESIS
    initial begin
        if (ADC_BITS == 0) begin
            $fatal(1, "trecap_adc_adapter: ADC_BITS must be nonzero");
        end
        if (DROP_COUNT_W == 0) begin
            $fatal(1, "trecap_adc_adapter: DROP_COUNT_W must be nonzero");
        end
        if (ADC_BITS > TMATH_WIDE_W) begin
            $fatal(1, "trecap_adc_adapter: ADC_BITS exceeds trecap_math_pkg wide helper width");
        end
        if ((ADC_BITS < T_SAMPLE_W) && !ALLOW_NARROW_LEFT_SHIFT) begin
            $warning("trecap_adc_adapter: ADC_BITS < T_SAMPLE_W; profile must explicitly enable and document left-shift scaling");
        end
    end

    always_ff @(posedge clk) begin
        if (rst_n && capture_input && (^adc_sample_raw_i === 1'bx)) begin
            $error("trecap_adc_adapter: adc_sample_raw_i is X on capture");
        end
        if (rst_n && zero_code_valid_i && (^zero_code_i === 1'bx)) begin
            $error("trecap_adc_adapter: zero_code_i is X while zero_code_valid_i=1");
        end
        if (rst_n && pending_valid_q && (^pending_sample_q.data === 1'bx)) begin
            $error("trecap_adc_adapter: output sample data is X while valid");
        end
        if (rst_n && pending_valid_q && (^pending_sample_q.sample_idx === 1'bx)) begin
            $error("trecap_adc_adapter: output sample_idx is X while valid");
        end
        if (rst_n && (preview_clip_hi || preview_clip_lo) && adc_sample_valid_i) begin
            $warning("trecap_adc_adapter: centered ADC preview clipped to T_SAMPLE_W display range");
        end
    end
`endif

endmodule : trecap_adc_adapter

`default_nettype wire
