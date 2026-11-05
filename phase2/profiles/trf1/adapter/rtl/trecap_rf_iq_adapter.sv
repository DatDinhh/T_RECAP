// SPDX-License-Identifier: MIT
// Finite CU8 I/Q -> real low-IF source. See ../CONTRACT.md.
// One shared multiplier. No change to the existing T-RECAP numerical core.
`default_nettype none
module trecap_rf_iq_adapter #(
    parameter integer MAX_PAIRS = 96000
)(
    input  wire clk,
    input  wire rst_n,
    input  wire clear_i,
    input  wire start_valid_i,
    output wire start_ready_o,
    input  wire [31:0] pair_count_i,
    input  wire [1:0] gain_shift_i,
    input  wire iq_valid_i,
    output wire iq_ready_o,
    input  wire [7:0] iq_i_i,
    input  wire [7:0] iq_q_i,
    output wire sample_valid_o,
    input  wire sample_ready_i,
    output reg signed [11:0] sample_data_o,
    output wire [31:0] sample_index_o,
    output wire sample_last_o,
    output reg sample_clipped_o,
    output wire busy_o,
    output reg done_o,
    output reg config_error_o,
    output reg [31:0] input_count_o,
    output reg [31:0] output_count_o,
    output reg [31:0] clip_count_o,
    output reg clip_sticky_o
);
    localparam [2:0] IDLE=0, LOAD=1, MAC=2, MAKE=3, HOLD=4;
    reg [2:0] state_q;
    reg [31:0] count_q, group_q;
    reg [1:0] gain_q, phase_q;
    reg [4:0] tap_q;
    reg signed [8:0] hist_i [0:20];
    reg signed [8:0] hist_q [0:20];
    reg signed [35:0] acc_q;
    integer k;

    `include "rf_coefficients.svh"

    wire active = rst_n && !clear_i;
    assign start_ready_o = active && state_q==IDLE && !config_error_o;
    assign iq_ready_o = active && state_q==LOAD && input_count_o<count_q;
    assign sample_valid_o = active && state_q==HOLD;
    assign sample_index_o = output_count_o;
    assign sample_last_o = sample_valid_o && output_count_o==((count_q<<2)-1);
    assign busy_o = active && state_q!=IDLE;

    wire signed [9:0] centered_i = $signed({1'b0,iq_i_i,1'b0}) - 10'sd255;
    wire signed [9:0] centered_q = $signed({1'b0,iq_q_i,1'b0}) - 10'sd255;
    wire [6:0] coeff_index = {tap_q,phase_q};
    wire signed [17:0] coefficient = rf_coeff(coeff_index);
    wire signed [8:0] history_value = phase_q[0] ? hist_q[tap_q] : hist_i[tap_q];
    wire signed [26:0] product = history_value * coefficient;
    wire signed [35:0] product_extended = {{9{product[26]}},product};

    // Apply oscillator sign before rounding. All intermediate arithmetic is
    // wider than the coefficient-bound worst case, including its negation.
    wire negate_phase = phase_q==1 || phase_q==2;
    wire signed [35:0] mixed = negate_phase ? -acc_q : acc_q;
    wire [4:0] shift_bits = 5'd16 - {3'd0,gain_q};
    wire signed [35:0] magnitude = mixed[35] ? -mixed : mixed;
    wire signed [35:0] half_lsb = 36'sd1 << (shift_bits-1'b1);
    wire signed [35:0] rounded_abs = (magnitude + half_lsb) >>> shift_bits;
    wire signed [35:0] rounded = mixed[35] ? -rounded_abs : rounded_abs;
    wire clipped = rounded>36'sd2047 || rounded < -36'sd2048;
    wire signed [11:0] quantized = rounded>36'sd2047 ? 12'sd2047 :
                                  rounded < -36'sd2048 ? 12'sh800 : rounded[11:0];

    // Reset and clear abort even a stalled output. The containing system must
    // clear its finite-stream consumer too when abandoning a transaction.
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state_q<=IDLE; count_q<=0; group_q<=0; gain_q<=0;
            phase_q<=0; tap_q<=0; acc_q<=0;
            sample_data_o<=0; sample_clipped_o<=0;
            done_o<=0; config_error_o<=0;
            input_count_o<=0; output_count_o<=0; clip_count_o<=0; clip_sticky_o<=0;
            for (k=0;k<21;k=k+1) begin hist_i[k]<=0; hist_q[k]<=0; end
        end else if (clear_i) begin
            state_q<=IDLE; count_q<=0; group_q<=0; gain_q<=0;
            phase_q<=0; tap_q<=0; acc_q<=0;
            sample_data_o<=0; sample_clipped_o<=0;
            done_o<=0; config_error_o<=0;
            input_count_o<=0; output_count_o<=0; clip_count_o<=0; clip_sticky_o<=0;
            for (k=0;k<21;k=k+1) begin hist_i[k]<=0; hist_q[k]<=0; end
        end else begin
            done_o<=0;
            case(state_q)
                IDLE: if(start_valid_i && start_ready_o) begin
                    if(pair_count_i==0 || pair_count_i>MAX_PAIRS) begin
                        config_error_o<=1;
                    end else begin
                        count_q<=pair_count_i; gain_q<=gain_shift_i;
                        group_q<=0; phase_q<=0; tap_q<=0; acc_q<=0;
                        input_count_o<=0; output_count_o<=0;
                        clip_count_o<=0; clip_sticky_o<=0;
                        sample_data_o<=0; sample_clipped_o<=0;
                        for(k=0;k<21;k=k+1) begin hist_i[k]<=0; hist_q[k]<=0; end
                        state_q<=LOAD;
                    end
                end
                LOAD: if(input_count_o==count_q || (iq_valid_i && iq_ready_o)) begin
                    for(k=20;k>0;k=k-1) begin
                        hist_i[k]<=hist_i[k-1]; hist_q[k]<=hist_q[k-1];
                    end
                    if(input_count_o==count_q) begin
                        // A padded zero is not representable by a CU8 byte.
                        hist_i[0]<=0; hist_q[0]<=0;
                    end else begin
                        hist_i[0]<=centered_i[8:0]; hist_q[0]<=centered_q[8:0];
                        input_count_o<=input_count_o+1'b1;
                    end
                    phase_q<=0; tap_q<=0; acc_q<=0; state_q<=MAC;
                end
                MAC: begin
                    acc_q<=acc_q+product_extended;
                    if(tap_q==20) state_q<=MAKE;
                    else tap_q<=tap_q+1'b1;
                end
                MAKE: begin
                    if(group_q<10) begin
                        // Discard the causal filter's first 40 real outputs.
                        tap_q<=0; acc_q<=0;
                        if(phase_q==3) begin group_q<=group_q+1'b1; state_q<=LOAD; end
                        else begin phase_q<=phase_q+1'b1; state_q<=MAC; end
                    end else begin
                        sample_data_o<=quantized; sample_clipped_o<=clipped;
                        state_q<=HOLD;
                    end
                end
                HOLD: if(sample_ready_i) begin
                    output_count_o<=output_count_o+1'b1;
                    if(sample_clipped_o) begin
                        clip_count_o<=clip_count_o+1'b1; clip_sticky_o<=1;
                    end
                    if(sample_last_o) begin state_q<=IDLE; done_o<=1; end
                    else begin
                        tap_q<=0; acc_q<=0;
                        if(phase_q==3) begin group_q<=group_q+1'b1; state_q<=LOAD; end
                        else begin phase_q<=phase_q+1'b1; state_q<=MAC; end
                    end
                end
                default: begin state_q<=IDLE; config_error_o<=1; end
            endcase
        end
    end

    // synthesis translate_off
    initial begin
        if(MAX_PAIRS<1 || MAX_PAIRS>1073741823)
            $fatal(1,"MAX_PAIRS must leave room for a 32-bit four-times output count");
    end
    // synthesis translate_on
endmodule
`default_nettype wire
