// SPDX-License-Identifier: MIT
// File class: [1] hand-written RTL boundary around a Quartus megafunction.
// Layer: rtl/platform/de1soc/
// Owner: T-RECAP Phase 2 implementation.
// Purpose: Generate the DE1-SoC audio-codec 12.288 MHz master clock from CLOCK_50.
// Contract: The production branch uses the Intel/Altera fractional PLL primitive.  The
//           non-synthesis branch is an average-rate test model only and is not timing evidence.

`default_nettype none

module audio_pll_wrapper #(
    parameter longint unsigned REF_CLK_HZ             = 50_000_000,
    parameter longint unsigned AUDIO_MCLK_HZ          = 12_288_000,
    parameter int unsigned     LOCK_STABLE_CYCLES     = 4,
    parameter int unsigned     SIM_LOCK_DELAY_CYCLES  = 8
) (
    input  logic ref_clk_i,
    input  logic rst_n_i,

    output wire  audio_mclk_o,
    output logic locked_o,
    output wire  config_supported_o
);

    // Step 16 intentionally freezes one reviewed board clock profile.  Unsupported parameter
    // combinations remain quiescent rather than silently producing an approximate audio clock.
    localparam bit CONFIG_SUPPORTED =
        (REF_CLK_HZ == 50_000_000) && (AUDIO_MCLK_HZ == 12_288_000);
    localparam int unsigned LOCK_STABLE_SAFE =
        (LOCK_STABLE_CYCLES < 1) ? 1 : LOCK_STABLE_CYCLES;
    localparam int unsigned LOCK_COUNT_W =
        (LOCK_STABLE_SAFE <= 1) ? 1 : $clog2(LOCK_STABLE_SAFE);
    localparam logic [LOCK_COUNT_W-1:0] LOCK_COUNT_LAST = LOCK_STABLE_SAFE - 1;

    wire pll_mclk_w;
    wire pll_locked_raw_w;
    (* async_reg = "true" *)
    (* preserve = "true" *)
    (* altera_attribute = "-name SYNCHRONIZER_IDENTIFICATION FORCED" *)
    logic [1:0] pll_locked_sync_q;
    logic [LOCK_COUNT_W-1:0] lock_stable_count_q;

    assign config_supported_o = CONFIG_SUPPORTED;
    assign audio_mclk_o = pll_mclk_w;

    generate
        if (CONFIG_SUPPORTED) begin : g_supported_clock_profile
`ifdef SYNTHESIS
            // This is the same primitive emitted by the Quartus PLL IP generator for Cyclone V.
            // The fractional VCO is required: 12.288/50 = 0.24576 cannot be represented by a
            // reviewed integer-divider clock.  Quartus owns device-specific compensation, VCO,
            // and generated-clock constraints for this primitive.
            wire [0:0] pll_outclk;

            altera_pll #(
                .fractional_vco_multiplier ("true"),
                .reference_clock_frequency ("50.0 MHz"),
                .operation_mode             ("direct"),
                .number_of_clocks           (1),
                .output_clock_frequency0    ("12.288000 MHz"),
                .phase_shift0               ("0 ps"),
                .duty_cycle0                (50),
                .pll_type                   ("General"),
                .pll_subtype                ("General")
            ) u_audio_altera_pll (
                .rst      (!rst_n_i),
                .outclk   (pll_outclk),
                .locked   (pll_locked_raw_w),
                .fboutclk (),
                .fbclk    (1'b0),
                .refclk   (ref_clk_i)
            );

            assign pll_mclk_w = pll_outclk[0];
`else
            // Portable simulation model.  A phase accumulator toggles at an exact long-term
            // average of 2*AUDIO_MCLK_HZ edges/s.  Edges are quantized to ref_clk_i and therefore
            // have one-reference-cycle jitter; this model may test reset/config sequencing but
            // must never be used for codec timing, STA, or hardware-signoff claims.
            localparam int unsigned SIM_LOCK_DELAY_SAFE =
                (SIM_LOCK_DELAY_CYCLES < 1) ? 1 : SIM_LOCK_DELAY_CYCLES;
            localparam int unsigned SIM_LOCK_COUNT_W =
                (SIM_LOCK_DELAY_SAFE <= 1) ? 1 : $clog2(SIM_LOCK_DELAY_SAFE);
            localparam logic [SIM_LOCK_COUNT_W-1:0] SIM_LOCK_COUNT_LAST =
                SIM_LOCK_DELAY_SAFE - 1;
            localparam logic [63:0] SIM_EDGE_RATE = 2 * AUDIO_MCLK_HZ;
            localparam logic [63:0] SIM_REF_RATE  = REF_CLK_HZ;

            logic [63:0] sim_phase_accum_q;
            logic [63:0] sim_phase_sum;
            logic [SIM_LOCK_COUNT_W-1:0] sim_lock_count_q;
            logic sim_mclk_q;
            logic sim_locked_q;

            assign sim_phase_sum = sim_phase_accum_q + SIM_EDGE_RATE;
            assign pll_mclk_w = sim_mclk_q;
            assign pll_locked_raw_w = sim_locked_q;

            always_ff @(posedge ref_clk_i or negedge rst_n_i) begin
                if (!rst_n_i) begin
                    sim_phase_accum_q <= 64'd0;
                    sim_lock_count_q <= '0;
                    sim_mclk_q <= 1'b0;
                    sim_locked_q <= 1'b0;
                end else begin
                    if (sim_phase_sum >= SIM_REF_RATE) begin
                        sim_phase_accum_q <= sim_phase_sum - SIM_REF_RATE;
                        sim_mclk_q <= ~sim_mclk_q;
                    end else begin
                        sim_phase_accum_q <= sim_phase_sum;
                    end

                    if (!sim_locked_q) begin
                        if (sim_lock_count_q == SIM_LOCK_COUNT_LAST) begin
                            sim_locked_q <= 1'b1;
                        end else begin
                            sim_lock_count_q <= sim_lock_count_q + 1'b1;
                        end
                    end
                end
            end
`endif
        end else begin : g_unsupported_clock_profile
            assign pll_mclk_w = 1'b0;
            assign pll_locked_raw_w = 1'b0;
        end
    endgenerate

    // The PLL lock indication is asynchronous status. Synchronize it before it fans into the
    // stable-lock qualifier; the qualifier is a persistence filter, not a metastability filter.
    always_ff @(posedge ref_clk_i or negedge rst_n_i) begin
        if (!rst_n_i) begin
            pll_locked_sync_q <= '0;
        end else begin
            pll_locked_sync_q <= {pll_locked_sync_q[0], pll_locked_raw_w};
        end
    end

    // A transient synchronized lock indication must not release codec configuration. Qualify it
    // for a small number of reference-clock cycles. Consumers still synchronize locked_o if they
    // use a different clock domain.
    always_ff @(posedge ref_clk_i or negedge rst_n_i) begin
        if (!rst_n_i) begin
            lock_stable_count_q <= '0;
            locked_o <= 1'b0;
        end else if (!pll_locked_sync_q[1] || !CONFIG_SUPPORTED) begin
            lock_stable_count_q <= '0;
            locked_o <= 1'b0;
        end else if (!locked_o) begin
            if (lock_stable_count_q == LOCK_COUNT_LAST) begin
                locked_o <= 1'b1;
            end else begin
                lock_stable_count_q <= lock_stable_count_q + 1'b1;
            end
        end
    end

`ifndef SYNTHESIS
    initial begin
        if (!CONFIG_SUPPORTED) begin
            $warning(
                "audio_pll_wrapper: unsupported REF_CLK_HZ=%0d AUDIO_MCLK_HZ=%0d; outputs remain fail-closed",
                REF_CLK_HZ,
                AUDIO_MCLK_HZ
            );
        end
        if ((2 * AUDIO_MCLK_HZ) >= REF_CLK_HZ) begin
            $warning(
                "audio_pll_wrapper: portable model requires 2*AUDIO_MCLK_HZ < REF_CLK_HZ"
            );
        end
    end
`endif

endmodule : audio_pll_wrapper

`default_nettype wire
