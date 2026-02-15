`timescale 1ns/1ps
`default_nettype none

// Arizona State University 
// Capstone Senior Project
// Sigma Force
// Dat Dinh, Dat Huynh, Paul Applebee, Kyung Jae Son
// tap_if.sv
//
// Internal tap interface for t_recap_demo_top.
//
// This interface is intended to be driven by a bind module
// (see bind_taps.sv), so monitors/scoreboards can avoid messy
// hierarchical references.


interface tap_if #(
  parameter int N      = 12,
  parameter int LFSR_W = 16
);


  // Basic timing / control

  logic        clk;
  logic        rst_n;
  logic        clr_metrics_pulse;

  logic [1:0]  mode_sel;
  logic        force_bypass;
  logic [7:0]  thresh8_manual;
  logic [N:0]  thresh_used;

  logic        sample_en;
  logic        dbg_tick;


  // Internal source and stream

  logic [LFSR_W-1:0]      lfsr_rnd;
  logic signed [N-1:0]    u_noise;
  logic signed [N-1:0]    x_stream;


  // Pair domain (inputs)

  logic                   pair_valid;
  logic signed [N-1:0]    x0;
  logic signed [N-1:0]    x1;


  // Pair domain (outputs)

  logic                   pair_out_valid;
  logic signed [N-1:0]    y0;
  logic signed [N-1:0]    y1;
  logic                   suppressed;

  // aligned x for metrics
  logic signed [N-1:0]    x0_a;
  logic signed [N-1:0]    x1_a;

  // optional Haar debug taps
  logic signed [N:0]      a_tap;
  logic signed [N:0]      d_tap;
  logic [N:0]             abs_d_tap;


  // Serialized output stream

  logic                   y_valid;
  logic signed [N-1:0]    y_out;


  // Metrics
  
  logic [31:0]            total_pairs;
  logic [31:0]            suppressed_pairs;
  logic [31:0]            sum_abs_err;
  logic [47:0]            sum_sq_err;


  // Debug / IO-related internals

  logic                   alive;
  logic                   suppressed_last;
  logic [23:0]            dbg_word;
  logic [23:0]            dbg_word_lat;
  logic [9:0]             ledr_lat;


  // Modports

  // Driven by bind (DUT-side)
  modport dut_out (
    output clk,
    output rst_n,
    output clr_metrics_pulse,
    output mode_sel,
    output force_bypass,
    output thresh8_manual,
    output thresh_used,
    output sample_en,
    output dbg_tick,
    output lfsr_rnd,
    output u_noise,
    output x_stream,
    output pair_valid,
    output x0,
    output x1,
    output pair_out_valid,
    output y0,
    output y1,
    output suppressed,
    output x0_a,
    output x1_a,
    output a_tap,
    output d_tap,
    output abs_d_tap,
    output y_valid,
    output y_out,
    output total_pairs,
    output suppressed_pairs,
    output sum_abs_err,
    output sum_sq_err,
    output alive,
    output suppressed_last,
    output dbg_word,
    output dbg_word_lat,
    output ledr_lat
  );

  // Read-only by monitors / scoreboards
  modport mon (
    input clk,
    input rst_n,
    input clr_metrics_pulse,
    input mode_sel,
    input force_bypass,
    input thresh8_manual,
    input thresh_used,
    input sample_en,
    input dbg_tick,
    input lfsr_rnd,
    input u_noise,
    input x_stream,
    input pair_valid,
    input x0,
    input x1,
    input pair_out_valid,
    input y0,
    input y1,
    input suppressed,
    input x0_a,
    input x1_a,
    input a_tap,
    input d_tap,
    input abs_d_tap,
    input y_valid,
    input y_out,
    input total_pairs,
    input suppressed_pairs,
    input sum_abs_err,
    input sum_sq_err,
    input alive,
    input suppressed_last,
    input dbg_word,
    input dbg_word_lat,
    input ledr_lat
  );

  // Optional monitor clocking block (nice for race-free sampling)
  clocking mon_cb @(posedge clk);
    input rst_n;
    input clr_metrics_pulse;
    input mode_sel;
    input force_bypass;
    input thresh8_manual;
    input thresh_used;
    input sample_en;
    input dbg_tick;
    input lfsr_rnd;
    input u_noise;
    input x_stream;
    input pair_valid;
    input x0;
    input x1;
    input pair_out_valid;
    input y0;
    input y1;
    input suppressed;
    input x0_a;
    input x1_a;
    input a_tap;
    input d_tap;
    input abs_d_tap;
    input y_valid;
    input y_out;
    input total_pairs;
    input suppressed_pairs;
    input sum_abs_err;
    input sum_sq_err;
    input alive;
    input suppressed_last;
    input dbg_word;
    input dbg_word_lat;
    input ledr_lat;
  endclocking

endinterface : tap_if

`default_nettype wire



