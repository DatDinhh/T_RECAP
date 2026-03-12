`timescale 1ns/1ps
`default_nettype none

// Arizona State University 
// Capstone Senior Project
// Sigma Force
// Dat Dinh, Dat Huynh, Paul Applebee, Kyung Jae Son
// scoreboard_pairs.sv
//
// Fully functional pair-domain scoreboard for t_recap_demo_top.
//
// Compares DUT pair outputs (y0,y1,suppressed) on pair_out_valid against
// one or both references:
//
//   - MEMH reference: x.memh, y.memh, sup.memh
//   - MODEL reference: ref_model_phase1 (lockstep stepped on sample_en)
//
// It also optionally checks:
//   - x0_a/x1_a alignment versus reference x0/x1
//   - suppression rule: suppressed == (abs_d_tap < thresh_used)  (strict <)
//   - lossless property when thresh_used==0: suppressed==0 and y==x
//
// The scoreboard is self-contained: it reads memh files directly if MEMH
// mode is enabled, and it instantiates a ref_model_phase1 if MODEL mode
// is enabled.
//
// Sampling strategy:
//   - All comparisons occur on negedge t.clk to avoid race with DUT posedge FF updates.
//   - The model is stepped on negedge when sample_en is observed (same convention as
//     x_stream_monitor) so that expected streams align with the values observed on taps.
//
// Plusargs:
//
//   +PAIR_SB_DISABLE
//   +PAIR_SB_MODE=memh|model|both|off
//
//   +PAIR_SB_X_FILE=<path>         (default "x.memh")   [also honors +X_MEMH]
//   +PAIR_SB_Y_FILE=<path>         (default "y.memh")   [also honors +Y_MEMH]
//   +PAIR_SB_SUP_FILE=<path>       (default "sup.memh") [also honors +SUP_MEMH]
//
//   +PAIR_SB_MAX_ERR=<N>           (default 10; 0 = never fatal due to count)
//   +PAIR_SB_STOP_ON_ERR
//   +PAIR_SB_VERBOSE
//
//   +PAIR_SB_CHECK_X_ALIGN         (default ON in MODEL/BOTH, OFF in MEMH-only)
//   +PAIR_SB_NO_CHECK_X_ALIGN
//
//   +PAIR_SB_CHECK_RULE            (check suppressed == (abs_d_tap < thresh_used))
//   +PAIR_SB_CHECK_LOSSLESS_T0     (if thresh_used==0, enforce y==x and sup==0)
//
//   +PAIR_SB_EPOCH_ON_CLEAR        (track epochs on clr_metrics_pulse rising edge) [default ON]
//   +PAIR_SB_NO_EPOCH_ON_CLEAR
//
// Notes:
//  - In MEMH mode, the scoreboard uses pair index k to compare:
//        y_exp[2*k], y_exp[2*k+1], sup_exp[k], x_exp[2*k], x_exp[2*k+1]
//  - In MODEL mode, the scoreboard keeps a small expected-pair queue fed by the model.


module scoreboard_pairs #(
  parameter int N      = 12,
  parameter int SHIFT  = 3,
  parameter int LFSR_W = 16,
  parameter logic [LFSR_W-1:0] SEED = 16'hACE1,
  parameter bit AUTO_START = 1'b1
)(
  tap_if t
);

  import tb_pkg::*;

  
  // Mode enum

  typedef enum int {MODE_OFF=0, MODE_MEMH=1, MODE_MODEL=2, MODE_BOTH=3} mode_e;
  mode_e mode;


  // Configuration

  bit disabled;
  bit verbose;

  int unsigned max_err;
  bit stop_on_err;

  bit check_x_align;
  bit check_rule;
  bit check_lossless_t0;

  bit epoch_on_clear;

  string x_file;
  string y_file;
  string sup_file;


  // Golden arrays (MEMH reference)

  si64_t x_exp[$];
  si64_t y_exp[$];
  bit    sup_exp[$];


  // Model reference (MODEL reference)

  ref_model_phase1 #(
    .N(N),
    .SHIFT(SHIFT),
    .LFSR_W(LFSR_W),
    .SEED_DEFAULT(SEED)
  ) rm();

  typedef struct packed {
    si64_t x0;
    si64_t x1;
    si64_t y0;
    si64_t y1;
    bit    sup;
    ui64_t thresh_used;
  } exp_pair_t;

  exp_pair_t expq[$];

  bit    ref_have_x0;
  si64_t ref_x0_hold;


  // Runtime bookkeeping

  bit running;
  bit stop_req;

  int unsigned k;          // pair index since last reset (and maybe across clear)
  int unsigned epoch;      // increments on clr_metrics_pulse rising edge (optional)
  int unsigned err_count;

  // event for each compared pair
  event sb_pair_ev;

  // last compared snapshot (for external tests if desired)
  int unsigned last_k;
  int unsigned last_epoch;
  longint unsigned last_time;

  si64_t last_act_x0;
  si64_t last_act_x1;
  si64_t last_act_y0;
  si64_t last_act_y1;
  bit    last_act_sup;

  bit    last_have_memh;
  bit    last_have_model;

  si64_t last_exp_memh_y0, last_exp_memh_y1;
  bit    last_exp_memh_sup;
  si64_t last_exp_memh_x0, last_exp_memh_x1;

  si64_t last_exp_model_y0, last_exp_model_y1;
  bit    last_exp_model_sup;
  si64_t last_exp_model_x0, last_exp_model_x1;


  // Helpers

  function automatic mode_e _parse_mode(input string s);
    if (s == "off" || s == "0" || s == "disable" || s == "disabled") _parse_mode = MODE_OFF;
    else if (s == "memh" || s == "file")                              _parse_mode = MODE_MEMH;
    else if (s == "model" || s == "predict" || s == "pred")           _parse_mode = MODE_MODEL;
    else if (s == "both" || s == "all")                               _parse_mode = MODE_BOTH;
    else                                                              _parse_mode = MODE_MEMH;
  endfunction

  function automatic bit _file_exists(input string path);
    int fd;
    begin
      fd = $fopen(path, "r");
      if (fd == 0) _file_exists = 1'b0;
      else begin
        _file_exists = 1'b1;
        $fclose(fd);
      end
    end
  endfunction

  task automatic _fatal_or_count(input string msg);
    begin
      err_count++;
      $display("[scoreboard_pairs] ERROR[%0d] k=%0d epoch=%0d : %s", err_count, k, epoch, msg);
      if (stop_on_err || (max_err != 0 && err_count >= max_err)) begin
        $fatal(1, "[scoreboard_pairs] Too many errors (err_count=%0d, max_err=%0d).", err_count, max_err);
      end
    end
  endtask


  // Public control/tasks
  
  task automatic start();
    if (running) begin
      $display("[scoreboard_pairs] NOTE: start() called but already running.");
      return;
    end
    stop_req = 1'b0;
    running  = 1'b1;
    fork
      run();
    join_none
  endtask

  task automatic stop();
    stop_req = 1'b1;
  endtask

  function automatic int unsigned get_error_count();
    return err_count;
  endfunction

  task automatic report(input string tag = "scoreboard_pairs");
    $display("[%s] mode=%0d (OFF=0 MEMH=1 MODEL=2 BOTH=3) pairs_checked=%0d epoch=%0d errors=%0d expq_len=%0d",
             tag, mode, k, epoch, err_count, expq.size());
  endtask

  // Optional: ensure model expected queue is empty (useful at end of test).
  task automatic check_no_pending_model_pairs();
    if (mode == MODE_MODEL || mode == MODE_BOTH) begin
      if (expq.size() != 0) begin
        $fatal(1, "[scoreboard_pairs] Pending expected pairs in model queue: %0d", expq.size());
      end
    end
  endtask

  // Wait for the next compared pair (event-based).
  task automatic wait_next_checked_pair(
    output int unsigned k_out,
    output int unsigned epoch_out,
    output si64_t       act_y0,
    output si64_t       act_y1,
    output bit          act_sup
  );
    begin
      @sb_pair_ev;
      k_out     = last_k;
      epoch_out = last_epoch;
      act_y0    = last_act_y0;
      act_y1    = last_act_y1;
      act_sup   = last_act_sup;
    end
  endtask


  // Initialization

  initial begin
    running   = 1'b0;
    stop_req  = 1'b0;

    k         = 0;
    epoch     = 0;
    err_count = 0;

    expq.delete();
    ref_have_x0 = 1'b0;
    ref_x0_hold = 0;

    // defaults
    disabled   = 1'b0;
    verbose    = 1'b0;
    max_err    = 10;
    stop_on_err= 1'b0;

    check_x_align     = 1'b0;
    check_rule        = 1'b0;
    check_lossless_t0 = 1'b0;

    epoch_on_clear    = 1'b1;

    x_file   = "x.memh";
    y_file   = "y.memh";
    sup_file = "sup.memh";

    // plusargs
    if ($test$plusargs("PAIR_SB_DISABLE")) disabled = 1'b1;
    if ($test$plusargs("PAIR_SB_VERBOSE")) verbose  = 1'b1;

    void'($value$plusargs("PAIR_SB_MAX_ERR=%d", max_err));
    if ($test$plusargs("PAIR_SB_STOP_ON_ERR")) stop_on_err = 1'b1;

    if ($test$plusargs("PAIR_SB_CHECK_RULE"))        check_rule        = 1'b1;
    if ($test$plusargs("PAIR_SB_CHECK_LOSSLESS_T0")) check_lossless_t0 = 1'b1;

    if ($test$plusargs("PAIR_SB_NO_EPOCH_ON_CLEAR")) epoch_on_clear = 1'b0;
    if ($test$plusargs("PAIR_SB_EPOCH_ON_CLEAR"))    epoch_on_clear = 1'b1;

    void'($value$plusargs("PAIR_SB_X_FILE=%s", x_file));
    void'($value$plusargs("PAIR_SB_Y_FILE=%s", y_file));
    void'($value$plusargs("PAIR_SB_SUP_FILE=%s", sup_file));

    // accept loader-style aliases too
    void'($value$plusargs("X_MEMH=%s", x_file));
    void'($value$plusargs("Y_MEMH=%s", y_file));
    void'($value$plusargs("SUP_MEMH=%s", sup_file));

    // Determine mode
    begin
      string mstr;
      mstr = "";
      if ($value$plusargs("PAIR_SB_MODE=%s", mstr)) begin
        mode = _parse_mode(mstr);
      end else begin
        // Default mode:
        // - if y.memh exists -> BOTH (strongest)
        // - else -> MODEL
        if (_file_exists(y_file) && _file_exists(sup_file)) mode = MODE_BOTH;
        else                                               mode = MODE_MODEL;
      end
    end

    if (disabled) mode = MODE_OFF;

    // Default x-align checking:
    // - ON when model is enabled (MODEL/BOTH)
    // - OFF in MEMH-only (optional, can still enable)
    if (mode == MODE_MODEL || mode == MODE_BOTH) check_x_align = 1'b1;

    if ($test$plusargs("PAIR_SB_NO_CHECK_X_ALIGN")) check_x_align = 1'b0;
    if ($test$plusargs("PAIR_SB_CHECK_X_ALIGN"))    check_x_align = 1'b1;

    // Load memh files if needed
    if (mode == MODE_MEMH || mode == MODE_BOTH) begin
      if (!_file_exists(x_file)) $fatal(1, "[scoreboard_pairs] x file not found: '%s'", x_file);
      if (!_file_exists(y_file)) $fatal(1, "[scoreboard_pairs] y file not found: '%s'", y_file);
      if (!_file_exists(sup_file)) $fatal(1, "[scoreboard_pairs] sup file not found: '%s'", sup_file);

      read_memh_signed(x_file, N, x_exp);
      read_memh_signed(y_file, N, y_exp);
      read_flags01(sup_file, sup_exp);

      if (x_exp.size() == 0) $fatal(1, "[scoreboard_pairs] Loaded 0 x samples from '%s'", x_file);
      if (y_exp.size() == 0) $fatal(1, "[scoreboard_pairs] Loaded 0 y samples from '%s'", y_file);
      if ((x_exp.size() % 2) != 0) $fatal(1, "[scoreboard_pairs] x length must be even; got %0d", x_exp.size());
      if ((y_exp.size() % 2) != 0) $fatal(1, "[scoreboard_pairs] y length must be even; got %0d", y_exp.size());

      if (x_exp.size() != y_exp.size()) begin
        $fatal(1, "[scoreboard_pairs] x/y length mismatch: x=%0d y=%0d", x_exp.size(), y_exp.size());
      end
      if (sup_exp.size() != (y_exp.size()/2)) begin
        $fatal(1, "[scoreboard_pairs] sup flags size mismatch: sup=%0d expected=%0d", sup_exp.size(), (y_exp.size()/2));
      end

      $display("[scoreboard_pairs] Loaded memh: x=%0d samples, y=%0d samples, sup=%0d pairs",
               x_exp.size(), y_exp.size(), sup_exp.size());
    end

    // Reset the model to a known starting state (even if mode doesn't use it)
    rm.reset_model(SEED, /*clear_hist*/ 1'b1);
    ref_have_x0 = 1'b0;
    ref_x0_hold = 0;

    if (mode == MODE_OFF) begin
      $display("[scoreboard_pairs] Disabled (mode=OFF).");
    end else begin
      $display("[scoreboard_pairs] Config:");
      $display("  mode=%0d (OFF=0 MEMH=1 MODEL=2 BOTH=3)", mode);
      $display("  files: x='%s' y='%s' sup='%s'", x_file, y_file, sup_file);
      $display("  check_x_align=%0d check_rule=%0d check_lossless_t0=%0d epoch_on_clear=%0d",
               check_x_align, check_rule, check_lossless_t0, epoch_on_clear);
      $display("  max_err=%0d stop_on_err=%0d verbose=%0d", max_err, stop_on_err, verbose);
      $display("  N=%0d SHIFT=%0d LFSR_W=%0d SEED=0x%0h", N, SHIFT, LFSR_W, SEED);
    end

    if (AUTO_START && mode != MODE_OFF) begin
      start();
    end
  end


  // Main run loop

  task automatic run();
    bit last_rst_n;
    bit last_clr;

    // model step outputs
    bit    xv, pv;
    samp_t x_out;
    samp_t y0_out, y1_out;
    bit    sup_out;

    // local hold for x1 in model pairing
    si64_t ref_x1_hold;

    // expected pair object from model queue
    exp_pair_t expm;

    // actual signals
    si64_t act_x0, act_x1;
    si64_t act_y0, act_y1;
    bit    act_sup;

    // memh expected
    si64_t exp_y0m, exp_y1m;
    bit    exp_supm;
    si64_t exp_x0m, exp_x1m;

    // suppression rule expected
    bit rule_sup;

    // threshold/bypass
    ui64_t thresh_u;
    bit    bypass;

    begin
      last_rst_n = 1'b1;
      last_clr   = 1'b0;

      // Wait for clock to be known
      wait (^t.clk !== 1'bX);

      forever begin
        @(negedge t.clk);

        if (stop_req) begin
          $display("[scoreboard_pairs] stop requested.");
          running = 1'b0;
          disable run;
        end

        // Reset handling
        if (!t.rst_n) begin
          if (last_rst_n) begin
            k = 0;
            epoch = 0;
            err_count = 0;
            expq.delete();

            rm.reset_model(SEED, /*clear_hist*/ 1'b1);
            ref_have_x0 = 1'b0;
            ref_x0_hold = 0;

            if (verbose) $display("[scoreboard_pairs] Reset asserted: counters/model cleared.");
          end
          last_rst_n = 1'b0;
          last_clr   = 1'b0;
          continue;
        end
        last_rst_n = 1'b1;

        // Clear pulse epoch tracking (optional)
        if (epoch_on_clear) begin
          if (t.clr_metrics_pulse && !last_clr) begin
            epoch++;
            if (verbose) $display("[scoreboard_pairs] clr_metrics_pulse: epoch -> %0d (k continues).", epoch);
          end
          last_clr = t.clr_metrics_pulse;
        end


        // MODEL: step on sample_en

        if (mode == MODE_MODEL || mode == MODE_BOTH) begin
          if (t.sample_en === 1'b1) begin
            bypass   = (t.force_bypass === 1'b1);
            thresh_u = ui64_t'(t.thresh_used);

            rm.step_sample(int'(thresh_u), bypass, xv, x_out, pv, y0_out, y1_out, sup_out);

            // We always get x_valid (xv) for sample_en. If not, something is wrong.
            if (!xv) begin
              _fatal_or_count("ref_model returned x_valid=0 on sample_en (unexpected)");
            end

            // Track x0/x1 for alignment (mirror the model's internal pairing)
            if (!ref_have_x0) begin
              ref_x0_hold = si64_t'($signed(x_out));
              ref_have_x0 = 1'b1;

              if (pv) begin
                _fatal_or_count("ref_model returned pair_valid=1 unexpectedly on first sample of pair");
              end
            end else begin
              ref_x1_hold = si64_t'($signed(x_out));
              ref_have_x0 = 1'b0;

              if (!pv) begin
                _fatal_or_count("ref_model returned pair_valid=0 unexpectedly on second sample of pair");
              end else begin
                // push expected pair into queue for future pair_out_valid comparison
                expm.x0 = ref_x0_hold;
                expm.x1 = ref_x1_hold;
                expm.y0 = si64_t'($signed(y0_out));
                expm.y1 = si64_t'($signed(y1_out));
                expm.sup = sup_out;
                expm.thresh_used = thresh_u;
                expq.push_back(expm);
              end
            end
          end
        end


        // Compare on pair_out_valid

        if (t.pair_out_valid !== 1'b1) begin
          continue;
        end

        // Basic X checks
        if (^t.y0 === 1'bX || ^t.y1 === 1'bX || ^t.suppressed === 1'bX) begin
          _fatal_or_count("y0/y1/suppressed contains X on pair_out_valid");
        end
        if (^t.x0_a === 1'bX || ^t.x1_a === 1'bX) begin
          _fatal_or_count("x0_a/x1_a contains X on pair_out_valid");
        end

        // Actual values
        act_x0  = si64_t'($signed(t.x0_a));
        act_x1  = si64_t'($signed(t.x1_a));
        act_y0  = si64_t'($signed(t.y0));
        act_y1  = si64_t'($signed(t.y1));
        act_sup = (t.suppressed === 1'b1);

        // Save last snapshot
        last_k      = k;
        last_epoch  = epoch;
        last_time   = $time;
        last_act_x0 = act_x0;
        last_act_x1 = act_x1;
        last_act_y0 = act_y0;
        last_act_y1 = act_y1;
        last_act_sup= act_sup;

        last_have_memh  = 1'b0;
        last_have_model = 1'b0;

        // MEMH reference comparison
        if (mode == MODE_MEMH || mode == MODE_BOTH) begin
          last_have_memh = 1'b1;
            if ((2*k + 1) >= y_exp.size()) begin
             if (verbose) $display("[scoreboard_pairs] Completed all %0d expected pairs; stopping.", y_exp.size()/2);
              running = 1'b0;
                disable run;
          end else begin
            exp_y0m  = y_exp[2*k+0];
            exp_y1m  = y_exp[2*k+1];
            exp_supm = sup_exp[k];
            exp_x0m  = x_exp[2*k+0];
            exp_x1m  = x_exp[2*k+1];

            last_exp_memh_y0  = exp_y0m;
            last_exp_memh_y1  = exp_y1m;
            last_exp_memh_sup = exp_supm;
            last_exp_memh_x0  = exp_x0m;
            last_exp_memh_x1  = exp_x1m;

            if (act_y0 != exp_y0m || act_y1 != exp_y1m || act_sup != exp_supm) begin
              _fatal_or_count($sformatf(
                "MEMH mismatch: dut(y0,y1,sup)=(%s,%s,%0d) exp=(%s,%s,%0d)",
                fmt_si64(act_y0), fmt_si64(act_y1), act_sup,
                fmt_si64(exp_y0m), fmt_si64(exp_y1m), exp_supm
              ));
            end else if (verbose) begin
              $display("[scoreboard_pairs] k=%0d MEMH OK y0=%0d y1=%0d sup=%0d", k, act_y0, act_y1, act_sup);
            end

            if (check_x_align) begin
              if (act_x0 != exp_x0m || act_x1 != exp_x1m) begin
                _fatal_or_count($sformatf(
                  "MEMH x-align mismatch: dut(x0_a,x1_a)=(%s,%s) exp=(%s,%s)",
                  fmt_si64(act_x0), fmt_si64(act_x1),
                  fmt_si64(exp_x0m), fmt_si64(exp_x1m)
                ));
              end
            end
          end
        end

        // MODEL reference comparison
        if (mode == MODE_MODEL || mode == MODE_BOTH) begin
          last_have_model = 1'b1;

          if (expq.size() == 0) begin
            _fatal_or_count("MODEL expected queue empty at pair_out_valid (model/DUT misalignment)");
          end else begin
            expm = expq.pop_front();

            last_exp_model_x0  = expm.x0;
            last_exp_model_x1  = expm.x1;
            last_exp_model_y0  = expm.y0;
            last_exp_model_y1  = expm.y1;
            last_exp_model_sup = expm.sup;

            if (act_y0 != expm.y0 || act_y1 != expm.y1 || act_sup != expm.sup) begin
              _fatal_or_count($sformatf(
                "MODEL mismatch: dut(y0,y1,sup)=(%s,%s,%0d) exp=(%s,%s,%0d) (thresh_used=%0d bypass=%0d)",
                fmt_si64(act_y0), fmt_si64(act_y1), act_sup,
                fmt_si64(expm.y0), fmt_si64(expm.y1), expm.sup,
                ui64_t'(t.thresh_used), (t.force_bypass===1'b1)
              ));
            end else if (verbose) begin
              $display("[scoreboard_pairs] k=%0d MODEL OK y0=%0d y1=%0d sup=%0d", k, act_y0, act_y1, act_sup);
            end

            if (check_x_align) begin
              if (act_x0 != expm.x0 || act_x1 != expm.x1) begin
                _fatal_or_count($sformatf(
                  "MODEL x-align mismatch: dut(x0_a,x1_a)=(%s,%s) exp=(%s,%s)",
                  fmt_si64(act_x0), fmt_si64(act_x1),
                  fmt_si64(expm.x0), fmt_si64(expm.x1)
                ));
              end
            end
          end
        end

        // Cross-check MEMH vs MODEL expected if both enabled
        if (mode == MODE_BOTH && last_have_memh && last_have_model) begin
          if (last_exp_memh_y0 != last_exp_model_y0 ||
              last_exp_memh_y1 != last_exp_model_y1 ||
              last_exp_memh_sup != last_exp_model_sup) begin
            _fatal_or_count($sformatf(
              "REF mismatch (memh vs model): memh(y0,y1,sup)=(%s,%s,%0d) model=(%s,%s,%0d)",
              fmt_si64(last_exp_memh_y0), fmt_si64(last_exp_memh_y1), last_exp_memh_sup,
              fmt_si64(last_exp_model_y0), fmt_si64(last_exp_model_y1), last_exp_model_sup
            ));
          end
        end

        // Optional suppression rule check (strict inequality)
        if (check_rule) begin
            if ((^t.abs_d_tap !== 1'bX) && (^t.thresh_used !== 1'bX)) begin
               rule_sup = (t.abs_d_tap < t.thresh_used);
            if (rule_sup != act_sup) begin
              _fatal_or_count($sformatf(
                "suppression rule mismatch: suppressed=%0d but (abs_d<thresh)=%0d  abs_d=%0d thresh=%0d",
                act_sup, rule_sup, t.abs_d_tap, t.thresh_used
              ));
            end
          end else begin
            _fatal_or_count("check_rule enabled but abs_d_tap or thresh_used is X/unknown");
          end
        end

        // Optional lossless check when thresh_used == 0
        if (check_lossless_t0) begin
          if (t.thresh_used == '0) begin
            if (act_sup != 1'b0) begin
              _fatal_or_count("lossless T=0 violated: suppressed asserted when thresh_used==0");
            end
            if (act_y0 != act_x0 || act_y1 != act_x1) begin
              _fatal_or_count($sformatf(
                "lossless T=0 violated: y!=x when thresh_used==0: (x0,x1)=(%s,%s) (y0,y1)=(%s,%s)",
                fmt_si64(act_x0), fmt_si64(act_x1), fmt_si64(act_y0), fmt_si64(act_y1)
              ));
            end
          end
        end

        // Publish event and increment pair index
        -> sb_pair_ev;
        k++;
     end
    end
  endtask


  // End-of-sim summary

  final begin
    if (mode != MODE_OFF) begin
      report("scoreboard_pairs_final");
    end
  end

endmodule : scoreboard_pairs

`default_nettype wire
