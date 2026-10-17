`default_nettype none
module mask_formal(
    input wire clk, rst_n, enable_i, clear_i, clear_metrics_i, clear_sticky_i,
    input wire [55:0] thr2_i,
    input wire in_valid_i, out_ready_i, in_unique_i, in_self_conj_i, in_last_i,
    input wire [63:0] in_frame_idx_i,
    input wire [7:0] in_bin_idx_i,
    input wire signed [27:0] in_re_i, in_im_i
);
    wire in_ready_o, out_valid_o;
    wire [63:0] out_frame_idx_o;
    wire [7:0] out_bin_idx_o;
    wire signed [27:0] out_re_o, out_im_o;
    wire [55:0] out_mag2_o;
    wire out_pre_mask_o, out_mask_o, out_eligible_o, out_unique_o, out_last_o;
    trecap_mag2_mask dut(
        .clk(clk), .rst_n(rst_n), .enable_i(enable_i), .clear_i(clear_i),
        .clear_metrics_i(clear_metrics_i), .clear_sticky_i(clear_sticky_i), .thr2_i(thr2_i),
        .in_valid_i(in_valid_i), .in_ready_o(in_ready_o), .in_frame_idx_i(in_frame_idx_i),
        .in_bin_idx_i(in_bin_idx_i), .in_re_i(in_re_i), .in_im_i(in_im_i),
        .in_unique_i(in_unique_i), .in_self_conj_i(in_self_conj_i), .in_last_i(in_last_i),
        .out_valid_o(out_valid_o), .out_ready_i(out_ready_i), .out_frame_idx_o(out_frame_idx_o),
        .out_bin_idx_o(out_bin_idx_o), .out_re_o(out_re_o), .out_im_o(out_im_o),
        .out_mag2_o(out_mag2_o), .out_pre_mask_o(out_pre_mask_o), .out_mask_o(out_mask_o),
        .out_eligible_o(out_eligible_o), .out_unique_o(out_unique_o), .out_last_o(out_last_o),
        .frame_stats_valid_o(), .frame_stats_frame_idx_o(), .frame_stats_o(), .overflow_sticky_o()
    );
    reg past_valid=0, expected_valid=0, saw_clear=0;
    reg [55:0] recorded_thr;
    reg [63:0] recorded_frame;
    reg [7:0] recorded_bin;
    reg signed [27:0] recorded_re, recorded_im;
    reg recorded_unique, recorded_last;
    wire accepted = in_valid_i && in_ready_o;
    wire [188:0] payload = {out_frame_idx_o,out_bin_idx_o,out_re_o,out_im_o,out_mag2_o,
        out_pre_mask_o,out_mask_o,out_eligible_o,out_unique_o,out_last_o};
    always @(posedge clk) begin
        past_valid<=1;
        if (!past_valid) assume(!rst_n);
        if (past_valid && rst_n) begin
            a_ready: assert(in_ready_o == (enable_i && !clear_i && (!out_valid_o || out_ready_i)));
            a_valid_ownership: assert(out_valid_o == expected_valid);
`ifdef MASK_NEGATIVE
            a_deliberately_false_never_valid: assert(!out_valid_o);
`endif
            if (out_valid_o) begin
                a_pre_mask_strict: assert(out_pre_mask_o == (out_unique_o && out_mag2_o < recorded_thr));
                a_eligible_dc_only: assert(out_eligible_o == (out_unique_o && out_bin_idx_o != 0));
                a_mask_rule: assert(out_mask_o == (out_eligible_o && out_pre_mask_o));
                a_no_mask_at_equality: assert(out_mag2_o != recorded_thr || !out_mask_o);
                a_dc_protected: assert(out_bin_idx_o != 0 || !out_mask_o);
                a_metadata: assert({out_frame_idx_o,out_bin_idx_o,out_unique_o,out_last_o} == {recorded_frame,recorded_bin,recorded_unique,recorded_last});
                a_complex_passthrough: assert(out_re_o == recorded_re && out_im_o == recorded_im);
            end
            if ($past(rst_n && !clear_i && out_valid_o && !out_ready_i) && !clear_i) begin
                a_stall_valid: assert(out_valid_o);
                a_stall_payload: assert(payload == $past(payload));
            end
            c_stall: cover(out_valid_o && !out_ready_i);
            c_simultaneous_accept: cover(out_valid_o && out_ready_i && accepted);
            c_dc_protected_despite_pre_mask: cover(out_valid_o && out_bin_idx_o==0 && out_pre_mask_o && !out_mask_o);
            c_nyquist_suppression: cover(out_valid_o && out_bin_idx_o==128 && out_mask_o);
            c_equality_retained: cover(out_valid_o && out_eligible_o && out_mag2_o==recorded_thr && !out_mask_o);
            c_just_below_suppressed: cover(out_valid_o && out_eligible_o && recorded_thr==out_mag2_o+56'd1 && out_mask_o);
            c_clear_recovery: cover(saw_clear && out_valid_o);
        end
        if (!rst_n || clear_i) begin
            expected_valid<=0;
            if (past_valid && rst_n && clear_i) saw_clear<=1;
        end else if (accepted) begin
            expected_valid<=1;
            recorded_thr<=thr2_i;
            recorded_frame<=in_frame_idx_i;
            recorded_bin<=in_bin_idx_i;
            recorded_re<=in_re_i;
            recorded_im<=in_self_conj_i ? 28'sd0 : in_im_i;
            recorded_unique<=in_unique_i;
            recorded_last<=in_last_i;
        end else if (out_ready_i) expected_valid<=0;
    end
endmodule
`default_nettype wire
