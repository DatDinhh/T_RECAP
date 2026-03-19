`timescale 1ns/1ps
`default_nettype none

// Arizona State University 
// Capstone Senior Project
// Sigma Force
// Dat Dinh, Dat Huynh, Paul Applebee, Kyung Jae Son
// pair_monitor.sv
//
// Fully functional monitor for the DUT *pair-domain* outputs.
//
// It watches tap_if.pair_out_valid and captures, per pair k:
//   - y0, y1 (reconstructed samples)
//   - suppressed flag
//   - aligned x0_a/x1_a (inputs aligned to the pair output, for error metrics)
//   - optional debug taps a_tap/d_tap/abs_d_tap, thresh_used, mode_sel
//
// It can run in two modes:
//   1) Passive monitor: capture + publish events (default)
//   2) Self-check mode against golden files y.memh + sup.memh (enable via plusargs)
//
// Why pair_out_valid is the right trigger:
//   - It is the registered output-valid aligned to y0/y1/suppressed (per RTL).
//   - It avoids having to reason about x-pair assemble latency manually.
//
// Sampling strategy:
//   - Samples on *negedge t.clk* to avoid races with DUT posedge FF updates.
//     (Matches x_stream_monitor style.)
//
// Plusargs:
//   +PAIR_MON_DISABLE               : disable monitor
//   +PAIR_MON_VERBOSE               : verbose per-pair prints
//   +PAIR_MON_MAX_ERR=<N>           : max mismatches before $fatal (default 10; 0=never)
//   +PAIR_MON_STOP_ON_ERR           : fatal on first mismatch
//
// Golden self-check controls:
//   +PAIR_MON_CHECK_MEMH            : enable checking vs y.memh/sup.memh
//   +PAIR_MON_Y_FILE=<path>         : y memh file (default "y.memh")
//   +PAIR_MON_SUP_FILE=<path>       : suppression flags file (default "sup.memh")
//   (also honors +Y_MEMH and +SUP_MEMH for consistency with golden_files_loader)
//
// Additional sanity checks:
//   +PAIR_MON_CHECK_RULE            : check suppressed == (abs_d_tap < thresh_used)
//   +PAIR_MON_RESET_K_ON_CLEAR       : reset pair index k when clr_metrics_pulse fires
//                                    (default 0; usually leave off)
//
// Public signals/events for scoreboards:
//   - event pair_ev;                  // triggers each captured pair
//   - last_* fields (k/epoch/y0/y1/...) updated before pair_ev
//   - task wait_next_pair(...)         // blocking getter for next pair


module pair_monitor #(
  parameter int N             = 12,
  parameter int LFSR_W         = 16,
  parameter bit AUTO_START     = 1'b1,
  parameter bit CAPTURE_HISTORY= 1'b0,   // set 1 to store every pair in a queue
  parameter int unsigned MAX_HISTORY = 0 // 0 = unlimited
)(
  tap_if t
);

  import tb_pkg::*;


  // Event + last captured registers 

  event pair_ev;

  int unsigned   last_k;
  int unsigned   last_epoch;
  longint unsigned last_time;

  logic signed [N-1:0] last_x0_a;
  logic signed [N-1:0] last_x1_a;
  logic signed [N-1:0] last_y0;
  logic signed [N-1:0] last_y1;
  bit                  last_suppressed;

  logic signed [N:0]   last_a_tap;
  logic signed [N:0]   last_d_tap;
  logic [N:0]          last_abs_d_tap;

  logic [N:0]          last_thresh_used;
  logic [1:0]          last_mode_sel;
  logic                last_force_bypass;


  // Optional history capture (useful for debug/plots)

  typedef struct {
    int unsigned      k;
    int unsigned      epoch;
    longint unsigned  sim_time;
    logic signed [N-1:0] x0_a;
    logic signed [N-1:0] x1_a;
    logic signed [N-1:0] y0;
    logic signed [N-1:0] y1;
    bit               suppressed;
    logic signed [N:0] a_tap;
    logic signed [N:0] d_tap;
    logic [N:0]        abs_d_tap;
    logic [N:0]        thresh_used;
    logic [1:0]        mode_sel;
    logic              force_bypass;
  } pair_evt_t;

  pair_evt_t hist[$];


  // Config

  bit check_memh;
  bit check_rule;
  bit reset_k_on_clear;

  string y_file;
  string sup_file;

  si64_t y_exp[$];
  bit    sup_exp[$];

  int unsigned max_err;
  bit stop_on_err;
  bit verbose;
  bit disabled;

  // Runtime state
  bit running;
  bit stop_req;

  int unsigned k;
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
      $display("[pair_monitor] ERROR[%0d] k=%0d : %s", err_count, k, msg);
      if (stop_on_err || (max_err != 0 && err_count >= max_err)) begin
        $fatal(1, "[pair_monitor] Too many errors (err_count=%0d, max_err=%0d).", err_count, max_err);
      end
    end
  endtask


  // Public control tasks

  task automatic start();
    if (running) begin
      $display("[pair_monitor] NOTE: start() called but monitor already running.");
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

  task automatic report(input string tag = "pair_monitor");
    $display("[%s] captured_pairs=%0d epoch=%0d errors=%0d check_memh=%0d check_rule=%0d",
             tag, k, epoch, err_count, check_memh, check_rule);
  endtask

  // Blocking wait for next pair capture; returns the captured values.
  task automatic wait_next_pair(
    output int unsigned      k_out,
    output int unsigned      epoch_out,
    output logic signed [N-1:0] x0_a_out,
    output logic signed [N-1:0] x1_a_out,
    output logic signed [N-1:0] y0_out,
    output logic signed [N-1:0] y1_out,
    output bit               suppressed_out
  );
    begin
      @pair_ev;
      k_out         = last_k;
      epoch_out     = last_epoch;
      x0_a_out      = last_x0_a;
      x1_a_out      = last_x1_a;
      y0_out        = last_y0;
      y1_out        = last_y1;
      suppressed_out= last_suppressed;
    end
  endtask


  // Init (plusargs + file loads)

  initial begin
    running = 1'b0;
    stop_req = 1'b0;

    k = 0;
    epoch = 0;
    err_count = 0;

    // defaults
    check_memh       = 1'b0;
    check_rule       = 1'b0;
    reset_k_on_clear = 1'b0;

    y_file  = "y.memh";
    sup_file= "sup.memh";

    max_err     = 10;
    stop_on_err = 1'b0;
    verbose     = 1'b0;
    disabled    = 1'b0;

    // parse plusargs
    if ($test$plusargs("PAIR_MON_DISABLE")) disabled = 1'b1;
    if ($test$plusargs("PAIR_MON_VERBOSE")) verbose  = 1'b1;

    void'($value$plusargs("PAIR_MON_MAX_ERR=%d", max_err));
    if ($test$plusargs("PAIR_MON_STOP_ON_ERR")) stop_on_err = 1'b1;

    if ($test$plusargs("PAIR_MON_CHECK_MEMH")) check_memh = 1'b1;
    if ($test$plusargs("PAIR_MON_CHECK_RULE")) check_rule = 1'b1;
    if ($test$plusargs("PAIR_MON_RESET_K_ON_CLEAR")) reset_k_on_clear = 1'b1;

    void'($value$plusargs("PAIR_MON_Y_FILE=%s", y_file));
    void'($value$plusargs("PAIR_MON_SUP_FILE=%s", sup_file));

    // accept loader-style names too
    void'($value$plusargs("Y_MEMH=%s", y_file));
    void'($value$plusargs("SUP_MEMH=%s", sup_file));

    if (disabled) begin
      $display("[pair_monitor] Disabled via +PAIR_MON_DISABLE.");
    end else begin
      $display("[pair_monitor] Config:");
      $display("  check_memh=%0d  check_rule=%0d  reset_k_on_clear=%0d", check_memh, check_rule, reset_k_on_clear);
      $display("  y_file='%s'  sup_file='%s'", y_file, sup_file);
      $display("  max_err=%0d stop_on_err=%0d verbose=%0d", max_err, stop_on_err, verbose);
      $display("  CAPTURE_HISTORY=%0d MAX_HISTORY=%0d", CAPTURE_HISTORY, MAX_HISTORY);
    end

    // load golden files if requested
    if (!disabled && check_memh) begin
      if (!_file_exists(y_file)) begin
        $fatal(1, "[pair_monitor] +PAIR_MON_CHECK_MEMH set but y file not found: '%s'", y_file);
      end
      if (!_file_exists(sup_file)) begin
        $fatal(1, "[pair_monitor] +PAIR_MON_CHECK_MEMH set but sup file not found: '%s'", sup_file);
      end

      read_memh_signed(y_file, N, y_exp);
      read_flags01(sup_file, sup_exp);

      if (y_exp.size() == 0) $fatal(1, "[pair_monitor] Loaded 0 y samples from '%s'", y_file);
      if ((y_exp.size() % 2) != 0) $fatal(1, "[pair_monitor] y.memh length must be even, got %0d", y_exp.size());

      if (sup_exp.size() == 0) $fatal(1, "[pair_monitor] Loaded 0 sup flags from '%s'", sup_file);

      if (sup_exp.size() != (y_exp.size()/2)) begin
        $fatal(1, "[pair_monitor] sup flags size (%0d) != y pairs (%0d).",
               sup_exp.size(), (y_exp.size()/2));
      end

      $display("[pair_monitor] Loaded y=%0d samples (%0d pairs), sup=%0d pairs.",
               y_exp.size(), (y_exp.size()/2), sup_exp.size());
    end

    if (!disabled && AUTO_START) begin
      start();
    end
  end


  // Main loop

  task automatic run();
    bit last_rst_n;
    bit last_clr;

    si64_t act_y0, act_y1;
    si64_t exp_y0, exp_y1;

    bit act_sup;
    bit exp_sup;

    bit rule_sup;

    begin
      last_rst_n = 1'b1;
      last_clr   = 1'b0;

      // Wait for clock to become known
      wait (^t.clk !== 1'bX);

      forever begin
        @(negedge t.clk);

        if (stop_req) begin
          $display("[pair_monitor] stop requested.");
          running = 1'b0;
          disable run;
        end

        // reset handling
        if (!t.rst_n) begin
          if (last_rst_n) begin
            k = 0;
            epoch = 0;
            err_count = 0;
            if (CAPTURE_HISTORY) hist.delete();
            if (verbose) $display("[pair_monitor] Reset asserted: counters/history cleared.");
          end
          last_rst_n = 1'b0;
          last_clr   = 1'b0;
          continue;
        end
        last_rst_n = 1'b1;

        // detect clear-metrics pulse for epoch tracking
        if (t.clr_metrics_pulse && !last_clr) begin
          epoch++;
          if (reset_k_on_clear) begin
            if (verbose) $display("[pair_monitor] clr_metrics_pulse: resetting k to 0 (epoch=%0d).", epoch);
            k = 0;
          end else if (verbose) begin
            $display("[pair_monitor] clr_metrics_pulse: epoch incremented to %0d (k continues).", epoch);
          end
        end
        last_clr = t.clr_metrics_pulse;

        // capture only when pair_out_valid
        if (!t.pair_out_valid) begin
          continue;
        end

        // basic X-checks
        if (^t.y0 === 1'bX || ^t.y1 === 1'bX || ^t.suppressed === 1'bX) begin
          _fatal_or_count("y0/y1/suppressed contains X on pair_out_valid");
        end

        // capture
        last_k          = k;
        last_epoch      = epoch;
        last_time       = $time;

        last_x0_a       = t.x0_a;
        last_x1_a       = t.x1_a;

        last_y0         = t.y0;
        last_y1         = t.y1;
        last_suppressed = t.suppressed;

        last_a_tap      = t.a_tap;
        last_d_tap      = t.d_tap;
        last_abs_d_tap  = t.abs_d_tap;

        last_thresh_used= t.thresh_used;
        last_mode_sel   = t.mode_sel;
        last_force_bypass = t.force_bypass;

        // optional history
        if (CAPTURE_HISTORY) begin
          pair_evt_t e;
          e.k          = last_k;
          e.epoch      = last_epoch;
          e.sim_time   = last_time;
          e.x0_a       = last_x0_a;
          e.x1_a       = last_x1_a;
          e.y0         = last_y0;
          e.y1         = last_y1;
          e.suppressed = last_suppressed;
          e.a_tap      = last_a_tap;
          e.d_tap      = last_d_tap;
          e.abs_d_tap  = last_abs_d_tap;
          e.thresh_used= last_thresh_used;
          e.mode_sel   = last_mode_sel;
          e.force_bypass = last_force_bypass;
          hist.push_back(e);

          if (MAX_HISTORY != 0 && hist.size() > MAX_HISTORY) begin
            // drop oldest
            hist.pop_front();
          end
        end

        // publish event
        -> pair_ev;

        // self-check: suppression rule (if enabled and taps known)
        if (check_rule) begin
          if (^t.abs_d_tap !== 1'bX && ^t.thresh_used !== 1'bX && ^t.suppressed !== 1'bX) begin
           rule_sup = (t.abs_d_tap < ((t.thresh_used=='0) ? '0 : (t.thresh_used-1'b1)));
            if (rule_sup !== t.suppressed) begin
              _fatal_or_count($sformatf("suppression rule mismatch: suppressed=%0d but (abs_d<thresh)=%0d  abs_d=%0d thresh=%0d",
                                        t.suppressed, rule_sup, t.abs_d_tap, t.thresh_used));
            end
          end
        end

        // self-check: compare against golden memh (if enabled)
        if (check_memh) begin
          if ((2*k+1) >= y_exp.size()) begin
            _fatal_or_count($sformatf("k=%0d out of range for y_exp (size=%0d)", k, y_exp.size()));
          end else if (k >= sup_exp.size()) begin
            _fatal_or_count($sformatf("k=%0d out of range for sup_exp (size=%0d)", k, sup_exp.size()));
          end else begin
            act_y0 = si64_t'($signed(t.y0));
            act_y1 = si64_t'($signed(t.y1));
            exp_y0 = y_exp[2*k+0];
            exp_y1 = y_exp[2*k+1];

            act_sup = (t.suppressed ? 1'b1 : 1'b0);
            exp_sup = sup_exp[k];

            if (act_y0 != exp_y0 || act_y1 != exp_y1 || act_sup != exp_sup) begin
              _fatal_or_count($sformatf(
                "golden mismatch: dut(y0,y1,sup)=(%s,%s,%0d) exp=(%s,%s,%0d)",
                fmt_si64(act_y0), fmt_si64(act_y1), act_sup,
                fmt_si64(exp_y0), fmt_si64(exp_y1), exp_sup
              ));
            end else if (verbose) begin
              $display("[pair_monitor] k=%0d OK y0=%0d y1=%0d sup=%0d",
                       k, act_y0, act_y1, act_sup);
            end
          end
        end else if (verbose) begin
          $display("[pair_monitor] k=%0d captured (no golden check): y0=%0d y1=%0d sup=%0d",
                   k, si64_t'($signed(t.y0)), si64_t'($signed(t.y1)), t.suppressed);
        end

        // advance pair index
        k++;
      end
    end
  endtask

endmodule : pair_monitor

`default_nettype wire
