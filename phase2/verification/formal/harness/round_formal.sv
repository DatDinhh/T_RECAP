`default_nettype none
module round_formal #(parameter integer IN_W=29, OUT_W=28, SHIFT=1, NEGATIVE=0);
    (* anyconst *) reg signed [IN_W-1:0] value_i;
    wire signed [OUT_W-1:0] value_o;
    wire sat_hi_o, sat_lo_o, sat_any_o;
    trecap_round_sat #(.IN_W(IN_W), .OUT_W(OUT_W), .SHIFT(SHIFT)) dut(.*);
    localparam integer R = IN_W + OUT_W + SHIFT + 4;
    wire signed [R-1:0] x = value_i;
    wire signed [R-1:0] unit_value = {{(R-1){1'b0}},1'b1};
    wire signed [R-1:0] floor_q = x >>> SHIFT;
    wire signed [R-1:0] residue = x - (floor_q <<< SHIFT);
    wire signed [R-1:0] half_value = unit_value <<< ((SHIFT>0)?SHIFT-1:0);
    // Independent floor quotient plus nonnegative remainder, not biased magnitude.
    wire round_up = SHIFT>0 && ((residue > half_value) || ((residue == half_value) && x >= 0));
    wire signed [R-1:0] nearest = floor_q + round_up;
    wire signed [R-1:0] lo = -(unit_value <<< (OUT_W-1));
    wire signed [R-1:0] hi = (unit_value <<< (OUT_W-1))-1;
    wire signed [R-1:0] clipped = nearest < lo ? lo : nearest > hi ? hi : nearest;
    always @* begin
        a_exact_value: assert(value_o == clipped);
        a_saturation_high: assert(sat_hi_o == (nearest > hi));
        a_saturation_low: assert(sat_lo_o == (nearest < lo));
        a_saturation_any: assert(sat_any_o == ((nearest > hi) || (nearest < lo)));
        a_mutually_exclusive: assert(!(sat_hi_o && sat_lo_o));
        if (NEGATIVE) a_deliberately_false_no_saturation: assert(!sat_any_o);
        c_zero: cover(x == 0);
        c_minimum_input: cover(x == -(unit_value <<< (IN_W-1)));
        c_maximum_input: cover(x == (unit_value <<< (IN_W-1))-1);
        if (SHIFT>0 && SHIFT<IN_W) begin
            c_positive_tie: cover(x > 0 && residue == half_value);
            c_negative_tie: cover(x < 0 && residue == half_value);
        end
        if (OUT_W+SHIFT <= IN_W && SHIFT>0) c_high_saturation: cover(sat_hi_o);
        if (OUT_W+SHIFT < IN_W) c_low_saturation: cover(sat_lo_o);
    end
endmodule
`default_nettype wire
