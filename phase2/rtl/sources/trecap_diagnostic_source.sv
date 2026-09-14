// SPDX-License-Identifier: MIT
// File class: [1] hand-written RTL source module.
// Layer: rtl/sources/
// Owner: T-RECAP Phase 2 implementation.
// Purpose: Deterministic non-signoff source streams for board and transport bring-up.
// Contract: Diagnostic streams are observability aids only. They do not replace BRAM replay
//           signoff and do not implement FFT/IFFT/WOLA/mask/error, telemetry packets, DDR writes,
//           HPS software, Ethernet, or dashboard behavior.

`default_nettype none

module trecap_diagnostic_source
#(
    parameter logic [15:0] LFSR_SEED = 16'hace1,
    parameter int unsigned DROP_COUNT_W = 32,
    // Zero keeps runtime period_i behavior; nonzero specializes a fixed profile.
    parameter int unsigned DIAGNOSTIC_PERIOD_FIXED = 0
) (
    input  logic                         clk,
    input  logic                         rst_n,
    input  logic                         enable_i,
    input  logic                         clear_i,
    input  logic                         clear_sticky_i,

    // Diagnostic mode. This is deliberately local to the diagnostic source; it is not the
    // generated source-mode enum. The source mux decides whether this source is selected.
    //   0: signed ramp
    //   1: single impulse at sample_idx 0, then zero
    //   2: constant
    //   3: alternating +amplitude/-amplitude
    //   4: deterministic 16-bit LFSR centered to signed sample range
    //   5: periodic impulse, fixed parameter or period_i clamped to at least 1
    input  logic [2:0]                   diag_mode_i,
    input  logic signed [trecap_core_pkg::T_SAMPLE_W-1:0] constant_i,
    input  logic signed [trecap_core_pkg::T_SAMPLE_W-1:0] amplitude_i,
    input  logic [31:0]                  period_i,

    input  logic                         sample_ready_i,
    output trecap_iface_pkg::trecap_sample_t               sample_o,
    output logic                         sample_valid_o,
    output logic signed [trecap_core_pkg::T_SAMPLE_W-1:0] sample_data_o,
    output logic [63:0]                  sample_idx_o,

    output logic                         output_accept_pulse_o,
    output logic                         source_discontinuity_pulse_o,
    output logic [63:0]                  samples_issued_o,
    output logic [63:0]                  samples_accepted_o,
    output logic [DROP_COUNT_W-1:0]      dropped_sample_count_o,
    output logic [15:0]                  lfsr_state_o,
    output logic                         mode_error_sticky_o,
    output logic                         disabled_sticky_o
);
  import trecap_core_pkg::*;
  import trecap_iface_pkg::*;
  import trecap_math_pkg::*;


    localparam int unsigned DROP_COUNT_SAFE_W = (DROP_COUNT_W == 0) ? 1 : DROP_COUNT_W;

    typedef enum logic [2:0] {
        TDIAG_RAMP             = 3'd0,
        TDIAG_SINGLE_IMPULSE   = 3'd1,
        TDIAG_CONSTANT         = 3'd2,
        TDIAG_ALTERNATING      = 3'd3,
        TDIAG_LFSR             = 3'd4,
        TDIAG_PERIODIC_IMPULSE = 3'd5
    } trecap_diag_mode_e;

    trecap_sample_t pending_sample_q;
    logic [63:0]    next_sample_idx_q;
    logic [63:0]    samples_issued_q;
    logic [63:0]    samples_accepted_q;
    logic [DROP_COUNT_SAFE_W-1:0] dropped_sample_count_q;
    logic [15:0]    lfsr_q;

    logic           output_accept;
    logic           can_issue;
    logic           mode_known;
    logic [31:0]    period_safe;
    logic           periodic_impulse_due;
    logic signed [T_SAMPLE_W-1:0] next_data_comb;
    logic [15:0]    lfsr_next;

    assign output_accept = pending_sample_q.valid && sample_ready_i;
    assign can_issue = enable_i && (!pending_sample_q.valid || output_accept);
    assign period_safe = (period_i == 32'd0) ? 32'd1 : period_i;

    generate
        if (DIAGNOSTIC_PERIOD_FIXED == 0) begin : gen_dynamic_period
            // Evaluate the current runtime period at each issue, as before.
            assign periodic_impulse_due = ((next_sample_idx_q % period_safe) == 0);
        end else if ((DIAGNOSTIC_PERIOD_FIXED & (DIAGNOSTIC_PERIOD_FIXED - 1)) == 0)
            begin : gen_fixed_power_of_two_period
            // A 64-bit mask also covers period=1 without a zero-width slice.
            localparam logic [63:0] PERIOD_MASK = 64'(DIAGNOSTIC_PERIOD_FIXED) - 64'd1;
            assign periodic_impulse_due = ((next_sample_idx_q & PERIOD_MASK) == 64'd0);
        end else begin : gen_fixed_period
            assign periodic_impulse_due =
                ((next_sample_idx_q % 64'(DIAGNOSTIC_PERIOD_FIXED)) == 64'd0);
        end
    endgenerate

    assign sample_o = pending_sample_q;
    assign sample_valid_o = pending_sample_q.valid;
    assign sample_data_o = pending_sample_q.data;
    assign sample_idx_o = pending_sample_q.sample_idx;
    assign samples_issued_o = samples_issued_q;
    assign samples_accepted_o = samples_accepted_q;
    assign dropped_sample_count_o = dropped_sample_count_q[DROP_COUNT_W-1:0];
    assign lfsr_state_o = lfsr_q;

    function automatic logic [15:0] lfsr_step(input logic [15:0] value);
        logic feedback;
    begin
        // x^16 + x^14 + x^13 + x^11 + 1. Avoid all-zero lock-up by injecting the seed.
        feedback = value[15] ^ value[13] ^ value[12] ^ value[10];
        lfsr_step = {value[14:0], feedback};
        if (lfsr_step == 16'h0000) begin
            lfsr_step = LFSR_SEED;
        end
    end
    endfunction : lfsr_step

    function automatic logic signed [T_SAMPLE_W-1:0] lfsr_to_sample(input logic [15:0] value);
        trecap_math_swide_t centered;
        trecap_math_swide_t scaled;
    begin
        centered = trecap_math_swide_t'({1'b0, value}) - trecap_math_swide_t'(16'd32768);
        scaled = trecap_rnd_shr(centered, 16 - T_SAMPLE_W);
        lfsr_to_sample = trecap_sat_sample(scaled);
    end
    endfunction : lfsr_to_sample

    function automatic logic signed [T_SAMPLE_W-1:0] ramp_to_sample(input logic [63:0] idx);
        logic signed [T_SAMPLE_W-1:0] truncated;
    begin
        truncated = idx[T_SAMPLE_W-1:0];
        return truncated;
    end
    endfunction : ramp_to_sample

    always_comb begin
        mode_known = 1'b1;
        lfsr_next = lfsr_step(lfsr_q);
        unique case (diag_mode_i)
            TDIAG_RAMP: begin
                next_data_comb = ramp_to_sample(next_sample_idx_q);
            end
            TDIAG_SINGLE_IMPULSE: begin
                next_data_comb = (next_sample_idx_q == 64'd0) ? amplitude_i : '0;
            end
            TDIAG_CONSTANT: begin
                next_data_comb = constant_i;
            end
            TDIAG_ALTERNATING: begin
                next_data_comb = next_sample_idx_q[0] ? -amplitude_i : amplitude_i;
            end
            TDIAG_LFSR: begin
                next_data_comb = lfsr_to_sample(lfsr_next);
            end
            TDIAG_PERIODIC_IMPULSE: begin
                next_data_comb = periodic_impulse_due ? amplitude_i : '0;
            end
            default: begin
                next_data_comb = '0;
                mode_known = 1'b0;
            end
        endcase
    end

    function automatic logic [DROP_COUNT_SAFE_W-1:0] inc_drop_count(
        input logic [DROP_COUNT_SAFE_W-1:0] value
    );
        if (&value) begin
            inc_drop_count = value;
        end else begin
            inc_drop_count = value + {{(DROP_COUNT_SAFE_W-1){1'b0}}, 1'b1};
        end
    endfunction : inc_drop_count

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            pending_sample_q             <= '0;
            next_sample_idx_q            <= 64'd0;
            samples_issued_q             <= 64'd0;
            samples_accepted_q           <= 64'd0;
            dropped_sample_count_q       <= '0;
            lfsr_q                       <= (LFSR_SEED == 16'h0000) ? 16'hace1 : LFSR_SEED;
            output_accept_pulse_o        <= 1'b0;
            source_discontinuity_pulse_o <= 1'b0;
            mode_error_sticky_o          <= 1'b0;
            disabled_sticky_o            <= 1'b0;
        end else begin
            output_accept_pulse_o        <= 1'b0;
            source_discontinuity_pulse_o <= 1'b0;

            if (clear_i) begin
                pending_sample_q             <= '0;
                next_sample_idx_q            <= 64'd0;
                samples_issued_q             <= 64'd0;
                samples_accepted_q           <= 64'd0;
                dropped_sample_count_q       <= '0;
                lfsr_q                       <= (LFSR_SEED == 16'h0000) ? 16'hace1 : LFSR_SEED;
                source_discontinuity_pulse_o <= 1'b1;
                mode_error_sticky_o          <= 1'b0;
                disabled_sticky_o            <= 1'b0;
            end else begin
                if (clear_sticky_i) begin
                    mode_error_sticky_o <= 1'b0;
                    disabled_sticky_o   <= 1'b0;
                end

                if (!enable_i && pending_sample_q.valid) begin
                    pending_sample_q.valid <= 1'b0;
                    disabled_sticky_o <= 1'b1;
                    dropped_sample_count_q <= inc_drop_count(dropped_sample_count_q);
                    source_discontinuity_pulse_o <= 1'b1;
                end else begin
                    if (output_accept) begin
                        output_accept_pulse_o <= 1'b1;
                        samples_accepted_q <= samples_accepted_q + 64'd1;
                    end

                    if (can_issue) begin
                        pending_sample_q.valid <= 1'b1;
                        pending_sample_q.data <= mode_known ? next_data_comb : '0;
                        pending_sample_q.sample_idx <= next_sample_idx_q;
                        next_sample_idx_q <= next_sample_idx_q + 64'd1;
                        samples_issued_q <= samples_issued_q + 64'd1;
                        if (diag_mode_i == TDIAG_LFSR) begin
                            lfsr_q <= lfsr_next;
                        end
                        if (!mode_known) begin
                            mode_error_sticky_o <= 1'b1;
                        end
                    end else if (output_accept) begin
                        pending_sample_q.valid <= 1'b0;
                    end
                end
            end
        end
    end

`ifndef SYNTHESIS
    initial begin
        if (DROP_COUNT_W == 0) begin
            $fatal(1, "trecap_diagnostic_source: DROP_COUNT_W must be nonzero");
        end
        if (T_SAMPLE_W > 16) begin
            $warning("trecap_diagnostic_source: LFSR display mapping assumes T_SAMPLE_W <= 16");
        end
    end

    always_ff @(posedge clk) begin
        if (rst_n && pending_sample_q.valid && (^pending_sample_q.data === 1'bx)) begin
            $error("trecap_diagnostic_source: sample data is X while valid");
        end
        if (rst_n && pending_sample_q.valid && !sample_ready_i &&
            (pending_sample_q !== $past(pending_sample_q))) begin
            $error("trecap_diagnostic_source: output payload changed while stalled");
        end
    end
`endif

endmodule : trecap_diagnostic_source

`default_nettype wire
