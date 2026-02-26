`timescale 1ns/1ps
`default_nettype none

// Arizona State University 
// Capstone Senior Project
// Sigma Force
// Dat Dinh, Dat Huynh, Paul Applebee, Kyung Jae Son
// scoreboard_metrics.sv
//
// Scoreboard for Phase-1 metrics counters in t_recap_demo_top.
//
// DUT counters (metrics_accum):
//   total_pairs      [31:0]
//   suppressed_pairs [31:0]
//   sum_abs_err      [31:0]
//   sum_sq_err       [47:0]
//
// This scoreboard provides:
//
// (1) Cycle-accurate checking of the DUT counters
//     - Recomputes expected metrics from the *tapped* pair-domain values
//       (x0_a/x1_a/y0/y1/suppressed) and compares against the DUT counters.
//     - Correctly models SystemVerilog NBA timing:
//         * metrics_accum sees pair_out_valid/clr_pulse one cycle "late"
//           (i.e., it increments/clears based on the previous cycle values).
//     - Implemented by capturing "prev_*" at negedge and applying it at the
//       next negedge before comparing against DUT counters.
//
// (2) Optional final signoff checks against:
//     - metrics.json (golden metrics)
//     - memh-derived metrics from (x.memh, y.memh, sup.memh)
//
// Epoch support:
//   When clr_metrics_pulse is asserted, the DUT clears metrics. The scoreboard
//   mirrors this and increments an internal epoch counter. It also records each
//   completed epoch's metrics into a history queue.
//
// Plusargs
// Enable/disable
//   +MET_SB_DISABLE
//   +MET_SB_VERBOSE
//   +MET_SB_MAX_ERR=<N>          (default 10; 0 = never fatal by count)
//   +MET_SB_STOP_ON_ERR
//
// Cycle checking
//   +MET_SB_CHECK_CYCLE          (default ON)
//   +MET_SB_NO_CHECK_CYCLE
//
// JSON signoff
//   +MET_SB_CHECK_JSON           (default ON if metrics file exists)
//   +MET_SB_NO_CHECK_JSON
//   +MET_SB_AUTO_FINAL_JSON      (default OFF)
//   +MET_SB_REQUIRE_JSON_CHECK   (fatal at end if JSON check never triggered)
//   +MET_SB_METRICS_FILE=<path>  (default "metrics.json")
//   +METRICS_JSON=<path>         (alias)
//
// MEMH signoff
//   +MET_SB_CHECK_MEMH           (default OFF)
//   +MET_SB_AUTO_FINAL_MEMH      (default OFF)
//   +MET_SB_REQUIRE_MEMH_CHECK   (fatal at end if MEMH check never triggered)
//   +MET_SB_X_FILE=<path>        (default "x.memh")  [also honors +X_MEMH]
//   +MET_SB_Y_FILE=<path>        (default "y.memh")  [also honors +Y_MEMH]
//   +MET_SB_SUP_FILE=<path>      (default "sup.memh")[also honors +SUP_MEMH]
//
// Invariants / extra sanity
//   +MET_SB_CHECK_INVARIANTS     (suppressed_pairs <= total_pairs)
//   +MET_SB_CHECK_LOSSLESS_T0    (if thresh_used==0 at a pair, assert y==x and sup==0)
//
// Epoch logging
//   +MET_SB_PRINT_EPOCHS         (print a summary whenever a clear occurs)


module scoreboard_metrics #(
  parameter int N      = 12,
  parameter int LFSR_W = 16,
  parameter bit AUTO_START = 1'b1
)(
  tap_if t
);

  // Selective imports to avoid name collisions with module params
  import tb_pkg::si64_t;
  import tb_pkg::ui64_t;
  import tb_pkg::abs64;
  import tb_pkg::read_memh_signed;
  import tb_pkg::read_flags01;
  import tb_pkg::read_metrics_json;
  import tb_pkg::fmt_si64;


  // Masks to match DUT counter widths

  localparam ui64_t MASK32 = 64'hFFFF_FFFF;
  localparam ui64_t MASK48 = (ui64_t'(1) << 48) - ui64_t'(1);


  // Config

  bit disabled;
  bit verbose;

  int unsigned max_err;
  bit stop_on_err;

  bit check_cycle;

  // JSON signoff
  bit check_json;
  bit auto_final_json;
  bit require_json_check;
  string metrics_file;

  bit   json_valid;
  ui64_t json_total_pairs;
  ui64_t json_suppressed_pairs;
  ui64_t json_sum_abs_err;
  ui64_t json_sum_sq_err;
  bit json_checked;

  // MEMH signoff
  bit check_memh;
  bit auto_final_memh;
  bit require_memh_check;
  string x_file;
  string y_file;
  string sup_file;

  bit   memh_valid;
  ui64_t memh_total_pairs;
  ui64_t memh_suppressed_pairs;
  ui64_t memh_sum_abs_err;
  ui64_t memh_sum_sq_err;
  bit memh_checked;

  // Invariants / extra checks
  bit check_invariants;
  bit check_lossless_t0;

  // Epoch logging
  bit print_epochs;


  // Runtime state

  bit running;
  bit stop_req;
  int unsigned err_count;

  // Our expected counters (mirroring DUT widths via masking)
  ui64_t exp_total_pairs;
  ui64_t exp_suppressed_pairs;
  ui64_t exp_sum_abs_err;
  ui64_t exp_sum_sq_err;

  // Epoch counter (increments on clear events as applied by metrics_accum)
  int unsigned epoch;

  // History (completed epochs)

  typedef struct {
    int unsigned epoch_id;
    ui64_t total_pairs;
    ui64_t suppressed_pairs;
    ui64_t sum_abs_err;
    ui64_t sum_sq_err;
  } epoch_metrics_t;

  epoch_metrics_t epoch_hist[$];


  // Prev snapshots to model NBA timing

  bit   prev_clr;
  bit   prev_pair_out_valid;
  bit   prev_suppressed;

  si64_t prev_x0;
  si64_t prev_x1;
  si64_t prev_y0;
  si64_t prev_y1;

  ui64_t prev_thresh_used;


  // Events / last snapshot (optional external synchronization)

  event met_sb_ev;
  event epoch_end_ev;

  int unsigned     last_epoch;
  longint unsigned last_time;

  ui64_t last_dut_total_pairs;
  ui64_t last_dut_suppressed_pairs;
  ui64_t last_dut_sum_abs_err;
  ui64_t last_dut_sum_sq_err;

  ui64_t last_exp_total_pairs;
  ui64_t last_exp_suppressed_pairs;
  ui64_t last_exp_sum_abs_err;
  ui64_t last_exp_sum_sq_err;


  // Small helpers

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

  function automatic bit _has_x32(input logic [31:0] v);
    _has_x32 = (^v === 1'bX);
  endfunction

  function automatic bit _has_x48(input logic [47:0] v);
    _has_x48 = (^v === 1'bX);
  endfunction

  task automatic _fatal_or_count(input string msg);
    begin
      err_count++;
      $display("[scoreboard_metrics] ERROR[%0d] epoch=%0d : %s", err_count, epoch, msg);
      if (stop_on_err || (max_err != 0 && err_count >= max_err)) begin
        $fatal(1, "[scoreboard_metrics] Too many errors (err_count=%0d max_err=%0d)", err_count, max_err);
      end
    end
  endtask


  // Public control/tasks

  task automatic start();
    if (running) begin
      $display("[scoreboard_metrics] NOTE: start() called but already running.");
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

  task automatic report(input string tag = "scoreboard_metrics");
    $display("[%s] epoch=%0d errors=%0d exp(tp,sp,abs,sq)=(%0d,%0d,%0d,%0d)",
             tag, epoch, err_count,
             exp_total_pairs, exp_suppressed_pairs, exp_sum_abs_err, exp_sum_sq_err);

    if (json_valid) begin
      $display("[%s] json(tp,sp,abs,sq)=(%0d,%0d,%0d,%0d) checked=%0d", tag,
               json_total_pairs, json_suppressed_pairs, json_sum_abs_err, json_sum_sq_err, json_checked);
    end

    if (memh_valid) begin
      $display("[%s] memh(tp,sp,abs,sq)=(%0d,%0d,%0d,%0d) checked=%0d", tag,
               memh_total_pairs, memh_suppressed_pairs, memh_sum_abs_err, memh_sum_sq_err, memh_checked);
    end

    $display("[%s] epoch_hist size=%0d", tag, epoch_hist.size());
  endtask

  task automatic check_now_against_values(
    input ui64_t exp_tp,
    input ui64_t exp_sp,
    input ui64_t exp_abs,
    input ui64_t exp_sq
  );
    ui64_t dut_tp, dut_sp, dut_abs, dut_sq;
    begin
      if (_has_x32(t.total_pairs) || _has_x32(t.suppressed_pairs) || _has_x32(t.sum_abs_err) || _has_x48(t.sum_sq_err)) begin
        $fatal(1, "[scoreboard_metrics] check_now_against_values: DUT metrics contain X.");
      end

      dut_tp  = ui64_t'(t.total_pairs);
      dut_sp  = ui64_t'(t.suppressed_pairs);
      dut_abs = ui64_t'(t.sum_abs_err);
      dut_sq  = ui64_t'(t.sum_sq_err);

      if ((dut_tp  != (exp_tp & MASK32)) ||
          (dut_sp  != (exp_sp & MASK32)) ||
          (dut_abs != (exp_abs & MASK32)) ||
          (dut_sq  != (exp_sq & MASK48))) begin
        $fatal(1, "[scoreboard_metrics] CHECK FAIL: dut(tp,sp,abs,sq)=(%0d,%0d,%0d,%0d) exp=(%0d,%0d,%0d,%0d)",
               dut_tp, dut_sp, dut_abs, dut_sq,
               (exp_tp & MASK32), (exp_sp & MASK32), (exp_abs & MASK32), (exp_sq & MASK48));
      end else begin
        $display("[scoreboard_metrics] CHECK PASS: (tp,sp,abs,sq)=(%0d,%0d,%0d,%0d)", dut_tp, dut_sp, dut_abs, dut_sq);
      end
    end
  endtask

  task automatic check_final_against_json();
    if (!json_valid) $fatal(1, "[scoreboard_metrics] JSON not loaded/valid.");
    check_now_against_values(json_total_pairs, json_suppressed_pairs, json_sum_abs_err, json_sum_sq_err);
  endtask

  task automatic check_final_against_memh();
    if (!memh_valid) $fatal(1, "[scoreboard_metrics] MEMH metrics not loaded/valid.");
    check_now_against_values(memh_total_pairs, memh_suppressed_pairs, memh_sum_abs_err, memh_sum_sq_err);
  endtask


  // MEMH metrics computation

  task automatic _compute_memh_metrics(
    input  string x_fn,
    input  string y_fn,
    input  string sup_fn,
    output bit    ok,
    output ui64_t tp,
    output ui64_t sp,
    output ui64_t sae,
    output ui64_t sse
  );
    si64_t xdat[$];
    si64_t ydat[$];
    bit    sdat[$];

    si64_t x0, x1, y0, y1;
    si64_t e0, e1;
    ui64_t ae0, ae1;
    ui64_t sq0, sq1;

    begin
      ok  = 1'b0;
      tp  = 0;
      sp  = 0;
      sae = 0;
      sse = 0;

      read_memh_signed(x_fn, N, xdat);
      read_memh_signed(y_fn, N, ydat);
      read_flags01(sup_fn, sdat);

      if (xdat.size() == 0 || ydat.size() == 0) begin
        $display("[scoreboard_metrics] MEMH compute: empty x/y.");
        return;
      end

      if ((xdat.size() % 2) != 0 || (ydat.size() % 2) != 0) begin
        $display("[scoreboard_metrics] MEMH compute: x/y length must be even (x=%0d y=%0d)", xdat.size(), ydat.size());
        return;
      end

      if (xdat.size() != ydat.size()) begin
        $display("[scoreboard_metrics] MEMH compute: x/y length mismatch (x=%0d y=%0d)", xdat.size(), ydat.size());
        return;
      end

      if (sdat.size() != (ydat.size()/2)) begin
        $display("[scoreboard_metrics] MEMH compute: sup length mismatch (sup=%0d pairs=%0d)", sdat.size(), (ydat.size()/2));
        return;
      end

      tp = ui64_t'(ydat.size()/2);

      for (int unsigned k = 0; k < tp; k++) begin
        x0 = xdat[2*k+0];
        x1 = xdat[2*k+1];
        y0 = ydat[2*k+0];
        y1 = ydat[2*k+1];

        e0 = x0 - y0;
        e1 = x1 - y1;

        ae0 = abs64(e0);
        ae1 = abs64(e1);

        sq0 = ae0 * ae0;
        sq1 = ae1 * ae1;

        sae = (sae + (ae0 + ae1)) & MASK32;
        sse = (sse + (sq0 + sq1)) & MASK48;

        if (sdat[k]) sp = (sp + 1) & MASK32;
      end

      ok = 1'b1;
    end
  endtask


  // Init

  initial begin
    running  = 1'b0;
    stop_req = 1'b0;

    err_count = 0;
    epoch     = 0;

    epoch_hist.delete();

    exp_total_pairs      = 0;
    exp_suppressed_pairs = 0;
    exp_sum_abs_err      = 0;
    exp_sum_sq_err       = 0;

    prev_clr            = 1'b0;
    prev_pair_out_valid = 1'b0;
    prev_suppressed     = 1'b0;
    prev_x0 = 0; prev_x1 = 0; prev_y0 = 0; prev_y1 = 0;
    prev_thresh_used = 0;

    // defaults
    disabled    = 1'b0;
    verbose     = 1'b0;
    max_err     = 10;
    stop_on_err = 1'b0;

    check_cycle = 1'b1;

    // JSON defaults
    metrics_file = "metrics.json";
    void'($value$plusargs("MET_SB_METRICS_FILE=%s", metrics_file));
    void'($value$plusargs("METRICS_JSON=%s", metrics_file));

    check_json        = _file_exists(metrics_file); // auto enable if present
    auto_final_json   = 1'b0;
    require_json_check= 1'b0;

    json_valid   = 1'b0;
    json_checked = 1'b0;

    // MEMH defaults
    x_file   = "x.memh";
    y_file   = "y.memh";
    sup_file = "sup.memh";

    void'($value$plusargs("MET_SB_X_FILE=%s", x_file));
    void'($value$plusargs("MET_SB_Y_FILE=%s", y_file));
    void'($value$plusargs("MET_SB_SUP_FILE=%s", sup_file));

    // aliases to match other loaders
    void'($value$plusargs("X_MEMH=%s", x_file));
    void'($value$plusargs("Y_MEMH=%s", y_file));
    void'($value$plusargs("SUP_MEMH=%s", sup_file));

    check_memh        = 1'b0;
    auto_final_memh   = 1'b0;
    require_memh_check= 1'b0;

    memh_valid   = 1'b0;
    memh_checked = 1'b0;

    // invariants
    check_invariants  = 1'b0;
    check_lossless_t0 = 1'b0;

    print_epochs = 1'b0;

    // parse plusargs
    if ($test$plusargs("MET_SB_DISABLE")) disabled = 1'b1;
    if ($test$plusargs("MET_SB_VERBOSE")) verbose  = 1'b1;

    void'($value$plusargs("MET_SB_MAX_ERR=%d", max_err));
    if ($test$plusargs("MET_SB_STOP_ON_ERR")) stop_on_err = 1'b1;

    if ($test$plusargs("MET_SB_NO_CHECK_CYCLE")) check_cycle = 1'b0;
    if ($test$plusargs("MET_SB_CHECK_CYCLE"))    check_cycle = 1'b1;

    if ($test$plusargs("MET_SB_NO_CHECK_JSON")) check_json = 1'b0;
    if ($test$plusargs("MET_SB_CHECK_JSON"))    check_json = 1'b1;

    if ($test$plusargs("MET_SB_AUTO_FINAL_JSON"))    auto_final_json = 1'b1;
    if ($test$plusargs("MET_SB_REQUIRE_JSON_CHECK")) require_json_check = 1'b1;

    if ($test$plusargs("MET_SB_CHECK_MEMH"))          check_memh = 1'b1;
    if ($test$plusargs("MET_SB_AUTO_FINAL_MEMH"))     auto_final_memh = 1'b1;
    if ($test$plusargs("MET_SB_REQUIRE_MEMH_CHECK"))  require_memh_check = 1'b1;

    if ($test$plusargs("MET_SB_CHECK_INVARIANTS"))  check_invariants = 1'b1;
    if ($test$plusargs("MET_SB_CHECK_LOSSLESS_T0")) check_lossless_t0 = 1'b1;

    if ($test$plusargs("MET_SB_PRINT_EPOCHS")) print_epochs = 1'b1;

    // Load JSON if enabled
    if (!disabled && check_json) begin
      if (!_file_exists(metrics_file)) begin
        $fatal(1, "[scoreboard_metrics] JSON enabled but file not found: '%s'", metrics_file);
      end
      read_metrics_json(metrics_file, json_total_pairs, json_suppressed_pairs, json_sum_abs_err, json_sum_sq_err);
      json_valid = 1'b1;
      $display("[scoreboard_metrics] Loaded metrics.json '%s': tp=%0d sp=%0d abs=%0d sq=%0d",
               metrics_file, json_total_pairs, json_suppressed_pairs, json_sum_abs_err, json_sum_sq_err);
    end

    // Compute MEMH metrics if enabled
    if (!disabled && check_memh) begin
      bit ok;
      _compute_memh_metrics(x_file, y_file, sup_file, ok,
                            memh_total_pairs, memh_suppressed_pairs, memh_sum_abs_err, memh_sum_sq_err);
      if (!ok) begin
        $fatal(1, "[scoreboard_metrics] MEMH metrics compute failed (x='%s' y='%s' sup='%s')", x_file, y_file, sup_file);
      end
      memh_valid = 1'b1;
      $display("[scoreboard_metrics] Computed MEMH metrics: tp=%0d sp=%0d abs=%0d sq=%0d",
               memh_total_pairs, memh_suppressed_pairs, memh_sum_abs_err, memh_sum_sq_err);
    end

    if (disabled) begin
      $display("[scoreboard_metrics] Disabled via +MET_SB_DISABLE");
    end else begin
      $display("[scoreboard_metrics] Config:");
      $display("  check_cycle=%0d verbose=%0d max_err=%0d stop_on_err=%0d", check_cycle, verbose, max_err, stop_on_err);
      $display("  check_json=%0d auto_final_json=%0d require_json_check=%0d metrics_file='%s'",
               check_json, auto_final_json, require_json_check, metrics_file);
      $display("  check_memh=%0d auto_final_memh=%0d require_memh_check=%0d x='%s' y='%s' sup='%s'",
               check_memh, auto_final_memh, require_memh_check, x_file, y_file, sup_file);
      $display("  check_invariants=%0d check_lossless_t0=%0d print_epochs=%0d", check_invariants, check_lossless_t0, print_epochs);
    end

    if (!disabled && AUTO_START) begin
      start();
    end
  end


  // Main run loop

  task automatic run();
    bit last_rst_n;

    // dut observed
    ui64_t dut_tp, dut_sp, dut_abs, dut_sq;

    // compute deltas
    si64_t e0, e1;
    ui64_t ae0, ae1;
    ui64_t sq0, sq1;

    // for epoch bookkeeping
    epoch_metrics_t em;

    begin
      last_rst_n = 1'b1;

      // Wait for clock to become known
      wait (^t.clk !== 1'bX);

      forever begin
        @(negedge t.clk);

        if (stop_req) begin
          $display("[scoreboard_metrics] stop requested.");
          running = 1'b0;
          disable run;
        end

        // Async reset handling
        if (!t.rst_n) begin
          if (last_rst_n) begin
            // reset asserted edge
            err_count = 0;
            epoch     = 0;
            epoch_hist.delete();

            exp_total_pairs      = 0;
            exp_suppressed_pairs = 0;
            exp_sum_abs_err      = 0;
            exp_sum_sq_err       = 0;

            prev_clr            = 1'b0;
            prev_pair_out_valid = 1'b0;
            prev_suppressed     = 1'b0;
            prev_x0 = 0; prev_x1 = 0; prev_y0 = 0; prev_y1 = 0;
            prev_thresh_used = 0;

            // don't clear json/memh loaded expectations
            json_checked = 1'b0;
            memh_checked = 1'b0;

            if (verbose) $display("[scoreboard_metrics] Reset asserted: state cleared.");
          end
          last_rst_n = 1'b0;
          continue;
        end
        last_rst_n = 1'b1;

        if (!check_cycle) begin
          // still update prev snapshots for correct epoch-aware auto-final
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


        // Apply previous-cycle effects (mirrors metrics_accum)

        // Clear has priority over increment.
        if (prev_clr) begin
          // record completed epoch (snapshot BEFORE clearing)
          em.epoch_id        = epoch;
          em.total_pairs     = exp_total_pairs;
          em.suppressed_pairs= exp_suppressed_pairs;
          em.sum_abs_err     = exp_sum_abs_err;
          em.sum_sq_err      = exp_sum_sq_err;
          epoch_hist.push_back(em);

          if (print_epochs) begin
            $display("[scoreboard_metrics] EPOCH_END epoch=%0d  (tp,sp,abs,sq)=(%0d,%0d,%0d,%0d)",
                     epoch, em.total_pairs, em.suppressed_pairs, em.sum_abs_err, em.sum_sq_err);
          end

          // clear expected counters
          exp_total_pairs      = 0;
          exp_suppressed_pairs = 0;
          exp_sum_abs_err      = 0;
          exp_sum_sq_err       = 0;

          epoch++;
          -> epoch_end_ev;

        end else if (prev_pair_out_valid) begin

          // Extra sanity: lossless property when thresh_used==0
          if (check_lossless_t0 && (prev_thresh_used == 0)) begin
            if (prev_suppressed !== 1'b0) begin
              _fatal_or_count("lossless T=0 violated: suppressed asserted when thresh_used==0");
            end
            if ((prev_x0 - prev_y0) != 0 || (prev_x1 - prev_y1) != 0) begin
              _fatal_or_count("lossless T=0 violated: x!=y when thresh_used==0");
            end
          end

          // error metrics
          e0  = prev_x0 - prev_y0;
          e1  = prev_x1 - prev_y1;
          ae0 = abs64(e0);
          ae1 = abs64(e1);
          sq0 = ae0 * ae0;
          sq1 = ae1 * ae1;

          exp_total_pairs      = (exp_total_pairs + 1) & MASK32;
          exp_suppressed_pairs = (exp_suppressed_pairs + (prev_suppressed ? 1 : 0)) & MASK32;
          exp_sum_abs_err      = (exp_sum_abs_err + (ae0 + ae1)) & MASK32;
          exp_sum_sq_err       = (exp_sum_sq_err + (sq0 + sq1)) & MASK48;
        end


        // Compare against DUT counters

        if (_has_x32(t.total_pairs) || _has_x32(t.suppressed_pairs) || _has_x32(t.sum_abs_err) || _has_x48(t.sum_sq_err)) begin
          _fatal_or_count("DUT metrics contain X; cannot compare.");
        end else begin
          dut_tp  = ui64_t'(t.total_pairs);
          dut_sp  = ui64_t'(t.suppressed_pairs);
          dut_abs = ui64_t'(t.sum_abs_err);
          dut_sq  = ui64_t'(t.sum_sq_err);

          if (dut_tp != exp_total_pairs) begin
            _fatal_or_count($sformatf("total_pairs mismatch: dut=%0d exp=%0d", dut_tp, exp_total_pairs));
          end
          if (dut_sp != exp_suppressed_pairs) begin
            _fatal_or_count($sformatf("suppressed_pairs mismatch: dut=%0d exp=%0d", dut_sp, exp_suppressed_pairs));
          end
          if (dut_abs != exp_sum_abs_err) begin
            _fatal_or_count($sformatf("sum_abs_err mismatch: dut=%0d exp=%0d", dut_abs, exp_sum_abs_err));
          end
          if (dut_sq != exp_sum_sq_err) begin
            _fatal_or_count($sformatf("sum_sq_err mismatch: dut=%0d exp=%0d", dut_sq, exp_sum_sq_err));
          end

          if (check_invariants) begin
            if (dut_sp > dut_tp) begin
              _fatal_or_count($sformatf("invariant violated: suppressed_pairs (%0d) > total_pairs (%0d)", dut_sp, dut_tp));
            end
          end

          // snapshot + event
          last_epoch = epoch;
          last_time  = $time;

          last_dut_total_pairs      = dut_tp;
          last_dut_suppressed_pairs = dut_sp;
          last_dut_sum_abs_err      = dut_abs;
          last_dut_sum_sq_err       = dut_sq;

          last_exp_total_pairs      = exp_total_pairs;
          last_exp_suppressed_pairs = exp_suppressed_pairs;
          last_exp_sum_abs_err      = exp_sum_abs_err;
          last_exp_sum_sq_err       = exp_sum_sq_err;

          -> met_sb_ev;

          if (verbose && (prev_clr || prev_pair_out_valid)) begin
            $display("[scoreboard_metrics] epoch=%0d update(prev_clr=%0d prev_pair=%0d) -> (tp,sp,abs,sq)=(%0d,%0d,%0d,%0d)",
                     epoch, prev_clr, prev_pair_out_valid, dut_tp, dut_sp, dut_abs, dut_sq);
          end


          // Auto-final signoff checks (epoch 0 only)

          if (epoch == 0) begin
            if (json_valid && auto_final_json && !json_checked && (exp_total_pairs == (json_total_pairs & MASK32))) begin
              if ((dut_tp  != (json_total_pairs      & MASK32)) ||
                  (dut_sp  != (json_suppressed_pairs & MASK32)) ||
                  (dut_abs != (json_sum_abs_err      & MASK32)) ||
                  (dut_sq  != (json_sum_sq_err       & MASK48))) begin
                $fatal(1, "[scoreboard_metrics] AUTO_FINAL_JSON FAIL: dut(tp,sp,abs,sq)=(%0d,%0d,%0d,%0d) json=(%0d,%0d,%0d,%0d)",
                       dut_tp, dut_sp, dut_abs, dut_sq,
                       (json_total_pairs & MASK32), (json_suppressed_pairs & MASK32),
                       (json_sum_abs_err & MASK32), (json_sum_sq_err & MASK48));
              end else begin
                $display("[scoreboard_metrics] AUTO_FINAL_JSON PASS at total_pairs=%0d", dut_tp);
              end
              json_checked = 1'b1;
            end

            if (memh_valid && auto_final_memh && !memh_checked && (exp_total_pairs == (memh_total_pairs & MASK32))) begin
              if ((dut_tp  != (memh_total_pairs      & MASK32)) ||
                  (dut_sp  != (memh_suppressed_pairs & MASK32)) ||
                  (dut_abs != (memh_sum_abs_err      & MASK32)) ||
                  (dut_sq  != (memh_sum_sq_err       & MASK48))) begin
                $fatal(1, "[scoreboard_metrics] AUTO_FINAL_MEMH FAIL: dut(tp,sp,abs,sq)=(%0d,%0d,%0d,%0d) memh=(%0d,%0d,%0d,%0d)",
                       dut_tp, dut_sp, dut_abs, dut_sq,
                       (memh_total_pairs & MASK32), (memh_suppressed_pairs & MASK32),
                       (memh_sum_abs_err & MASK32), (memh_sum_sq_err & MASK48));
              end else begin
                $display("[scoreboard_metrics] AUTO_FINAL_MEMH PASS at total_pairs=%0d", dut_tp);
              end
              memh_checked = 1'b1;
            end
          end
        end


        // Capture current taps as prev_* for next cycle

        prev_clr            = (t.clr_metrics_pulse === 1'b1);
        prev_pair_out_valid = (t.pair_out_valid === 1'b1);
        prev_suppressed     = (t.suppressed === 1'b1);

        prev_x0 = si64_t'($signed(t.x0_a));
        prev_x1 = si64_t'($signed(t.x1_a));
        prev_y0 = si64_t'($signed(t.y0));
        prev_y1 = si64_t'($signed(t.y1));

        prev_thresh_used = ui64_t'(t.thresh_used);
      end
    end
  endtask


  // End-of-sim enforcement + summary

  final begin
    if (!disabled) begin
      report("scoreboard_metrics_final");

      if (require_json_check && check_json && json_valid && !json_checked) begin
        $fatal(1, "[scoreboard_metrics] REQUIRE_JSON_CHECK failed: JSON auto-final check never triggered.");
      end

      if (require_memh_check && check_memh && memh_valid && !memh_checked) begin
        $fatal(1, "[scoreboard_metrics] REQUIRE_MEMH_CHECK failed: MEMH auto-final check never triggered.");
      end
    end
  end

endmodule : scoreboard_metrics

`default_nettype wire
