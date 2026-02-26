`timescale 1ns/1ps
`default_nettype none

// Arizona State University 
// Capstone Senior Project
// Sigma Force
// Dat Dinh, Dat Huynh, Paul Applebee, Kyung Jae Son
// x_stream_monitor.sv
//
// Fully functional monitor for the DUT internal x_stream.
//
// What it does:
//   - Watches tap_if.sample_en
//   - On each sample_en, samples tap_if.x_stream and compares to a reference
//
// Reference options (select via plusargs):
//   +X_MON_MODE=memh     : compare against x.memh (default if file exists)
//   +X_MON_MODE=predict  : compare against internal predictor (LFSR+shaper)
//   +X_MON_MODE=both     : compare against both (and cross-check them)
//   +X_MON_MODE=off      : disable monitor
//
// File control:
//   +X_MON_FILE=<path>   : path to x.memh (default "x.memh")
//
// Behavior control:
//   +X_MON_MAX_ERR=<N>   : max mismatches before fatal (default 10)
//   +X_MON_STOP_ON_ERR   : fatal on first mismatch
//   +X_MON_VERBOSE       : print per-sample info (noisy)
//
// Design matches t_recap_demo_top defaults:
//   - LFSR taps: bit0^bit2^bit3^bit5, shift-right insert at MSB
//   - LFSR seeded to SEED (default 16'hACE1) on reset
//   - noise_shaper update: s = s + asr(u - s, SHIFT), x = satN(s)
//
// IMPORTANT timing note:
//   - We sample on *negedge clk* to avoid race with DUT posedge FF updates.


module x_stream_monitor #(
  parameter int N       = 12,
  parameter int SHIFT   = 3,
  parameter int LFSR_W  = 16,
  parameter logic [LFSR_W-1:0] SEED = 16'hACE1,
  parameter bit AUTO_START = 1'b1
)(
  tap_if t
);

  import tb_pkg::*;


  // Configuration (from plusargs)

  typedef enum int {MODE_OFF=0, MODE_MEMH=1, MODE_PRED=2, MODE_BOTH=3} mode_e;

  mode_e mode;

  string x_file;

  int unsigned max_err;
  bit          stop_on_err;
  bit          verbose;


  // Reference storage (memh)

  si64_t x_exp[$];


  // Predictor state

  logic [LFSR_W-1:0] lfsr_pred;
  si64_t             shaper_pred;


  // Monitor bookkeeping

  bit running;
  bit stop_req;

  int unsigned n_checked;
  int unsigned err_count;


  // Helpers

  function automatic mode_e _parse_mode(input string s);
    string ts;
    begin
      ts = s;
      // normalize a few common spellings
      if (ts == "off" || ts == "0" || ts == "disable" || ts == "disabled") _parse_mode = MODE_OFF;
      else if (ts == "memh" || ts == "file")                                _parse_mode = MODE_MEMH;
      else if (ts == "predict" || ts == "pred" || ts == "model")             _parse_mode = MODE_PRED;
      else if (ts == "both" || ts == "all")                                  _parse_mode = MODE_BOTH;
      else                                                                    _parse_mode = MODE_MEMH;
    end
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

  task automatic _reset_predictor();
    begin
      lfsr_pred   = SEED;
      shaper_pred = 64'sd0;
    end
  endtask

  // Compute next predicted x sample (spec ordering: step LFSR then map then shaper).
  task automatic _predict_next_x(output si64_t x_pred, output si64_t u_pred);
    samp_t u_samp;
    si64_t diff, delta;
    begin
      // LFSR step
      lfsr_pred = lfsr_next(lfsr_pred);

      // map to centered signed noise (in N-bit range)
      u_samp = map_lfsr_to_centered_noise(lfsr_pred);
      u_pred = si64_t'($signed(u_samp));

      // shaper update
      diff       = u_pred - shaper_pred;
      delta      = asr64(diff, SHIFT);
      shaper_pred= shaper_pred + delta;

      // output
      x_pred = satN64(shaper_pred);
    end
  endtask

  task automatic _fatal_or_count(input string msg);
    begin
      err_count++;
      $display("[x_stream_monitor] ERROR[%0d] n=%0d : %s", err_count, n_checked, msg);
      if (stop_on_err || (max_err != 0 && err_count >= max_err)) begin
        $fatal(1, "[x_stream_monitor] Too many errors (err_count=%0d, max_err=%0d).", err_count, max_err);
      end
    end
  endtask


  // Public-ish tasks (callable hierarchically if desired)

  task automatic start();
    if (running) begin
      $display("[x_stream_monitor] NOTE: start() called but monitor already running.");
      return;
    end
    stop_req  = 1'b0;
    running   = 1'b1;
    fork
      run();
    join_none
  endtask

  task automatic stop();
    stop_req = 1'b1;
  endtask

  task automatic report(input string tag = "x_stream_monitor");
    $display("[%s] checked=%0d errors=%0d mode=%0d (OFF=0 MEMH=1 PRED=2 BOTH=3)",
             tag, n_checked, err_count, mode);
  endtask


  // Initialization (plusargs + loading)

  initial begin
    running   = 1'b0;
    stop_req  = 1'b0;
    n_checked = 0;
    err_count = 0;

    x_file = "x.memh";
    void'($value$plusargs("X_MON_FILE=%s", x_file));
    // also accept the same plusarg name used by golden_files_loader, if present
    void'($value$plusargs("X_MEMH=%s", x_file));

    max_err     = 10;
    stop_on_err = 1'b0;
    verbose     = 1'b0;

    void'($value$plusargs("X_MON_MAX_ERR=%d", max_err));
    if ($test$plusargs("X_MON_STOP_ON_ERR")) stop_on_err = 1'b1;
    if ($test$plusargs("X_MON_VERBOSE"))     verbose     = 1'b1;

    // mode default:
    //   - if +X_MON_MODE is provided, use it
    //   - else if x_file exists -> memh
    //   - else -> predict
    begin
      string mstr;
      mstr = "";
      if ($value$plusargs("X_MON_MODE=%s", mstr)) begin
        mode = _parse_mode(mstr);
      end else begin
        if (_file_exists(x_file)) mode = MODE_MEMH;
        else                      mode = MODE_PRED;
      end
    end

    // hard disable
    if ($test$plusargs("X_MON_DISABLE")) mode = MODE_OFF;

    if (mode == MODE_OFF) begin
      $display("[x_stream_monitor] Disabled (mode=OFF).");
    end else begin
      $display("[x_stream_monitor] Config:");
      $display("  mode=%0d (OFF=0 MEMH=1 PRED=2 BOTH=3)", mode);
      $display("  x_file='%s'", x_file);
      $display("  N=%0d SHIFT=%0d LFSR_W=%0d SEED=0x%0h", N, SHIFT, LFSR_W, SEED);
      $display("  max_err=%0d stop_on_err=%0d verbose=%0d", max_err, stop_on_err, verbose);
    end

    // load memh if needed
    if (mode == MODE_MEMH || mode == MODE_BOTH) begin
      if (!_file_exists(x_file)) begin
        $fatal(1, "[x_stream_monitor] Requested memh mode but file not found: '%s'", x_file);
      end
      read_memh_signed(x_file, N, x_exp);
      if (x_exp.size() == 0) begin
        $fatal(1, "[x_stream_monitor] x.memh loaded 0 entries from '%s'", x_file);
      end
      $display("[x_stream_monitor] Loaded %0d expected x samples from '%s'.", x_exp.size(), x_file);
    end

    // init predictor
    _reset_predictor();

    if (AUTO_START && mode != MODE_OFF) begin
      start();
    end
  end


  // Main run loop

  task automatic run();
    bit last_rst_n;
    si64_t x_act;
    si64_t x_ref_memh;
    si64_t x_ref_pred;
    si64_t u_pred;

    bit    have_memh;
    bit    have_pred;

    begin
      last_rst_n = 1'b1;

      // Wait for clock to become known
      wait (^t.clk !== 1'bX);

      forever begin
        // Sample on negedge to avoid race with DUT posedge updates
        @(negedge t.clk);

        if (stop_req) begin
          $display("[x_stream_monitor] stop requested.");
          running = 1'b0;
          disable run;
        end

        // Reset handling: on reset asserted, clear index + predictor
        if (!t.rst_n) begin
          if (last_rst_n) begin
            // reset just asserted
            n_checked = 0;
            err_count = 0; // typically you want clean slate across reset
            _reset_predictor();
            if (verbose) $display("[x_stream_monitor] Observed reset assert: counters cleared.");
          end
          last_rst_n = 1'b0;
          continue;
        end
        last_rst_n = 1'b1;

        // Only check on sample_en pulses
        if (!t.sample_en) begin
          continue;
        end

        // Detect X on x_stream
        if (^t.x_stream === 1'bX) begin
          _fatal_or_count($sformatf("x_stream is X at sample_en"));
          // still advance reference states to keep alignment? No: X implies broken.
          continue;
        end

        // Actual value (sign-extended)
        x_act = si64_t'($signed(t.x_stream));

        // Determine references
        have_memh = (mode == MODE_MEMH || mode == MODE_BOTH);
        have_pred = (mode == MODE_PRED || mode == MODE_BOTH);

        // predictor step must happen exactly once per checked sample if enabled
        if (have_pred) begin
          _predict_next_x(x_ref_pred, u_pred);
        end

        if (have_memh) begin
          if (n_checked >= x_exp.size()) begin
            _fatal_or_count($sformatf("Index out of range: n=%0d but x_exp.size()=%0d",
                                      n_checked, x_exp.size()));
            // do not compare further this cycle
            n_checked++;
            continue;
          end
          x_ref_memh = x_exp[n_checked];
        end

        // Cross-check memh vs predictor (useful to catch loader/predictor bugs)
        if (have_memh && have_pred) begin
          if (x_ref_memh != x_ref_pred) begin
            _fatal_or_count($sformatf("REF mismatch memh vs pred at n=%0d: memh=%s pred=%s",
                                      n_checked, fmt_si64(x_ref_memh), fmt_si64(x_ref_pred)));
          end
        end

        // Choose the reference for comparing to DUT
        if (have_memh) begin
          if (x_act != x_ref_memh) begin
            _fatal_or_count($sformatf("DUT x != memh at n=%0d: dut=%s exp=%s  (dut_lfsr=0x%0h dut_u=%0d)",
                                      n_checked, fmt_si64(x_act), fmt_si64(x_ref_memh),
                                      t.lfsr_rnd, si64_t'($signed(t.u_noise))));
          end else if (verbose) begin
            $display("[x_stream_monitor] n=%0d OK dut=%0d exp=%0d",
                     n_checked, x_act, x_ref_memh);
          end
        end else if (have_pred) begin
          if (x_act != x_ref_pred) begin
            _fatal_or_count($sformatf("DUT x != pred at n=%0d: dut=%s pred=%s (u_pred=%0d dut_u=%0d dut_lfsr=0x%0h)",
                                      n_checked, fmt_si64(x_act), fmt_si64(x_ref_pred),
                                      x_ref_pred, si64_t'($signed(t.u_noise)), t.lfsr_rnd));
          end else if (verbose) begin
            $display("[x_stream_monitor] n=%0d OK dut=%0d pred=%0d",
                     n_checked, x_act, x_ref_pred);
          end
        end

        n_checked++;
      end
    end
  endtask

endmodule : x_stream_monitor

`default_nettype wire
