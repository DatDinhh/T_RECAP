`timescale 1ns/1ps
`default_nettype none

// Arizona State University 
// Capstone Senior Project
// Sigma Force
// Dat Dinh, Dat Huynh, Paul Applebee, Kyung Jae Son
// test_bypass_lossless.sv
//
// Directed test: Lossless property when threshold T = 0.
//
// Spec:
//   If T = 0 then |d| < 0 is never true => d' = d for all pairs,
//   so y0=x0 and y1=x1 for every pair, and therefore
//     suppressed_pairs = 0
//     sum_abs_err      = 0
//     sum_sq_err       = 0
//
// This test exercises that property in TWO practical ways:
//
//   Case A (required): BYPASS mode (SW[9:8]=00), where the DUT forces thresh_used=0
//          regardless of SW[7:0]. We intentionally set SW[7:0] to a NONZERO value
//          to prove thresh_used still becomes 0.
//
//   Case B (optional): Manual mode (default MAN_ABS) with SW[7:0]=0, which also
//          yields thresh_used=0.
//
// It performs BOTH:
//   - pair-by-pair checks: suppressed==0 and y0==x0_a, y1==x1_a
//   - end-of-trial metrics checks: (tp,sp,abs,sq) = (K,0,0,0)
//
// IMPORTANT (truth, no sugarcoating):
//   If you compile the memh-based scoreboards/monitors and you have y.memh/sup.memh
//   present, their defaults likely select MEMH checking (which was generated for
//   THRESH=16, not THRESH=0). That will FAIL this test unless you override them to
//   model/pairs mode via plusargs, e.g.:
//     +PAIR_SB_MODE=model
//     +Y_SB_MODE=model_pairs
//     +Y_MON_MODE=pairs
//
// Compile dependency:
//   - test_base.sv (package test_pkg)
//   - board_driver.sv (package board_driver_pkg)


`ifndef TEST_BYPASS_LOSSLESS_SV
`define TEST_BYPASS_LOSSLESS_SV

package tests_pkg;

  import tb_pkg::*;
  import board_driver_pkg::*;
  import test_pkg::*;

  class test_bypass_lossless #(int N = tb_pkg::N, int LFSR_W = tb_pkg::LFSR_W)
    extends test_pkg::test_base #(N, LFSR_W);


    // Local knobs (plusargs)

    bit          also_manual_T0;
    bit          do_pairwise_checks;
    int unsigned check_first_pairs;  // 0 => check all pairs

    logic [7:0]  bypass_sw_thresh8;  // value we write onto SW[7:0] in bypass case

    // Which manual mode to use for Case B (still T=0).
    logic [1:0]  manual_mode_caseB;


    // Constructor

    function new(
      virtual board_if.tb             b,
      virtual tap_if #(N, LFSR_W).mon t,
      string                          name = "test_bypass_lossless"
    );
      super.new(b, t, name);

      // Force this test to be non-sweep.
      this.do_sweep = 1'b0;

      // Default behavior
      also_manual_T0      = 1'b1;
      do_pairwise_checks  = 1'b1;
      check_first_pairs   = 0;          // check all pairs by default
      bypass_sw_thresh8   = 8'hA5;      // intentionally NONZERO
      manual_mode_caseB   = MODE_MAN_ABS;

      // Parse test-specific plusargs
      if ($test$plusargs("BL_NO_MANUAL_T0")) also_manual_T0 = 1'b0;
      if ($test$plusargs("BL_MANUAL_T0"))    also_manual_T0 = 1'b1;

      if ($test$plusargs("BL_NO_PAIRWISE"))  do_pairwise_checks = 1'b0;
      if ($test$plusargs("BL_PAIRWISE"))     do_pairwise_checks = 1'b1;

      void'($value$plusargs("BL_CHECK_FIRST_PAIRS=%d", check_first_pairs));

      begin
        int unsigned tmp;
        if ($value$plusargs("BL_BYPASS_SW_THRESH=%d", tmp)) begin
          if (tmp > 255) tmp = 255;
          bypass_sw_thresh8 = tmp[7:0];
        end
        if ($value$plusargs("BL_MANUAL_MODE=%d", tmp)) begin
          manual_mode_caseB = tmp[1:0];
        end
      end

      // Make the base class "default" configuration match Case A (so build/reset are consistent)
      this.mode   = MODE_BYPASS;
      this.thresh8= bypass_sw_thresh8;

      if (this.verbose) begin
        $display("[%s] cfg: pairs_per_trial=%0d reset_hold=%0d timeout_clks=%0d drain_y=%0d",
                 this.name, this.pairs_per_trial, this.reset_hold_cycles, this.timeout_clks, this.drain_y_stream);
        $display("[%s] cfg: also_manual_T0=%0d do_pairwise_checks=%0d check_first_pairs=%0d bypass_sw_thresh8=%0d manual_mode_caseB=%0b",
                 this.name, also_manual_T0, do_pairwise_checks, check_first_pairs, bypass_sw_thresh8, manual_mode_caseB);
      end
    endfunction


    // Override: body()

    virtual task automatic body();
      // Case A: BYPASS mode (thresh_used forced to 0 even if SW[7:0] != 0)
      run_lossless_case(
        0,
        "CASE_A_BYPASS",
        MODE_BYPASS,
        bypass_sw_thresh8,
        pairs_per_trial,
        /*expect_force_bypass*/ 1'b1
      );

      // Case B: Manual mode with SW threshold = 0 (optional)
      if (also_manual_T0) begin
        run_lossless_case(
          1,
          "CASE_B_MANUAL_T0",
          manual_mode_caseB,
          8'd0,
          pairs_per_trial,
          /*expect_force_bypass*/ 1'b0
        );
      end
    endtask


    // Helper: one lossless case

    task automatic run_lossless_case(
      input int unsigned trial_id,
      input string       tag,
      input logic [1:0]  trial_mode,
      input logic [7:0]  trial_thresh8,
      input int unsigned kpairs,
      input bit          expect_force_bypass
    );
      ui64_t tp, sp, abs_e, sq_e;

      begin
        $display("\n[%s] ---- %s (trial %0d) ----", name, tag, trial_id);
        $display("[%s] mode=%s  SW_thresh=%0d  kpairs=%0d",
                 name, mode_to_string(trial_mode), trial_thresh8, kpairs);

        // Apply reset for a clean epoch
        drv.set_mode_and_threshold(trial_mode, trial_thresh8);
        drv.apply_reset(reset_hold_cycles);

        // Prime a couple sample ticks (settles the pipeline)
        drv.wait_sample_tick(timeout_clks);
        drv.wait_sample_tick(timeout_clks);

        // Pair-by-pair checks
        for (int unsigned k = 0; k < kpairs; k++) begin
          drv.wait_pair_out_valid(timeout_clks);

          if (do_pairwise_checks && ((check_first_pairs == 0) || (k < check_first_pairs))) begin
            check_lossless_pair(tag, k, trial_mode, expect_force_bypass);
          end
        end

        // Drain the y-stream (conservative) so stream-level scoreboards don't false-fail
        if (drain_y_stream) begin
          drv.wait_sample_tick(timeout_clks);
          drv.wait_sample_tick(timeout_clks);
          @(posedge t.clk);
        end

        // Let NBA updates land before reading counters
        #0;

        // End-of-trial metrics checks
        tp    = ui64_t'(t.total_pairs);
        sp    = ui64_t'(t.suppressed_pairs);
        abs_e = ui64_t'(t.sum_abs_err);
        sq_e  = ui64_t'(t.sum_sq_err);

        $display("[%s] %s metrics: total_pairs=%0d suppressed_pairs=%0d sum_abs_err=%0d sum_sq_err=%0d",
                 name, tag, tp, sp, abs_e, sq_e);

        if (tp != kpairs) begin
          $fatal(1, "[%s] %s FAIL: total_pairs (%0d) != kpairs (%0d).", name, tag, tp, kpairs);
        end
        if (sp != 0) begin
          $fatal(1, "[%s] %s FAIL: suppressed_pairs=%0d (expected 0 for T=0).", name, tag, sp);
        end
        if (abs_e != 0) begin
          $fatal(1, "[%s] %s FAIL: sum_abs_err=%0d (expected 0 for T=0).", name, tag, abs_e);
        end
        if (sq_e != 0) begin
          $fatal(1, "[%s] %s FAIL: sum_sq_err=%0d (expected 0 for T=0).", name, tag, sq_e);
        end

        // Additionally ensure thresh_used is zero at end (it should be for T=0 case)
        if (t.thresh_used !== '0) begin
          $fatal(1, "[%s] %s FAIL: thresh_used is not 0 at end-of-trial (thresh_used=%0d).", name, tag, t.thresh_used);
        end

        $display("[%s] %s PASS (lossless verified).", name, tag);

        // Record a result row using base-class data structure
        // (overwrites base semantics slightly: we always expect perfect lossless)
        begin
          trial_result_t r;
          r.trial_id            = trial_id;
          r.mode                = trial_mode;
          r.thresh8             = trial_thresh8;
          r.pairs_req           = kpairs;

          r.dut_total_pairs     = tp;
          r.dut_suppressed_pairs= sp;
          r.dut_sum_abs_err     = abs_e;
          r.dut_sum_sq_err      = sq_e;
          r.suppressed_ratio    = 0.0;
          r.end_time            = $time;

          results.push_back(r);
        end
      end
    endtask


    // Pair-level lossless check

    task automatic check_lossless_pair(
      input string      tag,
      input int unsigned k,
      input logic [1:0] trial_mode,
      input bit         expect_force_bypass
    );
      si64_t x0, x1, y0, y1;
      begin
        // Must be in the T=0 regime
        if (t.thresh_used !== '0) begin
          $fatal(1, "[%s] %s k=%0d FAIL: thresh_used=%0d (expected 0).", name, tag, k, t.thresh_used);
        end

        // force_bypass should only be asserted in BYPASS mode
        if (t.force_bypass !== expect_force_bypass) begin
          $fatal(1, "[%s] %s k=%0d FAIL: force_bypass=%0d expected=%0d (trial_mode=%0b).",
                 name, tag, k, t.force_bypass, expect_force_bypass, trial_mode);
        end

        // Suppression must never happen if T=0
        if (t.suppressed !== 1'b0) begin
          $fatal(1, "[%s] %s k=%0d FAIL: suppressed asserted (abs_d=%0d).", name, tag, k, t.abs_d_tap);
        end

        // Reconstruction must be exact: y == x (aligned)
        x0 = si64_t'($signed(t.x0_a));
        x1 = si64_t'($signed(t.x1_a));
        y0 = si64_t'($signed(t.y0));
        y1 = si64_t'($signed(t.y1));

        if (y0 != x0) begin
          $fatal(1, "[%s] %s k=%0d FAIL: y0!=x0 (x0=%s y0=%s).", name, tag, k, fmt_si64(x0), fmt_si64(y0));
        end
        if (y1 != x1) begin
          $fatal(1, "[%s] %s k=%0d FAIL: y1!=x1 (x1=%s y1=%s).", name, tag, k, fmt_si64(x1), fmt_si64(y1));
        end
      end
    endtask

  endclass : test_bypass_lossless

endpackage : tests_pkg

`endif // TEST_BYPASS_LOSSLESS_SV

`default_nettype wire




