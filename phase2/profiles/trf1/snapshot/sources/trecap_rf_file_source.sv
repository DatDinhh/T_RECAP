// SPDX-License-Identifier: MIT
// Finite-file RF source. Padding belongs to the transaction, not the RF signal.
`default_nettype none
module trecap_rf_file_source #(
    parameter integer TRANSACTION_SAMPLES = 384000
) (
    input  logic clk,
    input  logic rst_n,
    input  logic clear_i,
    input  logic start_valid_i,
    output logic start_ready_o,
    input  logic [31:0] pair_count_i,
    input  logic [1:0] gain_shift_i,
    input  logic iq_valid_i,
    output logic iq_ready_o,
    input  logic [7:0] iq_i_i,
    input  logic [7:0] iq_q_i,
    output logic sample_valid_o,
    input  logic sample_ready_i,
    output logic signed [11:0] sample_data_o,
    output logic [31:0] sample_index_o,
    output logic sample_last_o,
    output logic sample_clipped_o,
    output logic busy_o,
    output logic done_o,
    output logic config_error_o,
    output logic [31:0] input_count_o,
    output logic [31:0] output_count_o,
    output logic [31:0] clip_count_o,
    output logic clip_sticky_o,
    output logic [31:0] valid_sample_count_o,
    output logic [31:0] adapter_output_count_o
);
    localparam bit CONFIG_OK = (TRANSACTION_SAMPLES > 0) &&
                                ((TRANSACTION_SAMPLES % 4) == 0);
    localparam integer MAX_PAIRS = CONFIG_OK ? TRANSACTION_SAMPLES / 4 : 1;
    logic active_q, padding_q;
    logic [31:0] accepted_q, valid_samples_q;
    logic adapter_start_ready, adapter_iq_ready, adapter_valid;
    logic adapter_last, adapter_clipped, adapter_config_error;
    logic signed [11:0] adapter_data;
    wire admitted = start_valid_i && start_ready_o &&
                    (pair_count_i != 0) && (pair_count_i <= MAX_PAIRS);
    wire accepted = sample_valid_o && sample_ready_i;

    assign start_ready_o = rst_n && !clear_i && CONFIG_OK &&
                           !active_q && adapter_start_ready;
    assign iq_ready_o = rst_n && !clear_i && active_q &&
                        !padding_q && adapter_iq_ready;
    assign sample_valid_o = rst_n && !clear_i && active_q &&
                            (padding_q || adapter_valid);
    assign sample_data_o = padding_q ? 12'sd0 : adapter_data;
    assign sample_index_o = accepted_q;
    assign sample_last_o = sample_valid_o && (accepted_q == TRANSACTION_SAMPLES - 1);
    assign sample_clipped_o = !padding_q && adapter_clipped;
    assign busy_o = active_q;
    assign config_error_o = adapter_config_error || !CONFIG_OK;
    assign output_count_o = accepted_q;
    assign valid_sample_count_o = valid_samples_q;

    trecap_rf_iq_adapter #(.MAX_PAIRS(MAX_PAIRS)) adapter (
        .clk(clk), .rst_n(rst_n), .clear_i(clear_i),
        .start_valid_i(start_valid_i && !active_q && CONFIG_OK),
        .start_ready_o(adapter_start_ready),
        .pair_count_i(pair_count_i), .gain_shift_i(gain_shift_i),
        .iq_valid_i(iq_valid_i && active_q && !padding_q),
        .iq_ready_o(adapter_iq_ready), .iq_i_i(iq_i_i), .iq_q_i(iq_q_i),
        .sample_valid_o(adapter_valid),
        .sample_ready_i(sample_ready_i && active_q && !padding_q),
        .sample_data_o(adapter_data), .sample_index_o(),
        .sample_last_o(adapter_last), .sample_clipped_o(adapter_clipped),
        .busy_o(), .done_o(), .config_error_o(adapter_config_error),
        .input_count_o(input_count_o), .output_count_o(adapter_output_count_o),
        .clip_count_o(clip_count_o), .clip_sticky_o(clip_sticky_o)
    );

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            active_q <= 1'b0;
            padding_q <= 1'b0;
            accepted_q <= 32'd0;
            valid_samples_q <= 32'd0;
            done_o <= 1'b0;
        end else begin
            done_o <= 1'b0;
            if (clear_i) begin
                active_q <= 1'b0;
                padding_q <= 1'b0;
                accepted_q <= 32'd0;
                valid_samples_q <= 32'd0;
            end else if (admitted) begin
                active_q <= 1'b1;
                padding_q <= 1'b0;
                accepted_q <= 32'd0;
                valid_samples_q <= pair_count_i << 2;
            end else if (accepted) begin
                accepted_q <= accepted_q + 32'd1;
                if (accepted_q == TRANSACTION_SAMPLES - 1) begin
                    active_q <= 1'b0;
                    padding_q <= 1'b0;
                    done_o <= 1'b1;
                end else if (!padding_q && adapter_last) begin
                    padding_q <= 1'b1;
                end
            end
        end
    end

`ifndef SYNTHESIS
    initial begin
        if (!CONFIG_OK)
            $fatal(1, "RF transaction length must be positive and divisible by four");
    end
`endif
endmodule
`default_nettype wire
