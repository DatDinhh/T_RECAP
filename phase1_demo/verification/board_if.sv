`timescale 1ns/1ps
`default_nettype none

// Arizona State University 
// Capstone Senior Project
// Sigma Force
// Dat Dinh, Dat Huynh, Paul Applebee, Kyung Jae Son
// board_if.sv
//
// Board-level interface for t_recap_demo_top (DE10-Lite style).
//
// Signals:
//  - CLOCK_50 : driven by TB
//  - KEY[0]   : reset button (active-low on board; DUT uses rst_n = KEY[0])
//  - KEY[1]   : clear-metrics button (active-low; DUT edge-detects falling edge)
//  - SW[7:0]  : threshold
//  - SW[9:8]  : mode
//  - LEDR     : status/threshold display from DUT
//  - HEX0..5  : 7-seg outputs from DUT
//
// This interface also includes small convenience tasks for DV.


interface board_if;


  // Physical pins

  logic        CLOCK_50;
  logic [1:0]  KEY;
  logic [9:0]  SW;
  logic [9:0]  LEDR;
  logic [6:0]  HEX0;
  logic [6:0]  HEX1;
  logic [6:0]  HEX2;
  logic [6:0]  HEX3;
  logic [6:0]  HEX4;
  logic [6:0]  HEX5;


  // Mode encodings (match DUT comments)

  localparam logic [1:0] MODE_BYPASS = 2'b00;
  localparam logic [1:0] MODE_MAN_SUPP = 2'b01;
  localparam logic [1:0] MODE_MAN_ABS  = 2'b10;
  localparam logic [1:0] MODE_MAN_SQ   = 2'b11;


  // Modports

  // TB drives clock + inputs, observes outputs
  modport tb (
    output CLOCK_50,
    output KEY,
    output SW,
    input  LEDR,
    input  HEX0,
    input  HEX1,
    input  HEX2,
    input  HEX3,
    input  HEX4,
    input  HEX5
  );

  // DUT consumes clock + inputs, drives outputs
  modport dut (
    input  CLOCK_50,
    input  KEY,
    input  SW,
    output LEDR,
    output HEX0,
    output HEX1,
    output HEX2,
    output HEX3,
    output HEX4,
    output HEX5
  );


  // Convenience tasks 


  // Put inputs into a known released/default state.
  task automatic init_defaults();
    // KEY buttons are active-low, released = 1
    KEY = '1;
    // Switches default to 0
    SW  = '0;
  endtask

  // Wait N rising edges of CLOCK_50.
  task automatic wait_clocks(input int unsigned n = 1);
    repeat (n) @(posedge CLOCK_50);
  endtask

  // Apply an active-low reset on KEY[0].
  task automatic apply_reset(input int unsigned hold_cycles = 5);
    // Ensure other button released
    KEY[1] = 1'b1;

    KEY[0] = 1'b0; // assert reset
    wait_clocks(hold_cycles);
    KEY[0] = 1'b1; // deassert reset

    // give the DUT a couple cycles to settle
    wait_clocks(2);
  endtask

  // Generate the clear-metrics falling edge on KEY[1].
  // The DUT edge-detects KEY[1] with 2FFs; one-cycle low is sufficient.
  task automatic press_clear_metrics(input int unsigned low_cycles = 1);
    // released
    KEY[1] = 1'b1;
    wait_clocks(1);

    // press (active-low)
    KEY[1] = 1'b0;
    wait_clocks(low_cycles);

    // release
    KEY[1] = 1'b1;
    wait_clocks(1);
  endtask

  task automatic set_mode(input logic [1:0] mode);
    SW[9:8] = mode;
  endtask

  task automatic set_threshold(input logic [7:0] thresh);
    SW[7:0] = thresh;
  endtask

  task automatic set_mode_and_threshold(
    input logic [1:0] mode,
    input logic [7:0] thresh
  );
    SW[9:8] = mode;
    SW[7:0] = thresh;
  endtask

endinterface : board_if

`default_nettype wire




