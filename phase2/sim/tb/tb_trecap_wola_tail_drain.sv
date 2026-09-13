`timescale 1ns/1ps
`default_nettype none

module tb_trecap_wola_tail_drain;
    import trecap_core_pkg::*;

    localparam int unsigned ACTIVE_FRAMES    = 9;
    localparam int unsigned TAU_LAST         = ACTIVE_FRAMES * T_HOP_H;
    localparam int unsigned DRAIN_SAMPLES    = T_DELAY_D;
    localparam int unsigned NY               = TAU_LAST + DRAIN_SAMPLES;
    localparam int unsigned OUTPUT_STALL_MIN = 73;
    localparam int unsigned WATCHDOG_CYCLES  = 200_000;
    localparam int unsigned FRAC_BITS        = T_FRAC_F;

    logic clk;
    logic rst_n;
    logic enable_i;
    logic clear_i;
    logic clear_sticky_i;

    logic                         in_valid_i;
    logic                         in_ready_o;
    logic [63:0]                  in_frame_idx_i;
    logic [T_FFT_P-1:0]           in_sample_offset_i;
    logic signed [T_IFFT_W-1:0]   in_re_i;
    logic signed [T_IFFT_W-1:0]   in_im_i;
    logic                         in_last_i;

    logic                         drain_valid_i;
    logic                         drain_ready_o;
    logic [63:0]                  drain_sample_idx_i;
    logic                         drain_last_i;
    logic                         drain_source_done_q;

    logic                         out_valid_o;
    logic                         out_ready_i;
    logic signed [T_SAMPLE_W-1:0] out_sample_o;
    logic [63:0]                  out_sample_idx_o;
    logic [63:0]                  out_frame_idx_o;
    logic                         out_last_o;

    logic                         busy_o;
    logic                         drain_active_o;
    logic                         drain_accept_pulse_o;
    logic                         drain_done_pulse_o;
    logic [63:0]                  accepted_output_count_o;
    logic                         saturation_sticky_o;
    logic                         protocol_error_sticky_o;

    longint unsigned cycle_count_q;
    longint unsigned input_accept_count_q;
    longint unsigned drain_accept_count_q;
    longint unsigned drain_accept_pulse_count_q;
    longint unsigned output_accept_count_q;
    longint unsigned drain_done_count_q;
    int unsigned output_stall_count_q;
    logic output_stall_complete_q;
    logic prior_output_stall_q;
    logic signed [T_SAMPLE_W-1:0] prior_output_data_q;
    logic [63:0] prior_output_idx_q;
    logic prior_drain_stall_q;
    logic [63:0] prior_drain_idx_q;
    logic prior_drain_last_q;
    integer frame_driver_idx;
    integer coeff_init_idx;
    integer expected_frame_idx;
    integer expected_y_value;
    longint unsigned expected_contribution_start;

    trecap_synthesis_wola #(
        .WINDOW_FILE( "" )
    ) dut (
        .clk( clk ),
        .rst_n( rst_n ),
        .enable_i( enable_i ),
        .clear_i( clear_i ),
        .clear_sticky_i( clear_sticky_i ),
        .in_valid_i( in_valid_i ),
        .in_ready_o( in_ready_o ),
        .in_frame_idx_i( in_frame_idx_i ),
        .in_sample_offset_i( in_sample_offset_i ),
        .in_re_i( in_re_i ),
        .in_im_i( in_im_i ),
        .in_last_i( in_last_i ),
        .drain_valid_i( drain_valid_i ),
        .drain_ready_o( drain_ready_o ),
        .drain_sample_idx_i( drain_sample_idx_i ),
        .drain_last_i( drain_last_i ),
        .drain_sample_count_i( DRAIN_SAMPLES ),
        .out_valid_o( out_valid_o ),
        .out_ready_i( out_ready_i ),
        .out_sample_o( out_sample_o ),
        .out_sample_idx_o( out_sample_idx_o ),
        .out_frame_idx_o( out_frame_idx_o ),
        .out_last_o( out_last_o ),
        .busy_o( busy_o ),
        .drain_active_o( drain_active_o ),
        .drain_accept_pulse_o( drain_accept_pulse_o ),
        .drain_done_pulse_o( drain_done_pulse_o ),
        .accepted_output_count_o( accepted_output_count_o ),
        .saturation_sticky_o( saturation_sticky_o ),
        .protocol_error_sticky_o( protocol_error_sticky_o )
    );

    always #5 clk = ~clk;

    // A unity Q15 synthesis window turns each IFFT input (value << F) into an exact OLA
    // contribution of value. This makes pointer, overlap-add, and tail data checks nonzero and
    // independently predictable without relying on the production window artifact.
    initial begin
        #1;
        for (coeff_init_idx = 0;
             coeff_init_idx < T_FFT_L;
             coeff_init_idx = coeff_init_idx + 1) begin
            dut.u_window_rom.coeff_mem[coeff_init_idx] = 16'h8000;
        end
    end

    // Hold the first pure-drain output long enough to prove both ready/valid boundaries keep
    // their payloads stable. Release happens only after OUTPUT_STALL_MIN complete clocks.
    always_comb begin
        out_ready_i = 1'b1;
        if (out_valid_o && (out_sample_idx_o == TAU_LAST) &&
            !output_stall_complete_q) begin
            out_ready_i = 1'b0;
        end
    end

    // Present the first tail token before the final active frame reaches WOLA. The block must
    // continue accepting active IFFT frames until output_issue_count reaches tau_last.
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            drain_valid_i <= 1'b0;
            drain_sample_idx_i <= TAU_LAST;
            drain_last_i <= 1'b0;
            drain_source_done_q <= 1'b0;
        end else begin
            if (!drain_valid_i && !drain_source_done_q) begin
                drain_valid_i <= 1'b1;
                drain_sample_idx_i <= TAU_LAST;
                drain_last_i <= (DRAIN_SAMPLES == 1);
            end else if (drain_ready_o) begin
                if (drain_last_i) begin
                    drain_valid_i <= 1'b0;
                    drain_source_done_q <= 1'b1;
                end else begin
                    drain_sample_idx_i <= drain_sample_idx_i + 64'd1;
                    drain_last_i <= (drain_sample_idx_i == (NY - 64'd2));
                end
            end
        end
    end

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            cycle_count_q <= 0;
            input_accept_count_q <= 0;
            drain_accept_count_q <= 0;
            drain_accept_pulse_count_q <= 0;
            output_accept_count_q <= 0;
            drain_done_count_q <= 0;
            output_stall_count_q <= 0;
            output_stall_complete_q <= 1'b0;
            prior_output_stall_q <= 1'b0;
            prior_output_data_q <= '0;
            prior_output_idx_q <= '0;
            prior_drain_stall_q <= 1'b0;
            prior_drain_idx_q <= '0;
            prior_drain_last_q <= 1'b0;
        end else begin
            cycle_count_q <= cycle_count_q + 1;
            if (cycle_count_q >= WATCHDOG_CYCLES) begin
                $fatal(1, "WOLA tail-drain watchdog expired");
            end

            if (in_valid_i && in_ready_o) begin
                input_accept_count_q <= input_accept_count_q + 1;
            end

            if (drain_valid_i && drain_ready_o) begin
                if (drain_sample_idx_i !=
                    (TAU_LAST + drain_accept_count_q)) begin
                    $fatal(1, "drain token index mismatch: got %0d expected %0d",
                           drain_sample_idx_i, TAU_LAST + drain_accept_count_q);
                end
                drain_accept_count_q <= drain_accept_count_q + 1;
            end
            if (drain_accept_pulse_o) begin
                drain_accept_pulse_count_q <=
                    drain_accept_pulse_count_q + 1;
            end

            if (out_valid_o && out_ready_i) begin
                if (out_sample_idx_o != output_accept_count_q) begin
                    $fatal(1, "output index mismatch: got %0d expected %0d",
                           out_sample_idx_o, output_accept_count_q);
                end
                expected_y_value = 0;
                for (expected_frame_idx = 0;
                     expected_frame_idx < ACTIVE_FRAMES;
                     expected_frame_idx = expected_frame_idx + 1) begin
                    expected_contribution_start =
                        ((expected_frame_idx + 1) * T_HOP_H) + T_CUSHION_G;
                    if ((out_sample_idx_o >= expected_contribution_start) &&
                        (out_sample_idx_o <
                         (expected_contribution_start + T_FFT_L))) begin
                        expected_y_value =
                            expected_y_value + expected_frame_idx + 1;
                    end
                end
                if (out_sample_o !== expected_y_value) begin
                    $fatal(1,
                           "nonzero WOLA data mismatch at %0d: got %0d expected %0d",
                           out_sample_idx_o, out_sample_o,
                           expected_y_value);
                end
                output_accept_count_q <= output_accept_count_q + 1;
            end

            if (drain_done_pulse_o) begin
                drain_done_count_q <= drain_done_count_q + 1;
            end

            if (out_valid_o && !out_ready_i &&
                (out_sample_idx_o == TAU_LAST)) begin
                output_stall_count_q <= output_stall_count_q + 1;
                if (output_stall_count_q + 1 >= OUTPUT_STALL_MIN) begin
                    output_stall_complete_q <= 1'b1;
                end
            end

            if (prior_output_stall_q) begin
                if (!out_valid_o || (out_sample_o != prior_output_data_q) ||
                    (out_sample_idx_o != prior_output_idx_q)) begin
                    $fatal(1, "WOLA output changed while stalled");
                end
            end
            prior_output_stall_q <= out_valid_o && !out_ready_i;
            prior_output_data_q <= out_sample_o;
            prior_output_idx_q <= out_sample_idx_o;

            if (prior_drain_stall_q) begin
                if (!drain_valid_i ||
                    (drain_sample_idx_i != prior_drain_idx_q) ||
                    (drain_last_i != prior_drain_last_q)) begin
                    $fatal(1, "tail token changed while WOLA was not ready");
                end
            end
            prior_drain_stall_q <= drain_valid_i && !drain_ready_o;
            prior_drain_idx_q <= drain_sample_idx_i;
            prior_drain_last_q <= drain_last_i;
        end
    end

    task automatic send_nonzero_frame(input int unsigned frame_idx);
        int unsigned offset;
        begin
            for (offset = 0; offset < T_FFT_L; offset++) begin
                @(negedge clk);
                in_valid_i = 1'b1;
                in_frame_idx_i = frame_idx;
                in_sample_offset_i = offset[T_FFT_P-1:0];
                in_re_i = (frame_idx + 1) <<< FRAC_BITS;
                in_im_i = '0;
                in_last_i = (offset == (T_FFT_L - 1));
                do begin
                    @(posedge clk);
                end while (!in_ready_o);
                @(negedge clk);
                in_valid_i = 1'b0;
            end
        end
    endtask

    initial begin
        clk = 1'b0;
        rst_n = 1'b0;
        enable_i = 1'b1;
        clear_i = 1'b0;
        clear_sticky_i = 1'b0;
        in_valid_i = 1'b0;
        in_frame_idx_i = '0;
        in_sample_offset_i = '0;
        in_re_i = '0;
        in_im_i = '0;
        in_last_i = 1'b0;

        repeat (5) @(posedge clk);
        @(negedge clk);
        rst_n = 1'b1;

        for (frame_driver_idx = 0;
             frame_driver_idx < ACTIVE_FRAMES;
             frame_driver_idx = frame_driver_idx + 1) begin
            send_nonzero_frame(frame_driver_idx);
        end

        wait (drain_done_count_q == 1);
        repeat (4) @(posedge clk);

        if (input_accept_count_q != (ACTIVE_FRAMES * T_FFT_L)) begin
            $fatal(1, "accepted %0d IFFT beats, expected %0d",
                   input_accept_count_q, ACTIVE_FRAMES * T_FFT_L);
        end
        if (drain_accept_count_q != DRAIN_SAMPLES) begin
            $fatal(1, "accepted %0d drain tokens, expected %0d",
                   drain_accept_count_q, DRAIN_SAMPLES);
        end
        if (drain_accept_pulse_count_q != DRAIN_SAMPLES) begin
            $fatal(1, "observed %0d drain-accept pulses, expected %0d",
                   drain_accept_pulse_count_q, DRAIN_SAMPLES);
        end
        if (output_accept_count_q != NY) begin
            $fatal(1, "accepted %0d outputs, expected %0d",
                   output_accept_count_q, NY);
        end
        if (accepted_output_count_o != NY) begin
            $fatal(1, "DUT output counter is %0d, expected %0d",
                   accepted_output_count_o, NY);
        end
        if (drain_done_count_q != 1) begin
            $fatal(1, "drain-done pulse count is %0d, expected 1",
                   drain_done_count_q);
        end
        if (output_stall_count_q < OUTPUT_STALL_MIN) begin
            $fatal(1, "drain output was stalled only %0d cycles",
                   output_stall_count_q);
        end
        if (drain_active_o || drain_valid_i || out_valid_o || busy_o) begin
            $fatal(1, "WOLA did not return to completed idle state");
        end
        if (saturation_sticky_o || protocol_error_sticky_o) begin
            $fatal(1, "unexpected WOLA sticky error: saturation=%0b protocol=%0b",
                   saturation_sticky_o, protocol_error_sticky_o);
        end

        $display("WOLA_TAIL_DRAIN_PASS nonzero_frames=%0d input_beats=%0d drain=%0d outputs=%0d stall=%0d",
                 ACTIVE_FRAMES, input_accept_count_q, drain_accept_count_q,
                 output_accept_count_q, output_stall_count_q);
        $finish;
    end

endmodule

`default_nettype wire
