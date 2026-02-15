// Arizona State University 
// Capstone Senior Project
// Sigma Force
// Dat Dinh, Dat Huynh, Paul Applebee, Kyung Jae Son
// tb_pkg.sv  
// Common testbench utilities for T-RECAP Phase 1
//
// Goals:
//  - Provide a single, *bit-accurate* place for math helpers that must
//    match the Phase-1 algorithm contract (satN, rnd2 ties-away-from-zero,
//    abs, sign-extend, LFSR helper, etc.).
//  - Provide robust file loaders for golden artifacts: x.memh, y.memh,
//    sup.memh, metrics.json.
//
// Notes:
//  - This package is intended for non-UVM DV as well as a future UVM wrap.
//  - Defaults match the project spec (N=12, SHIFT=3, LFSR_W=16).


`ifndef TB_PKG_SV
`define TB_PKG_SV

package tb_pkg;

  typedef logic [1:0]   u2_t;
  typedef logic [7:0]   u8_t;
  typedef logic [31:0]  u32_t;


  // Compile-time defaults (override via +define+TB_N=... etc.)

  `ifndef TB_N
    `define TB_N 12
  `endif

  `ifndef TB_SHIFT
    `define TB_SHIFT 3
  `endif

  `ifndef TB_LFSR_W
    `define TB_LFSR_W 16
  `endif

  localparam int TB_N_LP      = `TB_N;
  localparam int TB_SHIFT_LP  = `TB_SHIFT;
  localparam int TB_LFSR_W_LP = `TB_LFSR_W;


  // Types

  localparam int N      = TB_N_LP;
  localparam int SHIFT  = TB_SHIFT_LP;
  localparam int LFSR_W = TB_LFSR_W_LP;

  typedef logic signed [N-1:0] samp_t;

  // Use 64-bit math in the TB to avoid overflow surprises.
  typedef longint signed   si64_t;
  typedef longint unsigned ui64_t;


  // Constants for N-bit signed range

  localparam si64_t ONE64   = 64'sd1;
  localparam si64_t MIN_N64 = - (ONE64 <<< (N-1));          // -2^(N-1)
  localparam si64_t MAX_N64 =   (ONE64 <<< (N-1)) - ONE64;  //  2^(N-1)-1


  // Small string helpers (portable, no fancy string methods required)

  function automatic bit _is_ws(input byte c);
    return (c == 8'd9)  || // \t
           (c == 8'd10) || // \n
           (c == 8'd13) || // \r
           (c == 8'd32);   // space
  endfunction

  function automatic string trim(input string s);
    int i0, i1;
    byte c;
    begin
      i0 = 0;
      i1 = s.len() - 1;
      // left trim
      while (i0 <= i1) begin
        c = s.getc(i0);
        if (!_is_ws(c)) break;
        i0++;
      end
      // right trim
      while (i1 >= i0) begin
        c = s.getc(i1);
        if (!_is_ws(c)) break;
        i1--;
      end
      if (i1 < i0) trim = "";
      else         trim = s.substr(i0, i1);
    end
  endfunction

  function automatic bit is_comment_or_empty(input string line);
    string t;
    begin
      t = trim(line);
      if (t.len() == 0) return 1'b1;
      // '#' comment
      if (t.getc(0) == 8'd35) return 1'b1; // '#'
      // '//' comment
      if (t.len() >= 2 && t.substr(0,1) == "//") return 1'b1;
      return 1'b0;
    end
  endfunction


  // Bit-accurate math helpers (match Phase-1 spec)
  

  // Absolute value (64-bit). Safe for the small ranges used here.
  function automatic ui64_t abs64(input si64_t x);
    abs64 = (x < 0) ? ui64_t'(-x) : ui64_t'(x);
  endfunction

  // Saturation to N-bit signed range, returning a 64-bit signed value
  // (still numerically within MIN_N64..MAX_N64).
  function automatic si64_t satN64(input si64_t z);
    if (z < MIN_N64)      satN64 = MIN_N64;
    else if (z > MAX_N64) satN64 = MAX_N64;
    else                  satN64 = z;
  endfunction

  // Saturation to N-bit signed range, returning samp_t.
  function automatic samp_t satN_samp(input si64_t z);
    satN_samp = samp_t'(satN64(z));
  endfunction

  // Arithmetic shift right (ASR) on 64-bit signed
  function automatic si64_t asr64(input si64_t z, input int unsigned k);
    // '>>>' is arithmetic shift in SystemVerilog.
    // Guard large shifts to avoid simulator warnings.
    if (k >= 63) asr64 = (z < 0) ? -ONE64 : 64'sd0;
    else         asr64 = (z >>> k);
  endfunction

  // Divide-by-2 rounding: ties away from zero (spec's rnd2()).
  //
  // For any integer q:
  //   if q even:  q/2
  //   if q odd and q>=0: (q+1)/2
  //   if q odd and q<0:  (q-1)/2
  function automatic si64_t rnd2_ties_away_from_zero(input si64_t q);
    if ((q & ONE64) == 0) begin
      rnd2_ties_away_from_zero = q / 2;
    end else if (q >= 0) begin
      rnd2_ties_away_from_zero = (q + ONE64) / 2;
    end else begin
      rnd2_ties_away_from_zero = (q - ONE64) / 2;
    end
  endfunction

  // Two's complement sign-extend of an unsigned value "u" of "width" bits.
  function automatic si64_t sign_extend_u(input ui64_t u, input int unsigned width);
    si64_t full, signb, v;
    begin
      if (width == 0) begin
        sign_extend_u = 64'sd0;
      end else begin
        if (width >= 64) begin
          // Not expected for this project; best-effort behavior.
          sign_extend_u = si64_t'(u);
        end else begin
          full  = (ONE64 <<< width);
          signb = (ONE64 <<< (width-1));
          v     = si64_t'(u & ui64_t'(full-ONE64));
          if ((v & signb) != 0) v = v - full;
          sign_extend_u = v;
        end
      end
    end
  endfunction

  // Convert a signed integer into its width-bit two's complement representation
  // returned as an unsigned 64-bit (for writing memh).
  function automatic ui64_t to_twos_comp_u(input si64_t s, input int unsigned width);
    si64_t full;
    si64_t v;
    begin
      if (width == 0) begin
        to_twos_comp_u = 0;
      end else if (width >= 64) begin
        to_twos_comp_u = ui64_t'(s);
      end else begin
        full = (ONE64 <<< width);
        v = s;
        // wrap to [0, 2^width)
        while (v < 0)    v = v + full;
        while (v >= full) v = v - full;
        to_twos_comp_u = ui64_t'(v);
      end
    end
  endfunction


  // LFSR helper (matches DUT taps: bits 0,2,3,5; shift-right; insert at MSB)

  function automatic logic [LFSR_W-1:0] lfsr_next(input logic [LFSR_W-1:0] r);
    logic new_bit;
    begin
      new_bit  = r[0] ^ r[2] ^ r[3] ^ r[5];
      lfsr_next = {new_bit, r[LFSR_W-1:1]};
    end
  endfunction

  // Map LFSR low N bits (unsigned) to signed centered noise:
  // u = (r mod 2^N) - 2^(N-1)
  function automatic samp_t map_lfsr_to_centered_noise(input logic [LFSR_W-1:0] r);
    ui64_t u;
    si64_t centered;
    begin
      u = ui64_t'(r[N-1:0]);
      centered = si64_t'(u) - (ONE64 <<< (N-1));
      map_lfsr_to_centered_noise = samp_t'(centered);
    end
  endfunction


  // Golden data loaders


  // Read a memh file containing one hex value per line representing a width-bit
  // two's complement signed integer. Pushes results into a dynamic array.
  task automatic read_memh_signed(
    input  string        filename,
    input  int unsigned   width,
    output si64_t         data[$]
  );
    int fd;
    string line;
    ui64_t u;
    si64_t v;
    int rc;
    begin
      data.delete();

      fd = $fopen(filename, "r");
      if (fd == 0) begin
        $fatal(1, "read_memh_signed: failed to open '%s'", filename);
      end

      while (!$feof(fd)) begin
        rc = $fgets(line, fd);
        if (rc == 0) break;

        if (is_comment_or_empty(line)) continue;

        // parse hex
        u = 0;
        if ($sscanf(line, "%h", u) != 1) begin
          // If the line isn't a hex number, ignore it.
          continue;
        end

        v = sign_extend_u(u, width);
        data.push_back(v);
      end

      $fclose(fd);
    end
  endtask

  // Read a memh file containing one hex value per line and return raw unsigned.
  task automatic read_memh_unsigned(
    input  string        filename,
    output ui64_t         data[$]
  );
    int fd;
    string line;
    ui64_t u;
    int rc;
    begin
      data.delete();

      fd = $fopen(filename, "r");
      if (fd == 0) begin
        $fatal(1, "read_memh_unsigned: failed to open '%s'", filename);
      end

      while (!$feof(fd)) begin
        rc = $fgets(line, fd);
        if (rc == 0) break;
        if (is_comment_or_empty(line)) continue;

        u = 0;
        if ($sscanf(line, "%h", u) != 1) continue;
        data.push_back(u);
      end

      $fclose(fd);
    end
  endtask

  // Read suppression flags (0/1) one per line.
  task automatic read_flags01(
    input  string filename,
    output bit    flags[$]
  );
    int fd;
    string line;
    int rc;
    int tmp;
    begin
      flags.delete();

      fd = $fopen(filename, "r");
      if (fd == 0) begin
        $fatal(1, "read_flags01: failed to open '%s'", filename);
      end

      while (!$feof(fd)) begin
        rc = $fgets(line, fd);
        if (rc == 0) break;
        if (is_comment_or_empty(line)) continue;

        tmp = 0;
        if ($sscanf(line, "%d", tmp) != 1) continue;
        flags.push_back((tmp != 0));
      end

      $fclose(fd);
    end
  endtask

  // Read metrics.json (simple line-based JSON parser for the known format).
  // Expected keys:
  //  - total_pairs
  //  - suppressed_pairs
  //  - sum_abs_err
  //  - sum_sq_err
    // Read metrics.json (simple line-based JSON parser for the known format).
  // Expected keys:
  //  - total_pairs
  //  - suppressed_pairs
  //  - sum_abs_err
  //  - sum_sq_err
  task automatic read_metrics_json(
    input  string filename,
    output ui64_t total_pairs,
    output ui64_t suppressed_pairs,
    output ui64_t sum_abs_err,
    output ui64_t sum_sq_err
  );
    int fd;
    string line;
    int rc;
    ui64_t tmp;
    begin
      total_pairs      = 0;
      suppressed_pairs = 0;
      sum_abs_err      = 0;
      sum_sq_err       = 0;

      fd = $fopen(filename, "r");
      if (fd == 0) begin
        $fatal(1, "read_metrics_json: failed to open '%s'", filename);
      end

      while (!$feof(fd)) begin
        rc = $fgets(line, fd);
        if (rc == 0) break;

        tmp = 0;
        if ($sscanf(line, " \"total_pairs\": %0d", tmp) == 1) begin
          total_pairs = tmp;
          continue;
        end

        tmp = 0;
        if ($sscanf(line, " \"suppressed_pairs\": %0d", tmp) == 1) begin
          suppressed_pairs = tmp;
          continue;
        end

        tmp = 0;
        if ($sscanf(line, " \"sum_abs_err\": %0d", tmp) == 1) begin
          sum_abs_err = tmp;
          continue;
        end

        tmp = 0;
        if ($sscanf(line, " \"sum_sq_err\": %0d", tmp) == 1) begin
          sum_sq_err = tmp;
          continue;
        end
      end

      $fclose(fd);
    end
  endtask


  // Formatting helpers

  function automatic string fmt_si64(input si64_t v);
    fmt_si64 = $sformatf("%0d (0x%0h)", v, ui64_t'(v));
  endfunction

  function automatic string fmt_samp(input samp_t v);
    si64_t sv;
    begin
      sv = si64_t'(v);
      fmt_samp = $sformatf("%0d (0x%0h)", sv, ui64_t'(to_twos_comp_u(sv, N)));
    end
  endfunction

endpackage : tb_pkg

`endif // TB_PKG_SV
