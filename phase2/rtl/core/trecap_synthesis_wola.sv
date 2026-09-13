// SPDX-License-Identifier: MIT
// File class: [1] hand-written RTL.
// Layer: rtl/core/
// Owner: T-RECAP Phase 2 implementation.
// Purpose: Apply the unsigned synthesis window and maintain the causal overlap-add ring.
// Contract: Mirrors the reference-model ordering at each frame boundary: emit the current H
//           mature samples from the OLA ring, then add z[i] to relative offset G+i from the
//           advanced OLA read pointer. After the final active frame commits, a separate drain
//           token stream emits exactly D remaining OLA samples without creating dummy frames.
//           Qw is unsigned F+1 bits. This block does not packetize, write DDR, or interact with
//           HPS/Ethernet/dashboard logic.

`default_nettype none

module trecap_synthesis_wola
  import trecap_core_pkg::*;
#(
    parameter int unsigned L            = T_FFT_L,
    parameter int unsigned H            = T_HOP_H,
    parameter int unsigned G            = T_CUSHION_G,
    parameter int unsigned D            = T_DELAY_D,
    parameter int unsigned P            = T_FFT_P,
    parameter int unsigned IFFT_W       = T_IFFT_W,
    parameter int unsigned WINDOW_W     = T_QW_W,
    parameter int unsigned Z_W          = T_Z_W,
    parameter int unsigned OLA_W        = T_OLA_W,
    parameter int unsigned OUT_W        = T_SAMPLE_W,
    parameter string       WINDOW_FILE  = "artifacts/coefficients/window_qw.memh"
) (
    input  logic                         clk,
    input  logic                         rst_n,
    input  logic                         enable_i,
    input  logic                         clear_i,
    input  logic                         clear_sticky_i,

    input  logic                         in_valid_i,
    output logic                         in_ready_o,
    input  logic [63:0]                  in_frame_idx_i,
    input  logic [P-1:0]                 in_sample_offset_i,
    input  logic signed [IFFT_W-1:0]     in_re_i,
    input  logic signed [IFFT_W-1:0]     in_im_i,
    input  logic                         in_last_i,

    // Pure full-tail ticks. Their logical sample indices begin at tau_last. They are held by
    // the finite-stream driver until the final active frame has completed STATE_ADD.
    input  logic                         drain_valid_i,
    output logic                         drain_ready_o,
    input  logic [63:0]                  drain_sample_idx_i,
    input  logic                         drain_last_i,
    input  logic [31:0]                  drain_sample_count_i,

    output logic                         out_valid_o,
    input  logic                         out_ready_i,
    output logic signed [OUT_W-1:0]      out_sample_o,
    output logic [63:0]                  out_sample_idx_o,
    output logic [63:0]                  out_frame_idx_o,
    output logic                         out_last_o,

    output logic                         busy_o,
    output logic                         drain_active_o,
    output logic                         drain_accept_pulse_o,
    output logic                         drain_done_pulse_o,
    output logic [63:0]                  accepted_output_count_o,
    output logic                         saturation_sticky_o,
    output logic                         protocol_error_sticky_o
);

    typedef enum logic [2:0] {
        STATE_COLLECT = 3'd0,
        STATE_EMIT    = 3'd1,
        STATE_ADD     = 3'd2,
        STATE_DRAIN   = 3'd3,
        STATE_DONE    = 3'd4
    } wola_state_e;

    localparam int unsigned L_ADDR_W   = (L <= 1) ? 1 : $clog2(L);
    localparam int unsigned D_ADDR_W   = (D <= 1) ? 1 : $clog2(D);
    localparam int unsigned PRODUCT_W  = IFFT_W + WINDOW_W + 1;
    localparam int unsigned OLA_SUM_W  = OLA_W + 1;
    localparam logic [L_ADDR_W-1:0] LAST_L_OFFSET = L_ADDR_W'(L - 1);

    logic signed [OLA_W-1:0] ola_mem [0:D-1];
    logic signed [Z_W-1:0]   z_mem   [0:L-1];

    wola_state_e                 state_q;
    logic [L_ADDR_W-1:0]         collect_offset_q;
    logic [L_ADDR_W-1:0]         add_offset_q;
    logic [31:0]                 emit_remaining_q;
    logic [31:0]                 drain_remaining_q;
    logic [63:0]                 current_frame_idx_q;
    logic [D_ADDR_W-1:0]         rd_addr_q;
    logic [63:0]                 output_issue_count_q;
    logic [63:0]                 output_accept_count_q;

    logic                        out_valid_q;
    logic signed [OUT_W-1:0]     out_sample_q;
    logic [63:0]                 out_sample_idx_q;
    logic [63:0]                 out_frame_idx_q;
    logic                        out_last_q;
    logic                        out_finishes_drain_q;

    logic [WINDOW_W-1:0]         window_coeff_u;
    logic signed [WINDOW_W:0]    window_coeff_s;
    logic                        window_valid;
    logic [L_ADDR_W-1:0]         window_addr_echo;
    logic                        window_oob;

    logic                        in_accept;
    logic                        out_accept;
    logic                        output_slot_available;
    logic                        issue_frame_output;
    logic                        drain_accept;
    logic                        drain_start_pending;
    logic signed [PRODUCT_W-1:0] product_comb;
    logic signed [Z_W-1:0]       z_comb;
    logic                        z_sat;
    logic [D_ADDR_W-1:0]         add_addr_comb;
    logic signed [OLA_SUM_W-1:0] ola_sum_comb;
    logic signed [OLA_W-1:0]     ola_sum_sat_comb;
    logic                        ola_add_sat;
    logic signed [OUT_W-1:0]     emit_sample_comb;
    logic                        emit_sample_sat;

    integer clear_idx;

    function automatic logic [D_ADDR_W-1:0] add_mod_d(
        input logic [D_ADDR_W-1:0] base,
        input int unsigned offset
    );
        int unsigned sum;
        begin
            sum = int'(base) + offset;
            if (sum >= D) begin
                sum = sum - D;
            end
            add_mod_d = D_ADDR_W'(sum);
        end
    endfunction : add_mod_d

    // An index match reserves the WOLA boundary even if the count is malformed. This keeps
    // the block fail-closed: it reports the bad count and backpressures both inputs instead
    // of accepting another active frame or emitting a non-contract tail length.
    assign drain_start_pending = drain_valid_i &&
                                 (drain_sample_idx_i == output_issue_count_q);
    assign in_ready_o = enable_i && !clear_i && (state_q == STATE_COLLECT) &&
                        !drain_start_pending;
    assign in_accept = in_valid_i && in_ready_o;
    assign out_accept = out_valid_q && out_ready_i;
    assign output_slot_available = !out_valid_q || out_ready_i;
    assign issue_frame_output = (state_q == STATE_EMIT) && enable_i &&
                                output_slot_available;
    assign drain_ready_o = enable_i && !clear_i && (state_q == STATE_DRAIN) &&
                           (drain_remaining_q != 32'd0) && output_slot_available;
    assign drain_accept = drain_valid_i && drain_ready_o;

    assign out_valid_o = out_valid_q;
    assign out_sample_o = out_sample_q;
    assign out_sample_idx_o = out_sample_idx_q;
    assign out_frame_idx_o = out_frame_idx_q;
    assign out_last_o = out_last_q;
    assign busy_o = ((state_q != STATE_COLLECT) && (state_q != STATE_DONE)) ||
                    (collect_offset_q != '0) || out_valid_q || drain_valid_i;
    assign drain_active_o = (state_q == STATE_DRAIN) ||
                            ((state_q == STATE_DONE) && out_valid_q &&
                             out_finishes_drain_q);
    assign accepted_output_count_o = output_accept_count_q;

    assign window_coeff_s = $signed({1'b0, window_coeff_u});
    assign product_comb = $signed(in_re_i) * window_coeff_s;
    assign add_addr_comb = add_mod_d(rd_addr_q, G + int'(add_offset_q));
    assign ola_sum_comb = $signed({ola_mem[add_addr_comb][OLA_W-1], ola_mem[add_addr_comb]}) +
                          $signed({{(OLA_SUM_W-Z_W){z_mem[add_offset_q][Z_W-1]}}, z_mem[add_offset_q]});

    window_rom #(
        .DEPTH( L ),
        .ADDR_W( L_ADDR_W ),
        .DATA_W( WINDOW_W ),
        .INIT_FILE( WINDOW_FILE ),
        .REGISTER_OUTPUT( 1'b0 )
    ) u_window_rom (
        .clk( clk ),
        .rst_n( rst_n ),
        .clear_i( clear_i ),
        .valid_i( in_accept ),
        .addr_i( in_sample_offset_i[L_ADDR_W-1:0] ),
        .valid_o( window_valid ),
        .addr_o( window_addr_echo ),
        .coeff_o( window_coeff_u ),
        .addr_oob_o( window_oob )
    );

    trecap_round_sat #(
        .IN_W( PRODUCT_W ),
        .OUT_W( Z_W ),
        .SHIFT( T_FRAC_F )
    ) u_synth_product_round (
        .value_i( product_comb ),
        .value_o( z_comb ),
        .sat_hi_o( ),
        .sat_lo_o( ),
        .sat_any_o( z_sat )
    );

    trecap_round_sat #(
        .IN_W( OLA_SUM_W ),
        .OUT_W( OLA_W ),
        .SHIFT( 0 )
    ) u_ola_add_sat (
        .value_i( ola_sum_comb ),
        .value_o( ola_sum_sat_comb ),
        .sat_hi_o( ),
        .sat_lo_o( ),
        .sat_any_o( ola_add_sat )
    );

    trecap_round_sat #(
        .IN_W( OLA_W ),
        .OUT_W( OUT_W ),
        .SHIFT( T_FRAC_F )
    ) u_ola_emit_round (
        .value_i( ola_mem[rd_addr_q] ),
        .value_o( emit_sample_comb ),
        .sat_hi_o( ),
        .sat_lo_o( ),
        .sat_any_o( emit_sample_sat )
    );

    always_ff @(posedge clk or negedge rst_n) begin : p_synthesis_wola
        if (!rst_n) begin
            state_q <= STATE_COLLECT;
            collect_offset_q <= '0;
            add_offset_q <= '0;
            emit_remaining_q <= 32'd0;
            drain_remaining_q <= 32'd0;
            current_frame_idx_q <= 64'd0;
            rd_addr_q <= '0;
            output_issue_count_q <= 64'd0;
            output_accept_count_q <= 64'd0;
            out_valid_q <= 1'b0;
            out_sample_q <= '0;
            out_sample_idx_q <= 64'd0;
            out_frame_idx_q <= 64'd0;
            out_last_q <= 1'b0;
            out_finishes_drain_q <= 1'b0;
            drain_accept_pulse_o <= 1'b0;
            drain_done_pulse_o <= 1'b0;
            saturation_sticky_o <= 1'b0;
            protocol_error_sticky_o <= 1'b0;
            for (clear_idx = 0; clear_idx < D; clear_idx = clear_idx + 1) begin
                ola_mem[clear_idx] <= '0;
            end
            for (clear_idx = 0; clear_idx < L; clear_idx = clear_idx + 1) begin
                z_mem[clear_idx] <= '0;
            end
        end else begin
            if (clear_i) begin
                state_q <= STATE_COLLECT;
                collect_offset_q <= '0;
                add_offset_q <= '0;
                emit_remaining_q <= 32'd0;
                drain_remaining_q <= 32'd0;
                current_frame_idx_q <= 64'd0;
                rd_addr_q <= '0;
                output_issue_count_q <= 64'd0;
                output_accept_count_q <= 64'd0;
                out_valid_q <= 1'b0;
                out_sample_q <= '0;
                out_sample_idx_q <= 64'd0;
                out_frame_idx_q <= 64'd0;
                out_last_q <= 1'b0;
                out_finishes_drain_q <= 1'b0;
                drain_accept_pulse_o <= 1'b0;
                drain_done_pulse_o <= 1'b0;
                saturation_sticky_o <= 1'b0;
                protocol_error_sticky_o <= 1'b0;
                for (clear_idx = 0; clear_idx < D; clear_idx = clear_idx + 1) begin
                    ola_mem[clear_idx] <= '0;
                end
                for (clear_idx = 0; clear_idx < L; clear_idx = clear_idx + 1) begin
                    z_mem[clear_idx] <= '0;
                end
            end else begin
                drain_accept_pulse_o <= 1'b0;
                drain_done_pulse_o <= 1'b0;

                if (clear_sticky_i) begin
                    saturation_sticky_o <= 1'b0;
                    protocol_error_sticky_o <= 1'b0;
                end

                if (!enable_i &&
                    (in_valid_i || drain_valid_i || out_valid_q ||
                     (state_q != STATE_COLLECT))) begin
                    protocol_error_sticky_o <= 1'b1;
                    state_q <= STATE_COLLECT;
                    collect_offset_q <= '0;
                    add_offset_q <= '0;
                    emit_remaining_q <= 32'd0;
                    drain_remaining_q <= 32'd0;
                    out_valid_q <= 1'b0;
                    out_last_q <= 1'b0;
                    out_finishes_drain_q <= 1'b0;
                end else begin
                    // A registered output remains stable until accepted. If this cycle does not
                    // replace it in STATE_EMIT/STATE_DRAIN, clear valid after the handshake.
                    if (out_accept) begin
                        out_valid_q <= 1'b0;
                        out_last_q <= 1'b0;
                        out_finishes_drain_q <= 1'b0;
                        output_accept_count_q <= output_accept_count_q + 64'd1;
                        if (out_finishes_drain_q) begin
                            drain_done_pulse_o <= 1'b1;
                        end
                    end

                    unique case (state_q)
                        STATE_COLLECT: begin
                            if (drain_valid_i) begin
                                if (drain_sample_idx_i < output_issue_count_q) begin
                                    protocol_error_sticky_o <= 1'b1;
                                end else if (drain_start_pending) begin
                                    if (drain_sample_count_i != D) begin
                                        protocol_error_sticky_o <= 1'b1;
                                    end else begin
                                        if (in_valid_i) begin
                                            protocol_error_sticky_o <= 1'b1;
                                        end
                                        drain_remaining_q <= drain_sample_count_i;
                                        state_q <= STATE_DRAIN;
                                    end
                                end
                            end

                            if (in_accept) begin
                                z_mem[in_sample_offset_i[L_ADDR_W-1:0]] <= z_comb;
                                current_frame_idx_q <= in_frame_idx_i;

                                if (in_sample_offset_i[L_ADDR_W-1:0] != collect_offset_q) begin
                                    protocol_error_sticky_o <= 1'b1;
                                end
                                if (in_last_i != (in_sample_offset_i[L_ADDR_W-1:0] == LAST_L_OFFSET)) begin
                                    protocol_error_sticky_o <= 1'b1;
                                end
                                if (in_im_i != '0) begin
                                    protocol_error_sticky_o <= 1'b1;
                                end
                                if (window_oob || !window_valid ||
                                    (window_addr_echo != in_sample_offset_i[L_ADDR_W-1:0])) begin
                                    protocol_error_sticky_o <= 1'b1;
                                end
                                if (z_sat) begin
                                    saturation_sticky_o <= 1'b1;
                                end

                                if (in_sample_offset_i[L_ADDR_W-1:0] == LAST_L_OFFSET) begin
                                    collect_offset_q <= '0;
                                    emit_remaining_q <= H;
                                    state_q <= STATE_EMIT;
                                end else begin
                                    collect_offset_q <= collect_offset_q + {{(L_ADDR_W-1){1'b0}}, 1'b1};
                                end
                            end else if (in_valid_i && !in_ready_o) begin
                                protocol_error_sticky_o <= 1'b1;
                            end
                        end

                        STATE_EMIT: begin
                            if (issue_frame_output) begin
                                if (emit_remaining_q != 0) begin
                                    out_valid_q <= 1'b1;
                                    out_sample_q <= emit_sample_comb;
                                    out_sample_idx_q <= output_issue_count_q;
                                    out_frame_idx_q <= current_frame_idx_q;
                                    out_last_q <= (emit_remaining_q == 32'd1);
                                    out_finishes_drain_q <= 1'b0;
                                    if (emit_sample_sat) begin
                                        saturation_sticky_o <= 1'b1;
                                    end
                                    ola_mem[rd_addr_q] <= '0;
                                    rd_addr_q <= add_mod_d(rd_addr_q, 1);
                                    output_issue_count_q <= output_issue_count_q + 64'd1;
                                    emit_remaining_q <= emit_remaining_q - 32'd1;
                                    if (emit_remaining_q == 32'd1) begin
                                        add_offset_q <= '0;
                                        state_q <= STATE_ADD;
                                    end
                                end else begin
                                    out_valid_q <= 1'b0;
                                    out_last_q <= 1'b0;
                                    add_offset_q <= '0;
                                    state_q <= STATE_ADD;
                                end
                            end
                        end

                        STATE_ADD: begin
                            ola_mem[add_addr_comb] <= ola_sum_sat_comb;
                            if (ola_add_sat) begin
                                saturation_sticky_o <= 1'b1;
                            end
                            if (add_offset_q == LAST_L_OFFSET) begin
                                add_offset_q <= '0;
                                if (drain_start_pending) begin
                                    if (drain_sample_count_i != D) begin
                                        protocol_error_sticky_o <= 1'b1;
                                        state_q <= STATE_COLLECT;
                                    end else begin
                                        drain_remaining_q <= drain_sample_count_i;
                                        state_q <= STATE_DRAIN;
                                    end
                                end else begin
                                    state_q <= STATE_COLLECT;
                                end
                            end else begin
                                add_offset_q <= add_offset_q + {{(L_ADDR_W-1){1'b0}}, 1'b1};
                            end
                        end

                        STATE_DRAIN: begin
                            if (drain_valid_i &&
                                (drain_sample_idx_i != output_issue_count_q)) begin
                                protocol_error_sticky_o <= 1'b1;
                            end

                            if (drain_accept) begin
                                out_valid_q <= 1'b1;
                                out_sample_q <= emit_sample_comb;
                                out_sample_idx_q <= output_issue_count_q;
                                out_frame_idx_q <= current_frame_idx_q;
                                out_last_q <= (drain_remaining_q == 32'd1);
                                out_finishes_drain_q <=
                                    (drain_remaining_q == 32'd1);
                                drain_accept_pulse_o <= 1'b1;

                                if (drain_last_i !=
                                    (drain_remaining_q == 32'd1)) begin
                                    protocol_error_sticky_o <= 1'b1;
                                end
                                if (emit_sample_sat) begin
                                    saturation_sticky_o <= 1'b1;
                                end

                                ola_mem[rd_addr_q] <= '0;
                                rd_addr_q <= add_mod_d(rd_addr_q, 1);
                                output_issue_count_q <= output_issue_count_q + 64'd1;
                                drain_remaining_q <= drain_remaining_q - 32'd1;

                                if (drain_remaining_q == 32'd1) begin
                                    state_q <= STATE_DONE;
                                end
                            end
                        end

                        STATE_DONE: begin
                            if (in_valid_i || drain_valid_i) begin
                                protocol_error_sticky_o <= 1'b1;
                            end
                        end

                        default: begin
                            state_q <= STATE_COLLECT;
                            protocol_error_sticky_o <= 1'b1;
                        end
                    endcase
                end
            end
        end
    end

`ifndef SYNTHESIS
    initial begin
        if (L != T_FFT_L) begin
            $fatal(1, "trecap_synthesis_wola: L must match generated T_FFT_L");
        end
        if (H != T_HOP_H) begin
            $fatal(1, "trecap_synthesis_wola: H must match generated T_HOP_H");
        end
        if (G != T_CUSHION_G) begin
            $fatal(1, "trecap_synthesis_wola: G must match generated T_CUSHION_G");
        end
        if (D != T_DELAY_D) begin
            $fatal(1, "trecap_synthesis_wola: D must match generated T_DELAY_D");
        end
        if (D != (L + G)) begin
            $fatal(1, "trecap_synthesis_wola: D must equal L + G");
        end
        if ((2 * H) != L) begin
            $fatal(1, "trecap_synthesis_wola: this implementation assumes H = L/2");
        end
        if (WINDOW_W != T_QW_W) begin
            $fatal(1, "trecap_synthesis_wola: WINDOW_W must match generated T_QW_W");
        end
        if (Z_W != T_Z_W) begin
            $fatal(1, "trecap_synthesis_wola: Z_W must match generated T_Z_W");
        end
        if (OLA_W != T_OLA_W) begin
            $fatal(1, "trecap_synthesis_wola: OLA_W must match generated T_OLA_W");
        end
    end
`endif

endmodule : trecap_synthesis_wola

`default_nettype wire
