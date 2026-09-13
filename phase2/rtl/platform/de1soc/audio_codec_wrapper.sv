// SPDX-License-Identifier: MIT
// File class: [1] hand-written RTL.
// Layer: rtl/platform/de1soc/
// Owner: T-RECAP Phase 2 implementation.
// Purpose: Operational DE1-SoC WM8731 I2S LINE-IN/LINE-OUT endpoint.
// Contract: Receive signed 16-bit stereo I2S frames, cross complete frames into clk_fabric,
//           and provide a non-stalling best-effort processed-output monitor.
// Generated dependencies: trecap_core_pkg plus common reset/CDC/FIFO primitives.

`default_nettype none

// The codec is configured as the I2S clock master. AUD_BCLK and both LRCK pins are therefore
// inputs to the FPGA; AUD_XCK is driven by the reviewed 12.288 MHz audio PLL output supplied by
// the board top. Complete stereo frames cross AUD_BCLK -> clk through an async FIFO. Processed
// monitor samples cross clk -> AUD_BCLK through a second async FIFO so WOLA output bursts cannot
// backpressure the mathematical core.
module audio_codec_wrapper
  import trecap_core_pkg::*;
#(
    parameter int unsigned AUDIO_SAMPLE_W        = 16,
    parameter int unsigned SAMPLE_RATE_HZ        = 48_000,
    parameter int unsigned AUDIO_MCLK_HZ         = 12_288_000,
    parameter int unsigned I2S_DELAY_BITS        = 1,
    parameter bit          LEFT_LRCK_LEVEL       = 1'b0,
    parameter int unsigned SYNC_STAGES           = 2,
    parameter int unsigned RX_FIFO_DEPTH         = 8,
    // The core emits reconstructed samples in frame-sized fabric-clock bursts. A deep monitor
    // FIFO absorbs that burstiness while preserving the rule that y_ready_i is always one.
    parameter int unsigned TX_FIFO_DEPTH         = 512,
    parameter int unsigned ACTIVE_TIMEOUT_CYCLES = 5_000_000
) (
    input  logic                             clk,
    input  logic                             rst_n,
    input  logic                             codec_ready_i,
    input  logic                             audio_mclk_i,
    input  logic                             enable_i,
    input  logic                             clear_sticky_i,

    input  logic                             lineout_enable_i,
    input  logic                             lineout_flush_i,
    input  logic signed [AUDIO_SAMPLE_W-1:0] lineout_left_i,
    input  logic signed [AUDIO_SAMPLE_W-1:0] lineout_right_i,
    input  logic                             lineout_valid_i,
    output logic                             lineout_ready_o,

    input  wire                              AUD_ADCDAT,
    inout  wire                              AUD_ADCLRCK,
    inout  wire                              AUD_BCLK,
    output logic                             AUD_DACDAT,
    inout  wire                              AUD_DACLRCK,
    output logic                             AUD_XCK,

    output logic                             audio_sample_valid_o,
    output logic signed [AUDIO_SAMPLE_W-1:0] audio_left_o,
    output logic signed [AUDIO_SAMPLE_W-1:0] audio_right_o,
    output logic [63:0]                      audio_sample_count_o,

    output logic                             audio_active_o,
    output logic                             frame_overrun_sticky_o,
    output logic                             lineout_overrun_sticky_o,
    output logic                             lineout_underflow_sticky_o,
    output logic                             bclk_seen_sticky_o,
    output logic                             lrck_seen_sticky_o,
    output logic [63:0]                      audio_rx_overflow_count_o,
    output logic [63:0]                      audio_tx_overflow_count_o,
    output logic [63:0]                      audio_tx_underflow_count_o
);

    localparam int unsigned SYNC_SAFE = (SYNC_STAGES < 2) ? 2 : SYNC_STAGES;
    localparam int unsigned DELAY_W = (I2S_DELAY_BITS <= 1) ? 1 : $clog2(I2S_DELAY_BITS + 1);
    localparam int unsigned BIT_COUNT_W = (AUDIO_SAMPLE_W <= 1) ? 1 : $clog2(AUDIO_SAMPLE_W + 1);
    localparam int unsigned ACTIVE_CNT_W =
        (ACTIVE_TIMEOUT_CYCLES <= 1) ? 1 : $clog2(ACTIVE_TIMEOUT_CYCLES);
    localparam int unsigned RX_FIFO_DATA_W = 64 + (2 * AUDIO_SAMPLE_W);
    localparam int unsigned TX_FIFO_DATA_W = 1 + (2 * AUDIO_SAMPLE_W);
    localparam logic [DELAY_W-1:0] I2S_REMAINING_DELAY_VALUE =
        (I2S_DELAY_BITS == 0) ? '0 : DELAY_W'(I2S_DELAY_BITS - 1);
    localparam logic [BIT_COUNT_W-1:0] AUDIO_WORD_BITS = BIT_COUNT_W'(AUDIO_SAMPLE_W);
    localparam logic [BIT_COUNT_W-1:0] AUDIO_WORD_LAST = BIT_COUNT_W'(AUDIO_SAMPLE_W - 1);
    localparam logic [ACTIVE_CNT_W-1:0] ACTIVE_TIMEOUT_LAST =
        (ACTIVE_TIMEOUT_CYCLES <= 1) ? '0 : ACTIVE_CNT_W'(ACTIVE_TIMEOUT_CYCLES - 1);

    wire aud_bclk = AUD_BCLK;
    wire aud_adclrck = AUD_ADCLRCK;
    wire aud_daclrck = AUD_DACLRCK;

    // WM8731 codec-master mode owns the serial clocks. The FPGA owns only DAC data and XCK.
    assign AUD_BCLK = 1'bz;
    assign AUD_ADCLRCK = 1'bz;
    assign AUD_DACLRCK = 1'bz;
    assign AUD_XCK = audio_mclk_i;

    logic rst_n_bclk_rx;
    logic rst_n_bclk_tx;

    trecap_reset_sync #(
        .STAGES(SYNC_SAFE),
        .RELEASE_ON_NEGEDGE(1'b0)
    ) u_bclk_rx_reset_sync (
        .clk(aud_bclk),
        .async_rst_n(rst_n),
        .rst_n(rst_n_bclk_rx)
    );

    trecap_reset_sync #(
        .STAGES(SYNC_SAFE),
        .RELEASE_ON_NEGEDGE(1'b1)
    ) u_bclk_tx_reset_sync (
        .clk(aud_bclk),
        .async_rst_n(rst_n),
        .rst_n(rst_n_bclk_tx)
    );

    function automatic logic [63:0] sat_inc64(input logic [63:0] value);
        return (&value) ? value : (value + 64'd1);
    endfunction

    // Codec readiness suppresses serial admission and forces DAC silence. The platform reset is
    // deliberately independent of PLL lock and codec status.
    (* async_reg = "true" *)
    (* preserve = "true" *)
    logic [SYNC_SAFE-1:0] bclk_codec_ready_sync_q;

    (* async_reg = "true" *)
    (* preserve = "true" *)
    logic [SYNC_SAFE-1:0] bclk_capture_enable_sync_q;

    (* async_reg = "true" *)
    (* preserve = "true" *)
    logic [SYNC_SAFE-1:0] bclk_tx_codec_ready_sync_q;

    always_ff @(posedge aud_bclk or negedge rst_n_bclk_rx) begin
        if (!rst_n_bclk_rx) begin
            bclk_codec_ready_sync_q <= '0;
            bclk_capture_enable_sync_q <= '0;
        end else begin
            bclk_codec_ready_sync_q <=
                {bclk_codec_ready_sync_q[SYNC_SAFE-2:0], codec_ready_i};
            bclk_capture_enable_sync_q <=
                {bclk_capture_enable_sync_q[SYNC_SAFE-2:0], enable_i};
        end
    end

    always_ff @(negedge aud_bclk or negedge rst_n_bclk_tx) begin
        if (!rst_n_bclk_tx) begin
            bclk_tx_codec_ready_sync_q <= '0;
        end else begin
            bclk_tx_codec_ready_sync_q <=
                {bclk_tx_codec_ready_sync_q[SYNC_SAFE-2:0], codec_ready_i};
        end
    end

    wire codec_ready_bclk_rx = bclk_codec_ready_sync_q[SYNC_SAFE-1];
    wire codec_ready_bclk_tx = bclk_tx_codec_ready_sync_q[SYNC_SAFE-1];
    wire capture_enable_bclk_rx = bclk_capture_enable_sync_q[SYNC_SAFE-1];

    // -------------------------------------------------------------------------
    // I2S ADC receiver and stereo-frame async FIFO (AUD_BCLK -> clk).
    // -------------------------------------------------------------------------
    logic                             bclk_lrck_q;
    logic                             bclk_channel_q;
    logic                             bclk_rx_armed_q;
    logic [DELAY_W-1:0]               bclk_delay_q;
    logic [BIT_COUNT_W-1:0]           bclk_bit_count_q;
    logic signed [AUDIO_SAMPLE_W-1:0] bclk_shift_q;
    logic signed [AUDIO_SAMPLE_W-1:0] bclk_left_q;
    logic                             bclk_left_seen_q;
    logic [63:0]                      bclk_frame_count_q;
    logic                             bclk_seen_source_q;
    logic                             lrck_seen_source_q;
    logic                             rx_fifo_in_valid_q;
    logic [RX_FIFO_DATA_W-1:0]        rx_fifo_in_data_q;
    logic                             rx_fifo_in_ready;
    logic                             rx_fifo_wr_overflow_pulse;
    logic                             rx_fifo_wr_overflow_sticky_unused;
    logic                             rx_overflow_event_dst;
    logic                             rx_overflow_event_src_drop;

    always_ff @(posedge aud_bclk or negedge rst_n_bclk_rx) begin
        if (!rst_n_bclk_rx) begin
            bclk_lrck_q <= LEFT_LRCK_LEVEL;
            bclk_channel_q <= LEFT_LRCK_LEVEL;
            bclk_rx_armed_q <= 1'b0;
            bclk_delay_q <= '0;
            bclk_bit_count_q <= '0;
            bclk_shift_q <= '0;
            bclk_left_q <= '0;
            bclk_left_seen_q <= 1'b0;
            bclk_frame_count_q <= 64'd0;
            bclk_seen_source_q <= 1'b0;
            lrck_seen_source_q <= 1'b0;
            rx_fifo_in_valid_q <= 1'b0;
            rx_fifo_in_data_q <= '0;
        end else begin
            bclk_seen_source_q <= 1'b1;
            rx_fifo_in_valid_q <= 1'b0;

            if (!codec_ready_bclk_rx || !capture_enable_bclk_rx) begin
                bclk_lrck_q <= aud_adclrck;
                bclk_channel_q <= LEFT_LRCK_LEVEL;
                bclk_rx_armed_q <= 1'b0;
                bclk_delay_q <= '0;
                bclk_bit_count_q <= '0;
                bclk_shift_q <= '0;
                bclk_left_q <= '0;
                bclk_left_seen_q <= 1'b0;
            end else if (!bclk_rx_armed_q) begin
                // codec_ready_i/capture enable are asynchronous to the serial frame phase.  Do
                // not interpret a mid-slot suffix plus padding as the first left word: arm only
                // on a fresh LRCK boundary.  If that first boundary starts the right channel,
                // bclk_left_seen_q remains clear and the receiver naturally waits for the next
                // complete left/right pair before publishing a frame.
                if (aud_adclrck != bclk_lrck_q) begin
                    bclk_lrck_q <= aud_adclrck;
                    bclk_channel_q <= aud_adclrck;
                    bclk_rx_armed_q <= 1'b1;
                    bclk_delay_q <= I2S_REMAINING_DELAY_VALUE;
                    bclk_bit_count_q <= '0;
                    bclk_shift_q <= '0;
                    bclk_left_seen_q <= 1'b0;
                    lrck_seen_source_q <= 1'b1;
                end
            end else if (aud_adclrck != bclk_lrck_q) begin
                bclk_lrck_q <= aud_adclrck;
                bclk_channel_q <= aud_adclrck;
                bclk_delay_q <= I2S_REMAINING_DELAY_VALUE;
                bclk_bit_count_q <= '0;
                bclk_shift_q <= '0;
                lrck_seen_source_q <= 1'b1;
            end else if (bclk_delay_q != '0) begin
                bclk_delay_q <= bclk_delay_q - DELAY_W'(1);
            end else if (bclk_bit_count_q < AUDIO_WORD_BITS) begin
                bclk_shift_q <= {bclk_shift_q[AUDIO_SAMPLE_W-2:0], AUD_ADCDAT};
                bclk_bit_count_q <= bclk_bit_count_q + BIT_COUNT_W'(1);

                if (bclk_bit_count_q == AUDIO_WORD_LAST) begin
                    if (bclk_channel_q == LEFT_LRCK_LEVEL) begin
                        bclk_left_q <= {bclk_shift_q[AUDIO_SAMPLE_W-2:0], AUD_ADCDAT};
                        bclk_left_seen_q <= 1'b1;
                    end else if (bclk_left_seen_q) begin
                        bclk_frame_count_q <= bclk_frame_count_q + 64'd1;
                        rx_fifo_in_data_q <= {
                            bclk_frame_count_q + 64'd1,
                            bclk_left_q,
                            bclk_shift_q[AUDIO_SAMPLE_W-2:0],
                            AUD_ADCDAT
                        };
                        rx_fifo_in_valid_q <= 1'b1;
                        bclk_left_seen_q <= 1'b0;
                    end
                end
            end
        end
    end

    logic                      rx_fifo_out_valid;
    logic                      rx_fifo_out_ready;
    logic [RX_FIFO_DATA_W-1:0] rx_fifo_out_data;

    trecap_async_fifo #(
        .DATA_W(RX_FIFO_DATA_W),
        .DEPTH(RX_FIFO_DEPTH),
        .SYNC_STAGES(SYNC_SAFE)
    ) u_audio_rx_fifo (
        .wr_clk(aud_bclk),
        .wr_rst_n(rst_n_bclk_rx),
        .in_valid_i(rx_fifo_in_valid_q),
        .in_ready_o(rx_fifo_in_ready),
        .in_data_i(rx_fifo_in_data_q),
        .rd_clk(clk),
        .rd_rst_n(rst_n),
        .out_valid_o(rx_fifo_out_valid),
        .out_ready_i(rx_fifo_out_ready),
        .out_data_o(rx_fifo_out_data),
        .wr_level_o(),
        .rd_level_o(),
        .wr_full_o(),
        .rd_empty_o(),
        .wr_almost_full_o(),
        .rd_almost_empty_o(),
        .wr_push_pulse_o(),
        .rd_pop_pulse_o(),
        .wr_overflow_pulse_o(rx_fifo_wr_overflow_pulse),
        .rd_underflow_pulse_o(),
        .wr_overflow_sticky_o(rx_fifo_wr_overflow_sticky_unused),
        .rd_underflow_sticky_o()
    );

    // Drain even while deselected so a new source epoch cannot replay stale physical frames.
    assign rx_fifo_out_ready = rx_fifo_out_valid;

    trecap_sync_pulse #(
        .SYNC_STAGES(SYNC_SAFE)
    ) u_rx_overflow_event_cdc (
        .src_clk(aud_bclk),
        .src_rst_n(rst_n_bclk_rx),
        .src_pulse_i(rx_fifo_wr_overflow_pulse),
        .src_ready_o(),
        .src_busy_o(),
        .src_accept_o(),
        .src_drop_o(rx_overflow_event_src_drop),
        .dst_clk(clk),
        .dst_rst_n(rst_n),
        .dst_pulse_o(rx_overflow_event_dst)
    );

    // -------------------------------------------------------------------------
    // Best-effort LINE-OUT async FIFO (clk -> AUD_BCLK).
    // -------------------------------------------------------------------------
    logic lineout_enable_d_q;
    logic codec_ready_d_q;
    // One epoch bit is sufficient only under the frozen board-control contract: every current
    // flush source is separated from the next by safe-boundary/debounce/re-initialization latency
    // longer than TX_FIFO_DEPTH/AUD_BCLK drain time, and disabled LINE-OUT continuously drains
    // stale entries. Any future unbounded or software-paced flush source requires a wider or
    // acknowledged generation before it may share this FIFO.
    logic tx_epoch_q;
    wire lineout_flush_request = lineout_flush_i ||
        (lineout_enable_d_q && !lineout_enable_i) ||
        (codec_ready_d_q && !codec_ready_i);

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            lineout_enable_d_q <= 1'b0;
            codec_ready_d_q <= 1'b0;
            tx_epoch_q <= 1'b0;
        end else begin
            lineout_enable_d_q <= lineout_enable_i;
            codec_ready_d_q <= codec_ready_i;
            if (lineout_flush_request) begin
                tx_epoch_q <= ~tx_epoch_q;
            end
        end
    end

    wire tx_fifo_in_valid = lineout_valid_i && lineout_enable_i && codec_ready_i;
    wire [TX_FIFO_DATA_W-1:0] tx_fifo_in_data = {
        tx_epoch_q,
        lineout_left_i,
        lineout_right_i
    };
    logic tx_fifo_in_ready;
    logic tx_fifo_wr_overflow_pulse;
    logic tx_fifo_wr_overflow_sticky_unused;

    assign lineout_ready_o = lineout_enable_i && codec_ready_i && tx_fifo_in_ready;

    (* async_reg = "true" *)
    (* preserve = "true" *)
    logic [SYNC_SAFE-1:0] bclk_lineout_enable_sync_q;

    (* async_reg = "true" *)
    (* preserve = "true" *)
    logic [SYNC_SAFE-1:0] bclk_tx_epoch_sync_q;

    logic lineout_flush_dst_pulse;
    logic lineout_flush_src_drop;

    trecap_sync_pulse #(
        .SYNC_STAGES(SYNC_SAFE)
    ) u_lineout_flush_cdc (
        .src_clk(clk),
        .src_rst_n(rst_n),
        .src_pulse_i(lineout_flush_request),
        .src_ready_o(),
        .src_busy_o(),
        .src_accept_o(),
        .src_drop_o(lineout_flush_src_drop),
        .dst_clk(aud_bclk),
        .dst_rst_n(rst_n_bclk_rx),
        .dst_pulse_o(lineout_flush_dst_pulse)
    );

    logic                      tx_fifo_out_valid;
    logic                      tx_fifo_out_ready;
    logic [TX_FIFO_DATA_W-1:0] tx_fifo_out_data;

    trecap_async_fifo #(
        .DATA_W(TX_FIFO_DATA_W),
        .DEPTH(TX_FIFO_DEPTH),
        .SYNC_STAGES(SYNC_SAFE)
    ) u_audio_tx_fifo (
        .wr_clk(clk),
        .wr_rst_n(rst_n),
        .in_valid_i(tx_fifo_in_valid),
        .in_ready_o(tx_fifo_in_ready),
        .in_data_i(tx_fifo_in_data),
        .rd_clk(aud_bclk),
        .rd_rst_n(rst_n_bclk_rx),
        .out_valid_o(tx_fifo_out_valid),
        .out_ready_i(tx_fifo_out_ready),
        .out_data_o(tx_fifo_out_data),
        .wr_level_o(),
        .rd_level_o(),
        .wr_full_o(),
        .rd_empty_o(),
        .wr_almost_full_o(),
        .rd_almost_empty_o(),
        .wr_push_pulse_o(),
        .rd_pop_pulse_o(),
        .wr_overflow_pulse_o(tx_fifo_wr_overflow_pulse),
        .rd_underflow_pulse_o(),
        .wr_overflow_sticky_o(tx_fifo_wr_overflow_sticky_unused),
        .rd_underflow_sticky_o()
    );

    logic                             bclk_tx_control_lrck_q;
    logic                             bclk_lineout_enabled_q;
    logic                             bclk_lineout_primed_q;
    logic signed [AUDIO_SAMPLE_W-1:0] bclk_lineout_left_q;
    logic signed [AUDIO_SAMPLE_W-1:0] bclk_lineout_right_q;
    logic                             bclk_tx_underflow_pulse_q;

    wire bclk_lineout_enable_sync = bclk_lineout_enable_sync_q[SYNC_SAFE-1];
    wire bclk_tx_epoch_sync = bclk_tx_epoch_sync_q[SYNC_SAFE-1];
    wire tx_fifo_entry_epoch = tx_fifo_out_data[TX_FIFO_DATA_W-1];
    wire tx_fifo_entry_current = tx_fifo_out_valid &&
        (tx_fifo_entry_epoch == bclk_tx_epoch_sync);
    wire tx_frame_start_left = (aud_daclrck != bclk_tx_control_lrck_q) &&
        (aud_daclrck == LEFT_LRCK_LEVEL);

    // Stale epochs drain at BCLK rate; current data pops only once per stereo frame.
    assign tx_fifo_out_ready = tx_fifo_out_valid &&
        ((!codec_ready_bclk_rx) || (!bclk_lineout_enable_sync) ||
         (tx_fifo_entry_epoch != bclk_tx_epoch_sync) || tx_frame_start_left);

    always_ff @(posedge aud_bclk or negedge rst_n_bclk_rx) begin
        if (!rst_n_bclk_rx) begin
            bclk_lineout_enable_sync_q <= '0;
            bclk_tx_epoch_sync_q <= '0;
            bclk_tx_control_lrck_q <= LEFT_LRCK_LEVEL;
            bclk_lineout_enabled_q <= 1'b0;
            bclk_lineout_primed_q <= 1'b0;
            bclk_lineout_left_q <= '0;
            bclk_lineout_right_q <= '0;
            bclk_tx_underflow_pulse_q <= 1'b0;
        end else begin
            bclk_lineout_enable_sync_q <=
                {bclk_lineout_enable_sync_q[SYNC_SAFE-2:0], lineout_enable_i};
            bclk_tx_epoch_sync_q <= {bclk_tx_epoch_sync_q[SYNC_SAFE-2:0], tx_epoch_q};
            bclk_tx_control_lrck_q <= aud_daclrck;
            bclk_tx_underflow_pulse_q <= 1'b0;

            if (!codec_ready_bclk_rx || !bclk_lineout_enable_sync ||
                lineout_flush_dst_pulse) begin
                bclk_lineout_enabled_q <= 1'b0;
                bclk_lineout_primed_q <= 1'b0;
                bclk_lineout_left_q <= '0;
                bclk_lineout_right_q <= '0;
            end else begin
                bclk_lineout_enabled_q <= 1'b1;
                if (tx_frame_start_left) begin
                    if (tx_fifo_entry_current) begin
                        bclk_lineout_left_q <=
                            tx_fifo_out_data[(2*AUDIO_SAMPLE_W)-1:AUDIO_SAMPLE_W];
                        bclk_lineout_right_q <= tx_fifo_out_data[AUDIO_SAMPLE_W-1:0];
                        bclk_lineout_primed_q <= 1'b1;
                    end else begin
                        bclk_lineout_left_q <= '0;
                        bclk_lineout_right_q <= '0;
                        if (bclk_lineout_primed_q) begin
                            bclk_tx_underflow_pulse_q <= 1'b1;
                        end
                    end
                end
            end
        end
    end

    logic tx_underflow_event_dst;
    logic tx_underflow_event_src_drop;

    trecap_sync_pulse #(
        .SYNC_STAGES(SYNC_SAFE)
    ) u_tx_underflow_event_cdc (
        .src_clk(aud_bclk),
        .src_rst_n(rst_n_bclk_rx),
        .src_pulse_i(bclk_tx_underflow_pulse_q),
        .src_ready_o(),
        .src_busy_o(),
        .src_accept_o(),
        .src_drop_o(tx_underflow_event_src_drop),
        .dst_clk(clk),
        .dst_rst_n(rst_n),
        .dst_pulse_o(tx_underflow_event_dst)
    );

    // -------------------------------------------------------------------------
    // I2S DAC serializer. Data changes on falling BCLK edges and the codec samples it on rising
    // edges. Once primed, a missing sample emits one zero stereo frame and one underflow event.
    // The FIFO frame is prefetched on the first rising edge after the left LRCK transition.  The
    // serializer therefore defers selecting either channel until the following falling edge: that
    // is the standard-I2S MSB launch edge and guarantees left/right come from one atomic FIFO word.
    // -------------------------------------------------------------------------
    logic                             bclk_tx_lrck_q;
    logic [BIT_COUNT_W-1:0]           bclk_tx_bit_count_q;
    logic signed [AUDIO_SAMPLE_W-1:0] bclk_tx_shift_q;
    logic                             bclk_dacdat_q;

    always_ff @(negedge aud_bclk or negedge rst_n_bclk_tx) begin
        if (!rst_n_bclk_tx) begin
            bclk_tx_lrck_q <= LEFT_LRCK_LEVEL;
            bclk_tx_bit_count_q <= '0;
            bclk_tx_shift_q <= '0;
            bclk_dacdat_q <= 1'b0;
        end else if (!codec_ready_bclk_tx || !bclk_lineout_enabled_q) begin
            // Track the LRCK value sampled on the intervening rising edge.  Sampling the codec's
            // LRCK directly on its launch (falling) edge would provide no setup time.
            bclk_tx_lrck_q <= bclk_tx_control_lrck_q;
            bclk_tx_bit_count_q <= '0;
            bclk_tx_shift_q <= '0;
            bclk_dacdat_q <= 1'b0;
        end else if (bclk_tx_control_lrck_q != bclk_tx_lrck_q) begin
            // LRCK was observed on the preceding rising edge, which also prefetched a new atomic
            // FIFO frame at a left boundary.  This falling edge is exactly one BCLK after the
            // LRCK transition, so it is the standard-I2S MSB launch edge.
            bclk_tx_lrck_q <= bclk_tx_control_lrck_q;
            if (bclk_lineout_primed_q) begin
                bclk_tx_bit_count_q <= BIT_COUNT_W'(1);
                if (bclk_tx_control_lrck_q == LEFT_LRCK_LEVEL) begin
                    bclk_dacdat_q <= bclk_lineout_left_q[AUDIO_SAMPLE_W-1];
                    bclk_tx_shift_q <= {
                        bclk_lineout_left_q[AUDIO_SAMPLE_W-2:0],
                        1'b0
                    };
                end else begin
                    bclk_dacdat_q <= bclk_lineout_right_q[AUDIO_SAMPLE_W-1];
                    bclk_tx_shift_q <= {
                        bclk_lineout_right_q[AUDIO_SAMPLE_W-2:0],
                        1'b0
                    };
                end
            end else begin
                bclk_tx_bit_count_q <= '0;
                bclk_tx_shift_q <= '0;
                bclk_dacdat_q <= 1'b0;
            end
        end else if (!bclk_lineout_primed_q) begin
            bclk_tx_bit_count_q <= '0;
            bclk_tx_shift_q <= '0;
            bclk_dacdat_q <= 1'b0;
        end else if (bclk_tx_bit_count_q < AUDIO_WORD_BITS) begin
            bclk_dacdat_q <= bclk_tx_shift_q[AUDIO_SAMPLE_W-1];
            bclk_tx_shift_q <= {bclk_tx_shift_q[AUDIO_SAMPLE_W-2:0], 1'b0};
            bclk_tx_bit_count_q <= bclk_tx_bit_count_q + BIT_COUNT_W'(1);
        end else begin
            bclk_dacdat_q <= 1'b0;
        end
    end

    assign AUD_DACDAT = bclk_dacdat_q;

    // -------------------------------------------------------------------------
    // Fabric-domain outputs, activity, sticky diagnostics, and saturating counters.
    // -------------------------------------------------------------------------
    (* async_reg = "true" *)
    (* preserve = "true" *)
    logic [SYNC_SAFE-1:0] clk_bclk_seen_sync_q;

    (* async_reg = "true" *)
    (* preserve = "true" *)
    logic [SYNC_SAFE-1:0] clk_lrck_seen_sync_q;

    logic [ACTIVE_CNT_W-1:0] active_timeout_cnt_q;

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            clk_bclk_seen_sync_q <= '0;
            clk_lrck_seen_sync_q <= '0;
            audio_sample_valid_o <= 1'b0;
            audio_left_o <= '0;
            audio_right_o <= '0;
            audio_sample_count_o <= 64'd0;
            audio_active_o <= 1'b0;
            active_timeout_cnt_q <= '0;
            frame_overrun_sticky_o <= 1'b0;
            lineout_overrun_sticky_o <= 1'b0;
            lineout_underflow_sticky_o <= 1'b0;
            bclk_seen_sticky_o <= 1'b0;
            lrck_seen_sticky_o <= 1'b0;
            audio_rx_overflow_count_o <= 64'd0;
            audio_tx_overflow_count_o <= 64'd0;
            audio_tx_underflow_count_o <= 64'd0;
        end else begin
            clk_bclk_seen_sync_q <= {clk_bclk_seen_sync_q[SYNC_SAFE-2:0], bclk_seen_source_q};
            clk_lrck_seen_sync_q <= {clk_lrck_seen_sync_q[SYNC_SAFE-2:0], lrck_seen_source_q};
            audio_sample_valid_o <= 1'b0;

            if (clear_sticky_i) begin
                frame_overrun_sticky_o <= 1'b0;
                lineout_overrun_sticky_o <= 1'b0;
                lineout_underflow_sticky_o <= 1'b0;
                bclk_seen_sticky_o <= 1'b0;
                lrck_seen_sticky_o <= 1'b0;
                audio_rx_overflow_count_o <= 64'd0;
                audio_tx_overflow_count_o <= 64'd0;
                audio_tx_underflow_count_o <= 64'd0;
            end

            if (clk_bclk_seen_sync_q[SYNC_SAFE-1]) begin
                bclk_seen_sticky_o <= 1'b1;
            end
            if (clk_lrck_seen_sync_q[SYNC_SAFE-1]) begin
                lrck_seen_sticky_o <= 1'b1;
            end

            if (rx_overflow_event_dst) begin
                frame_overrun_sticky_o <= 1'b1;
                audio_rx_overflow_count_o <= sat_inc64(audio_rx_overflow_count_o);
            end
            if (tx_fifo_wr_overflow_pulse) begin
                lineout_overrun_sticky_o <= 1'b1;
                audio_tx_overflow_count_o <= sat_inc64(audio_tx_overflow_count_o);
            end
            if (lineout_flush_src_drop) begin
                lineout_overrun_sticky_o <= 1'b1;
            end
            if (tx_underflow_event_dst) begin
                lineout_underflow_sticky_o <= 1'b1;
                audio_tx_underflow_count_o <= sat_inc64(audio_tx_underflow_count_o);
            end

            if (rx_fifo_out_valid) begin
                audio_sample_count_o <= rx_fifo_out_data[RX_FIFO_DATA_W-1 -: 64];
                audio_left_o <= rx_fifo_out_data[(2*AUDIO_SAMPLE_W)-1:AUDIO_SAMPLE_W];
                audio_right_o <= rx_fifo_out_data[AUDIO_SAMPLE_W-1:0];
                audio_sample_valid_o <= enable_i && codec_ready_i;
                if (enable_i && codec_ready_i) begin
                    active_timeout_cnt_q <= '0;
                    audio_active_o <= 1'b1;
                end
            end else if (!enable_i || !codec_ready_i) begin
                active_timeout_cnt_q <= '0;
                audio_active_o <= 1'b0;
            end else if (active_timeout_cnt_q == ACTIVE_TIMEOUT_LAST) begin
                audio_active_o <= 1'b0;
            end else begin
                active_timeout_cnt_q <= active_timeout_cnt_q + ACTIVE_CNT_W'(1);
            end
        end
    end

    wire unused_fifo_status = rx_fifo_in_ready ^ rx_fifo_wr_overflow_sticky_unused ^
                              tx_fifo_wr_overflow_sticky_unused;
    wire unused_cdc_drop_status = rx_overflow_event_src_drop ^
                                  tx_underflow_event_src_drop ^ unused_fifo_status;

`ifndef SYNTHESIS
    function automatic bit is_power_of_two(input int unsigned value);
        return (value >= 2) && ((value & (value - 1)) == 0);
    endfunction

    initial begin
        if (AUDIO_SAMPLE_W != 16) begin
            $fatal(1, "audio_codec_wrapper: Step-16 WM8731 profile freezes 16-bit I2S");
        end
        if (AUDIO_SAMPLE_W < T_SAMPLE_W) begin
            $fatal(1, "audio_codec_wrapper: codec width must cover the core input width");
        end
        if (SAMPLE_RATE_HZ != 48_000) begin
            $fatal(1, "audio_codec_wrapper: Step-16 profile freezes 48 ksample/s");
        end
        if (AUDIO_MCLK_HZ != (256 * SAMPLE_RATE_HZ)) begin
            $fatal(1, "audio_codec_wrapper: MCLK must equal 256*Fs");
        end
        if (I2S_DELAY_BITS != 1) begin
            $fatal(1, "audio_codec_wrapper: Step-16 serial format is standard one-bit-delay I2S");
        end
        if (!is_power_of_two(RX_FIFO_DEPTH) || !is_power_of_two(TX_FIFO_DEPTH)) begin
            $fatal(1, "audio_codec_wrapper: audio FIFO depths must be powers of two >= 2");
        end
        if (ACTIVE_TIMEOUT_CYCLES == 0) begin
            $fatal(1, "audio_codec_wrapper: ACTIVE_TIMEOUT_CYCLES must be nonzero");
        end
    end
`endif

endmodule : audio_codec_wrapper

`default_nettype wire
