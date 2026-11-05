// SPDX-License-Identifier: MIT
// File class: [1] hand-written RTL.
// Layer: rtl/core/
// Owner: T-RECAP Phase 2 implementation.
// Purpose: Reference-model-compatible rolling sample ring and zero-extended frame extractor.
// Contract: Matches SampleRing behavior from the reference model: the ring is logically
//           initialized to zeros, every accepted sample is pushed, and a frame request reads
//           the most recent L samples oldest-to-newest. Pre-stream indices are emitted as
//           zero samples. This block does not do windowing, FFT/IFFT, masking, WOLA,
//           telemetry formatting, DDR writes, HPS, Ethernet, or dashboard work.

`default_nettype none

module trecap_input_ring
#(
    parameter int unsigned SAMPLE_W = trecap_core_pkg::T_SAMPLE_W,
    parameter int unsigned L        = trecap_core_pkg::T_FFT_L,
    // 2*L keeps the most recent frame plus conservative C0 look-ahead storage. It is kept
    // power-of-two so positive sample_idx low bits form the physical address.
    parameter int unsigned DEPTH    = 2*trecap_core_pkg::T_FFT_L,
    parameter int unsigned ADDR_W   = (DEPTH <= 1) ? 1 : $clog2(DEPTH),
    parameter int unsigned OFFSET_W = (L <= 1) ? 1 : $clog2(L)
) (
    input  logic                         clk,
    input  logic                         rst_n,
    input  logic                         enable_i,
    input  logic                         clear_i,
    input  logic                         clear_sticky_i,

    input  logic                         sample_valid_i,
    output logic                         sample_ready_o,
    input  logic signed [SAMPLE_W-1:0]   sample_i,
    input  logic [63:0]                  sample_idx_i,
    output logic                         sample_accept_pulse_o,
    output logic signed [SAMPLE_W-1:0]   accepted_sample_o,
    output logic [63:0]                  accepted_sample_idx_o,

    input  logic                         frame_req_valid_i,
    output logic                         frame_req_ready_o,
    input  logic [63:0]                  frame_req_frame_idx_i,
    input  logic [63:0]                  frame_req_trigger_sample_idx_i,

    output logic                         frame_sample_valid_o,
    input  logic                         frame_sample_ready_i,
    output logic signed [SAMPLE_W-1:0]   frame_sample_o,
    output logic [63:0]                  frame_sample_idx_o,
    output logic [OFFSET_W-1:0]          frame_sample_offset_o,
    output logic [63:0]                  frame_sample_frame_idx_o,
    output logic                         frame_sample_last_o,

    output logic                         busy_o,
    output logic                         overflow_sticky_o
);
  import trecap_core_pkg::*;


    localparam logic [OFFSET_W-1:0] LAST_OFFSET = OFFSET_W'(L - 1);
    localparam logic signed [64:0] L_MINUS_ONE = 65'(L - 1);
    localparam int unsigned RAM_W = 64 + SAMPLE_W;

    // One M10K simple-dual-port word contains the sample and its absolute tag.
    // Only the small validity bitmap is reset. Payload/tag RAM has no reset mux.
    (* ramstyle = "M10K" *) logic [RAM_W-1:0] sample_mem [0:DEPTH-1];
    logic [DEPTH-1:0] valid_bits_q;
    logic [RAM_W-1:0] read_word_q;

    logic frame_active_q;
    logic [63:0] frame_idx_q;
    logic signed [64:0] frame_start_idx_q;
    logic [OFFSET_W-1:0] frame_offset_q;
    logic have_last_sample_idx_q;
    logic [63:0] last_sample_idx_q;

    // A read request owns this metadata until its synchronous RAM response is
    // copied into the output holding register. At most one read is outstanding.
    logic read_pending_q;
    logic read_zero_q;
    logic read_entry_present_q;
    logic signed [64:0] read_idx_q;
    logic [OFFSET_W-1:0] read_offset_q;
    logic [63:0] read_frame_idx_q;
    logic read_last_q;
    logic read_tag_ok;

    logic out_valid_q;
    logic signed [SAMPLE_W-1:0] out_sample_q;
    logic signed [64:0] out_sample_idx_s_q;
    logic [OFFSET_W-1:0] out_offset_q;
    logic [63:0] out_frame_idx_q;
    logic out_last_q;

    logic sample_accept;
    logic frame_req_accept;
    logic frame_sample_accept;
    logic issue_read;
    logic signed [64:0] read_sample_idx_s;
    logic read_is_zero_extended;
    logic [ADDR_W-1:0] write_addr;
    logic [ADDR_W-1:0] read_addr;

    assign sample_ready_o = rst_n && enable_i && !clear_i &&
                            !frame_req_valid_i && !frame_active_q &&
                            !read_pending_q && !out_valid_q;
    assign frame_req_ready_o = rst_n && enable_i && !clear_i &&
                               !frame_active_q && !read_pending_q && !out_valid_q;
    assign sample_accept = sample_valid_i && sample_ready_o;
    assign frame_req_accept = frame_req_valid_i && frame_req_ready_o;
    assign frame_sample_accept = frame_sample_valid_o && frame_sample_ready_i;

    // Source admission stops for the entire extraction, so a synchronous read
    // never races a ring overwrite. The scheduler may have accepted one newer
    // look-ahead sample before presenting the request; DEPTH >= 2*L covers it.
    assign write_addr = sample_idx_i[ADDR_W-1:0];
    assign read_sample_idx_s = frame_start_idx_q + $signed(65'(frame_offset_q));
    assign read_is_zero_extended = (read_sample_idx_s < 65'sd0);
    assign read_addr = read_sample_idx_s[ADDR_W-1:0];
    assign issue_read = rst_n && enable_i && !clear_i && frame_active_q &&
                        !read_pending_q && (!out_valid_q || frame_sample_ready_i);
    assign read_tag_ok = read_zero_q ||
                         (read_entry_present_q &&
                          (read_word_q[RAM_W-1 -: 64] == read_idx_q[63:0]));

    assign frame_sample_valid_o = out_valid_q;
    assign frame_sample_o = out_sample_q;
    assign frame_sample_idx_o = out_sample_idx_s_q[63:0];
    assign frame_sample_offset_o = out_offset_q;
    assign frame_sample_frame_idx_o = out_frame_idx_q;
    assign frame_sample_last_o = out_last_q;
    assign busy_o = frame_active_q || read_pending_q || out_valid_q;

    // Intel simple-dual-port inference template: one write address, one
    // registered read address/data operation, and no reset on either RAM port.
    always_ff @(posedge clk) begin : p_sample_memory
        if (sample_accept) begin
            sample_mem[write_addr] <= {sample_idx_i, $unsigned(sample_i)};
        end
        if (issue_read && !read_is_zero_extended) begin
            read_word_q <= sample_mem[read_addr];
        end
    end

    always_ff @(posedge clk or negedge rst_n) begin : p_input_ring
        if (!rst_n) begin
            valid_bits_q <= '0;
            frame_active_q <= 1'b0;
            frame_idx_q <= '0;
            frame_start_idx_q <= '0;
            frame_offset_q <= '0;
            have_last_sample_idx_q <= 1'b0;
            last_sample_idx_q <= '0;
            read_pending_q <= 1'b0;
            read_zero_q <= 1'b0;
            read_entry_present_q <= 1'b0;
            read_idx_q <= '0;
            read_offset_q <= '0;
            read_frame_idx_q <= '0;
            read_last_q <= 1'b0;
            out_valid_q <= 1'b0;
            out_sample_q <= '0;
            out_sample_idx_s_q <= '0;
            out_offset_q <= '0;
            out_frame_idx_q <= '0;
            out_last_q <= 1'b0;
            sample_accept_pulse_o <= 1'b0;
            accepted_sample_o <= '0;
            accepted_sample_idx_o <= '0;
            overflow_sticky_o <= 1'b0;
        end else begin
            sample_accept_pulse_o <= 1'b0;
            if (clear_i) begin
                valid_bits_q <= '0;
                frame_active_q <= 1'b0;
                frame_idx_q <= '0;
                frame_start_idx_q <= '0;
                frame_offset_q <= '0;
                have_last_sample_idx_q <= 1'b0;
                last_sample_idx_q <= '0;
                read_pending_q <= 1'b0;
                read_zero_q <= 1'b0;
                read_entry_present_q <= 1'b0;
                read_idx_q <= '0;
                read_offset_q <= '0;
                read_frame_idx_q <= '0;
                read_last_q <= 1'b0;
                out_valid_q <= 1'b0;
                out_sample_q <= '0;
                out_sample_idx_s_q <= '0;
                out_offset_q <= '0;
                out_frame_idx_q <= '0;
                out_last_q <= 1'b0;
                accepted_sample_o <= '0;
                accepted_sample_idx_o <= '0;
                overflow_sticky_o <= 1'b0;
            end else begin
                if (clear_sticky_i) overflow_sticky_o <= 1'b0;

                if (sample_accept) begin
                    valid_bits_q[write_addr] <= 1'b1;
                    accepted_sample_o <= sample_i;
                    accepted_sample_idx_o <= sample_idx_i;
                    sample_accept_pulse_o <= 1'b1;
                    if (have_last_sample_idx_q &&
                        (sample_idx_i != (last_sample_idx_q + 64'd1))) begin
                        overflow_sticky_o <= 1'b1;
                    end
                    have_last_sample_idx_q <= 1'b1;
                    last_sample_idx_q <= sample_idx_i;
                end

                if (frame_sample_accept) begin
                    out_valid_q <= 1'b0;
                    out_last_q <= 1'b0;
                end

                if (frame_req_accept) begin
                    frame_active_q <= 1'b1;
                    frame_idx_q <= frame_req_frame_idx_i;
                    frame_start_idx_q <= $signed({1'b0, frame_req_trigger_sample_idx_i}) - L_MINUS_ONE;
                    frame_offset_q <= '0;
                end

                if (issue_read) begin
                    read_pending_q <= 1'b1;
                    read_zero_q <= read_is_zero_extended;
                    read_entry_present_q <= valid_bits_q[read_addr];
                    read_idx_q <= read_sample_idx_s;
                    read_offset_q <= frame_offset_q;
                    read_frame_idx_q <= frame_idx_q;
                    read_last_q <= (frame_offset_q == LAST_OFFSET);
                    if (frame_offset_q == LAST_OFFSET) begin
                        frame_active_q <= 1'b0;
                        frame_offset_q <= '0;
                    end else begin
                        frame_offset_q <= frame_offset_q + 1'b1;
                    end
                end

                if (read_pending_q) begin
                    read_pending_q <= 1'b0;
                    out_valid_q <= 1'b1;
                    out_sample_q <= (read_zero_q || !read_tag_ok)
                                    ? '0 : $signed(read_word_q[SAMPLE_W-1:0]);
                    out_sample_idx_s_q <= read_idx_q;
                    out_offset_q <= read_offset_q;
                    out_frame_idx_q <= read_frame_idx_q;
                    out_last_q <= read_last_q;
                    if (!read_tag_ok) overflow_sticky_o <= 1'b1;
                end

                if (!enable_i) begin
                    if (frame_active_q || read_pending_q || out_valid_q)
                        overflow_sticky_o <= 1'b1;
                    frame_active_q <= 1'b0;
                    read_pending_q <= 1'b0;
                    out_valid_q <= 1'b0;
                    out_last_q <= 1'b0;
                    frame_offset_q <= '0;
                end
            end
        end
    end

`ifndef SYNTHESIS
    initial begin
        if (SAMPLE_W != T_SAMPLE_W)
            $fatal(1, "trecap_input_ring: SAMPLE_W must match generated T_SAMPLE_W");
        if (L != T_FFT_L)
            $fatal(1, "trecap_input_ring: L must match generated T_FFT_L");
        if ((DEPTH < (2*L)) || ((DEPTH & (DEPTH - 1)) != 0))
            $fatal(1, "trecap_input_ring: DEPTH must be a power of two and at least 2*L");
        if (ADDR_W != $clog2(DEPTH))
            $fatal(1, "trecap_input_ring: ADDR_W must equal clog2(DEPTH)");
    end
`endif

endmodule : trecap_input_ring

`default_nettype wire
