// SPDX-License-Identifier: MIT
// File class: [1] hand-written RTL.
// Layer: rtl/platform/de1soc/
// Owner: T-RECAP Phase 2 implementation.
// Purpose: Own the DE1-SoC fabric clock, canonical platform reset, synchronized board inputs,
//          and exact-average-rate clock-enable generation.
// Contract: CLOCK_50 is the only active fabric clock in this profile.  KEY[0] and the HPS-to-FPGA
//           reset assert the canonical reset asynchronously; release is qualified and synchronized.
// Generated dependencies: none.

`default_nettype none

module clock_reset_ctrl #(
    parameter int unsigned     RESET_SYNC_STAGES            = 2,
    parameter int unsigned     INPUT_SYNC_STAGES            = 2,
    parameter int unsigned     BOARD_RESET_RELEASE_CYCLES   = 1_000_000,
    parameter int unsigned     KEY_DEBOUNCE_CYCLES          = 1_000_000,
    parameter longint unsigned FABRIC_CLK_HZ                 = 50_000_000,
    parameter longint unsigned SAMPLE_TICK_HZ                = 48_000,
    parameter longint unsigned STATUS_TICK_HZ                = 10,
    parameter longint unsigned METRICS_TICK_HZ               = 30,
    parameter longint unsigned HEARTBEAT_TOGGLE_HZ           = 2
) (
    input  logic       CLOCK_50,
    input  logic       h2f_reset_n_i,
    input  logic [3:0] KEY,
    input  logic [9:0] SW,

    output logic       clk_fabric_o,
    output logic       rst_n_platform_o,

    // DE1-SoC buttons are active-low.  Levels are debounced; pulses are one fabric cycle wide.
    output logic [3:0] key_level_o,
    output logic [3:0] key_press_pulse_o,
    output logic [3:0] key_release_pulse_o,

    // Switches are synchronized for observation.  Functional control still enters through the
    // CSR shadow/commit contract instead of bypassing the control plane.
    output logic [9:0] sw_sync_o,

    // These are one-cycle clock enables in clk_fabric_o, never generated clocks.
    output logic       sample_tick_o,
    output logic       status_tick_o,
    output logic       metrics_tick_o,
    output logic       heartbeat_toggle_o,
    output logic       heartbeat_o
);

    localparam int unsigned INPUT_SYNC_SAFE = (INPUT_SYNC_STAGES < 2) ? 2 : INPUT_SYNC_STAGES;
    localparam int unsigned RELEASE_SAFE =
        (BOARD_RESET_RELEASE_CYCLES < 1) ? 1 : BOARD_RESET_RELEASE_CYCLES;
    localparam int unsigned RELEASE_COUNT_W =
        (RELEASE_SAFE <= 1) ? 1 : $clog2(RELEASE_SAFE);
    localparam int unsigned DEBOUNCE_SAFE =
        (KEY_DEBOUNCE_CYCLES < 1) ? 1 : KEY_DEBOUNCE_CYCLES;
    localparam int unsigned DEBOUNCE_COUNT_W =
        (DEBOUNCE_SAFE <= 1) ? 1 : $clog2(DEBOUNCE_SAFE);
    localparam int unsigned RATE_ACCUM_W =
        (FABRIC_CLK_HZ <= 1) ? 1 : $clog2(FABRIC_CLK_HZ);

    localparam logic [RELEASE_COUNT_W-1:0] RELEASE_COUNT_LAST = RELEASE_SAFE - 1;
    localparam logic [DEBOUNCE_COUNT_W-1:0] DEBOUNCE_COUNT_LAST = DEBOUNCE_SAFE - 1;
    localparam logic [RATE_ACCUM_W:0] FABRIC_CLK_RATE = FABRIC_CLK_HZ;
    localparam logic [RATE_ACCUM_W:0] SAMPLE_TICK_RATE = SAMPLE_TICK_HZ;
    localparam logic [RATE_ACCUM_W:0] STATUS_TICK_RATE = STATUS_TICK_HZ;
    localparam logic [RATE_ACCUM_W:0] METRICS_TICK_RATE = METRICS_TICK_HZ;
    localparam logic [RATE_ACCUM_W:0] HEARTBEAT_TOGGLE_RATE = HEARTBEAT_TOGGLE_HZ;

    // Intel FPGA registers power up low, so release cannot occur until KEY[0] has been observed
    // continuously high for BOARD_RESET_RELEASE_CYCLES fabric edges.  A press asynchronously
    // clears both registers and therefore asserts the platform reset immediately.
    (* altera_attribute = "-name POWER_UP_LEVEL LOW" *)
    logic [RELEASE_COUNT_W-1:0] board_reset_release_count_q;
    (* altera_attribute = "-name POWER_UP_LEVEL LOW" *)
    logic board_reset_release_qualified_n_q;
    logic platform_async_rst_n;

    (* async_reg = "true" *)
    (* preserve = "true" *)
    logic [INPUT_SYNC_SAFE-1:0] key_sync_q [4];

    (* async_reg = "true" *)
    (* preserve = "true" *)
    logic [INPUT_SYNC_SAFE-1:0] sw_sync_q [10];

    logic [3:0] key_stable_q;
    logic [3:0] key_stable_d;
    logic [DEBOUNCE_COUNT_W-1:0] key_debounce_count_q [4];

    logic [RATE_ACCUM_W-1:0] sample_tick_accum_q;
    logic [RATE_ACCUM_W-1:0] status_tick_accum_q;
    logic [RATE_ACCUM_W-1:0] metrics_tick_accum_q;
    logic [RATE_ACCUM_W-1:0] heartbeat_toggle_accum_q;

    logic [RATE_ACCUM_W:0] sample_tick_sum;
    logic [RATE_ACCUM_W:0] status_tick_sum;
    logic [RATE_ACCUM_W:0] metrics_tick_sum;
    logic [RATE_ACCUM_W:0] heartbeat_toggle_sum;

    logic sample_tick_q;
    logic status_tick_q;
    logic metrics_tick_q;
    logic heartbeat_toggle_q;
    logic heartbeat_q;

    genvar gi;

    assign clk_fabric_o = CLOCK_50;

    always_ff @(posedge CLOCK_50 or negedge KEY[0]) begin
        if (!KEY[0]) begin
            board_reset_release_count_q <= '0;
            board_reset_release_qualified_n_q <= 1'b0;
        end else if (!board_reset_release_qualified_n_q) begin
            if (board_reset_release_count_q == RELEASE_COUNT_LAST) begin
                board_reset_release_qualified_n_q <= 1'b1;
            end else begin
                board_reset_release_count_q <= board_reset_release_count_q + 1'b1;
            end
        end
    end

    // H2F reset is intentionally global in the full-board profile.  The Platform Designer reset
    // sink driven by rst_n_platform_o does not reset the HPS reset producer, so this is not a
    // combinational or sequential reset loop.
    assign platform_async_rst_n = board_reset_release_qualified_n_q & h2f_reset_n_i;

    trecap_reset_sync #(
        .STAGES(RESET_SYNC_STAGES),
        .RELEASE_ON_NEGEDGE(1'b0)
    ) u_platform_reset_sync (
        .clk(CLOCK_50),
        .async_rst_n(platform_async_rst_n),
        .rst_n(rst_n_platform_o)
    );

    generate
        for (gi = 0; gi < 4; gi++) begin : g_key_sync_debounce
            always_ff @(posedge CLOCK_50 or negedge rst_n_platform_o) begin
                if (!rst_n_platform_o) begin
                    key_sync_q[gi] <= '1;
                    key_stable_q[gi] <= 1'b1;
                    key_stable_d[gi] <= 1'b1;
                    key_debounce_count_q[gi] <= '0;
                end else begin
                    key_sync_q[gi] <= {key_sync_q[gi][INPUT_SYNC_SAFE-2:0], KEY[gi]};
                    key_stable_d[gi] <= key_stable_q[gi];

                    if (key_sync_q[gi][INPUT_SYNC_SAFE-1] == key_stable_q[gi]) begin
                        key_debounce_count_q[gi] <= '0;
                    end else if (key_debounce_count_q[gi] == DEBOUNCE_COUNT_LAST) begin
                        key_stable_q[gi] <= key_sync_q[gi][INPUT_SYNC_SAFE-1];
                        key_debounce_count_q[gi] <= '0;
                    end else begin
                        key_debounce_count_q[gi] <= key_debounce_count_q[gi] + 1'b1;
                    end
                end
            end

            assign key_level_o[gi] = key_stable_q[gi];
            assign key_press_pulse_o[gi] = key_stable_d[gi] & ~key_stable_q[gi];
            assign key_release_pulse_o[gi] = ~key_stable_d[gi] & key_stable_q[gi];
        end

        for (gi = 0; gi < 10; gi++) begin : g_sw_sync
            always_ff @(posedge CLOCK_50 or negedge rst_n_platform_o) begin
                if (!rst_n_platform_o) begin
                    sw_sync_q[gi] <= '0;
                end else begin
                    sw_sync_q[gi] <= {sw_sync_q[gi][INPUT_SYNC_SAFE-2:0], SW[gi]};
                end
            end

            assign sw_sync_o[gi] = sw_sync_q[gi][INPUT_SYNC_SAFE-1];
        end
    endgenerate

    assign sample_tick_sum = {1'b0, sample_tick_accum_q} + SAMPLE_TICK_RATE;
    assign status_tick_sum = {1'b0, status_tick_accum_q} + STATUS_TICK_RATE;
    assign metrics_tick_sum = {1'b0, metrics_tick_accum_q} + METRICS_TICK_RATE;
    assign heartbeat_toggle_sum =
        {1'b0, heartbeat_toggle_accum_q} + HEARTBEAT_TOGGLE_RATE;

    always_ff @(posedge CLOCK_50 or negedge rst_n_platform_o) begin
        if (!rst_n_platform_o) begin
            sample_tick_accum_q <= '0;
            status_tick_accum_q <= '0;
            metrics_tick_accum_q <= '0;
            heartbeat_toggle_accum_q <= '0;
            sample_tick_q <= 1'b0;
            status_tick_q <= 1'b0;
            metrics_tick_q <= 1'b0;
            heartbeat_toggle_q <= 1'b0;
            heartbeat_q <= 1'b0;
        end else begin
            sample_tick_q <= 1'b0;
            status_tick_q <= 1'b0;
            metrics_tick_q <= 1'b0;
            heartbeat_toggle_q <= 1'b0;

            if (sample_tick_sum >= FABRIC_CLK_RATE) begin
                sample_tick_accum_q <= sample_tick_sum - FABRIC_CLK_RATE;
                sample_tick_q <= 1'b1;
            end else begin
                sample_tick_accum_q <= sample_tick_sum[RATE_ACCUM_W-1:0];
            end

            if (status_tick_sum >= FABRIC_CLK_RATE) begin
                status_tick_accum_q <= status_tick_sum - FABRIC_CLK_RATE;
                status_tick_q <= 1'b1;
            end else begin
                status_tick_accum_q <= status_tick_sum[RATE_ACCUM_W-1:0];
            end

            if (metrics_tick_sum >= FABRIC_CLK_RATE) begin
                metrics_tick_accum_q <= metrics_tick_sum - FABRIC_CLK_RATE;
                metrics_tick_q <= 1'b1;
            end else begin
                metrics_tick_accum_q <= metrics_tick_sum[RATE_ACCUM_W-1:0];
            end

            if (heartbeat_toggle_sum >= FABRIC_CLK_RATE) begin
                heartbeat_toggle_accum_q <= heartbeat_toggle_sum - FABRIC_CLK_RATE;
                heartbeat_toggle_q <= 1'b1;
                heartbeat_q <= ~heartbeat_q;
            end else begin
                heartbeat_toggle_accum_q <= heartbeat_toggle_sum[RATE_ACCUM_W-1:0];
            end
        end
    end

    assign sample_tick_o = sample_tick_q;
    assign status_tick_o = status_tick_q;
    assign metrics_tick_o = metrics_tick_q;
    assign heartbeat_toggle_o = heartbeat_toggle_q;
    assign heartbeat_o = heartbeat_q;

`ifndef SYNTHESIS
    initial begin
        if (RESET_SYNC_STAGES < 2) begin
            $error("clock_reset_ctrl: RESET_SYNC_STAGES must be at least 2");
        end
        if (INPUT_SYNC_STAGES < 2) begin
            $error("clock_reset_ctrl: INPUT_SYNC_STAGES must be at least 2");
        end
        if (BOARD_RESET_RELEASE_CYCLES < 1) begin
            $error("clock_reset_ctrl: BOARD_RESET_RELEASE_CYCLES must be at least 1");
        end
        if (KEY_DEBOUNCE_CYCLES < 1) begin
            $error("clock_reset_ctrl: KEY_DEBOUNCE_CYCLES must be at least 1");
        end
        if (FABRIC_CLK_HZ != 50_000_000) begin
            $error("clock_reset_ctrl: direct-clock profile requires FABRIC_CLK_HZ=50000000");
        end
        if ((SAMPLE_TICK_HZ < 1) || (SAMPLE_TICK_HZ >= FABRIC_CLK_HZ)) begin
            $error("clock_reset_ctrl: SAMPLE_TICK_HZ must be in [1, FABRIC_CLK_HZ)");
        end
        if ((STATUS_TICK_HZ < 1) || (STATUS_TICK_HZ >= FABRIC_CLK_HZ)) begin
            $error("clock_reset_ctrl: STATUS_TICK_HZ must be in [1, FABRIC_CLK_HZ)");
        end
        // Zero disables the metrics clock-enable for a STATUS-only profile.
        if (METRICS_TICK_HZ >= FABRIC_CLK_HZ) begin
            $error("clock_reset_ctrl: METRICS_TICK_HZ must be in [0, FABRIC_CLK_HZ)");
        end
        if ((HEARTBEAT_TOGGLE_HZ < 1) || (HEARTBEAT_TOGGLE_HZ >= FABRIC_CLK_HZ)) begin
            $error("clock_reset_ctrl: HEARTBEAT_TOGGLE_HZ must be in [1, FABRIC_CLK_HZ)");
        end
    end
`endif

endmodule : clock_reset_ctrl

`default_nettype wire
