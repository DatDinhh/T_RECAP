`timescale 1ns/1ps
`default_nettype none

// Arizona State University 
// Capstone Senior Project
// Sigma Force
// Dat Dinh, Dat Huynh, Paul Applebee, Kyung Jae Son
// test_threshold_sweep.sv
//
// Threshold sweep regression test for T-RECAP Phase 1.
//
// What this test does (no hand-waving):
//   - Runs multiple "trials". Each trial resets the DUT (so input x[] is IDENTICAL
//     across trials), programs a threshold T (SW[7:0]) and a non-bypass mode,
//     then lets the DUT process K pairs.
//   - Records the DUT metrics after K pairs.
//   - Enforces monotonic relationships that MUST hold for a fixed input stream:
//       * suppressed_pairs is monotonic in T (non-decreasing if T increases)
//       * sum_abs_err     is monotonic in T
//       * sum_sq_err      is monotonic in T
//     Why monotonic is guaranteed:
//       - Unsuppressed pairs reconstruct exactly => zero error.
//       - Increasing T can only flip a pair from "kept" to "suppressed".
//       - Newly suppressed pairs add non-negative error.
//
// Optional extras:
//   - If you sweep multiple non-bypass modes (01/10/11), metrics must match
//     exactly across modes for the same threshold. (Modes should only affect
//     display/debug, not the algorithm.)
//   - If metrics.json exists and your sweep includes T=16 with K matching
//     metrics.json, it can sanity-check that point.
//
// IMPORTANT PRACTICAL NOTE ABOUT YOUR DV:
//   If y.memh/sup.memh exist and your stream/pair scoreboards default to MEMH
//   checking, they will FAIL for thresholds != 16 because those goldens were
//   generated at T=16. For sweep runs, set scoreboards to model-based modes.
//   Example command-line knobs (depending on what you instantiate):
//     +PAIR_SB_MODE=model
//     +Y_SB_MODE=model_pairs


`ifndef TEST_THRESHOLD_SWEEP_SV
`define TEST_THRESHOLD_SWEEP_SV

package tests_sweep_pkg;

  import tb_pkg::*;
  import board_driver_pkg::*;
  import test_pkg::*;

  class test_threshold_sweep #(int N = tb_pkg::N, int LFSR_W = tb_pkg::LFSR_W)
    extends test_pkg::test_base #(N, LFSR_W);


    // Test-specific knobs

    bit ts_verbose;

    bit check_monotonic;       // monotonic metrics vs threshold (requires reset_between_trials=1)
    bit check_mode_invariance; // metrics must match across non-bypass modes for same T

    bit strict_total_pairs;    // fatal if dut_total_pairs != K (recommended)

    // Optional golden point check at T=16
    bit    check_golden16;
    string metrics_file;
    bit    golden_loaded;
    ui64_t g_tp, g_sp, g_abs, g_sq;

    // Threshold sweep settings
    int unsigned ts_start;
    int unsigned ts_end;
    int unsigned ts_step;

    // Modes to sweep (bit i corresponds to mode value i)
    //   bit0: 00 bypass
    //   bit1: 01 man_supp
    //   bit2: 10 man_abs
    //   bit3: 11 man_sq
    int unsigned mode_mask;
    bit          include_bypass_trial;
    logic [7:0]  bypass_sw_thresh8;

    // Primary mode used for condensed summary
    logic [1:0] primary_mode;


    // Constructor

    function new(
      virtual board_if.tb             b,
      virtual tap_if t,
      string                          name = "test_threshold_sweep"
    );
      int unsigned tmp;
      string s;
      bit have_any;

      super.new(b, t, name);

      ts_verbose = ($test$plusargs("TSW_VERBOSE") != 0) || this.verbose;

      // Defaults: a reasonable sweep that isn't insane on runtime.
      // You can override with +TSW_THRESH_START/END/STEP (or TB_* equivalents).
      ts_start = 0;
      ts_end   = 255;
      ts_step  = 16;

      // Default: sweep only one non-bypass mode (MAN_ABS)
      mode_mask = (1 << int'(MODE_MAN_ABS));
      include_bypass_trial = 1'b0;
      bypass_sw_thresh8    = 8'hA5; // intentionally nonzero when bypass is exercised

      // Checks ON by default
      check_monotonic       = 1'b1;
      check_mode_invariance = 1'b1;
      strict_total_pairs    = 1'b1;

      // Golden16 check defaults to ON if metrics.json exists
      metrics_file  = "metrics.json";
      golden_loaded = 1'b0;
      g_tp = 0; g_sp = 0; g_abs = 0; g_sq = 0;
      check_golden16 = file_exists(metrics_file);

      // Allow overriding K pairs
      void'($value$plusargs("TSW_KPAIRS=%d", this.pairs_per_trial));

      // Read sweep range (TSW_* has priority; else TB_*; else defaults above)
      have_any = 1'b0;
      if ($value$plusargs("TSW_THRESH_START=%d", tmp)) begin ts_start = (tmp > 255) ? 255 : tmp; have_any = 1'b1; end
      if ($value$plusargs("TSW_THRESH_END=%d",   tmp)) begin ts_end   = (tmp > 255) ? 255 : tmp; have_any = 1'b1; end
      if ($value$plusargs("TSW_THRESH_STEP=%d",  tmp)) begin ts_step  = (tmp == 0) ? 1 : tmp;   have_any = 1'b1; end

      if (!have_any) begin
        // fall back to TB sweep args if user already uses that convention
        if ($value$plusargs("TB_THRESH_START=%d", tmp)) begin ts_start = (tmp > 255) ? 255 : tmp; have_any = 1'b1; end
        if ($value$plusargs("TB_THRESH_END=%d",   tmp)) begin ts_end   = (tmp > 255) ? 255 : tmp; have_any = 1'b1; end
        if ($value$plusargs("TB_THRESH_STEP=%d",  tmp)) begin ts_step  = (tmp == 0) ? 1 : tmp;   have_any = 1'b1; end
      end

      // Modes: single mode selection
      if ($value$plusargs("TSW_MODE=%d", tmp)) begin
        if (tmp > 3) tmp = 3;
        mode_mask = (1 << tmp);
      end

      // Modes: mask selection (supports decimal or hex strings)
      s = "";
      if ($value$plusargs("TSW_MODE_MASK=%s", s)) begin
        int unsigned mv;
        mv = 0;
        if (($sscanf(s, "0x%x", mv) == 1) || ($sscanf(s, "%x", mv) == 1)) begin
          mode_mask = mv;
        end else if ($sscanf(s, "%d", mv) == 1) begin
          mode_mask = mv;
        end
      end

      // Include bypass as an extra baseline trial (optional)
      if ($test$plusargs("TSW_INCLUDE_BYPASS")) include_bypass_trial = 1'b1;
      if ($test$plusargs("TSW_NO_BYPASS"))      include_bypass_trial = 1'b0;
      if ($value$plusargs("TSW_BYPASS_SW_THRESH=%d", tmp)) begin
        if (tmp > 255) tmp = 255;
        bypass_sw_thresh8 = tmp[7:0];
      end

      // Golden metrics file override
      void'($value$plusargs("TSW_METRICS_FILE=%s", metrics_file));
      void'($value$plusargs("METRICS_JSON=%s",   metrics_file));
      if ($test$plusargs("TSW_NO_GOLDEN16")) check_golden16 = 1'b0;
      if ($test$plusargs("TSW_CHECK_GOLDEN16")) check_golden16 = 1'b1;

      // Check toggles
      if ($test$plusargs("TSW_NO_MONO")) check_monotonic = 1'b0;
      if ($test$plusargs("TSW_MONO"))    check_monotonic = 1'b1;

      if ($test$plusargs("TSW_NO_MODE_INVAR")) check_mode_invariance = 1'b0;
      if ($test$plusargs("TSW_MODE_INVAR"))    check_mode_invariance = 1'b1;

      if ($test$plusargs("TSW_NO_STRICT_TP")) strict_total_pairs = 1'b0;
      if ($test$plusargs("TSW_STRICT_TP"))    strict_total_pairs = 1'b1;

      // Enforce sweep semantics for this test
      this.do_sweep = 1'b1;

      // Reset between every trial is REQUIRED for meaningful cross-threshold comparisons.
      // You can disable, but then monotonic/mode invariance checks become meaningless.
      this.reset_between_trials = 1'b1;
      if ($test$plusargs("TSW_NO_RESET_BETWEEN_TRIALS") || $test$plusargs("TB_NO_RESET_BETWEEN_TRIALS")) begin
        this.reset_between_trials = 1'b0;
      end
      if ($test$plusargs("TSW_RESET_BETWEEN_TRIALS") || $test$plusargs("TB_RESET_BETWEEN_TRIALS")) begin
        this.reset_between_trials = 1'b1;
      end

      this.clear_between_trials = 1'b0; // clearing without reset breaks comparability too

      // Base-class mode/thresh are only used for the initial build/reset.
      // Set them to the first planned sweep settings.
      this.mode   = MODE_MAN_ABS;
      this.thresh8= ts_start[7:0];

      // Choose a primary mode for condensed reporting (first non-bypass bit in mask).
      primary_mode = MODE_MAN_ABS;
      for (int m = 1; m < 4; m++) begin
        if ((mode_mask & (1 << m)) != 0) begin
          primary_mode = m[1:0];
          break;
        end
      end

      if (ts_verbose) begin
        $display("[%s] cfg: K=%0d  sweep=[%0d..%0d] step=%0d  mode_mask=0x%0h  include_bypass=%0d",
                 this.name, this.pairs_per_trial, ts_start, ts_end, ts_step, mode_mask[3:0], include_bypass_trial);
        $display("[%s] checks: monotonic=%0d mode_invar=%0d strict_tp=%0d golden16=%0d metrics_file='%s'",
                 this.name, check_monotonic, check_mode_invariance, strict_total_pairs, check_golden16, metrics_file);
        $display("[%s] reset_between_trials=%0d (required for mono/mode-invar)", this.name, this.reset_between_trials);
      end

    endfunction


    // Override body

    virtual task automatic body();
      preflight();
      if (check_golden16) load_golden_metrics();
      run_sweep();
    endtask

    // -------------------------
    // Preflight warnings (can't fix scoreboard config from inside sim)
    // -------------------------
    task automatic preflight();
      bit y_exists;
      bit sup_exists;
      bit sweep_has_non16;
      string tmp_s;
      bit has_pair_mode;
      bit has_y_mode;

      begin
        y_exists   = file_exists("y.memh");
        sup_exists = file_exists("sup.memh");

        sweep_has_non16 = !((ts_start == 16) && (ts_end == 16));

        // If someone forgot to set the scoreboards to model-mode, they'll get unrelated failures.
        // We can only warn.
        tmp_s = "";
        has_pair_mode = $value$plusargs("PAIR_SB_MODE=%s", tmp_s);
        tmp_s = "";
        has_y_mode    = $value$plusargs("Y_SB_MODE=%s", tmp_s);

        if ((y_exists || sup_exists) && sweep_has_non16) begin
          $display("[%s] NOTE: y.memh/sup.memh present and sweep includes thresholds != 16.", name);
          $display("[%s]       If your pair/y stream scoreboards default to MEMH checking, they will FAIL.", name);
          $display("[%s]       Run with model-based modes, e.g.: +PAIR_SB_MODE=model +Y_SB_MODE=model_pairs", name);
          if (!has_pair_mode) $display("[%s]       (PAIR_SB_MODE not set on command line)", name);
          if (!has_y_mode)    $display("[%s]       (Y_SB_MODE not set on command line)", name);
        end

        if (check_monotonic && !this.reset_between_trials) begin
          $fatal(1, "[%s] Monotonic checking requires reset_between_trials=1. You disabled it (TSW_NO_RESET_BETWEEN_TRIALS).\nDisable monotonic checks with +TSW_NO_MONO OR re-enable reset.", name);
        end

        if (check_mode_invariance && !this.reset_between_trials) begin
          $fatal(1, "[%s] Mode-invariance checking requires reset_between_trials=1. You disabled it.", name);
        end

        if (ts_step == 0) ts_step = 1;
      end
    endtask


    // Load golden metrics (metrics.json)

    task automatic load_golden_metrics();
      begin
        if (!file_exists(metrics_file)) begin
          $display("[%s] NOTE: metrics file not found '%s' -> disabling golden16 check.", name, metrics_file);
          check_golden16 = 1'b0;
          golden_loaded = 1'b0;
          return;
        end

        read_metrics_json(metrics_file, g_tp, g_sp, g_abs, g_sq);
        golden_loaded = 1'b1;

        if (ts_verbose) begin
          $display("[%s] Loaded golden metrics '%s': tp=%0d sp=%0d abs=%0d sq=%0d",
                   name, metrics_file, g_tp, g_sp, g_abs, g_sq);
        end
      end
    endtask


    // The sweep itself

    task automatic run_sweep();
      // prev metrics per mode for monotonic checks (index 0..3)
      bit   prev_valid [0:3];
      int unsigned prev_T [0:3];
      ui64_t prev_sp [0:3];
      ui64_t prev_abs[0:3];
      ui64_t prev_sq [0:3];

      // reference for mode invariance at a given T
      bit   have_ref;
      ui64_t ref_tp, ref_sp, ref_abs, ref_sq;
      logic [1:0] ref_mode;

      int dir;
      int unsigned T;
      int unsigned trial_id;

      logic [1:0] modes[$];

      begin
        // init prev trackers
        for (int m = 0; m < 4; m++) begin
          prev_valid[m] = 1'b0;
          prev_T[m]     = 0;
          prev_sp[m]    = 0;
          prev_abs[m]   = 0;
          prev_sq[m]    = 0;
        end

        // Build mode list from mask (skip bypass here; handled separately)
        modes.delete();
        for (int m = 1; m < 4; m++) begin
          if ((mode_mask & (1 << m)) != 0) modes.push_back(m[1:0]);
        end
        if (modes.size() == 0) begin
          // Safety fallback
          modes.push_back(MODE_MAN_ABS);
        end

        // Determine sweep direction
        dir = (ts_start <= ts_end) ? 1 : -1;

        // Optional bypass baseline
        trial_id = 0;
        if (include_bypass_trial) begin
          run_trial(trial_id, MODE_BYPASS, bypass_sw_thresh8, this.pairs_per_trial);
          check_trial_sanity(trial_id, MODE_BYPASS, 0, /*is_bypass*/1'b1);
          trial_id++;
        end

        // Main threshold sweep
        T = ts_start;
        while (1) begin
          have_ref = 1'b0;

          foreach (modes[i]) begin
            logic [1:0] m;
            m = modes[i];

            run_trial(trial_id, m, T[7:0], this.pairs_per_trial);
            check_trial_sanity(trial_id, m, T, /*is_bypass*/1'b0);

            // Mode-invariance: reference is first mode run at this T
            if (check_mode_invariance) begin
              ui64_t tp, sp, ab, sq;
              tp = ui64_t'(this.results[this.results.size()-1].dut_total_pairs);
              sp = ui64_t'(this.results[this.results.size()-1].dut_suppressed_pairs);
              ab = ui64_t'(this.results[this.results.size()-1].dut_sum_abs_err);
              sq = ui64_t'(this.results[this.results.size()-1].dut_sum_sq_err);

              if (!have_ref) begin
                have_ref = 1'b1;
                ref_tp = tp; ref_sp = sp; ref_abs = ab; ref_sq = sq;
                ref_mode = m;
              end else begin
                if (tp != ref_tp || sp != ref_sp || ab != ref_abs || sq != ref_sq) begin
                  $fatal(1,
                    "[%s] MODE-INVAR FAIL at T=%0d: ref_mode=%s got (tp,sp,abs,sq)=(%0d,%0d,%0d,%0d), mode=%s got (%0d,%0d,%0d,%0d)",
                    name, T,
                    mode_to_string(ref_mode), ref_tp, ref_sp, ref_abs, ref_sq,
                    mode_to_string(m), tp, sp, ab, sq);
                end
              end
            end

            // Monotonic per-mode across thresholds
            if (check_monotonic) begin
              ui64_t cur_sp, cur_abs, cur_sq;
              cur_sp  = ui64_t'(this.results[this.results.size()-1].dut_suppressed_pairs);
              cur_abs = ui64_t'(this.results[this.results.size()-1].dut_sum_abs_err);
              cur_sq  = ui64_t'(this.results[this.results.size()-1].dut_sum_sq_err);

              if (prev_valid[int'(m)]) begin
                if (dir > 0) begin
                  if (cur_sp < prev_sp[int'(m)])
                    $fatal(1, "[%s] MONO FAIL (suppressed_pairs) mode=%s: T %0d->%0d  %0d->%0d",
                           name, mode_to_string(m), prev_T[int'(m)], T, prev_sp[int'(m)], cur_sp);
                  if (cur_abs < prev_abs[int'(m)])
                    $fatal(1, "[%s] MONO FAIL (sum_abs_err) mode=%s: T %0d->%0d  %0d->%0d",
                           name, mode_to_string(m), prev_T[int'(m)], T, prev_abs[int'(m)], cur_abs);
                  if (cur_sq < prev_sq[int'(m)])
                    $fatal(1, "[%s] MONO FAIL (sum_sq_err) mode=%s: T %0d->%0d  %0d->%0d",
                           name, mode_to_string(m), prev_T[int'(m)], T, prev_sq[int'(m)], cur_sq);
                end else begin
                  if (cur_sp > prev_sp[int'(m)])
                    $fatal(1, "[%s] MONO FAIL (suppressed_pairs, descending) mode=%s: T %0d->%0d  %0d->%0d",
                           name, mode_to_string(m), prev_T[int'(m)], T, prev_sp[int'(m)], cur_sp);
                  if (cur_abs > prev_abs[int'(m)])
                    $fatal(1, "[%s] MONO FAIL (sum_abs_err, descending) mode=%s: T %0d->%0d  %0d->%0d",
                           name, mode_to_string(m), prev_T[int'(m)], T, prev_abs[int'(m)], cur_abs);
                  if (cur_sq > prev_sq[int'(m)])
                    $fatal(1, "[%s] MONO FAIL (sum_sq_err, descending) mode=%s: T %0d->%0d  %0d->%0d",
                           name, mode_to_string(m), prev_T[int'(m)], T, prev_sq[int'(m)], cur_sq);
                end
              end

              prev_valid[int'(m)] = 1'b1;
              prev_T[int'(m)]     = T;
              prev_sp[int'(m)]    = cur_sp;
              prev_abs[int'(m)]   = cur_abs;
              prev_sq[int'(m)]    = cur_sq;
            end

            // Optional golden check at T=16
            if (check_golden16 && golden_loaded && (T == 16)) begin
              ui64_t tp, sp, ab, sq;
              tp = ui64_t'(this.results[this.results.size()-1].dut_total_pairs);
              sp = ui64_t'(this.results[this.results.size()-1].dut_suppressed_pairs);
              ab = ui64_t'(this.results[this.results.size()-1].dut_sum_abs_err);
              sq = ui64_t'(this.results[this.results.size()-1].dut_sum_sq_err);

              // Only meaningful if K matches the golden's total_pairs
              if (tp == g_tp) begin
                if (sp != g_sp || ab != g_abs || sq != g_sq) begin
                  $fatal(1, "[%s] GOLDEN16 FAIL mode=%s: dut(tp,sp,abs,sq)=(%0d,%0d,%0d,%0d) exp=(%0d,%0d,%0d,%0d)",
                         name, mode_to_string(m), tp, sp, ab, sq, g_tp, g_sp, g_abs, g_sq);
                end else if (ts_verbose) begin
                  $display("[%s] GOLDEN16 PASS mode=%s: (tp,sp,abs,sq)=(%0d,%0d,%0d,%0d)",
                           name, mode_to_string(m), tp, sp, ab, sq);
                end
              end else if (ts_verbose) begin
                $display("[%s] NOTE: skipping GOLDEN16 compare because K mismatch: dut_tp=%0d json_tp=%0d", name, tp, g_tp);
              end
            end

            trial_id++;
          end

          // advance threshold
          if (T == ts_end) break;
          if (dir > 0) begin
            if (T + ts_step > ts_end) T = ts_end;
            else                      T = T + ts_step;
          end else begin
            if (T < ts_step) begin
              T = ts_end; // safety
            end else if (T - ts_step < ts_end) begin
              T = ts_end;
            end else begin
              T = T - ts_step;
            end
          end
        end

        $display("[%s] Threshold sweep complete. Trials run=%0d", name, trial_id);
      end
    endtask


    // Sanity checks per trial

    task automatic check_trial_sanity(
      input int unsigned trial_id,
      input logic [1:0]  m,
      input int unsigned T,
      input bit          is_bypass
    );
      ui64_t tp, sp, ab, sq;
      real ratio;
      begin
        tp = ui64_t'(this.results[this.results.size()-1].dut_total_pairs);
        sp = ui64_t'(this.results[this.results.size()-1].dut_suppressed_pairs);
        ab = ui64_t'(this.results[this.results.size()-1].dut_sum_abs_err);
        sq = ui64_t'(this.results[this.results.size()-1].dut_sum_sq_err);
        ratio = (tp != 0) ? (real'(sp) / real'(tp)) : 0.0;

        if (strict_total_pairs && (tp != ui64_t'(this.pairs_per_trial))) begin
          $fatal(1, "[%s] Trial %0d FAIL: total_pairs=%0d expected=%0d (driver/run_pairs issue or metrics timing issue)",
                 name, trial_id, tp, this.pairs_per_trial);
        end

        if (sp > tp) begin
          $fatal(1, "[%s] Trial %0d FAIL: suppressed_pairs (%0d) > total_pairs (%0d)", name, trial_id, sp, tp);
        end

        // For bypass or T==0 (manual) the algorithm must be lossless
        if (is_bypass || (T == 0)) begin
          if (sp != 0 || ab != 0 || sq != 0) begin
            $fatal(1, "[%s] Trial %0d FAIL (lossless expected): mode=%s T=%0d got sp=%0d abs=%0d sq=%0d",
                   name, trial_id, mode_to_string(m), T, sp, ab, sq);
          end
        end

        if (ts_verbose) begin
          $display("[%s] Trial %0d OK: mode=%s T=%0d tp=%0d sp=%0d (ratio=%0.6f) abs=%0d sq=%0d",
                   name, trial_id, mode_to_string(m), T, tp, sp, ratio, ab, sq);
        end
      end
    endtask


    // Optional: add a condensed summary after base prints results

    virtual task automatic post_run();
      super.post_run();
      print_condensed_summary(primary_mode);
    endtask

    task automatic print_condensed_summary(input logic [1:0] msel);
      begin
        $display("[%s] ----- Condensed sweep summary (mode=%s) -----", name, mode_to_string(msel));
        $display("[%s]   thresh | tp | sp | sp_ratio  | abs_err | sq_err", name);
        $display("[%s]  -------+----+----+----------+---------+-------", name);

        foreach (this.results[i]) begin
          if (this.results[i].mode != msel) continue;
          if (this.results[i].mode == MODE_BYPASS) continue;

          $display("[%s]   %5d | %0d | %0d | %0.6f | %0d | %0d",
                   name,
                   this.results[i].thresh8,
                   this.results[i].dut_total_pairs,
                   this.results[i].dut_suppressed_pairs,
                   this.results[i].suppressed_ratio,
                   this.results[i].dut_sum_abs_err,
                   this.results[i].dut_sum_sq_err);
        end

        $display("[%s] --------------------------------------------\n", name);
      end
    endtask

  endclass : test_threshold_sweep

endpackage : tests_sweep_pkg

// Convenience alias so tb_top can just refer to "test_threshold_sweep"
typedef tests_sweep_pkg::test_threshold_sweep test_threshold_sweep;

`endif // TEST_THRESHOLD_SWEEP_SV

`default_nettype wire

