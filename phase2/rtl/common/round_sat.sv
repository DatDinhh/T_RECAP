// SPDX-License-Identifier: MIT
// File class: [1] hand-written RTL.
// Layer: rtl/common/
// Owner: T-RECAP Phase 2 implementation.
// Purpose: Generic combinational rounded-right-shift and signed saturation primitive.
// Contract: Implements the Revision J rnd_shr(v, s) and signed satN-style operators.
// Generated dependencies: none; callers pass widths and shifts from generated packages.

`default_nettype none

// Combinational round-then-saturate block for signed fixed-point datapaths.
//
// Behavior:
//   rounded = rnd_shr(value_i, SHIFT)
//   value_o = signed_saturate(rounded, OUT_W)
//
// Rounding is round-to-nearest with ties away from zero. This module exists so
// precision-reducing assignments are explicit instead of hidden truncations.
module trecap_round_sat #(
    parameter int unsigned IN_W  = 32,
    parameter int unsigned OUT_W = 16,
    parameter int unsigned SHIFT = 0
) (
    input  logic signed [IN_W-1:0]  value_i,

    output logic signed [OUT_W-1:0] value_o,
    output logic                    sat_hi_o,
    output logic                    sat_lo_o,
    output logic                    sat_any_o
);

    localparam int unsigned BASE_W           = (IN_W > OUT_W) ? IN_W : OUT_W;
    localparam int unsigned WORK_W           = BASE_W + SHIFT + 4;
    localparam int unsigned ROUND_BIAS_SHIFT = (SHIFT == 0) ? 0 : (SHIFT - 1);

    typedef logic signed [WORK_W-1:0] work_s_t;
    typedef logic        [WORK_W-1:0] work_u_t;

    work_s_t in_ext;
    work_u_t abs_mag;
    work_u_t round_bias;
    work_u_t rounded_mag;
    work_s_t rounded_ext;
    work_s_t min_value;
    work_s_t max_value;
    work_s_t clipped_ext;

    always_comb begin
        in_ext = {{(WORK_W-IN_W){value_i[IN_W-1]}}, value_i};

        abs_mag = '0;
        round_bias = '0;
        rounded_mag = '0;
        rounded_ext = in_ext;

        if (SHIFT != 0) begin
            // Revision J:
            //   rnd_shr(v, s) = sgn(v) * floor((abs(v) + 2^(s-1)) / 2^s)
            // for s >= 1. This avoids native arithmetic-shift truncation for
            // negative odd values and matches the reference arithmetic contract.
            if (in_ext < '0) begin
                abs_mag = work_u_t'(-in_ext);
            end else begin
                abs_mag = work_u_t'(in_ext);
            end

            round_bias = work_u_t'(1) << ROUND_BIAS_SHIFT;
            rounded_mag = (abs_mag + round_bias) >> SHIFT;

            if (in_ext < '0) begin
                rounded_ext = -work_s_t'(rounded_mag);
            end else begin
                rounded_ext = work_s_t'(rounded_mag);
            end
        end

        min_value = -(work_s_t'(1) <<< (OUT_W - 1));
        max_value =  (work_s_t'(1) <<< (OUT_W - 1)) - work_s_t'(1);

        sat_hi_o = 1'b0;
        sat_lo_o = 1'b0;
        clipped_ext = rounded_ext;

        if (rounded_ext > max_value) begin
            clipped_ext = max_value;
            sat_hi_o = 1'b1;
        end else if (rounded_ext < min_value) begin
            clipped_ext = min_value;
            sat_lo_o = 1'b1;
        end

        sat_any_o = sat_hi_o | sat_lo_o;
        value_o = clipped_ext[OUT_W-1:0];
    end

`ifndef SYNTHESIS
    initial begin
        if (IN_W < 1) begin
            $fatal(1, "trecap_round_sat: IN_W must be at least 1, got %0d", IN_W);
        end
        if (OUT_W < 1) begin
            $fatal(1, "trecap_round_sat: OUT_W must be at least 1, got %0d", OUT_W);
        end
    end
`endif

endmodule : trecap_round_sat

`default_nettype wire
