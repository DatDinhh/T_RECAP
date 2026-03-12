`timescale 1ns/1ps
`default_nettype wire

// Arizona State University 
// Capstone Senior Project
// Sigma Force
// Dat Dinh, Dat Huynh, Paul Applebee, Kyung Jae Son
// sva_phase1_bind.sv
//
// Phase-1 SVA (assertions) for t_recap_demo_top.sv.
// This file provides a single bound assertion module that checks:
//
//   - Mode/threshold wiring invariants
//   - Tick pulse shape (sample_en/dbg_tick one-cycle pulses when DIV>1)
//   - LFSR stepping correctness
//   - u_noise mapping correctness
//   - Noise shaper correctness (cycle-by-cycle, gated by sample_en)
//   - Pair assembly correctness (x_stream -> x0/x1 + pair_valid)
//   - Haar core correctness (a/d/abs/suppressed/y0/y1, pipelined)
//   - Serializer correctness (push2/pop1 model, using a queue)
//   - Metrics counters correctness (model + compare, NBA-correct delay)
//   - Debug/IO latching correctness (dbg_word, alive, suppressed_last, LEDR, HEX)
//
// Controls (plusargs):
//   +SVA_DISABLE or +SVA_OFF        : disables all assertions in this file
//   +SVA_VERBOSE                   : enables a few informational prints
//   +SVA_ALLOW_OVERFLOW            : do not fatal if serializer would overflow
//   +SVA_NO_SHAPER_CHECK           : skips noise shaper bit-accurate check
//   +SVA_NO_SERIALIZER_CHECK       : skips serializer (y_valid/y_out) checks
//   +SVA_NO_METRICS_CHECK          : skips metrics counter checks


module sva_phase1_top #(
  parameter int N            = 12,
  parameter int LFSR_W        = 16,
  parameter int SAMPLE_DIV    = 50_000,
  parameter int DBG_DIV       = 50_000_000,
  parameter int SHAPER_SHIFT  = 3,
  parameter int FIFO_DEPTH    = 4
)(
  // Board ports
  input  logic        CLOCK_50,
  input  logic [1:0]  KEY,
  input  logic [9:0]  SW,
  input  logic [9:0]  LEDR,
  input  logic [6:0]  HEX0,
  input  logic [6:0]  HEX1,
  input  logic [6:0]  HEX2,
  input  logic [6:0]  HEX3,
  input  logic [6:0]  HEX4,
  input  logic [6:0]  HEX5,

  // Internal top signals (bound connections)
  input  logic             rst_n,
  input  logic             clr_metrics_pulse,
  input  logic [1:0]       mode_sel,
  input  logic             force_bypass,
  input  logic [7:0]       thresh8_manual,
  input  logic [N:0]       thresh_used,

  input  logic             sample_en,
  input  logic             dbg_tick,

  input  logic [LFSR_W-1:0]      lfsr_rnd,
  input  logic signed [N-1:0]    u_noise,
  input  logic signed [N-1:0]    x_stream,

  input  logic                   pair_valid,
  input  logic signed [N-1:0]    x0,
  input  logic signed [N-1:0]    x1,

  input  logic                   pair_out_valid,
  input  logic signed [N-1:0]    y0,
  input  logic signed [N-1:0]    y1,
  input  logic                   suppressed,
  input  logic signed [N-1:0]    x0_a,
  input  logic signed [N-1:0]    x1_a,
  input  logic signed [N:0]      a_tap,
  input  logic signed [N:0]      d_tap,
  input  logic [N:0]             abs_d_tap,

  input  logic                   y_valid,
  input  logic signed [N-1:0]    y_out,

  input  logic [31:0]            total_pairs,
  input  logic [31:0]            suppressed_pairs,
  input  logic [31:0]            sum_abs_err,
  input  logic [47:0]            sum_sq_err,

  input  logic                   alive,
  input  logic                   suppressed_last,
  input  logic [23:0]            dbg_word,
  input  logic [23:0]            dbg_word_lat,
  input  logic [9:0]             ledr_lat
);


  // Global enable + options

  bit sva_en;
  bit sva_verbose;
  bit allow_overflow;
  bit no_shaper_check;
  bit no_serializer_check;
  bit no_metrics_check;

  initial begin
    sva_en            = !($test$plusargs("SVA_DISABLE") || $test$plusargs("SVA_OFF"));
    sva_verbose       =  $test$plusargs("SVA_VERBOSE");
    allow_overflow    =  $test$plusargs("SVA_ALLOW_OVERFLOW");
    no_shaper_check   =  $test$plusargs("SVA_NO_SHAPER_CHECK");
    no_serializer_check = $test$plusargs("SVA_NO_SERIALIZER_CHECK");
    no_metrics_check  =  $test$plusargs("SVA_NO_METRICS_CHECK");

    if (sva_verbose) begin
      $display("[SVA] sva_phase1_top: sva_en=%0d allow_overflow=%0d no_shaper=%0d no_serializer=%0d no_metrics=%0d",
               sva_en, allow_overflow, no_shaper_check, no_serializer_check, no_metrics_check);
    end
    // Parameter sanity checks (fail fast on impossible configs)
    if (N < 8)          $fatal(1, "[SVA] N must be >= 8 (design assumes LEDR[7:0] threshold display)");
    if (LFSR_W < N)     $fatal(1, "[SVA] LFSR_W (%0d) must be >= N (%0d)", LFSR_W, N);
    if (FIFO_DEPTH < 2) $fatal(1, "[SVA] FIFO_DEPTH (%0d) must be >= 2", FIFO_DEPTH);
  end


  // Helper functions (pure TB math)

  function automatic longint signed satN64(input longint signed v);
    longint signed maxv;
    longint signed minv;
    begin
      maxv = (longint'(1) <<< (N-1)) - 1;
      minv = - (longint'(1) <<< (N-1));
      if (v > maxv)      satN64 = maxv;
      else if (v < minv) satN64 = minv;
      else               satN64 = v;
    end
  endfunction

  function automatic longint unsigned abs64(input longint signed v);
    begin
      abs64 = (v < 0) ? longint'( -v ) : longint'( v );
    end
  endfunction

  // Divide by 2 with rounding: ties away from zero
  function automatic longint signed rnd2_ties_away(input longint signed q);
    begin
      if ((q & 1) == 0) begin
        rnd2_ties_away = (q >>> 1);
      end else if (q >= 0) begin
        rnd2_ties_away = ((q + 1) >>> 1);
      end else begin
        rnd2_ties_away = ((q - 1) >>> 1);
      end
    end
  endfunction

  function automatic logic [6:0] hex7seg_encode(input logic [3:0] hex);
    begin
      unique case (hex)
        4'h0: hex7seg_encode = 7'b1000000;
        4'h1: hex7seg_encode = 7'b1111001;
        4'h2: hex7seg_encode = 7'b0100100;
        4'h3: hex7seg_encode = 7'b0110000;
        4'h4: hex7seg_encode = 7'b0011001;
        4'h5: hex7seg_encode = 7'b0010010;
        4'h6: hex7seg_encode = 7'b0000010;
        4'h7: hex7seg_encode = 7'b1111000;
        4'h8: hex7seg_encode = 7'b0000000;
        4'h9: hex7seg_encode = 7'b0010000;
        4'hA: hex7seg_encode = 7'b0001000;
        4'hB: hex7seg_encode = 7'b0000011;
        4'hC: hex7seg_encode = 7'b1000110;
        4'hD: hex7seg_encode = 7'b0100001;
        4'hE: hex7seg_encode = 7'b0000110;
        4'hF: hex7seg_encode = 7'b0001110;
        default: hex7seg_encode = 7'b1111111;
      endcase
    end
  endfunction

  // Map LFSR bits to centered noise as in spec: u = (lfsr % 2^N) - 2^(N-1)
  function automatic longint signed map_lfsr_to_u(input logic [LFSR_W-1:0] r);
    longint unsigned uu;
    begin
      uu = longint'(r[N-1:0]);
      map_lfsr_to_u = longint'(uu) - (longint'(1) <<< (N-1));
    end
  endfunction

  // LFSR step function (matches lfsr_noise in RTL)
  function automatic logic [LFSR_W-1:0] lfsr_step(input logic [LFSR_W-1:0] r);
    logic nb;
    begin
      nb = r[0] ^ r[2] ^ r[3] ^ r[5];
      lfsr_step = {nb, r[LFSR_W-1:1]};
    end
  endfunction


  // Priming flag: skip checks on the first negedge after reset deassert
  bit primed;
  // Common previous-value registers (negedge sampled, post-NBA stable)

  logic prev_sample_en, prev_dbg_tick;
  logic [LFSR_W-1:0] prev_lfsr_rnd;

  logic prev_pair_valid;
  logic prev_pair_out_valid;
  logic prev_suppressed;
  logic prev_clr;

  logic signed [N-1:0] prev_x_stream;
  logic signed [N-1:0] prev_y0, prev_y1;
  logic signed [N-1:0] prev_x0_a, prev_x1_a;

  logic [23:0] prev_dbg_word;
  logic [23:0] prev_dbg_word_lat;
  logic [9:0]  prev_ledr_lat;
  logic        prev_alive;
  logic        prev_suppressed_last;
  logic [7:0]  prev_thresh8;
  logic [N:0]  prev_thresh_used;


  // SHAPER model state

  longint signed sh_state;


  // PAIR assembly model

  bit have_x0_m;
  logic signed [N-1:0] hold_x0_m;


  // HAAR expected (for next-cycle pair_out_valid)

  bit exp_haar_valid;
  longint signed exp_x0a, exp_x1a;
  longint signed exp_y0, exp_y1;
  bit          exp_sup;
  longint signed exp_a, exp_d;
  longint unsigned exp_abs_d;


  // SERIALIZER model queue

  longint signed yq[$];


  // METRICS expected (mirrors metrics_accum, NBA correct delay)

  longint unsigned met_tp;
  longint unsigned met_sp;
  longint unsigned met_sae;
  longint unsigned met_sse;

  // masks
  localparam longint unsigned MASK32 = 32'hFFFF_FFFF;
  localparam longint unsigned MASK48 = 64'h0000_FFFF_FFFF_FFFF;


  // Main SVA "engine" @ negedge clk
  //  - We sample at negedge to avoid races with DUT posedge FF updates.

  always_ff @(negedge CLOCK_50 or negedge rst_n) begin : sva_negedge
    // locals
    longint signed u_exp;
    longint signed x_exp;

    // haar locals
    longint signed x0_i, x1_i;
    longint signed a_i, d_i, d_p;
    longint unsigned abs_d_i;
    longint signed y0_num, y1_num;
    longint signed y0_r, y1_r;
    bit sup_i;

    // serializer locals
    int unsigned q_len_pre;
    bit do_pop;
    bit push_valid, push_ok;
    longint signed exp_pop;

    // metrics locals
    longint signed e0, e1;
    longint unsigned ae0, ae1;
    longint unsigned sq0, sq1;

    // dbg/hex locals
    logic [23:0] dbg_word_exp;
    logic [3:0]  n0,n1,n2,n3,n4,n5;
    logic [6:0]  hx0,hx1,hx2,hx3,hx4,hx5;

    if (!rst_n) begin
      // reset model state
      primed            <= 1'b0;
      prev_sample_en      <= 1'b0;
      prev_dbg_tick       <= 1'b0;
      prev_lfsr_rnd       <= '0;

      prev_pair_valid     <= 1'b0;
      prev_pair_out_valid <= 1'b0;
      prev_suppressed     <= 1'b0;
      prev_clr            <= 1'b0;

      prev_x_stream       <= '0;
      prev_y0             <= '0;
      prev_y1             <= '0;
      prev_x0_a           <= '0;
      prev_x1_a           <= '0;

      prev_dbg_word       <= '0;
      prev_dbg_word_lat   <= '0;
      prev_ledr_lat       <= '0;
      prev_alive          <= 1'b0;
      prev_suppressed_last<= 1'b0;
      prev_thresh8        <= '0;
      prev_thresh_used    <= '0;

      sh_state            <= 0;

      have_x0_m           <= 1'b0;
      hold_x0_m           <= '0;

      exp_haar_valid      <= 1'b0;
      exp_x0a             <= 0;
      exp_x1a             <= 0;
      exp_y0              <= 0;
      exp_y1              <= 0;
      exp_sup             <= 1'b0;
      exp_a               <= 0;
      exp_d               <= 0;
      exp_abs_d           <= 0;

      yq.delete();

      met_tp              <= 0;
      met_sp              <= 0;
      met_sae             <= 0;
      met_sse             <= 0;

    end else begin
      if (sva_en && primed) begin

        // Basic wiring invariants

        assert (rst_n == KEY[0])
          else $fatal(1, "[SVA] rst_n != KEY[0]");

        assert (mode_sel == SW[9:8])
          else $fatal(1, "[SVA] mode_sel != SW[9:8]");

        assert (thresh8_manual == SW[7:0])
          else $fatal(1, "[SVA] thresh8_manual != SW[7:0]");

        assert (force_bypass == (mode_sel == 2'b00))
          else $fatal(1, "[SVA] force_bypass mismatch with mode_sel");

        // thresh_used must be 0 in bypass, else zero-extended thresh8 into N+1 bits
        begin
          logic [N:0] texp;
          if (force_bypass) texp = '0;
          else              texp = {{(N+1-8){1'b0}}, thresh8_manual};
          assert (thresh_used == texp)
            else $fatal(1, "[SVA] thresh_used mismatch (force_bypass=%0d thresh8=%0d got=%0d exp=%0d)",
                        force_bypass, thresh8_manual, thresh_used, texp);
        end


        // Tick pulse shape checks (when DIV>1, tick should not be high at two consecutive negedges)

        if (SAMPLE_DIV > 1) begin
          assert (!(sample_en && prev_sample_en))
            else $fatal(1, "[SVA] sample_en is wider than 1 cycle (consecutive highs)");
        end
        if (DBG_DIV > 1) begin
          assert (!(dbg_tick && prev_dbg_tick))
            else $fatal(1, "[SVA] dbg_tick is wider than 1 cycle (consecutive highs)");
        end


        // LFSR correctness
        //  - if sample_en, lfsr must step according to taps
        //  - if !sample_en, lfsr must hold

        if (sample_en) begin
          assert (lfsr_rnd == lfsr_step(prev_lfsr_rnd))
            else $fatal(1, "[SVA] LFSR step mismatch: prev=0x%0h got=0x%0h exp=0x%0h",
                        prev_lfsr_rnd, lfsr_rnd, lfsr_step(prev_lfsr_rnd));
        end else begin
          assert (lfsr_rnd == prev_lfsr_rnd)
            else $fatal(1, "[SVA] LFSR changed without sample_en: prev=0x%0h got=0x%0h",
                        prev_lfsr_rnd, lfsr_rnd);
        end


        // u_noise mapping (combinational)

        u_exp = map_lfsr_to_u(lfsr_rnd);
        assert (longint'($signed(u_noise)) == u_exp)
          else $fatal(1, "[SVA] u_noise mapping mismatch: lfsr=0x%0h u_dut=%0d u_exp=%0d",
                      lfsr_rnd, $signed(u_noise), u_exp);


        // Noise shaper check 

        if (!no_shaper_check) begin
          if (sample_en) begin
            longint signed diff, delta, next_state;
            diff       = $signed(u_noise) - sh_state;
            delta      = (diff >>> SHAPER_SHIFT);
            next_state = sh_state + delta;
            x_exp      = satN64(next_state);

            assert (longint'($signed(x_stream)) == x_exp)
              else $fatal(1, "[SVA] shaper mismatch: x_dut=%0d x_exp=%0d (u=%0d state=%0d diff=%0d delta=%0d)",
                          $signed(x_stream), x_exp, $signed(u_noise), sh_state, diff, delta);

            sh_state <= next_state;
          end else begin
            // When sample_en is low, x_stream should hold its previous value
            // (noise_shaper only updates x_out when en).
            assert (x_stream == prev_x_stream)
              else $fatal(1, "[SVA] x_stream changed while sample_en=0");
          end
        end


        // Pair assembler check (based on x_stream samples at sample_en)

        if (sample_en) begin
          if (!have_x0_m) begin
            // first sample of a pair
            assert (pair_valid == 1'b0)
              else $fatal(1, "[SVA] pair_valid asserted on first sample of pair");
            hold_x0_m <= x_stream;
            have_x0_m <= 1'b1;
          end else begin
            // second sample of a pair -> must output pair_valid and correct x0/x1
            assert (pair_valid == 1'b1)
              else $fatal(1, "[SVA] pair_valid NOT asserted on second sample of pair");

            assert ($signed(x0) == $signed(hold_x0_m))
              else $fatal(1, "[SVA] x0 mismatch on pair_valid: got=%0d exp=%0d", $signed(x0), $signed(hold_x0_m));

            assert ($signed(x1) == $signed(x_stream))
              else $fatal(1, "[SVA] x1 mismatch on pair_valid: got=%0d exp=%0d", $signed(x1), $signed(x_stream));

            have_x0_m <= 1'b0;
          end
        end else begin
          // pair_valid should be a 1-cycle pulse aligned to sample_en of second sample
          assert (pair_valid == 1'b0)
            else $fatal(1, "[SVA] pair_valid asserted when sample_en=0");
        end


        // Haar core check (pipelined 1 cycle: pair_valid -> pair_out_valid)
        // We build expected on pair_valid cycle and check outputs on next cycle.

        if (pair_out_valid) begin
          assert (exp_haar_valid)
            else $fatal(1, "[SVA] pair_out_valid asserted but no expected HAAR pending");

          // Compare y0/y1/suppressed and aligned x
          assert (longint'($signed(y0)) == exp_y0)
            else $fatal(1, "[SVA] y0 mismatch: dut=%0d exp=%0d", $signed(y0), exp_y0);

          assert (longint'($signed(y1)) == exp_y1)
            else $fatal(1, "[SVA] y1 mismatch: dut=%0d exp=%0d", $signed(y1), exp_y1);

          assert ((suppressed ? 1'b1 : 1'b0) == exp_sup)
            else $fatal(1, "[SVA] suppressed mismatch: dut=%0d exp=%0d", suppressed, exp_sup);

          assert (longint'($signed(x0_a)) == exp_x0a)
            else $fatal(1, "[SVA] x0_a mismatch: dut=%0d exp=%0d", $signed(x0_a), exp_x0a);

          assert (longint'($signed(x1_a)) == exp_x1a)
            else $fatal(1, "[SVA] x1_a mismatch: dut=%0d exp=%0d", $signed(x1_a), exp_x1a);

          // a/d/abs taps
          assert (longint'($signed(a_tap)) == exp_a)
            else $fatal(1, "[SVA] a_tap mismatch: dut=%0d exp=%0d", $signed(a_tap), exp_a);

          assert (longint'($signed(d_tap)) == exp_d)
            else $fatal(1, "[SVA] d_tap mismatch: dut=%0d exp=%0d", $signed(d_tap), exp_d);

          assert (longint'(abs_d_tap) == exp_abs_d)
            else $fatal(1, "[SVA] abs_d_tap mismatch: dut=%0d exp=%0d", abs_d_tap, exp_abs_d);

          // Self-consistency: abs_d == abs(d)
          assert (abs_d_tap == (d_tap[N] ? (~d_tap + 1'b1) : d_tap))
            else $fatal(1, "[SVA] abs_d_tap != abs(d_tap)");

        end

        // Build expected for next cycle when pair_valid is asserted
        // (pair_valid is the input-ready signal to haar_core)
        exp_haar_valid <= pair_valid;

        if (pair_valid) begin
          x0_i = $signed(x0);
          x1_i = $signed(x1);

          a_i  = x0_i + x1_i;
          d_i  = x0_i - x1_i;

          abs_d_i = abs64(d_i);
          sup_i   = (abs_d_i < longint'(thresh_used));

          d_p   = sup_i ? 0 : d_i;

          y0_num = a_i + d_p;
          y1_num = a_i - d_p;

          y0_r = rnd2_ties_away(y0_num);
          y1_r = rnd2_ties_away(y1_num);

          exp_y0    <= satN64(y0_r);
          exp_y1    <= satN64(y1_r);
          exp_sup   <= sup_i;

          exp_x0a   <= x0_i;
          exp_x1a   <= x1_i;

          exp_a     <= a_i;
          exp_d     <= d_i;
          exp_abs_d <= abs_d_i;

          // Strong sanity: if thresh_used==0, suppression must never happen and y==x
          if (thresh_used == '0) begin
            assert (sup_i == 1'b0)
              else $fatal(1, "[SVA] thresh==0 but suppression predicted");
            assert (satN64(y0_r) == x0_i && satN64(y1_r) == x1_i)
              else $fatal(1, "[SVA] thresh==0 but y!=x predicted (x0=%0d x1=%0d y0=%0d y1=%0d)",
                          x0_i, x1_i, satN64(y0_r), satN64(y1_r));
          end
        end


        // Serializer check (queue model) - optional
        // NOTE: This checks functional ordering + y_valid gating relative to sample_en.

        if (!no_serializer_check) begin
          q_len_pre  = yq.size();
          do_pop     = sample_en && (q_len_pre != 0);
          push_valid = pair_out_valid;
          push_ok    = push_valid && (q_len_pre <= (FIFO_DEPTH - 2));

          // y_valid must exactly equal do_pop in this cycle (DUT clears y_valid each cycle)
          assert ((y_valid ? 1'b1 : 1'b0) == (do_pop ? 1'b1 : 1'b0))
            else $fatal(1, "[SVA] y_valid mismatch: dut=%0d exp=%0d (sample_en=%0d q_len=%0d)",
                        y_valid, do_pop, sample_en, q_len_pre);

          if (do_pop) begin
            exp_pop = yq[0];
            assert ($signed(y_out) == exp_pop)
              else $fatal(1, "[SVA] y_out mismatch: dut=%0d exp=%0d (q_len=%0d)",
                          $signed(y_out), exp_pop, q_len_pre);
          end

          // Overflow expectation
          if (push_valid && !push_ok && !allow_overflow) begin
            $fatal(1, "[SVA] Serializer overflow predicted: q_len=%0d depth=%0d", q_len_pre, FIFO_DEPTH);
          end

          // Apply update (pop then push)
          if (do_pop && (yq.size() != 0)) begin
            void'(yq.pop_front());
          end
          if (push_ok) begin
            yq.push_back($signed(y0));
            yq.push_back($signed(y1));
          end

          // Size safety
          assert (yq.size() <= FIFO_DEPTH)
            else $fatal(1, "[SVA] Serializer model queue exceeded depth: size=%0d depth=%0d",
                        yq.size(), FIFO_DEPTH);
        end


        // Metrics check - NBA-correct delay

        if (!no_metrics_check) begin
          // Apply previous cycle effect (mirrors metrics_accum)
          if (prev_clr) begin
            met_tp  <= 0;
            met_sp  <= 0;
            met_sae <= 0;
            met_sse <= 0;
          end else if (prev_pair_out_valid) begin
            e0  = $signed(prev_x0_a) - $signed(prev_y0);
            e1  = $signed(prev_x1_a) - $signed(prev_y1);
            ae0 = abs64(e0);
            ae1 = abs64(e1);
            sq0 = ae0 * ae0;
            sq1 = ae1 * ae1;

            met_tp  <= (met_tp + 1) & MASK32;
            met_sp  <= (met_sp + (prev_suppressed ? 1 : 0)) & MASK32;
            met_sae <= (met_sae + (ae0 + ae1)) & MASK32;
            met_sse <= (met_sse + (sq0 + sq1)) & MASK48;
          end

          // Compare DUT counters against expected current met_* values
          // We compare using the current met_* (from previous assignments), so do it
          // with temporary expected values computed from prev_* as in combinational form.
          begin
            longint unsigned exp_tp, exp_sp, exp_sae, exp_sse;

            exp_tp  = met_tp;
            exp_sp  = met_sp;
            exp_sae = met_sae;
            exp_sse = met_sse;

            if (prev_clr) begin
              exp_tp  = 0;
              exp_sp  = 0;
              exp_sae = 0;
              exp_sse = 0;
            end else if (prev_pair_out_valid) begin
              e0  = $signed(prev_x0_a) - $signed(prev_y0);
              e1  = $signed(prev_x1_a) - $signed(prev_y1);
              ae0 = abs64(e0);
              ae1 = abs64(e1);
              sq0 = ae0 * ae0;
              sq1 = ae1 * ae1;

              exp_tp  = (exp_tp + 1) & MASK32;
              exp_sp  = (exp_sp + (prev_suppressed ? 1 : 0)) & MASK32;
              exp_sae = (exp_sae + (ae0 + ae1)) & MASK32;
              exp_sse = (exp_sse + (sq0 + sq1)) & MASK48;
            end

            assert (total_pairs == exp_tp[31:0])
              else $fatal(1, "[SVA] total_pairs mismatch: dut=%0d exp=%0d", total_pairs, exp_tp);

            assert (suppressed_pairs == exp_sp[31:0])
              else $fatal(1, "[SVA] suppressed_pairs mismatch: dut=%0d exp=%0d", suppressed_pairs, exp_sp);

            assert (sum_abs_err == exp_sae[31:0])
              else $fatal(1, "[SVA] sum_abs_err mismatch: dut=%0d exp=%0d", sum_abs_err, exp_sae);

            assert (sum_sq_err == exp_sse[47:0])
              else $fatal(1, "[SVA] sum_sq_err mismatch: dut=%0d exp=%0d", sum_sq_err, exp_sse);

            // invariant
            assert (suppressed_pairs <= total_pairs)
              else $fatal(1, "[SVA] invariant violated: suppressed_pairs(%0d) > total_pairs(%0d)",
                          suppressed_pairs, total_pairs);
          end
        end


        // Debug word selection + IO checks

        unique case (mode_sel)
          2'b00: dbg_word_exp = sum_abs_err[23:0];
          2'b01: dbg_word_exp = suppressed_pairs[23:0];
          2'b10: dbg_word_exp = sum_abs_err[23:0];
          default: dbg_word_exp = sum_sq_err[23:0];
        endcase

        assert (dbg_word == dbg_word_exp)
          else $fatal(1, "[SVA] dbg_word mismatch: dut=0x%06h exp=0x%06h (mode=%0b)", dbg_word, dbg_word_exp, mode_sel);

        // LEDR is continuous assign from ledr_lat
        assert (LEDR == ledr_lat)
          else $fatal(1, "[SVA] LEDR != ledr_lat (LEDR=0x%0h ledr_lat=0x%0h)", LEDR, ledr_lat);

        // HEX encoding of dbg_word_lat
        n0 = dbg_word_lat[3:0];
        n1 = dbg_word_lat[7:4];
        n2 = dbg_word_lat[11:8];
        n3 = dbg_word_lat[15:12];
        n4 = dbg_word_lat[19:16];
        n5 = dbg_word_lat[23:20];

        hx0 = hex7seg_encode(n0);
        hx1 = hex7seg_encode(n1);
        hx2 = hex7seg_encode(n2);
        hx3 = hex7seg_encode(n3);
        hx4 = hex7seg_encode(n4);
        hx5 = hex7seg_encode(n5);

        assert (HEX0 == hx0) else $fatal(1, "[SVA] HEX0 mismatch dut=%b exp=%b", HEX0, hx0);
        assert (HEX1 == hx1) else $fatal(1, "[SVA] HEX1 mismatch dut=%b exp=%b", HEX1, hx1);
        assert (HEX2 == hx2) else $fatal(1, "[SVA] HEX2 mismatch dut=%b exp=%b", HEX2, hx2);
        assert (HEX3 == hx3) else $fatal(1, "[SVA] HEX3 mismatch dut=%b exp=%b", HEX3, hx3);
        assert (HEX4 == hx4) else $fatal(1, "[SVA] HEX4 mismatch dut=%b exp=%b", HEX4, hx4);
        assert (HEX5 == hx5) else $fatal(1, "[SVA] HEX5 mismatch dut=%b exp=%b", HEX5, hx5);

        
        // Latched debug behavior checks (1-cycle delayed enable due to NBA)
        // Latch blocks update when dbg_tick was high in the *previous* cycle.

        if (prev_dbg_tick) begin
          // dbg_word_lat and ledr_lat should have captured previous-cycle values
          assert (dbg_word_lat == prev_dbg_word)
            else $fatal(1, "[SVA] dbg_word_lat did not latch prev dbg_word on dbg_tick");

          assert (ledr_lat == {prev_alive, prev_suppressed_last, prev_thresh_used[7:0]})
            else $fatal(1, "[SVA] ledr_lat did not latch expected bits on dbg_tick");
        end else begin
          // Should hold stable if no dbg_tick
          assert (dbg_word_lat == prev_dbg_word_lat)
            else $fatal(1, "[SVA] dbg_word_lat changed without dbg_tick");

          assert (ledr_lat == prev_ledr_lat)
            else $fatal(1, "[SVA] ledr_lat changed without dbg_tick");
        end

        // alive toggles when dbg_tick was high in previous cycle; else stable
        if (prev_dbg_tick) begin
          assert (alive == ~prev_alive)
            else $fatal(1, "[SVA] alive did not toggle on dbg_tick");
        end else begin
          assert (alive == prev_alive)
            else $fatal(1, "[SVA] alive toggled without dbg_tick");
        end

        // suppressed_last updates when pair_out_valid was high in previous cycle; else holds
        if (prev_pair_out_valid) begin
          assert (suppressed_last == prev_suppressed)
            else $fatal(1, "[SVA] suppressed_last did not capture suppressed on pair_out_valid");
        end else begin
          assert (suppressed_last == prev_suppressed_last)
            else $fatal(1, "[SVA] suppressed_last changed without pair_out_valid");
        end

      end // sva_en


      primed            <= 1'b1;
      // Update prev_* registers (always, even if sva disabled)

      prev_sample_en       <= sample_en;
      prev_dbg_tick        <= dbg_tick;
      prev_lfsr_rnd        <= lfsr_rnd;

      prev_pair_valid      <= pair_valid;
      prev_pair_out_valid  <= pair_out_valid;
      prev_suppressed      <= suppressed;
      prev_clr             <= clr_metrics_pulse;
      prev_x_stream       <= x_stream;

      prev_y0              <= y0;
      prev_y1              <= y1;
      prev_x0_a            <= x0_a;
      prev_x1_a            <= x1_a;

      prev_dbg_word        <= dbg_word;
      prev_dbg_word_lat    <= dbg_word_lat;
      prev_ledr_lat        <= ledr_lat;
      prev_alive           <= alive;
      prev_suppressed_last <= suppressed_last;
      prev_thresh8         <= thresh8_manual;
      prev_thresh_used     <= thresh_used;

    end
  end

endmodule : sva_phase1_top



// Bind into every t_recap_demo_top instance.
//
// NOTE: We bind against *internal signals* of the top. This requires
// the signal names to match exactly the ones in t_recap_demo_top.sv.


bind t_recap_demo_top sva_phase1_top #(
  .N           (N),
  .LFSR_W       (LFSR_W),
  .SAMPLE_DIV   (SAMPLE_DIV),
  .DBG_DIV      (DBG_DIV),
  .SHAPER_SHIFT (SHAPER_SHIFT),
  .FIFO_DEPTH   (FIFO_DEPTH)
) u_sva_phase1 (
  // board ports
  .CLOCK_50 (CLOCK_50),
  .KEY      (KEY),
  .SW       (SW),
  .LEDR     (LEDR),
  .HEX0     (HEX0),
  .HEX1     (HEX1),
  .HEX2     (HEX2),
  .HEX3     (HEX3),
  .HEX4     (HEX4),
  .HEX5     (HEX5),

  // internal nets
  .rst_n            (rst_n),
  .clr_metrics_pulse(clr_metrics_pulse),
  .mode_sel         (mode_sel),
  .force_bypass     (force_bypass),
  .thresh8_manual   (thresh8_manual),
  .thresh_used      (thresh_used),

  .sample_en        (sample_en),
  .dbg_tick         (dbg_tick),

  .lfsr_rnd         (lfsr_rnd),
  .u_noise          (u_noise),
  .x_stream         (x_stream),

  .pair_valid       (pair_valid),
  .x0               (x0),
  .x1               (x1),

  .pair_out_valid   (pair_out_valid),
  .y0               (y0),
  .y1               (y1),
  .suppressed       (suppressed),
  .x0_a             (x0_a),
  .x1_a             (x1_a),
  .a_tap            (a_tap),
  .d_tap            (d_tap),
  .abs_d_tap        (abs_d_tap),

  .y_valid          (y_valid),
  .y_out            (y_out),

  .total_pairs      (total_pairs),
  .suppressed_pairs (suppressed_pairs),
  .sum_abs_err      (sum_abs_err),
  .sum_sq_err       (sum_sq_err),

  .alive            (alive),
  .suppressed_last  (suppressed_last),
  .dbg_word         (dbg_word),
  .dbg_word_lat     (dbg_word_lat),
  .ledr_lat         (ledr_lat)
);

`default_nettype wire

