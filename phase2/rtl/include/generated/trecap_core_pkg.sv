// AUTO-GENERATED - DO NOT EDIT
// Generator: scripts/gen_headers.py
// Generator version: r1.2.0
// Source manifest: spec/generated/gen_manifest.json

package trecap_core_pkg;

  // Core baseline parameters.
  localparam int unsigned T_SAMPLE_W             = 12;  // External signed input/output sample width.
  localparam int unsigned T_FFT_L                = 256;  // FFT length.
  localparam int unsigned T_FFT_P                = 8;  // Number of radix-2 stages.
  localparam int unsigned T_HOP_H                = 128;  // Hop size.
  localparam int unsigned T_FRAC_F               = 15;  // Fixed-point fractional width.
  localparam int unsigned T_CUSHION_G            = 128;  // Scheduling cushion.
  localparam int unsigned T_DELAY_D              = 384;  // Exact causal delay L+G.
  localparam bit          T_PROTECT_DC           = 1;
  localparam bit          T_PROTECT_NYQ          = 0;

  // Fixed-point and internal width schedule.
  localparam int unsigned T_QW_W                 = 16;
  localparam int unsigned T_TWIDDLE_W            = 17;
  localparam int unsigned T_U_W                  = 27;
  localparam int unsigned T_FFT_W                = 28;
  localparam int unsigned T_FFT_PRE_W            = 29;
  localparam int unsigned T_CAN_PRE_W            = 29;
  localparam int unsigned T_CAN_W                = 28;
  localparam int unsigned T_MAG2_W               = 56;
  localparam int unsigned T_IFFT_W               = 36;
  localparam int unsigned T_Z_W                  = 36;
  localparam int unsigned T_OLA_W                = 37;

  // Derived constants used by core, telemetry taps, and artifact consumers.
  localparam int unsigned T_UNIQUE_BINS          = (T_FFT_L/2) + 1;
  localparam int unsigned T_SELF_CONJ_DC_BIN     = 0;
  localparam int unsigned T_SELF_CONJ_NYQ_BIN    = T_FFT_L/2;
  localparam logic [T_MAG2_W-1:0] T_THR2_RESET   = '0;
  localparam int signed   T_SAMPLE_MIN           = -(1 << (T_SAMPLE_W-1));
  localparam int signed   T_SAMPLE_MAX           =  (1 << (T_SAMPLE_W-1)) - 1;

endpackage : trecap_core_pkg
