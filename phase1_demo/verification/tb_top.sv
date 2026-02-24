`timescale 1ns/1ps
`default_nettype none

// Arizona State University 
// Capstone Senior Project
// Sigma Force
// Dat Dinh, Dat Huynh, Paul Applebee, Kyung Jae Son
// tb_top.sv
//
// Fully functional *non-UVM* top-level testbench for:
//   t_recap_demo_top.sv  (T-RECAP Phase 1 Haar Demo)
//
// This top does ALL the plumbing:
//   - Generates CLOCK_50
//   - Instantiates board_if + tap_if
//   - Instantiates the DUT (with simulation-friendly tick dividers)
//   - Binds internal DUT nets into tap_if via t_recap_tap_bind (bind_taps.sv)
//   - Instantiates monitors + scoreboards + coverage
//   - Selects and runs a class-based test via +TEST=<name>
//
// Recommended compile order:
//   tb_pkg.sv
//   board_if.sv
//   tap_if.sv
//   bind_taps.sv
//   t_recap_demo_top.sv
//   ref_model_phase1.sv
//   golden_files_loader.sv
//   x_stream_monitor.sv
//   pair_monitor.sv
//   y_stream_monitor.sv
//   metrics_monitor.sv
//   io_monitor.sv
//   scoreboard_pairs.sv
//   scoreboard_y_stream.sv
//   scoreboard_metrics.sv
//   cov_phase1.sv
//   sva_phase1_bind.sv
//   board_driver_pkg.sv 
//   test_base.sv
//   test_bypass_lossless.sv
//   test_golden_thresh16.sv
//   test_threshold_sweep.sv
//   test_clear_metrics_midrun.sv
//   test_mode_switch_stress.sv
//   tb_top.sv



module tb_top;


  // Imports

  import tb_pkg::*;

  // Tests live in packages; import them so we can construct classes by name.
  import test_pkg::*;
  import board_driver_pkg::*;

  import tests_pkg::*;             // test_bypass_lossless
  import tests_golden_pkg::*;      // test_golden_thresh16
  import tests_sweep_pkg::*;       // test_threshold_sweep
  import tests_clear_pkg::*;       // test_clear_metrics_midrun
  import tests_mode_stress_pkg::*; // test_mode_switch_stress

  
  // Simulation-friendly parameters

  localparam int N_TB      = tb_pkg::N;
  localparam int SHIFT_TB  = tb_pkg::SHIFT;
  localparam int LFSR_W_TB = tb_pkg::LFSR_W;

  localparam int FIFO_DEPTH_TB = 4;

  // For simulation, DO NOT use hardware dividers (50_000 and 50_000_000),
  // or you will simulate forever.
  // Override with compile-time defines if you want:
  //   +define+SIM_SAMPLE_DIV=10
  //   +define+SIM_DBG_DIV=200
  `ifndef SIM_SAMPLE_DIV
    localparam int SAMPLE_DIV_TB = 4;
  `else
    localparam int SAMPLE_DIV_TB = `SIM_SAMPLE_DIV;
  `endif

  `ifndef SIM_DBG_DIV
    localparam int DBG_DIV_TB = 200;
  `else
    localparam int DBG_DIV_TB = `SIM_DBG_DIV;
  `endif


  // Interfaces

  board_if b();
  tap_if #(.N(N_TB), .LFSR_W(LFSR_W_TB)) taps();

  
  // Clock generator

  localparam time CLK_HALF = 10ns; // 50 MHz => 20 ns period

  initial begin
    b.CLOCK_50 = 1'b0;
    forever #CLK_HALF b.CLOCK_50 = ~b.CLOCK_50;
  end


  // Power-on init (avoid X-propagation into monitors)

  initial begin
    // Default released state
    b.init_defaults();

    // Assert reset immediately at time 0 to keep everything deterministic.
    b.KEY[0] = 1'b0; // reset asserted (active-low)
    b.KEY[1] = 1'b1; // clear button released
    b.SW     = '0;

    // Hold reset for a few cycles then release.
    // (Tests will typically apply their own reset too.)
    repeat (5) @(posedge b.CLOCK_50);
    b.KEY[0] = 1'b1;
  end


  // DUT instance

  t_recap_demo_top #(
    .N            (N_TB),
    .LFSR_W        (LFSR_W_TB),
    .SAMPLE_DIV    (SAMPLE_DIV_TB),
    .DBG_DIV       (DBG_DIV_TB),
    .SHAPER_SHIFT  (SHIFT_TB),
    .FIFO_DEPTH    (FIFO_DEPTH_TB)
  ) dut (
    .CLOCK_50 (b.CLOCK_50),
    .KEY      (b.KEY),
    .SW       (b.SW),
    .LEDR     (b.LEDR),
    .HEX0     (b.HEX0),
    .HEX1     (b.HEX1),
    .HEX2     (b.HEX2),
    .HEX3     (b.HEX3),
    .HEX4     (b.HEX4),
    .HEX5     (b.HEX5)
  );


  // Monitors / Scoreboards / Coverage


  // Streams + pair domain monitors
  x_stream_monitor #(
    .N      (N_TB),
    .SHIFT  (SHIFT_TB),
    .LFSR_W (LFSR_W_TB)
  ) u_x_mon (taps);

  pair_monitor #(
    .N      (N_TB),
    .LFSR_W (LFSR_W_TB)
  ) u_pair_mon (taps);

  y_stream_monitor #(
    .N      (N_TB),
    .SHIFT  (SHIFT_TB),
    .LFSR_W (LFSR_W_TB),
    .DEPTH  (FIFO_DEPTH_TB)
  ) u_y_mon (taps);

  metrics_monitor #(
    .N      (N_TB),
    .LFSR_W (LFSR_W_TB)
  ) u_met_mon (taps);

  io_monitor #(
    .N      (N_TB),
    .LFSR_W (LFSR_W_TB)
  ) u_io_mon (
    .b (b),
    .t (taps)
  );

  // Scoreboards (algorithm signoff)
  scoreboard_pairs #(
    .N      (N_TB),
    .SHIFT  (SHIFT_TB),
    .LFSR_W (LFSR_W_TB)
  ) u_sb_pairs (taps);

  scoreboard_y_stream #(
    .N      (N_TB),
    .SHIFT  (SHIFT_TB),
    .LFSR_W (LFSR_W_TB),
    .DEPTH  (FIFO_DEPTH_TB)
  ) u_sb_y (taps);

  scoreboard_metrics #(
    .N      (N_TB),
    .LFSR_W (LFSR_W_TB)
  ) u_sb_met (taps);

  // Functional coverage
  cov_phase1 #(
    .N      (N_TB),
    .LFSR_W (LFSR_W_TB),
    .DEPTH  (FIFO_DEPTH_TB)
  ) u_cov (taps);

  // NOTE: Assertions are bound by sva_phase1_bind.sv (no instantiation needed).

  
  // Optional waveform dump

  initial begin
    if ($test$plusargs("VCD")) begin
      $display("[tb_top] VCD enabled -> waves.vcd");
      $dumpfile("waves.vcd");
      $dumpvars(0, tb_top);
    end
  end


  // Test selection and execution

  initial begin : test_select
    string tname;

    // Let everything settle for one delta and one clock edge
    #0;
    @(posedge b.CLOCK_50);

    if ($test$plusargs("LIST_TESTS") || $test$plusargs("HELP")) begin
      $display("\n[tb_top] Available tests via +TEST=<name>:");
      $display("  golden_thresh16      (default signoff; uses x.memh/y.memh/sup.memh/metrics.json)");
      $display("  bypass_lossless      (T=0 / bypass lossless property)");
      $display("  threshold_sweep      (monotonic metrics vs T; usually use model-based scoreboards)");
      $display("  clear_metrics_midrun (press KEY1 mid-run; verify counters reset)");
      $display("  mode_switch_stress   (toggle mode while running; default excludes bypass)");
      $display("\nUseful global knobs:");
      $display("  +TB_VERBOSE, +VCD");
      $display("  +SVA_DISABLE/+SVA_OFF, +COV_DISABLE/+COV_OFF");
      $display("  (See each test file header for its specific plusargs.)\n");
    end

    if (!$value$plusargs("TEST=%s", tname)) begin
      tname = "golden_thresh16";
    end

    $display("[tb_top] Starting TEST='%s'  (SIM_SAMPLE_DIV=%0d SIM_DBG_DIV=%0d)",
             tname, SAMPLE_DIV_TB, DBG_DIV_TB);

    // Construct and run the selected test.
    if ((tname == "golden_thresh16") || (tname == "golden") || (tname == "signoff")) begin
      tests_golden_pkg::test_golden_thresh16 #(N_TB, LFSR_W_TB) t0;
      t0 = new(b, taps, "test_golden_thresh16");
      t0.run();

    end else if ((tname == "bypass_lossless") || (tname == "lossless") || (tname == "t0")) begin
      tests_pkg::test_bypass_lossless #(N_TB, LFSR_W_TB) t1;
      t1 = new(b, taps, "test_bypass_lossless");
      t1.run();

    end else if ((tname == "threshold_sweep") || (tname == "sweep")) begin
      tests_sweep_pkg::test_threshold_sweep #(N_TB, LFSR_W_TB) t2;
      t2 = new(b, taps, "test_threshold_sweep");
      t2.run();

    end else if ((tname == "clear_metrics_midrun") || (tname == "clear_midrun") || (tname == "clear")) begin
      tests_clear_pkg::test_clear_metrics_midrun #(N_TB, LFSR_W_TB) t3;
      t3 = new(b, taps, "test_clear_metrics_midrun");
      t3.run();

    end else if ((tname == "mode_switch_stress") || (tname == "mode_stress") || (tname == "mode_switch")) begin
      tests_mode_stress_pkg::test_mode_switch_stress #(N_TB, LFSR_W_TB) t4;
      t4 = new(b, taps, "test_mode_switch_stress");
      t4.run();

    end else begin
      $fatal(1, "[tb_top] Unknown +TEST='%s'. Run with +LIST_TESTS to see valid names.", tname);
    end
  end

endmodule : tb_top

// Bind tap interface onto the DUT instance inside tb_top
bind tb_top.dut t_recap_tap_bind #(
  .N      (tb_pkg::N),
  .LFSR_W (tb_pkg::LFSR_W)
) u_tap_bind (
  .tap              (tb_top.taps),

  // IMPORTANT: explicitly bind to DUT instance signals
  .clk              (tb_top.dut.CLOCK_50),
  .rst_n            (tb_top.dut.rst_n),

  .clr_metrics_pulse(tb_top.dut.clr_metrics_pulse),
  .mode_sel         (tb_top.dut.mode_sel),
  .force_bypass     (tb_top.dut.force_bypass),
  .thresh8_manual   (tb_top.dut.thresh8_manual),
  .thresh_used      (tb_top.dut.thresh_used),
  .sample_en        (tb_top.dut.sample_en),
  .dbg_tick         (tb_top.dut.dbg_tick),
  .lfsr_rnd         (tb_top.dut.lfsr_rnd),
  .u_noise          (tb_top.dut.u_noise),
  .x_stream         (tb_top.dut.x_stream),
  .pair_valid       (tb_top.dut.pair_valid),
  .x0               (tb_top.dut.x0),
  .x1               (tb_top.dut.x1),
  .pair_out_valid   (tb_top.dut.pair_out_valid),
  .y0               (tb_top.dut.y0),
  .y1               (tb_top.dut.y1),
  .suppressed       (tb_top.dut.suppressed),
  .x0_a             (tb_top.dut.x0_a),
  .x1_a             (tb_top.dut.x1_a),
  .a_tap            (tb_top.dut.a_tap),
  .d_tap            (tb_top.dut.d_tap),
  .abs_d_tap        (tb_top.dut.abs_d_tap),
  .y_valid          (tb_top.dut.y_valid),
  .y_out            (tb_top.dut.y_out),
  .total_pairs      (tb_top.dut.total_pairs),
  .suppressed_pairs (tb_top.dut.suppressed_pairs),
  .sum_abs_err      (tb_top.dut.sum_abs_err),
  .sum_sq_err       (tb_top.dut.sum_sq_err),
  .alive            (tb_top.dut.alive),
  .suppressed_last  (tb_top.dut.suppressed_last),
  .dbg_word         (tb_top.dut.dbg_word),
  .dbg_word_lat     (tb_top.dut.dbg_word_lat),
  .ledr_lat         (tb_top.dut.ledr_lat)
);`default_nettype wire

