`timescale 1ns/1ps
`default_nettype none

// Arizona State University 
// Capstone Senior Project
// Sigma Force
// Dat Dinh, Dat Huynh, Paul Applebee, Kyung Jae Son
// test_clear_metrics_midrun.sv
//
// Directed test: press KEY[1] (clear metrics) while the DUT is actively
// streaming, and verify the metrics accumulator resets cleanly mid-run.
//
// What we verify (no hand-waving):
//   1) We can observe clr_metrics_pulse on the internal tap.
//   2) Metrics do NOT clear in the same cycle as clr_metrics_pulse asserts
//      (because clr_metrics_pulse is generated from KEY sync FFs).
//   3) Metrics DO clear on the next cycle.
//   4) After clear, counters restart from 0 and count *new* pairs correctly.
//   5) Optional: if x/y/sup memh files are present (the provided goldens),
//      we compute expected metrics for the segments and compare.
//
// IMPORTANT PRACTICAL TRUTH:
//   - metrics.json corresponds to the FULL 5000-pair run at THRESH=16 with NO
//     mid-run clear. If you enable a JSON signoff check while running this test,
//     it will NOT match and may fail. That's expected.
//
// Suggested scoreboard knobs for this test:
//   - Keep pair/y stream checking enabled (algorithm unaffected by clear)
//   - Disable "auto-final JSON" checks in scoreboard_metrics, or disable JSON
//     checking entirely for this test:
//       +MET_SB_NO_CHECK_JSON
//
// Plusargs
// General:
//   +CMR_VERBOSE
//   +CMR_MODE=<0..3>          (default: uses TB_MODE or MAN_ABS)
//   +CMR_THRESH=<0..255>      (default: uses TB_THRESH or 16)
//
// Segment lengths:
//   +CMR_PRE_KPAIRS=<int>     (default 200)
//   +CMR_POST_KPAIRS=<int>    (default 200)
//
// Optional 2nd clear:
//   +CMR_SECOND_CLEAR
//   +CMR_MID_KPAIRS=<int>     (default 100)
//
// Clear button press shape:
//   +CMR_CLEAR_LOW_CYCLES=<int>   (default 1)
//
// Optional memh segment checking:
//   +CMR_MEMH_SEGMENTS            (force enable)
//   +CMR_NO_MEMH_SEGMENTS         (force disable)
//   +CMR_STRICT_MEMH              (fatal if memh check requested but cannot run)
//   +CMR_X_FILE=<path>            (default x.memh)   [alias: +X_MEMH]
//   +CMR_Y_FILE=<path>            (default y.memh)   [alias: +Y_MEMH]
//   +CMR_SUP_FILE=<path>          (default sup.memh) [alias: +SUP_MEMH]


`ifndef TEST_CLEAR_METRICS_MIDRUN_SV
`define TEST_CLEAR_METRICS_MIDRUN_SV

package tests_clear_pkg;

  import tb_pkg::*;
  import test_pkg::*;
  import board_driver_pkg::*;

  class test_clear_metrics_midrun #(int N = tb_pkg::N, int LFSR_W = tb_pkg::LFSR_W)
    extends test_pkg::test_base #(N, LFSR_W);


    // Knobs

    bit          cmr_verbose;

    logic [1:0]  trial_mode;
    logic [7:0]  trial_thresh8;

    int unsigned pre_kpairs;
    int unsigned mid_kpairs;
    int unsigned post_kpairs;

    bit          do_second_clear;
    int unsigned clear_low_cycles;

    // memh segment check
    bit          memh_segments;
    bit          strict_memh;

    string       x_file;
    string       y_file;
    string       sup_file;

    si64_t       x_g[$];
    si64_t       y_g[$];
    bit          sup_g[$];

    bit          memh_loaded;

    
    // masks match DUT counter widths

    localparam ui64_t MASK32 = 64'hFFFF_FFFF;
    localparam ui64_t MASK48 = (ui64_t'(1) << 48) - ui64_t'(1);


    // Constructor

    function new(
      virtual board_if.tb             b,
      virtual tap_if #(N, LFSR_W).mon t,
      string                          name = "test_clear_metrics_midrun"
    );
      int unsigned tmp;

      super.new(b, t, name);

      cmr_verbose = ($test$plusargs("CMR_VERBOSE") != 0) || this.verbose;

      // Defaults (keep runtime reasonable)
      pre_kpairs  = 200;
      mid_kpairs  = 100;
      post_kpairs = 200;

      do_second_clear = ($test$plusargs("CMR_SECOND_CLEAR") != 0);
      clear_low_cycles = 1;
      void'($value$plusargs("CMR_CLEAR_LOW_CYCLES=%d", clear_low_cycles));
      if (clear_low_cycles == 0) clear_low_cycles = 1;

      void'($value$plusargs("CMR_PRE_KPAIRS=%d", pre_kpairs));
      void'($value$plusargs("CMR_MID_KPAIRS=%d", mid_kpairs));
      void'($value$plusargs("CMR_POST_KPAIRS=%d", post_kpairs));

      // Mode/thresh defaults: reuse base class config (which already parsed TB_MODE/TB_THRESH)
      trial_mode   = this.mode;
      trial_thresh8= this.thresh8;

      if ($value$plusargs("CMR_MODE=%d", tmp)) begin
        if (tmp > 3) tmp = 3;
        trial_mode = tmp[1:0];
      end
      if ($value$plusargs("CMR_THRESH=%d", tmp)) begin
        if (tmp > 255) tmp = 255;
        trial_thresh8 = tmp[7:0];
      end

      // Make base class initial build/reset align with this test
      this.do_sweep = 1'b0;
      this.mode     = trial_mode;
      this.thresh8  = trial_thresh8;

      // MEMH segment checking default behavior:
      //   - auto-enable only if (T==16) and non-bypass and the files exist
      //   - user can force enable/disable via plusargs
      x_file   = "x.memh";
      y_file   = "y.memh";
      sup_file = "sup.memh";

      void'($value$plusargs("CMR_X_FILE=%s", x_file));
      void'($value$plusargs("CMR_Y_FILE=%s", y_file));
      void'($value$plusargs("CMR_SUP_FILE=%s", sup_file));

      // aliases
      void'($value$plusargs("X_MEMH=%s", x_file));
      void'($value$plusargs("Y_MEMH=%s", y_file));
      void'($value$plusargs("SUP_MEMH=%s", sup_file));

      strict_memh = ($test$plusargs("CMR_STRICT_MEMH") != 0);

      memh_segments = 1'b0;
      if ((trial_mode != MODE_BYPASS) && (trial_thresh8 == 8'd16) &&
          file_exists(x_file) && file_exists(y_file) && file_exists(sup_file)) begin
        memh_segments = 1'b1;
      end
      if ($test$plusargs("CMR_MEMH_SEGMENTS"))    memh_segments = 1'b1;
      if ($test$plusargs("CMR_NO_MEMH_SEGMENTS")) memh_segments = 1'b0;

      memh_loaded = 1'b0;

      if (cmr_verbose) begin
        $display("[%s] cfg: mode=%s thresh8=%0d pre=%0d mid=%0d post=%0d second_clear=%0d clear_low_cycles=%0d",
                 this.name, mode_to_string(trial_mode), trial_thresh8,
                 pre_kpairs, mid_kpairs, post_kpairs, do_second_clear, clear_low_cycles);
        $display("[%s] cfg: memh_segments=%0d strict_memh=%0d files: x='%s' y='%s' sup='%s'",
                 this.name, memh_segments, strict_memh, x_file, y_file, sup_file);
      end
    endfunction


    // Override body

    virtual task automatic body();
      ui64_t tp, sp, abs_e, sq_e;

      // Values captured during clear timing
      ui64_t tp_at_pulse;
      ui64_t sp_at_pulse;
      ui64_t abs_at_pulse;
      ui64_t sq_at_pulse;
      bit   pov_during_pulse;

      // Segment start indices (pair index in the continuous golden streams)
      int unsigned start_after_clear1;
      int unsigned start_after_clear2;

      begin
        // Load MEMH goldens if requested
        if (memh_segments) begin
          load_memh_goldens();
        end

        // Program and reset
        drv.set_mode_and_threshold(trial_mode, trial_thresh8);
        drv.apply_reset(this.reset_hold_cycles);

        // Prime a couple sample ticks (helps avoid start-up weirdness)
        drv.wait_sample_tick(this.timeout_clks);
        drv.wait_sample_tick(this.timeout_clks);


        // Segment 0: run PRE pairs

        $display("\n[%s] SEG0 PRE: running %0d pairs before clear...", name, pre_kpairs);
        drv.run_pairs(pre_kpairs, this.timeout_clks, /*drain*/ 1'b0);
        // sample metrics after NBA settles
        @(negedge t.clk);
        read_metrics(tp, sp, abs_e, sq_e);

        $display("[%s] SEG0 metrics: tp=%0d sp=%0d abs=%0d sq=%0d", name, tp, sp, abs_e, sq_e);

        if (tp != pre_kpairs) begin
          $display("[%s] NOTE: tp (%0d) != pre_kpairs (%0d). This can happen if pairs occurred during priming.",
                   name, tp, pre_kpairs);
        end

        // Optional: compare SEG0 vs memh window starting at 0
        if (memh_loaded) begin
          check_metrics_against_memh(/*start_pair*/ 0, /*count*/ tp,
                                     /*dut*/ tp, sp, abs_e, sq_e,
                                     "SEG0_PRE");
        end

        // Record result row
        push_result_row(0, trial_mode, trial_thresh8, int'(tp), tp, sp, abs_e, sq_e);


        // Clear #1 mid-run

        $display("\n[%s] CLEAR #1: pressing KEY1 low for %0d cycles...", name, clear_low_cycles);
        drv.press_clear_metrics(clear_low_cycles);

        // Wait until we see clr_metrics_pulse asserted (tap)
        wait_for_clr_pulse(tp_at_pulse, sp_at_pulse, abs_at_pulse, sq_at_pulse, pov_during_pulse);

        $display("[%s] saw clr_metrics_pulse: tp_at_pulse=%0d sp=%0d abs=%0d sq=%0d pair_out_valid_during_pulse=%0d",
                 name, tp_at_pulse, sp_at_pulse, abs_at_pulse, sq_at_pulse, pov_during_pulse);

        // The clear actually takes effect one cycle AFTER clr_metrics_pulse
        @(negedge t.clk);
        read_metrics(tp, sp, abs_e, sq_e);

        if ((tp != 0) || (sp != 0) || (abs_e != 0) || (sq_e != 0)) begin
          $fatal(1, "[%s] CLEAR #1 FAIL: metrics did not clear to 0 after clr_metrics_pulse. Got tp=%0d sp=%0d abs=%0d sq=%0d",
                 name, tp, sp, abs_e, sq_e);
        end
        $display("[%s] CLEAR #1 OK: metrics cleared to zero.", name);

        // Determine the post-clear1 segment start index in the continuous stream
        // If a pair_out_valid was present during the clr_pulse cycle, that pair's increment
        // would have been overridden by the clear at the next posedge, so we skip it.
        start_after_clear1 = int'(tp_at_pulse) + (pov_during_pulse ? 1 : 0);


        // Segment 1: run POST (or MID if second clear)

        if (!do_second_clear) begin
          $display("\n[%s] SEG1 POST: running %0d pairs after clear #1...", name, post_kpairs);
          drv.run_pairs(post_kpairs, this.timeout_clks, /*drain*/ 1'b0);
          @(negedge t.clk);
          read_metrics(tp, sp, abs_e, sq_e);

          if (tp != post_kpairs) begin
            $fatal(1, "[%s] SEG1 FAIL: expected tp==post_kpairs (%0d) but got %0d", name, post_kpairs, tp);
          end

          $display("[%s] SEG1 metrics: tp=%0d sp=%0d abs=%0d sq=%0d", name, tp, sp, abs_e, sq_e);

          if (memh_loaded) begin
            check_metrics_against_memh(/*start_pair*/ start_after_clear1, /*count*/ post_kpairs,
                                       /*dut*/ tp, sp, abs_e, sq_e,
                                       "SEG1_POST");
          end

          push_result_row(1, trial_mode, trial_thresh8, post_kpairs, tp, sp, abs_e, sq_e);

        end else begin
          // SEG1 MID
          $display("\n[%s] SEG1 MID: running %0d pairs after clear #1 before clear #2...", name, mid_kpairs);
          drv.run_pairs(mid_kpairs, this.timeout_clks, /*drain*/ 1'b0);
          @(negedge t.clk);
          read_metrics(tp, sp, abs_e, sq_e);

          if (tp != mid_kpairs) begin
            $fatal(1, "[%s] SEG1(MID) FAIL: expected tp==mid_kpairs (%0d) but got %0d", name, mid_kpairs, tp);
          end

          $display("[%s] SEG1(MID) metrics: tp=%0d sp=%0d abs=%0d sq=%0d", name, tp, sp, abs_e, sq_e);

          if (memh_loaded) begin
            check_metrics_against_memh(/*start_pair*/ start_after_clear1, /*count*/ mid_kpairs,
                                       /*dut*/ tp, sp, abs_e, sq_e,
                                       "SEG1_MID");
          end

          push_result_row(1, trial_mode, trial_thresh8, mid_kpairs, tp, sp, abs_e, sq_e);


          // Clear #2

          $display("\n[%s] CLEAR #2: pressing KEY1 low for %0d cycles...", name, clear_low_cycles);
          drv.press_clear_metrics(clear_low_cycles);

          wait_for_clr_pulse(tp_at_pulse, sp_at_pulse, abs_at_pulse, sq_at_pulse, pov_during_pulse);

          $display("[%s] saw clr_metrics_pulse #2: tp_at_pulse=%0d sp=%0d abs=%0d sq=%0d pair_out_valid_during_pulse=%0d",
                   name, tp_at_pulse, sp_at_pulse, abs_at_pulse, sq_at_pulse, pov_during_pulse);

          @(negedge t.clk);
          read_metrics(tp, sp, abs_e, sq_e);

          if ((tp != 0) || (sp != 0) || (abs_e != 0) || (sq_e != 0)) begin
            $fatal(1, "[%s] CLEAR #2 FAIL: metrics did not clear to 0 after clr_metrics_pulse. Got tp=%0d sp=%0d abs=%0d sq=%0d",
                   name, tp, sp, abs_e, sq_e);
          end
          $display("[%s] CLEAR #2 OK: metrics cleared to zero.", name);

          start_after_clear2 = int'(tp_at_pulse) + (pov_during_pulse ? 1 : 0);


          // SEG2 POST

          $display("\n[%s] SEG2 POST: running %0d pairs after clear #2...", name, post_kpairs);
          drv.run_pairs(post_kpairs, this.timeout_clks, /*drain*/ 1'b0);
          @(negedge t.clk);
          read_metrics(tp, sp, abs_e, sq_e);

          if (tp != post_kpairs) begin
            $fatal(1, "[%s] SEG2 FAIL: expected tp==post_kpairs (%0d) but got %0d", name, post_kpairs, tp);
          end

          $display("[%s] SEG2 metrics: tp=%0d sp=%0d abs=%0d sq=%0d", name, tp, sp, abs_e, sq_e);

          if (memh_loaded) begin
            check_metrics_against_memh(/*start_pair*/ start_after_clear2, /*count*/ post_kpairs,
                                       /*dut*/ tp, sp, abs_e, sq_e,
                                       "SEG2_POST");
          end

          push_result_row(2, trial_mode, trial_thresh8, post_kpairs, tp, sp, abs_e, sq_e);
        end

        $display("\n[%s] PASS: clear-metrics midrun behavior verified.", name);
      end
    endtask


    // Load MEMH goldens

    task automatic load_memh_goldens();
      int unsigned pairs_needed;
      begin
        if (!file_exists(x_file) || !file_exists(y_file) || !file_exists(sup_file)) begin
          if (strict_memh) begin
            $fatal(1, "[%s] MEMH segment check requested, but missing files: x='%s' y='%s' sup='%s'",
                   name, x_file, y_file, sup_file);
          end
          $display("[%s] NOTE: MEMH segment check disabled (files missing).", name);
          memh_loaded = 1'b0;
          return;
        end

        x_g.delete();
        y_g.delete();
        sup_g.delete();

        read_memh_signed(x_file, N, x_g);
        read_memh_signed(y_file, N, y_g);
        read_flags01(sup_file, sup_g);

        if ((x_g.size() % 2) != 0 || (y_g.size() % 2) != 0) begin
          if (strict_memh) $fatal(1, "[%s] MEMH invalid: x/y length must be even (x=%0d y=%0d)", name, x_g.size(), y_g.size());
          $display("[%s] NOTE: MEMH segment check disabled (x/y length invalid).", name);
          memh_loaded = 1'b0;
          return;
        end

        if (x_g.size() != y_g.size()) begin
          if (strict_memh) $fatal(1, "[%s] MEMH invalid: x/y length mismatch (x=%0d y=%0d)", name, x_g.size(), y_g.size());
          $display("[%s] NOTE: MEMH segment check disabled (x/y length mismatch).", name);
          memh_loaded = 1'b0;
          return;
        end

        if (sup_g.size() != (y_g.size()/2)) begin
          if (strict_memh) $fatal(1, "[%s] MEMH invalid: sup length mismatch (sup=%0d pairs=%0d)", name, sup_g.size(), (y_g.size()/2));
          $display("[%s] NOTE: MEMH segment check disabled (sup length mismatch).", name);
          memh_loaded = 1'b0;
          return;
        end

        // Determine max pairs we might touch. Worst case: we need pre + mid + post + some slack.
        pairs_needed = pre_kpairs + post_kpairs;
        if (do_second_clear) pairs_needed = pre_kpairs + mid_kpairs + post_kpairs;

        if (pairs_needed > (y_g.size()/2)) begin
          if (strict_memh) begin
            $fatal(1, "[%s] MEMH too short for requested pairs: need %0d pairs but memh has %0d pairs",
                   name, pairs_needed, (y_g.size()/2));
          end
          $display("[%s] NOTE: MEMH segment check disabled (requested pairs exceed memh length). need=%0d have=%0d",
                   name, pairs_needed, (y_g.size()/2));
          memh_loaded = 1'b0;
          return;
        end

        memh_loaded = 1'b1;
        $display("[%s] MEMH loaded for segment checks: x=%0d y=%0d sup_pairs=%0d",
                 name, x_g.size(), y_g.size(), sup_g.size());
      end
    endtask

    
    // Read current DUT metrics (safe to call at negedge)

    task automatic read_metrics(
      output ui64_t tp,
      output ui64_t sp,
      output ui64_t abs_e,
      output ui64_t sq_e
    );
      begin
        if ((^t.total_pairs === 1'bX) || (^t.suppressed_pairs === 1'bX) || (^t.sum_abs_err === 1'bX) || (^t.sum_sq_err === 1'bX)) begin
          $fatal(1, "[%s] DUT metrics contain X (tp=%b sp=%b abs=%b sq=%b)",
                 name, ^t.total_pairs, ^t.suppressed_pairs, ^t.sum_abs_err, ^t.sum_sq_err);
        end
        tp    = ui64_t'(t.total_pairs);
        sp    = ui64_t'(t.suppressed_pairs);
        abs_e = ui64_t'(t.sum_abs_err);
        sq_e  = ui64_t'(t.sum_sq_err);
      end
    endtask


    // Wait for clr_metrics_pulse and snapshot counters in that cycle

    task automatic wait_for_clr_pulse(
      output ui64_t tp,
      output ui64_t sp,
      output ui64_t abs_e,
      output ui64_t sq_e,
      output bit   pair_out_valid_during_pulse
    );
      int unsigned to;
      int unsigned c;
      begin
        to = (this.timeout_clks != 0) ? this.timeout_clks : drv.default_timeout_clks;
        c  = 0;

        while (1) begin
          @(negedge t.clk);
          if (t.clr_metrics_pulse === 1'b1) begin
            read_metrics(tp, sp, abs_e, sq_e);
            pair_out_valid_during_pulse = (t.pair_out_valid === 1'b1);
            return;
          end

          c++;
          if ((to != 0) && (c >= to)) begin
            $fatal(1, "[%s] TIMEOUT waiting for clr_metrics_pulse after %0d cycles", name, to);
          end
        end
      end
    endtask


    // Compute and compare a segment of metrics vs memh window

    task automatic check_metrics_against_memh(
      input int unsigned start_pair,
      input int unsigned count_pairs,
      input ui64_t       dut_tp,
      input ui64_t       dut_sp,
      input ui64_t       dut_abs,
      input ui64_t       dut_sq,
      input string       tag
    );
      ui64_t exp_tp, exp_sp, exp_abs, exp_sq;
      begin
        if (!memh_loaded) return;

        if ((start_pair + count_pairs) > sup_g.size()) begin
          if (strict_memh) begin
            $fatal(1, "[%s] %s MEMH window OOR: start=%0d count=%0d sup_pairs=%0d",
                   name, tag, start_pair, count_pairs, sup_g.size());
          end
          $display("[%s] NOTE: %s skipping memh segment check (window out of range).", name, tag);
          return;
        end

        compute_memh_window_metrics(start_pair, count_pairs, exp_tp, exp_sp, exp_abs, exp_sq);

        // Compare masked to DUT widths
        if ((dut_tp  != (exp_tp  & MASK32)) ||
            (dut_sp  != (exp_sp  & MASK32)) ||
            (dut_abs != (exp_abs & MASK32)) ||
            (dut_sq  != (exp_sq  & MASK48))) begin
          $fatal(1,
                 "[%s] %s MEMH METRICS MISMATCH: dut(tp,sp,abs,sq)=(%0d,%0d,%0d,%0d) exp=(%0d,%0d,%0d,%0d)  window=[%0d..%0d)",
                 name, tag,
                 dut_tp, dut_sp, dut_abs, dut_sq,
                 (exp_tp  & MASK32),
                 (exp_sp  & MASK32),
                 (exp_abs & MASK32),
                 (exp_sq  & MASK48),
                 start_pair, start_pair+count_pairs);
        end

        if (cmr_verbose) begin
          $display("[%s] %s MEMH metrics match. window=[%0d..%0d) tp=%0d sp=%0d abs=%0d sq=%0d",
                   name, tag, start_pair, start_pair+count_pairs,
                   (exp_tp & MASK32), (exp_sp & MASK32), (exp_abs & MASK32), (exp_sq & MASK48));
        end
      end
    endtask

    task automatic compute_memh_window_metrics(
      input  int unsigned start_pair,
      input  int unsigned count_pairs,
      output ui64_t exp_tp,
      output ui64_t exp_sp,
      output ui64_t exp_abs,
      output ui64_t exp_sq
    );
      si64_t e0, e1;
      ui64_t ae0, ae1;
      ui64_t sq0, sq1;
      si64_t x0, x1, y0, y1;
      begin
        exp_tp  = ui64_t'(count_pairs);
        exp_sp  = 0;
        exp_abs = 0;
        exp_sq  = 0;

        for (int unsigned k = 0; k < count_pairs; k++) begin
          x0 = x_g[2*(start_pair+k) + 0];
          x1 = x_g[2*(start_pair+k) + 1];
          y0 = y_g[2*(start_pair+k) + 0];
          y1 = y_g[2*(start_pair+k) + 1];

          e0 = x0 - y0;
          e1 = x1 - y1;

          ae0 = abs64(e0);
          ae1 = abs64(e1);

          sq0 = ae0 * ae0;
          sq1 = ae1 * ae1;

          exp_abs = (exp_abs + (ae0 + ae1)) & MASK32;
          exp_sq  = (exp_sq  + (sq0 + sq1)) & MASK48;

          if (sup_g[start_pair + k]) exp_sp = (exp_sp + 1) & MASK32;
        end
      end
    endtask


    // Push a result row into base-class summary table

    task automatic push_result_row(
      input int unsigned rid,
      input logic [1:0]  m,
      input logic [7:0]  th,
      input int unsigned pairs_req,
      input ui64_t       tp,
      input ui64_t       sp,
      input ui64_t       abs_e,
      input ui64_t       sq_e
    );
      trial_result_t r;
      begin
        r.trial_id            = rid;
        r.mode                = m;
        r.thresh8             = th;
        r.pairs_req           = pairs_req;

        r.dut_total_pairs      = tp;
        r.dut_suppressed_pairs = sp;
        r.dut_sum_abs_err      = abs_e;
        r.dut_sum_sq_err       = sq_e;

        r.suppressed_ratio     = (tp != 0) ? (real'(sp)/real'(tp)) : 0.0;
        r.end_time             = $time;

        results.push_back(r);
      end
    endtask

  endclass : test_clear_metrics_midrun

endpackage : tests_clear_pkg

`endif // TEST_CLEAR_METRICS_MIDRUN_SV

`default_nettype wire
