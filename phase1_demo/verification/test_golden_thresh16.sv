`timescale 1ns/1ps
`default_nettype none

// Arizona State University 
// Capstone Senior Project
// Sigma Force
// Dat Dinh, Dat Huynh, Paul Applebee, Kyung Jae Son
// test_golden_thresh16.sv
//
// Golden regression test for the provided Phase-1 golden artifacts:
//   - x.memh
//   - y.memh
//   - sup.memh
//   - metrics.json
//
// This test is meant to be the Phase-1 SIGNOFF run.
// It checks, for THRESH=16 and K=5000 pairs:
//
//   1) x_stream matches x.memh for the first 2K samples
//   2) Pair-domain outputs (y0,y1,suppressed) match y.memh/sup.memh for K pairs
//   3) Serialized y_out stream matches y.memh for the first 2K outputs
//   4) Metrics match metrics.json when total_pairs first reaches K
//
// IMPORTANT TIMING TRUTH (do not ignore):
//   The DUT's metrics accumulator sees pair_out_valid "one clock later"
//   because haar_core and metrics_accum are both always_ff blocks using
//   nonblocking assignments. Therefore:
//     - pair_out_valid for pair k occurs at sample tick n=2k+1
//     - total_pairs increments for that pair at the NEXT sample tick (n=2k+2)
//
// This test snapshots metrics at the moment total_pairs == K.
//
// Plusargs
// File paths (defaults shown):
//   +GT_X_FILE=x.memh          (alias: +X_MEMH=...)
//   +GT_Y_FILE=y.memh          (alias: +Y_MEMH=...)
//   +GT_SUP_FILE=sup.memh      (alias: +SUP_MEMH=...)
//   +GT_METRICS_FILE=metrics.json  (alias: +METRICS_JSON=...)
//
// Enable/disable sub-checks:
//   +GT_NO_X_CHECK
//   +GT_NO_PAIR_CHECK
//   +GT_NO_YSTREAM_CHECK
//   +GT_NO_METRICS_CHECK
//
// Overrides (NOT recommended unless you also provide matching golden files):
//   +GT_ALLOW_OVERRIDE   (allows TB_KPAIRS/TB_THRESH/TB_MODE to change run settings)
//
// Verbosity:
//   +GT_VERBOSE


`ifndef TEST_GOLDEN_THRESH16_SV
`define TEST_GOLDEN_THRESH16_SV

package tests_golden_pkg;

  import tb_pkg::*;
  import test_pkg::*;
  import board_driver_pkg::*;

  class test_golden_thresh16 #(int N = tb_pkg::N, int LFSR_W = tb_pkg::LFSR_W)
    extends test_pkg::test_base #(N, LFSR_W);


    // Golden file paths

    string x_file;
    string y_file;
    string sup_file;
    string metrics_file;

    
    // Enable knobs

    bit gt_verbose;

    bit check_x;
    bit check_pairs;
    bit check_y_stream;
    bit check_metrics;

    bit allow_override;


    // Golden data in memory

    si64_t x_g[$];
    si64_t y_g[$];
    bit    sup_g[$];

    ui64_t met_tp, met_sp, met_abs, met_sq;
    bit    metrics_loaded;


    // Derived constants

    int unsigned K;       // pairs in this run
    int unsigned NSAMP;   // samples = 2*K


    // Constructor

    function new(
      virtual board_if.tb             b,
      virtual tap_if #(N, LFSR_W).mon t,
      string                          name = "test_golden_thresh16"
    );
      super.new(b, t, name);

      gt_verbose = ($test$plusargs("GT_VERBOSE") != 0);

      allow_override = ($test$plusargs("GT_ALLOW_OVERRIDE") != 0);

      // Default golden run settings (override TB_* unless GT_ALLOW_OVERRIDE is set)
      if (!allow_override) begin
        this.pairs_per_trial = 5000;
        this.thresh8         = 8'd16;
        this.mode            = MODE_MAN_ABS;

        // prevent sweep logic
        this.do_sweep = 1'b0;
        this.reset_between_trials = 1'b0;
        this.clear_between_trials = 1'b0;
      end

      // Golden file defaults
      x_file       = "x.memh";
      y_file       = "y.memh";
      sup_file     = "sup.memh";
      metrics_file = "metrics.json";

      void'($value$plusargs("GT_X_FILE=%s", x_file));
      void'($value$plusargs("GT_Y_FILE=%s", y_file));
      void'($value$plusargs("GT_SUP_FILE=%s", sup_file));
      void'($value$plusargs("GT_METRICS_FILE=%s", metrics_file));

      // aliases (match other parts of the TB)
      void'($value$plusargs("X_MEMH=%s", x_file));
      void'($value$plusargs("Y_MEMH=%s", y_file));
      void'($value$plusargs("SUP_MEMH=%s", sup_file));
      void'($value$plusargs("METRICS_JSON=%s", metrics_file));

      // Checks ON by default
      check_x        = 1'b1;
      check_pairs    = 1'b1;
      check_y_stream = 1'b1;
      check_metrics  = 1'b1;

      if ($test$plusargs("GT_NO_X_CHECK"))        check_x        = 1'b0;
      if ($test$plusargs("GT_NO_PAIR_CHECK"))     check_pairs    = 1'b0;
      if ($test$plusargs("GT_NO_YSTREAM_CHECK"))  check_y_stream = 1'b0;
      if ($test$plusargs("GT_NO_METRICS_CHECK"))  check_metrics  = 1'b0;

      metrics_loaded = 1'b0;

      // Derived run sizes
      K     = this.pairs_per_trial;
      NSAMP = 2 * K;

      if (gt_verbose || this.verbose) begin
        $display("[%s] cfg: allow_override=%0d mode=%s thresh8=%0d K=%0d",
                 this.name, allow_override, mode_to_string(this.mode), this.thresh8, K);
        $display("[%s] files: x='%s' y='%s' sup='%s' metrics='%s'",
                 this.name, x_file, y_file, sup_file, metrics_file);
        $display("[%s] checks: x=%0d pairs=%0d y_stream=%0d metrics=%0d",
                 this.name, check_x, check_pairs, check_y_stream, check_metrics);
      end
    endfunction


    // Override body

    virtual task automatic body();
      load_goldens();
      run_and_check();
    endtask


    // Load golden artifacts

    task automatic load_goldens();
      int unsigned pairs_in_files;
      begin
        if (K == 0) $fatal(1, "[%s] K==0 not allowed for golden test.", name);

        if (check_x) begin
          if (!file_exists(x_file)) $fatal(1, "[%s] Missing x.memh file: '%s'", name, x_file);
          x_g.delete();
          read_memh_signed(x_file, N, x_g);
          if (x_g.size() < NSAMP) begin
            $fatal(1, "[%s] x.memh too short: have %0d need %0d", name, x_g.size(), NSAMP);
          end
        end

        // Pair/y checks need y + sup
        if (check_pairs || check_y_stream) begin
          if (!file_exists(y_file)) $fatal(1, "[%s] Missing y.memh file: '%s'", name, y_file);
          if (!file_exists(sup_file)) $fatal(1, "[%s] Missing sup.memh file: '%s'", name, sup_file);

          y_g.delete();
          sup_g.delete();

          read_memh_signed(y_file, N, y_g);
          read_flags01(sup_file, sup_g);

          if ((y_g.size() % 2) != 0) begin
            $fatal(1, "[%s] y.memh length must be even; got %0d", name, y_g.size());
          end

          pairs_in_files = y_g.size() / 2;

          if (pairs_in_files < K) begin
            $fatal(1, "[%s] y.memh too short: have %0d pairs need %0d", name, pairs_in_files, K);
          end

          if (sup_g.size() < K) begin
            $fatal(1, "[%s] sup.memh too short: have %0d flags need %0d", name, sup_g.size(), K);
          end
        end

        if (check_metrics) begin
          if (!file_exists(metrics_file)) $fatal(1, "[%s] Missing metrics.json file: '%s'", name, metrics_file);
          read_metrics_json(metrics_file, met_tp, met_sp, met_abs, met_sq);
          metrics_loaded = 1'b1;

          if (met_tp != ui64_t'(K)) begin
            $fatal(1, "[%s] metrics.json total_pairs=%0d does not match configured K=%0d. (Use matching metrics.json or +GT_NO_METRICS_CHECK.)",
                   name, met_tp, K);
          end

          if (gt_verbose || this.verbose) begin
            $display("[%s] metrics.json: tp=%0d sp=%0d abs=%0d sq=%0d",
                     name, met_tp, met_sp, met_abs, met_sq);
          end
        end
      end
    endtask


    // Main run + checks
    
    task automatic run_and_check();
      int unsigned samp_idx;
      int unsigned pair_idx;
      int unsigned y_idx;

      // metrics snapshot at tp==K
      bit   metrics_checked;
      ui64_t dut_tp, dut_sp, dut_abs, dut_sq;

      int unsigned tick_cnt;
      int unsigned max_ticks;

      begin
        // Apply the golden config
        drv.set_mode_and_threshold(this.mode, this.thresh8);
        drv.apply_reset(this.reset_hold_cycles);

        // Sanity: ensure we're not in bypass (unless user forced it)
        if (!allow_override) begin
          if (t.force_bypass !== 1'b0) $fatal(1, "[%s] Expected force_bypass=0 for golden run, got %b", name, t.force_bypass);
          if (t.thresh_used !== ui64_t'(16)) $fatal(1, "[%s] Expected thresh_used=16 for golden run, got %0d", name, t.thresh_used);
        end

        samp_idx = 0;
        pair_idx = 0;
        y_idx    = 0;

        metrics_checked = 1'b0;
        dut_tp = 0; dut_sp = 0; dut_abs = 0; dut_sq = 0;

        // We expect to need NSAMP+2 sample ticks to see NSAMP y_valid pops,
        // due to the initial empty FIFO behavior.
        max_ticks = NSAMP + 16;

        $display("[%s] Starting golden checks: need x_samples=%0d pairs=%0d y_samples=%0d (max_sample_ticks=%0d)",
                 name, (check_x?NSAMP:0), (check_pairs?K:0), (check_y_stream?NSAMP:0), max_ticks);
        // Prime the checkers with the sample already present before the first wait.
        // Debug proved x_stream is already at the first golden sample here.
        @(negedge t.clk);

         if (check_x && (samp_idx < NSAMP)) begin
             si64_t dut_x;
             dut_x = si64_t'($signed(t.x_stream));
         if (dut_x !== x_g[samp_idx]) begin
            $fatal(1, "[%s] X MISMATCH @sample %0d: dut=%s exp=%s",
               name, samp_idx, fmt_si64(dut_x), fmt_si64(x_g[samp_idx]));
          end
            samp_idx++;
             end
        for (tick_cnt = 0;
             tick_cnt < max_ticks && ((check_x && (samp_idx < NSAMP)) ||
                                      (check_pairs && (pair_idx < K)) ||
                                      (check_y_stream && (y_idx < NSAMP)) ||
                                      (check_metrics && !metrics_checked));
             tick_cnt++) begin

   // If we're already inside an asserted sample tick, don't skip it.
   // Otherwise wait for the next sample tick.
        if (!t.sample_en) begin
            drv.wait_sample_tick(this.timeout_clks);
        end

    // Sample at negedge for race-free viewing after all posedge NBAs settle
          @(negedge t.clk);

          // X stream check

          if (check_x && (samp_idx < NSAMP)) begin
            si64_t dut_x;
            dut_x = si64_t'($signed(t.x_stream));
            if (dut_x !== x_g[samp_idx]) begin
              $fatal(1, "[%s] X MISMATCH @sample %0d: dut=%s exp=%s",
                     name, samp_idx, fmt_si64(dut_x), fmt_si64(x_g[samp_idx]));
            end
            samp_idx++;
          end


          // Pair-domain check (y0/y1 + suppressed)
          
          if (t.pair_out_valid === 1'b1) begin
            if (check_pairs && (pair_idx < K)) begin
              si64_t dut_y0, dut_y1;
              si64_t exp_y0, exp_y1;
              si64_t dut_x0a, dut_x1a;

              dut_y0 = si64_t'($signed(t.y0));
              dut_y1 = si64_t'($signed(t.y1));
              exp_y0 = y_g[2*pair_idx + 0];
              exp_y1 = y_g[2*pair_idx + 1];

              if (dut_y0 !== exp_y0) begin
                $fatal(1, "[%s] Y0 MISMATCH @pair %0d: dut=%s exp=%s",
                       name, pair_idx, fmt_si64(dut_y0), fmt_si64(exp_y0));
              end
              if (dut_y1 !== exp_y1) begin
                $fatal(1, "[%s] Y1 MISMATCH @pair %0d: dut=%s exp=%s",
                       name, pair_idx, fmt_si64(dut_y1), fmt_si64(exp_y1));
              end

              // suppression flag
              if ((t.suppressed === 1'b1) !== sup_g[pair_idx]) begin
                $fatal(1, "[%s] SUP FLAG MISMATCH @pair %0d: dut=%0d exp=%0d (abs_d=%0d T=%0d)",
                       name, pair_idx, (t.suppressed===1'b1), sup_g[pair_idx], t.abs_d_tap, t.thresh_used);
              end

              // aligned x check if we loaded x.memh
              if (check_x) begin
                dut_x0a = si64_t'($signed(t.x0_a));
                dut_x1a = si64_t'($signed(t.x1_a));

                if (dut_x0a !== x_g[2*pair_idx + 0]) begin
                  $fatal(1, "[%s] X0_A MISMATCH @pair %0d: dut=%s exp=%s",
                         name, pair_idx, fmt_si64(dut_x0a), fmt_si64(x_g[2*pair_idx + 0]));
                end
                if (dut_x1a !== x_g[2*pair_idx + 1]) begin
                  $fatal(1, "[%s] X1_A MISMATCH @pair %0d: dut=%s exp=%s",
                         name, pair_idx, fmt_si64(dut_x1a), fmt_si64(x_g[2*pair_idx + 1]));
                end
              end

              pair_idx++;
            // Stop cleanly once we've checked all expected pairs.
             // Prevents monitors/scoreboards from running past end-of-memh.
              // if (pair_idx >= K) begin
              // $display("[%s] Checked all pairs (K=%0d). Stopping simulation.", name, K);
                // $finish;
                 //end
            end
          end


          // Serialized y_out stream check

          if (t.y_valid === 1'b1) begin
            if (check_y_stream && (y_idx < NSAMP)) begin
              si64_t dut_y;
              dut_y = si64_t'($signed(t.y_out));
              if (dut_y !== y_g[y_idx]) begin
                $fatal(1, "[%s] Y_STREAM MISMATCH @y_idx %0d: dut=%s exp=%s",
                       name, y_idx, fmt_si64(dut_y), fmt_si64(y_g[y_idx]));
              end
            end
            if (check_y_stream && (y_idx < NSAMP)) y_idx++;
          end


          // Metrics snapshot check when total_pairs reaches K

          if (check_metrics && !metrics_checked) begin
            if (t.total_pairs === K[31:0]) begin
              // Snapshot counters at this moment
              dut_tp  = ui64_t'(t.total_pairs);
              dut_sp  = ui64_t'(t.suppressed_pairs);
              dut_abs = ui64_t'(t.sum_abs_err);
              dut_sq  = ui64_t'(t.sum_sq_err);

              if (!metrics_loaded) $fatal(1, "[%s] Internal error: metrics_loaded=0 but check_metrics=1", name);

              if ((dut_tp  != met_tp)  ||
                  (dut_sp  != met_sp)  ||
                  (dut_abs != met_abs) ||
                  (dut_sq  != met_sq)) begin
                $fatal(1, "[%s] METRICS MISMATCH at tp==%0d: dut(tp,sp,abs,sq)=(%0d,%0d,%0d,%0d) exp=(%0d,%0d,%0d,%0d)",
                       name, K,
                       dut_tp, dut_sp, dut_abs, dut_sq,
                       met_tp, met_sp, met_abs, met_sq);
              end else begin
                $display("[%s] METRICS MATCH at tp==%0d: (tp,sp,abs,sq)=(%0d,%0d,%0d,%0d)",
                         name, K, dut_tp, dut_sp, dut_abs, dut_sq);
              end

              metrics_checked = 1'b1;
            end
          end
        end


        // Final expectations

        if (check_x && (samp_idx != NSAMP)) begin
          $fatal(1, "[%s] Did not check all x samples: checked=%0d expected=%0d", name, samp_idx, NSAMP);
        end
        if (check_pairs && (pair_idx != K) && (t.total_pairs < K)) begin
          $fatal(1, "[%s] Did not check all pairs: checked=%0d expected=%0d", name, pair_idx, K);
        end
        if (check_y_stream && (y_idx != NSAMP)) begin
          $fatal(1, "[%s] Did not check all y_out samples: checked=%0d expected=%0d (try increasing max_ticks?)",
                 name, y_idx, NSAMP);
        end
        if (check_metrics && !metrics_checked) begin
          $fatal(1, "[%s] Metrics check never triggered (total_pairs never reached %0d in time).", name, K);
        end

        // Record one result row (using the snapshot values if metrics were checked,
        // otherwise record current metrics at end-of-test)
        begin
          trial_result_t r;
          ui64_t tp_end, sp_end, abs_end, sq_end;

          tp_end  = ui64_t'(t.total_pairs);
          sp_end  = ui64_t'(t.suppressed_pairs);
          abs_end = ui64_t'(t.sum_abs_err);
          sq_end  = ui64_t'(t.sum_sq_err);

          r.trial_id = 0;
          r.mode     = this.mode;
          r.thresh8  = this.thresh8;
          r.pairs_req= K;

          if (metrics_checked) begin
            r.dut_total_pairs      = dut_tp;
            r.dut_suppressed_pairs = dut_sp;
            r.dut_sum_abs_err      = dut_abs;
            r.dut_sum_sq_err       = dut_sq;
            r.suppressed_ratio     = (dut_tp != 0) ? (real'(dut_sp) / real'(dut_tp)) : 0.0;
          end else begin
            r.dut_total_pairs      = tp_end;
            r.dut_suppressed_pairs = sp_end;
            r.dut_sum_abs_err      = abs_end;
            r.dut_sum_sq_err       = sq_end;
            r.suppressed_ratio     = (tp_end != 0) ? (real'(sp_end) / real'(tp_end)) : 0.0;
          end

          r.end_time = $time;

          results.push_back(r);
        end

        $display("[%s] PASS: golden THRESH=16 checks completed (x/pairs/y_stream/metrics).", name);
      end
    endtask

  endclass : test_golden_thresh16

endpackage : tests_golden_pkg

`endif // TEST_GOLDEN_THRESH16_SV

`default_nettype wire
