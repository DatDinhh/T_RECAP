`timescale 1ns/1ps
`default_nettype none

// Arizona State University 
// Capstone Senior Project
// Sigma Force
// Dat Dinh, Dat Huynh, Paul Applebee, Kyung Jae Son
// golden_files_loader.sv
//
// Loads golden/reference artifacts produced by golden_model.cpp:
//
//   - x.memh        : expected x stream (N-bit two's complement hex, 1 per line)
//   - y.memh        : expected y stream (N-bit two's complement hex, 1 per line)
//   - sup.memh      : suppression flags (0/1, 1 per pair)
//   - metrics.json  : expected totals (optional, but recommended)
//
// This module is intentionally tool-friendly (pure SystemVerilog, no DPI).
//
// Typical usage in tb_top.sv:
//
//   import tb_pkg::*;
//   golden_files_loader #(.N(N), .AUTO_LOAD(1), .STRICT(1)) g();
//
//   initial begin
//     g.wait_loaded();
//     $display("Loaded %0d samples, %0d pairs", g.num_samples(), g.num_pairs());
//   end
//
// Plusargs supported (override default filenames):
//   +X_MEMH=<path> +Y_MEMH=<path> +SUP_MEMH=<path> +METRICS_JSON=<path>
//
// Parameters:
//   N                  : sample bit width used by golden model
//   AUTO_LOAD          : if 1, automatically loads at time 0 from plusargs/defaults
//   STRICT             : if 1, mismatches/format errors => $fatal; else => warnings
//   REQUIRE_METRICS    : if 1, missing metrics.json => $fatal
//
// Notes:
//  - The loader also computes metrics from x/y/sup and cross-checks against
//    metrics.json when present.
//  - This is *not* a scoreboard; it's a data source + sanity checker.


module golden_files_loader #(
  parameter int  N               = 12,
  parameter bit  AUTO_LOAD       = 1'b1,
  parameter bit  STRICT          = 1'b1,
  parameter bit  REQUIRE_METRICS = 1'b1
);

  import tb_pkg::*;


  // Publicly readable storage

  si64_t x_exp[$];       // signed values of x[n]
  si64_t y_exp[$];       // signed values of y[n]
  bit    sup_exp[$];     // suppression flag per pair k

  // Expected metrics from metrics.json (if loaded)
  ui64_t json_total_pairs;
  ui64_t json_suppressed_pairs;
  ui64_t json_sum_abs_err;
  ui64_t json_sum_sq_err;
  bit    json_valid;

  // Computed metrics from x/y/sup (always computed if x/y exist)
  ui64_t comp_total_pairs;
  ui64_t comp_suppressed_pairs;
  ui64_t comp_sum_abs_err;
  ui64_t comp_sum_sq_err;

  // Filenames actually used
  string x_file;
  string y_file;
  string sup_file;
  string metrics_file;

  // Load-complete flag
  bit loaded;


  // Convenience getters

  function automatic int unsigned num_samples();
    return x_exp.size();
  endfunction

  function automatic int unsigned num_samples_y();
    return y_exp.size();
  endfunction

  function automatic int unsigned num_pairs();
    return int'(comp_total_pairs);
  endfunction

  function automatic bit is_loaded();
    return loaded;
  endfunction

  function automatic bit has_metrics_json();
    return json_valid;
  endfunction

  // Wait until files are loaded (useful for tests that start at time 0)
  task automatic wait_loaded();
    wait (loaded == 1'b1);
  endtask


  // Core load entrypoints


  // Load file paths from plusargs (or defaults) and call load().
  task automatic load_from_plusargs();
    string xf, yf, sf, mf;
    begin
      xf = "x.memh";
      yf = "y.memh";
      sf = "sup.memh";
      mf = "metrics.json";

      void'($value$plusargs("X_MEMH=%s", xf));
      void'($value$plusargs("Y_MEMH=%s", yf));
      void'($value$plusargs("SUP_MEMH=%s", sf));
      void'($value$plusargs("METRICS_JSON=%s", mf));

      load(xf, yf, sf, mf);
    end
  endtask

  // Main loader.
  task automatic load(
    input string xf = "x.memh",
    input string yf = "y.memh",
    input string sf = "sup.memh",
    input string mf = "metrics.json"
  );
    begin
      loaded = 1'b0;

      x_file       = xf;
      y_file       = yf;
      sup_file     = sf;
      metrics_file = mf;

      // 1) load memh streams
      read_memh_signed(x_file, N, x_exp);
      read_memh_signed(y_file, N, y_exp);

      // 2) load suppression flags (per pair)
      read_flags01(sup_file, sup_exp);

      // 3) metrics.json is optional unless REQUIRE_METRICS=1
      json_valid = 1'b0;
      if (_file_exists(metrics_file)) begin
        read_metrics_json(metrics_file,
                          json_total_pairs,
                          json_suppressed_pairs,
                          json_sum_abs_err,
                          json_sum_sq_err);
        json_valid = 1'b1;
      end else begin
        json_total_pairs      = 0;
        json_suppressed_pairs = 0;
        json_sum_abs_err      = 0;
        json_sum_sq_err       = 0;
        if (REQUIRE_METRICS) begin
          $fatal(1, "golden_files_loader: metrics.json missing: '%s'", metrics_file);
        end else begin
          $display("[golden_files_loader] NOTE: metrics.json not found (%s). Skipping metrics-json checks.",
                   metrics_file);
        end
      end

      // 4) compute metrics from loaded x/y/sup and cross-check
      compute_metrics_from_loaded();
      self_check_sanity();

      loaded = 1'b1;

      $display("[golden_files_loader] Loaded:");
      $display("  x: %0d samples from '%s'", x_exp.size(), x_file);
      $display("  y: %0d samples from '%s'", y_exp.size(), y_file);
      $display("  sup: %0d pairs from '%s'", sup_exp.size(), sup_file);
      if (json_valid) begin
        $display("  metrics.json: total_pairs=%0d suppressed_pairs=%0d sum_abs_err=%0d sum_sq_err=%0d",
                 json_total_pairs, json_suppressed_pairs, json_sum_abs_err, json_sum_sq_err);
      end
    end
  endtask

  
  // Implementation details
  

  function automatic bit _file_exists(input string path);
    int fd;
    begin
      fd = $fopen(path, "r");
      if (fd == 0) begin
        _file_exists = 1'b0;
      end else begin
        _file_exists = 1'b1;
        $fclose(fd);
      end
    end
  endfunction

  task automatic _die_or_warn(input string msg);
    if (STRICT) $fatal(1, "%s", msg);
    else        $display("[golden_files_loader] WARNING: %s", msg);
  endtask

  // Compute metrics from x_exp/y_exp/sup_exp.
  task automatic compute_metrics_from_loaded();
    ui64_t K;
    ui64_t k;
    si64_t e0, e1;
    ui64_t abs0, abs1;
    si64_t sq0, sq1;
    int unsigned Lmin;
    begin
      comp_total_pairs      = 0;
      comp_suppressed_pairs = 0;
      comp_sum_abs_err      = 0;
      comp_sum_sq_err       = 0;

      // Determine number of pairs based on min(x_len, y_len).
      K = 0;
      if (x_exp.size() > 0 && y_exp.size() > 0) begin
        Lmin = (x_exp.size() < y_exp.size()) ? x_exp.size() : y_exp.size();
        K    = ui64_t'(Lmin / 2); // floor
      end
      comp_total_pairs = K;

      // Suppressed pairs: count sup_exp, but only up to K pairs.
      for (k = 0; k < K; k++) begin
        if (k < sup_exp.size()) begin
          comp_suppressed_pairs += (sup_exp[int'(k)] ? 1 : 0);
        end
      end

      // Error metrics from x/y
      for (k = 0; k < K; k++) begin
        e0 = x_exp[int'(2*k+0)] - y_exp[int'(2*k+0)];
        e1 = x_exp[int'(2*k+1)] - y_exp[int'(2*k+1)];

        abs0 = abs64(e0);
        abs1 = abs64(e1);

        comp_sum_abs_err += abs0 + abs1;

        sq0 = e0 * e0;
        sq1 = e1 * e1;
        comp_sum_sq_err += ui64_t'(sq0 + sq1);
      end
    end
  endtask

  // Sanity checks on loaded file consistency.
  task automatic self_check_sanity();
    int unsigned Lx, Ly;
    ui64_t exp_pairs_from_stream;
    ui64_t exp_pairs_from_sup;
    ui64_t mism;
    ui64_t k;
    ui64_t sup_count;
    begin
      Lx = x_exp.size();
      Ly = y_exp.size();

      if (Lx == 0) _die_or_warn($sformatf("golden_files_loader: x stream length is 0 (file='%s')", x_file));
      if (Ly == 0) _die_or_warn($sformatf("golden_files_loader: y stream length is 0 (file='%s')", y_file));

      if (Lx != Ly) begin
        _die_or_warn($sformatf("golden_files_loader: x/y length mismatch: x=%0d y=%0d", Lx, Ly));
      end

      if ((Lx % 2) != 0) begin
        _die_or_warn($sformatf("golden_files_loader: x length is odd (%0d). Expected even (pairs).", Lx));
      end

      exp_pairs_from_stream = ui64_t'(Lx / 2);
      exp_pairs_from_sup    = ui64_t'(sup_exp.size());

      if (exp_pairs_from_sup != exp_pairs_from_stream) begin
        _die_or_warn($sformatf("golden_files_loader: sup pairs (%0d) != stream pairs (%0d)",
                               exp_pairs_from_sup, exp_pairs_from_stream));
      end

      // If metrics.json present, cross-check computed vs json.
      if (json_valid) begin
        mism = 0;

        if (json_total_pairs != comp_total_pairs) begin
          mism++;
          $display("[golden_files_loader] MISMATCH: total_pairs json=%0d computed=%0d",
                   json_total_pairs, comp_total_pairs);
        end
        if (json_suppressed_pairs != comp_suppressed_pairs) begin
          mism++;
          $display("[golden_files_loader] MISMATCH: suppressed_pairs json=%0d computed=%0d",
                   json_suppressed_pairs, comp_suppressed_pairs);
        end
        if (json_sum_abs_err != comp_sum_abs_err) begin
          mism++;
          $display("[golden_files_loader] MISMATCH: sum_abs_err json=%0d computed=%0d",
                   json_sum_abs_err, comp_sum_abs_err);
        end
        if (json_sum_sq_err != comp_sum_sq_err) begin
          mism++;
          $display("[golden_files_loader] MISMATCH: sum_sq_err json=%0d computed=%0d",
                   json_sum_sq_err, comp_sum_sq_err);
        end

        if (mism != 0) begin
          _die_or_warn($sformatf("golden_files_loader: metrics.json mismatch count=%0d", mism));
        end

        // Also cross-check that sum(sup_exp) equals metrics.json suppressed_pairs
        sup_count = 0;
        for (k = 0; k < sup_exp.size(); k++) begin
          sup_count += (sup_exp[int'(k)] ? 1 : 0);
        end
        if (sup_count != json_suppressed_pairs) begin
          _die_or_warn($sformatf("golden_files_loader: sup flag count (%0d) != metrics.json suppressed_pairs (%0d)",
                                 sup_count, json_suppressed_pairs));
        end
      end
    end
  endtask

  // Auto-load at time 0 if enabled
  initial begin
    loaded     = 1'b0;
    json_valid = 1'b0;

    if (AUTO_LOAD) begin
      // Allow tests to opt out: +NO_GOLDEN_LOAD
      if ($test$plusargs("NO_GOLDEN_LOAD")) begin
        $display("[golden_files_loader] NOTE: +NO_GOLDEN_LOAD set. Skipping AUTO_LOAD.");
      end else begin
        load_from_plusargs();
      end
    end
  end

endmodule : golden_files_loader

`default_nettype wire
