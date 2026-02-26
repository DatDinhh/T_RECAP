`timescale 1ns/1ps
`default_nettype none

// Arizona State University 
// Capstone Senior Project
// Sigma Force
// Dat Dinh, Dat Huynh, Paul Applebee, Kyung Jae Son
// test_base.sv
//
// Non-UVM, class-based "base test" for T-RECAP Phase 1 DV.
//
// This file provides a reusable base class that:
//   - Connects to board_if (driving KEY/SW) and tap_if (observing DUT internals)
//   - Owns a board_driver instance (from board_driver_pkg)
//   - Implements a standard run flow: init -> reset -> (optional sweep) trials -> report -> finish
//   - Provides robust wait/timeout behavior to avoid "hang forever" failures
//   - Records per-trial results (DUT metrics) for quick sanity review
//
// Intended usage in tb_top.sv (example):
//
//   import tb_pkg::*;
//   import board_driver_pkg::*;
//   import test_pkg::*;
//
//   board_if b();
//   tap_if #(.N(N), .LFSR_W(LFSR_W)) taps();
//
//   // ... instantiate DUT + bind taps ...
//
//   initial begin
//     test_base #(N, LFSR_W) t0 = new(b, taps, "t0");
//     t0.run();
//   end
//
// Key defaults (match provided golden artifacts):
//   - threshold = 16
//   - pairs_per_trial = 5000   (=> 10000 samples)
//   - mode = MAN_ABS (SW[9:8]=2'b10)
//
// Plusargs (recommended):
//
//   +TB_VERBOSE
//   +TB_KPAIRS=<int>            (default 5000)
//   +TB_THRESH=<0..255>         (default 16)
//   +TB_MODE=<0..3>             (default 2: MAN_ABS)
//   +TB_TIMEOUT_CLKS=<int>      (default driver default = 2,000,000)
//   +TB_GLOBAL_TIMEOUT_CLKS=<int>   (default 0 = disabled)
//
// Sweep controls (optional):
//   +TB_SWEEP                      (enable sweep mode)
//   +TB_THRESH_START=<int>         (implies sweep)
//   +TB_THRESH_END=<int>           (implies sweep)
//   +TB_THRESH_STEP=<int>          (default 1)
//   +TB_RESET_BETWEEN_TRIALS       (default ON when sweep enabled)
//   +TB_NO_RESET_BETWEEN_TRIALS
//   +TB_CLEAR_BETWEEN_TRIALS       (default OFF; only meaningful without reset)
//   +TB_NO_CLEAR_BETWEEN_TRIALS
//
// Notes / truth (important):
//   - The provided x.memh/y.memh/sup.memh/metrics.json correspond to THRESH=16
//     with SEED=0xACE1, SHIFT=3, N=12, NSAMP=10000.
//   - If you sweep thresholds while memh-based scoreboards are enabled,
//     they WILL fail unless you switch those scoreboards to model-based mode.


`ifndef TEST_BASE_SV
`define TEST_BASE_SV

package test_pkg;

  import tb_pkg::*;
  import board_driver_pkg::*;


  // Base test class

  class test_base #(int N = tb_pkg::N, int LFSR_W = tb_pkg::LFSR_W);

    // Virtual interfaces
    virtual board_if.tb                 b;
    virtual tap_if     t;

    // Driver (front panel agent)
    board_driver #(N, LFSR_W)           drv;

    // Identity / logging
    string name;
    bit    verbose;


    // Primary config knobs

    int unsigned pairs_per_trial;       // K pairs per trial
    logic [7:0]  thresh8;               // threshold switch value
    logic [1:0]  mode;                  // SW[9:8] mode

    int unsigned reset_hold_cycles;     // KEY0 hold time in clocks

    // Timeouts
    int unsigned timeout_clks;          // per-wait timeout override (0 => driver default)
    int unsigned global_timeout_clks;   // global watchdog (0 => disabled)

    // Drain behavior after each trial
    bit drain_y_stream;


    // Sweep configuration

    bit do_sweep;
    int unsigned thresh_start;
    int unsigned thresh_end;
    int unsigned thresh_step;

    bit reset_between_trials;
    bit clear_between_trials;


    // Per-trial results storage

    typedef struct {
      int unsigned  trial_id;
      logic [1:0]   mode;
      logic [7:0]   thresh8;
      int unsigned  pairs_req;

      ui64_t        dut_total_pairs;
      ui64_t        dut_suppressed_pairs;
      ui64_t        dut_sum_abs_err;
      ui64_t        dut_sum_sq_err;

      real          suppressed_ratio;
      longint unsigned end_time;
    } trial_result_t;

    trial_result_t results[$];


    // Internal bookkeeping

    bit running;

    // plusarg-captured driver timeout override (applied after drv constructed)
    bit          have_drv_timeout_override;
    int unsigned drv_timeout_override;


    // Constructor

    function new(
      virtual board_if.tb             b,
      virtual tap_if t,
      string                          name = "test_base"
    );
      this.b    = b;
      this.t    = t;
      this.name = name;

      this.verbose = ($test$plusargs("TB_VERBOSE") != 0);

      // Defaults: match provided golden artifacts
      this.pairs_per_trial   = 5000;
      this.thresh8           = 8'd16;
      this.mode              = MODE_MAN_ABS;

      this.reset_hold_cycles = 5;

      this.timeout_clks       = 0; // 0 => use driver default
      this.global_timeout_clks= 0; // disabled

      this.drain_y_stream = 1'b1;

      // Sweep defaults: OFF
      this.do_sweep           = 1'b0;
      this.thresh_start       = this.thresh8;
      this.thresh_end         = this.thresh8;
      this.thresh_step        = 1;

      // For sweeps, the *correct* thing (for repeatability) is to reset between trials.
      this.reset_between_trials = 1'b0;
      this.clear_between_trials = 1'b0;

      this.have_drv_timeout_override = 1'b0;
      this.drv_timeout_override      = 0;

      this.running = 1'b0;

      // Parse plusargs BEFORE building the driver
      parse_plusargs();

      // Create the driver now that config is known
      this.drv = new(b, t, {name, ".drv"});
      this.drv.verbose = this.verbose;
      if (have_drv_timeout_override) begin
        this.drv.default_timeout_clks = drv_timeout_override; // 0 allowed => disables timeouts inside driver waits
      end

      if (this.do_sweep) begin
        // If user didn't explicitly choose, default to reset between trials for sweep runs.
        // (You can turn it off with +TB_NO_RESET_BETWEEN_TRIALS.)
        if (!$test$plusargs("TB_NO_RESET_BETWEEN_TRIALS") &&
            !$test$plusargs("TB_RESET_BETWEEN_TRIALS")) begin
          this.reset_between_trials = 1'b1;
        end
      end
    endfunction


    // Utilities

    function automatic string mode_to_string(input logic [1:0] m);
      unique case (m)
        MODE_BYPASS   : mode_to_string = "BYPASS(00)";
        MODE_MAN_SUPP : mode_to_string = "MAN_SUPP(01)";
        MODE_MAN_ABS  : mode_to_string = "MAN_ABS(10)";
        MODE_MAN_SQ   : mode_to_string = "MAN_SQ(11)";
        default                 : mode_to_string = $sformatf("0b%0b", m);
      endcase
    endfunction

    function automatic bit file_exists(input string path);
      int fd;
      begin
        fd = $fopen(path, "r");
        if (fd == 0) file_exists = 1'b0;
        else begin
          file_exists = 1'b1;
          $fclose(fd);
        end
      end
    endfunction

    
    // Plusargs parsing

    function void parse_plusargs();
      int unsigned tmp;

      // pairs/threshold/mode
      void'($value$plusargs("TB_KPAIRS=%d", pairs_per_trial));

      if ($value$plusargs("TB_THRESH=%d", tmp)) begin
        if (tmp > 255) tmp = 255;
        thresh8 = tmp[7:0];
      end

      if ($value$plusargs("TB_MODE=%d", tmp)) begin
        mode = tmp[1:0];
      end

      // reset hold
      void'($value$plusargs("TB_RESET_HOLD_CYCLES=%d", reset_hold_cycles));

      // timeouts
      void'($value$plusargs("TB_TIMEOUT_CLKS=%d", timeout_clks));

      if ($value$plusargs("TB_DRIVER_TIMEOUT_CLKS=%d", tmp)) begin
        have_drv_timeout_override = 1'b1;
        drv_timeout_override      = tmp; // allow 0 to disable
      end else if ($value$plusargs("TB_TIMEOUT_DEFAULT=%d", tmp)) begin
        // legacy alias
        have_drv_timeout_override = 1'b1;
        drv_timeout_override      = tmp;
      end

      void'($value$plusargs("TB_GLOBAL_TIMEOUT_CLKS=%d", global_timeout_clks));

      // drain toggle
      if ($test$plusargs("TB_NO_DRAIN_Y")) drain_y_stream = 1'b0;
      if ($test$plusargs("TB_DRAIN_Y"))    drain_y_stream = 1'b1;

      // Sweep enables
      if ($test$plusargs("TB_SWEEP")) do_sweep = 1'b1;

      if ($value$plusargs("TB_THRESH_START=%d", tmp)) begin
        do_sweep     = 1'b1;
        thresh_start = tmp;
      end
      if ($value$plusargs("TB_THRESH_END=%d", tmp)) begin
        do_sweep   = 1'b1;
        thresh_end = tmp;
      end
      if ($value$plusargs("TB_THRESH_STEP=%d", tmp)) begin
        do_sweep   = 1'b1;
        thresh_step= (tmp == 0) ? 1 : tmp;
      end

      // Sweep reset/clear behavior
      if ($test$plusargs("TB_RESET_BETWEEN_TRIALS"))    reset_between_trials = 1'b1;
      if ($test$plusargs("TB_NO_RESET_BETWEEN_TRIALS")) reset_between_trials = 1'b0;

      if ($test$plusargs("TB_CLEAR_BETWEEN_TRIALS"))    clear_between_trials = 1'b1;
      if ($test$plusargs("TB_NO_CLEAR_BETWEEN_TRIALS")) clear_between_trials = 1'b0;

      if (do_sweep) begin
        // clamp & sanitize sweep range into [0..255]
        if (thresh_start > 255) thresh_start = 255;
        if (thresh_end   > 255) thresh_end   = 255;

        // If user only specified start, default end = start
        // If user only specified end, default start = current thresh8
        if (!$value$plusargs("TB_THRESH_START=%d", tmp) && $value$plusargs("TB_THRESH_END=%d", tmp)) begin
          thresh_start = thresh8;
        end
        if ($value$plusargs("TB_THRESH_START=%d", tmp) && !$value$plusargs("TB_THRESH_END=%d", tmp)) begin
          thresh_end = thresh_start;
        end
      end
    endfunction


    // Run flow

    task automatic run();
      if (running) begin
        $display("[%s] NOTE: run() called but already running.", name);
        return;
      end
      running = 1'b1;

      banner();

      // global watchdog (optional)
      if (global_timeout_clks != 0) begin
        fork
          global_watchdog();
        join_none
      end

      // Standard phases
      build();
      reset_phase();
      body();
      post_run();

      $display("[%s] DONE. (If you see this and no $fatal happened, your DV checks passed for this run.)", name);
      $finish;
    endtask

    // Build: initialize board inputs
    virtual task automatic build();
      drv.init_defaults();
      // Put mode/threshold into a known state BEFORE reset release (board-like behavior)
      drv.set_mode_and_threshold(mode, thresh8);
      if (verbose) $display("[%s] build(): init defaults + set mode/thresh before reset.", name);
    endtask

    // Reset: apply reset and ensure taps see it
    virtual task automatic reset_phase();
      if (verbose) $display("[%s] reset_phase(): applying reset (hold_cycles=%0d)", name, reset_hold_cycles);
      drv.apply_reset(reset_hold_cycles);

      // Sanity: confirm taps show reset released
      if (t != null) begin
        if (t.rst_n !== 1'b1) begin
          $fatal(1, "[%s] Reset deasserted on board but tap rst_n is not 1 (rst_n=%b).", name, t.rst_n);
        end
      end
    endtask

    // Main body (override in derived tests)
    virtual task automatic body();
      if (do_sweep) begin
        run_threshold_sweep();
      end else begin
        run_trial(0, mode, thresh8, pairs_per_trial);
      end
    endtask

    // Post-run: print results table
    virtual task automatic post_run();
      print_results();
      if (verbose) begin
        // quick last metrics print (from taps)
        if (t != null) begin
          $display("[%s] Final DUT metrics: total_pairs=%0d suppressed_pairs=%0d sum_abs_err=%0d sum_sq_err=%0d",
                   name, t.total_pairs, t.suppressed_pairs, t.sum_abs_err, t.sum_sq_err);
        end
      end
    endtask


    // Watchdog

    task automatic global_watchdog();
      int unsigned w;
      begin
        w = 0;
        while (w < global_timeout_clks) begin
          @(posedge b.CLOCK_50);
          w++;
        end
        $fatal(1, "[%s] GLOBAL TIMEOUT: exceeded %0d CLOCK_50 cycles.", name, global_timeout_clks);
      end
    endtask


    // Trial helpers

    task automatic run_threshold_sweep();
      int unsigned tid;
      int unsigned T;
      begin
        tid = 0;

        if (thresh_step == 0) thresh_step = 1;

        // Truthful warning: memh goldens are for THRESH=16
        if (file_exists("y.memh") && ((thresh_start != 16) || (thresh_end != 16))) begin
          $display("[%s] WARNING: y.memh exists but you are sweeping thresholds [%0d..%0d].", name, thresh_start, thresh_end);
          $display("[%s]          If memh-based scoreboards are enabled, they will fail (goldens are THRESH=16).", name);
          $display("[%s]          Switch scoreboards to model mode (e.g. +Y_SB_MODE=model_pairs +PAIR_SB_MODE=model).", name);
        end

        // Iterate inclusive; supports start > end by swapping
        if (thresh_start <= thresh_end) begin
          for (T = thresh_start; T <= thresh_end; T += thresh_step) begin
            run_trial(tid, mode, T[7:0], pairs_per_trial);
            tid++;
          end
        end else begin
          // descending sweep
          for (T = thresh_start; T >= thresh_end; T -= thresh_step) begin
            run_trial(tid, mode, T[7:0], pairs_per_trial);
            tid++;
            if (T < thresh_step) break; // prevent underflow
          end
        end
      end
    endtask

    task automatic run_trial(
      input int unsigned trial_id,
      input logic [1:0]  trial_mode,
      input logic [7:0]  trial_thresh8,
      input int unsigned kpairs
    );
      trial_result_t r;
      ui64_t tp, sp, abs_e, sq_e;

      begin
        $display("\n[%s] ---- TRIAL %0d ---- mode=%s thresh=%0d kpairs=%0d",
                 name, trial_id, mode_to_string(trial_mode), trial_thresh8, kpairs);

        // Either reset or just clear metrics between trials
        if ((trial_id == 0) || reset_between_trials) begin
          drv.set_mode_and_threshold(trial_mode, trial_thresh8);
          drv.apply_reset(reset_hold_cycles);
        end else begin
          drv.set_mode_and_threshold(trial_mode, trial_thresh8);
          @(posedge b.CLOCK_50);
          if (clear_between_trials) begin
            drv.press_clear_metrics(1);
          end
        end

        // Allow one sample tick to start stream (helps avoid "startup transient" edge cases)
        if (t != null) begin
          drv.wait_sample_tick(timeout_clks);
        end else begin
          @(posedge b.CLOCK_50);
        end

        // Run K pairs
        drv.run_pairs(kpairs, timeout_clks, drain_y_stream);

        // Give one more clock for counters / debug to settle
        @(posedge b.CLOCK_50);

        // Capture metrics from taps
        if (t == null) begin
          $fatal(1, "[%s] No tap_if connected; cannot read metrics for trial.", name);
        end

        tp    = ui64_t'(t.total_pairs);
        sp    = ui64_t'(t.suppressed_pairs);
        abs_e = ui64_t'(t.sum_abs_err);
        sq_e  = ui64_t'(t.sum_sq_err);

        $display("[%s] Trial %0d DUT metrics: total_pairs=%0d suppressed_pairs=%0d (ratio=%0.5f) sum_abs_err=%0d sum_sq_err=%0d",
                 name, trial_id, tp, sp, (tp!=0)?(real'(sp)/real'(tp)):0.0, abs_e, sq_e);

        // Strong sanity: if bypass mode OR threshold_used==0 then errors must be 0 and suppressed must be 0.
        // (This is the algorithm spec's required property.)
        if ((trial_mode == MODE_BYPASS) || (t.thresh_used == '0)) begin
          if (sp != 0 || abs_e != 0 || sq_e != 0) begin
            $fatal(1, "[%s] Sanity FAIL for T=0/bypass: expected (sp,abs,sq)=(0,0,0) but got (%0d,%0d,%0d)",
                   name, sp, abs_e, sq_e);
          end
        end

        // Fill result record
        r.trial_id            = trial_id;
        r.mode                = trial_mode;
        r.thresh8             = trial_thresh8;
        r.pairs_req           = kpairs;

        r.dut_total_pairs     = tp;
        r.dut_suppressed_pairs= sp;
        r.dut_sum_abs_err     = abs_e;
        r.dut_sum_sq_err      = sq_e;
        r.suppressed_ratio    = (tp != 0) ? (real'(sp) / real'(tp)) : 0.0;
        r.end_time            = $time;

        results.push_back(r);

        // Useful consistency check: total_pairs should be kpairs (unless you cleared metrics mid-trial)
        if (tp != kpairs) begin
          $display("[%s] NOTE: total_pairs (%0d) != requested kpairs (%0d).", name, tp, kpairs);
          $display("[%s]       If you used clr_metrics_pulse during the trial, this is expected.", name);
        end
      end
    endtask


    // Reporting

    task automatic print_results();
      begin
        if (results.size() == 0) begin
          $display("[%s] No trial results recorded.", name);
          return;
        end

        $display("\n[%s] ===== TRIAL SUMMARY =====", name);
        $display("[%s]   id | mode         | thresh | kpairs | dut_tp | dut_sp | sp_ratio  | abs_err | sq_err | end_time", name);
        $display("[%s]  ----+--------------+--------+--------+--------+--------+----------+---------+--------+---------", name);

        foreach (results[i]) begin
          $display("[%s]  %3d | %-12s | %6d | %6d | %6d | %6d | %0.6f | %7d | %6d | %0t",
                   name,
                   results[i].trial_id,
                   mode_to_string(results[i].mode),
                   results[i].thresh8,
                   results[i].pairs_req,
                   results[i].dut_total_pairs,
                   results[i].dut_suppressed_pairs,
                   results[i].suppressed_ratio,
                   results[i].dut_sum_abs_err,
                   results[i].dut_sum_sq_err,
                   results[i].end_time);
        end
        $display("[%s] ===========================\n", name);
      end
    endtask

    // Banner

    task automatic banner();
      begin
        $display("\n============================================================");
        $display("[%s] T-RECAP Phase-1 Base Test", name);
        $display("  N=%0d LFSR_W=%0d", N, LFSR_W);
        $display("  mode=%s  thresh=%0d  pairs_per_trial=%0d", mode_to_string(mode), thresh8, pairs_per_trial);
        $display("  do_sweep=%0d  reset_between_trials=%0d  clear_between_trials=%0d", do_sweep, reset_between_trials, clear_between_trials);
        if (do_sweep) begin
          $display("  sweep: start=%0d end=%0d step=%0d", thresh_start, thresh_end, thresh_step);
        end
        $display("  reset_hold_cycles=%0d  timeout_clks(override)=%0d  drv_default_timeout=%0d  global_timeout=%0d",
                 reset_hold_cycles, timeout_clks,
                 (have_drv_timeout_override ? drv_timeout_override : drv.default_timeout_clks),
                 global_timeout_clks);
        $display("  drain_y_stream=%0d  verbose=%0d", drain_y_stream, verbose);

        // Truth about the provided golden artifacts.
        if (file_exists("metrics.json")) begin
          $display("  NOTE: metrics.json present. The provided golden set corresponds to THRESH=16 (pairs=5000).");
        end
        $display("============================================================\n");
      end
    endtask

  endclass : test_base

endpackage : test_pkg

`endif // TEST_BASE_SV

`default_nettype wire
