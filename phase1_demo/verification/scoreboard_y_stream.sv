`timescale 1ns/1ps
`default_nettype none

// Arizona State University 
// Capstone Senior Project
// Sigma Force
// Dat Dinh, Dat Huynh, Paul Applebee, Kyung Jae Son
// scoreboard_y_stream.sv
//
// Fully functional scoreboard for the DUT serialized output stream (y_out/y_valid).
//
// It can validate y-stream correctness against up to three reference sources:
//
//   (1) MEMH stream reference (golden y.memh)
//       - Compares each observed y_out sample (when y_valid=1) against y_exp[m].
//
//   (2) MODEL stream reference (ref_model_phase1)
//       - Steps the SV reference model on each sample_en pulse and queues the
//         predicted (y0,y1) outputs in order.
//       - Compares each observed y_out sample against the front of that queue.
//
//   (3) PAIRS/serializer reference (DUT y0/y1 on pair_out_valid)
//       - Models the out_fifo_serializer behavior (push2/pop1) and checks:
//           * y_valid equals expected do_pop
//           * y_out equals expected FIFO pop value
//           * detects overflow conditions (push when no space)
//
// Notes:
//   - Sampling is done at negedge t.clk to avoid race with DUT posedge updates.
//   - This scoreboard is *stream-domain* (one sample at a time).
//   - For algorithm correctness at the pair level, see scoreboard_pairs.sv.
//   - For standalone serializer correctness checking, y_stream_monitor.sv already does
//     something similar; this file is the "scoreboard" version with model+memh support.
//
// Plusargs:
//   +Y_SB_DISABLE
//   +Y_SB_VERBOSE
//   +Y_SB_MAX_ERR=<N>              (default 10; 0 = never fatal by count)
//   +Y_SB_STOP_ON_ERR
//
//   +Y_SB_MODE=<mode string>
//       Modes (case-sensitive):
//         off
//         memh
//         model
//         pairs
//         memh_pairs   (or pairs_memh)
//         model_pairs  (or pairs_model)
//         memh_model   (or model_memh)      (value-only; no serializer checks)
//         all          (memh + model + pairs)
//
//   Files:
//     +Y_SB_Y_FILE=<path>          (default "y.memh")
//     +Y_MEMH=<path>               (alias)
//
//   Serializer model controls (pairs checking):
//     +Y_SB_DEPTH=<int>            (default parameter DEPTH)
//     +Y_SB_CHECK_VALID            (force y_valid check on)
//     +Y_SB_NO_CHECK_VALID         (force y_valid check off)
//     +Y_SB_ALLOW_OVERFLOW         (do not fatal when push arrives with no space)
//
//   Clear/reset behavior:
//     +Y_SB_EPOCH_ON_CLEAR         (default ON)
//     +Y_SB_NO_EPOCH_ON_CLEAR
//     +Y_SB_RESET_M_ON_CLEAR       (reset y sample index m on clr_metrics_pulse rising edge)
//     +Y_SB_STRICT_MEMH_LENGTH     (fatal if y_valid arrives after memh end)
//     +Y_SB_REQUIRE_FULL_MEMH      (fatal at end-of-sim if not all memh samples were checked)
//
// Public outputs/events:
//   - event y_sb_ev;                       // triggers each time a y_valid sample is processed
//   - last_* snapshot fields updated before y_sb_ev
//   - tasks: start(), stop(), report(), check_complete_memh(), check_no_pending_model()


module scoreboard_y_stream #(
  parameter int N       = 12,
  parameter int SHIFT   = 3,
  parameter int LFSR_W  = 16,
  parameter int DEPTH   = 4,
  parameter logic [LFSR_W-1:0] SEED = 16'hACE1,
  parameter bit AUTO_START = 1'b1
)(
  tap_if t
);

  import tb_pkg::*;

  
  // Event + last snapshot

  event y_sb_ev;

  int unsigned      last_m;
  int unsigned      last_epoch;
  longint unsigned  last_time;

  si64_t            last_act_y;

  bit               last_have_memh;
  si64_t            last_exp_memh;

  bit               last_have_model;
  si64_t            last_exp_model;

  bit               last_have_pairs;
  si64_t            last_exp_pairs;


  // Mode selection -> flags
  
  localparam int REF_MEMH  = 1;
  localparam int REF_MODEL = 2;
  localparam int REF_PAIRS = 4;

  function automatic int _parse_mode_mask(input string s);
    // Returns OR of REF_* bits
    if (s == "off" || s == "0" || s == "disable" || s == "disabled")
      _parse_mode_mask = 0;
    else if (s == "memh" || s == "file")
      _parse_mode_mask = REF_MEMH;
    else if (s == "model" || s == "predict" || s == "pred")
      _parse_mode_mask = REF_MODEL;
    else if (s == "pairs" || s == "pair" || s == "fifo")
      _parse_mode_mask = REF_PAIRS;
    else if (s == "all" || s == "everything")
      _parse_mode_mask = (REF_MEMH | REF_MODEL | REF_PAIRS);
    else if (s == "memh_pairs" || s == "pairs_memh" || s == "memh+pairs" || s == "pairs+memh")
      _parse_mode_mask = (REF_MEMH | REF_PAIRS);
    else if (s == "model_pairs" || s == "pairs_model" || s == "model+pairs" || s == "pairs+model")
      _parse_mode_mask = (REF_MODEL | REF_PAIRS);
    else if (s == "memh_model" || s == "model_memh" || s == "memh+model" || s == "model+memh" || s == "both")
      _parse_mode_mask = (REF_MEMH | REF_MODEL);
    else
      _parse_mode_mask = (REF_MEMH | REF_PAIRS); // safe default
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


  // Configuration

  bit disabled;
  bit verbose;

  int unsigned max_err;
  bit stop_on_err;

  bit use_memh;
  bit use_model;
  bit use_pairs;

  string y_file;

  int unsigned depth_cfg;

  bit check_valid;          // for pairs (serializer) y_valid check
  bit allow_overflow;       // allow push with no space (DUT drops + sticky)

  bit epoch_on_clear;       // track epoch increments on clr_metrics_pulse rising edge
  bit reset_m_on_clear;     // reset output sample index m on clear (OFF by default)
  bit strict_memh_length;   // fatal if y_valid beyond y_exp end
  bit require_full_memh;    // fatal at end-of-sim if not all y_exp checked

  
  // MEMH reference storage

  si64_t y_exp[$];
  bit    memh_done;


  // MODEL reference storage

  ref_model_phase1 #(
    .N(N),
    .SHIFT(SHIFT),
    .LFSR_W(LFSR_W),
    .SEED_DEFAULT(SEED)
  ) rm();

  // queue of expected y samples (in-order)
  si64_t model_q[$];


  // PAIRS/serializer reference storage (models out_fifo_serializer FIFO contents)

  si64_t fifo_q[$]; // acts like mem[rd_ptr..] in queue form


  // Runtime state

  bit running;
  bit stop_req;

  int unsigned m;
  int unsigned epoch;
  int unsigned err_count;


  // Error handling

  task automatic _fatal_or_count(input string msg);
    begin
      err_count++;
      $display("[scoreboard_y_stream] ERROR[%0d] m=%0d epoch=%0d : %s", err_count, m, epoch, msg);
      if (stop_on_err || (max_err != 0 && err_count >= max_err)) begin
        $fatal(1, "[scoreboard_y_stream] Too many errors (err_count=%0d, max_err=%0d).", err_count, max_err);
      end
    end
  endtask


  // Public control tasks

  task automatic start();
    if (running) begin
      $display("[scoreboard_y_stream] NOTE: start() called but already running.");
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

  task automatic report(input string tag = "scoreboard_y_stream");
    $display("[%s] mode(memh,model,pairs)=(%0d,%0d,%0d) y_seen=%0d epoch=%0d errors=%0d fifo_q=%0d model_q=%0d memh_done=%0d",
             tag, use_memh, use_model, use_pairs, m, epoch, err_count, fifo_q.size(), model_q.size(), memh_done);
  endtask

  // Verify that all memh samples were checked.
  task automatic check_complete_memh();
    begin
      if (!use_memh) begin
        $display("[scoreboard_y_stream] check_complete_memh: memh mode not enabled; skipping.");
        return;
      end
      if (m < y_exp.size()) begin
        $fatal(1, "[scoreboard_y_stream] MEMH NOT COMPLETE: checked %0d / %0d y samples.",
               m, y_exp.size());
      end
      $display("[scoreboard_y_stream] MEMH COMPLETE: checked %0d / %0d y samples.",
               m, y_exp.size());
    end
  endtask

  // Verify the model queue is empty.
  task automatic check_no_pending_model();
    begin
      if (!use_model) begin
        $display("[scoreboard_y_stream] check_no_pending_model: model mode not enabled; skipping.");
        return;
      end
      if (model_q.size() != 0) begin
        $fatal(1, "[scoreboard_y_stream] MODEL PENDING OUTPUTS: model_q has %0d unconsumed samples.", model_q.size());
      end
      $display("[scoreboard_y_stream] MODEL queue empty (no pending outputs).");
    end
  endtask


  // Initialization / plusargs

  initial begin
    running   = 1'b0;
    stop_req  = 1'b0;

    m         = 0;
    epoch     = 0;
    err_count = 0;

    fifo_q.delete();
    model_q.delete();
    y_exp.delete();
    memh_done = 1'b0;

    // defaults
    disabled   = 1'b0;
    verbose    = 1'b0;
    max_err    = 10;
    stop_on_err= 1'b0;

    y_file = "y.memh";
    void'($value$plusargs("Y_SB_Y_FILE=%s", y_file));
    void'($value$plusargs("Y_MEMH=%s", y_file));

    depth_cfg = DEPTH;
    void'($value$plusargs("Y_SB_DEPTH=%d", depth_cfg));

    allow_overflow = 1'b0;
    if ($test$plusargs("Y_SB_ALLOW_OVERFLOW")) allow_overflow = 1'b1;

    epoch_on_clear = 1'b1;
    if ($test$plusargs("Y_SB_NO_EPOCH_ON_CLEAR")) epoch_on_clear = 1'b0;
    if ($test$plusargs("Y_SB_EPOCH_ON_CLEAR"))    epoch_on_clear = 1'b1;

    reset_m_on_clear = 1'b0;
    if ($test$plusargs("Y_SB_RESET_M_ON_CLEAR")) reset_m_on_clear = 1'b1;

    strict_memh_length = 1'b0;
    if ($test$plusargs("Y_SB_STRICT_MEMH_LENGTH")) strict_memh_length = 1'b1;

    require_full_memh = 1'b0;
    if ($test$plusargs("Y_SB_REQUIRE_FULL_MEMH")) require_full_memh = 1'b1;

    if ($test$plusargs("Y_SB_DISABLE")) disabled = 1'b1;
    if ($test$plusargs("Y_SB_VERBOSE")) verbose  = 1'b1;

    void'($value$plusargs("Y_SB_MAX_ERR=%d", max_err));
    if ($test$plusargs("Y_SB_STOP_ON_ERR")) stop_on_err = 1'b1;

    // Determine mode flags
    begin
      int mask;
      string mstr;
      mstr = "";
      if ($value$plusargs("Y_SB_MODE=%s", mstr)) begin
        mask = _parse_mode_mask(mstr);
      end else begin
        // default: if y.memh exists -> memh+pairs else model+pairs
        if (_file_exists(y_file)) mask = (REF_MEMH | REF_PAIRS);
        else                      mask = (REF_MODEL | REF_PAIRS);
      end

      if (disabled) mask = 0;

      use_memh  = ((mask & REF_MEMH)  != 0);
      use_model = ((mask & REF_MODEL) != 0);
      use_pairs = ((mask & REF_PAIRS) != 0);
    end

    // check_valid default: ON if pairs enabled
    check_valid = use_pairs ? 1'b1 : 1'b0;
    if ($test$plusargs("Y_SB_CHECK_VALID"))    check_valid = 1'b1;
    if ($test$plusargs("Y_SB_NO_CHECK_VALID")) check_valid = 1'b0;

    // sanity: depth
    if (use_pairs && (depth_cfg < 2)) begin
      $fatal(1, "[scoreboard_y_stream] depth_cfg=%0d invalid; must be >= 2.", depth_cfg);
    end

    // load memh if requested
    if (use_memh) begin
      if (!_file_exists(y_file)) begin
        $fatal(1, "[scoreboard_y_stream] MEMH mode enabled but y_file not found: '%s'", y_file);
      end
      read_memh_signed(y_file, N, y_exp);
      if (y_exp.size() == 0) begin
        $fatal(1, "[scoreboard_y_stream] Loaded 0 samples from '%s'", y_file);
      end
      $display("[scoreboard_y_stream] Loaded y.memh: %0d samples from '%s'", y_exp.size(), y_file);
    end

    // reset the reference model to a known seed
    rm.reset_model(SEED, /*clear_hist*/ 1'b1);
    model_q.delete();

    if (use_memh || use_model || use_pairs) begin
      $display("[scoreboard_y_stream] Config:");
      $display("  use_memh=%0d use_model=%0d use_pairs=%0d", use_memh, use_model, use_pairs);
      $display("  y_file='%s' exists=%0d", y_file, _file_exists(y_file));
      $display("  depth_cfg=%0d check_valid=%0d allow_overflow=%0d", depth_cfg, check_valid, allow_overflow);
      $display("  epoch_on_clear=%0d reset_m_on_clear=%0d strict_memh_length=%0d require_full_memh=%0d",
               epoch_on_clear, reset_m_on_clear, strict_memh_length, require_full_memh);
      $display("  max_err=%0d stop_on_err=%0d verbose=%0d", max_err, stop_on_err, verbose);
      $display("  N=%0d SHIFT=%0d LFSR_W=%0d SEED=0x%0h", N, SHIFT, LFSR_W, SEED);
    end else begin
      $display("[scoreboard_y_stream] Disabled (mode=OFF).");
    end

    if (AUTO_START && (use_memh || use_model || use_pairs)) begin
      start();
    end
  end


  // Main run loop

  task automatic run();
    bit last_rst_n;
    bit last_clr;

    // MODEL step outputs (we only need y0/y1 when pair completes)
    bit    xv, pv;
    samp_t x_out;
    samp_t my0, my1;
    bit    msup;

    // serializer model locals
    int unsigned q_len_pre;
    bit          do_pop;
    bit          push_valid;
    bit          push_ok;
    si64_t       exp_pop_pairs;

    // sample actual and expected values
    si64_t act_y;
    si64_t exp_memh;
    si64_t exp_model;

    bit memh_extra_reported;

    begin
      last_rst_n = 1'b1;
      last_clr   = 1'b0;
      memh_extra_reported = 1'b0;

      // Wait for a non-X clock
      wait (^t.clk !== 1'bX);

      forever begin
        @(negedge t.clk);

        if (stop_req) begin
          $display("[scoreboard_y_stream] stop requested.");
          running = 1'b0;
          disable run;
        end

        // Reset handling
        if (!t.rst_n) begin
          if (last_rst_n) begin
            m         = 0;
            epoch     = 0;
            err_count = 0;

            fifo_q.delete();
            model_q.delete();

            // reset model state
            rm.reset_model(SEED, /*clear_hist*/ 1'b1);

            memh_done = 1'b0;
            memh_extra_reported = 1'b0;

            if (verbose) $display("[scoreboard_y_stream] Reset asserted: state cleared.");
          end
          last_rst_n = 1'b0;
          last_clr   = 1'b0;
          continue;
        end
        last_rst_n = 1'b1;

        // Handle clear-metrics pulse (epoch tracking only; stream should continue)
        if (t.clr_metrics_pulse && !last_clr) begin
          if (epoch_on_clear) epoch++;
          if (reset_m_on_clear) begin
            if (verbose) $display("[scoreboard_y_stream] clr_metrics_pulse: resetting m to 0.");
            m = 0;
          end
        end
        last_clr = t.clr_metrics_pulse;


        // MODEL stepping: drive reference model on each sample_en

        if (use_model && (t.sample_en === 1'b1)) begin
          rm.step_sample(int'(ui64_t'(t.thresh_used)),
                         (t.force_bypass === 1'b1),
                         xv, x_out, pv, my0, my1, msup);

          if (!xv) begin
            _fatal_or_count("ref_model returned x_valid=0 on sample_en (unexpected).");
          end

          if (pv) begin
            model_q.push_back(si64_t'($signed(my0)));
            model_q.push_back(si64_t'($signed(my1)));
          end
        end

        
        // PAIRS/serializer model: compute expected pop/push for THIS cycle

        if (use_pairs) begin
          q_len_pre  = fifo_q.size();
          do_pop     = (t.sample_en === 1'b1) && (q_len_pre != 0);
          push_valid = (t.pair_out_valid === 1'b1);
          push_ok    = push_valid && (q_len_pre <= (depth_cfg - 2));

          // y_valid check
          if (check_valid) begin
            if ((t.y_valid === 1'b1) != do_pop) begin
              _fatal_or_count($sformatf("y_valid mismatch: dut=%0d exp=%0d (sample_en=%0d q_len_pre=%0d)",
                                        t.y_valid, do_pop, t.sample_en, q_len_pre));
            end
          end

          // y_out check when a pop is expected
          if (do_pop) begin
            if (q_len_pre == 0) begin
              _fatal_or_count("internal error: do_pop=1 but q_len_pre==0");
            end else begin
              exp_pop_pairs = fifo_q[0];

              if (t.y_valid !== 1'b1) begin
                _fatal_or_count("expected y_valid=1 due to do_pop, but dut y_valid!=1");
              end else if (^t.y_out === 1'bX) begin
                _fatal_or_count("y_out is X when y_valid=1");
              end else begin
                act_y = si64_t'($signed(t.y_out));
                if (act_y != exp_pop_pairs) begin
                  _fatal_or_count($sformatf("serializer mismatch: dut y=%s exp=%s (q_len_pre=%0d)",
                                            fmt_si64(act_y), fmt_si64(exp_pop_pairs), q_len_pre));
                end else if (verbose) begin
                  $display("[scoreboard_y_stream] PAIRS OK: y=%0d (q_len_pre=%0d)", act_y, q_len_pre);
                end
              end
            end
          end

          // Overflow check (push when no room)
          if (push_valid && !push_ok && !allow_overflow) begin
            _fatal_or_count($sformatf("FIFO overflow condition: pair_out_valid=1 but no space (q_len_pre=%0d depth=%0d)",
                                      q_len_pre, depth_cfg));
          end
        end


        // Stream-value checks: whenever DUT produces a y sample

        if (t.y_valid === 1'b1) begin
          if (^t.y_out === 1'bX) begin
            _fatal_or_count("y_out is X when y_valid=1 (cannot compare to references)");
            act_y = 64'sd0;
          end else begin
            act_y = si64_t'($signed(t.y_out));
          end

          // Prepare snapshot defaults
          last_m        = m;
          last_epoch    = epoch;
          last_time     = $time;
          last_act_y    = act_y;

          last_have_memh  = 1'b0;
          last_exp_memh   = 64'sd0;
          last_have_model = 1'b0;
          last_exp_model  = 64'sd0;
          last_have_pairs = 1'b0;
          last_exp_pairs  = 64'sd0;

          // MEMH compare
          if (use_memh) begin
            if (!memh_done) begin
              if (m >= y_exp.size()) begin
                memh_done = 1'b1;
                if (strict_memh_length) begin
                  _fatal_or_count($sformatf("memh overrun: m=%0d but y_exp.size()=%0d", m, y_exp.size()));
                end else if (!memh_extra_reported) begin
                  memh_extra_reported = 1'b1;
                  $display("[scoreboard_y_stream] NOTE: reached end of y.memh at m=%0d (size=%0d). Further y_valid samples will not be compared to memh unless strict enabled.",
                           m, y_exp.size());
                end
              end else begin
                exp_memh = y_exp[m];
                last_have_memh = 1'b1;
                last_exp_memh  = exp_memh;

                if (act_y != exp_memh) begin
                  _fatal_or_count($sformatf("MEMH mismatch: m=%0d dut=%s exp=%s",
                                            m, fmt_si64(act_y), fmt_si64(exp_memh)));
                end else if (verbose) begin
                  $display("[scoreboard_y_stream] MEMH OK: m=%0d y=%0d", m, act_y);
                end
              end
            end
          end

          // MODEL compare
          if (use_model) begin
            if (model_q.size() == 0) begin
              _fatal_or_count($sformatf("MODEL underflow: y_valid at m=%0d but model_q is empty", m));
            end else begin
              exp_model = model_q[0];
              last_have_model = 1'b1;
              last_exp_model  = exp_model;

              if (act_y != exp_model) begin
                _fatal_or_count($sformatf("MODEL mismatch: m=%0d dut=%s exp=%s (model_q_len=%0d)",
                                          m, fmt_si64(act_y), fmt_si64(exp_model), model_q.size()));
              end else if (verbose) begin
                $display("[scoreboard_y_stream] MODEL OK: m=%0d y=%0d", m, act_y);
              end

              // consume expected sample
              void'(model_q.pop_front());
            end
          end

          // PAIRS expected value snapshot (only meaningful if do_pop true)
          if (use_pairs) begin
            // If check_valid is on, y_valid implies do_pop, so q_len_pre>0 and exp_pop_pairs computed.
            // If check_valid is off, we can only snapshot if fifo_q currently non-empty.
            if (fifo_q.size() != 0) begin
              last_have_pairs = 1'b1;
              last_exp_pairs  = fifo_q[0];
            end
          end

          // Cross-check MEMH vs MODEL expected values (debug assist)
          if (use_memh && use_model && last_have_memh && last_have_model) begin
            if (last_exp_memh != last_exp_model) begin
              _fatal_or_count($sformatf("REF mismatch (memh vs model) at m=%0d: memh=%s model=%s",
                                        m, fmt_si64(last_exp_memh), fmt_si64(last_exp_model)));
            end
          end

          // publish event
          -> y_sb_ev;

          // advance stream index
          m++;
        end


        // Update PAIRS FIFO model queue AFTER checks (pop then push)

        if (use_pairs) begin
          // Note: use do_pop/push_ok computed from PRE-STATE q_len_pre earlier this cycle.
          if (do_pop && (fifo_q.size() != 0)) begin
            void'(fifo_q.pop_front());
          end

          if (push_ok) begin
            if (^t.y0 === 1'bX || ^t.y1 === 1'bX) begin
              _fatal_or_count("y0/y1 is X when push_ok=1 (cannot update serializer model)");
            end else begin
              fifo_q.push_back(si64_t'($signed(t.y0)));
              fifo_q.push_back(si64_t'($signed(t.y1)));
            end
          end
        end
      end
    end
  endtask


  // Final summary + optional strict completion checks

  final begin
    if (use_memh || use_model || use_pairs) begin
      report("scoreboard_y_stream_final");
      if (require_full_memh && use_memh) begin
        if (m < y_exp.size()) begin
          $fatal(1, "[scoreboard_y_stream] REQUIRE_FULL_MEMH failed: checked %0d / %0d y samples.",
                 m, y_exp.size());
        end
      end
    end
  end

endmodule : scoreboard_y_stream

`default_nettype wire

