
`timescale 1ns/1ps
`default_nettype none

// Arizona State University 
// Capstone Senior Project
// Sigma Force
// Dat Dinh, Dat Huynh, Paul Applebee, Kyung Jae Son
// ref_model_phase1.sv
//
// Bit-accurate SystemVerilog reference model for T-RECAP Phase 1.
//
// Implements the frozen Phase-1 contract (see Phase-1 algorithm spec):
//   1) LFSR update (example taps, W=16):
//        b = r0 ^ r2 ^ r3 ^ r5
//        r = (r >> 1) | (b << (W-1))
//   2) Map low N bits to signed centered noise:
//        u = (r mod 2^N) - 2^(N-1)
//   3) Noise shaper (first-order leaky integrator):
//        s = s + asr(u - s, SHIFT)
//        x = satN(s)
//   4) Pairing (non-overlapping):
//        (x0[k], x1[k]) = (x[2k], x[2k+1])
//   5) Haar + selective suppression:
//        a = x0 + x1
//        d = x0 - x1
//        sk = 1 if |d| < T else 0
//        d' = 0 if sk else d
//   6) Inverse Haar with divide-by-2 rounding ties-away-from-zero:
//        y0 = satN(rnd2(a + d'))
//        y1 = satN(rnd2(a - d'))
//        y[2k] = y0, y[2k+1] = y1
//   7) Metrics:
//        total_pairs++
//        suppressed_pairs += sk
//        sum_abs_err += |x0 - y0| + |x1 - y1|
//        sum_sq_err  += (x0 - y0)^2 + (x1 - y1)^2
//
// This reference model is designed to be driven by the TB in one of two ways:
//   A) Offline: call run_nsamp()/run_pairs() and then use x_stream/y_stream/sup_pair.
//   B) Online/lockstep: call step_sample() every time you observe DUT sample_en,
//      passing the current threshold (and bypass bit if desired).
//
// Note: This is NOT a UVM component, it is a lightweight predictor model.


module ref_model_phase1 #(
  parameter int N         = 12,
  parameter int SHIFT     = 3,
  parameter int LFSR_W    = 16,
  parameter logic [LFSR_W-1:0] SEED_DEFAULT = 16'hACE1
);


  // Types / ranges

  typedef longint signed   si64_t;
  typedef longint unsigned ui64_t;

  typedef logic signed [N-1:0] samp_t;

  localparam si64_t ONE64 = 64'sd1;

  // N-bit signed numeric limits (in 64-bit domain)
  function automatic si64_t minN64();
    minN64 = -(ONE64 <<< (N-1));
  endfunction
  function automatic si64_t maxN64();
    maxN64 = (ONE64 <<< (N-1)) - ONE64;
  endfunction


  // Public outputs/state (TB reads these)


  // Generated/processed streams (signed integer values)
  si64_t x_stream[$];   // length = nsamp
  si64_t y_stream[$];   // length = nsamp (even)
  bit    sup_pair[$];   // length = nsamp/2, 1 flag per pair

  // Metrics (64-bit to avoid overflow)
  ui64_t total_pairs;
  ui64_t suppressed_pairs;
  ui64_t sum_abs_err;
  ui64_t sum_sq_err;

  // Current generator state (exposed for debug, TB may read)
  logic [LFSR_W-1:0] lfsr_state;
  si64_t             shaper_state;

  // Indices (counts how many samples/pairs have been produced so far)
  ui64_t samp_count;
  ui64_t pair_count;

  // Last-step outputs (convenient for online driving)
  samp_t last_x;
  bit    last_x_valid;

  samp_t last_y0, last_y1;
  bit    last_pair_valid;
  bit    last_suppressed;
  si64_t last_a;
  si64_t last_d;
  ui64_t last_abs_d;

  
  // Internal pair assembly state

  bit   have_x0;
  si64_t x0_hold;


  // Helper functions (bit-accurate)


  function automatic ui64_t abs64(input si64_t v);
    abs64 = (v < 0) ? ui64_t'(-v) : ui64_t'(v);
  endfunction

  // Arithmetic shift right: SystemVerilog >>> on signed performs sign-extension
  // and matches floor division by 2^k for negative numbers.
  function automatic si64_t asr64(input si64_t v, input int unsigned k);
    if (k == 0) asr64 = v;
    else        asr64 = (v >>> k);
  endfunction

  // Saturate to N-bit signed range (returns 64-bit integer, clamped).
  function automatic si64_t satN64(input si64_t v);
    si64_t lo, hi;
    begin
      lo = minN64();
      hi = maxN64();
      if (v < lo)      satN64 = lo;
      else if (v > hi) satN64 = hi;
      else             satN64 = v;
    end
  endfunction

  // Divide-by-2 with rounding ties-away-from-zero (rnd2 contract).
  // For odd numbers:
  //   +odd => (n+1)/2
  //   -odd => (n-1)/2
  function automatic si64_t rnd2_ties_away(input si64_t num);
    si64_t adj;
    begin
      if ((num & ONE64) == 0) adj = num;
      else if (num >= 0)      adj = num + ONE64;
      else                    adj = num - ONE64;
      rnd2_ties_away = adj / 2;
    end
  endfunction

  // LFSR step with taps {0,2,3,5} when shifting right.
  function automatic logic [LFSR_W-1:0] lfsr_step(input logic [LFSR_W-1:0] s);
    logic b;
    begin
      // Works for W>=6. For this project W is expected to be 16.
      b = s[0] ^ s[2] ^ s[3] ^ s[5];
      lfsr_step = {b, s[LFSR_W-1:1]};
    end
  endfunction

  // Map low N bits of LFSR to signed centered noise:
  //   u = (lfsr & ((1<<N)-1)) - 2^(N-1)
  function automatic si64_t map_lfsr_to_u(input logic [LFSR_W-1:0] s);
    ui64_t mask;
    ui64_t u_unsigned;
    si64_t centered;
    begin
      // Guard supported range (matches C++ golden model limits)
      if (N < 2 || N > 30) begin
        $fatal(1, "ref_model_phase1: N=%0d out of supported range (2..30).", N);
      end
      mask = (ui64_t'(1) << N) - ui64_t'(1);
      u_unsigned = ui64_t'(s) & mask;
      centered   = si64_t'(u_unsigned) - (ONE64 <<< (N-1));
      map_lfsr_to_u = centered;
    end
  endfunction

  // Compute one Haar pair output (pure function).
  task automatic haar_pair_compute(
    input  si64_t      x0,
    input  si64_t      x1,
    input  ui64_t      thresh_nonneg,
    output si64_t      y0,
    output si64_t      y1,
    output bit         suppressed,
    output si64_t      a,
    output si64_t      d,
    output ui64_t      abs_d
  );
    si64_t dp;
    si64_t num0, num1;
    begin
      a = x0 + x1;
      d = x0 - x1;
      abs_d = abs64(d);

      suppressed = (abs_d < thresh_nonneg);
      dp = suppressed ? 64'sd0 : d;

      num0 = a + dp;
      num1 = a - dp;

      y0 = satN64(rnd2_ties_away(num0));
      y1 = satN64(rnd2_ties_away(num1));
    end
  endtask


  // Reset / control tasks


  task automatic clear_history();
    x_stream.delete();
    y_stream.delete();
    sup_pair.delete();
  endtask

  task automatic clear_metrics();
    total_pairs      = 0;
    suppressed_pairs = 0;
    sum_abs_err      = 0;
    sum_sq_err       = 0;
  endtask

  task automatic reset_model(
    input logic [LFSR_W-1:0] seed = SEED_DEFAULT,
    input bit clear_hist = 1'b1
  );
    begin
      if (seed == '0) begin
        $fatal(1, "ref_model_phase1: seed must be non-zero for LFSR.");
      end
      if (LFSR_W < 6) begin
        $fatal(1, "ref_model_phase1: LFSR_W must be >= 6 (got %0d).", LFSR_W);
      end

      lfsr_state   = seed;
      shaper_state = 64'sd0;

      have_x0      = 1'b0;
      x0_hold      = 64'sd0;

      samp_count   = 0;
      pair_count   = 0;

      last_x         = '0;
      last_x_valid   = 1'b0;
      last_y0        = '0;
      last_y1        = '0;
      last_pair_valid= 1'b0;
      last_suppressed= 1'b0;
      last_a         = 64'sd0;
      last_d         = 64'sd0;
      last_abs_d     = 0;

      clear_metrics();
      if (clear_hist) clear_history();
    end
  endtask


  // Single-step API (online / lockstep)


  // Step the model by exactly 1 sample.
  //
  // Arguments:
  //   thresh_in  : threshold magnitude (non-negative). Only used on pair completion.
  //   bypass     : if 1, forces threshold to 0 (lossless path).
  //
  // Returns (via last_* + outputs):
  //   x_valid=1 always, x_out is new x sample (N-bit clipped)
  //   pair_valid=1 only every 2nd call; then y0/y1/suppressed correspond to that pair
  task automatic step_sample(
    input  int unsigned thresh_in,
    input  bit          bypass,
    output bit          x_valid,
    output samp_t       x_out,
    output bit          pair_valid,
    output samp_t       y0_out,
    output samp_t       y1_out,
    output bit          suppressed_out
  );
    si64_t u;
    si64_t diff, delta;
    si64_t x64;

    // pair-related
    ui64_t T;
    si64_t y0_64, y1_64;
    si64_t a64, d64;
    ui64_t absd64;

    si64_t x1_hold;
    si64_t e0, e1;
    begin
      // defaults
      x_valid        = 1'b0;
      x_out          = '0;
      pair_valid     = 1'b0;
      y0_out         = '0;
      y1_out         = '0;
      suppressed_out = 1'b0;

      last_x_valid    = 1'b0;
      last_pair_valid = 1'b0;

      // 1) LFSR step (IMPORTANT: step before mapping, matches golden_model.cpp)
      lfsr_state = lfsr_step(lfsr_state);

      // 2) map -> centered noise
      u = map_lfsr_to_u(lfsr_state);

      // 3) shaper update
      diff        = u - shaper_state;
      delta       = asr64(diff, SHIFT);
      shaper_state= shaper_state + delta;

      // 4) x[n] = satN(s)
      x64 = satN64(shaper_state);

      // publish x
      x_out       = samp_t'(x64[N-1:0]);
      x_valid     = 1'b1;
      last_x      = x_out;
      last_x_valid= 1'b1;

      // store stream
      x_stream.push_back(x64);
      samp_count++;

      // 5) pair assembly
      if (!have_x0) begin
        x0_hold = x64;
        have_x0 = 1'b1;
      end else begin
        x1_hold = x64;
        have_x0 = 1'b0;

        // threshold selection
        T = bypass ? ui64_t'(0) : ui64_t'(thresh_in);

        // 6) Haar pair compute
        haar_pair_compute(x0_hold, x1_hold, T, y0_64, y1_64, suppressed_out, a64, d64, absd64);

        // store pair outputs to stream arrays
        y_stream.push_back(y0_64);
        y_stream.push_back(y1_64);
        sup_pair.push_back(suppressed_out);

        // update last pair debug
        last_y0         = samp_t'(y0_64[N-1:0]);
        last_y1         = samp_t'(y1_64[N-1:0]);
        last_suppressed = suppressed_out;
        last_a          = a64;
        last_d          = d64;
        last_abs_d      = absd64;

        // publish pair outputs
        y0_out     = last_y0;
        y1_out     = last_y1;
        pair_valid = 1'b1;

        last_pair_valid = 1'b1;

        // 7) metrics update
        e0 = x0_hold - y0_64;
        e1 = x1_hold - y1_64;

        total_pairs      += 1;
        suppressed_pairs += (suppressed_out ? 1 : 0);
        sum_abs_err      += abs64(e0) + abs64(e1);
        sum_sq_err       += ui64_t'(e0*e0) + ui64_t'(e1*e1);

        pair_count++;
      end
    end
  endtask

  // Convenience: step with bypass=0.
  task automatic step_sample_thresh(
    input  int unsigned thresh_in,
    output bit          x_valid,
    output samp_t       x_out,
    output bit          pair_valid,
    output samp_t       y0_out,
    output samp_t       y1_out,
    output bit          suppressed_out
  );
    step_sample(thresh_in, 1'b0, x_valid, x_out, pair_valid, y0_out, y1_out, suppressed_out);
  endtask


  // Offline run APIs (batch)

  // Run nsamp samples (rounded down to even like golden_model.cpp) with constant threshold.
  // If reset_first=1, the model state/history/metrics are reset before running.
  task automatic run_nsamp(
    input  int          nsamp,
    input  int unsigned thresh_in,
    input  bit          bypass      = 1'b0,
    input  bit          reset_first = 1'b1,
    input  logic [LFSR_W-1:0] seed  = SEED_DEFAULT
  );
    int n_adj;
    bit xv, pv;
    samp_t xo, y0o, y1o;
    bit supo;
    begin
      if (reset_first) reset_model(seed, /*clear_hist*/ 1'b1);

      // match golden behavior: if nsamp odd, drop last sample
      n_adj = nsamp;
      if ((n_adj % 2) != 0) begin
        n_adj = n_adj - 1;
        $display("[ref_model_phase1] NOTE: nsamp must be even; rounding down to %0d.", n_adj);
      end
      if (n_adj < 0) n_adj = 0;

      for (int i = 0; i < n_adj; i++) begin
        step_sample(thresh_in, bypass, xv, xo, pv, y0o, y1o, supo);
      end

      // Sanity: output sizes should match adjusted sample count
      if (x_stream.size() != n_adj)
        $fatal(1, "ref_model_phase1: internal error: x_stream.size()=%0d expected %0d", x_stream.size(), n_adj);
      if (y_stream.size() != n_adj)
        $fatal(1, "ref_model_phase1: internal error: y_stream.size()=%0d expected %0d", y_stream.size(), n_adj);
      if (sup_pair.size() != (n_adj/2))
        $fatal(1, "ref_model_phase1: internal error: sup_pair.size()=%0d expected %0d", sup_pair.size(), (n_adj/2));
    end
  endtask

  // Run exactly K pairs with constant threshold (i.e. 2K samples).
  task automatic run_pairs(
    input  int          Kpairs,
    input  int unsigned thresh_in,
    input  bit          bypass      = 1'b0,
    input  bit          reset_first = 1'b1,
    input  logic [LFSR_W-1:0] seed  = SEED_DEFAULT
  );
    int nsamp;
    begin
      if (Kpairs < 0) Kpairs = 0;
      nsamp = 2 * Kpairs;
      run_nsamp(nsamp, thresh_in, bypass, reset_first, seed);
    end
  endtask


  // Utility checks / dumps

  // Required property: if T=0 (or bypass=1), the transform must be lossless:
  // y_stream[i] == x_stream[i] for all i, and error metrics are zero.
  task automatic check_lossless_T0();
    begin
      if (x_stream.size() != y_stream.size()) begin
        $fatal(1, "ref_model_phase1: lossless check failed: x/y size mismatch x=%0d y=%0d",
               x_stream.size(), y_stream.size());
      end
      for (int i = 0; i < x_stream.size(); i++) begin
        if (x_stream[i] !== y_stream[i]) begin
          $fatal(1, "ref_model_phase1: lossless check failed at i=%0d: x=%0d y=%0d",
                 i, x_stream[i], y_stream[i]);
        end
      end
      if (sum_abs_err != 0 || sum_sq_err != 0 || suppressed_pairs != 0) begin
        $fatal(1, "ref_model_phase1: lossless check failed: sum_abs_err=%0d sum_sq_err=%0d suppressed_pairs=%0d",
               sum_abs_err, sum_sq_err, suppressed_pairs);
      end
    end
  endtask

  // Dump the generated streams to memh/flag files (handy for debugging).
  task automatic dump_memh_signed(
    input string filename,
    input si64_t data[$]
  );
    int fd;
    int hexw;
    ui64_t mask;
    ui64_t u;
    begin
      fd = $fopen(filename, "w");
      if (fd == 0) $fatal(1, "ref_model_phase1: failed to open '%s' for write", filename);

      hexw = (N + 3) / 4;
      mask = (ui64_t'(1) << N) - ui64_t'(1);

      for (int i = 0; i < data.size(); i++) begin
        // two's complement in low N bits
        u = ui64_t'(data[i]) & mask;
        $fdisplay(fd, "%0h", u);
      end

      $fclose(fd);
    end
  endtask

  task automatic dump_flags01(
    input string filename,
    input bit flags[$]
  );
    int fd;
    begin
      fd = $fopen(filename, "w");
      if (fd == 0) $fatal(1, "ref_model_phase1: failed to open '%s' for write", filename);

      for (int i = 0; i < flags.size(); i++) begin
        $fdisplay(fd, "%0d", flags[i] ? 1 : 0);
      end

      $fclose(fd);
    end
  endtask

  // Dump metrics in a JSON-like text block (not strict JSON formatting guarantees,
  // but good enough for logs).
  task automatic dump_metrics(input string filename);
    int fd;
    begin
      fd = $fopen(filename, "w");
      if (fd == 0) $fatal(1, "ref_model_phase1: failed to open '%s' for write", filename);

      $fdisplay(fd, "{");
      $fdisplay(fd, "  \"total_pairs\": %0d,", total_pairs);
      $fdisplay(fd, "  \"suppressed_pairs\": %0d,", suppressed_pairs);
      $fdisplay(fd, "  \"sum_abs_err\": %0d,", sum_abs_err);
      $fdisplay(fd, "  \"sum_sq_err\": %0d", sum_sq_err);
      $fdisplay(fd, "}");

      $fclose(fd);
    end
  endtask

  // Provide a quick summary line for debug.
  task automatic print_summary(input string tag = "ref_model_phase1");
    real sup_ratio;
    begin
      sup_ratio = (total_pairs == 0) ? 0.0 : (1.0 * suppressed_pairs) / (1.0 * total_pairs);
      $display("[%s] N=%0d SHIFT=%0d seed=0x%0h samples=%0d pairs=%0d sup=%0d (ratio=%0.6f) abs_err=%0d sq_err=%0d",
               tag, N, SHIFT, lfsr_state, x_stream.size(), total_pairs,
               suppressed_pairs, sup_ratio, sum_abs_err, sum_sq_err);
    end
  endtask


  // Optional: initialize to defaults (no run) so last_* are defined.

  initial begin
    reset_model(SEED_DEFAULT, /*clear_hist*/ 1'b1);
  end

endmodule : ref_model_phase1

`default_nettype wire

