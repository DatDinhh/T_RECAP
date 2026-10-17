// SPDX-License-Identifier: MIT
// File class: [1] hand-written RTL.
// Layer: rtl/core/
// Owner: T-RECAP Phase 2 implementation.
// Purpose: Apply the frozen unsigned analysis window to one L-sample frame before FFT.
// Contract: Matches reference analysis_window_frame(): u[i] = x_frame[i] * Qw[i].
//           Qw is unsigned W_Qw bits. No fractional downshift is performed in the analysis path.
//           This block does not schedule frames, compute FFTs, masks, WOLA, telemetry, DDR,
//           HPS, Ethernet, or dashboard behavior.

`default_nettype none

module trecap_analysis_window
#(
    parameter int unsigned L            = trecap_core_pkg::T_FFT_L,
    parameter int unsigned P            = trecap_core_pkg::T_FFT_P,
    parameter int unsigned SAMPLE_W     = trecap_core_pkg::T_SAMPLE_W,
    parameter int unsigned WINDOW_W     = trecap_core_pkg::T_QW_W,
    parameter int unsigned OUT_W        = trecap_core_pkg::T_U_W,
    parameter              WINDOW_FILE  = "artifacts/coefficients/window_qw.memh"
) (
    input  logic                         clk,
    input  logic                         rst_n,
    input  logic                         enable_i,
    input  logic                         clear_i,
    input  logic                         clear_sticky_i,

    input  logic                         frame_valid_i,
    output logic                         frame_ready_o,
    input  logic [63:0]                  frame_idx_i,
    input  logic [63:0]                  frame_start_sample_idx_i,

    input  logic                         sample_valid_i,
    output logic                         sample_ready_o,
    input  logic signed [SAMPLE_W-1:0]   sample_i,
    input  logic [63:0]                  sample_idx_i,

    output logic                         out_valid_o,
    input  logic                         out_ready_i,
    output logic signed [OUT_W-1:0]      out_sample_o,
    output logic [P-1:0]                 out_sample_offset_o,
    output logic [63:0]                  out_frame_idx_o,
    output logic [63:0]                  out_source_sample_idx_o,
    output logic                         out_last_o,

    output logic                         busy_o,
    output logic                         frame_accept_pulse_o,
    output logic                         sample_accept_pulse_o,
    output logic                         output_accept_pulse_o,
    output logic                         frame_done_pulse_o,
    output logic                         input_underrun_sticky_o,
    output logic                         output_backpressure_sticky_o,
    output logic                         protocol_error_sticky_o,
    output logic                         window_oob_sticky_o,
    output logic                         saturation_sticky_o
);
  import trecap_core_pkg::*;


    localparam int unsigned ADDR_W = (L <= 1) ? 1 : $clog2(L);
    localparam logic [ADDR_W-1:0] LAST_OFFSET = ADDR_W'(L - 1);
    localparam int unsigned PRODUCT_W = SAMPLE_W + WINDOW_W + 1;

    logic                         active_q;
    logic [ADDR_W-1:0]            offset_q;
    logic [63:0]                  frame_idx_q;
    logic [63:0]                  frame_start_sample_idx_q;

    logic                         out_valid_q;
    logic signed [OUT_W-1:0]      out_sample_q;
    logic [P-1:0]                 out_sample_offset_q;
    logic [63:0]                  out_frame_idx_q;
    logic [63:0]                  out_source_sample_idx_q;
    logic                         out_last_q;

    logic [WINDOW_W-1:0]          window_coeff_u;
    logic                         window_valid;
    logic [ADDR_W-1:0]            window_addr_echo;
    logic                         window_oob;

    logic                         frame_accept;
    logic                         sample_accept;
    logic                         output_accept;
    logic signed [PRODUCT_W-1:0]  product_comb;
    logic signed [OUT_W-1:0]      windowed_sample_comb;
    logic                         sat_any;
    logic [63:0]                  expected_sample_idx_comb;

    window_rom #(
        .DEPTH( L ),
        .ADDR_W( ADDR_W ),
        .DATA_W( WINDOW_W ),
        .INIT_FILE( WINDOW_FILE ),
        .REGISTER_OUTPUT( 1'b0 )
    ) u_window_rom (
        .clk( clk ),
        .rst_n( rst_n ),
        .clear_i( clear_i ),
        .valid_i( active_q ),
        .addr_i( offset_q ),
        .valid_o( window_valid ),
        .addr_o( window_addr_echo ),
        .coeff_o( window_coeff_u ),
        .addr_oob_o( window_oob )
    );

    assign frame_accept  = frame_valid_i && frame_ready_o;
    assign sample_accept = sample_valid_i && sample_ready_o;
    assign output_accept = out_valid_q && out_ready_i;

    assign frame_ready_o  = enable_i && !clear_i && !active_q && !out_valid_q;
    assign sample_ready_o = enable_i && !clear_i && active_q && (!out_valid_q || out_ready_i);
    assign busy_o         = active_q || out_valid_q;

    assign out_valid_o             = out_valid_q;
    assign out_sample_o            = out_sample_q;
    assign out_sample_offset_o     = out_sample_offset_q;
    assign out_frame_idx_o         = out_frame_idx_q;
    assign out_source_sample_idx_o = out_source_sample_idx_q;
    assign out_last_o              = out_last_q;

    assign expected_sample_idx_comb = frame_start_sample_idx_q + {{(64-ADDR_W){1'b0}}, offset_q};

    // Qw is unsigned. Extend it with a leading zero before multiplication so 16'h8000 is
    // +32768, not a signed -32768.
    assign product_comb = $signed(sample_i) * $signed({1'b0, window_coeff_u});

    trecap_round_sat #(
        .IN_W( PRODUCT_W ),
        .OUT_W( OUT_W ),
        .SHIFT( 0 )
    ) u_product_fit (
        .value_i( product_comb ),
        .value_o( windowed_sample_comb ),
        .sat_hi_o( ),
        .sat_lo_o( ),
        .sat_any_o( sat_any )
    );

    always_ff @(posedge clk or negedge rst_n) begin : p_analysis_window
        if (!rst_n) begin
            active_q                     <= 1'b0;
            offset_q                     <= '0;
            frame_idx_q                  <= 64'd0;
            frame_start_sample_idx_q     <= 64'd0;
            out_valid_q                  <= 1'b0;
            out_sample_q                 <= '0;
            out_sample_offset_q          <= '0;
            out_frame_idx_q              <= 64'd0;
            out_source_sample_idx_q      <= 64'd0;
            out_last_q                   <= 1'b0;
            frame_accept_pulse_o         <= 1'b0;
            sample_accept_pulse_o        <= 1'b0;
            output_accept_pulse_o        <= 1'b0;
            frame_done_pulse_o           <= 1'b0;
            input_underrun_sticky_o      <= 1'b0;
            output_backpressure_sticky_o <= 1'b0;
            protocol_error_sticky_o      <= 1'b0;
            window_oob_sticky_o          <= 1'b0;
            saturation_sticky_o          <= 1'b0;
        end else begin
            frame_accept_pulse_o  <= 1'b0;
            sample_accept_pulse_o <= 1'b0;
            output_accept_pulse_o <= 1'b0;
            frame_done_pulse_o    <= 1'b0;

            if (clear_i) begin
                active_q                     <= 1'b0;
                offset_q                     <= '0;
                frame_idx_q                  <= 64'd0;
                frame_start_sample_idx_q     <= 64'd0;
                out_valid_q                  <= 1'b0;
                out_sample_q                 <= '0;
                out_sample_offset_q          <= '0;
                out_frame_idx_q              <= 64'd0;
                out_source_sample_idx_q      <= 64'd0;
                out_last_q                   <= 1'b0;
                input_underrun_sticky_o      <= 1'b0;
                output_backpressure_sticky_o <= 1'b0;
                protocol_error_sticky_o      <= 1'b0;
                window_oob_sticky_o          <= 1'b0;
                saturation_sticky_o          <= 1'b0;
            end else begin
                if (clear_sticky_i) begin
                    input_underrun_sticky_o      <= 1'b0;
                    output_backpressure_sticky_o <= 1'b0;
                    protocol_error_sticky_o      <= 1'b0;
                    window_oob_sticky_o          <= 1'b0;
                    saturation_sticky_o          <= 1'b0;
                end

                if (output_accept && !sample_accept) begin
                    out_valid_q <= 1'b0;
                    out_last_q  <= 1'b0;
                    output_accept_pulse_o <= 1'b1;
                end

                if (frame_accept) begin
                    active_q                 <= 1'b1;
                    offset_q                 <= '0;
                    frame_idx_q              <= frame_idx_i;
                    frame_start_sample_idx_q <= frame_start_sample_idx_i;
                    frame_accept_pulse_o     <= 1'b1;
                end

                if (sample_accept) begin
                    out_valid_q             <= 1'b1;
                    out_sample_q            <= windowed_sample_comb;
                    out_sample_offset_q     <= P'(offset_q);
                    out_frame_idx_q         <= frame_idx_q;
                    out_source_sample_idx_q <= sample_idx_i;
                    out_last_q              <= (offset_q == LAST_OFFSET);
                    sample_accept_pulse_o   <= 1'b1;

                    if (output_accept) begin
                        output_accept_pulse_o <= 1'b1;
                    end
                    if (!window_valid || window_oob || (window_addr_echo != offset_q)) begin
                        window_oob_sticky_o <= 1'b1;
                        protocol_error_sticky_o <= 1'b1;
                    end
                    if (sample_idx_i != expected_sample_idx_comb) begin
                        protocol_error_sticky_o <= 1'b1;
                    end
                    if (sat_any) begin
                        saturation_sticky_o <= 1'b1;
                    end

                    if (offset_q == LAST_OFFSET) begin
                        active_q <= 1'b0;
                        offset_q <= '0;
                        frame_done_pulse_o <= 1'b1;
                    end else begin
                        offset_q <= offset_q + {{(ADDR_W-1){1'b0}}, 1'b1};
                    end
                end

                if (out_valid_q && !out_ready_i) begin
                    output_backpressure_sticky_o <= 1'b1;
                end

                if (!enable_i && active_q) begin
                    active_q <= 1'b0;
                    protocol_error_sticky_o <= 1'b1;
                end
            end
        end
    end

`ifndef SYNTHESIS
    initial begin
        if (L != T_FFT_L) begin
            $fatal(1, "trecap_analysis_window: L must match generated T_FFT_L");
        end
        if (P != T_FFT_P) begin
            $fatal(1, "trecap_analysis_window: P must match generated T_FFT_P");
        end
        if (SAMPLE_W != T_SAMPLE_W) begin
            $fatal(1, "trecap_analysis_window: SAMPLE_W must match generated T_SAMPLE_W");
        end
        if (WINDOW_W != T_QW_W) begin
            $fatal(1, "trecap_analysis_window: WINDOW_W must match generated T_QW_W");
        end
        if (OUT_W != T_U_W) begin
            $fatal(1, "trecap_analysis_window: OUT_W must match generated T_U_W");
        end
    end
`endif

endmodule : trecap_analysis_window

`default_nettype wire
