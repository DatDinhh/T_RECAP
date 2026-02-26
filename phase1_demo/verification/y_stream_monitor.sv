
`timescale 1ns/1ps
`default_nettype none

// Arizona State University 
// Capstone Senior Project
// Sigma Force
// Dat Dinh, Dat Huynh, Paul Applebee, Kyung Jae Son
// y_stream_monitor.sv
//
// Fully functional monitor for the DUT serialized output stream (y_out/y_valid).
//
// It supports three reference modes:
//   - memh : Compare y_out against y.memh (bit-exact golden stream).
//   - pairs: Build an expected queue from DUT pair outputs (y0/y1 on pair_out_valid)
//            and verify the serializer/FIFO produces the exact same stream order.
//   - both : Do BOTH checks simultaneously.
//
// Why pairs mode matters:
//   It validates the out_fifo_serializer behavior (push2/pop1 ordering, valid gating)
//   without assuming a specific threshold or having an external golden file.
//
// Sampling strategy:
//   - Sample on negedge of t.clk to avoid races with DUT posedge FF updates.
//   - The internal expected-queue model matches the out_fifo_serializer semantics:
//
//       do_pop  = sample_en && (count != 0)     // based on pre-state count
//       push_ok = pair_out_valid && (count <= DEPTH-2)
//
//     Pop happens before push in the RTL always_ff, but both are evaluated from
//     the pre-state count. We emulate that.
//
// Plusargs:
//   +Y_MON_DISABLE                 : disable monitor
//   +Y_MON_MODE=memh|pairs|both|off
//   +Y_MON_Y_FILE=<path>           : y.memh path (default "y.memh")
//   +Y_MEMH=<path>                 : alias for y file
//   +Y_MON_DEPTH=<int>             : serializer FIFO depth (default parameter DEPTH)
//   +Y_MON_MAX_ERR=<N>             : max mismatches before $fatal (default 10; 0=never)
//   +Y_MON_STOP_ON_ERR             : fatal on first mismatch
//   +Y_MON_VERBOSE                 : per-event printing
//   +Y_MON_RESET_M_ON_CLEAR         : reset memh index m when clr_metrics_pulse rises
//   +Y_MON_ALLOW_OVERFLOW           : don't fatal when push occurs while no space
//   +Y_MON_CHECK_VALID              : check y_valid equals expected do_pop (default on for pairs/both)
//
// Public interface for scoreboards:
//   - event y_ev;                  // triggers each time a y sample is observed (y_valid=1)
//   - last_m, last_y, last_exp_*   // updated before y_ev
//   - task wait_next_y(...)


module y_stream_monitor #(
  parameter int N             = 12,
  parameter int SHIFT         = tb_pkg::SHIFT,
  parameter int LFSR_W         = 16,
  parameter int DEPTH          = 4,
  parameter bit AUTO_START     = 1'b1,
  parameter bit CAPTURE_HISTORY= 1'b0,
  parameter int unsigned MAX_HISTORY = 0
)(
  tap_if t
);

  import tb_pkg::*;


  // Mode enum

  typedef enum int {MODE_OFF=0, MODE_MEMH=1, MODE_PAIRS=2, MODE_BOTH=3} mode_e;
  mode_e mode;


  // Events / last captured

  event y_ev;

  int unsigned   last_m;
  int unsigned   last_epoch;
  longint unsigned last_time;

  logic signed [N-1:0] last_y;
  si64_t               last_y_si64;

  // Expected references at last y_valid (for debugging)
  bit                 last_have_memh;
  bit                 last_have_pairs;
  si64_t              last_exp_memh;
  si64_t              last_exp_pairs;


  // Optional history

  typedef struct {
    int unsigned      m;
    int unsigned      epoch;
    longint unsigned  sim_time;
    si64_t            y_act;
    si64_t            y_exp_memh;
    si64_t            y_exp_pairs;
    bit               have_memh;
    bit               have_pairs;
  } y_evt_t;

  y_evt_t hist[$];


  // Config

  string y_file;

  int unsigned max_err;
  bit stop_on_err;
  bit verbose;
  bit disabled;

  bit reset_m_on_clear;
  bit allow_overflow;
  bit check_valid;

  int unsigned depth_cfg;

  
  // Golden stream (memh)

  si64_t y_exp[$];


  // Pair-derived expected queue (serializer model)

  si64_t exp_q[$]; // acts like FIFO queue of expected y stream values (based on pair pushes)


  // Runtime state
  
  bit running;
  bit stop_req;

  int unsigned m;      // y stream index (increments only on y_valid)
  int unsigned epoch;  // increments on clr_metrics_pulse rising edge (optional use)
  int unsigned err_count;


  // Helpers

  function automatic mode_e _parse_mode(input string s);
    if (s == "off" || s == "0" || s == "disable" || s == "disabled") _parse_mode = MODE_OFF;
    else if (s == "memh" || s == "file")                              _parse_mode = MODE_MEMH;
    else if (s == "pairs" || s == "pair" || s == "fifo")              _parse_mode = MODE_PAIRS;
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
      $display("[y_stream_monitor] ERROR[%0d] m=%0d : %s", err_count, m, msg);
      if (stop_on_err || (max_err != 0 && err_count >= max_err)) begin
        $fatal(1, "[y_stream_monitor] Too many errors (err_count=%0d, max_err=%0d).", err_count, max_err);
      end
    end
  endtask


  // Public tasks

  task automatic start();
    if (running) begin
      $display("[y_stream_monitor] NOTE: start() called but already running.");
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

  task automatic report(input string tag = "y_stream_monitor");
    $display("[%s] y_seen=%0d epoch=%0d errors=%0d mode=%0d (OFF=0 MEMH=1 PAIRS=2 BOTH=3) q_len=%0d",
             tag, m, epoch, err_count, mode, exp_q.size());
  endtask

  task automatic wait_next_y(
    output int unsigned      m_out,
    output int unsigned      epoch_out,
    output logic signed [N-1:0] y_out,
    output bit               have_memh,
    output si64_t            exp_memh,
    output bit               have_pairs,
    output si64_t            exp_pairs
  );
    begin
      @y_ev;
      m_out       = last_m;
      epoch_out   = last_epoch;
      y_out       = last_y;
      have_memh   = last_have_memh;
      exp_memh    = last_exp_memh;
      have_pairs  = last_have_pairs;
      exp_pairs   = last_exp_pairs;
    end
  endtask

  // Initialization (plusargs + loads)

  initial begin
    running   = 1'b0;
    stop_req  = 1'b0;

    m         = 0;
    epoch     = 0;
    err_count = 0;

    exp_q.delete();
    if (CAPTURE_HISTORY) hist.delete();

    // defaults
    y_file = "y.memh";
    void'($value$plusargs("Y_MON_Y_FILE=%s", y_file));
    void'($value$plusargs("Y_MEMH=%s", y_file));

    max_err     = 10;
    stop_on_err = 1'b0;
    verbose     = 1'b0;
    disabled    = 1'b0;

    reset_m_on_clear = 1'b0;
    allow_overflow   = 1'b0;

    // valid check default: ON if pairs/both, OFF if memh only
    check_valid = 1'b1;

    depth_cfg = DEPTH;
    void'($value$plusargs("Y_MON_DEPTH=%d", depth_cfg));

    if ($test$plusargs("Y_MON_DISABLE")) disabled = 1'b1;
    if ($test$plusargs("Y_MON_VERBOSE")) verbose  = 1'b1;

    void'($value$plusargs("Y_MON_MAX_ERR=%d", max_err));
    if ($test$plusargs("Y_MON_STOP_ON_ERR")) stop_on_err = 1'b1;

    if ($test$plusargs("Y_MON_RESET_M_ON_CLEAR")) reset_m_on_clear = 1'b1;
    if ($test$plusargs("Y_MON_ALLOW_OVERFLOW"))   allow_overflow   = 1'b1;

    if ($test$plusargs("Y_MON_CHECK_VALID"))      check_valid = 1'b1;
    if ($test$plusargs("Y_MON_NO_CHECK_VALID"))   check_valid = 1'b0;

    // Mode selection:
    //  - if +Y_MON_MODE provided, use it
    //  - else: if y_file exists -> memh, else -> pairs
    begin
      string mstr;
      mstr = "";
      if ($value$plusargs("Y_MON_MODE=%s", mstr)) begin
        mode = _parse_mode(mstr);
      end else begin
        if (_file_exists(y_file)) mode = MODE_MEMH;
        else                      mode = MODE_PAIRS;
      end
    end

    if (disabled) mode = MODE_OFF;

    // If user selects memh/both, we require y.memh to exist
    if (mode == MODE_MEMH || mode == MODE_BOTH) begin
      if (!_file_exists(y_file)) begin
        $fatal(1, "[y_stream_monitor] Requested memh checking but y file not found: '%s'", y_file);
      end
      read_memh_signed(y_file, N, y_exp);
      if (y_exp.size() == 0) $fatal(1, "[y_stream_monitor] Loaded 0 y samples from '%s'", y_file);
      $display("[y_stream_monitor] Loaded y.memh: %0d samples from '%s'.", y_exp.size(), y_file);
    end

    if (mode == MODE_OFF) begin
      $display("[y_stream_monitor] Disabled (mode=OFF).");
    end else begin
      $display("[y_stream_monitor] Config:");
      $display("  mode=%0d (OFF=0 MEMH=1 PAIRS=2 BOTH=3)", mode);
      $display("  y_file='%s'  depth_cfg=%0d", y_file, depth_cfg);
      $display("  max_err=%0d stop_on_err=%0d verbose=%0d", max_err, stop_on_err, verbose);
      $display("  reset_m_on_clear=%0d allow_overflow=%0d check_valid=%0d",
               reset_m_on_clear, allow_overflow, check_valid);
      $display("  CAPTURE_HISTORY=%0d MAX_HISTORY=%0d", CAPTURE_HISTORY, MAX_HISTORY);
    end

    if (AUTO_START && mode != MODE_OFF) begin
      start();
    end
  end


  // Main run loop

  task automatic run();
    bit last_rst_n;
    bit last_clr;

    int unsigned q_len_pre;
    bit do_pop_exp;
    bit push_ok_exp;
    bit push_valid;

    si64_t exp_pop;
    si64_t act_y;
    si64_t exp_memh;

    si64_t push_y0;
    si64_t push_y1;

    begin
      last_rst_n = 1'b1;
      last_clr   = 1'b0;

      // Wait for clock to become known
      wait (^t.clk !== 1'bX);

      forever begin
        @(negedge t.clk);

        if (stop_req) begin
          $display("[y_stream_monitor] stop requested.");
          running = 1'b0;
          disable run;
        end

        // reset handling
        if (!t.rst_n) begin
          if (last_rst_n) begin
            m         = 0;
            epoch     = 0;
            err_count = 0;
            exp_q.delete();
            if (CAPTURE_HISTORY) hist.delete();
            if (verbose) $display("[y_stream_monitor] Reset asserted: indices/queue/history cleared.");
          end
          last_rst_n = 1'b0;
          last_clr   = 1'b0;
          continue;
        end
        last_rst_n = 1'b1;

        // clear pulse handling (epoch tracking)
        if (t.clr_metrics_pulse && !last_clr) begin
          epoch++;
          if (reset_m_on_clear) begin
            if (verbose) $display("[y_stream_monitor] clr_metrics_pulse: resetting m to 0 (epoch=%0d).", epoch);
            m = 0;
          end else if (verbose) begin
            $display("[y_stream_monitor] clr_metrics_pulse: epoch=%0d (m continues).", epoch);
          end
        end
        last_clr = t.clr_metrics_pulse;

        // Pre-state queue length for this clock edge
        q_len_pre = exp_q.size();

        // Determine expected push/pop for this cycle (based on pre-state)
        push_valid = (t.pair_out_valid === 1'b1);
        do_pop_exp = (t.sample_en === 1'b1) && (q_len_pre != 0);

        // push_ok rule matches RTL: count <= DEPTH-2 based on pre-state count.
        if (depth_cfg < 2) begin
          // depth must be >=2; if not, treat as fatal because design contract violated
          $fatal(1, "[y_stream_monitor] depth_cfg=%0d invalid; must be >=2.", depth_cfg);
        end
        push_ok_exp = push_valid && (q_len_pre <= (depth_cfg - 2));

        // PAIRS MODE CHECKS (serializer correctness)
        if (mode == MODE_PAIRS || mode == MODE_BOTH) begin
          if (check_valid) begin
            if ((t.y_valid === 1'b1) != do_pop_exp) begin
              _fatal_or_count($sformatf("y_valid mismatch: dut=%0d expected=%0d (sample_en=%0d q_len_pre=%0d)",
                                        t.y_valid, do_pop_exp, t.sample_en, q_len_pre));
            end
          end

          if (do_pop_exp) begin
            if (q_len_pre == 0) begin
              _fatal_or_count("internal error: do_pop_exp set but q_len_pre==0");
            end else begin
              exp_pop = exp_q[0];
              if (t.y_valid !== 1'b1) begin
                _fatal_or_count("expected y_valid=1 due to do_pop_exp, but dut y_valid=0");
              end else begin
                if (^t.y_out === 1'bX) begin
                  _fatal_or_count("y_out is X when y_valid=1");
                end else begin
                  act_y = si64_t'($signed(t.y_out));
                  if (act_y != exp_pop) begin
                    _fatal_or_count($sformatf("serializer mismatch (pairs): dut y=%s exp=%s (q_len_pre=%0d)",
                                              fmt_si64(act_y), fmt_si64(exp_pop), q_len_pre));
                  end
                end
              end
            end
          end else begin
            // do_pop_exp==0: if y_valid asserted unexpectedly, it's already caught above.
            // no additional action
          end

          // Overflow check: push_valid but push_ok false means DUT will drop inputs and set sticky.
          if (push_valid && !push_ok_exp && !allow_overflow) begin
            _fatal_or_count($sformatf("FIFO overflow condition: pair_out_valid=1 but no space (q_len_pre=%0d depth=%0d)",
                                      q_len_pre, depth_cfg));
          end
        end

        // MEMH MODE CHECKS (bit-exact golden stream)
        if (t.y_valid === 1'b1) begin
          // Update last_* and trigger event later (after checks)
          last_m       = m;
          last_epoch   = epoch;
          last_time    = $time;
          last_y       = t.y_out;
          last_y_si64  = si64_t'($signed(t.y_out));

          last_have_memh  = 1'b0;
          last_have_pairs = 1'b0;
          last_exp_memh   = 64'sd0;
          last_exp_pairs  = 64'sd0;

          // memh expected
          if (mode == MODE_MEMH || mode == MODE_BOTH) begin
            last_have_memh = 1'b1;

            if (m >= y_exp.size()) begin
              _fatal_or_count($sformatf("memh index out of range: m=%0d y_exp.size()=%0d", m, y_exp.size()));
            end else begin
              exp_memh = y_exp[m];
              last_exp_memh = exp_memh;

              if (last_y_si64 != exp_memh) begin
                _fatal_or_count($sformatf("golden mismatch (memh): dut y=%s exp=%s",
                                          fmt_si64(last_y_si64), fmt_si64(exp_memh)));
              end else if (verbose) begin
                $display("[y_stream_monitor] m=%0d OK (memh) y=%0d", m, last_y_si64);
              end
            end
          end

          // pairs expected (if do_pop_exp true, we already computed exp_pop)
          if (mode == MODE_PAIRS || mode == MODE_BOTH) begin
            // do_pop_exp should be true when y_valid is true if check_valid is on,
            // but if check_valid is off we still can derive the expected value.
            if (q_len_pre != 0) begin
              last_have_pairs = 1'b1;
              last_exp_pairs  = exp_q[0];
            end
          end

          // capture history
          if (CAPTURE_HISTORY) begin
            y_evt_t e;
            e.m          = last_m;
            e.epoch      = last_epoch;
            e.sim_time   = last_time;
            e.y_act      = last_y_si64;
            e.y_exp_memh = last_exp_memh;
            e.y_exp_pairs= last_exp_pairs;
            e.have_memh  = last_have_memh;
            e.have_pairs = last_have_pairs;
            hist.push_back(e);
            if (MAX_HISTORY != 0 && hist.size() > MAX_HISTORY) begin
              hist.pop_front();
            end
          end

          // publish event for scoreboards
          -> y_ev;

          // advance memh index only on y_valid
          m++;
        end

        // Update expected queue model (pairs/both)
        if (mode == MODE_PAIRS || mode == MODE_BOTH) begin
          // Update order matches RTL: pop first (if do_pop and count!=0), then push.
          if (do_pop_exp && (exp_q.size() != 0)) begin
            void'(exp_q.pop_front());
          end

          if (push_ok_exp) begin
            // Validate y0/y1 not X
            if (^t.y0 === 1'bX || ^t.y1 === 1'bX) begin
              _fatal_or_count("y0/y1 contains X when pair_out_valid=1 (cannot build expected queue)");
            end else begin
              push_y0 = si64_t'($signed(t.y0));
              push_y1 = si64_t'($signed(t.y1));
              exp_q.push_back(push_y0);
              exp_q.push_back(push_y1);
            end
          end
        end
      end
    end
  endtask

endmodule : y_stream_monitor

`default_nettype wire

