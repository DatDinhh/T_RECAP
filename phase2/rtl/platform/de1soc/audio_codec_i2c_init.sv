// SPDX-License-Identifier: MIT
// File class: [1] hand-written platform RTL.
// Layer: rtl/platform/de1soc/
// Owner: T-RECAP Phase 2 implementation.
// Purpose: Configure the DE1-SoC WM8731-compatible codec for 48 kS/s, 16-bit I2S master mode.
// Contract: Own only the FPGA-side codec-control I2C bus.  Audio serialization/CDC remains in
//           audio_codec_wrapper.sv and mathematical audio scaling remains in trecap_audio_adapter.

`default_nettype none

module audio_codec_i2c_init #(
    parameter longint unsigned CLK_HZ                    = 50_000_000,
    parameter longint unsigned I2C_BUS_HZ                = 100_000,
    parameter longint unsigned AUDIO_MCLK_HZ             = 12_288_000,
    parameter longint unsigned AUDIO_SAMPLE_RATE_HZ      = 48_000,
    parameter int unsigned     AUDIO_WORD_W              = 16,
    parameter logic [6:0]      CODEC_I2C_ADDRESS         = 7'h1a,
    parameter int unsigned     STARTUP_DELAY_CYCLES      = 50_000,
    parameter int unsigned     INTERWRITE_DELAY_CYCLES   = 500,
    parameter int unsigned     RETRY_DELAY_CYCLES        = 5_000,
    // Number of retries after the initial attempt for each register write.
    parameter int unsigned     MAX_RETRIES               = 3
) (
    input  logic clk,
    input  logic rst_n,

    // start_i is edge-armed: a held-high request is accepted at most once.  The bus owner shall
    // assert bus_grant_i before start and hold it until busy_o returns low.  enable_i normally
    // comes from synchronized, qualified audio-PLL lock.
    input  logic enable_i,
    input  logic bus_grant_i,
    input  logic start_i,
    input  logic clear_sticky_i,

    output logic start_ready_o,
    output logic start_accept_pulse_o,
    output logic start_reject_pulse_o,
    output logic busy_o,
    output logic config_done_o,
    output logic config_done_pulse_o,
    output logic config_error_sticky_o,
    output logic nack_seen_sticky_o,
    output wire  unsupported_config_o,

    output logic [31:0] ack_error_count_o,
    output logic [31:0] retry_count_o,
    output logic [31:0] bus_abort_count_o,
    output logic [31:0] config_write_count_o,
    output logic [3:0]  register_index_o,

    // Both pins are open drain.  External board pull-ups establish logic high.
    inout  wire FPGA_I2C_SCLK,
    inout  wire FPGA_I2C_SDAT
);

    localparam longint unsigned I2C_EDGE_RATE = 2 * I2C_BUS_HZ;
    localparam longint unsigned I2C_EDGE_RATE_SAFE =
        (I2C_EDGE_RATE == 0) ? 1 : I2C_EDGE_RATE;
    localparam longint unsigned HALF_DIV_CALC =
        CLK_HZ / I2C_EDGE_RATE_SAFE;
    localparam int unsigned HALF_DIV_SAFE = (HALF_DIV_CALC < 1) ? 1 : HALF_DIV_CALC;
    localparam int unsigned HALF_DIV_W =
        (HALF_DIV_SAFE <= 1) ? 1 : $clog2(HALF_DIV_SAFE);
    localparam logic [HALF_DIV_W-1:0] HALF_DIV_LAST = HALF_DIV_SAFE - 1;

    localparam int unsigned WAIT_MAX_AB =
        (STARTUP_DELAY_CYCLES > INTERWRITE_DELAY_CYCLES)
            ? STARTUP_DELAY_CYCLES : INTERWRITE_DELAY_CYCLES;
    localparam int unsigned WAIT_MAX =
        (WAIT_MAX_AB > RETRY_DELAY_CYCLES) ? WAIT_MAX_AB : RETRY_DELAY_CYCLES;
    localparam int unsigned WAIT_W = (WAIT_MAX <= 1) ? 1 : $clog2(WAIT_MAX + 1);

    localparam int unsigned RETRY_W =
        (MAX_RETRIES < 1) ? 1 : $clog2(MAX_RETRIES + 1);

    // Reset, inactive, analog levels/paths, serial format/rate, then ACTIVE last.
    localparam int unsigned CONFIG_WRITE_COUNT = 12;
    localparam int unsigned CONFIG_INDEX_W = $clog2(CONFIG_WRITE_COUNT);
    localparam logic [CONFIG_INDEX_W-1:0] CONFIG_INDEX_LAST = CONFIG_WRITE_COUNT - 1;

    localparam bit CONFIG_SUPPORTED =
        (CLK_HZ == 50_000_000) &&
        (AUDIO_MCLK_HZ == 12_288_000) &&
        (AUDIO_SAMPLE_RATE_HZ == 48_000) &&
        (AUDIO_WORD_W == 16) &&
        (CODEC_I2C_ADDRESS == 7'h1a) &&
        (I2C_BUS_HZ > 0) &&
        (I2C_BUS_HZ == 100_000) &&
        (I2C_EDGE_RATE <= CLK_HZ) &&
        ((CLK_HZ % I2C_EDGE_RATE_SAFE) == 0);

    typedef enum logic [3:0] {
        I2C_IDLE          = 4'd0,
        I2C_WAIT          = 4'd1,
        I2C_START_HOLD    = 4'd2,
        I2C_START_LOW     = 4'd3,
        I2C_BIT_LOW       = 4'd4,
        I2C_BIT_HIGH      = 4'd5,
        I2C_ACK_LOW       = 4'd6,
        I2C_ACK_HIGH      = 4'd7,
        I2C_STOP_LOW      = 4'd8,
        I2C_STOP_HIGH     = 4'd9,
        I2C_STOP_RELEASE  = 4'd10
    } i2c_state_e;

    i2c_state_e state_q;
    logic [HALF_DIV_W-1:0] half_div_count_q;
    logic [WAIT_W-1:0] wait_count_q;
    logic [CONFIG_INDEX_W-1:0] config_index_q;
    logic [RETRY_W-1:0] register_retry_q;
    logic [1:0] byte_index_q;
    logic [2:0] bit_index_q;
    logic [7:0] tx_byte_q;
    logic stop_due_to_nack_q;
    logic start_armed_q;

    logic scl_drive_low;
    logic sda_drive_low;

    wire half_tick;
    wire start_request;
    wire sampled_ack;
    (* async_reg = "true", preserve = "true",
       altera_attribute = "-name SYNCHRONIZER_IDENTIFICATION FORCED" *)
    logic [1:0] sda_sync_q;

    // SDA is asynchronous to the fabric. At 100kHz the ACK high phase is 250
    // fabric clocks, so two synchronization stages settle before its final edge.
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) sda_sync_q <= 2'b11;
        else sda_sync_q <= {sda_sync_q[0], FPGA_I2C_SDAT};
    end

    assign unsupported_config_o = !CONFIG_SUPPORTED;
    assign start_ready_o = CONFIG_SUPPORTED && enable_i && bus_grant_i &&
                           !busy_o && (state_q == I2C_IDLE);
    assign start_request = start_i && start_armed_q;
    assign half_tick = (half_div_count_q == HALF_DIV_LAST);
    // A released SDA resolves to 1 on hardware.  In a pull-up-free unit test it may be Z, which
    // is deliberately not accepted as ACK; the testbench must model the slave pulling SDA low.
    assign sampled_ack = (sda_sync_q[1] === 1'b0);

    assign FPGA_I2C_SCLK = scl_drive_low ? 1'b0 : 1'bz;
    assign FPGA_I2C_SDAT = sda_drive_low ? 1'b0 : 1'bz;

    function automatic logic [15:0] codec_register_word(
        input logic [CONFIG_INDEX_W-1:0] index
    );
        begin
            unique case (index)
                // WM8731-compatible control words are {register[6:0], data[8:0]}.
                0:  codec_register_word = {7'd15, 9'h000}; // Software reset.
                1:  codec_register_word = {7'd9,  9'h000}; // Inactive while configuring.
                2:  codec_register_word = {7'd0,  9'h017}; // Left line-in, 0 dB, unmuted.
                3:  codec_register_word = {7'd1,  9'h017}; // Right line-in, 0 dB, unmuted.
                4:  codec_register_word = {7'd2,  9'h079}; // Left headphone out, 0 dB.
                5:  codec_register_word = {7'd3,  9'h079}; // Right headphone out, 0 dB.
                6:  codec_register_word = {7'd4,  9'h012}; // DAC select, LINE-IN, mic muted.
                7:  codec_register_word = {7'd5,  9'h000}; // Digital path, no soft mute.
                8:  codec_register_word = {7'd6,  9'h002}; // Power required blocks; microphone off.
                9:  codec_register_word = {7'd7,  9'h042}; // Master, 16-bit, I2S format.
                10: codec_register_word = {7'd8,  9'h000}; // Normal 48 kHz at 12.288 MHz.
                11: codec_register_word = {7'd9,  9'h001}; // Activate only after all writes.
                default: codec_register_word = {7'd15, 9'h000};
            endcase
        end
    endfunction : codec_register_word

    function automatic logic [7:0] transaction_byte(
        input logic [CONFIG_INDEX_W-1:0] index,
        input logic [1:0] byte_index
    );
        logic [15:0] register_word;
        begin
            register_word = codec_register_word(index);
            unique case (byte_index)
                2'd0: transaction_byte = {CODEC_I2C_ADDRESS, 1'b0};
                2'd1: transaction_byte = register_word[15:8];
                2'd2: transaction_byte = register_word[7:0];
                default: transaction_byte = 8'h00;
            endcase
        end
    endfunction : transaction_byte

    function automatic logic [31:0] saturating_increment(input logic [31:0] value);
        begin
            saturating_increment = (&value) ? value : (value + 32'd1);
        end
    endfunction : saturating_increment

    // Decode I2C waveforms from registered protocol state.  Gating with grant and busy makes a
    // reset, abort, or ownership loss release both wires without ever actively driving high.
    always_comb begin
        scl_drive_low = 1'b0;
        sda_drive_low = 1'b0;

        if (busy_o && bus_grant_i) begin
            unique case (state_q)
                I2C_START_LOW: begin
                    sda_drive_low = 1'b1;
                end
                I2C_BIT_LOW: begin
                    scl_drive_low = 1'b1;
                    sda_drive_low = !tx_byte_q[bit_index_q];
                end
                I2C_BIT_HIGH: begin
                    sda_drive_low = !tx_byte_q[bit_index_q];
                end
                I2C_ACK_LOW: begin
                    scl_drive_low = 1'b1;
                end
                I2C_STOP_LOW: begin
                    scl_drive_low = 1'b1;
                    sda_drive_low = 1'b1;
                end
                I2C_STOP_HIGH: begin
                    sda_drive_low = 1'b1;
                end
                default: begin
                    scl_drive_low = 1'b0;
                    sda_drive_low = 1'b0;
                end
            endcase
        end
    end

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state_q <= I2C_IDLE;
            half_div_count_q <= '0;
            wait_count_q <= '0;
            config_index_q <= '0;
            register_retry_q <= '0;
            byte_index_q <= '0;
            bit_index_q <= 3'd7;
            tx_byte_q <= 8'h00;
            stop_due_to_nack_q <= 1'b0;
            start_armed_q <= 1'b1;
            busy_o <= 1'b0;
            config_done_o <= 1'b0;
            config_done_pulse_o <= 1'b0;
            config_error_sticky_o <= 1'b0;
            nack_seen_sticky_o <= 1'b0;
            start_accept_pulse_o <= 1'b0;
            start_reject_pulse_o <= 1'b0;
            ack_error_count_o <= 32'd0;
            retry_count_o <= 32'd0;
            bus_abort_count_o <= 32'd0;
            config_write_count_o <= 32'd0;
            register_index_o <= 4'd0;
        end else begin
            config_done_pulse_o <= 1'b0;
            start_accept_pulse_o <= 1'b0;
            start_reject_pulse_o <= 1'b0;

            if (!start_i) begin
                start_armed_q <= 1'b1;
            end

            // Loss of any ownership/prerequisite invalidates a previously completed codec setup,
            // including while the initializer is idle.  This prevents a stale config_done_o from
            // briefly reopening capture when the FPGA I2C grant later returns and re-init starts.
            if (!enable_i || !bus_grant_i || !CONFIG_SUPPORTED) begin
                config_done_o <= 1'b0;
            end

            if (clear_sticky_i) begin
                config_done_o <= 1'b0;
                config_error_sticky_o <= 1'b0;
                nack_seen_sticky_o <= 1'b0;
                ack_error_count_o <= 32'd0;
                retry_count_o <= 32'd0;
                bus_abort_count_o <= 32'd0;
            end

            if (start_request) begin
                start_armed_q <= 1'b0;
                if (start_ready_o) begin
                    start_accept_pulse_o <= 1'b1;
                    busy_o <= 1'b1;
                    config_done_o <= 1'b0;
                    config_index_q <= '0;
                    register_index_o <= 4'd0;
                    register_retry_q <= '0;
                    byte_index_q <= 2'd0;
                    bit_index_q <= 3'd7;
                    tx_byte_q <= transaction_byte('0, 2'd0);
                    stop_due_to_nack_q <= 1'b0;
                    wait_count_q <= WAIT_W'(STARTUP_DELAY_CYCLES);
                    half_div_count_q <= '0;
                    state_q <= I2C_WAIT;
                end else begin
                    start_reject_pulse_o <= 1'b1;
                end
            end else if (busy_o && (!enable_i || !bus_grant_i || !CONFIG_SUPPORTED)) begin
                // Releasing a grant or losing the qualified PLL while a write is active aborts
                // the sequence and releases the physical wires.  A fresh start edge is required.
                busy_o <= 1'b0;
                config_done_o <= 1'b0;
                config_error_sticky_o <= 1'b1;
                bus_abort_count_o <= saturating_increment(bus_abort_count_o);
                half_div_count_q <= '0;
                state_q <= I2C_IDLE;
            end else if (busy_o) begin
                unique case (state_q)
                    I2C_WAIT: begin
                        half_div_count_q <= '0;
                        if (wait_count_q == '0) begin
                            byte_index_q <= 2'd0;
                            bit_index_q <= 3'd7;
                            tx_byte_q <= transaction_byte(config_index_q, 2'd0);
                            stop_due_to_nack_q <= 1'b0;
                            state_q <= I2C_START_HOLD;
                        end else begin
                            wait_count_q <= wait_count_q - 1'b1;
                        end
                    end

                    I2C_START_HOLD: begin
                        if (half_tick) begin
                            half_div_count_q <= '0;
                            state_q <= I2C_START_LOW;
                        end else begin
                            half_div_count_q <= half_div_count_q + 1'b1;
                        end
                    end

                    I2C_START_LOW: begin
                        if (half_tick) begin
                            half_div_count_q <= '0;
                            state_q <= I2C_BIT_LOW;
                        end else begin
                            half_div_count_q <= half_div_count_q + 1'b1;
                        end
                    end

                    I2C_BIT_LOW: begin
                        if (half_tick) begin
                            half_div_count_q <= '0;
                            state_q <= I2C_BIT_HIGH;
                        end else begin
                            half_div_count_q <= half_div_count_q + 1'b1;
                        end
                    end

                    I2C_BIT_HIGH: begin
                        if (half_tick) begin
                            half_div_count_q <= '0;
                            if (bit_index_q == 3'd0) begin
                                state_q <= I2C_ACK_LOW;
                            end else begin
                                bit_index_q <= bit_index_q - 1'b1;
                                state_q <= I2C_BIT_LOW;
                            end
                        end else begin
                            half_div_count_q <= half_div_count_q + 1'b1;
                        end
                    end

                    I2C_ACK_LOW: begin
                        if (half_tick) begin
                            half_div_count_q <= '0;
                            state_q <= I2C_ACK_HIGH;
                        end else begin
                            half_div_count_q <= half_div_count_q + 1'b1;
                        end
                    end

                    I2C_ACK_HIGH: begin
                        if (half_tick) begin
                            half_div_count_q <= '0;
                            if (!sampled_ack) begin
                                nack_seen_sticky_o <= 1'b1;
                                ack_error_count_o <= saturating_increment(ack_error_count_o);
                                stop_due_to_nack_q <= 1'b1;
                                state_q <= I2C_STOP_LOW;
                            end else if (byte_index_q == 2'd2) begin
                                stop_due_to_nack_q <= 1'b0;
                                state_q <= I2C_STOP_LOW;
                            end else begin
                                byte_index_q <= byte_index_q + 1'b1;
                                bit_index_q <= 3'd7;
                                tx_byte_q <= transaction_byte(
                                    config_index_q,
                                    byte_index_q + 1'b1
                                );
                                state_q <= I2C_BIT_LOW;
                            end
                        end else begin
                            half_div_count_q <= half_div_count_q + 1'b1;
                        end
                    end

                    I2C_STOP_LOW: begin
                        if (half_tick) begin
                            half_div_count_q <= '0;
                            state_q <= I2C_STOP_HIGH;
                        end else begin
                            half_div_count_q <= half_div_count_q + 1'b1;
                        end
                    end

                    I2C_STOP_HIGH: begin
                        if (half_tick) begin
                            half_div_count_q <= '0;
                            state_q <= I2C_STOP_RELEASE;
                        end else begin
                            half_div_count_q <= half_div_count_q + 1'b1;
                        end
                    end

                    I2C_STOP_RELEASE: begin
                        if (half_tick) begin
                            half_div_count_q <= '0;
                            if (stop_due_to_nack_q) begin
                                if (register_retry_q < RETRY_W'(MAX_RETRIES)) begin
                                    register_retry_q <= register_retry_q + 1'b1;
                                    retry_count_o <= saturating_increment(retry_count_o);
                                    wait_count_q <= WAIT_W'(RETRY_DELAY_CYCLES);
                                    state_q <= I2C_WAIT;
                                end else begin
                                    busy_o <= 1'b0;
                                    config_done_o <= 1'b0;
                                    config_error_sticky_o <= 1'b1;
                                    state_q <= I2C_IDLE;
                                end
                            end else begin
                                config_write_count_o <=
                                    saturating_increment(config_write_count_o);
                                register_retry_q <= '0;
                                if (config_index_q == CONFIG_INDEX_LAST) begin
                                    busy_o <= 1'b0;
                                    config_done_o <= 1'b1;
                                    config_done_pulse_o <= 1'b1;
                                    state_q <= I2C_IDLE;
                                end else begin
                                    config_index_q <= config_index_q + 1'b1;
                                    register_index_o <= register_index_o + 1'b1;
                                    wait_count_q <= WAIT_W'(INTERWRITE_DELAY_CYCLES);
                                    state_q <= I2C_WAIT;
                                end
                            end
                        end else begin
                            half_div_count_q <= half_div_count_q + 1'b1;
                        end
                    end

                    default: begin
                        busy_o <= 1'b0;
                        config_done_o <= 1'b0;
                        config_error_sticky_o <= 1'b1;
                        half_div_count_q <= '0;
                        state_q <= I2C_IDLE;
                    end
                endcase
            end else begin
                state_q <= I2C_IDLE;
                half_div_count_q <= '0;
            end
        end
    end

`ifndef SYNTHESIS
    initial begin
        if (!CONFIG_SUPPORTED) begin
            $warning(
                "audio_codec_i2c_init: unsupported profile CLK=%0d I2C=%0d MCLK=%0d Fs=%0d word=%0d addr=0x%0h; bus remains released",
                CLK_HZ,
                I2C_BUS_HZ,
                AUDIO_MCLK_HZ,
                AUDIO_SAMPLE_RATE_HZ,
                AUDIO_WORD_W,
                CODEC_I2C_ADDRESS
            );
        end
        if (STARTUP_DELAY_CYCLES == 0) begin
            $warning("audio_codec_i2c_init: STARTUP_DELAY_CYCLES=0 removes codec settle time");
        end
    end
`endif

endmodule : audio_codec_i2c_init

`default_nettype wire
