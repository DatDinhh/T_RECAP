// SPDX-License-Identifier: MIT
// File class: [1] hand-written RTL source adapter.
// Layer: rtl/sources/
// Owner: T-RECAP Phase 2 implementation.
// Purpose: Convert signed audio-codec samples into the signed T-RECAP core sample stream.
// Contract: This adapter applies the documented live-audio scale rule only. It does not average
//           stereo channels silently, does not implement STFT/FFT/IFFT/WOLA/mask/error logic, and
//           does not know CSR, telemetry packets, DDR rings, HPS software, Ethernet, or dashboard
//           behavior.

`default_nettype none

module trecap_audio_adapter
#(
    parameter int unsigned AUDIO_SAMPLE_W          = 16,
    // 0 selects left channel; 1 selects right channel. Stereo averaging is intentionally absent
    // until a profile freezes an exact signed rounding rule for it.
    parameter bit          SELECT_RIGHT_CHANNEL    = 1'b0,
    // The spec freezes the normal audio rule for Baudio >= N. If a future profile uses narrower
    // audio samples, it must explicitly enable and document this left-shift rule.
    parameter bit          ALLOW_NARROW_LEFT_SHIFT = 1'b0,
    parameter int unsigned DROP_COUNT_W            = 32
) (
    input  logic                         clk,
    input  logic                         rst_n,
    input  logic                         enable_i,
    input  logic                         clear_i,
    input  logic                         clear_sticky_i,

    // Signed, zero-centered stereo frame from rtl/platform/de1soc/audio_codec_wrapper.sv. The
    // platform wrapper cannot be backpressured; this adapter has one output staging register and
    // drops/counts live samples when the downstream source stream is stalled.
    input  logic                         audio_sample_valid_i,
    input  logic signed [AUDIO_SAMPLE_W-1:0] audio_left_i,
    input  logic signed [AUDIO_SAMPLE_W-1:0] audio_right_i,
    input  logic [63:0]                  audio_sample_count_i,

    // Ready/valid signed T-RECAP source stream. sample_idx counts samples admitted to this
    // adapter's core stream, not raw audio frames. Dropped raw audio frames do not create gaps.
    input  logic                         sample_ready_i,
    output trecap_iface_pkg::trecap_sample_t               sample_o,
    output logic                         sample_valid_o,
    output logic signed [trecap_core_pkg::T_SAMPLE_W-1:0] sample_data_o,
    output logic [63:0]                  sample_idx_o,

    // One-cycle pulses for source-mux/platform diagnostics.
    output logic                         input_accept_pulse_o,
    output logic                         input_drop_pulse_o,
    output logic                         output_accept_pulse_o,
    output logic                         clipped_hi_pulse_o,
    output logic                         clipped_lo_pulse_o,
    output logic                         source_discontinuity_pulse_o,

    // Saturating counters. These are source-adapter counters, not telemetry PACKET_FIFO_DROP_COUNT
    // and not HPS DMA_DROP_COUNT.
    output logic [63:0]                  input_sample_count_o,
    output logic [63:0]                  output_sample_count_o,
    output logic [63:0]                  source_samples_admitted_o,
    output logic [DROP_COUNT_W-1:0]      dropped_sample_count_o,
    output logic [63:0]                  last_source_sample_count_o,

    output logic                         overflow_sticky_o,
    output logic                         disabled_drop_sticky_o,
    output logic                         clipped_hi_sticky_o,
    output logic                         clipped_lo_sticky_o,
    output logic                         config_error_sticky_o
);
  import trecap_core_pkg::*;
  import trecap_iface_pkg::*;
  import trecap_math_pkg::*;


    localparam int signed AUDIO_TO_CORE_SHIFT = AUDIO_SAMPLE_W - T_SAMPLE_W;
    localparam int unsigned DROP_COUNT_SAFE_W = (DROP_COUNT_W == 0) ? 1 : DROP_COUNT_W;
    localparam bit AUDIO_CONFIG_OK = (AUDIO_SAMPLE_W >= T_SAMPLE_W) || ALLOW_NARROW_LEFT_SHIFT;

    trecap_sample_t pending_sample_q;
    logic           pending_valid_q;
    logic [63:0]    next_sample_idx_q;
    logic [63:0]    input_sample_count_q;
    logic [63:0]    output_sample_count_q;
    logic [63:0]    source_samples_admitted_q;
    logic [DROP_COUNT_SAFE_W-1:0] dropped_sample_count_q;
    logic [63:0]    last_source_sample_count_q;

    logic signed [AUDIO_SAMPLE_W-1:0] selected_audio;
    logic                             output_accept;
    logic                             can_capture_input;
    logic                             capture_input;
    logic                             drop_input;
    logic                             scaled_clip_hi;
    logic                             scaled_clip_lo;
    logic signed [T_SAMPLE_W-1:0]     scaled_sample;

    assign selected_audio = SELECT_RIGHT_CHANNEL ? audio_right_i : audio_left_i;
    assign output_accept = pending_valid_q && sample_ready_i;
    assign can_capture_input = !pending_valid_q || output_accept;
    assign capture_input = enable_i && AUDIO_CONFIG_OK && audio_sample_valid_i && can_capture_input;
    assign drop_input = audio_sample_valid_i && (!enable_i || !AUDIO_CONFIG_OK || !can_capture_input);

    assign sample_o = pending_sample_q;
    assign sample_valid_o = pending_sample_q.valid;
    assign sample_data_o = pending_sample_q.data;
    assign sample_idx_o = pending_sample_q.sample_idx;

    assign input_sample_count_o = input_sample_count_q;
    assign output_sample_count_o = output_sample_count_q;
    assign source_samples_admitted_o = source_samples_admitted_q;
    assign dropped_sample_count_o = dropped_sample_count_q[DROP_COUNT_W-1:0];
    assign last_source_sample_count_o = last_source_sample_count_q;

    function automatic trecap_math_swide_t rounded_to_core_domain(
        input logic signed [AUDIO_SAMPLE_W-1:0] value
    );
        trecap_math_swide_t wide_value;
        trecap_math_swide_t result;
        int unsigned shift_abs;
    begin
        wide_value = trecap_math_swide_t'(value);
        if (AUDIO_TO_CORE_SHIFT > 0) begin
            shift_abs = AUDIO_TO_CORE_SHIFT;
            result = trecap_rnd_shr(wide_value, shift_abs);
        end else if (AUDIO_TO_CORE_SHIFT < 0) begin
            shift_abs = -AUDIO_TO_CORE_SHIFT;
            if (ALLOW_NARROW_LEFT_SHIFT) begin
                result = wide_value <<< shift_abs;
            end else begin
                result = '0;
            end
        end else begin
            result = wide_value;
        end
        return result;
    end
    endfunction : rounded_to_core_domain

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
        trecap_math_swide_t rounded_audio;
        trecap_math_swide_t sample_min_wide;
        trecap_math_swide_t sample_max_wide;

        rounded_audio = rounded_to_core_domain(selected_audio);
        sample_min_wide = trecap_math_swide_t'(T_SAMPLE_MIN);
        sample_max_wide = trecap_math_swide_t'(T_SAMPLE_MAX);
        scaled_clip_lo = (rounded_audio < sample_min_wide);
        scaled_clip_hi = (rounded_audio > sample_max_wide);
        scaled_sample = trecap_sat_sample(rounded_audio);
    end

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            pending_sample_q             <= '0;
            pending_valid_q              <= 1'b0;
            next_sample_idx_q            <= 64'd0;
            input_sample_count_q         <= 64'd0;
            output_sample_count_q        <= 64'd0;
            source_samples_admitted_q    <= 64'd0;
            dropped_sample_count_q       <= '0;
            last_source_sample_count_q   <= 64'd0;
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
                input_sample_count_q         <= 64'd0;
                output_sample_count_q        <= 64'd0;
                source_samples_admitted_q    <= 64'd0;
                dropped_sample_count_q       <= '0;
                last_source_sample_count_q   <= 64'd0;
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

                if (audio_sample_valid_i) begin
                    input_sample_count_q <= input_sample_count_q + 64'd1;
                    last_source_sample_count_q <= audio_sample_count_i;
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
                    output_sample_count_q <= output_sample_count_q + 64'd1;
                end

                if (capture_input) begin
                    pending_valid_q <= 1'b1;
                    pending_sample_q.valid <= 1'b1;
                    pending_sample_q.data <= scaled_sample;
                    pending_sample_q.sample_idx <= next_sample_idx_q;
                    next_sample_idx_q <= next_sample_idx_q + 64'd1;
                    source_samples_admitted_q <= source_samples_admitted_q + 64'd1;
                    input_accept_pulse_o <= 1'b1;

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
                    end else if (!AUDIO_CONFIG_OK) begin
                        config_error_sticky_o <= 1'b1;
                    end else begin
                        overflow_sticky_o <= 1'b1;
                    end
                end

                if (!AUDIO_CONFIG_OK) begin
                    config_error_sticky_o <= 1'b1;
                end
            end
        end
    end

`ifndef SYNTHESIS
    initial begin
        if (AUDIO_SAMPLE_W == 0) begin
            $fatal(1, "trecap_audio_adapter: AUDIO_SAMPLE_W must be nonzero");
        end
        if (DROP_COUNT_W == 0) begin
            $fatal(1, "trecap_audio_adapter: DROP_COUNT_W must be nonzero");
        end
        if ((AUDIO_SAMPLE_W < T_SAMPLE_W) && !ALLOW_NARROW_LEFT_SHIFT) begin
            $warning("trecap_audio_adapter: AUDIO_SAMPLE_W < T_SAMPLE_W; profile must explicitly enable and document left-shift scaling");
        end
    end

    always_ff @(posedge clk) begin
        if (rst_n && capture_input && (^selected_audio === 1'bx)) begin
            $error("trecap_audio_adapter: selected audio sample is X on capture");
        end
        if (rst_n && pending_valid_q && (^pending_sample_q.data === 1'bx)) begin
            $error("trecap_audio_adapter: output sample data is X while valid");
        end
        if (rst_n && pending_valid_q && (^pending_sample_q.sample_idx === 1'bx)) begin
            $error("trecap_audio_adapter: output sample_idx is X while valid");
        end
    end
`endif

endmodule : trecap_audio_adapter

`default_nettype wire
