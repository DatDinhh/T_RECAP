`timescale 1ns/1ps
`default_nettype none

// Arizona State University 
// Capstone Senior Project
// Sigma Force
// Dat Dinh, Dat Huynh, Paul Applebee, Kyung Jae Son
// phase2_top.sv
//
// Production-oriented Phase 2 top-level integration for T-RECAP.
//
// This file intentionally contains TWO tops:
//
//   1) phase2_core_top
//      - board-agnostic, reusable integration shell intended for long-term RTL,
//        ASIC portability, and signoff-driven DV.
//      - instantiates the real Phase 2 engine core (expected elsewhere in repo
//        as phase2_engine_core.sv and its child modules / IP wrappers).
//
//   2) phase2_top
//      - DE1-SoC deployment wrapper around phase2_core_top.
//      - provides clean reset handling, debounced buttons, board config decode,
//        internal deterministic bring-up source, status LEDs, and HEX display.
//
// Why both modules exist in one file:
//   - The board wrapper is useful immediately for FPGA deployment.
//   - The reusable core wrapper keeps the architecture portable if the design is
//     later hardened or migrated toward an ASIC / tapeout flow.
// Board-agnostic reusable core top

module phase2_core_top #(
  parameter int N               = 12,
  parameter int L               = 256,
  parameter int H               = 128,
  parameter int WIN_W           = 16,
  parameter int FFT_IN_W        = 20,
  parameter int FFT_W           = 24,
  parameter int OLA_W           = 32,
  parameter int FRAME_ID_W      = 32,
  parameter int THR2_W          = (2*FFT_W + 2)
)(
  input  logic                         clk,
  input  logic                         rst_n,

  // Streaming input
  input  logic                         xin_valid,
  input  logic signed [N-1:0]         xin,
  output logic                         xin_ready,

  // Configuration
  input  logic                         cfg_enable,
  input  logic                         cfg_bypass_mask,
  input  logic                         cfg_protect_dc,
  input  logic                         cfg_protect_nyq,
  input  logic                         cfg_clr_metrics_pulse,
  input  logic [THR2_W-1:0]           cfg_thr2,

  // Reconstructed output stream
  output logic                         yout_valid,
  output logic signed [N-1:0]         yout,

  // Sparse-bin sideband stream (for downstream compute skipping)
  output logic                         sbin_valid,
  input  logic                         sbin_ready,
  output logic [FRAME_ID_W-1:0]       sbin_frame_id,
  output logic [$clog2(L)-1:0]        sbin_bin_idx,
  output logic signed [FFT_W-1:0]     sbin_re,
  output logic signed [FFT_W-1:0]     sbin_im,

  // Sticky / summary status
  output logic                         stat_frame_job_overflow,
  output logic                         stat_ola_overflow,
  output logic                         stat_fft_overflow,
  output logic                         stat_ifft_overflow,
  output logic [31:0]                  stat_total_frames,
  output logic [31:0]                  stat_total_output_samples,
  output logic [31:0]                  stat_suppressed_unique_bins,
  output logic [31:0]                  stat_eligible_unique_bins,
  output logic [63:0]                  stat_input_energy,
  output logic [63:0]                  stat_output_energy,
  output logic [63:0]                  stat_sum_abs_err,
  output logic [63:0]                  stat_sum_sq_err
);

  localparam int BIN_W = (L <= 2) ? 1 : $clog2(L);


  // Static parameter checks.
  // These are hard failures because a wrong top-level contract here will poison
  // the whole project, golden model included.

  initial begin : p_static_checks
    if (L < 8) begin
      $fatal(1, "phase2_core_top: L must be >= 8; got %0d", L);
    end
    if ((L & (L-1)) != 0) begin
      $fatal(1, "phase2_core_top: L must be a power of two; got %0d", L);
    end
    if (H <= 0) begin
      $fatal(1, "phase2_core_top: H must be > 0; got %0d", H);
    end
    if (H != (L/2)) begin
      $fatal(1, "phase2_core_top: frozen baseline expects H=L/2. Got L=%0d, H=%0d", L, H);
    end
    if (FFT_IN_W < (N + 4)) begin
      $error("phase2_core_top: FFT_IN_W=%0d is unusually small for N=%0d", FFT_IN_W, N);
    end
    if (FFT_W < FFT_IN_W) begin
      $error("phase2_core_top: FFT_W=%0d < FFT_IN_W=%0d; check width plan", FFT_W, FFT_IN_W);
    end
    if (OLA_W < (N + 8)) begin
      $error("phase2_core_top: OLA_W=%0d is unusually small for N=%0d", OLA_W, N);
    end
    if (THR2_W < (2*FFT_W)) begin
      $error("phase2_core_top: THR2_W=%0d seems too small for FFT_W=%0d", THR2_W, FFT_W);
    end
    if (BIN_W != $clog2(L)) begin
      $fatal(1, "phase2_core_top: internal BIN_W mismatch");
    end
  end


  // This architecture is intentionally non-backpressured in steady state.
  // Real-time correctness requires the engine to keep up. If it cannot, it must
  // raise sticky overflow/error flags rather than silently stall the stream.

  assign xin_ready = cfg_enable;

  // Top-level explicit port mapping is kept here so the contract is frozen.

  (* keep_hierarchy = "yes" *)
  phase2_engine_core #(
    .N               (N),
    .L               (L),
    .H               (H),
    .WIN_W           (WIN_W),
    .FFT_IN_W        (FFT_IN_W),
    .FFT_W           (FFT_W),
    .OLA_W           (OLA_W),
    .FRAME_ID_W      (FRAME_ID_W),
    .THR2_W          (THR2_W)
  ) u_phase2_engine_core (
    .clk                       (clk),
    .rst_n                     (rst_n),

    .xin_valid                 (xin_valid & xin_ready),
    .xin                       (xin),

    .cfg_enable                (cfg_enable),
    .cfg_bypass_mask           (cfg_bypass_mask),
    .cfg_protect_dc            (cfg_protect_dc),
    .cfg_protect_nyq           (cfg_protect_nyq),
    .cfg_clr_metrics_pulse     (cfg_clr_metrics_pulse),
    .cfg_thr2                  (cfg_thr2),

    .yout_valid                (yout_valid),
    .yout                      (yout),

    .sbin_valid                (sbin_valid),
    .sbin_ready                (sbin_ready),
    .sbin_frame_id             (sbin_frame_id),
    .sbin_bin_idx              (sbin_bin_idx),
    .sbin_re                   (sbin_re),
    .sbin_im                   (sbin_im),

    .stat_frame_job_overflow   (stat_frame_job_overflow),
    .stat_ola_overflow         (stat_ola_overflow),
    .stat_fft_overflow         (stat_fft_overflow),
    .stat_ifft_overflow        (stat_ifft_overflow),
    .stat_total_frames         (stat_total_frames),
    .stat_total_output_samples (stat_total_output_samples),
    .stat_suppressed_unique_bins(stat_suppressed_unique_bins),
    .stat_eligible_unique_bins (stat_eligible_unique_bins),
    .stat_input_energy         (stat_input_energy),
    .stat_output_energy        (stat_output_energy),
    .stat_sum_abs_err          (stat_sum_abs_err),
    .stat_sum_sq_err           (stat_sum_sq_err)
  );

endmodule



// DE1-SoC deployment wrapper
// Board mapping (recommended baseline):
//   KEY[0] : reset (active-low pushbutton)
//   KEY[1] : clear metrics / clear sticky status
//   KEY[2] : cycle HEX display page
//   KEY[3] : cycle internal demo-source profile
//
//   SW[9]  : core enable
//   SW[8]  : bypass mask (1 = no suppression, architecture still active)
//   SW[7:0]: threshold magnitude control (board-side UI value; squared and
//            shifted here into cfg_thr2 domain)
//
// LEDR mapping:
//   [0] enable
//   [1] bypass
//   [2] protect_dc (fixed 1 here)
//   [3] protect_nyq (fixed 0 here)
//   [4] heartbeat
//   [5] sparse-bin valid (activity indicator)
//   [6] frame-job overflow sticky
//   [7] fft overflow sticky
//   [8] ifft overflow sticky
//   [9] OLA overflow sticky
//
// HEX pages (cycle with KEY[2]):
//   0 total_frames[23:0]
//   1 suppressed_unique_bins[23:0]
//   2 eligible_unique_bins[23:0]
//   3 sum_abs_err[23:0]
//   4 sum_sq_err[23:0]
//   5 input_energy[23:0]
//   6 output_energy[23:0]
//   7 {src_mode, thr_mag, flags}
//
// NOTE:
//   The board wrapper uses an internal deterministic demo source by default for
//   bring-up. For real external acquisition, replace xin/xin_valid generation
//   with ADC / codec / GPIO streaming while preserving the phase2_core_top
//   interface and the sample cadence assumptions.

module phase2_top #(
  parameter int N               = 12,
  parameter int L               = 256,
  parameter int H               = 128,
  parameter int WIN_W           = 16,
  parameter int FFT_IN_W        = 20,
  parameter int FFT_W           = 24,
  parameter int OLA_W           = 32,
  parameter int FRAME_ID_W      = 32,
  parameter int THR2_W          = (2*FFT_W + 2),

  parameter int SAMPLE_DIV      = 6_250,      // 50 MHz / 6250 = 8 kHz
  parameter int DBG_DIV         = 5_000_000,  // 10 Hz heartbeat / display latch
  parameter int DEBOUNCE_CLKS   = 500_000,    // 10 ms @ 50 MHz
  parameter int BOARD_THR2_SHIFT= 8
)(
  input  logic                  CLOCK_50,
  input  logic [3:0]            KEY,
  input  logic [9:0]            SW,
  output logic [9:0]            LEDR,
  output logic [6:0]            HEX0,
  output logic [6:0]            HEX1,
  output logic [6:0]            HEX2,
  output logic [6:0]            HEX3,
  output logic [6:0]            HEX4,
  output logic [6:0]            HEX5
);
  localparam int BIN_W = (L <= 2) ? 1 : $clog2(L);


  // Clean reset: asynchronous assertion from KEY[0], synchronous release.

  logic rst_n;
  reset_sync_active_low u_reset_sync (
    .clk     (CLOCK_50),
    .arst_n  (KEY[0]),
    .srst_n  (rst_n)
  );


  // Button conditioning

  logic clr_metrics_pulse;
  logic page_adv_pulse;
  logic src_mode_pulse;

  btn_pulse_active_low #(.STABLE_CLKS(DEBOUNCE_CLKS)) u_btn_clr (
    .clk         (CLOCK_50),
    .rst_n       (rst_n),
    .btn_n_async (KEY[1]),
    .press_pulse (clr_metrics_pulse)
  );

  btn_pulse_active_low #(.STABLE_CLKS(DEBOUNCE_CLKS)) u_btn_page (
    .clk         (CLOCK_50),
    .rst_n       (rst_n),
    .btn_n_async (KEY[2]),
    .press_pulse (page_adv_pulse)
  );

  btn_pulse_active_low #(.STABLE_CLKS(DEBOUNCE_CLKS)) u_btn_src (
    .clk         (CLOCK_50),
    .rst_n       (rst_n),
    .btn_n_async (KEY[3]),
    .press_pulse (src_mode_pulse)
  );


  // Board-side UI/config decode

  logic cfg_enable;
  logic cfg_bypass_mask;
  logic cfg_protect_dc;
  logic cfg_protect_nyq;
  logic [7:0] thr_mag_ui;
  logic [15:0] thr_mag_sq;
  logic [THR2_W-1:0] cfg_thr2;

  assign cfg_enable       = SW[9];
  assign cfg_bypass_mask  = SW[8];
  assign cfg_protect_dc   = 1'b1;
  assign cfg_protect_nyq  = 1'b0;
  assign thr_mag_ui       = SW[7:0];
  assign thr_mag_sq       = thr_mag_ui * thr_mag_ui;
  assign cfg_thr2         = ({{(THR2_W-16){1'b0}}, thr_mag_sq} << BOARD_THR2_SHIFT);


  // Sample tick and debug tick

  logic sample_tick;
  logic dbg_tick;

  tick_pulse_gen #(.DIV(SAMPLE_DIV)) u_sample_tick (
    .clk    (CLOCK_50),
    .rst_n  (rst_n),
    .enable (1'b1),
    .tick   (sample_tick)
  );

  tick_pulse_gen #(.DIV(DBG_DIV)) u_dbg_tick (
    .clk    (CLOCK_50),
    .rst_n  (rst_n),
    .enable (1'b1),
    .tick   (dbg_tick)
  );


  // Deterministic internal source for bring-up.
  // Use KEY[3] to cycle profiles.

  logic [1:0] src_mode;
  always_ff @(posedge CLOCK_50 or negedge rst_n) begin
    if (!rst_n) begin
      src_mode <= 2'd0;
    end else if (src_mode_pulse) begin
      src_mode <= src_mode + 2'd1;
    end
  end

  logic                        xin_valid;
  logic signed [N-1:0]        xin;

  phase2_demo_source #(
    .N           (N),
    .LFSR_W      (16),
    .NOISE_SHIFT (4)
  ) u_demo_source (
    .clk       (CLOCK_50),
    .rst_n     (rst_n),
    .sample_en (sample_tick & cfg_enable),
    .src_mode  (src_mode),
    .xout_valid(xin_valid),
    .xout      (xin)
  );


  // Core instance

  logic                        xin_ready;
  logic                        yout_valid;
  logic signed [N-1:0]        yout;

  logic                        sbin_valid;
  logic [FRAME_ID_W-1:0]      sbin_frame_id;
  logic [BIN_W-1:0]           sbin_bin_idx;
  logic signed [FFT_W-1:0]    sbin_re, sbin_im;

  logic                        stat_frame_job_overflow;
  logic                        stat_ola_overflow;
  logic                        stat_fft_overflow;
  logic                        stat_ifft_overflow;
  logic [31:0]                 stat_total_frames;
  logic [31:0]                 stat_total_output_samples;
  logic [31:0]                 stat_suppressed_unique_bins;
  logic [31:0]                 stat_eligible_unique_bins;
  logic [63:0]                 stat_input_energy;
  logic [63:0]                 stat_output_energy;
  logic [63:0]                 stat_sum_abs_err;
  logic [63:0]                 stat_sum_sq_err;

  phase2_core_top #(
    .N          (N),
    .L          (L),
    .H          (H),
    .WIN_W      (WIN_W),
    .FFT_IN_W   (FFT_IN_W),
    .FFT_W      (FFT_W),
    .OLA_W      (OLA_W),
    .FRAME_ID_W (FRAME_ID_W),
    .THR2_W     (THR2_W)
  ) u_phase2_core_top (
    .clk                       (CLOCK_50),
    .rst_n                     (rst_n),

    .xin_valid                 (xin_valid),
    .xin                       (xin),
    .xin_ready                 (xin_ready),

    .cfg_enable                (cfg_enable),
    .cfg_bypass_mask           (cfg_bypass_mask),
    .cfg_protect_dc            (cfg_protect_dc),
    .cfg_protect_nyq           (cfg_protect_nyq),
    .cfg_clr_metrics_pulse     (clr_metrics_pulse),
    .cfg_thr2                  (cfg_thr2),

    .yout_valid                (yout_valid),
    .yout                      (yout),

    .sbin_valid                (sbin_valid),
    .sbin_ready                (1'b1),
    .sbin_frame_id             (sbin_frame_id),
    .sbin_bin_idx              (sbin_bin_idx),
    .sbin_re                   (sbin_re),
    .sbin_im                   (sbin_im),

    .stat_frame_job_overflow   (stat_frame_job_overflow),
    .stat_ola_overflow         (stat_ola_overflow),
    .stat_fft_overflow         (stat_fft_overflow),
    .stat_ifft_overflow        (stat_ifft_overflow),
    .stat_total_frames         (stat_total_frames),
    .stat_total_output_samples (stat_total_output_samples),
    .stat_suppressed_unique_bins(stat_suppressed_unique_bins),
    .stat_eligible_unique_bins (stat_eligible_unique_bins),
    .stat_input_energy         (stat_input_energy),
    .stat_output_energy        (stat_output_energy),
    .stat_sum_abs_err          (stat_sum_abs_err),
    .stat_sum_sq_err           (stat_sum_sq_err)
  );


  // Sticky status for board observability

  logic overflow_job_sticky;
  logic overflow_fft_sticky;
  logic overflow_ifft_sticky;
  logic overflow_ola_sticky;
  logic heartbeat;

  always_ff @(posedge CLOCK_50 or negedge rst_n) begin
    if (!rst_n) begin
      overflow_job_sticky  <= 1'b0;
      overflow_fft_sticky  <= 1'b0;
      overflow_ifft_sticky <= 1'b0;
      overflow_ola_sticky  <= 1'b0;
      heartbeat            <= 1'b0;
    end else begin
      if (clr_metrics_pulse) begin
        overflow_job_sticky  <= 1'b0;
        overflow_fft_sticky  <= 1'b0;
        overflow_ifft_sticky <= 1'b0;
        overflow_ola_sticky  <= 1'b0;
      end else begin
        overflow_job_sticky  <= overflow_job_sticky  | stat_frame_job_overflow;
        overflow_fft_sticky  <= overflow_fft_sticky  | stat_fft_overflow;
        overflow_ifft_sticky <= overflow_ifft_sticky | stat_ifft_overflow;
        overflow_ola_sticky  <= overflow_ola_sticky  | stat_ola_overflow;
      end

      if (dbg_tick) begin
        heartbeat <= ~heartbeat;
      end
    end
  end


  // HEX page selection and display word

  logic [2:0] page_sel;
  logic [23:0] dbg_word;

  always_ff @(posedge CLOCK_50 or negedge rst_n) begin
    if (!rst_n) begin
      page_sel <= 3'd0;
    end else if (page_adv_pulse) begin
      page_sel <= page_sel + 3'd1;
    end
  end

  always_comb begin
    unique case (page_sel)
      3'd0: dbg_word = stat_total_frames[23:0];
      3'd1: dbg_word = stat_suppressed_unique_bins[23:0];
      3'd2: dbg_word = stat_eligible_unique_bins[23:0];
      3'd3: dbg_word = stat_sum_abs_err[23:0];
      3'd4: dbg_word = stat_sum_sq_err[23:0];
      3'd5: dbg_word = stat_input_energy[23:0];
      3'd6: dbg_word = stat_output_energy[23:0];
      3'd7: dbg_word = {
               src_mode,
               cfg_enable,
               cfg_bypass_mask,
               cfg_protect_dc,
               cfg_protect_nyq,
               thr_mag_ui,
               10'h000
             };
      default: dbg_word = 24'h0;
    endcase
  end

  hex7seg u_hex0 (.hex(dbg_word[ 3: 0]), .seg(HEX0));
  hex7seg u_hex1 (.hex(dbg_word[ 7: 4]), .seg(HEX1));
  hex7seg u_hex2 (.hex(dbg_word[11: 8]), .seg(HEX2));
  hex7seg u_hex3 (.hex(dbg_word[15:12]), .seg(HEX3));
  hex7seg u_hex4 (.hex(dbg_word[19:16]), .seg(HEX4));
  hex7seg u_hex5 (.hex(dbg_word[23:20]), .seg(HEX5));


  // LED status

  always_comb begin
    LEDR[0] = cfg_enable;
    LEDR[1] = cfg_bypass_mask;
    LEDR[2] = cfg_protect_dc;
    LEDR[3] = cfg_protect_nyq;
    LEDR[4] = heartbeat;
    LEDR[5] = sbin_valid;
    LEDR[6] = overflow_job_sticky;
    LEDR[7] = overflow_fft_sticky;
    LEDR[8] = overflow_ifft_sticky;
    LEDR[9] = overflow_ola_sticky;
  end

  // Synthesis-time board sanity warning. Not fatal.
  initial begin : p_board_notes
    if (SAMPLE_DIV <= 0) begin
      $fatal(1, "phase2_top: SAMPLE_DIV must be > 0");
    end
    if (DBG_DIV <= 0) begin
      $fatal(1, "phase2_top: DBG_DIV must be > 0");
    end
  end

endmodule



// Helper: reset synchronizer (async assert, sync release)

module reset_sync_active_low (
  input  logic clk,
  input  logic arst_n,
  output logic srst_n
);
  logic [1:0] ff;
  always_ff @(posedge clk or negedge arst_n) begin
    if (!arst_n) begin
      ff <= 2'b00;
    end else begin
      ff <= {ff[0], 1'b1};
    end
  end
  assign srst_n = ff[1];
endmodule



// Helper: debounced one-pulse generator for active-low pushbutton

module btn_pulse_active_low #(
  parameter int STABLE_CLKS = 500_000
)(
  input  logic clk,
  input  logic rst_n,
  input  logic btn_n_async,
  output logic press_pulse
);
  localparam int CW = (STABLE_CLKS <= 2) ? 1 : $clog2(STABLE_CLKS);

  logic btn_meta, btn_sync;
  logic btn_stable_n;
  logic btn_stable_n_d;
  logic [CW-1:0] stable_ctr;

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      btn_meta <= 1'b1;
      btn_sync <= 1'b1;
    end else begin
      btn_meta <= btn_n_async;
      btn_sync <= btn_meta;
    end
  end

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      btn_stable_n   <= 1'b1;
      btn_stable_n_d <= 1'b1;
      stable_ctr     <= '0;
      press_pulse    <= 1'b0;
    end else begin
      press_pulse <= 1'b0;

      if (btn_sync == btn_stable_n) begin
        stable_ctr <= '0;
      end else begin
        if (stable_ctr == STABLE_CLKS-1) begin
          btn_stable_n <= btn_sync;
          stable_ctr   <= '0;
        end else begin
          stable_ctr <= stable_ctr + 1'b1;
        end
      end

      btn_stable_n_d <= btn_stable_n;
      if ((btn_stable_n_d == 1'b1) && (btn_stable_n == 1'b0)) begin
        press_pulse <= 1'b1;
      end
    end
  end
endmodule



// Helper: periodic one-cycle tick pulse

module tick_pulse_gen #(
  parameter int DIV = 50_000
)(
  input  logic clk,
  input  logic rst_n,
  input  logic enable,
  output logic tick
);
  localparam int CW = (DIV <= 2) ? 1 : $clog2(DIV);
  logic [CW-1:0] ctr;

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      ctr  <= '0;
      tick <= 1'b0;
    end else begin
      tick <= 1'b0;
      if (enable) begin
        if (ctr == DIV-1) begin
          ctr  <= '0;
          tick <= 1'b1;
        end else begin
          ctr <= ctr + 1'b1;
        end
      end
    end
  end
endmodule



// Internal deterministic demo source for STFT bring-up on FPGA board.
//
// src_mode:
//   00 = two square-wave tones + shaped noise
//   01 = shaped noise only
//   10 = tones only
//   11 = tone0 only
//
// This is intentionally simple and deterministic. It is not the final external
// acquisition path. Its job is to make the board wrapper useful immediately.

module phase2_demo_source #(
  parameter int N           = 12,
  parameter int LFSR_W      = 16,
  parameter int NOISE_SHIFT = 4
)(
  input  logic                 clk,
  input  logic                 rst_n,
  input  logic                 sample_en,
  input  logic [1:0]           src_mode,
  output logic                 xout_valid,
  output logic signed [N-1:0]  xout
);
  logic [LFSR_W-1:0] lfsr_rnd;
  logic [N-1:0]      u_u;
  logic signed [N:0] u_center_wide;
  logic signed [N-1:0] u_noise;
  logic signed [N-1:0] shaped_noise;

  logic [15:0] phase0, phase1;
  logic signed [N-1:0] tone0, tone1;
  logic signed [N+3:0] mix_wide;

  localparam logic signed [N-1:0] AMP0 = (1 <<< (N-3));
  localparam logic signed [N-1:0] AMP1 = (1 <<< (N-4));

  function automatic logic signed [N-1:0] sat_to_N(input logic signed [N+3:0] v);
    logic signed [N+3:0] maxv, minv;
    begin
      maxv = ({{(N+3){1'b0}},1'b1} <<< (N-1)) - 1;
      minv = -({{(N+3){1'b0}},1'b1} <<< (N-1));
      if (v > maxv)      sat_to_N = maxv[N-1:0];
      else if (v < minv) sat_to_N = minv[N-1:0];
      else               sat_to_N = v[N-1:0];
    end
  endfunction

  lfsr_noise #(.W(LFSR_W)) u_lfsr (
    .clk       (clk),
    .rst_n     (rst_n),
    .en        (sample_en),
    .seed_load (1'b0),
    .seed      (16'hACE1),
    .rnd       (lfsr_rnd)
  );

  assign u_u           = lfsr_rnd[N-1:0];
  assign u_center_wide = $signed({1'b0, u_u}) - $signed(1 <<< (N-1));
  assign u_noise       = u_center_wide[N-1:0];

  noise_shaper #(.N(N), .SHIFT(NOISE_SHIFT), .STATE_W(N+12)) u_shaper (
    .clk      (clk),
    .rst_n    (rst_n),
    .en       (sample_en),
    .in_noise (u_noise),
    .x_out    (shaped_noise)
  );

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      phase0     <= 16'd0;
      phase1     <= 16'd0;
      xout_valid <= 1'b0;
      xout       <= '0;
    end else begin
      xout_valid <= 1'b0;
      if (sample_en) begin
        phase0 <= phase0 + 16'd913;
        phase1 <= phase1 + 16'd2711;

        xout_valid <= 1'b1;
        xout       <= sat_to_N(mix_wide);
      end
    end
  end

  always_comb begin
    tone0 = phase0[15] ? AMP0 : -AMP0;
    tone1 = phase1[15] ? AMP1 : -AMP1;

    unique case (src_mode)
      2'b00: mix_wide = $signed(tone0) + $signed(tone1) + ($signed(shaped_noise) >>> 2);
      2'b01: mix_wide = ($signed(shaped_noise) >>> 1);
      2'b10: mix_wide = $signed(tone0) + $signed(tone1);
      2'b11: mix_wide = $signed(tone0);
      default: mix_wide = '0;
    endcase
  end
endmodule



// Reusable deterministic LFSR

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
  always_comb begin
    new_bit = rnd[0] ^ rnd[2] ^ rnd[3] ^ rnd[5];
  end

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      rnd <= 16'hACE1;
    end else if (seed_load) begin
      rnd <= (seed != '0) ? seed : 16'hACE1;
    end else if (en) begin
      rnd <= {new_bit, rnd[W-1:1]};
    end
  end
endmodule



// Simple first-order noise shaper reused from Phase 1 style bring-up flow

module noise_shaper #(
  parameter int N       = 12,
  parameter int SHIFT   = 3,
  parameter int STATE_W = N+12
)(
  input  logic                    clk,
  input  logic                    rst_n,
  input  logic                    en,
  input  logic signed [N-1:0]     in_noise,
  output logic signed [N-1:0]     x_out
);
  logic signed [STATE_W-1:0] state;
  logic signed [STATE_W-1:0] in_ext;
  logic signed [STATE_W-1:0] diff;
  logic signed [STATE_W-1:0] delta;
  logic signed [STATE_W-1:0] next_state;

  function automatic logic signed [N-1:0] sat_to_N(input logic signed [STATE_W-1:0] v);
    logic signed [STATE_W-1:0] maxv, minv, one;
    begin
      one  = 'sd1;
      maxv = (one <<< (N-1)) - one;
      minv = -(one <<< (N-1));
      if (v > maxv)      sat_to_N = maxv[N-1:0];
      else if (v < minv) sat_to_N = minv[N-1:0];
      else               sat_to_N = v[N-1:0];
    end
  endfunction

  always_comb begin
    in_ext     = {{(STATE_W-N){in_noise[N-1]}}, in_noise};
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



// 7-segment decoder (active-low segments)

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
