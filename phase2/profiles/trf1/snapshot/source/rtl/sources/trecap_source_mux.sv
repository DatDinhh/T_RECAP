// SPDX-License-Identifier: MIT
// File class: [1] hand-written RTL source module.
// Layer: rtl/sources/
// Owner: T-RECAP Phase 2 implementation.
// Purpose: Select exactly one signed sample source for the T-RECAP core input stream.
// Contract: Source-mode selection is a safe-boundary/shadow-commit boundary. This mux does not
//           implement source adapters, STFT/FFT/IFFT/WOLA logic, telemetry formatting, DDR writes,
//           HPS software, Ethernet, or dashboard behavior.

`default_nettype none

module trecap_source_mux
#(
    parameter trecap_iface_pkg::trecap_source_mode_e RESET_SOURCE_MODE = trecap_iface_pkg::TSRC_BRAM_REPLAY,
    parameter bit                  ACCEPT_SWITCH_WHEN_OUTPUT_IDLE = 1'b1,
    parameter int unsigned         SWITCH_REJECT_COUNT_W = 32
) (
    input  logic                         clk,
    input  logic                         rst_n,
    input  logic                         enable_i,
    input  logic                         clear_i,
    input  logic                         clear_sticky_i,

    // Shadow/commit source-mode control. The CSR layer owns validation/reject policy; this mux
    // still checks for X/unknown values and waits for a safe switch point before changing output.
    input  trecap_iface_pkg::trecap_source_mode_e          requested_source_mode_i,
    input  logic                         source_mode_commit_i,
    input  logic                         safe_to_switch_i,
    input  logic                         force_discontinuity_i,

    input  trecap_iface_pkg::trecap_sample_t               bram_sample_i,
    input  logic                         bram_sample_valid_i,
    output logic                         bram_sample_ready_o,

    input  trecap_iface_pkg::trecap_sample_t               adc_sample_i,
    input  logic                         adc_sample_valid_i,
    output logic                         adc_sample_ready_o,

    input  trecap_iface_pkg::trecap_sample_t               audio_sample_i,
    input  logic                         audio_sample_valid_i,
    output logic                         audio_sample_ready_o,

    input  trecap_iface_pkg::trecap_sample_t               diagnostic_sample_i,
    input  logic                         diagnostic_sample_valid_i,
    output logic                         diagnostic_sample_ready_o,

    input  logic                         sample_ready_i,
    output trecap_iface_pkg::trecap_sample_t               sample_o,
    output logic                         sample_valid_o,
    output logic signed [trecap_core_pkg::T_SAMPLE_W-1:0] sample_data_o,
    output logic [63:0]                  sample_idx_o,

    output trecap_iface_pkg::trecap_source_mode_e          active_source_mode_o,
    output trecap_iface_pkg::trecap_source_mode_e          pending_source_mode_o,
    output logic                         pending_switch_o,
    output logic                         switch_accept_pulse_o,
    output logic                         switch_apply_pulse_o,
    output logic                         switch_reject_pulse_o,
    output logic                         source_discontinuity_pulse_o,
    output logic                         output_accept_pulse_o,
    output logic [63:0]                  output_sample_count_o,
    output logic [SWITCH_REJECT_COUNT_W-1:0] switch_reject_count_o,
    output logic                         invalid_source_mode_sticky_o,
    output logic                         switch_pending_sticky_o,
    output logic                         disabled_sticky_o
);
  import trecap_core_pkg::*;
  import trecap_iface_pkg::*;


    localparam int unsigned REJECT_COUNT_SAFE_W = (SWITCH_REJECT_COUNT_W == 0) ? 1 : SWITCH_REJECT_COUNT_W;

    trecap_source_mode_e active_source_mode_q;
    trecap_source_mode_e pending_source_mode_q;
    logic                pending_switch_q;
    logic [63:0]         output_sample_count_q;
    logic [REJECT_COUNT_SAFE_W-1:0] switch_reject_count_q;

    trecap_sample_t      selected_sample;
    logic                selected_valid;
    logic                output_accept;
    logic                switch_safe_now;
    logic                requested_mode_known;
    logic                selected_mode_known;

    assign output_accept = sample_valid_o && sample_ready_i;
    assign switch_safe_now = safe_to_switch_i ||
                             (ACCEPT_SWITCH_WHEN_OUTPUT_IDLE && !sample_valid_o);

    assign sample_o = selected_sample;
    assign sample_valid_o = enable_i && selected_valid;
    assign sample_data_o = selected_sample.data;
    assign sample_idx_o = selected_sample.sample_idx;
    assign active_source_mode_o = active_source_mode_q;
    assign pending_source_mode_o = pending_source_mode_q;
    assign pending_switch_o = pending_switch_q;
    assign output_sample_count_o = output_sample_count_q;
    assign switch_reject_count_o = switch_reject_count_q[SWITCH_REJECT_COUNT_W-1:0];

    function automatic bit source_mode_known(input trecap_source_mode_e mode);
        unique case (mode)
            TSRC_BRAM_REPLAY,
            TSRC_ADC_LIVE,
            TSRC_AUDIO_WRAPPER,
            TSRC_DIAGNOSTIC: return 1'b1;
            default: return 1'b0;
        endcase
    endfunction : source_mode_known

    function automatic logic [REJECT_COUNT_SAFE_W-1:0] inc_reject_count(
        input logic [REJECT_COUNT_SAFE_W-1:0] value
    );
        if (&value) begin
            inc_reject_count = value;
        end else begin
            inc_reject_count = value + {{(REJECT_COUNT_SAFE_W-1){1'b0}}, 1'b1};
        end
    endfunction : inc_reject_count

    function automatic trecap_sample_t normalized_sample(
        input trecap_sample_t raw_sample,
        input logic           valid_override
    );
        trecap_sample_t result;
    begin
        result = raw_sample;
        result.valid = raw_sample.valid && valid_override;
        return result;
    end
    endfunction : normalized_sample

    always_comb begin
        requested_mode_known = source_mode_known(requested_source_mode_i);
        selected_mode_known = source_mode_known(active_source_mode_q);
        selected_sample = '0;
        selected_valid = 1'b0;
        bram_sample_ready_o = 1'b0;
        adc_sample_ready_o = 1'b0;
        audio_sample_ready_o = 1'b0;
        diagnostic_sample_ready_o = 1'b0;

        if (enable_i && selected_mode_known) begin
            unique case (active_source_mode_q)
                TSRC_BRAM_REPLAY: begin
                    selected_sample = normalized_sample(bram_sample_i, bram_sample_valid_i);
                    selected_valid = selected_sample.valid;
                    bram_sample_ready_o = sample_ready_i;
                end
                TSRC_ADC_LIVE: begin
                    selected_sample = normalized_sample(adc_sample_i, adc_sample_valid_i);
                    selected_valid = selected_sample.valid;
                    adc_sample_ready_o = sample_ready_i;
                end
                TSRC_AUDIO_WRAPPER: begin
                    selected_sample = normalized_sample(audio_sample_i, audio_sample_valid_i);
                    selected_valid = selected_sample.valid;
                    audio_sample_ready_o = sample_ready_i;
                end
                TSRC_DIAGNOSTIC: begin
                    selected_sample = normalized_sample(diagnostic_sample_i, diagnostic_sample_valid_i);
                    selected_valid = selected_sample.valid;
                    diagnostic_sample_ready_o = sample_ready_i;
                end
                default: begin
                    selected_sample = '0;
                    selected_valid = 1'b0;
                end
            endcase
        end
    end

    task automatic apply_source_mode(input trecap_source_mode_e mode);
        active_source_mode_q <= mode;
        switch_apply_pulse_o <= 1'b1;
        source_discontinuity_pulse_o <= 1'b1;
    endtask : apply_source_mode

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            active_source_mode_q          <= RESET_SOURCE_MODE;
            pending_source_mode_q         <= RESET_SOURCE_MODE;
            pending_switch_q              <= 1'b0;
            output_sample_count_q         <= 64'd0;
            switch_reject_count_q         <= '0;
            switch_accept_pulse_o         <= 1'b0;
            switch_apply_pulse_o          <= 1'b0;
            switch_reject_pulse_o         <= 1'b0;
            source_discontinuity_pulse_o  <= 1'b0;
            output_accept_pulse_o         <= 1'b0;
            invalid_source_mode_sticky_o  <= 1'b0;
            switch_pending_sticky_o       <= 1'b0;
            disabled_sticky_o             <= 1'b0;
        end else begin
            switch_accept_pulse_o        <= 1'b0;
            switch_apply_pulse_o         <= 1'b0;
            switch_reject_pulse_o        <= 1'b0;
            source_discontinuity_pulse_o <= 1'b0;
            output_accept_pulse_o        <= 1'b0;

            if (clear_i) begin
                active_source_mode_q          <= RESET_SOURCE_MODE;
                pending_source_mode_q         <= RESET_SOURCE_MODE;
                pending_switch_q              <= 1'b0;
                output_sample_count_q         <= 64'd0;
                switch_reject_count_q         <= '0;
                source_discontinuity_pulse_o  <= 1'b1;
                invalid_source_mode_sticky_o  <= 1'b0;
                switch_pending_sticky_o       <= 1'b0;
                disabled_sticky_o             <= 1'b0;
            end else begin
                if (clear_sticky_i) begin
                    invalid_source_mode_sticky_o <= 1'b0;
                    switch_pending_sticky_o <= 1'b0;
                    disabled_sticky_o <= 1'b0;
                end

                if (!enable_i && sample_valid_o) begin
                    disabled_sticky_o <= 1'b1;
                    source_discontinuity_pulse_o <= 1'b1;
                end

                if (output_accept) begin
                    output_accept_pulse_o <= 1'b1;
                    output_sample_count_q <= output_sample_count_q + 64'd1;
                end

                if (source_mode_commit_i) begin
                    if (!requested_mode_known) begin
                        switch_reject_pulse_o <= 1'b1;
                        invalid_source_mode_sticky_o <= 1'b1;
                        switch_reject_count_q <= inc_reject_count(switch_reject_count_q);
                    end else begin
                        pending_source_mode_q <= requested_source_mode_i;
                        switch_accept_pulse_o <= 1'b1;
                        if ((requested_source_mode_i == active_source_mode_q) && !pending_switch_q) begin
                            // Idempotent commit. Count as accepted, but do not mark discontinuity.
                        end else if (switch_safe_now) begin
                            apply_source_mode(requested_source_mode_i);
                            pending_switch_q <= 1'b0;
                        end else begin
                            pending_switch_q <= 1'b1;
                            switch_pending_sticky_o <= 1'b1;
                        end
                    end
                end else if (pending_switch_q && switch_safe_now) begin
                    apply_source_mode(pending_source_mode_q);
                    pending_switch_q <= 1'b0;
                end

                if (force_discontinuity_i) begin
                    source_discontinuity_pulse_o <= 1'b1;
                end

                if (!selected_mode_known) begin
                    invalid_source_mode_sticky_o <= 1'b1;
                end
            end
        end
    end

`ifndef SYNTHESIS
    initial begin
        if (!source_mode_known(RESET_SOURCE_MODE)) begin
            $fatal(1, "trecap_source_mux: RESET_SOURCE_MODE is illegal");
        end
        if (SWITCH_REJECT_COUNT_W == 0) begin
            $fatal(1, "trecap_source_mux: SWITCH_REJECT_COUNT_W must be nonzero");
        end
    end

    always_ff @(posedge clk) begin
        if (rst_n && sample_valid_o && (^sample_o.data === 1'bx)) begin
            $error("trecap_source_mux: selected sample data is X while valid");
        end
        if (rst_n && sample_valid_o && (^sample_o.sample_idx === 1'bx)) begin
            $error("trecap_source_mux: selected sample_idx is X while valid");
        end
        if (rst_n && sample_valid_o && !sample_ready_i && (sample_o !== $past(sample_o))) begin
            $error("trecap_source_mux: selected sample changed while downstream stalled");
        end
        if (rst_n && ((bram_sample_ready_o + adc_sample_ready_o + audio_sample_ready_o + diagnostic_sample_ready_o) > 1)) begin
            $error("trecap_source_mux: more than one source ready asserted");
        end
    end
`endif

endmodule : trecap_source_mux

`default_nettype wire
