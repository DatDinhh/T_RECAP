`timescale 1ns/1ps
`default_nettype none

// Arizona State University 
// Capstone Senior Project
// Sigma Force
// Dat Dinh, Dat Huynh, Paul Applebee, Kyung Jae Son
// metrics_monitor.sv
//
// Fully functional monitor/checker for the DUT metrics counters:
//
//   total_pairs      (32-bit)
//   suppressed_pairs (32-bit)
//   sum_abs_err      (32-bit)
//   sum_sq_err       (48-bit)
//
// This monitor does two things:
//
// (A) Cycle-accurate validation of the *metrics_accum* RTL behavior
//     by re-computing the metric increments from the tapped signals
//     (x0_a/x1_a/y0/y1/suppressed) and comparing against the DUT counters.
//
//     IMPORTANT PIPELINE NOTE (matches the RTL in t_recap_demo_top.sv):
//       - metrics_accum increments on posedge when pair_out_valid was HIGH
//         in the *previous* cycle (because pair_out_valid/y0/y1/... are
//         updated with nonblocking assignments in haar_core).
//       - metrics_accum clears on posedge when clr_pulse was HIGH in the
//         *previous* cycle (same NBA timing reason).
//
//     Therefore this monitor uses a 1-cycle delayed ("prev") copy of:
//       prev_pair_out_valid, prev_suppressed, prev_x0_a, prev_x1_a, prev_y0, prev_y1,
//       prev_clr_metrics_pulse
//     to predict what the DUT counters should be *after the current posedge*.
//
// (B) Optional final check against metrics.json (golden sign-off numbers)
//     for the canonical Phase-1 run.
//
// Plusargs:
//   +MET_MON_DISABLE                : disable monitor
//   +MET_MON_VERBOSE                : print per-update info
//   +MET_MON_MAX_ERR=<N>            : max mismatches before fatal (default 10; 0=never)
//   +MET_MON_STOP_ON_ERR            : fatal on first mismatch
//
//   +MET_MON_CHECK_CYCLE            : enable cycle-by-cycle checking (default ON)
//   +MET_MON_NO_CHECK_CYCLE         : disable cycle checking
//
//   +MET_MON_CHECK_JSON             : enable metrics.json checks (default ON if file exists)
//   +MET_MON_NO_CHECK_JSON          : disable json checks
//   +MET_MON_AUTO_FINAL             : when exp_total_pairs reaches json_total_pairs (epoch 0),
//                                     perform a one-time final check and fatal on mismatch.
//
//   +MET_MON_METRICS_FILE=<path>    : metrics.json path (default "metrics.json")
//   +METRICS_JSON=<path>            : alias
//
//   +MET_MON_RESET_ERR_ON_CLEAR      : reset internal error counter when a clear occurs
//   +MET_MON_CHECK_INVARIANTS        : check suppressed_pairs<=total_pairs and basic sanity
//   +MET_MON_CHECK_LOSSLESS_T0       : if thresh_used==0 at a pair, assert e0=e1=0 and suppressed=0
//
// Public outputs/events for TB:
//   - event met_ev;                  : triggers after each comparison update
//   - last_* fields updated before met_ev
//   - tasks: report(), check_final_against_json(), check_now_against_values()


module metrics_monitor #(
  parameter int N      = 12,
  parameter int LFSR_W = 16,
  parameter bit AUTO_START = 1'b1
)(
  tap_if t
);

  import tb_pkg::*;


  // Event + last snapshot

  event met_ev;

  int unsigned last_epoch;
  longint unsigned last_time;

  // last observed DUT counters (as integers)
  ui64_t last_dut_total_pairs;
  ui64_t last_dut_suppressed_pairs;
  ui64_t last_dut_sum_abs_err;
  ui64_t last_dut_sum_sq_err;

  // last expected counters (as integers)
  ui64_t last_exp_total_pairs;
  ui64_t last_exp_suppressed_pairs;
  ui64_t last_exp_sum_abs_err;
  ui64_t last_exp_sum_sq_err;


  // Config

  bit disabled;
  bit verbose;

  int unsigned max_err;
  bit stop_on_err;

  bit check_cycle;
  bit check_json;
  bit auto_final;

  bit reset_err_on_clear;
  bit check_invariants;
  bit check_lossless_T0;

  string metrics_file;


  // Loaded JSON expectations 

  bit   json_valid;
  ui64_t json_total_pairs;
  ui64_t json_suppressed_pairs;
  ui64_t json_sum_abs_err;
  ui64_t json_sum_sq_err;

  bit final_checked;


  // Internal expected counters (match DUT widths via masking)

  ui64_t exp_total_pairs;
  ui64_t exp_suppressed_pairs;
  ui64_t exp_sum_abs_err;
  ui64_t exp_sum_sq_err;

  // Width masks (for wraparound-safe modeling)
  localparam ui64_t MASK32 = 64'hFFFF_FFFF;
  localparam ui64_t MASK48 = (ui64_t'(1) << 48) - ui64_t'(1);

  
  // Delayed ("prev") input snapshots used to model NBA timing

  bit   prev_clr;
  bit   prev_pair_out_valid;
  bit   prev_suppressed;

  si64_t prev_x0;
  si64_t prev_x1;
  si64_t prev_y0;
  si64_t prev_y1;

  ui64_t prev_thresh_used; // for optional lossless check only


  // Runtime

  bit running;
  bit stop_req;
  int unsigned epoch;
  int unsigned err_count;


  // Helpers

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
      $display("[metrics_monitor] ERROR[%0d] epoch=%0d : %s", err_count, epoch, msg);
      if (stop_on_err || (max_err != 0 && err_count >= max_err)) begin
        $fatal(1, "[metrics_monitor] Too many errors (err_count=%0d, max_err=%0d).", err_count, max_err);
      end
    end
  endtask

  function automatic ui64_t _dut_u32(input logic [31:0] v);
    _dut_u32 = ui64_t'(v);
  endfunction

  function automatic ui64_t _dut_u48(input logic [47:0] v);
    _dut_u48 = ui64_t'(v);
  endfunction

  function automatic bit _has_x(input logic [31:0] v);
    _has_x = (^v === 1'bX);
  endfunction

  function automatic bit _has_x48(input logic [47:0] v);
    _has_x48 = (^v === 1'bX);
  endfunction


  // Public control tasks

  task automatic start();
    if (running) begin
      $display("[metrics_monitor] NOTE: start() called but already running.");
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

  task automatic report(input string tag = "metrics_monitor");
    $display("[%s] epoch=%0d errors=%0d exp(tp,sp,abs,sq)=(%0d,%0d,%0d,%0d) dut=(%0d,%0d,%0d,%0d)",
             tag, epoch, err_count,
             last_exp_total_pairs, last_exp_suppressed_pairs, last_exp_sum_abs_err, last_exp_sum_sq_err,
             last_dut_total_pairs, last_dut_suppressed_pairs, last_dut_sum_abs_err, last_dut_sum_sq_err);
    if (json_valid) begin
      $display("[%s] json(tp,sp,abs,sq)=(%0d,%0d,%0d,%0d) final_checked=%0d",
               tag, json_total_pairs, json_suppressed_pairs, json_sum_abs_err, json_sum_sq_err, final_checked);
    end
  endtask

  // Check current DUT counters against provided expected values.
  task automatic check_now_against_values(
    input ui64_t exp_tp,
    input ui64_t exp_sp,
    input ui64_t exp_abs,
    input ui64_t exp_sq
  );
    ui64_t dut_tp, dut_sp, dut_abs, dut_sq;
    begin
      if (_has_x(t.total_pairs) || _has_x(t.suppressed_pairs) || _has_x(t.sum_abs_err) || _has_x48(t.sum_sq_err)) begin
        $fatal(1, "[metrics_monitor] check_now_against_values: DUT metrics contain X.");
      end

      dut_tp  = _dut_u32(t.total_pairs);
      dut_sp  = _dut_u32(t.suppressed_pairs);
      dut_abs = _dut_u32(t.sum_abs_err);
      dut_sq  = _dut_u48(t.sum_sq_err);

      if (dut_tp != (exp_tp & MASK32) ||
          dut_sp != (exp_sp & MASK32) ||
          dut_abs!= (exp_abs & MASK32) ||
          dut_sq != (exp_sq & MASK48)) begin
        $fatal(1, "[metrics_monitor] FINAL CHECK FAIL: dut(tp,sp,abs,sq)=(%0d,%0d,%0d,%0d) exp=(%0d,%0d,%0d,%0d)",
               dut_tp, dut_sp, dut_abs, dut_sq,
               (exp_tp & MASK32), (exp_sp & MASK32), (exp_abs & MASK32), (exp_sq & MASK48));
      end else begin
        $display("[metrics_monitor] FINAL CHECK PASS: (tp,sp,abs,sq)=(%0d,%0d,%0d,%0d)",
                 dut_tp, dut_sp, dut_abs, dut_sq);
      end
    end
  endtask

  task automatic check_final_against_json();
    if (!json_valid) begin
      $fatal(1, "[metrics_monitor] check_final_against_json called but json_valid=0 (file='%s')", metrics_file);
    end
    check_now_against_values(json_total_pairs, json_suppressed_pairs, json_sum_abs_err, json_sum_sq_err);
  endtask


  // Initialization (plusargs + optional JSON load)

  initial begin
    running  = 1'b0;
    stop_req = 1'b0;

    epoch = 0;
    err_count = 0;

    // expected counters start at 0
    exp_total_pairs      = 0;
    exp_suppressed_pairs = 0;
    exp_sum_abs_err      = 0;
    exp_sum_sq_err       = 0;

    // prev snapshots
    prev_clr           = 1'b0;
    prev_pair_out_valid= 1'b0;
    prev_suppressed    = 1'b0;

    prev_x0 = 0;
    prev_x1 = 0;
    prev_y0 = 0;
    prev_y1 = 0;
    prev_thresh_used = 0;

    // last snapshots
    last_epoch = 0;
    last_time  = 0;

    last_dut_total_pairs = 0;
    last_dut_suppressed_pairs = 0;
    last_dut_sum_abs_err = 0;
    last_dut_sum_sq_err  = 0;

    last_exp_total_pairs = 0;
    last_exp_suppressed_pairs = 0;
    last_exp_sum_abs_err = 0;
    last_exp_sum_sq_err  = 0;

    // config defaults
    disabled    = 1'b0;
    verbose     = 1'b0;

    max_err     = 10;
    stop_on_err = 1'b0;

    check_cycle = 1'b1;

    metrics_file = "metrics.json";
    void'($value$plusargs("MET_MON_METRICS_FILE=%s", metrics_file));
    void'($value$plusargs("METRICS_JSON=%s", metrics_file));

    // json check default: ON if file exists, else OFF
    check_json  = _file_exists(metrics_file);

    auto_final  = 1'b0;

    reset_err_on_clear = 1'b0;
    check_invariants   = 1'b0;
    check_lossless_T0  = 1'b0;

    // plusargs
    if ($test$plusargs("MET_MON_DISABLE")) disabled = 1'b1;
    if ($test$plusargs("MET_MON_VERBOSE")) verbose  = 1'b1;

    void'($value$plusargs("MET_MON_MAX_ERR=%d", max_err));
    if ($test$plusargs("MET_MON_STOP_ON_ERR")) stop_on_err = 1'b1;

    if ($test$plusargs("MET_MON_NO_CHECK_CYCLE")) check_cycle = 1'b0;
    if ($test$plusargs("MET_MON_CHECK_CYCLE"))    check_cycle = 1'b1;

    if ($test$plusargs("MET_MON_NO_CHECK_JSON")) check_json = 1'b0;
    if ($test$plusargs("MET_MON_CHECK_JSON"))    check_json = 1'b1;

    if ($test$plusargs("MET_MON_AUTO_FINAL")) auto_final = 1'b1;

    if ($test$plusargs("MET_MON_RESET_ERR_ON_CLEAR")) reset_err_on_clear = 1'b1;
    if ($test$plusargs("MET_MON_CHECK_INVARIANTS"))   check_invariants   = 1'b1;
    if ($test$plusargs("MET_MON_CHECK_LOSSLESS_T0"))  check_lossless_T0  = 1'b1;

    // Load JSON if enabled
    json_valid = 1'b0;
    json_total_pairs = 0;
    json_suppressed_pairs = 0;
    json_sum_abs_err = 0;
    json_sum_sq_err  = 0;
    final_checked    = 1'b0;

    if (!disabled && check_json) begin
      if (!_file_exists(metrics_file)) begin
        $fatal(1, "[metrics_monitor] JSON checking enabled but file not found: '%s'", metrics_file);
      end
      read_metrics_json(metrics_file, json_total_pairs, json_suppressed_pairs, json_sum_abs_err, json_sum_sq_err);
      json_valid = 1'b1;
      $display("[metrics_monitor] Loaded metrics.json '%s': tp=%0d sp=%0d abs=%0d sq=%0d",
               metrics_file, json_total_pairs, json_suppressed_pairs, json_sum_abs_err, json_sum_sq_err);
    end

    if (!disabled) begin
      $display("[metrics_monitor] Config:");
      $display("  check_cycle=%0d  check_json=%0d  auto_final=%0d", check_cycle, check_json, auto_final);
      $display("  max_err=%0d stop_on_err=%0d verbose=%0d", max_err, stop_on_err, verbose);
      $display("  reset_err_on_clear=%0d check_invariants=%0d check_lossless_T0=%0d",
               reset_err_on_clear, check_invariants, check_lossless_T0);
      $display("  metrics_file='%s' (exists=%0d)", metrics_file, _file_exists(metrics_file));
    end else begin
      $display("[metrics_monitor] Disabled via +MET_MON_DISABLE.");
    end

    if (!disabled && AUTO_START) begin
      start();
    end
  end

  
  // Core update function: apply one cycle of DUT behavior

  task automatic _apply_prev_to_expected();
    si64_t e0, e1;
    ui64_t ae0, ae1;
    ui64_t sq0, sq1;
    ui64_t add_abs;
    ui64_t add_sq;
    begin
      // Clear has priority over increment, like DUT.
      if (prev_clr) begin
        exp_total_pairs      = 0;
        exp_suppressed_pairs = 0;
        exp_sum_abs_err      = 0;
        exp_sum_sq_err       = 0;

        epoch++;
        if (reset_err_on_clear) err_count = 0;

      end else if (prev_pair_out_valid) begin
        // Optional sanity check: lossless when threshold==0 (bypass)
        if (check_lossless_T0 && (prev_thresh_used == 0)) begin
          if (prev_suppressed !== 1'b0) begin
            _fatal_or_count("lossless T=0 violated: suppressed asserted when thresh_used==0");
          end
          if ((prev_x0 - prev_y0) != 0 || (prev_x1 - prev_y1) != 0) begin
            _fatal_or_count("lossless T=0 violated: x!=y when thresh_used==0");
          end
        end

        // Errors in integer domain
        e0 = prev_x0 - prev_y0;
        e1 = prev_x1 - prev_y1;

        ae0 = abs64(e0);
        ae1 = abs64(e1);

        sq0 = ae0 * ae0;
        sq1 = ae1 * ae1;

        add_abs = (ae0 + ae1);
        add_sq  = (sq0 + sq1);

        // Apply modular arithmetic to match DUT register widths
        exp_total_pairs      = (exp_total_pairs + 1) & MASK32;
        exp_suppressed_pairs = (exp_suppressed_pairs + (prev_suppressed ? 1 : 0)) & MASK32;
        exp_sum_abs_err      = (exp_sum_abs_err + add_abs) & MASK32;
        exp_sum_sq_err       = (exp_sum_sq_err + add_sq) & MASK48;
      end
    end
  endtask


  // Main run loop

  task automatic run();
    bit last_rst_n;

    // observed (current) DUT counters at this negedge
    ui64_t dut_tp, dut_sp, dut_abs, dut_sq;

    // expected after applying previous cycle
    ui64_t exp_tp_next, exp_sp_next, exp_abs_next, exp_sq_next;

    bit inv_ok;

    begin
      last_rst_n = 1'b1;

      // Wait for clock to become known
      wait (^t.clk !== 1'bX);

      forever begin
        @(negedge t.clk);

        if (stop_req) begin
          $display("[metrics_monitor] stop requested.");
          running = 1'b0;
          disable run;
        end

        // Handle async reset (metrics counters are async reset in RTL)
        if (!t.rst_n) begin
          if (last_rst_n) begin
            // reset just asserted
            epoch = 0;
            err_count = 0;

            exp_total_pairs      = 0;
            exp_suppressed_pairs = 0;
            exp_sum_abs_err      = 0;
            exp_sum_sq_err       = 0;

            prev_clr            = 1'b0;
            prev_pair_out_valid = 1'b0;
            prev_suppressed     = 1'b0;
            prev_x0 = 0; prev_x1 = 0; prev_y0 = 0; prev_y1 = 0;
            prev_thresh_used = 0;

            final_checked = 1'b0;

            if (verbose) $display("[metrics_monitor] Reset asserted: expected/state cleared.");
          end
          last_rst_n = 1'b0;

          // Optionally check DUT counters are 0 during reset
          if (check_cycle) begin
            if (!_has_x(t.total_pairs) && _dut_u32(t.total_pairs) != 0) _fatal_or_count("DUT total_pairs not 0 during reset");
            if (!_has_x(t.suppressed_pairs) && _dut_u32(t.suppressed_pairs) != 0) _fatal_or_count("DUT suppressed_pairs not 0 during reset");
            if (!_has_x(t.sum_abs_err) && _dut_u32(t.sum_abs_err) != 0) _fatal_or_count("DUT sum_abs_err not 0 during reset");
            if (!_has_x48(t.sum_sq_err) && _dut_u48(t.sum_sq_err) != 0) _fatal_or_count("DUT sum_sq_err not 0 during reset");
          end

          continue;
        end
        last_rst_n = 1'b1;

        if (!check_cycle) begin
          // Still update prev snapshots so we can do auto_final and/or external checks
          prev_clr            = (t.clr_metrics_pulse === 1'b1);
          prev_pair_out_valid = (t.pair_out_valid === 1'b1);
          prev_suppressed     = (t.suppressed === 1'b1);

          prev_x0 = si64_t'($signed(t.x0_a));
          prev_x1 = si64_t'($signed(t.x1_a));
          prev_y0 = si64_t'($signed(t.y0));
          prev_y1 = si64_t'($signed(t.y1));
          prev_thresh_used = ui64_t'(t.thresh_used);

          continue;
        end

        // Apply prev cycle to expected
        // Save current expected before update
        exp_tp_next  = exp_total_pairs;
        exp_sp_next  = exp_suppressed_pairs;
        exp_abs_next = exp_sum_abs_err;
        exp_sq_next  = exp_sum_sq_err;

        _apply_prev_to_expected();

        // After task, exp_* hold updated values (after posedge we've just passed)
        exp_tp_next  = exp_total_pairs;
        exp_sp_next  = exp_suppressed_pairs;
        exp_abs_next = exp_sum_abs_err;
        exp_sq_next  = exp_sum_sq_err;

        // Read DUT counters
        if (_has_x(t.total_pairs) || _has_x(t.suppressed_pairs) || _has_x(t.sum_abs_err) || _has_x48(t.sum_sq_err)) begin
          _fatal_or_count("DUT metrics contain X (cannot compare).");
        end else begin
          dut_tp  = _dut_u32(t.total_pairs);
          dut_sp  = _dut_u32(t.suppressed_pairs);
          dut_abs = _dut_u32(t.sum_abs_err);
          dut_sq  = _dut_u48(t.sum_sq_err);

          // compare
          if (dut_tp != exp_tp_next) begin
            _fatal_or_count($sformatf("total_pairs mismatch: dut=%0d exp=%0d", dut_tp, exp_tp_next));
          end
          if (dut_sp != exp_sp_next) begin
            _fatal_or_count($sformatf("suppressed_pairs mismatch: dut=%0d exp=%0d", dut_sp, exp_sp_next));
          end
          if (dut_abs != exp_abs_next) begin
            _fatal_or_count($sformatf("sum_abs_err mismatch: dut=%0d exp=%0d", dut_abs, exp_abs_next));
          end
          if (dut_sq != exp_sq_next) begin
            _fatal_or_count($sformatf("sum_sq_err mismatch: dut=%0d exp=%0d", dut_sq, exp_sq_next));
          end

          // optional invariants
          if (check_invariants) begin
            inv_ok = 1'b1;
            if (dut_sp > dut_tp) begin
              inv_ok = 1'b0;
              _fatal_or_count($sformatf("invariant violated: suppressed_pairs (%0d) > total_pairs (%0d)", dut_sp, dut_tp));
            end
            // (sum_abs_err and sum_sq_err are unsigned accumulators; no additional invariant needed here)
          end

          if (verbose && (prev_clr || prev_pair_out_valid)) begin
            $display("[metrics_monitor] epoch=%0d update(prev_clr=%0d prev_pair=%0d) -> dut(tp,sp,abs,sq)=(%0d,%0d,%0d,%0d)",
                     epoch, prev_clr, prev_pair_out_valid, dut_tp, dut_sp, dut_abs, dut_sq);
          end

          // update last snapshots + fire event
          last_epoch = epoch;
          last_time  = $time;

          last_dut_total_pairs       = dut_tp;
          last_dut_suppressed_pairs  = dut_sp;
          last_dut_sum_abs_err       = dut_abs;
          last_dut_sum_sq_err        = dut_sq;

          last_exp_total_pairs       = exp_tp_next;
          last_exp_suppressed_pairs  = exp_sp_next;
          last_exp_sum_abs_err       = exp_abs_next;
          last_exp_sum_sq_err        = exp_sq_next;

          -> met_ev;

          // Optional one-time auto-final check vs JSON (only epoch 0)
          if (json_valid && auto_final && !final_checked && (epoch == 0) && (exp_total_pairs == (json_total_pairs & MASK32))) begin
            if ((dut_tp  != (json_total_pairs      & MASK32)) ||
                (dut_sp  != (json_suppressed_pairs & MASK32)) ||
                (dut_abs != (json_sum_abs_err      & MASK32)) ||
                (dut_sq  != (json_sum_sq_err       & MASK48))) begin
              $fatal(1, "[metrics_monitor] AUTO_FINAL FAIL: dut(tp,sp,abs,sq)=(%0d,%0d,%0d,%0d) json=(%0d,%0d,%0d,%0d)",
                     dut_tp, dut_sp, dut_abs, dut_sq,
                     (json_total_pairs & MASK32), (json_suppressed_pairs & MASK32),
                     (json_sum_abs_err & MASK32), (json_sum_sq_err & MASK48));
            end else begin
              $display("[metrics_monitor] AUTO_FINAL PASS at total_pairs=%0d: matches metrics.json.", dut_tp);
            end
            final_checked = 1'b1;
          end
        end

        // Capture current signals as "prev" for next cycle
        prev_clr            = (t.clr_metrics_pulse === 1'b1);
        prev_pair_out_valid = (t.pair_out_valid === 1'b1);
        prev_suppressed     = (t.suppressed === 1'b1);

        // These are stable registers; safe to sample on negedge.
        prev_x0 = si64_t'($signed(t.x0_a));
        prev_x1 = si64_t'($signed(t.x1_a));
        prev_y0 = si64_t'($signed(t.y0));
        prev_y1 = si64_t'($signed(t.y1));
        prev_thresh_used = ui64_t'(t.thresh_used);
      end
    end
  endtask

endmodule : metrics_monitor

`default_nettype wire
