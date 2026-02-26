`timescale 1ns/1ps
`default_nettype none

// Arizona State University 
// Capstone Senior Project
// Sigma Force
// Dat Dinh, Dat Huynh, Paul Applebee, Kyung Jae Son
// test_mode_switch_stress.sv
//
// Stress test: toggle SW[9:8] (mode_sel) repeatedly while the Phase-1
// streaming algorithm runs.
//
// DUT truth (critical):
//   - mode_sel == 2'b00 (BYPASS) forces thresh_used=0 -> algorithm changes.
//   - mode_sel == 2'b01/10/11 only affects display/debug muxing.
//
// Therefore this test has two useful configurations:
//   A) Default (recommended): mode_mask = 0xE (01/10/11 only)
//      -> algorithm is invariant, so the run SHOULD match metrics.json when
//         THRESH=16 and K matches.
//
//   B) Optional: include BYPASS in the mode mask (bit0=1)
//      -> algorithm is allowed to change. In that case we:
//           * do NOT attempt to match metrics.json by default
//           * still enforce a strong local invariant for any pair processed
//             while force_bypass==1:
//                 suppressed == 0 and y == x (lossless)
//
// Plusargs
//
// Run size / settings
//   +MSS_KPAIRS=<int>              (default: TB_KPAIRS / base default 5000)
//   +MSS_THRESH=<0..255>           (default: TB_THRESH / base default 16)
//
// Mode switching
//   +MSS_MODE_MASK=<mask>          (default 0xE -> modes 01/10/11)
//                                 (bit0=00, bit1=01, bit2=10, bit3=11)
//   +MSS_SWITCH_MIN=<int>          (default 50)
//   +MSS_SWITCH_MAX=<int>          (default 500)
//   +MSS_SWITCH_UNIT=<clk|sample|dbg> (default "clk")
//   +MSS_SEED=<int>                (optional random seed)
//
// Checks
//   +MSS_NO_MODESEL_CHECK           (disable mode_sel consistency check)
//   +MSS_NO_THRESH_CHECK            (disable thresh_used/force_bypass consistency check)
//   +MSS_NO_BYPASS_LOSSLESS_CHECK   (if BYPASS is enabled in mask, disable lossless pair check)
//
// Golden metrics.json check (only valid when BYPASS is NOT used)
//   +MSS_METRICS_FILE=<path>        (default metrics.json)
//   +MSS_CHECK_GOLDEN_METRICS       (force enable)
//   +MSS_NO_GOLDEN_METRICS          (force disable)
//
// Verbosity
//   +MSS_VERBOSE


`ifndef TEST_MODE_SWITCH_STRESS_SV
`define TEST_MODE_SWITCH_STRESS_SV

package tests_mode_stress_pkg;

  import tb_pkg::*;
  import board_driver_pkg::*;
  import test_pkg::*;

  class test_mode_switch_stress #(int N = tb_pkg::N, int LFSR_W = tb_pkg::LFSR_W)
    extends test_pkg::test_base #(N, LFSR_W);


    // Configuration knobs

    bit          mss_verbose;

    int unsigned K;
    logic [7:0]  T8;

    int unsigned mode_mask;     // bitmask for allowed modes

    int unsigned switch_min;
    int unsigned switch_max;
    string       switch_unit;   // "clk" | "sample" | "dbg"

    bit          have_seed;
    int unsigned seed;

    // checks
    bit check_modesel;
    bit check_thresh;
    bit check_bypass_lossless;

    // golden metrics
    string metrics_file;
    bit    check_golden_metrics;
    bit    force_golden_metrics;
    bit    disable_golden_metrics;


    // Statistics

    int unsigned switch_count;
    int unsigned mode_seen_pairs [0:3];
    int unsigned bypass_pair_count;
    int unsigned nonbypass_pair_count;


    // Constructor

    function new(
      virtual board_if.tb             b,
      virtual tap_if t,
      string                          name = "test_mode_switch_stress"
    );
      int unsigned tmp;
      string s;
      super.new(b, t, name);

      mss_verbose = ($test$plusargs("MSS_VERBOSE") != 0) || this.verbose;

      // Defaults are inherited from test_base (K=5000, T=16, mode=MAN_ABS)
      K  = this.pairs_per_trial;
      T8 = this.thresh8;

      // Default: exclude BYPASS (only exercise display modes)
      mode_mask = 4'hE; // 1110b -> modes 01/10/11

      // Default switching intensity (in chosen units)
      switch_min  = 50;
      switch_max  = 500;
      switch_unit = "clk";

      // Optional seed
      have_seed = 1'b0;
      seed      = 32'h0;

      // Checks ON by default
      check_modesel         = 1'b1;
      check_thresh          = 1'b1;
      check_bypass_lossless = 1'b1;

      // Golden metrics default: only auto-enable when safe
      metrics_file           = "metrics.json";
      check_golden_metrics   = 1'b0;
      force_golden_metrics   = 1'b0;
      disable_golden_metrics = 1'b0;

      // Overrides
      void'($value$plusargs("MSS_KPAIRS=%d", K));
      if ($value$plusargs("MSS_THRESH=%d", tmp)) begin
        if (tmp > 255) tmp = 255;
        T8 = tmp[7:0];
      end

      // Mode mask parse (accept 0x.. or decimal)
      s = "";
      if ($value$plusargs("MSS_MODE_MASK=%s", s)) begin
        int unsigned mv;
        mv = mode_mask;
        if (($sscanf(s, "0x%x", mv) == 1) || ($sscanf(s, "%x", mv) == 1)) begin
          mode_mask = mv;
        end else if ($sscanf(s, "%d", mv) == 1) begin
          mode_mask = mv;
        end
      end
      mode_mask &= 4'hF;
      if (mode_mask == 0) begin
        // nonsensical -> fall back to safe default
        mode_mask = 4'hE;
      end

      void'($value$plusargs("MSS_SWITCH_MIN=%d", switch_min));
      void'($value$plusargs("MSS_SWITCH_MAX=%d", switch_max));
      if (switch_min == 0) switch_min = 1;
      if (switch_max < switch_min) switch_max = switch_min;

      void'($value$plusargs("MSS_SWITCH_UNIT=%s", switch_unit));
      if (!(switch_unit == "clk" || switch_unit == "sample" || switch_unit == "dbg")) begin
        // unknown string -> default
        switch_unit = "clk";
      end

      if ($value$plusargs("MSS_SEED=%d", tmp)) begin
        have_seed = 1'b1;
        seed      = tmp;
      end

      if ($test$plusargs("MSS_NO_MODESEL_CHECK")) check_modesel = 1'b0;
      if ($test$plusargs("MSS_NO_THRESH_CHECK"))  check_thresh  = 1'b0;
      if ($test$plusargs("MSS_NO_BYPASS_LOSSLESS_CHECK")) check_bypass_lossless = 1'b0;

      void'($value$plusargs("MSS_METRICS_FILE=%s", metrics_file));
      void'($value$plusargs("METRICS_JSON=%s", metrics_file));

      if ($test$plusargs("MSS_CHECK_GOLDEN_METRICS")) force_golden_metrics = 1'b1;
      if ($test$plusargs("MSS_NO_GOLDEN_METRICS"))    disable_golden_metrics = 1'b1;

      // Set base-class knobs so banner/build/reset align.
      // Choose an initial mode: first enabled non-bypass mode if possible.
      this.thresh8         = T8;
      this.pairs_per_trial = K;
      this.do_sweep        = 1'b0;

      this.mode = pick_first_mode(mode_mask);

      // Auto-enable golden metrics when safe:
      //   - not forcing disable
      //   - NOT allowing bypass in mask
      //   - T==16
      //   - metrics file exists
      if (!disable_golden_metrics && ((mode_mask & 4'h1) == 0) && (T8 == 8'd16) && file_exists(metrics_file)) begin
        check_golden_metrics = 1'b1;
      end
      if (force_golden_metrics) check_golden_metrics = 1'b1;
      if (disable_golden_metrics) check_golden_metrics = 1'b0;

      if (mss_verbose) begin
        $display("[%s] cfg: K=%0d T=%0d mode_mask=0x%0h init_mode=%s", this.name, K, T8, mode_mask[3:0], mode_to_string(this.mode));
        $display("[%s] cfg: switch_unit=%s switch_min=%0d switch_max=%0d seed_set=%0d seed=%0d", this.name, switch_unit, switch_min, switch_max, have_seed, seed);
        $display("[%s] cfg: checks: modesel=%0d thresh=%0d bypass_lossless=%0d golden_metrics=%0d metrics_file='%s'", this.name,
                 check_modesel, check_thresh, check_bypass_lossless, check_golden_metrics, metrics_file);
      end

    endfunction

    // Pick first enabled mode (prefers 01/10/11 over 00 if available)
    function automatic logic [1:0] pick_first_mode(input int unsigned mask);
      pick_first_mode = MODE_MAN_ABS;
      // prefer non-bypass
      for (int m = 1; m < 4; m++) begin
        if ((mask & (1 << m)) != 0) begin
          pick_first_mode = m[1:0];
          return pick_first_mode;
        end
      end
      // else bypass
      if ((mask & 1) != 0) pick_first_mode = 2'b00;
    endfunction

    // Build a dynamic list of allowed modes from the mask
    function automatic void build_mode_list(input int unsigned mask, ref logic [1:0] modes[$]);
      modes.delete();
      for (int m = 0; m < 4; m++) begin
        if ((mask & (1 << m)) != 0) modes.push_back(m[1:0]);
      end
    endfunction

    // Randomly pick a mode from mask; try to avoid repeating current mode if possible.
    function automatic logic [1:0] pick_mode(input int unsigned mask, input logic [1:0] cur);
      logic [1:0] modes[$];
      int idx;
      build_mode_list(mask, modes);
      if (modes.size() == 0) begin
        pick_mode = cur;
        return pick_mode;
      end
      if (modes.size() == 1) begin
        pick_mode = modes[0];
        return pick_mode;
      end

      // Try a few times to pick a different mode
      pick_mode = cur;
      for (int tries = 0; tries < 8; tries++) begin
        idx = $urandom_range(0, modes.size()-1);
        if (modes[idx] != cur) begin
          pick_mode = modes[idx];
          return pick_mode;
        end
      end

      // fallback
      idx = $urandom_range(0, modes.size()-1);
      pick_mode = modes[idx];
    endfunction

    // Wait for one dbg_tick pulse (1-cycle pulse). Uses tap_if.
    task automatic wait_dbg_tick(input int unsigned timeout_override = 0);
      int unsigned to, c;
      begin
        to = drv.eff_timeout(timeout_override);
        c  = 0;
        while (1) begin
          @(posedge t.clk);
          if (t.dbg_tick === 1'b1) break;
          c++;
          if ((to != 0) && (c >= to)) begin
            $fatal(1, "[%s] TIMEOUT waiting for dbg_tick after %0d cycles", name, to);
          end
        end
      end
    endtask

    // Wait N "units" (clk/sample/dbg), but break early if done.
    task automatic wait_units_or_done(
      input int unsigned n,
      ref bit done
    );
      int unsigned i;
      begin
        for (i = 0; i < n; i++) begin
          if (done) break;
          if (switch_unit == "clk") begin
            @(posedge b.CLOCK_50);
          end else if (switch_unit == "sample") begin
            drv.wait_sample_tick(this.timeout_clks);
          end else begin
            wait_dbg_tick(this.timeout_clks);
          end
        end
      end
    endtask


    // Override body

    virtual task automatic body();
      preflight();
      run_stress();
    endtask


    // Preflight warnings

    task automatic preflight();
      bit y_exists;
      bit sup_exists;
      begin
        y_exists   = file_exists("y.memh");
        sup_exists = file_exists("sup.memh");

        if (((mode_mask & 4'h1) != 0) && (y_exists || sup_exists)) begin
          $display("[%s] NOTE: You enabled BYPASS in MSS_MODE_MASK (mask=0x%0h) and y.memh/sup.memh exist.", name, mode_mask[3:0]);
          $display("[%s]       MEMH-based scoreboards will likely FAIL because goldens were generated at THRESH=16 with no bypass.", name);
          $display("[%s]       If you want full checking under dynamic bypass, use model-based scoreboards (e.g. +PAIR_SB_MODE=model +Y_SB_MODE=model_pairs).", name);
        end

        if (check_golden_metrics && ((mode_mask & 4'h1) != 0)) begin
          $display("[%s] NOTE: golden metrics check is ON but BYPASS is enabled in the mode mask. Disabling golden metrics check.", name);
          check_golden_metrics = 1'b0;
        end
      end
    endtask


    // Main stress run

    task automatic run_stress();
      bit done;
      logic [1:0] cur_mode;
      logic [1:0] next_mode;

      int unsigned k;
      int unsigned wait_n;

      ui64_t dut_tp, dut_sp, dut_abs, dut_sq;

      // Optional golden expectations
      ui64_t g_tp, g_sp, g_abs, g_sq;
      bit    g_loaded;

      begin
        done = 1'b0;
        switch_count = 0;
        bypass_pair_count = 0;
        nonbypass_pair_count = 0;
        for (int m = 0; m < 4; m++) mode_seen_pairs[m] = 0;

        // Seed RNG (if requested)
        if (have_seed) void'($urandom(seed));

        // Base-class already reset in reset_phase(). Ensure mode/thresh are correct now.
        // Change at negedge for safe setup before next posedge work.
        cur_mode = this.mode;
        @(negedge t.clk);
        drv.set_mode_and_threshold(cur_mode, T8);

        // Sanity: confirm thresh_used / bypass behavior at start
        @(negedge t.clk);
        if (check_modesel) begin
          if (t.mode_sel !== b.SW[9:8]) begin
            $fatal(1, "[%s] START FAIL: tap mode_sel=%0b does not match board SW[9:8]=%0b", name, t.mode_sel, b.SW[9:8]);
          end
        end
        if (check_thresh) begin
          if ((b.SW[9:8] == 2'b00) && (t.thresh_used !== '0)) begin
            $fatal(1, "[%s] START FAIL: BYPASS mode but thresh_used!=0 (thresh_used=%0d)", name, t.thresh_used);
          end
          if ((b.SW[9:8] != 2'b00) && (t.thresh_used !== ui64_t'(T8))) begin
            $fatal(1, "[%s] START FAIL: non-bypass but thresh_used!=T8 (thresh_used=%0d T8=%0d)", name, t.thresh_used, T8);
          end
        end

        $display("\n[%s] ---- MODE SWITCH STRESS START ----", name);
        $display("[%s] K=%0d  THRESH=%0d  mode_mask=0x%0h  switch_unit=%s (%0d..%0d)",
                 name, K, T8, mode_mask[3:0], switch_unit, switch_min, switch_max);

        // Fork: one thread changes mode, one counts K pairs
        fork
          begin : mode_switcher
            while (!done) begin
              // Random wait between switches
              wait_n = $urandom_range(switch_min, switch_max);
              wait_units_or_done(wait_n, done);
              if (done) break;

              next_mode = pick_mode(mode_mask, cur_mode);

              // Apply change at negedge to avoid race with posedge sampling
              @(negedge t.clk);
              drv.set_mode_and_threshold(next_mode, T8);
              cur_mode = next_mode;
              switch_count++;

              if (mss_verbose && ((switch_count % 50) == 0)) begin
                $display("[%s] mode switch #%0d -> %s (SW[9:8]=%0b)", name, switch_count, mode_to_string(cur_mode), b.SW[9:8]);
              end
            end
          end

          begin : pair_counter
            for (k = 0; k < K; k++) begin
              drv.wait_pair_out_valid(this.timeout_clks);
              @(negedge t.clk);

              // Basic consistency checks
              if (check_modesel) begin
                if (t.mode_sel !== b.SW[9:8]) begin
                  $fatal(1, "[%s] FAIL @pair%0d: tap mode_sel=%0b != board SW[9:8]=%0b", name, k, t.mode_sel, b.SW[9:8]);
                end
              end
              if (check_thresh) begin
                if ((b.SW[9:8] == 2'b00) && (t.force_bypass !== 1'b1)) begin
                  $fatal(1, "[%s] FAIL @pair%0d: expected force_bypass=1 in mode00, got %b", name, k, t.force_bypass);
                end
                if ((b.SW[9:8] != 2'b00) && (t.force_bypass !== 1'b0)) begin
                  $fatal(1, "[%s] FAIL @pair%0d: expected force_bypass=0 in non-bypass, got %b", name, k, t.force_bypass);
                end

                if ((b.SW[9:8] == 2'b00) && (t.thresh_used !== '0)) begin
                  $fatal(1, "[%s] FAIL @pair%0d: BYPASS but thresh_used=%0d (expected 0)", name, k, t.thresh_used);
                end
                if ((b.SW[9:8] != 2'b00) && (t.thresh_used !== ui64_t'(T8))) begin
                  $fatal(1, "[%s] FAIL @pair%0d: non-bypass but thresh_used=%0d (expected %0d)", name, k, t.thresh_used, T8);
                end
              end

              // Count modes observed at pair boundaries
              mode_seen_pairs[int'(b.SW[9:8])]++;

              // If in BYPASS, enforce lossless pair property (unless disabled)
              if ((b.SW[9:8] == 2'b00)) begin
                bypass_pair_count++;
                if (check_bypass_lossless) begin
                  si64_t x0, x1, y0, y1;
                  x0 = si64_t'($signed(t.x0_a));
                  x1 = si64_t'($signed(t.x1_a));
                  y0 = si64_t'($signed(t.y0));
                  y1 = si64_t'($signed(t.y1));

                  if (t.suppressed !== 1'b0) begin
                    $fatal(1, "[%s] BYPASS LOSSLESS FAIL @pair%0d: suppressed=1 (abs_d=%0d)", name, k, t.abs_d_tap);
                  end
                  if ((y0 != x0) || (y1 != x1)) begin
                    $fatal(1, "[%s] BYPASS LOSSLESS FAIL @pair%0d: y!=x (x0=%s y0=%s x1=%s y1=%s)",
                           name, k, fmt_si64(x0), fmt_si64(y0), fmt_si64(x1), fmt_si64(y1));
                  end
                end
              end else begin
                nonbypass_pair_count++;
              end

              if (mss_verbose && ((k % 1000) == 0) && (k != 0)) begin
                $display("[%s] progress: %0d/%0d pairs (switches=%0d)", name, k, K, switch_count);
              end
            end
            done = 1'b1;
          end
        join

        // Wait until metrics accumulator catches up (1-cycle NBA lag)
        drv.wait_until_total_pairs(K, this.timeout_clks);
        @(negedge t.clk);

        dut_tp  = ui64_t'(t.total_pairs);
        dut_sp  = ui64_t'(t.suppressed_pairs);
        dut_abs = ui64_t'(t.sum_abs_err);
        dut_sq  = ui64_t'(t.sum_sq_err);

        $display("\n[%s] ---- STRESS RUN COMPLETE ----", name);
        $display("[%s] switches=%0d  bypass_pairs=%0d  nonbypass_pairs=%0d", name, switch_count, bypass_pair_count, nonbypass_pair_count);
        $display("[%s] mode_seen_pairs: m0=%0d m1=%0d m2=%0d m3=%0d", name,
                 mode_seen_pairs[0], mode_seen_pairs[1], mode_seen_pairs[2], mode_seen_pairs[3]);
        $display("[%s] DUT metrics at total_pairs==%0d: sp=%0d abs=%0d sq=%0d", name, K, dut_sp, dut_abs, dut_sq);

        // Golden metrics check (only meaningful if BYPASS not used)
        if (check_golden_metrics) begin
          g_loaded = 1'b0;
          if (!file_exists(metrics_file)) begin
            $display("[%s] NOTE: metrics file not found '%s' -> skipping golden metrics check.", name, metrics_file);
          end else begin
            read_metrics_json(metrics_file, g_tp, g_sp, g_abs, g_sq);
            g_loaded = 1'b1;

            if (g_tp != ui64_t'(K)) begin
              $display("[%s] NOTE: metrics.json total_pairs=%0d != K=%0d -> skipping golden metrics check.", name, g_tp, K);
              g_loaded = 1'b0;
            end
          end

          if (g_loaded) begin
            if ((dut_tp != g_tp) || (dut_sp != g_sp) || (dut_abs != g_abs) || (dut_sq != g_sq)) begin
              $fatal(1,
                     "[%s] GOLDEN METRICS MISMATCH: dut(tp,sp,abs,sq)=(%0d,%0d,%0d,%0d) exp=(%0d,%0d,%0d,%0d)",
                     name, dut_tp, dut_sp, dut_abs, dut_sq,
                     g_tp, g_sp, g_abs, g_sq);
            end
            $display("[%s] GOLDEN METRICS MATCH: (tp,sp,abs,sq)=(%0d,%0d,%0d,%0d)", name, dut_tp, dut_sp, dut_abs, dut_sq);
          end
        end

        // Record a single result row for base-class summary
        begin
          trial_result_t r;
          r.trial_id            = 0;
          r.mode                = this.mode;
          r.thresh8             = T8;
          r.pairs_req           = K;
          r.dut_total_pairs     = dut_tp;
          r.dut_suppressed_pairs= dut_sp;
          r.dut_sum_abs_err     = dut_abs;
          r.dut_sum_sq_err      = dut_sq;
          r.suppressed_ratio    = (dut_tp != 0) ? (real'(dut_sp) / real'(dut_tp)) : 0.0;
          r.end_time            = $time;
          results.push_back(r);
        end

        $display("[%s] PASS: mode switch stress completed.", name);
      end
    endtask

  endclass : test_mode_switch_stress

endpackage : tests_mode_stress_pkg

`endif // TEST_MODE_SWITCH_STRESS_SV

`default_nettype wire
