`timescale 1ns/1ps
`default_nettype none

// Arizona State University 
// Capstone Senior Project
// Sigma Force
// Dat Dinh, Dat Huynh, Paul Applebee, Kyung Jae Son
// cov_phase1.sv
//
// Functional coverage for T-RECAP Phase 1 demo.
//
// This file is non-UVM and works by sampling the existing
// tap_if signals (already bound into the DUT by bind_taps.sv).
//
// Coverage goals (practical Phase-1 signoff):
//   - All modes exercised (bypass + the 3 display modes)
//   - Threshold sweep buckets including edge cases (0, 1, 255)
//   - Suppression behavior: suppressed / not suppressed, and boundary |d|==T
//   - Sign of detail d (neg/zero/pos) and representative magnitude buckets
//   - Rounding corner cases: odd numerators for rnd2() for both + and -
//   - Saturation events at y0/y1 rails
//   - Clear-metrics pulse behavior while active
//   - Output serializer occupancy: empty / mid / near-full / overflow-attempt
//
// Enable/disable via plusargs:
//   +COV_DISABLE (or +COV_OFF)      : disable all coverage in this module
//   +COV_VERBOSE                   : print config and occasional messages
//   +COV_MAX_PAIRS=<K>             : stop sampling pair-based covergroups after K pairs
//   +COV_MAX_SAMPLES=<N>           : stop sampling sample-based covergroups after N samples
//   +COV_DEPTH=<D>                 : override serializer FIFO depth for occupancy model
//   +COV_ALLOW_OVERFLOW            : do not count overflow-attempt as an error condition (still covered)
//   +COV_NO_FINAL_REPORT           : suppress final coverage printout
//
// Notes:
//   - Uses a small internal FIFO-occupancy model driven by (sample_en, pair_out_valid).
//   - Samples on posedge clk (coverage only, correctness is handled by SVA/scoreboards).



`ifndef TB_ENABLE_COV

module cov_phase1 #(
  parameter int N      = 12,
  parameter int LFSR_W = 16,
  parameter int DEPTH  = 4
)(
  tap_if t
);

  // Coverage disabled at compile-time (TB_ENABLE_COV not defined).
  // This stub keeps the DV build working without requiring ModelSim coverage compilation.

endmodule

`else

module cov_phase1 #(
  parameter int N      = 12,
  parameter int LFSR_W = 16,
  parameter int DEPTH  = 4
)(
  tap_if t
);

  
  // Imports / local typedefs

  import tb_pkg::*;

  typedef longint signed   si64_t_local;
  typedef longint unsigned ui64_t_local;


  // Plusarg configuration

  bit disabled;
  bit verbose;
  bit no_final_report;

  int unsigned max_pairs;
  int unsigned max_samples;

  int unsigned depth_cfg;
  bit allow_overflow;

  
  // Internal state for sampling limits / occupancy model

  int unsigned sample_cnt;
  int unsigned pair_cnt;

  int unsigned occ;          // modeled FIFO occupancy in *samples* (0..DEPTH)
  int unsigned occ_pre;      // pre-state occupancy used for coverage sampling
  bit          do_pop_pre;
  bit          push_valid_pre;
  bit          push_ok_pre;
  bit          overflow_attempt_pre;

  // Epoch tracking (clr_metrics_pulse rising edge)
  int unsigned epoch;
  bit last_clr;


  // Helpers

  function automatic int unsigned umin(input int unsigned a, input int unsigned b);
    return (a < b) ? a : b;
  endfunction

  function automatic si64_t_local minN64();
    minN64 = -(64'sd1 <<< (N-1));
  endfunction

  function automatic si64_t_local maxN64();
    maxN64 = (64'sd1 <<< (N-1)) - 64'sd1;
  endfunction

  // Compute comparator relation of |d| vs T:
  //   0: lt, 1: eq, 2: gt
  function automatic int rel_absd_T(input ui64_t_local abs_d, input ui64_t_local T);
    if (abs_d < T)      rel_absd_T = 0;
    else if (abs_d==T)  rel_absd_T = 1;
    else                rel_absd_T = 2;
  endfunction


  // Covergroups


  // Mode + threshold selection coverage.
  covergroup cg_mode_thresh with function sample(
    logic [1:0] mode_sel,
    logic [N:0] thresh_used
  );
    option.per_instance = 1;

    cp_mode : coverpoint mode_sel {
      bins bypass = {2'b00};
      bins disp_sup = {2'b01};
      bins disp_abs = {2'b10};
      bins disp_sq  = {2'b11};
    }

    // Threshold (we cover only the low 8 bits, since that's what switches drive).
    cp_thresh8 : coverpoint thresh_used[7:0] {
      bins t0   = {8'd0};
      bins t1   = {8'd1};
      bins t2_3 = {[8'd2:8'd3]};
      bins t4_7 = {[8'd4:8'd7]};
      bins t8_15  = {[8'd8:8'd15]};
      bins t16_31 = {[8'd16:8'd31]};
      bins t32_63 = {[8'd32:8'd63]};
      bins t64_127= {[8'd64:8'd127]};
      bins t128_254 = {[8'd128:8'd254]};
      bins t255 = {8'd255};
    }

    cp_thresh_used_is_zero : coverpoint (thresh_used == '0) {
      bins yes = {1};
      bins no  = {0};
    }

    // Cross: ensure each mode sees a variety of thresholds.
    x_mode_thresh : cross cp_mode, cp_thresh8;

  endgroup

  // Sample domain activity coverage.
  covergroup cg_sample_activity with function sample(
    bit sample_en,
    logic signed [N-1:0] x_stream
  );
    option.per_instance = 1;

    cp_sample_en : coverpoint sample_en {
      bins no = {0};
      bins yes = {1};
    }

    // Basic distribution of x_stream.
    // Useful to ensure we exercise near rails too.
    cp_x : coverpoint x_stream {
      bins min = {si64_t_local'(minN64())};
      bins max = {si64_t_local'(maxN64())};
      bins near_min = {[si64_t_local'(minN64()):si64_t_local'(minN64()+16)]};
      bins near_max = {[si64_t_local'(maxN64()-16):si64_t_local'(maxN64())]};
      bins mid = {[si64_t_local'(-32):si64_t_local'(32)]};
      bins other = default;
    }
  endgroup

  // Pair-domain algorithm corner coverage.
  covergroup cg_pair_algo with function sample(
    bit            suppressed,
    int            rel,           // 0 lt, 1 eq, 2 gt
    logic signed [N:0]  d_tap,
    logic [N:0]         abs_d_tap,
    logic [N:0]         thresh_used,
    logic signed [N:0]  a_tap,
    logic signed [N-1:0] x0_a,
    logic signed [N-1:0] x1_a,
    logic signed [N-1:0] y0,
    logic signed [N-1:0] y1,
    bit            num0_odd,
    bit            num1_odd,
    bit            num0_neg,
    bit            num1_neg
  );
    option.per_instance = 1;

    cp_supp : coverpoint suppressed {
      bins kept = {0};
      bins sup  = {1};
    }

    cp_rel : coverpoint rel {
      bins lt = {0};
      bins eq = {1};
      bins gt = {2};
    }

    // Ensure boundary case is exercised (eq) and that suppression respects strict <.
    x_supp_rel : cross cp_supp, cp_rel {
      // highlight the critical boundary case: |d|==T should map to NOT suppressed (sup==0, rel==eq)
      bins eq_not_supp = binsof(cp_rel.eq) && binsof(cp_supp.kept);
      bins lt_supp     = binsof(cp_rel.lt) && binsof(cp_supp.sup);
    }

    // Sign buckets for d_tap (N+1-bit signed, range [-2^N .. 2^N-1])
    cp_d_sign : coverpoint d_tap {
      bins neg  = {[-(1<<N) : -1]};
      bins zero = {0};
      bins pos  = {[1 : (1<<N)-1]};
    }

    // Magnitude buckets for abs(d). abs_d_tap is unsigned [N:0], max is 2^N.
    cp_abs_d : coverpoint abs_d_tap {
      bins z0      = {0};
      bins z1      = {1};
      bins b_small = {[2:7]};
      bins med     = {[8:31]};
      bins b_large = {[32:127]};
      bins huge    = {[128:(1<<N)]};
    }

    // Rounding: cover odd numerators and their sign (ties-away-from-zero matters)
    cp_num0_odd : coverpoint num0_odd { bins even={0}; bins odd={1}; }
    cp_num1_odd : coverpoint num1_odd { bins even={0}; bins odd={1}; }

    cp_num0_sign : coverpoint num0_neg { bins pos_or_zero={0}; bins neg={1}; }
    cp_num1_sign : coverpoint num1_neg { bins pos_or_zero={0}; bins neg={1}; }

    x_num0_rounding : cross cp_num0_odd, cp_num0_sign;
    x_num1_rounding : cross cp_num1_odd, cp_num1_sign;

    // Saturation events at output rails (N-bit signed)
    cp_y0_sat : coverpoint y0 {
      bins min = {-(1<<<(N-1))};
      bins max = {(1<<<(N-1))-1};
      bins mid = default;
    }
    cp_y1_sat : coverpoint y1 {
      bins min = {-(1<<<(N-1))};
      bins max = {(1<<<(N-1))-1};
      bins mid = default;
    }

  endgroup

  // Clear-metrics / epoch behavior coverage.
  covergroup cg_clear_epoch with function sample(
    bit clr_pulse,
    bit sample_en,
    bit pair_out_valid,
    logic [1:0] mode_sel
  );
    option.per_instance = 1;

    cp_clr : coverpoint clr_pulse { bins no={0}; bins yes={1}; }
    cp_clr_with_sample : coverpoint (clr_pulse && sample_en) { bins no={0}; bins yes={1}; }
    cp_clr_with_pair   : coverpoint (clr_pulse && pair_out_valid) { bins no={0}; bins yes={1}; }

    cp_mode : coverpoint mode_sel {
      bins bypass = {2'b00};
      bins m1 = {2'b01};
      bins m2 = {2'b10};
      bins m3 = {2'b11};
    }

    x_clr_mode : cross cp_clr, cp_mode;
  endgroup

  // Output serializer occupancy coverage (modeled).
  covergroup cg_fifo_occ with function sample(
    int unsigned occ_pre,
    bit do_pop,
    bit push_valid,
    bit push_ok,
    bit overflow_attempt
  );
    option.per_instance = 1;

    cp_occ : coverpoint occ_pre {
      bins empty = {0};
      bins one   = {1};
      bins two   = {2};
      bins three = {3};
      bins near_full = {[DEPTH-1:DEPTH]}; // includes full (if it occurs)
      bins other = default;
    }

    cp_pop : coverpoint do_pop { bins no={0}; bins yes={1}; }
    cp_push: coverpoint push_valid { bins no={0}; bins yes={1}; }
    cp_push_ok : coverpoint push_ok { bins no={0}; bins yes={1}; }

    // Overflow attempt is "pair_out_valid when no space for 2 pushes"
    cp_ovf : coverpoint overflow_attempt { bins no={0}; bins yes={1}; }

    x_occ_pop_push : cross cp_occ, cp_pop, cp_push;
  endgroup


  // Covergroup instances

  cg_mode_thresh      c_mt;
  cg_sample_activity  c_sa;
  cg_pair_algo        c_pa;
  cg_clear_epoch      c_ce;
  cg_fifo_occ         c_fo;


  // Init

  initial begin
    disabled = 1'b0;
    verbose  = 1'b0;
    no_final_report = 1'b0;

    max_pairs   = 0; // 0 = unlimited
    max_samples = 0; // 0 = unlimited

    depth_cfg = DEPTH;
    allow_overflow = 1'b0;

    if ($test$plusargs("COV_DISABLE") || $test$plusargs("COV_OFF")) disabled = 1'b1;
    if ($test$plusargs("COV_VERBOSE")) verbose = 1'b1;
    if ($test$plusargs("COV_NO_FINAL_REPORT")) no_final_report = 1'b1;

    void'($value$plusargs("COV_MAX_PAIRS=%d", max_pairs));
    void'($value$plusargs("COV_MAX_SAMPLES=%d", max_samples));
    void'($value$plusargs("COV_DEPTH=%d", depth_cfg));

    if ($test$plusargs("COV_ALLOW_OVERFLOW")) allow_overflow = 1'b1;

    // Instantiate covergroups
    c_mt = new();
    c_sa = new();
    c_pa = new();
    c_ce = new();
    c_fo = new();

    sample_cnt = 0;
    pair_cnt   = 0;
    occ        = 0;
    epoch      = 0;
    last_clr   = 1'b0;

    if (!disabled && verbose) begin
      $display("[cov_phase1] Enabled. N=%0d LFSR_W=%0d DEPTH=%0d depth_cfg=%0d max_pairs=%0d max_samples=%0d allow_overflow=%0d",
               N, LFSR_W, DEPTH, depth_cfg, max_pairs, max_samples, allow_overflow);
    end
    if (disabled) begin
      $display("[cov_phase1] Disabled via +COV_DISABLE/+COV_OFF.");
    end
  end


  // Sampling + occupancy model

  always @(posedge t.clk) begin
    if (disabled) begin
      // nothing
    end else begin
      // Reset handling
      if (!t.rst_n) begin
        sample_cnt <= 0;
        pair_cnt   <= 0;
        occ        <= 0;
        epoch      <= 0;
        last_clr   <= 1'b0;
      end else begin
        // Epoch tracking on clr_metrics_pulse rising edge
        if (t.clr_metrics_pulse && !last_clr) begin
          epoch <= epoch + 1;
        end
        last_clr <= t.clr_metrics_pulse;


        // Always sample mode/threshold (unless sample limit reached)

        c_mt.sample(t.mode_sel, t.thresh_used);


        // Sample activity coverage on sample_en (if within sample limit)

        if (t.sample_en) begin
          if ((max_samples == 0) || (sample_cnt < max_samples)) begin
            c_sa.sample(1'b1, t.x_stream);
          end
          sample_cnt <= sample_cnt + 1;
        end else begin
          // still sample "no" occasionally? Not needed.
          // c_sa.sample(1'b0, t.x_stream);
        end

        
        // Occupancy model pre-state signals

        occ_pre            = occ;
        do_pop_pre         = (t.sample_en && (occ_pre != 0));
        push_valid_pre     = (t.pair_out_valid === 1'b1);
        push_ok_pre        = push_valid_pre && (occ_pre <= (depth_cfg - 2));
        overflow_attempt_pre = push_valid_pre && !push_ok_pre;

        // Sample FIFO occupancy coverage every cycle (or you can gate on activity)
        c_fo.sample(occ_pre, do_pop_pre, push_valid_pre, push_ok_pre, overflow_attempt_pre);

        // Update occupancy model (pop then push) based on pre-state logic (matches RTL intent)
        if (do_pop_pre && occ != 0) begin
          occ <= occ - 1;
        end

        if (push_ok_pre) begin
          // push two samples
          occ <= (do_pop_pre && occ != 0) ? (occ - 1 + 2) : (occ + 2);
        end

        // Clamp occupancy to [0..depth_cfg] to avoid silly sim artifacts
        if (occ > depth_cfg) begin
          occ <= depth_cfg;
        end


        // Pair-domain coverage (on pair_out_valid) with derived rounding flags

        if (t.pair_out_valid) begin
          if ((max_pairs == 0) || (pair_cnt < max_pairs)) begin
            si64_t_local a, d, dp, num0, num1;
            ui64_t_local absd, T;
            int rel;

            a    = si64_t_local'($signed(t.a_tap));
            d    = si64_t_local'($signed(t.d_tap));
            absd = ui64_t_local'(t.abs_d_tap);
            T    = ui64_t_local'(t.thresh_used);
            rel  = rel_absd_T(absd, T);

            dp   = (t.suppressed ? 64'sd0 : d);
            num0 = a + dp;
            num1 = a - dp;

            c_pa.sample(
              (t.suppressed === 1'b1),
              rel,
              t.d_tap,
              t.abs_d_tap,
              t.thresh_used,
              t.a_tap,
              t.x0_a,
              t.x1_a,
              t.y0,
              t.y1,
              num0[0],   // odd?
              num1[0],   // odd?
              (num0 < 0),
              (num1 < 0)
            );
          end
          pair_cnt <= pair_cnt + 1;
        end


        // Clear coverage (sample every cycle, captures overlaps)

        c_ce.sample(t.clr_metrics_pulse, t.sample_en, t.pair_out_valid, t.mode_sel);

      end
    end
  end


  // Some useful cover properties (temporal / corner conditions)

`ifndef SYNTHESIS
  // 1) Cover that we ever see a suppressed pair.
  cover property (@(posedge t.clk) disable iff (!t.rst_n)
    t.pair_out_valid && t.suppressed
  );

  // 2) Cover that we ever see a non-suppressed pair.
  cover property (@(posedge t.clk) disable iff (!t.rst_n)
    t.pair_out_valid && !t.suppressed
  );

  // 3) Boundary condition: |d| == T AND suppressed must be 0 (strict <).
  cover property (@(posedge t.clk) disable iff (!t.rst_n)
    t.pair_out_valid && (t.abs_d_tap == t.thresh_used) && !t.suppressed
  );

  // 4) Lossless condition exercised: bypass mode implies thresh_used==0 and suppressed never true.
  cover property (@(posedge t.clk) disable iff (!t.rst_n)
    t.pair_out_valid && (t.mode_sel == 2'b00) && (t.thresh_used == '0) && !t.suppressed
  );

  // 5) Clear metrics while activity ongoing (during sample or pair event)
  cover property (@(posedge t.clk) disable iff (!t.rst_n)
    t.clr_metrics_pulse && (t.sample_en || t.pair_out_valid)
  );
`endif


  // Final report

  final begin
    if (!disabled && !no_final_report) begin
      real cov_mt, cov_sa, cov_pa, cov_ce, cov_fo;
      cov_mt = c_mt.get_inst_coverage();
      cov_sa = c_sa.get_inst_coverage();
      cov_pa = c_pa.get_inst_coverage();
      cov_ce = c_ce.get_inst_coverage();
      cov_fo = c_fo.get_inst_coverage();

      $display("\n[cov_phase1] Coverage summary:");
      $display("  cg_mode_thresh     = %0.2f%%", cov_mt);
      $display("  cg_sample_activity = %0.2f%%", cov_sa);
      $display("  cg_pair_algo       = %0.2f%%", cov_pa);
      $display("  cg_clear_epoch     = %0.2f%%", cov_ce);
      $display("  cg_fifo_occ        = %0.2f%%", cov_fo);

      // Overall simulator coverage 
      $display("  $get_coverage()    = %0.2f%%", $get_coverage());

      $display("  sampled: samples=%0d pairs=%0d epochs=%0d", sample_cnt, pair_cnt, epoch);
      $display("  NOTE: This is functional coverage only; correctness is handled by SVA + scoreboards.\n");
    end
  end

endmodule : cov_phase1


`endif

`default_nettype wire
