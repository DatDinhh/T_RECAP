// SPDX-License-Identifier: MIT
// File class: [1] hand-written RTL package.
// Layer: rtl/include/
// Purpose: Shared fixed-point arithmetic helper functions for the T-RECAP Phase 2 RTL.
// Contract: Implements the Revision J fixed-point operator contract from the active spec.

`default_nettype none

package trecap_math_pkg;

  import trecap_core_pkg::*;
  // Wide helper width used only inside package-level arithmetic functions. This is not
  // a replacement for the generated width schedule; leaf RTL still stores values using
  // widths from trecap_core_pkg.sv.
  localparam int unsigned TMATH_WIDE_W = 128;

  typedef logic signed [TMATH_WIDE_W-1:0] trecap_math_swide_t;
  typedef logic        [TMATH_WIDE_W-1:0] trecap_math_uwide_t;

  typedef struct packed {
    trecap_math_swide_t re;
    trecap_math_swide_t im;
  } trecap_math_complex_swide_t;

  // Return sign(v) using the spec convention: -1, 0, +1.
  function automatic int signed trecap_sgn(input trecap_math_swide_t value);
    if (value < '0) begin
      return -1;
    end
    if (value > '0) begin
      return 1;
    end
    return 0;
  endfunction : trecap_sgn

  // Unsigned magnitude of a signed wide value. The most-negative input maps to its
  // mathematical magnitude in unsigned two's-complement form.
  function automatic trecap_math_uwide_t trecap_abs_mag(input trecap_math_swide_t value);
    if (value < '0) begin
      return trecap_math_uwide_t'(-value);
    end
    return trecap_math_uwide_t'(value);
  endfunction : trecap_abs_mag

  // Sign-preserving arithmetic right shift. For normal RTL use the native >>> operator;
  // this function centralizes the boundary behavior for package-level helpers.
  function automatic trecap_math_swide_t trecap_asr(
      input trecap_math_swide_t value,
      input int unsigned shift
  );
    if (shift == 0) begin
      return value;
    end
    if (shift >= TMATH_WIDE_W) begin
      return (value < '0) ? {TMATH_WIDE_W{1'b1}} : '0;
    end
    return value >>> shift;
  endfunction : trecap_asr

  // Round-to-nearest with ties away from zero after a right shift. This implements
  // rnd_shr(v, s). The zero-shift case returns the input exactly.
  function automatic trecap_math_swide_t trecap_rnd_shr(
      input trecap_math_swide_t value,
      input int unsigned shift
  );
    trecap_math_uwide_t mag;
    trecap_math_uwide_t rounded_mag;
    trecap_math_uwide_t bias;

    if (shift == 0) begin
      return value;
    end

    if (shift >= TMATH_WIDE_W) begin
      return '0;
    end

    mag = trecap_abs_mag(value);
    bias = trecap_math_uwide_t'(1) << (shift - 1);
    rounded_mag = (mag + bias) >> shift;

    if (value < '0) begin
      return -(trecap_math_swide_t'(rounded_mag));
    end
    return trecap_math_swide_t'(rounded_mag);
  endfunction : trecap_rnd_shr

  function automatic trecap_math_swide_t trecap_rnd2(input trecap_math_swide_t value);
    return trecap_rnd_shr(value, 1);
  endfunction : trecap_rnd2

  // Saturate a signed wide value to an arbitrary signed two's-complement width. The
  // return type remains wide so the caller can cast or slice explicitly.
  function automatic trecap_math_swide_t trecap_sat_signed(
      input trecap_math_swide_t value,
      input int unsigned width
  );
    trecap_math_swide_t one;
    trecap_math_swide_t min_value;
    trecap_math_swide_t max_value;

    if (width == 0) begin
      return '0;
    end
    if (width >= TMATH_WIDE_W) begin
      return value;
    end

    one = trecap_math_swide_t'(1);
    min_value = -(one <<< (width - 1));
    max_value =  (one <<< (width - 1)) - one;

    if (value < min_value) begin
      return min_value;
    end
    if (value > max_value) begin
      return max_value;
    end
    return value;
  endfunction : trecap_sat_signed

  // Saturate to the generated external sample width N.
  function automatic logic signed [T_SAMPLE_W-1:0] trecap_sat_sample(
      input trecap_math_swide_t value
  );
    trecap_math_swide_t clipped;
    clipped = trecap_sat_signed(value, T_SAMPLE_W);
    return clipped[T_SAMPLE_W-1:0];
  endfunction : trecap_sat_sample

  // Saturate to int16_t for live display payloads. This is a display helper, not a
  // replacement for the core sample contract.
  function automatic logic signed [15:0] trecap_sat_i16(input trecap_math_swide_t value);
    trecap_math_swide_t clipped;
    clipped = trecap_sat_signed(value, 16);
    return clipped[15:0];
  endfunction : trecap_sat_i16

  // Clip an unsigned wide value to an arbitrary unsigned width. The return type remains
  // wide so the caller can cast or slice explicitly.
  function automatic trecap_math_uwide_t trecap_clip_unsigned(
      input trecap_math_uwide_t value,
      input int unsigned width
  );
    trecap_math_uwide_t max_value;

    if (width == 0) begin
      return '0;
    end
    if (width >= TMATH_WIDE_W) begin
      return value;
    end

    max_value = (trecap_math_uwide_t'(1) << width) - trecap_math_uwide_t'(1);
    if (value > max_value) begin
      return max_value;
    end
    return value;
  endfunction : trecap_clip_unsigned

  // Revision G spectrum display compression: clip16(z >> spec_shift).
  function automatic logic [15:0] trecap_clip16_after_shift(
      input trecap_math_uwide_t value,
      input int unsigned shift
  );
    trecap_math_uwide_t shifted;

    if (shift >= TMATH_WIDE_W) begin
      shifted = '0;
    end else begin
      shifted = value >> shift;
    end

    if (|shifted[TMATH_WIDE_W-1:16]) begin
      return 16'hffff;
    end
    return shifted[15:0];
  endfunction : trecap_clip16_after_shift

  // Align byte counts to a power-of-two boundary. If align_bytes is zero or not a
  // power of two, return the input unchanged so validation logic can reject the config.
  function automatic longint unsigned trecap_align_up_pow2(
      input longint unsigned value,
      input longint unsigned align_bytes
  );
    if ((align_bytes == 0) || ((align_bytes & (align_bytes - 1)) != 0)) begin
      return value;
    end
    return (value + align_bytes - 1) & ~(align_bytes - 1);
  endfunction : trecap_align_up_pow2

  function automatic longint unsigned trecap_align64(input longint unsigned value);
    return trecap_align_up_pow2(value, 64);
  endfunction : trecap_align64

  function automatic bit trecap_is_power_of_two(input longint unsigned value);
    return (value != 0) && ((value & (value - 1)) == 0);
  endfunction : trecap_is_power_of_two

  // Exact core configuration sanity check exposed for simulation/build assertions.
  function automatic bit trecap_core_geometry_ok();
    return (T_DELAY_D == (T_FFT_L + T_CUSHION_G)) &&
           (T_HOP_H * 2 == T_FFT_L) &&
           (T_UNIQUE_BINS == ((T_FFT_L / 2) + 1)) &&
           (T_MAG2_W == (2 * T_CAN_W));
  endfunction : trecap_core_geometry_ok


  // Rescale a full-precision product to a requested fractional width. The Revision J
  // product path normally has fa + fb >= fout; the left-shift branch exists only so
  // wrapper code does not silently truncate if a future adapter uses fewer fractional bits.
  function automatic trecap_math_swide_t trecap_mul_to_frac(
      input trecap_math_swide_t a,
      input int unsigned fa,
      input trecap_math_swide_t b,
      input int unsigned fb,
      input int unsigned fout
  );
    trecap_math_swide_t prod;
    int unsigned fin;

    prod = a * b;
    fin = fa + fb;

    if (fin >= fout) begin
      return trecap_rnd_shr(prod, fin - fout);
    end
    if ((fout - fin) >= TMATH_WIDE_W) begin
      return '0;
    end
    return prod <<< (fout - fin);
  endfunction : trecap_mul_to_frac

  // Complex multiply with all operands interpreted as F-fractional fixed-point values.
  // Product sums are formed before the single final rounded shift, matching the spec rule.
  function automatic trecap_math_complex_swide_t trecap_cmul_f(
      input trecap_math_swide_t ar,
      input trecap_math_swide_t ai,
      input trecap_math_swide_t br,
      input trecap_math_swide_t bi
  );
    trecap_math_complex_swide_t out;
    trecap_math_swide_t pre_re;
    trecap_math_swide_t pre_im;

    pre_re = (ar * br) - (ai * bi);
    pre_im = (ar * bi) + (ai * br);
    out.re = trecap_rnd_shr(pre_re, T_FRAC_F);
    out.im = trecap_rnd_shr(pre_im, T_FRAC_F);
    return out;
  endfunction : trecap_cmul_f

  // Full-precision magnitude squared helper for canonical FFT bins. Callers shall
  // provision the destination width according to T_MAG2_W or a documented larger width.
  function automatic trecap_math_uwide_t trecap_mag2_swide(
      input trecap_math_swide_t re,
      input trecap_math_swide_t im
  );
    trecap_math_uwide_t abs_re;
    trecap_math_uwide_t abs_im;

    abs_re = trecap_abs_mag(re);
    abs_im = trecap_abs_mag(im);
    return (abs_re * abs_re) + (abs_im * abs_im);
  endfunction : trecap_mag2_swide

  function automatic bit trecap_mask_from_mag2(
      input logic [T_MAG2_W-1:0] mag2,
      input logic [T_MAG2_W-1:0] thr2
  );
    return mag2 < thr2;
  endfunction : trecap_mask_from_mag2

  function automatic bit trecap_unique_bin_eligible(input int unsigned bin_idx);
    if ((bin_idx == T_SELF_CONJ_DC_BIN) && T_PROTECT_DC) begin
      return 1'b0;
    end
    if ((bin_idx == T_SELF_CONJ_NYQ_BIN) && T_PROTECT_NYQ) begin
      return 1'b0;
    end
    return 1'b1;
  endfunction : trecap_unique_bin_eligible

  function automatic int unsigned trecap_unique_bin_weight(input int unsigned bin_idx);
    if ((bin_idx == T_SELF_CONJ_DC_BIN) || (bin_idx == T_SELF_CONJ_NYQ_BIN)) begin
      return 1;
    end
    return 2;
  endfunction : trecap_unique_bin_weight

  function automatic int unsigned trecap_clog2_ceil(input int unsigned value);
    int unsigned v;
    int unsigned n;

    if (value <= 1) begin
      return 0;
    end

    v = value - 1;
    n = 0;
    while (v != 0) begin
      v = v >> 1;
      n = n + 1;
    end
    return n;
  endfunction : trecap_clog2_ceil

endpackage : trecap_math_pkg

`default_nettype wire
