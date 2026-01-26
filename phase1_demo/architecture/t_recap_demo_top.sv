`timescale 1ns/1ps
`default_nettype none

// Arizona State University 
// Capstone Senior Project
// Sigma Force
// Dat Dinh, Dat Huynh, Paul Applebee, Kyung Jae Son
// t_recap_demo_top.sv  (Phase 1 DE10-Lite Haar Demo - self contained)
//
// Board I/O:
//  - CLOCK_50
//  - KEY[0] : reset (active-low button => rst_n = KEY[0])
//  - KEY[1] : clear metrics (press to clear; edge-detected)
//  - SW[7:0]: THRESH (0..255)
//  - SW[9:8]: MODE/DEBUG
//      00: BYPASS (force THRESH=0), HEX shows sum_abs_err (should be 0)
//      01: MANUAL, HEX shows suppressed_pairs
//      10: MANUAL, HEX shows sum_abs_err
//      11: MANUAL, HEX shows sum_sq_err (LSBs)
//
// Outputs:
//  - LEDR[7:0] : THRESH used
//  - LEDR[8]   : last suppressed flag (latched @ 10Hz)
//  - LEDR[9]   : alive blink (toggles @ 10Hz)
//  - HEX0..HEX5: display 24-bit latched debug word (6 hex digits)
//
// Internal pipeline:
//  sample_en(8k) -> LFSR -> map to signed noise -> noise_shaper -> x[n]
//                -> pair_assembler -> haar_core -> push2/pop1 serializer -> y[n] (internal)
//                                                -> metrics_accum (per pair)
//  dbg_tick(10Hz) latches debug word + LEDs


module t_recap_demo_top #(
  parameter int N            = 12,        // sample width (signed)
  parameter int LFSR_W        = 16,
  parameter int SAMPLE_DIV    = 6250,      // 50MHz / 8kHz
  parameter int DBG_DIV       = 5_000_000, // 50MHz / 10Hz
  parameter int SHAPER_SHIFT  = 3,
  parameter int FIFO_DEPTH    = 4          // must be >= 2
)(
  input  logic        CLOCK_50,
  input  logic [1:0]  KEY,
  input  logic [9:0]  SW,
  output logic [9:0]  LEDR,
  output logic [6:0]  HEX0,
  output logic [6:0]  HEX1,
  output logic [6:0]  HEX2,
  output logic [6:0]  HEX3,
  output logic [6:0]  HEX4,
  output logic [6:0]  HEX5
);


  // Reset + clear handling
  
  logic rst_n;
  assign rst_n = KEY[0]; // active-low reset button, so rst_n = KEY0

  // Edge detect KEY1 press (active-low)
  logic key1_d, key1_dd;
  always_ff @(posedge CLOCK_50 or negedge rst_n) begin
    if (!rst_n) begin
      key1_d  <= 1'b1;
      key1_dd <= 1'b1;
    end else begin
      key1_d  <= KEY[1];
      key1_dd <= key1_d;
    end
  end
  logic clr_metrics_pulse;
  assign clr_metrics_pulse = (key1_dd == 1'b1) && (key1_d == 1'b0); // falling edge


  // Mode + Threshold

  logic [1:0] mode_sel;
  assign mode_sel = SW[9:8];

  logic force_bypass;
  assign force_bypass = (mode_sel == 2'b00);

  logic [7:0] thresh8_manual;
  assign thresh8_manual = SW[7:0];

  logic [N:0] thresh_used; // unsigned magnitude compare width
  always_comb begin
    if (force_bypass) thresh_used = '0;
    else              thresh_used = {{(N+1-8){1'b0}}, thresh8_manual};
  end


  // Tick generators

  logic sample_en;
  tick_pulse_gen #(.DIV(SAMPLE_DIV)) u_sample_tick (
    .clk    (CLOCK_50),
    .rst_n  (rst_n),
    .enable (1'b1),
    .tick   (sample_en)
  );

  logic dbg_tick;
  tick_pulse_gen #(.DIV(DBG_DIV)) u_dbg_tick (
    .clk    (CLOCK_50),
    .rst_n  (rst_n),
    .enable (1'b1),
    .tick   (dbg_tick)
  );


  // Internal source: LFSR -> centered signed noise -> shaper -> x[n]

  logic [LFSR_W-1:0] lfsr_rnd;

  lfsr_noise #(.W(LFSR_W)) u_lfsr (
    .clk       (CLOCK_50),
    .rst_n     (rst_n),
    .en        (sample_en),
    .seed_load (1'b0),
    .seed      (16'hACE1),
    .rnd       (lfsr_rnd)
  );

  // Map LFSR low N bits (unsigned) to signed centered noise in [-2^(N-1), 2^(N-1)-1]
  logic signed [N-1:0] u_noise;
  logic [N-1:0]        u_u;
  assign u_u = lfsr_rnd[N-1:0];

  // u_noise = unsigned(u_u) - 2^(N-1)
  // compute in N+1 bits then truncate (safe for this range)
  logic signed [N:0] u_center_wide;
  assign u_center_wide = $signed({1'b0, u_u}) - $signed(1 <<< (N-1));
  assign u_noise       = u_center_wide[N-1:0];

  logic signed [N-1:0] x_stream;
  noise_shaper #(.N(N), .SHIFT(SHAPER_SHIFT), .STATE_W(N+12)) u_shaper (
    .clk      (CLOCK_50),
    .rst_n    (rst_n),
    .en       (sample_en),
    .in_noise (u_noise),
    .x_out    (x_stream)
  );


  // Pair assembly

  logic pair_valid;
  logic signed [N-1:0] x0, x1;

  pair_assembler #(.N(N)) u_pair (
    .clk        (CLOCK_50),
    .rst_n      (rst_n),
    .en         (sample_en),
    .x_in       (x_stream),
    .pair_valid (pair_valid),
    .x0         (x0),
    .x1         (x1)
  );


  // Haar core (pair domain)

  logic pair_out_valid;
  logic signed [N-1:0] y0, y1;
  logic suppressed;

  // aligned copies for metrics
  logic signed [N-1:0] x0_a, x1_a;

  // optional debug taps
  logic signed [N:0] a_tap, d_tap;
  logic [N:0]        abs_d_tap;

  haar_core #(.N(N)) u_haar (
    .clk           (CLOCK_50),
    .rst_n         (rst_n),
    .pair_valid    (pair_valid),
    .x0            (x0),
    .x1            (x1),
    .thresh        (thresh_used),

    .out_valid     (pair_out_valid),
    .y0            (y0),
    .y1            (y1),
    .suppressed    (suppressed),

    .x0_aligned    (x0_a),
    .x1_aligned    (x1_a),

    .a             (a_tap),
    .d             (d_tap),
    .abs_d         (abs_d_tap)
  );


  // Output serializer (push2/pop1)

  logic y_valid;
  logic signed [N-1:0] y_out;

  out_fifo_serializer #(.N(N), .DEPTH(FIFO_DEPTH)) u_ser (
    .clk         (CLOCK_50),
    .rst_n       (rst_n),
    .sample_en   (sample_en),

    .push2_valid (pair_out_valid),
    .push2_data0 (y0),
    .push2_data1 (y1),

    .y_valid     (y_valid),
    .y_out       (y_out)
  );


  // Metrics (pair domain)

  logic [31:0] total_pairs;
  logic [31:0] suppressed_pairs;
  logic [31:0] sum_abs_err;
  logic [47:0] sum_sq_err;

  metrics_accum #(.N(N)) u_metrics (
    .clk             (CLOCK_50),
    .rst_n           (rst_n),
    .clr_pulse       (clr_metrics_pulse),

    .pair_out_valid  (pair_out_valid),
    .suppressed      (suppressed),

    .x0              (x0_a),
    .x1              (x1_a),
    .y0              (y0),
    .y1              (y1),

    .total_pairs     (total_pairs),
    .suppressed_pairs(suppressed_pairs),
    .sum_abs_err     (sum_abs_err),
    .sum_sq_err      (sum_sq_err)
  );


  // Debug latch @ ~10Hz

  logic alive;
  always_ff @(posedge CLOCK_50 or negedge rst_n) begin
    if (!rst_n) alive <= 1'b0;
    else if (dbg_tick) alive <= ~alive;
  end

  logic suppressed_last;
  always_ff @(posedge CLOCK_50 or negedge rst_n) begin
    if (!rst_n) suppressed_last <= 1'b0;
    else if (pair_out_valid) suppressed_last <= suppressed;
  end

  // Select what to display on HEX (24-bit word => 6 hex digits)
  logic [23:0] dbg_word;
  always_comb begin
    unique case (mode_sel)
      2'b00: dbg_word = sum_abs_err[23:0];          // BYPASS sanity: should remain 0
      2'b01: dbg_word = suppressed_pairs[23:0];     // workload proxy
      2'b10: dbg_word = sum_abs_err[23:0];          // quality proxy
      default: dbg_word = sum_sq_err[23:0];         // quality proxy (LSBs)
    endcase
  end

  logic [23:0] dbg_word_lat;
  logic [9:0]  ledr_lat;

  always_ff @(posedge CLOCK_50 or negedge rst_n) begin
    if (!rst_n) begin
      dbg_word_lat <= '0;
      ledr_lat     <= '0;
    end else if (dbg_tick) begin
      dbg_word_lat <= dbg_word;
      ledr_lat     <= {alive, suppressed_last, thresh_used[7:0]}; // 10 bits
    end
  end

  assign LEDR = ledr_lat;

  // HEX digits (active-low segments)
  logic [3:0] nib0, nib1, nib2, nib3, nib4, nib5;
  assign nib0 = dbg_word_lat[3:0];
  assign nib1 = dbg_word_lat[7:4];
  assign nib2 = dbg_word_lat[11:8];
  assign nib3 = dbg_word_lat[15:12];
  assign nib4 = dbg_word_lat[19:16];
  assign nib5 = dbg_word_lat[23:20];

  hex7seg u_hex0(.hex(nib0), .seg(HEX0));
  hex7seg u_hex1(.hex(nib1), .seg(HEX1));
  hex7seg u_hex2(.hex(nib2), .seg(HEX2));
  hex7seg u_hex3(.hex(nib3), .seg(HEX3));
  hex7seg u_hex4(.hex(nib4), .seg(HEX4));
  hex7seg u_hex5(.hex(nib5), .seg(HEX5));

endmodule



// Tick pulse generator: tick is 1 for one clk when counter hits DIV-1

module tick_pulse_gen #(
  parameter int DIV = 6250
)(
  input  logic clk,
  input  logic rst_n,
  input  logic enable,
  output logic tick
);
  localparam int CW = (DIV <= 1) ? 1 : $clog2(DIV);

  logic [CW-1:0] cnt;

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      cnt  <= '0;
      tick <= 1'b0;
    end else begin
      tick <= 1'b0;
      if (!enable) begin
        cnt <= '0;
      end else begin
        if (cnt == DIV-1) begin
          cnt  <= '0;
          tick <= 1'b1;
        end else begin
          cnt <= cnt + 1'b1;
        end
      end
    end
  end
endmodule



// 16-bit style LFSR (parameter W), shift-right, insert new bit at MSB
// new_bit = rnd[0] ^ rnd[2] ^ rnd[3] ^ rnd[5] (matches C++ example)

module lfsr_noise #(
  parameter int W = 16
)(
  input  logic         clk,
  input  logic         rst_n,
  input  logic         en,
  input  logic         seed_load,
  input  logic [W-1:0] seed,
  output logic [W-1:0] rnd
);
  logic new_bit;

  always_comb begin
    // tap indices assume rnd[0] is LSB
    new_bit = rnd[0] ^ rnd[2] ^ rnd[3] ^ rnd[5];
  end

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      rnd <= seed;
    end else if (seed_load) begin
      rnd <= seed;
    end else if (en) begin
      rnd <= {new_bit, rnd[W-1:1]}; // shift right, insert at MSB
    end
  end
endmodule



// Noise shaper: leaky integrator
// state = state + ((in_noise - state) >>> SHIFT)
// output = saturate(state) to N-bit signed

module noise_shaper #(
  parameter int N = 12,
  parameter int SHIFT = 3,
  parameter int STATE_W = 24
)(
  input  logic                 clk,
  input  logic                 rst_n,
  input  logic                 en,
  input  logic signed [N-1:0]  in_noise,
  output logic signed [N-1:0]  x_out
);

  logic signed [STATE_W-1:0] state;
  logic signed [STATE_W-1:0] in_ext;
  logic signed [STATE_W-1:0] diff;
  logic signed [STATE_W-1:0] delta;
  logic signed [STATE_W-1:0] next_state;

  // Saturation helper
  function automatic logic signed [N-1:0] sat_to_N(input logic signed [STATE_W-1:0] v);
    logic signed [STATE_W-1:0] maxv, minv;
    logic signed [STATE_W-1:0] one;
    begin
      one  = 'sd1;
      maxv = (one <<< (N-1)) - one;      // +2^(N-1)-1
      minv = - (one <<< (N-1));          // -2^(N-1)
      if (v > maxv)      sat_to_N = maxv[N-1:0];
      else if (v < minv) sat_to_N = minv[N-1:0];
      else               sat_to_N = v[N-1:0];
    end
  endfunction

  always_comb begin
    in_ext     = {{(STATE_W-N){in_noise[N-1]}}, in_noise};
    diff       = in_ext - state;
    delta      = diff >>> SHIFT; // arithmetic shift
    next_state = state + delta;
  end

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      state <= '0;
      x_out <= '0;
    end else if (en) begin
      state <= next_state;
      x_out <= sat_to_N(next_state);
    end
  end

endmodule



// Pair assembler: emits (x0,x1) and pair_valid every 2 enabled samples

module pair_assembler #(
  parameter int N = 12
)(
  input  logic                 clk,
  input  logic                 rst_n,
  input  logic                 en,
  input  logic signed [N-1:0]  x_in,
  output logic                 pair_valid,
  output logic signed [N-1:0]  x0,
  output logic signed [N-1:0]  x1
);
  logic phase;

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      phase      <= 1'b0;
      pair_valid <= 1'b0;
      x0         <= '0;
      x1         <= '0;
    end else begin
      pair_valid <= 1'b0;
      if (en) begin
        if (!phase) begin
          x0    <= x_in;
          phase <= 1'b1;
        end else begin
          x1         <= x_in;
          pair_valid <= 1'b1;
          phase      <= 1'b0;
        end
      end
    end
  end
endmodule



// Haar core: forward Haar + hard threshold on detail + inverse Haar
// Contract:
//  a = x0 + x1 (N+1 bits)
//  d = x0 - x1 (N+1 bits)
//  if |d| < thresh => d' = 0 else d' = d
//  y0 = round_div2_ties_away(a + d')
//  y1 = round_div2_ties_away(a - d')
//  saturate y0,y1 to N-bit signed
// Outputs are registered; out_valid is registered copy of pair_valid.

module haar_core #(
  parameter int N = 12
)(
  input  logic                 clk,
  input  logic                 rst_n,
  input  logic                 pair_valid,
  input  logic signed [N-1:0]  x0,
  input  logic signed [N-1:0]  x1,
  input  logic [N:0]           thresh,

  output logic                 out_valid,
  output logic signed [N-1:0]  y0,
  output logic signed [N-1:0]  y1,
  output logic                 suppressed,

  output logic signed [N-1:0]  x0_aligned,
  output logic signed [N-1:0]  x1_aligned,

  output logic signed [N:0]    a,
  output logic signed [N:0]    d,
  output logic [N:0]           abs_d
);

  localparam int WNUM = N+2;

  // module-scope intermediates (NO block declarations)
  logic signed [N:0] x0e, x1e;
  logic signed [N:0] a_c, d_c;
  logic [N:0]        abs_c;
  logic              sup_c;
  logic signed [N:0] d_p;

  logic signed [WNUM-1:0] a_w, d_w;
  logic signed [WNUM-1:0] num0, num1;
  logic signed [WNUM-1:0] y0_w, y1_w;
  logic signed [N-1:0]    y0_sat, y1_sat;

  // rounding helper for WNUM-bit signed
  function automatic logic signed [WNUM-1:0] round_div2_ties_away(input logic signed [WNUM-1:0] num);
    logic signed [WNUM-1:0] adj;
    begin
      if (num[0] == 1'b0) adj = num;                    // even
      else if (num[WNUM-1] == 1'b0) adj = num + 'sd1;   // + odd -> +1
      else adj = num - 'sd1;                            // - odd -> -1
      round_div2_ties_away = adj >>> 1;
    end
  endfunction

  function automatic logic signed [N-1:0] sat_to_N(input logic signed [WNUM-1:0] v);
    logic signed [WNUM-1:0] maxv, minv;
    begin
      maxv = ( 'sd1 <<< (N-1)) - 'sd1;
      minv = -('sd1 <<< (N-1));
      if (v > maxv)      sat_to_N = maxv[N-1:0];
      else if (v < minv) sat_to_N = minv[N-1:0];
      else               sat_to_N = v[N-1:0];
    end
  endfunction

  // combinational math
  always_comb begin
    x0e  = {{1{x0[N-1]}}, x0};
    x1e  = {{1{x1[N-1]}}, x1};

    a_c  = x0e + x1e;
    d_c  = x0e - x1e;

    abs_c = d_c[N] ? (~d_c + 1'b1) : d_c;

    sup_c = (abs_c < thresh);
    d_p   = sup_c ? '0 : d_c;

    a_w   = {{1{a_c[N]}}, a_c};
    d_w   = {{1{d_p[N]}}, d_p};

    num0  = a_w + d_w;
    num1  = a_w - d_w;

    y0_w  = round_div2_ties_away(num0);
    y1_w  = round_div2_ties_away(num1);

    y0_sat = sat_to_N(y0_w);
    y1_sat = sat_to_N(y1_w);
  end

  // registered outputs
  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      out_valid   <= 1'b0;
      y0          <= '0;
      y1          <= '0;
      suppressed  <= 1'b0;
      x0_aligned  <= '0;
      x1_aligned  <= '0;
      a           <= '0;
      d           <= '0;
      abs_d       <= '0;
    end else begin
      out_valid <= pair_valid;

      if (pair_valid) begin
        y0         <= y0_sat;
        y1         <= y1_sat;
        suppressed <= sup_c;

        x0_aligned <= x0;
        x1_aligned <= x1;

        a          <= a_c;
        d          <= d_c;
        abs_d      <= abs_c;
      end
    end
  end

endmodule



// Output FIFO serializer: push2 (y0,y1) per pair, pop1 per sample_en
// DEPTH must be >= 2. Depth 4 is safe.

module out_fifo_serializer #(
  parameter int N = 12,
  parameter int DEPTH = 4
)(
  input  logic                 clk,
  input  logic                 rst_n,
  input  logic                 sample_en,

  input  logic                 push2_valid,
  input  logic signed [N-1:0]  push2_data0,
  input  logic signed [N-1:0]  push2_data1,

  output logic                 y_valid,
  output logic signed [N-1:0]  y_out
);

  localparam int PW = (DEPTH <= 2) ? 1 : $clog2(DEPTH);
  localparam int CW = $clog2(DEPTH+1);

  logic signed [N-1:0] mem [0:DEPTH-1];
  logic [PW-1:0] rd_ptr, wr_ptr;
  logic [CW-1:0] count;

  logic overflow_sticky;

  function automatic logic [PW-1:0] inc_ptr(input logic [PW-1:0] p);
    begin
      if (p == DEPTH-1) inc_ptr = '0;
      else             inc_ptr = p + 1'b1;
    end
  endfunction

  // module-scope control signals
  logic do_pop;
  logic push_ok;
  logic [PW-1:0] w0, w1, w2;

  assign do_pop  = sample_en && (count != 0);
  assign push_ok = push2_valid && (count <= (DEPTH-2));

  always_comb begin
    w0 = wr_ptr;
    w1 = inc_ptr(w0);
    w2 = inc_ptr(w1);
  end

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      rd_ptr          <= '0;
      wr_ptr          <= '0;
      count           <= '0;
      y_valid         <= 1'b0;
      y_out           <= '0;
      overflow_sticky <= 1'b0;
    end else begin
      y_valid <= 1'b0;

      // pop (1 sample) on sample_en if available
      if (do_pop) begin
        y_out   <= mem[rd_ptr];
        y_valid <= 1'b1;
        rd_ptr  <= inc_ptr(rd_ptr);
      end

      // push two samples per pair if space else drop and sticky flag
      if (push_ok) begin
        mem[w0] <= push2_data0;
        mem[w1] <= push2_data1;
        wr_ptr  <= w2;
      end else if (push2_valid) begin
        overflow_sticky <= 1'b1;
      end

      // count update (based on actual push_ok, not just push2_valid)
      unique case ({push_ok, do_pop})
        2'b00: count <= count;
        2'b01: count <= count - 1'b1;
        2'b10: count <= count + 2'd2;
        2'b11: count <= count + 1'b1; // -1 +2
      endcase
    end
  end

endmodule



// Metrics accumulator (pair domain)
//  total_pairs++
//  suppressed_pairs += suppressed
//  sum_abs_err += |e0| + |e1|
//  sum_sq_err  += e0^2 + e1^2
// Clear on clr_pulse.

module metrics_accum #(
  parameter int N = 12
)(
  input  logic                 clk,
  input  logic                 rst_n,
  input  logic                 clr_pulse,

  input  logic                 pair_out_valid,
  input  logic                 suppressed,

  input  logic signed [N-1:0]  x0,
  input  logic signed [N-1:0]  x1,
  input  logic signed [N-1:0]  y0,
  input  logic signed [N-1:0]  y1,

  output logic [31:0]          total_pairs,
  output logic [31:0]          suppressed_pairs,
  output logic [31:0]          sum_abs_err,
  output logic [47:0]          sum_sq_err
);

  function automatic logic [N:0] abs_sN1(input logic signed [N:0] v);
    begin
      abs_sN1 = v[N] ? (~v + 1'b1) : v;
    end
  endfunction

  // module-scope intermediates
  logic signed [N:0] x0e, x1e, y0e, y1e;
  logic signed [N:0] e0, e1;
  logic [N:0]        ae0, ae1;
  logic [2*(N+1)-1:0] sq0, sq1;

  always_comb begin
    x0e = {{1{x0[N-1]}}, x0};
    x1e = {{1{x1[N-1]}}, x1};
    y0e = {{1{y0[N-1]}}, y0};
    y1e = {{1{y1[N-1]}}, y1};

    e0  = x0e - y0e;
    e1  = x1e - y1e;

    ae0 = abs_sN1(e0);
    ae1 = abs_sN1(e1);

    sq0 = ae0 * ae0;
    sq1 = ae1 * ae1;
  end

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      total_pairs      <= '0;
      suppressed_pairs <= '0;
      sum_abs_err      <= '0;
      sum_sq_err       <= '0;
    end else begin
      if (clr_pulse) begin
        total_pairs      <= '0;
        suppressed_pairs <= '0;
        sum_abs_err      <= '0;
        sum_sq_err       <= '0;
      end else if (pair_out_valid) begin
        total_pairs      <= total_pairs + 1;
        suppressed_pairs <= suppressed_pairs + (suppressed ? 1 : 0);
        sum_abs_err      <= sum_abs_err + ae0 + ae1;
        sum_sq_err       <= sum_sq_err + sq0 + sq1;
      end
    end
  end

endmodule



// Hex digit to 7-seg (active-low segments) for DE10-Lite style displays
// seg[6:0] corresponds to {a,b,c,d,e,f,g} active-low.

module hex7seg(
  input  logic [3:0] hex,
  output logic [6:0] seg
);
  always_comb begin
    unique case (hex)
      4'h0: seg = 7'b1000000;
      4'h1: seg = 7'b1111001;
      4'h2: seg = 7'b0100100;
      4'h3: seg = 7'b0110000;
      4'h4: seg = 7'b0011001;
      4'h5: seg = 7'b0010010;
      4'h6: seg = 7'b0000010;
      4'h7: seg = 7'b1111000;
      4'h8: seg = 7'b0000000;
      4'h9: seg = 7'b0010000;
      4'hA: seg = 7'b0001000;
      4'hB: seg = 7'b0000011;
      4'hC: seg = 7'b1000110;
      4'hD: seg = 7'b0100001;
      4'hE: seg = 7'b0000110;
      4'hF: seg = 7'b0001110;
      default: seg = 7'b1111111;
    endcase
  end
endmodule

`default_nettype wire
