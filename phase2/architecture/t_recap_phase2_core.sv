
`timescale 1ns/1ps
`default_nettype none

// Arizona State University 
// Capstone Senior Project
// Sigma Force
// Dat Dinh, Dat Huynh, Paul Applebee, Kyung Jae Son
// t_recap_phase2_core.sv
//
// Fully functional, synthesizable Phase-2 core for DE1-SoC (Cyclone V).
//
// Implements the Phase-2 algorithm contract:
//
//  - Streaming shell (1 sample per sample_en):
//      xring write, OLA read->satN output, OLA clear, pointer advance,
//      hop counter -> triggers ProcessFrame every H samples.
//
//  - ProcessFrame (runs on clk, must finish within H sample periods):
//      Gather L samples (oldest->newest) + analysis window (sqrt-Hann),
//      Forward FFT normalized by per-stage /2 scaling (rnd2),
//      Compute mag2 on unique bins and apply hard threshold mask (DC protected),
//      Enforce Hermitian symmetry,
//      Inverse FFT (unscaled),
//      Synthesis window + overlap-add into OLA.
//
// Notes:
//  - This implementation is industry grade in structure: STFT + OLA,
//    deterministic deadlines, and explicit overrun detection.
//  - It uses a sequential radix-2 DIT FFT/IFFT engine (1 butterfly/clk).
//    At 50MHz and audio/moderate sample rates, it easily meets real-time.
//  - Window and twiddle ROMs are loaded via $readmemh.
//
// Required memh files (generated alongside this core):
//   - phase2_win256_q15.memh        : L lines, Q1.15 sqrt-Hann window
//   - phase2_twcos256_q15.memh      : L/2 lines, Q1.15 cos(2*pi*k/L)
//   - phase2_twsin256_q15.memh      : L/2 lines, Q1.15 sin(2*pi*k/L)
//
// Interface matches t_recap_phase2_top.sv.
//


module t_recap_phase2_core #(
  parameter int N      = 12,   // signed input/output sample width
  parameter int L      = 256,  // FFT length (power of 2)
  parameter int H      = 128,  // hop size (typically L/2)
  parameter int F      = 15,   // Q1.F fractional bits for window/twiddles
  // Internal datapath width (safe default, tunable after matching golden):
  parameter int W      = N + $clog2(L) + 6,  // complex datapath width
  // OLA accumulator width (wide enough for overlap + internal headroom):
  parameter int ACC_W  = N + $clog2(L) + 8
)(
  input  logic                 clk,
  input  logic                 rst_n,
  input  logic                 enable,

  input  logic                 sample_en,   // one pulse per input/output sample
  input  logic signed [N-1:0]  xin,

  input  logic                 bypass,      // when 1: force "no suppression"
  input  logic [7:0]           thresh_T,    // non-negative integer threshold

  output logic                 y_valid,
  output logic signed [N-1:0]  yout,

  input  logic                 clr_metrics_pulse,

  output logic                 busy,
  output logic                 frame_overrun,

  output logic [31:0]          total_frames,
  output logic [31:0]          suppressed_unique_bins,
  output logic [31:0]          total_unique_bins
);


  // Compile-time sanity checks (simulation-time fatal if violated)

  localparam int P       = $clog2(L);
  localparam int ADDR_W  = P;
  localparam int HALF_L  = (L/2);
  localparam int UNIQUE_BINS = (L/2) + 1;
  localparam int OLA_OFFSET  = H;

  initial begin
    if (L <= 0) $fatal(1, "L must be > 0");
    if ((L & (L-1)) != 0) $fatal(1, "L must be a power of 2");
    if (H <= 0) $fatal(1, "H must be > 0");
    if (H > L)  $fatal(1, "H must be <= L");
    if (F < 1 || F > 30) $fatal(1, "F out of supported range");
    if (ACC_W < W) $fatal(1, "ACC_W must be >= W");
  end


  // Memories / buffers

  // Input ring (N-bit)
  (* ramstyle = "M10K" *) logic signed [N-1:0]   xring [0:L-1];

  // OLA accumulator (ACC_W-bit)
  (* ramstyle = "M10K" *) logic signed [ACC_W-1:0] ola   [0:L-1];

  // Window ROM (Q1.F => F+1 bits)
  (* ramstyle = "M10K" *) logic signed [F:0] win_rom [0:L-1];

  // Twiddle ROM (Q1.F): cos/sin tables for k=0..L/2-1
  (* ramstyle = "M10K" *) logic signed [F:0] tw_cos [0:HALF_L-1];
  (* ramstyle = "M10K" *) logic signed [F:0] tw_sin [0:HALF_L-1];

  // FFT complex buffers (in-place)
  logic signed [W-1:0] fft_re [0:L-1];
  logic signed [W-1:0] fft_im [0:L-1];

  // IFFT complex buffers (in-place)
  logic signed [W-1:0] ifft_re [0:L-1];
  logic signed [W-1:0] ifft_im [0:L-1];

  // Initialize memories for simulation / FPGA init. (No runtime reset fanout.)
  integer ii;
  initial begin
    for (ii = 0; ii < L; ii++) begin
      xring[ii]   = '0;
      ola[ii]     = '0;
      fft_re[ii]  = '0;
      fft_im[ii]  = '0;
      ifft_re[ii] = '0;
      ifft_im[ii] = '0;
      win_rom[ii] = '0;
    end
    for (ii = 0; ii < HALF_L; ii++) begin
      tw_cos[ii] = '0;
      tw_sin[ii] = '0;
    end

    // Window / twiddles (L=256,F=15 default)
    $readmemh("phase2_win256_q15.memh",   win_rom);
    $readmemh("phase2_twcos256_q15.memh", tw_cos);
    $readmemh("phase2_twsin256_q15.memh", tw_sin);
  end


  // Bit-accurate operator helpers (match Phase-2 contract)

  // satN for final output
  function automatic logic signed [N-1:0] satN(input longint signed v);
    longint signed lo, hi, one;
    begin
      one = 1;
      lo  = -(one <<< (N-1));
      hi  =  (one <<< (N-1)) - 1;
      if (v < lo)      satN = lo[N-1:0];
      else if (v > hi) satN = hi[N-1:0];
      else             satN = v[N-1:0];
    end
  endfunction

  // Divide-by-2 with rounding ties away from zero (rnd2)
  function automatic longint signed rnd2(input longint signed q);
    begin
      if ((q & 1) == 0) rnd2 = q >>> 1;
      else if (q >= 0)  rnd2 = (q + 1) >>> 1;
      else              rnd2 = (q - 1) >>> 1;
    end
  endfunction

  // Right shift with rounding ties away from zero (rndshr)
  function automatic longint signed rndshr(input longint signed v, input int s);
    longint signed av, add, q;
    begin
      if (s <= 0) begin
        rndshr = v;
      end else begin
        av  = (v < 0) ? -v : v;
        add = (longint'(1) <<< (s-1));
        q   = (av + add) >>> s;
        rndshr = (v < 0) ? -q : q;
      end
    end
  endfunction

  // Fixed-point multiply (mul_q): b is Q1.F, returns integer-domain result
  function automatic logic signed [W-1:0] mul_q(
    input logic signed [W-1:0] a,
    input logic signed [F:0]   b
  );
    longint signed p, r;
    begin
      p = $signed(a) * $signed(b);   // scaled by 2^F
      r = rndshr(p, F);              // back to integer scale
      mul_q = r[W-1:0];              // truncate/wrap to W
    end
  endfunction

  // Safe negation for Q1.F (avoid -(-1.0) overflow)
  function automatic logic signed [F:0] neg_q1f(input logic signed [F:0] v);
    logic signed [F:0] neg;
    begin
      // Most-negative value represents -1.0 exactly: 1000...0
      if (v == {1'b1, {F{1'b0}}}) neg = {1'b0, {F{1'b1}}}; // clamp to +max (0x7FFF)
      else                       neg = -v;
      neg_q1f = neg;
    end
  endfunction

  // Complex multiply by twiddle (tw_re + j*tw_im), with Q1.F twiddle
  task automatic cmul_q(
    input  logic signed [W-1:0] a_re,
    input  logic signed [W-1:0] a_im,
    input  logic signed [F:0]   tw_re,
    input  logic signed [F:0]   tw_im,
    output logic signed [W-1:0] o_re,
    output logic signed [W-1:0] o_im
  );
    longint signed p1, p2, p3, p4;
    longint signed re_w, im_w;
    longint signed re_i, im_i;
    begin
      p1   = $signed(a_re) * $signed(tw_re);
      p2   = $signed(a_im) * $signed(tw_im);
      p3   = $signed(a_re) * $signed(tw_im);
      p4   = $signed(a_im) * $signed(tw_re);
      re_w = p1 - p2; // still scaled by 2^F
      im_w = p3 + p4; // still scaled by 2^F
      re_i = rndshr(re_w, F);
      im_i = rndshr(im_w, F);
      o_re = re_i[W-1:0];
      o_im = im_i[W-1:0];
    end
  endtask

  // Bit-reverse of ADDR_W-bit index
  function automatic logic [ADDR_W-1:0] bit_reverse(input logic [ADDR_W-1:0] x);
    integer b;
    begin
      bit_reverse = '0;
      for (b = 0; b < ADDR_W; b++) begin
        bit_reverse[b] = x[ADDR_W-1-b];
      end
    end
  endfunction

  // Add small offset modulo L (assumes sum < 2L)
  function automatic logic [ADDR_W-1:0] add_modL_small(
    input logic [ADDR_W-1:0] a,
    input int unsigned       b
  );
    int unsigned tmp;
    begin
      tmp = int'(a) + b;
      if (tmp >= L) tmp = tmp - L;
      add_modL_small = tmp[ADDR_W-1:0];
    end
  endfunction


  // Streaming shell state

  logic [ADDR_W-1:0] wr_ptr, rd_ptr;
  int unsigned       hop_cnt;

  // frame start handshake
  logic              start_pending;
  logic [ADDR_W-1:0] wr_snap;
  logic [ADDR_W-1:0] rd_snap;
  logic [ADDR_W-1:0] ola_base;
  logic [15:0]       T2_snap;

  // output regs
  logic signed [N-1:0] yout_r;

  
  // Frame engine state

  typedef enum logic [2:0] {
    F_IDLE   = 3'd0,
    F_GATHER = 3'd1,
    F_FFT    = 3'd2,
    F_MASK   = 3'd3,
    F_IFFT   = 3'd4,
    F_OLA    = 3'd5,
    F_METRICS= 3'd6
  } frame_state_t;

  frame_state_t fstate;

  int unsigned i_cnt;     // gather/OLA index
  int unsigned stage;     // FFT stage
  int unsigned j_cnt;     // butterfly j within half
  int unsigned grp_base;  // butterfly group base
  int unsigned k_cnt;     // mask unique bin index (0..L/2)

  int unsigned supp_this_frame;


  // Outputs

  assign yout   = yout_r;
  assign y_valid = sample_en; // "one output sample produced" per sample tick
  assign busy    = (fstate != F_IDLE) || start_pending;


  // Main sequential logic

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      // shell pointers
      wr_ptr          <= '0;
      rd_ptr          <= '0;
      hop_cnt         <= 0;

      // output
      yout_r          <= '0;

      // frame handshake/state
      start_pending   <= 1'b0;
      wr_snap         <= '0;
      rd_snap         <= '0;
      ola_base        <= '0;
      T2_snap         <= '0;

      fstate          <= F_IDLE;
      i_cnt           <= 0;
      stage           <= 0;
      j_cnt           <= 0;
      grp_base        <= 0;
      k_cnt           <= 0;
      supp_this_frame <= 0;

      // metrics
      total_frames            <= 32'd0;
      suppressed_unique_bins  <= 32'd0;
      total_unique_bins       <= 32'd0;

      frame_overrun    <= 1'b0;

    end else begin

      // Clear metrics (edge pulse)

      if (clr_metrics_pulse) begin
        total_frames           <= 32'd0;
        suppressed_unique_bins <= 32'd0;
        total_unique_bins      <= 32'd0;
        frame_overrun          <= 1'b0;
      end


      // If disabled: abort frame engine and mute & drain OLA

      if (!enable) begin
        // abort any in-flight frame
        fstate        <= F_IDLE;
        start_pending <= 1'b0;
        hop_cnt       <= 0;

        // Still honor sample ticks so audio stays alive, output 0 and clear OLA slot.
        if (sample_en) begin
          // write zeros into xring to keep deterministic state
          xring[wr_ptr] <= '0;
          wr_ptr <= (wr_ptr == L-1) ? '0 : (wr_ptr + 1'b1);

          // clear OLA at current output slot and output 0
          ola[rd_ptr] <= '0;
          rd_ptr <= (rd_ptr == L-1) ? '0 : (rd_ptr + 1'b1);

          yout_r <= '0;
        end

      end else begin

        // Streaming shell: per sample tick

        if (sample_en) begin
          // xring write
          xring[wr_ptr] <= xin;

          // output from OLA (before clearing)
          yout_r <= satN($signed(ola[rd_ptr]));

          // clear OLA slot after emitting
          ola[rd_ptr] <= '0;

          // advance pointers
          wr_ptr <= (wr_ptr == L-1) ? '0 : (wr_ptr + 1'b1);
          rd_ptr <= (rd_ptr == L-1) ? '0 : (rd_ptr + 1'b1);

          // hop counter + frame trigger
          if (hop_cnt == (H-1)) begin
            hop_cnt <= 0;

            if (!start_pending && (fstate == F_IDLE)) begin
              // Accept frame start: snapshot pointers AFTER this sample write/out advances
              // After update, wr_ptr_next points to oldest sample.
              // After update, rd_ptr_next points to next output slot.
              wr_snap   <= (wr_ptr == L-1) ? '0 : (wr_ptr + 1'b1);
              rd_snap   <= (rd_ptr == L-1) ? '0 : (rd_ptr + 1'b1);

              // base for OLA write: delay by OLA_OFFSET 
              ola_base  <= add_modL_small(((rd_ptr == L-1) ? '0 : (rd_ptr + 1'b1)), OLA_OFFSET);

              // snapshot threshold squared
              if (bypass) T2_snap <= 16'd0;
              else        T2_snap <= (thresh_T * thresh_T);

              start_pending <= 1'b1;
            end else begin
              // Frame engine still busy => deadline miss
              frame_overrun <= 1'b1;
            end
          end else begin
            hop_cnt <= hop_cnt + 1;
          end
        end


        // Frame engine FSM (runs every clk)

        unique case (fstate)


          // IDLE: wait for start_pending

          F_IDLE: begin
            if (start_pending) begin
              start_pending   <= 1'b0;

              // init gather
              i_cnt           <= 0;
              supp_this_frame <= 0;

              // clear FFT buffers (only what we write anyway)
              // (We will overwrite all elements during gather.)
              fstate          <= F_GATHER;
            end
          end


          // GATHER: read L samples oldest->newest, apply window, store in
          // bit-reversed order into FFT buffers (DIT input reorder)

          F_GATHER: begin
            logic [ADDR_W-1:0] xaddr;
            logic [ADDR_W-1:0] br;
            logic signed [W-1:0] xext;
            logic signed [W-1:0] xw;
            xaddr = add_modL_small(wr_snap, i_cnt);
            br    = bit_reverse(i_cnt[ADDR_W-1:0]);

            xext  = {{(W-N){xring[xaddr][N-1]}}, xring[xaddr]};
            xw    = mul_q(xext, win_rom[i_cnt]);

            fft_re[br] <= xw;
            fft_im[br] <= '0;

            if (i_cnt == (L-1)) begin
              // init FFT counters
              stage    <= 0;
              j_cnt    <= 0;
              grp_base <= 0;
              fstate   <= F_FFT;
            end else begin
              i_cnt <= i_cnt + 1;
            end
          end


          // FFT: radix-2 DIT, normalized by per-stage divide-by-2 (rnd2)
          // One butterfly per clk.

          F_FFT: begin
            int unsigned half, m;
            int unsigned tw_shift;
            int unsigned idx1, idx2;
            int unsigned tw_idx;

            logic signed [F:0]   twre, twim;
            logic signed [W-1:0] tre, tim;

            longint signed u_re, u_im, t_re, t_im;
            longint signed sum_re, sum_im, dif_re, dif_im;

            half     = (1u << stage);
            m        = (half << 1);
            tw_shift = (P - stage - 1);
            idx1     = grp_base + j_cnt;
            idx2     = idx1 + half;
            tw_idx   = (j_cnt << tw_shift);

            // twiddle for forward FFT: cos - j sin
            twre = tw_cos[tw_idx];
            twim = neg_q1f(tw_sin[tw_idx]);

            // t = v * twiddle
            cmul_q(fft_re[idx2], fft_im[idx2], twre, twim, tre, tim);

            // u = fft[idx1]
            u_re = $signed(fft_re[idx1]);
            u_im = $signed(fft_im[idx1]);
            t_re = $signed(tre);
            t_im = $signed(tim);

            sum_re = u_re + t_re;
            sum_im = u_im + t_im;
            dif_re = u_re - t_re;
            dif_im = u_im - t_im;

            // stage scaling: /2 with ties-away rounding
            longint signed sum_re_s, sum_im_s, dif_re_s, dif_im_s;
            sum_re_s = rnd2(sum_re);
            sum_im_s = rnd2(sum_im);
            dif_re_s = rnd2(dif_re);
            dif_im_s = rnd2(dif_im);
            fft_re[idx1] <= sum_re_s[W-1:0];
            fft_im[idx1] <= sum_im_s[W-1:0];
            fft_re[idx2] <= dif_re_s[W-1:0];
            fft_im[idx2] <= dif_im_s[W-1:0];

            // advance butterfly counters
            if (j_cnt == (half-1)) begin
              j_cnt <= 0;
              if (grp_base + m >= L) begin
                grp_base <= 0;
                if (stage == (P-1)) begin
                  // FFT complete -> mask stage
                  k_cnt   <= 0;
                  fstate  <= F_MASK;
                end else begin
                  stage <= stage + 1;
                end
              end else begin
                grp_base <= grp_base + m;
              end
            end else begin
              j_cnt <= j_cnt + 1;
            end
          end


          // MASK: compute mag2 on unique bins and write masked spectrum into
          // IFFT buffers in bit-reversed order. Also enforce Hermitian symmetry.
          // Fills all L bins of IFFT input by processing k=0..L/2.

          F_MASK: begin
            logic signed [W-1:0] Xre, Xim;
            logic signed [W-1:0] Yre, Yim;

            longint signed  re_l, im_l;
            longint unsigned mag2;
            longint unsigned T2u;

            logic suppress;

            logic [ADDR_W-1:0] br_k;
            logic [ADDR_W-1:0] br_mk;

            int unsigned mk; // L - k

            Xre = fft_re[k_cnt];
            Xim = fft_im[k_cnt];

            // DC and Nyquist bins should be purely real (best effort)
            if (k_cnt == 0) begin
              Xim = '0;
            end
            if (k_cnt == HALF_L) begin
              Xim = '0;
            end

            re_l = $signed(Xre);
            im_l = $signed(Xim);
            mag2 = longint'(re_l * re_l) + longint'(im_l * im_l);

            T2u = longint'(T2_snap);

            if (k_cnt == 0) begin
              suppress = 1'b0; // DC protect
            end else if (T2_snap == 0) begin
              suppress = 1'b0; // bypass/no-suppress
            end else begin
              suppress = (mag2 < T2u);
            end

            if (suppress) begin
              Yre = '0;
              Yim = '0;
              supp_this_frame <= supp_this_frame + 1;
            end else begin
              Yre = Xre;
              Yim = Xim;
            end

            // write bin k into IFFT input buffer at bit-reversed address
            br_k = bit_reverse(k_cnt[ADDR_W-1:0]);
            ifft_re[br_k] <= Yre;
            ifft_im[br_k] <= Yim;

            // write conjugate pair for k=1..L/2-1
            if ((k_cnt >= 1) && (k_cnt <= (HALF_L-1))) begin
              mk    = L - k_cnt;
              br_mk = bit_reverse(mk[ADDR_W-1:0]);
              ifft_re[br_mk] <= Yre;
              ifft_im[br_mk] <= -Yim;
            end

            if (k_cnt == HALF_L) begin
              // mask complete -> init IFFT counters
              stage    <= 0;
              j_cnt    <= 0;
              grp_base <= 0;
              fstate   <= F_IFFT;
            end else begin
              k_cnt <= k_cnt + 1;
            end
          end

          // IFFT: radix-2 DIT with inverse twiddle (cos + j sin), unscaled.
          // One butterfly per clk.

          F_IFFT: begin
            int unsigned half, m;
            int unsigned tw_shift;
            int unsigned idx1, idx2;
            int unsigned tw_idx;

            logic signed [F:0]   twre, twim;
            logic signed [W-1:0] tre, tim;

            longint signed u_re, u_im, t_re, t_im;
            longint signed sum_re, sum_im, dif_re, dif_im;

            half     = (1u << stage);
            m        = (half << 1);
            tw_shift = (P - stage - 1);
            idx1     = grp_base + j_cnt;
            idx2     = idx1 + half;
            tw_idx   = (j_cnt << tw_shift);

            // twiddle for IFFT: cos + j sin
            twre = tw_cos[tw_idx];
            twim = tw_sin[tw_idx];

            // t = v * twiddle
            cmul_q(ifft_re[idx2], ifft_im[idx2], twre, twim, tre, tim);

            u_re = $signed(ifft_re[idx1]);
            u_im = $signed(ifft_im[idx1]);
            t_re = $signed(tre);
            t_im = $signed(tim);

            sum_re = u_re + t_re;
            sum_im = u_im + t_im;
            dif_re = u_re - t_re;
            dif_im = u_im - t_im;

            // unscaled IFFT: no /2 scaling
            ifft_re[idx1] <= sum_re[W-1:0];
            ifft_im[idx1] <= sum_im[W-1:0];
            ifft_re[idx2] <= dif_re[W-1:0];
            ifft_im[idx2] <= dif_im[W-1:0];

            // advance butterfly counters
            if (j_cnt == (half-1)) begin
              j_cnt <= 0;
              if (grp_base + m >= L) begin
                grp_base <= 0;
                if (stage == (P-1)) begin
                  // IFFT complete -> OLA
                  i_cnt  <= 0;
                  fstate <= F_OLA;
                end else begin
                  stage <= stage + 1;
                end
              end else begin
                grp_base <= grp_base + m;
              end
            end else begin
              j_cnt <= j_cnt + 1;
            end
          end


          // OLA: synthesis window and overlap-add into OLA accumulator
          // ola[(ola_base + i) mod L] += mul_q(Re{yframe[i]}, w[i], F)

          F_OLA: begin
            logic [ADDR_W-1:0] oaddr;
            logic signed [W-1:0] yr;
            logic signed [W-1:0] yw;
            longint signed acc_sum;

            yr = ifft_re[i_cnt];            // take real part
            yw = mul_q(yr, win_rom[i_cnt]); // synthesis window

            oaddr = add_modL_small(ola_base, i_cnt);

            // accumulate (sign-extend yw into ACC_W)
            acc_sum = $signed(ola[oaddr]) + $signed({{(ACC_W-W){yw[W-1]}}, yw});
            ola[oaddr] <= acc_sum[ACC_W-1:0]; // wrap if overflow

            if (i_cnt == (L-1)) begin
              fstate <= F_METRICS;
            end else begin
              i_cnt <= i_cnt + 1;
            end
          end


          // METRICS: update per-frame counters and return to IDLE

          F_METRICS: begin
            total_frames           <= total_frames + 1;
            suppressed_unique_bins <= suppressed_unique_bins + supp_this_frame;
            total_unique_bins      <= total_unique_bins + UNIQUE_BINS;

            // clear for next frame
            supp_this_frame <= 0;

            fstate <= F_IDLE;
          end

          default: begin
            fstate <= F_IDLE;
          end

        endcase
      end
    end
  end

endmodule

`default_nettype wire
