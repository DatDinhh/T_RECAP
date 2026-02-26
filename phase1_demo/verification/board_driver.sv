`timescale 1ns/1ps
`default_nettype none

// Arizona State University 
// Capstone Senior Project
// Sigma Force
// Dat Dinh, Dat Huynh, Paul Applebee, Kyung Jae Son
// board_driver.sv  
//
// Provides package: board_driver_pkg
// Provides class  : board_driver


`ifndef BOARD_DRIVER_SV
`define BOARD_DRIVER_SV

package board_driver_pkg;

  import tb_pkg::*;

  // Mode encodings (must match DUT + board_if.sv)
  localparam logic [1:0] MODE_BYPASS   = 2'b00;
  localparam logic [1:0] MODE_MAN_SUPP = 2'b01;
  localparam logic [1:0] MODE_MAN_ABS  = 2'b10;
  localparam logic [1:0] MODE_MAN_SQ   = 2'b11;

  class board_driver #(int N = tb_pkg::N,
                       int LFSR_W = tb_pkg::LFSR_W);

    // Virtual interfaces
    virtual board_if             b;
    virtual tap_if #(N, LFSR_W).mon t;

    // Logging/config
    string name;
    bit    verbose;

    // Default timeout in tap clock cycles (0 => infinite)
    int unsigned default_timeout_clks;

    // Constructor
    function new(virtual board_if             b,
                 virtual tap_if #(N, LFSR_W).mon t = null,
                 string                          name = "board_driver");
      this.b = b;
      this.t = t;
      this.name = name;
      this.verbose = 0;
      this.default_timeout_clks = 2_000_000;
    endfunction

    task automatic vprint(input string s);
      if (verbose) $display("[%0t] [%s] %s", $time, name, s);
    endtask

    function automatic int unsigned eff_timeout(input int unsigned override_timeout);
      if (override_timeout != 0) return override_timeout;
      else return default_timeout_clks;
    endfunction


    // Front panel actions

    task automatic init_defaults();
      b.init_defaults();
      vprint("init_defaults()");
    endtask

    task automatic apply_reset(input int unsigned hold_cycles = 5);
      vprint($sformatf("apply_reset(%0d)", hold_cycles));
      b.apply_reset(hold_cycles);
    endtask

    task automatic press_clear_metrics(input int unsigned low_cycles = 1);
      vprint($sformatf("press_clear_metrics(%0d)", low_cycles));
      b.press_clear_metrics(low_cycles);
    endtask

    task automatic set_mode_and_threshold(
      input logic [1:0] mode,
      input logic [7:0] thresh
    );
      @(negedge b.CLOCK_50);
      b.SW[9:8] = mode;
      b.SW[7:0] = thresh;
      vprint($sformatf("set_mode_and_threshold(mode=%0b, thresh=%0d/0x%02h)", mode, thresh, thresh));
    endtask

    // Convenience wrappers
    task automatic set_bypass(input logic [7:0] thresh = 8'd0);
      set_mode_and_threshold(MODE_BYPASS, thresh);
    endtask
    task automatic set_manual_supp(input logic [7:0] thresh);
      set_mode_and_threshold(MODE_MAN_SUPP, thresh);
    endtask
    task automatic set_manual_abs(input logic [7:0] thresh);
      set_mode_and_threshold(MODE_MAN_ABS, thresh);
    endtask
    task automatic set_manual_sq(input logic [7:0] thresh);
      set_mode_and_threshold(MODE_MAN_SQ, thresh);
    endtask


    // Wait primitives (tap-based)

    task automatic wait_clocks(input int unsigned n = 1);
      b.wait_clocks(n);
    endtask

    task automatic wait_sample_tick(input int unsigned timeout_clks = 0);
      int unsigned to;
      int unsigned waited;

      to = eff_timeout(timeout_clks);
      waited = 0;

      if (t == null) begin
        @(posedge b.CLOCK_50);
        return;
      end

      while (1) begin
        @(posedge t.clk);
        if (t.sample_en) break;

        if (to != 0) begin
          waited++;
          if (waited >= to)
            $fatal(1, "[%s] TIMEOUT waiting for sample_en (waited %0d tap clocks)", name, waited);
        end
      end
    endtask

    task automatic wait_pair_out_valid(input int unsigned timeout_clks = 0);
      int unsigned to;
      int unsigned waited;

      to = eff_timeout(timeout_clks);
      waited = 0;

      if (t == null) begin
        wait_sample_tick(timeout_clks);
        wait_sample_tick(timeout_clks);
        @(posedge b.CLOCK_50);
        return;
      end

      while (1) begin
        @(posedge t.clk);
        if (t.pair_out_valid) break;

        if (to != 0) begin
          waited++;
          if (waited >= to)
            $fatal(1, "[%s] TIMEOUT waiting for pair_out_valid (waited %0d tap clocks)", name, waited);
        end
      end
    endtask

    task automatic wait_until_total_pairs(
      input int unsigned target_pairs,
      input int unsigned timeout_clks = 0
    );
      int unsigned to;
      int unsigned waited;

      if (t == null)
        $fatal(1, "[%s] wait_until_total_pairs requires tap_if (t==null).", name);

      to = eff_timeout(timeout_clks);
      waited = 0;

      while (1) begin
        @(posedge t.clk);
        if (t.total_pairs >= target_pairs) break;

        if (to != 0) begin
          waited++;
          if (waited >= to)
            $fatal(1, "[%s] TIMEOUT waiting for total_pairs>=%0d (now=%0d)", name, target_pairs, t.total_pairs);
        end
      end
    endtask

    // Run for K pairs (i.e., wait K occurrences of pair_out_valid).
    // This is typically what you want when validating y0/y1 and metrics.
    task automatic run_pairs(
      input int unsigned kpairs,
      input int unsigned timeout_clks = 0,
      input bit          drain_y_stream = 1'b1
    );
      vprint($sformatf("Running %0d pairs (waiting for pair_out_valid pulses)...", kpairs));

      for (int unsigned k = 0; k < kpairs; k++) begin
        wait_pair_out_valid(timeout_clks);
      end

      // After the last pair, the serializer can have 1 remaining sample buffered.
      // Drain exactly one sample tick so we don't consume the next pair's output.
      if (drain_y_stream) begin
        if (t != null) begin
          wait_sample_tick(timeout_clks);
          @(posedge t.clk);
        end else begin
          @(posedge b.CLOCK_50);
        end
      end
    endtask


  endclass : board_driver

endpackage : board_driver_pkg

`endif // BOARD_DRIVER_SV
`default_nettype wire





