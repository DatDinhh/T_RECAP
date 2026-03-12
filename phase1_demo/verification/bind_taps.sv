`timescale 1ns/1ps
`default_nettype wire

// Arizona State University 
// Capstone Senior Project
// Sigma Force
// Dat Dinh, Dat Huynh, Paul Applebee, Kyung Jae Son
// bind_taps.sv
//
// Provides a bindable wiring module that copies internal DUT signals
// into a tap_if instance.
//
// IMPORTANT USAGE NOTE:
//  - The bind statement must be placed in *tb_top.sv*
//    where the tap_if instance exists.
//  - Example:
//
//      tap_if #(.N(N), .LFSR_W(LFSR_W)) taps();
//      t_recap_demo_top #(.N(N), .LFSR_W(LFSR_W), ...) dut(...);
//
//      bind t_recap_demo_top t_recap_tap_bind #(.N(N), .LFSR_W(LFSR_W)) u_tap_bind (
//        .tap(taps),
//        .clk(CLOCK_50),
//        .rst_n(rst_n),
//        .clr_metrics_pulse(clr_metrics_pulse),
//        .mode_sel(mode_sel),
//        .force_bypass(force_bypass),
//        .thresh8_manual(thresh8_manual),
//        .thresh_used(thresh_used),
//        .sample_en(sample_en),
//        .dbg_tick(dbg_tick),
//        .lfsr_rnd(lfsr_rnd),
//        .u_noise(u_noise),
//        .x_stream(x_stream),
//        .pair_valid(pair_valid),
//        .x0(x0), .x1(x1),
//        .pair_out_valid(pair_out_valid),
//        .y0(y0), .y1(y1),
//        .suppressed(suppressed),
//        .x0_a(x0_a), .x1_a(x1_a),
//        .a_tap(a_tap), .d_tap(d_tap), .abs_d_tap(abs_d_tap),
//        .y_valid(y_valid), .y_out(y_out),
//        .total_pairs(total_pairs),
//        .suppressed_pairs(suppressed_pairs),
//        .sum_abs_err(sum_abs_err),
//        .sum_sq_err(sum_sq_err),
//        .alive(alive),
//        .suppressed_last(suppressed_last),
//        .dbg_word(dbg_word),
//        .dbg_word_lat(dbg_word_lat),
//        .ledr_lat(ledr_lat)
//      );


module t_recap_tap_bind #(
  parameter int N      = 12,
  parameter int LFSR_W = 16
) (
  tap_if.dut_out            tap,

  // basic
  input  logic             clk,
  input  logic             rst_n,
  input  logic             clr_metrics_pulse,

  // mode/threshold
  input  logic [1:0]       mode_sel,
  input  logic             force_bypass,
  input  logic [7:0]       thresh8_manual,
  input  logic [N:0]       thresh_used,

  // ticks
  input  logic             sample_en,
  input  logic             dbg_tick,

  // source
  input  logic [LFSR_W-1:0]    lfsr_rnd,
  input  logic signed [N-1:0]  u_noise,
  input  logic signed [N-1:0]  x_stream,

  // pair in
  input  logic                 pair_valid,
  input  logic signed [N-1:0]  x0,
  input  logic signed [N-1:0]  x1,

  // pair out
  input  logic                 pair_out_valid,
  input  logic signed [N-1:0]  y0,
  input  logic signed [N-1:0]  y1,
  input  logic                 suppressed,
  input  logic signed [N-1:0]  x0_a,
  input  logic signed [N-1:0]  x1_a,

  // haar taps
  input  logic signed [N:0]    a_tap,
  input  logic signed [N:0]    d_tap,
  input  logic [N:0]           abs_d_tap,

  // y stream
  input  logic                 y_valid,
  input  logic signed [N-1:0]  y_out,

  // metrics
  input  logic [31:0]          total_pairs,
  input  logic [31:0]          suppressed_pairs,
  input  logic [31:0]          sum_abs_err,
  input  logic [47:0]          sum_sq_err,

  // debug
  input  logic                 alive,
  input  logic                 suppressed_last,
  input  logic [23:0]          dbg_word,
  input  logic [23:0]          dbg_word_lat,
  input  logic [9:0]           ledr_lat
);

  // Pure wiring into interface (procedural to keep it legal for variables)
  always_comb begin
    tap.clk              = clk;
    tap.rst_n            = rst_n;
    tap.clr_metrics_pulse= clr_metrics_pulse;

    tap.mode_sel         = mode_sel;
    tap.force_bypass     = force_bypass;
    tap.thresh8_manual   = thresh8_manual;
    tap.thresh_used      = thresh_used;

    tap.sample_en        = sample_en;
    tap.dbg_tick         = dbg_tick;

    tap.lfsr_rnd         = lfsr_rnd;
    tap.u_noise          = u_noise;
    tap.x_stream         = x_stream;

    tap.pair_valid       = pair_valid;
    tap.x0               = x0;
    tap.x1               = x1;

    tap.pair_out_valid   = pair_out_valid;
    tap.y0               = y0;
    tap.y1               = y1;
    tap.suppressed       = suppressed;
    tap.x0_a             = x0_a;
    tap.x1_a             = x1_a;

    tap.a_tap            = a_tap;
    tap.d_tap            = d_tap;
    tap.abs_d_tap        = abs_d_tap;

    tap.y_valid          = y_valid;
    tap.y_out            = y_out;

    tap.total_pairs      = total_pairs;
    tap.suppressed_pairs = suppressed_pairs;
    tap.sum_abs_err      = sum_abs_err;
    tap.sum_sq_err       = sum_sq_err;

    tap.alive            = alive;
    tap.suppressed_last  = suppressed_last;
    tap.dbg_word         = dbg_word;
    tap.dbg_word_lat     = dbg_word_lat;
    tap.ledr_lat         = ledr_lat;
  end

endmodule : t_recap_tap_bind

`default_nettype wire



