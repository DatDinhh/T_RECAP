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
  import trecap_core_pkg::*;
#(
    parameter int unsigned SAMPLE_W = T_SAMPLE_W,
    parameter int unsigned L        = T_FFT_L,
    // 2*L keeps the most recent frame plus conservative C0 look-ahead storage. It is kept
    // power-of-two so positive sample_idx low bits form the physical address.
    parameter int unsigned DEPTH    = 2*T_FFT_L,
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

    localparam logic [OFFSET_W-1:0] LAST_OFFSET  = L - 1;
    localparam logic signed [64:0]   L_MINUS_ONE = L - 1;

    logic signed [SAMPLE_W-1:0] sample_mem [0:DEPTH-1];
    logic [63:0]                idx_mem    [0:DEPTH-1];
    logic                       valid_mem  [0:DEPTH-1];

    logic [63:0]                accepted_count_q;
    logic                       frame_active_q;
    logic [63:0]                frame_idx_q;
    logic signed [64:0]         frame_start_idx_q;
    logic [OFFSET_W-1:0]        frame_offset_q;
    logic                       have_last_sample_idx_q;
    logic [63:0]                last_sample_idx_q;

    logic                       out_valid_q;
    logic signed [SAMPLE_W-1:0] out_sample_q;
    logic signed [64:0]         out_sample_idx_s_q;
    logic [OFFSET_W-1:0]        out_offset_q;
    logic [63:0]                out_frame_idx_q;
    logic                       out_last_q;

    logic                       sample_accept;
    logic                       frame_req_accept;
    logic                       frame_sample_accept;
    logic                       load_next_beat;

    logic signed [64:0]         read_sample_idx_s;
    logic                       read_is_zero_extended;
    logic [ADDR_W-1:0]          write_addr;
    logic [ADDR_W-1:0]          read_addr;
    logic                       read_entry_valid;
    logic signed [SAMPLE_W-1:0] read_sample_comb;

    assign sample_accept = sample_valid_i && sample_ready_o;
    assign frame_req_accept = frame_req_valid_i && frame_req_ready_o;
    assign frame_sample_accept = frame_sample_valid_o && frame_sample_ready_i;

    // Conservative C0 admission control.
    //
    // A new frame becomes due every H accepted samples, while this single-port extractor can
    // require at least L clocks (and arbitrarily longer under downstream backpressure) to
    // deliver one frame. Therefore the source must not continue advancing while a frame request
    // is pending or an extraction beat is outstanding. The BRAM replay source is a compliant
    // ready/valid producer and holds its sample/index stable while this ready is low.
    //
    // The scheduler observes sample_accept_pulse_o one clock after the source handshake, so at
    // most one post-boundary look-ahead sample can be accepted before frame_req_valid_i rises.
    // That sample is newer than the requested frame and is safe because DEPTH >= 2*L.
    assign sample_ready_o = enable_i && !clear_i &&
                            !frame_req_valid_i && !frame_active_q && !out_valid_q;
    assign frame_req_ready_o = enable_i && !clear_i && !frame_active_q && !out_valid_q;

    assign write_addr = sample_idx_i[ADDR_W-1:0];
    assign read_sample_idx_s = frame_start_idx_q + $signed(65'(frame_offset_q));
    assign read_is_zero_extended = (read_sample_idx_s < 65'sd0);
    assign read_addr = read_sample_idx_s[ADDR_W-1:0];
    assign read_entry_valid = read_is_zero_extended ||
                              (valid_mem[read_addr] && (idx_mem[read_addr] == read_sample_idx_s[63:0]));
    // A positive-index tag miss is a fatal correctness condition for signoff. Keep simulation
    // progressing with a deterministic zero rather than leaking a newer sample that reused the
    // same physical address; overflow_sticky_o records the violation below.
    assign read_sample_comb = read_is_zero_extended ? '0 :
                              (read_entry_valid ? sample_mem[read_addr] : '0);

    assign load_next_beat = enable_i && frame_active_q && (!out_valid_q || frame_sample_ready_i);

    assign frame_sample_valid_o = out_valid_q;
    assign frame_sample_o = out_sample_q;
    assign frame_sample_idx_o = out_sample_idx_s_q[63:0];
    assign frame_sample_offset_o = out_offset_q;
    assign frame_sample_frame_idx_o = out_frame_idx_q;
    assign frame_sample_last_o = out_last_q;
    assign busy_o = frame_active_q || out_valid_q;

    always_ff @(posedge clk or negedge rst_n) begin : p_input_ring
        integer i;
        if (!rst_n) begin
            accepted_count_q          <= 64'd0;
            frame_active_q            <= 1'b0;
            frame_idx_q               <= 64'd0;
            frame_start_idx_q         <= 65'sd0;
            frame_offset_q            <= '0;
            have_last_sample_idx_q    <= 1'b0;
            last_sample_idx_q         <= 64'd0;
            out_valid_q               <= 1'b0;
            out_sample_q              <= '0;
            out_sample_idx_s_q        <= 65'sd0;
            out_offset_q              <= '0;
            out_frame_idx_q           <= 64'd0;
            out_last_q                <= 1'b0;
            sample_accept_pulse_o     <= 1'b0;
            accepted_sample_o         <= '0;
            accepted_sample_idx_o     <= 64'd0;
            overflow_sticky_o         <= 1'b0;
            for (i = 0; i < DEPTH; i = i + 1) begin
                valid_mem[i] <= 1'b0;
                idx_mem[i] <= 64'd0;
            end
        end else begin
            sample_accept_pulse_o <= 1'b0;

            if (clear_i) begin
                accepted_count_q       <= 64'd0;
                frame_active_q         <= 1'b0;
                frame_idx_q            <= 64'd0;
                frame_start_idx_q      <= 65'sd0;
                frame_offset_q         <= '0;
                have_last_sample_idx_q <= 1'b0;
                last_sample_idx_q      <= 64'd0;
                out_valid_q            <= 1'b0;
                out_sample_q           <= '0;
                out_sample_idx_s_q     <= 65'sd0;
                out_offset_q           <= '0;
                out_frame_idx_q        <= 64'd0;
                out_last_q             <= 1'b0;
                accepted_sample_o      <= '0;
                accepted_sample_idx_o  <= 64'd0;
                overflow_sticky_o      <= 1'b0;
                for (i = 0; i < DEPTH; i = i + 1) begin
                    valid_mem[i] <= 1'b0;
                    idx_mem[i] <= 64'd0;
                end
            end else begin
                if (clear_sticky_i) begin
                    overflow_sticky_o <= 1'b0;
                end

                if (sample_accept) begin
                    sample_mem[write_addr] <= sample_i;
                    idx_mem[write_addr] <= sample_idx_i;
                    valid_mem[write_addr] <= 1'b1;
                    accepted_sample_o <= sample_i;
                    accepted_sample_idx_o <= sample_idx_i;
                    sample_accept_pulse_o <= 1'b1;
                    accepted_count_q <= accepted_count_q + 64'd1;

                    if (have_last_sample_idx_q && (sample_idx_i != (last_sample_idx_q + 64'd1))) begin
                        overflow_sticky_o <= 1'b1;
                    end
                    have_last_sample_idx_q <= 1'b1;
                    last_sample_idx_q <= sample_idx_i;
                end

                if (frame_sample_accept && !load_next_beat) begin
                    out_valid_q <= 1'b0;
                    out_last_q <= 1'b0;
                end

                if (frame_req_accept) begin
                    frame_active_q <= 1'b1;
                    frame_idx_q <= frame_req_frame_idx_i;
                    frame_start_idx_q <= $signed({1'b0, frame_req_trigger_sample_idx_i}) - L_MINUS_ONE;
                    frame_offset_q <= '0;
                end

                if (load_next_beat) begin
                    out_valid_q <= 1'b1;
                    out_sample_q <= read_sample_comb;
                    out_sample_idx_s_q <= read_sample_idx_s;
                    out_offset_q <= frame_offset_q;
                    out_frame_idx_q <= frame_idx_q;
                    out_last_q <= (frame_offset_q == LAST_OFFSET);

                    if (!read_entry_valid) begin
                        // Positive-index samples must have been pushed into the ring. Missing
                        // entries indicate an impossible frame request, source discontinuity, or
                        // ring overwrite caused by a core-local scheduling violation. Emit zero
                        // to preserve stream progress and flag the error.
                        overflow_sticky_o <= 1'b1;
                    end

                    if (frame_offset_q == LAST_OFFSET) begin
                        frame_active_q <= 1'b0;
                        frame_offset_q <= '0;
                    end else begin
                        frame_offset_q <= frame_offset_q + {{(OFFSET_W-1){1'b0}}, 1'b1};
                    end
                end

                if (!enable_i) begin
                    if (frame_active_q || out_valid_q) begin
                        overflow_sticky_o <= 1'b1;
                    end
                    frame_active_q <= 1'b0;
                    out_valid_q <= 1'b0;
                    frame_offset_q <= '0;
                end
            end
        end
    end

`ifndef SYNTHESIS
    initial begin
        if (SAMPLE_W != T_SAMPLE_W) begin
            $fatal(1, "trecap_input_ring: SAMPLE_W must match generated T_SAMPLE_W");
        end
        if (L != T_FFT_L) begin
            $fatal(1, "trecap_input_ring: L must match generated T_FFT_L");
        end
        if ((DEPTH < (2*L)) || ((DEPTH & (DEPTH - 1)) != 0)) begin
            $fatal(1, "trecap_input_ring: DEPTH must be a power of two and at least 2*L");
        end
    end

    always_ff @(posedge clk) begin
        if (rst_n && !clear_i) begin
            if ((frame_req_valid_i || frame_active_q || out_valid_q) && sample_ready_o) begin
                $error("trecap_input_ring: sample_ready_o asserted while frame storage is reserved");
            end
            if (load_next_beat && !read_entry_valid) begin
                $error("trecap_input_ring: requested positive-index sample is absent or overwritten");
            end
        end
    end
`endif

endmodule : trecap_input_ring

`default_nettype wire
