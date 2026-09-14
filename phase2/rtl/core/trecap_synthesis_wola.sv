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
#(
    parameter int unsigned L            = trecap_core_pkg::T_FFT_L,
    parameter int unsigned H            = trecap_core_pkg::T_HOP_H,
    parameter int unsigned G            = trecap_core_pkg::T_CUSHION_G,
    parameter int unsigned D            = trecap_core_pkg::T_DELAY_D,
    parameter int unsigned P            = trecap_core_pkg::T_FFT_P,
    parameter int unsigned IFFT_W       = trecap_core_pkg::T_IFFT_W,
    parameter int unsigned WINDOW_W     = trecap_core_pkg::T_QW_W,
    parameter int unsigned Z_W          = trecap_core_pkg::T_Z_W,
    parameter int unsigned OLA_W        = trecap_core_pkg::T_OLA_W,
    parameter int unsigned OUT_W        = trecap_core_pkg::T_SAMPLE_W,
    parameter              WINDOW_FILE  = "artifacts/coefficients/window_qw.memh"
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
    // the finite-stream driver until the final active frame has completed the final overlap-add write.
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
  import trecap_core_pkg::*;


    typedef enum logic [3:0] {
        STATE_SCRUB, STATE_COLLECT, STATE_COLLECT_WAIT,
        STATE_EMIT_READ, STATE_EMIT_CAPTURE, STATE_ADD_READ, STATE_ADD_WRITE,
        STATE_DRAIN, STATE_DRAIN_CAPTURE, STATE_DONE, STATE_FAULT
    } wola_state_e;

    localparam int unsigned L_ADDR_W = (L <= 1) ? 1 : $clog2(L);
    localparam int unsigned D_ADDR_W = (D <= 1) ? 1 : $clog2(D);
    localparam int unsigned PRODUCT_W = IFFT_W + WINDOW_W + 1;
    localparam int unsigned OLA_SUM_W = OLA_W + 1;
    localparam logic [L_ADDR_W-1:0] LAST_L_OFFSET = L_ADDR_W'(L - 1);

    // Payload arrays have synchronous ports and no asynchronous/full-array reset.
    // OLA is scrubbed through its write port; z is fully overwritten per frame.
    (* ramstyle = "M10K" *) logic signed [OLA_W-1:0] ola_mem [0:D-1];
    (* ramstyle = "M10K" *) logic signed [Z_W-1:0] z_mem [0:L-1];
    (* ramstyle = "M10K" *) logic [WINDOW_W-1:0] window_mem [0:L-1];
    logic signed [OLA_W-1:0] ola_read_q;
    logic signed [Z_W-1:0] z_read_q;
    logic [WINDOW_W-1:0] window_coeff_q;

    wola_state_e state_q;
    logic [D_ADDR_W-1:0] scrub_addr_q;
    logic [L_ADDR_W-1:0] collect_offset_q;
    logic [L_ADDR_W-1:0] add_offset_q;
    logic [31:0] emit_remaining_q;
    logic [31:0] drain_remaining_q;
    logic [63:0] current_frame_idx_q;
    logic [D_ADDR_W-1:0] rd_addr_q;
    logic [63:0] output_issue_count_q;
    logic [63:0] output_accept_count_q;

    // Window lookup -> registered product -> rounded z RAM write. Throughput
    // is one accepted IFFT sample per clock; the last sample drains two stages.
    logic sample_pipe_valid_q;
    logic signed [IFFT_W-1:0] sample_pipe_re_q;
    logic [L_ADDR_W-1:0] sample_pipe_offset_q;
    logic sample_pipe_last_q;
    logic product_valid_q;
    logic signed [PRODUCT_W-1:0] product_q;
    logic [L_ADDR_W-1:0] product_offset_q;
    logic product_last_q;

    logic out_valid_q;
    logic signed [OUT_W-1:0] out_sample_q;
    logic [63:0] out_sample_idx_q;
    logic [63:0] out_frame_idx_q;
    logic out_last_q;
    logic out_finishes_drain_q;

    logic in_accept;
    logic out_accept;
    logic output_slot_available;
    logic issue_frame_output;
    logic drain_accept;
    logic drain_start_pending;
    logic input_token_good;
    logic z_write_en;
    logic signed [Z_W-1:0] z_comb;
    logic z_sat;
    logic [D_ADDR_W-1:0] add_addr_comb;
    logic ola_read_en;
    logic [D_ADDR_W-1:0] ola_read_addr;
    logic ola_write_en;
    logic [D_ADDR_W-1:0] ola_write_addr;
    logic signed [OLA_W-1:0] ola_write_data;
    logic signed [OLA_SUM_W-1:0] ola_sum_comb;
    logic signed [OLA_W-1:0] ola_sum_sat_comb;
    logic ola_add_sat;
    logic signed [OUT_W-1:0] emit_sample_comb;
    logic emit_sample_sat;

    function automatic logic [D_ADDR_W-1:0] add_mod_d(
        input logic [D_ADDR_W-1:0] base,
        input int unsigned offset
    );
        int unsigned sum;
        begin
            sum = int'(base) + offset;
            if (sum >= D) sum = sum - D;
            add_mod_d = D_ADDR_W'(sum);
        end
    endfunction

    assign drain_start_pending = drain_valid_i &&
                                 (drain_sample_idx_i == output_issue_count_q);
    assign in_ready_o = rst_n && enable_i && !clear_i &&
                        (state_q == STATE_COLLECT) && !drain_start_pending;
    assign in_accept = in_valid_i && in_ready_o;
    assign input_token_good =
        (in_sample_offset_i == P'(collect_offset_q)) &&
        (in_last_i == (collect_offset_q == LAST_L_OFFSET)) &&
        ((collect_offset_q == '0) || (in_frame_idx_i == current_frame_idx_q));
    assign out_accept = out_valid_q && out_ready_i;
    assign output_slot_available = !out_valid_q || out_ready_i;
    assign issue_frame_output = rst_n && enable_i && !clear_i &&
                                (state_q == STATE_EMIT_READ) && output_slot_available;
    assign drain_ready_o = rst_n && enable_i && !clear_i &&
                           (state_q == STATE_DRAIN) &&
                           (drain_remaining_q != 0) && output_slot_available;
    assign drain_accept = drain_valid_i && drain_ready_o;

    assign out_valid_o = out_valid_q;
    assign out_sample_o = out_sample_q;
    assign out_sample_idx_o = out_sample_idx_q;
    assign out_frame_idx_o = out_frame_idx_q;
    assign out_last_o = out_last_q;
    assign busy_o = ((state_q != STATE_COLLECT) && (state_q != STATE_DONE)) ||
                    (collect_offset_q != '0) || sample_pipe_valid_q ||
                    product_valid_q || out_valid_q || drain_valid_i;
    assign drain_active_o = (state_q == STATE_DRAIN) ||
                            (state_q == STATE_DRAIN_CAPTURE) ||
                            ((state_q == STATE_DONE) && out_valid_q && out_finishes_drain_q);
    assign accepted_output_count_o = output_accept_count_q;

    assign add_addr_comb = add_mod_d(rd_addr_q, G + int'(add_offset_q));
    assign ola_sum_comb = $signed({ola_read_q[OLA_W-1], ola_read_q}) +
                          $signed({{(OLA_SUM_W-Z_W){z_read_q[Z_W-1]}}, z_read_q});
    assign z_write_en = rst_n && enable_i && !clear_i && product_valid_q &&
                        (state_q != STATE_SCRUB) && (state_q != STATE_FAULT);
    assign ola_read_en = issue_frame_output || drain_accept ||
                         (rst_n && enable_i && !clear_i && (state_q == STATE_ADD_READ));
    assign ola_read_addr = (state_q == STATE_ADD_READ) ? add_addr_comb : rd_addr_q;

    always_comb begin
        ola_write_en = 1'b0;
        ola_write_addr = rd_addr_q;
        ola_write_data = '0;
        if (rst_n && !clear_i) begin
            if (state_q == STATE_SCRUB) begin
                ola_write_en = 1'b1;
                ola_write_addr = scrub_addr_q;
            end else if (enable_i) begin
                case (state_q)
                    STATE_ADD_WRITE: begin
                        ola_write_en = 1'b1;
                        ola_write_addr = add_addr_comb;
                        ola_write_data = ola_sum_sat_comb;
                    end
                    STATE_EMIT_CAPTURE, STATE_DRAIN_CAPTURE: ola_write_en = 1'b1;
                    default: begin end
                endcase
            end
        end
    end

    initial begin
        for (int unsigned i = 0; i < L; i++) window_mem[i] = '0;
        if (WINDOW_FILE != "") $readmemh(WINDOW_FILE, window_mem);
    end

    always_ff @(posedge clk) begin : p_storage_ports
        if (in_accept && input_token_good)
            window_coeff_q <= window_mem[in_sample_offset_i[L_ADDR_W-1:0]];
        if (z_write_en) z_mem[product_offset_q] <= z_comb;
        if (rst_n && enable_i && !clear_i && (state_q == STATE_ADD_READ))
            z_read_q <= z_mem[add_offset_q];
        if (ola_read_en) ola_read_q <= ola_mem[ola_read_addr];
        if (ola_write_en) ola_mem[ola_write_addr] <= ola_write_data;
    end

    trecap_round_sat #(.IN_W(PRODUCT_W), .OUT_W(Z_W), .SHIFT(T_FRAC_F))
    u_synth_product_round (
        .value_i(product_q), .value_o(z_comb),
        .sat_hi_o(), .sat_lo_o(), .sat_any_o(z_sat)
    );
    trecap_round_sat #(.IN_W(OLA_SUM_W), .OUT_W(OLA_W), .SHIFT(0))
    u_ola_add_sat (
        .value_i(ola_sum_comb), .value_o(ola_sum_sat_comb),
        .sat_hi_o(), .sat_lo_o(), .sat_any_o(ola_add_sat)
    );
    trecap_round_sat #(.IN_W(OLA_W), .OUT_W(OUT_W), .SHIFT(T_FRAC_F))
    u_ola_emit_round (
        .value_i(ola_read_q), .value_o(emit_sample_comb),
        .sat_hi_o(), .sat_lo_o(), .sat_any_o(emit_sample_sat)
    );

    always_ff @(posedge clk or negedge rst_n) begin : p_synthesis_wola
        if (!rst_n) begin
            state_q <= STATE_SCRUB;
            scrub_addr_q <= '0;
            collect_offset_q <= '0;
            add_offset_q <= '0;
            emit_remaining_q <= '0;
            drain_remaining_q <= '0;
            current_frame_idx_q <= '0;
            rd_addr_q <= '0;
            output_issue_count_q <= '0;
            output_accept_count_q <= '0;
            sample_pipe_valid_q <= 1'b0;
            sample_pipe_re_q <= '0;
            sample_pipe_offset_q <= '0;
            sample_pipe_last_q <= 1'b0;
            product_valid_q <= 1'b0;
            product_q <= '0;
            product_offset_q <= '0;
            product_last_q <= 1'b0;
            out_valid_q <= 1'b0;
            out_sample_q <= '0;
            out_sample_idx_q <= '0;
            out_frame_idx_q <= '0;
            out_last_q <= 1'b0;
            out_finishes_drain_q <= 1'b0;
            drain_accept_pulse_o <= 1'b0;
            drain_done_pulse_o <= 1'b0;
            saturation_sticky_o <= 1'b0;
            protocol_error_sticky_o <= 1'b0;
        end else if (clear_i) begin
            state_q <= STATE_SCRUB;
            scrub_addr_q <= '0;
            collect_offset_q <= '0;
            add_offset_q <= '0;
            emit_remaining_q <= '0;
            drain_remaining_q <= '0;
            current_frame_idx_q <= '0;
            rd_addr_q <= '0;
            output_issue_count_q <= '0;
            output_accept_count_q <= '0;
            sample_pipe_valid_q <= 1'b0;
            product_valid_q <= 1'b0;
            out_valid_q <= 1'b0;
            out_sample_q <= '0;
            out_sample_idx_q <= '0;
            out_frame_idx_q <= '0;
            out_last_q <= 1'b0;
            out_finishes_drain_q <= 1'b0;
            drain_accept_pulse_o <= 1'b0;
            drain_done_pulse_o <= 1'b0;
            saturation_sticky_o <= 1'b0;
            protocol_error_sticky_o <= 1'b0;
        end else begin
            drain_accept_pulse_o <= 1'b0;
            drain_done_pulse_o <= 1'b0;
            sample_pipe_valid_q <= 1'b0;
            product_valid_q <= 1'b0;
            if (clear_sticky_i) begin
                saturation_sticky_o <= 1'b0;
                protocol_error_sticky_o <= 1'b0;
            end

            // Scrubbing runs even with processing disabled. No client can see
            // the partially initialized OLA ring: busy remains high throughout.
            if (state_q == STATE_SCRUB) begin
                if (scrub_addr_q == D_ADDR_W'(D - 1)) begin
                    scrub_addr_q <= '0;
                    state_q <= STATE_COLLECT;
                end else scrub_addr_q <= scrub_addr_q + 1'b1;
            end else if (!enable_i) begin
                if ((state_q != STATE_COLLECT && state_q != STATE_DONE) ||
                    (collect_offset_q != '0) || in_valid_i || drain_valid_i || out_valid_q) begin
                    protocol_error_sticky_o <= 1'b1;
                    state_q <= STATE_FAULT;
                    out_valid_q <= 1'b0;
                end
            end else if (state_q == STATE_FAULT) begin
                // A full clear starts a new epoch. A sticky-only clear cannot
                // resume a partially collected frame or partially updated OLA.
                protocol_error_sticky_o <= 1'b1;
                out_valid_q <= 1'b0;
            end else begin
                if (out_accept) begin
                    out_valid_q <= 1'b0;
                    out_last_q <= 1'b0;
                    out_finishes_drain_q <= 1'b0;
                    output_accept_count_q <= output_accept_count_q + 64'd1;
                    if (out_finishes_drain_q) drain_done_pulse_o <= 1'b1;
                end
                if (sample_pipe_valid_q) begin
                    product_valid_q <= 1'b1;
                    product_q <= $signed(sample_pipe_re_q) * $signed({1'b0, window_coeff_q});
                    product_offset_q <= sample_pipe_offset_q;
                    product_last_q <= sample_pipe_last_q;
                end
                if (z_write_en && z_sat) saturation_sticky_o <= 1'b1;

                case (state_q)
                    STATE_COLLECT: begin
                        if (drain_valid_i && (drain_sample_idx_i < output_issue_count_q))
                            protocol_error_sticky_o <= 1'b1;
                        if (drain_start_pending) begin
                            if ((drain_sample_count_i != D) || (collect_offset_q != '0) ||
                                sample_pipe_valid_q || product_valid_q || in_valid_i) begin
                                protocol_error_sticky_o <= 1'b1;
                                state_q <= STATE_FAULT;
                            end else begin
                                drain_remaining_q <= drain_sample_count_i;
                                state_q <= STATE_DRAIN;
                            end
                        end
                        if (in_accept) begin
                            // Preserve real-part synthesis even when finite-width IFFT
                            // leaves an imaginary residual; expose it as protocol status.
                            if (in_im_i != '0) protocol_error_sticky_o <= 1'b1;
                            if (!input_token_good) begin
                                protocol_error_sticky_o <= 1'b1;
                                state_q <= STATE_FAULT;
                                product_valid_q <= 1'b0;
                            end else begin
                                sample_pipe_valid_q <= 1'b1;
                                sample_pipe_re_q <= in_re_i;
                                sample_pipe_offset_q <= collect_offset_q;
                                sample_pipe_last_q <= in_last_i;
                                if (collect_offset_q == '0) current_frame_idx_q <= in_frame_idx_i;
                                if (collect_offset_q == LAST_L_OFFSET) begin
                                    collect_offset_q <= '0;
                                    state_q <= STATE_COLLECT_WAIT;
                                end else collect_offset_q <= collect_offset_q + 1'b1;
                            end
                        end
                    end
                    STATE_COLLECT_WAIT: begin
                        if (z_write_en && product_last_q) begin
                            emit_remaining_q <= H;
                            state_q <= STATE_EMIT_READ;
                        end
                    end
                    STATE_EMIT_READ: begin
                        if (issue_frame_output) state_q <= STATE_EMIT_CAPTURE;
                    end
                    STATE_EMIT_CAPTURE: begin
                        out_valid_q <= 1'b1;
                        out_sample_q <= emit_sample_comb;
                        out_sample_idx_q <= output_issue_count_q;
                        out_frame_idx_q <= current_frame_idx_q;
                        out_last_q <= (emit_remaining_q == 1);
                        out_finishes_drain_q <= 1'b0;
                        if (emit_sample_sat) saturation_sticky_o <= 1'b1;
                        rd_addr_q <= add_mod_d(rd_addr_q, 1);
                        output_issue_count_q <= output_issue_count_q + 64'd1;
                        emit_remaining_q <= emit_remaining_q - 1'b1;
                        if (emit_remaining_q == 1) begin
                            add_offset_q <= '0;
                            state_q <= STATE_ADD_READ;
                        end else state_q <= STATE_EMIT_READ;
                    end
                    STATE_ADD_READ: state_q <= STATE_ADD_WRITE;
                    STATE_ADD_WRITE: begin
                        if (ola_add_sat) saturation_sticky_o <= 1'b1;
                        if (add_offset_q == LAST_L_OFFSET) begin
                            add_offset_q <= '0;
                            if (drain_start_pending) begin
                                if (drain_sample_count_i != D) begin
                                    protocol_error_sticky_o <= 1'b1;
                                    state_q <= STATE_FAULT;
                                end else begin
                                    drain_remaining_q <= drain_sample_count_i;
                                    state_q <= STATE_DRAIN;
                                end
                            end else state_q <= STATE_COLLECT;
                        end else begin
                            add_offset_q <= add_offset_q + 1'b1;
                            state_q <= STATE_ADD_READ;
                        end
                    end
                    STATE_DRAIN: begin
                        if (drain_accept) begin
                            if ((drain_sample_idx_i != output_issue_count_q) ||
                                (drain_last_i != (drain_remaining_q == 1)))
                                protocol_error_sticky_o <= 1'b1;
                            drain_accept_pulse_o <= 1'b1;
                            state_q <= STATE_DRAIN_CAPTURE;
                        end
                    end
                    STATE_DRAIN_CAPTURE: begin
                        out_valid_q <= 1'b1;
                        out_sample_q <= emit_sample_comb;
                        out_sample_idx_q <= output_issue_count_q;
                        out_frame_idx_q <= current_frame_idx_q;
                        out_last_q <= (drain_remaining_q == 1);
                        out_finishes_drain_q <= (drain_remaining_q == 1);
                        if (emit_sample_sat) saturation_sticky_o <= 1'b1;
                        rd_addr_q <= add_mod_d(rd_addr_q, 1);
                        output_issue_count_q <= output_issue_count_q + 64'd1;
                        drain_remaining_q <= drain_remaining_q - 1'b1;
                        state_q <= (drain_remaining_q == 1) ? STATE_DONE : STATE_DRAIN;
                    end
                    STATE_DONE: begin
                        if (in_valid_i || drain_valid_i) protocol_error_sticky_o <= 1'b1;
                    end
                    default: begin
                        state_q <= STATE_FAULT;
                        protocol_error_sticky_o <= 1'b1;
                    end
                endcase
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
