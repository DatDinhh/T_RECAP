`timescale 1ns/1ps
`default_nettype none

// Arizona State University 
// Capstone Senior Project
// Sigma Force
// Dat Dinh, Dat Huynh, Paul Applebee, Kyung Jae Son
// t_recap_phase2_top.sv
//
// DE1-SoC top-level wrapper for T-RECAP Phase 2 (STFT/FFT + suppression + OLA).
//
// This file intentionally follows the Phase-1 demo style (self-contained
// utilities, clean control/visibility) while targeting the DE1-SoC board.
//
// Industry grade top-level traits provided here:
//   - Deterministic sample tick (or CODEC-driven tick)
//   - Never-stalling sample stream into the Phase-2 core
//   - Clean reset + edge-detected metric clear
//   - Live threshold control + bypass mode
//   - Overrun visibility (missed hop deadline)
//   - Low-rate latched debug output to LEDs + HEX
//
// Dependencies:
//   - t_recap_phase2_core.sv
//       Implements Algorithm 1 + Algorithm 2 
//       (xring + OLA, windowing, FFT/IFFT, mask + symmetry, metrics, overrun)
//
// Optional dependency USE_AUDIO_CODEC != 0:
//   - codec_interface.sv (or equivalent DE1-SoC audio driver)
//       Provides 48kHz-ish advance pulse + ADC/DAC 24-bit samples.
//
// Controls:
//   KEY[0] : reset (active-low pushbutton => rst_n = KEY[0])
//   KEY[1] : clear metrics (press => falling edge)
//   KEY[2] : run enable (hold pressed to pause)
//   SW[7:0]: threshold magnitude T (0..255)
//   SW[9:8]: mode / HEX display select
//            00: BYPASS (T forced 0). HEX shows total_frames
//            01: SUPPRESS. HEX shows suppressed_unique_bins (LSBs)
//            10: SUPPRESS. HEX shows total_unique_bins (LSBs)
//            11: SUPPRESS. HEX shows last yout sample (sign-extended)
//
// LEDs:
//   LEDR[7:0] : threshold used (T)
//   LEDR[8]   : frame_overrun (latched at dbg_tick)
//   LEDR[9]   : alive blink (toggles at dbg_tick)
//
// HEX0..HEX5 show a 24-bit debug word (6 hex digits)


module t_recap_phase2_top #(
  parameter int N               = 12,          // signed sample width
  parameter int L               = 256,         // FFT length (2^P)
  parameter int H               = 128,         // hop size
  parameter int F               = 15,          // window/twiddle frac bits (core-defined)
  parameter int CLK_HZ          = 50_000_000,  // DE1-SoC system clock
  parameter int FS_HZ           = 48_000,      // internal demo sample rate
  parameter int DBG_HZ          = 10,          // LED/HEX refresh
  parameter bit USE_AUDIO_CODEC = 1'b0         // 0: synthetic source/sink
)(
  input  logic       CLOCK_50,
  input  logic [3:0] KEY,
  input  logic [9:0] SW,

  output wire  [9:0] LEDR,
  output wire  [6:0] HEX0,
  output wire  [6:0] HEX1,
  output wire  [6:0] HEX2,
  output wire  [6:0] HEX3,
  output wire  [6:0] HEX4,
  output wire  [6:0] HEX5,

  // Optional DE1-SoC Audio CODEC pins (kept for pin compatibility)
  output wire        FPGA_I2C_SCLK,
  inout  wire        FPGA_I2C_SDAT,
  output wire        AUD_XCK,
  inout  wire        AUD_DACLRCK,
  inout  wire        AUD_ADCLRCK,
  inout  wire        AUD_BCLK,
  input  logic       AUD_ADCDAT,
  output wire        AUD_DACDAT
);


  // Reset + controls

  logic rst_n;
  assign rst_n = KEY[0];

  // Edge detect KEY[1] press (active-low)
  logic key1_d, key1_dd;
  always_ff @(posedge CLOCK_50 or negedge rst_n) begin
    if (!rst_n) begin
      key1_d  <= 1'b1;
      key1_dd <= 1'b1;
    end else begin
      key1_d  <= KEY[1];
      key1_dd <= key1_d;
    end
  end
  wire clr_metrics_pulse = (key1_dd == 1'b1) && (key1_d == 1'b0);

  // Run enable: KEY[2] high (not pressed) => enabled
  wire run_en = KEY[2];

  // Mode select + threshold
  wire [1:0] mode_sel = SW[9:8];
  wire       force_bypass = (mode_sel == 2'b00);

  wire [7:0] thresh8_manual = SW[7:0];
  wire [7:0] thresh8_used   = force_bypass ? 8'h00 : thresh8_manual;


  // Tick generators (internal demo clocking)
  
  localparam int SAMPLE_DIV_RAW = (FS_HZ <= 0) ? 1 : (CLK_HZ / FS_HZ);
  localparam int SAMPLE_DIV     = (SAMPLE_DIV_RAW < 1) ? 1 : SAMPLE_DIV_RAW;

  localparam int DBG_DIV_RAW    = (DBG_HZ <= 0) ? CLK_HZ : (CLK_HZ / DBG_HZ);
  localparam int DBG_DIV        = (DBG_DIV_RAW < 1) ? 1 : DBG_DIV_RAW;

  logic sample_en;
  tick_pulse_gen #(.DIV(SAMPLE_DIV)) u_sample_tick (
    .clk    (CLOCK_50),
    .rst_n  (rst_n),
    .enable (run_en),
    .tick   (sample_en)
  );

  logic dbg_tick;
  tick_pulse_gen #(.DIV(DBG_DIV)) u_dbg_tick (
    .clk    (CLOCK_50),
    .rst_n  (rst_n),
    .enable (1'b1),
    .tick   (dbg_tick)
  );


  // Input source: synthetic (always present) + optional audio codec

  logic signed [N-1:0] xin;

  // Synthetic source: LFSR -> centered signed -> optional smoothing
  localparam int LFSR_W = 16;
  logic [LFSR_W-1:0] lfsr_rnd;

  lfsr_noise #(.W(LFSR_W)) u_lfsr (
    .clk       (CLOCK_50),
    .rst_n     (rst_n),
    .en        (sample_en),
    .seed_load (1'b0),
    .seed      (16'hACE1),
    .rnd       (lfsr_rnd)
  );

  logic [N-1:0]        u_u;
  logic signed [N:0]   u_center_wide;
  logic signed [N-1:0] u_noise;
  assign u_u = lfsr_rnd[N-1:0];
  assign u_center_wide = $signed({1'b0, u_u}) - $signed(1 <<< (N-1));
  assign u_noise       = u_center_wide[N-1:0];

  logic signed [N-1:0] x_synth;
  noise_shaper #(.N(N), .SHIFT(3), .STATE_W(N+12)) u_shaper (
    .clk      (CLOCK_50),
    .rst_n    (rst_n),
    .en       (sample_en),
    .in_noise (u_noise),
    .x_out    (x_synth)
  );

  // Audio interface signals (only meaningful if USE_AUDIO_CODEC=1) ---
  logic        aud_advance;
  logic signed [23:0] aud_adc_l, aud_adc_r;
  logic signed [23:0] aud_dac_l, aud_dac_r;

  // Tie-offs for audio outputs when not used
  wire fpga_i2c_sclk_tie = 1'b1; // I2C idle high
  wire aud_xck_tie       = 1'b0;
  wire aud_dacdat_tie    = 1'b0;

  generate
    if (USE_AUDIO_CODEC) begin : g_audio
      // IMPORTANT:
      // Provide/bring in a DE1-SoC codec driver named `codec_interface`.
      // It must expose the ports used below.
      codec_interface u_codec (
        .CLOCK_50      (CLOCK_50),
        .reset         (~rst_n),
        .dac_left      (aud_dac_l),
        .dac_right     (aud_dac_r),
        .adc_left      (aud_adc_l),
        .adc_right     (aud_adc_r),
        .advance       (aud_advance),
        .FPGA_I2C_SCLK (FPGA_I2C_SCLK),
        .FPGA_I2C_SDAT (FPGA_I2C_SDAT),
        .AUD_XCK       (AUD_XCK),
        .AUD_DACLRCK   (AUD_DACLRCK),
        .AUD_ADCLRCK   (AUD_ADCLRCK),
        .AUD_BCLK      (AUD_BCLK),
        .AUD_ADCDAT    (AUD_ADCDAT),
        .AUD_DACDAT    (AUD_DACDAT)
      );

      // Use left channel; truncate 24 -> N (top bits preserve sign)
      always_comb begin
        xin = aud_adc_l[23 -: N];
      end

    end else begin : g_no_audio
      // Drive pins to safe idle states
      assign FPGA_I2C_SCLK = fpga_i2c_sclk_tie;
      assign AUD_XCK       = aud_xck_tie;
      assign AUD_DACDAT    = aud_dacdat_tie;

      // Leave inouts undriven (board pull-ups/codec handle idle)
      // FPGA_I2C_SDAT, AUD_*LRCK, AUD_BCLK are inout.

      always_comb begin
        xin = x_synth;
      end

      // Internal audio signals held at 0
      always_comb begin
        aud_advance = 1'b0;
        aud_adc_l   = '0;
        aud_adc_r   = '0;
        aud_dac_l   = '0;
        aud_dac_r   = '0;
      end
    end
  endgenerate

  // Choose the sample tick for the core
  wire core_sample_en = (USE_AUDIO_CODEC) ? aud_advance : sample_en;


  // Phase-2 core

  logic signed [N-1:0] yout;
  logic                y_valid;

  logic core_busy;
  logic frame_overrun;

  logic [31:0] total_frames;
  logic [31:0] suppressed_unique_bins;
  logic [31:0] total_unique_bins;

  t_recap_phase2_core #(
    .N(N),
    .L(L),
    .H(H),
    .F(F)
  ) u_phase2 (
    .clk                (CLOCK_50),
    .rst_n              (rst_n),
    .enable             (run_en),

    .sample_en          (core_sample_en),
    .xin                (xin),

    .bypass             (force_bypass),
    .thresh_T           (thresh8_used),

    .y_valid            (y_valid),
    .yout               (yout),

    .clr_metrics_pulse  (clr_metrics_pulse),

    .busy               (core_busy),
    .frame_overrun      (frame_overrun),

    .total_frames       (total_frames),
    .suppressed_unique_bins (suppressed_unique_bins),
    .total_unique_bins  (total_unique_bins)
  );

  // If audio is enabled, drive DAC with yout (mono -> stereo)
  generate
    if (USE_AUDIO_CODEC) begin : g_audio_sink
      logic signed [23:0] y24;
      always_comb y24 = $signed(yout) <<< (24 - N);

      always_ff @(posedge CLOCK_50 or negedge rst_n) begin
        if (!rst_n) begin
          aud_dac_l <= '0;
          aud_dac_r <= '0;
        end else if (aud_advance) begin
          aud_dac_l <= y24;
          aud_dac_r <= y24;
        end
      end
    end
  endgenerate


  // Debug + display

  logic alive;
  always_ff @(posedge CLOCK_50 or negedge rst_n) begin
    if (!rst_n) alive <= 1'b0;
    else if (dbg_tick) alive <= ~alive;
  end

  // Track last valid output sample
  logic signed [N-1:0] y_last;
  always_ff @(posedge CLOCK_50 or negedge rst_n) begin
    if (!rst_n) y_last <= '0;
    else if (y_valid) y_last <= yout;
  end

  // Select a 24-bit debug word
  logic [23:0] dbg_word;
  always_comb begin
    unique case (mode_sel)
      2'b00: dbg_word = total_frames[23:0];
      2'b01: dbg_word = suppressed_unique_bins[23:0];
      2'b10: dbg_word = total_unique_bins[23:0];
      default: dbg_word = {{(24-N){y_last[N-1]}}, y_last};
    endcase
  end

  // Latch at dbg_tick
  logic [23:0] dbg_word_lat;
  logic [9:0]  ledr_lat;

  always_ff @(posedge CLOCK_50 or negedge rst_n) begin
    if (!rst_n) begin
      dbg_word_lat <= '0;
      ledr_lat     <= '0;
    end else if (dbg_tick) begin
      dbg_word_lat <= dbg_word;
      ledr_lat     <= {alive, frame_overrun, thresh8_used};
    end
  end

  assign LEDR = ledr_lat;

  // 7-seg decode
  wire [3:0] nib0 = dbg_word_lat[3:0];
  wire [3:0] nib1 = dbg_word_lat[7:4];
  wire [3:0] nib2 = dbg_word_lat[11:8];
  wire [3:0] nib3 = dbg_word_lat[15:12];
  wire [3:0] nib4 = dbg_word_lat[19:16];
  wire [3:0] nib5 = dbg_word_lat[23:20];

  hex7seg u_hex0(.hex(nib0), .seg(HEX0));
  hex7seg u_hex1(.hex(nib1), .seg(HEX1));
  hex7seg u_hex2(.hex(nib2), .seg(HEX2));
  hex7seg u_hex3(.hex(nib3), .seg(HEX3));
  hex7seg u_hex4(.hex(nib4), .seg(HEX4));
  hex7seg u_hex5(.hex(nib5), .seg(HEX5));

endmodule



// Utility modules embedded for convenience

// Tick pulse generator: tick is 1 for one clk when counter hits DIV-1
module tick_pulse_gen #(
  parameter int DIV = 6250
)(
  input  logic clk,
  input  logic rst_n,
  input  logic enable,
  output logic tick
);
  localparam int CW = (DIV <= 1) ? 1 : $clog2(DIV);
  logic [CW-1:0] cnt;

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      cnt  <= '0;
      tick <= 1'b0;
    end else begin
      tick <= 1'b0;
      if (!enable) begin
        cnt <= '0;
      end else begin
        if (cnt == DIV-1) begin
          cnt  <= '0;
          tick <= 1'b1;
        end else begin
          cnt <= cnt + 1'b1;
        end
      end
    end
  end
endmodule


// 16-bit style LFSR (parameter W), shift-right, insert new bit at MSB
// new_bit = rnd[0] ^ rnd[2] ^ rnd[3] ^ rnd[5]
module lfsr_noise #(
  parameter int W = 16
)(
  input  logic         clk,
  input  logic         rst_n,
  input  logic         en,
  input  logic         seed_load,
  input  logic [W-1:0] seed,
  output logic [W-1:0] rnd
);
  logic new_bit;

  always_comb new_bit = rnd[0] ^ rnd[2] ^ rnd[3] ^ rnd[5];

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      rnd <= seed;
    end else if (seed_load) begin
      rnd <= seed;
    end else if (en) begin
      rnd <= {new_bit, rnd[W-1:1]};
    end
  end
endmodule


// Noise shaper: leaky integrator
// state = state + ((in_noise - state) >>> SHIFT)
// output = saturate(state) to N-bit signed
module noise_shaper #(
  parameter int N = 12,
  parameter int SHIFT = 3,
  parameter int STATE_W = 24
)(
  input  logic                 clk,
  input  logic                 rst_n,
  input  logic                 en,
  input  logic signed [N-1:0]  in_noise,
  output logic signed [N-1:0]  x_out
);
  logic signed [STATE_W-1:0] state;
  logic signed [STATE_W-1:0] in_ext;
  logic signed [STATE_W-1:0] diff;
  logic signed [STATE_W-1:0] delta;
  logic signed [STATE_W-1:0] next_state;

  function automatic logic signed [N-1:0] sat_to_N(input logic signed [STATE_W-1:0] v);
    logic signed [STATE_W-1:0] maxv, minv;
    logic signed [STATE_W-1:0] one;
    begin
      one  = 'sd1;
      maxv = (one <<< (N-1)) - one;
      minv = - (one <<< (N-1));
      if (v > maxv)      sat_to_N = maxv[N-1:0];
      else if (v < minv) sat_to_N = minv[N-1:0];
      else               sat_to_N = v[N-1:0];
    end
  endfunction

  always_comb begin
    in_ext     = $signed(in_noise);
    diff       = in_ext - state;
    delta      = diff >>> SHIFT;
    next_state = state + delta;
  end

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      state <= '0;
      x_out <= '0;
    end else if (en) begin
      state <= next_state;
      x_out <= sat_to_N(next_state);
    end
  end
endmodule


// Hex digit to 7-seg (active-low segments). seg[6:0] = {a,b,c,d,e,f,g}.
module hex7seg(
  input  logic [3:0] hex,
  output logic [6:0] seg
);
  always_comb begin
    unique case (hex)
      4'h0: seg = 7'b1000000;
      4'h1: seg = 7'b1111001;
      4'h2: seg = 7'b0100100;
      4'h3: seg = 7'b0110000;
      4'h4: seg = 7'b0011001;
      4'h5: seg = 7'b0010010;
      4'h6: seg = 7'b0000010;
      4'h7: seg = 7'b1111000;
      4'h8: seg = 7'b0000000;
      4'h9: seg = 7'b0010000;
      4'hA: seg = 7'b0001000;
      4'hB: seg = 7'b0000011;
      4'hC: seg = 7'b1000110;
      4'hD: seg = 7'b0100001;
      4'hE: seg = 7'b0000110;
      4'hF: seg = 7'b0001110;
      default: seg = 7'b1111111;
    endcase
  end
endmodule

`default_nettype wire
