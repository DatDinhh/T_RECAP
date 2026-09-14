// SPDX-License-Identifier: MIT
// File class: [1] hand-written RTL.
// Layer: rtl/core/
// Owner: T-RECAP Phase 2 implementation.
// Purpose: Align x[n-D] with y[n] and compute time-domain error metrics/taps.
// Contract: Matches reference update_time_error_metrics(): err[n] = x_zero_extended[n-D] - y[n].
//           This block does not compute FFT/IFFT/STFT/WOLA/mask decisions and owns no telemetry,
//           DDR, HPS, Ethernet, or dashboard behavior.

`default_nettype none

module trecap_delay_error_metrics
#(
    parameter int unsigned SAMPLE_W = trecap_core_pkg::T_SAMPLE_W,
    parameter int unsigned DELAY_D  = trecap_core_pkg::T_DELAY_D,
    parameter int unsigned ERR_W    = 16,
    parameter int unsigned DEPTH    = 1024,
    parameter int unsigned ADDR_W   = (DEPTH <= 1) ? 1 : $clog2(DEPTH)
) (
    input  logic                         clk,
    input  logic                         rst_n,
    input  logic                         enable_i,
    input  logic                         clear_i,
    input  logic                         clear_metrics_i,
    input  logic                         clear_sticky_i,

    input  logic                         x_valid_i,
    output logic                         x_ready_o,
    input  logic signed [SAMPLE_W-1:0]   x_sample_i,
    input  logic [63:0]                  x_sample_idx_i,

    input  logic                         y_valid_i,
    output logic                         y_ready_o,
    input  logic signed [SAMPLE_W-1:0]   y_sample_i,
    input  logic [63:0]                  y_sample_idx_i,

    output logic                         y_out_valid_o,
    input  logic                         y_out_ready_i,
    output trecap_iface_pkg::trecap_sample_t               y_sample_o,
    output logic signed [SAMPLE_W-1:0]   y_sample_data_o,
    output logic [63:0]                  y_sample_idx_o,

    output trecap_iface_pkg::trecap_core_tap_sample_t      tap_sample_o,
    output logic                         tap_sample_valid_o,

    output logic [63:0]                  accepted_x_count_o,
    output logic [63:0]                  accepted_y_count_o,
    output logic [ADDR_W:0]              history_occupancy_o,
    output logic                         history_full_o,
    output logic                         history_empty_o,
    output logic                         busy_o,
    output logic [63:0]                  sum_abs_err_lo_o,
    output logic [63:0]                  sum_sq_err_lo_o,
    output logic [15:0]                  max_abs_err_o,
    output logic [31:0]                  overflow_flags_o,
    output logic                         delay_not_full_sticky_o,
    output logic                         metric_overflow_sticky_o,
    output logic                         protocol_error_sticky_o,
    output logic                         output_backpressure_sticky_o
);
  import trecap_core_pkg::*;
  import trecap_iface_pkg::*;


    localparam int unsigned RAM_W      = 64 + SAMPLE_W;
    localparam int unsigned ERR_FULL_W = SAMPLE_W + 1;
    localparam int unsigned ABS_W      = ERR_FULL_W;
    localparam int unsigned SQ_W       = 2 * ABS_W;
    localparam logic [ADDR_W:0] DEPTH_COUNT = DEPTH;
    localparam logic [63:0] COUNT_MAX = 64'hffff_ffff_ffff_ffff;

    // The history is an ordered FIFO, not an index cache. Strict x/y index admission plus
    // next_retire_idx_q prove that the FIFO head is exactly x[y-D]. Memory contents never need
    // reset; pointer/occupancy reset invalidates every stale word and permits block-RAM inference.
    logic [ADDR_W-1:0] write_ptr_q;
    logic [ADDR_W-1:0] read_ptr_q;
    logic [ADDR_W:0]   occupancy_q;
    logic [63:0]       next_x_idx_q;
    logic [63:0]       next_y_idx_q;
    logic [63:0]       next_retire_idx_q;
    logic [63:0]       metric_sample_count_q;

    logic              pending_y_valid_q;
    logic signed [SAMPLE_W-1:0] pending_y_sample_q;
    logic [63:0]       pending_y_idx_q;
    logic              pending_y_needs_history_q;
    logic              pending_history_data_valid_q;
    logic signed [SAMPLE_W-1:0] pending_history_sample_q;

    logic              y_out_valid_q;
    trecap_sample_t    y_sample_q;
    trecap_core_tap_sample_t tap_sample_q;

    logic              fail_stop_q;
    logic              protocol_status_q;
    logic              arithmetic_fault_q;

    logic              x_index_ok;
    logic              y_index_ok;
    logic              history_empty;
    logic              history_full;
    logic              output_slot_available;
    logic              pending_slot_available;
    logic              y_needs_history;
    logic [63:0]       y_xref_idx;
    logic              y_history_relation_ok;
    logic              x_accept;
    logic              y_request_accept;
    logic              history_push;
    logic              history_pop;
    logic              y_output_accept;

    logic [RAM_W-1:0]  history_wr_data;
    logic [SAMPLE_W-1:0] history_wr_sample_bits;
    logic [RAM_W-1:0]  history_rd_data;
    logic              history_rd_valid;
    logic              history_rd_wr_same_addr;
    logic              history_wr_oob;
    logic              history_rd_oob;
    logic [63:0]       history_rd_idx;
    logic signed [SAMPLE_W-1:0] history_rd_sample;

    logic [63:0]       pending_xref_idx;
    logic              pending_history_tag_ok;
    logic              pending_history_ready;
    logic              pending_history_bad;
    logic signed [SAMPLE_W-1:0] x_delayed_comb;
    logic signed [ERR_FULL_W-1:0] x_ext_comb;
    logic signed [ERR_FULL_W-1:0] y_ext_comb;
    logic signed [ERR_FULL_W-1:0] err_full_comb;
    logic signed [ERR_W-1:0]      err_i16_comb;
    logic                         err_sat;
    logic [ABS_W-1:0]             abs_err_comb;
    logic [SQ_W-1:0]              sq_err_comb;
    logic [64:0]                  sum_abs_ext_comb;
    logic [64:0]                  sum_sq_ext_comb;
    logic                         pending_commit;
    logic                         irrecoverable_history_request;

    function automatic logic [ADDR_W-1:0] increment_ptr(
        input logic [ADDR_W-1:0] ptr
    );
        begin
            if (ptr == (DEPTH - 1)) begin
                increment_ptr = '0;
            end else begin
                increment_ptr = ptr + 1'b1;
            end
        end
    endfunction : increment_ptr

    assign history_empty = (occupancy_q == '0);
    assign history_full = (occupancy_q == DEPTH_COUNT);
    assign x_index_ok = !x_valid_i || (x_sample_idx_i == next_x_idx_q);
    assign y_index_ok = !y_valid_i || (y_sample_idx_i == next_y_idx_q);

    assign output_slot_available = !y_out_valid_q || y_out_ready_i;
    assign pending_slot_available = !pending_y_valid_q || pending_commit;
    assign y_needs_history = y_valid_i && (y_sample_idx_i >= DELAY_D);
    assign y_xref_idx = y_sample_idx_i - DELAY_D;
    assign y_history_relation_ok =
        !y_needs_history ||
        (!history_empty && (next_retire_idx_q == y_xref_idx));

    // Ready is fail-closed on a bad index. When valid is low, meaningless payload bits never
    // suppress ready. Full history never borrows same-cycle pop credit, which prevents a
    // same-address read/write dependency at pointer wrap.
    assign x_ready_o =
        rst_n && enable_i && !clear_i && !fail_stop_q &&
        !history_full && (next_x_idx_q != COUNT_MAX) && x_index_ok;
    assign y_ready_o =
        rst_n && enable_i && !clear_i && !clear_metrics_i && !fail_stop_q &&
        pending_slot_available && (next_y_idx_q != COUNT_MAX) &&
        y_index_ok && y_history_relation_ok;

    assign x_accept = x_valid_i && x_ready_o;
    assign y_request_accept = y_valid_i && y_ready_o;
    assign history_push = x_accept;
    assign history_pop = y_request_accept && y_needs_history;
    assign y_output_accept = y_out_valid_q && y_out_ready_i;

    assign history_wr_sample_bits = $unsigned(x_sample_i);

    // Pack by explicit bit slices from an unsigned sample bit-vector. This avoids tool-dependent
    // sign extension inside a mixed-width concatenation, which would corrupt the 64-bit index tag.
    always_comb begin : p_pack_history_word
        history_wr_data = '0;
        history_wr_data[SAMPLE_W-1:0] = history_wr_sample_bits;
        history_wr_data[RAM_W-1 -: 64] = x_sample_idx_i;
    end
    assign history_rd_idx = history_rd_data[RAM_W-1 -: 64];
    assign history_rd_sample = $signed(history_rd_data[SAMPLE_W-1:0]);

    // One 1024 x (64 + SAMPLE_W) simple-dual-port M10K history store. Data and
    // read-data registers have no reset; occupancy/pending-valid reset starts a new epoch.
    // The control path never reads an empty FIFO and never credits a simultaneous pop
    // when full, so a valid request cannot read and write the same physical address.
    (* ramstyle = "M10K" *) logic [RAM_W-1:0] history_mem [0:DEPTH-1];

    always_ff @(posedge clk) begin : p_history_storage
        if (rst_n && history_push && (write_ptr_q < DEPTH)) begin
            history_mem[write_ptr_q] <= history_wr_data;
        end
        if (rst_n && history_pop && (read_ptr_q < DEPTH)) begin
            history_rd_data <= history_mem[read_ptr_q];
        end
    end

    always_ff @(posedge clk or negedge rst_n) begin : p_history_response
        if (!rst_n) begin
            history_rd_valid <= 1'b0;
            history_rd_wr_same_addr <= 1'b0;
            history_wr_oob <= 1'b0;
            history_rd_oob <= 1'b0;
        end else if (clear_i) begin
            history_rd_valid <= 1'b0;
            history_rd_wr_same_addr <= 1'b0;
            history_wr_oob <= 1'b0;
            history_rd_oob <= 1'b0;
        end else begin
            history_rd_valid <= history_pop && (read_ptr_q < DEPTH);
            history_rd_wr_same_addr <= history_push && history_pop &&
                                      (write_ptr_q == read_ptr_q);
            history_wr_oob <= history_push && (write_ptr_q >= DEPTH);
            history_rd_oob <= history_pop && (read_ptr_q >= DEPTH);
        end
    end
    assign pending_xref_idx = pending_y_idx_q - DELAY_D;
    assign pending_history_tag_ok =
        history_rd_valid && (history_rd_idx == pending_xref_idx);
    assign pending_history_ready =
        !pending_y_needs_history_q ||
        pending_history_data_valid_q ||
        pending_history_tag_ok;
    assign pending_history_bad =
        pending_y_valid_q && pending_y_needs_history_q &&
        history_rd_valid && !pending_history_tag_ok;

    assign x_delayed_comb =
        pending_y_needs_history_q
            ? (pending_history_data_valid_q
                ? pending_history_sample_q
                : history_rd_sample)
            : '0;
    assign x_ext_comb =
        {{(ERR_FULL_W-SAMPLE_W){x_delayed_comb[SAMPLE_W-1]}}, x_delayed_comb};
    assign y_ext_comb =
        {{(ERR_FULL_W-SAMPLE_W){pending_y_sample_q[SAMPLE_W-1]}},
         pending_y_sample_q};
    assign err_full_comb = x_ext_comb - y_ext_comb;

    trecap_round_sat #(
        .IN_W( ERR_FULL_W ),
        .OUT_W( ERR_W ),
        .SHIFT( 0 )
    ) u_error_sat (
        .value_i( err_full_comb ),
        .value_o( err_i16_comb ),
        .sat_hi_o( ),
        .sat_lo_o( ),
        .sat_any_o( err_sat )
    );

    assign abs_err_comb =
        err_full_comb[ERR_FULL_W-1]
            ? $unsigned(-err_full_comb)
            : $unsigned(err_full_comb);
    assign sq_err_comb = abs_err_comb * abs_err_comb;
    assign sum_abs_ext_comb =
        {1'b0, sum_abs_err_lo_o} +
        {{(65-ABS_W){1'b0}}, abs_err_comb};
    assign sum_sq_ext_comb =
        {1'b0, sum_sq_err_lo_o} +
        {{(65-SQ_W){1'b0}}, sq_err_comb};

    // A pending history tag mismatch or impossible error saturation is an alignment/arithmetic
    // contract failure. Do not forward or accumulate the corrupt sample.
    assign pending_commit =
        rst_n && enable_i && !clear_i && !clear_metrics_i && !fail_stop_q &&
        pending_y_valid_q && output_slot_available &&
        pending_history_ready && !err_sat;

    assign irrecoverable_history_request =
        enable_i && !clear_i && y_valid_i && y_index_ok &&
        y_needs_history && !y_history_relation_ok &&
        (y_xref_idx < next_x_idx_q);

    assign y_out_valid_o = y_out_valid_q;
    assign y_sample_o = y_sample_q;
    assign y_sample_data_o = y_sample_q.data;
    assign y_sample_idx_o = y_sample_q.sample_idx;
    assign tap_sample_o = tap_sample_q;
    assign tap_sample_valid_o = tap_sample_q.valid;
    assign accepted_x_count_o = next_x_idx_q;
    assign accepted_y_count_o = metric_sample_count_q;
    assign history_occupancy_o = occupancy_q;
    assign history_full_o = history_full;
    assign history_empty_o = history_empty;
    assign busy_o =
        !history_empty || pending_y_valid_q || y_out_valid_q || fail_stop_q;
    assign protocol_error_sticky_o = protocol_status_q || fail_stop_q;

    // Core-local delay status. The core integration wrapper translates these private bits into
    // its public overflow namespace; they must never be ORed raw into transport CSR flags.
    always_comb begin : p_overflow_map
        overflow_flags_o = 32'd0;
        if (arithmetic_fault_q || metric_overflow_sticky_o) begin
            overflow_flags_o[0] = 1'b1;
        end
        if (fail_stop_q || delay_not_full_sticky_o) begin
            overflow_flags_o[1] = 1'b1;
        end
    end

    always_ff @(posedge clk or negedge rst_n) begin : p_delay_error_metrics
        if (!rst_n) begin
            write_ptr_q                    <= '0;
            read_ptr_q                     <= '0;
            occupancy_q                    <= '0;
            next_x_idx_q                   <= 64'd0;
            next_y_idx_q                   <= 64'd0;
            next_retire_idx_q              <= 64'd0;
            metric_sample_count_q          <= 64'd0;
            pending_y_valid_q              <= 1'b0;
            pending_y_sample_q             <= '0;
            pending_y_idx_q                <= 64'd0;
            pending_y_needs_history_q      <= 1'b0;
            pending_history_data_valid_q   <= 1'b0;
            pending_history_sample_q       <= '0;
            y_out_valid_q                  <= 1'b0;
            y_sample_q                     <= '0;
            tap_sample_q                   <= '0;
            fail_stop_q                    <= 1'b0;
            protocol_status_q              <= 1'b0;
            arithmetic_fault_q             <= 1'b0;
            sum_abs_err_lo_o               <= 64'd0;
            sum_sq_err_lo_o                <= 64'd0;
            max_abs_err_o                  <= 16'd0;
            delay_not_full_sticky_o        <= 1'b0;
            metric_overflow_sticky_o       <= 1'b0;
            output_backpressure_sticky_o   <= 1'b0;
        end else begin
            tap_sample_q.valid <= 1'b0;

            if (clear_i) begin
                write_ptr_q                    <= '0;
                read_ptr_q                     <= '0;
                occupancy_q                    <= '0;
                next_x_idx_q                   <= 64'd0;
                next_y_idx_q                   <= 64'd0;
                next_retire_idx_q              <= 64'd0;
                metric_sample_count_q          <= 64'd0;
                pending_y_valid_q              <= 1'b0;
                pending_y_sample_q             <= '0;
                pending_y_idx_q                <= 64'd0;
                pending_y_needs_history_q      <= 1'b0;
                pending_history_data_valid_q   <= 1'b0;
                pending_history_sample_q       <= '0;
                y_out_valid_q                  <= 1'b0;
                y_sample_q                     <= '0;
                tap_sample_q                   <= '0;
                fail_stop_q                    <= 1'b0;
                protocol_status_q              <= 1'b0;
                arithmetic_fault_q             <= 1'b0;
                sum_abs_err_lo_o               <= 64'd0;
                sum_sq_err_lo_o                <= 64'd0;
                max_abs_err_o                  <= 16'd0;
                delay_not_full_sticky_o        <= 1'b0;
                metric_overflow_sticky_o       <= 1'b0;
                output_backpressure_sticky_o   <= 1'b0;
            end else begin
                if (clear_sticky_i) begin
                    protocol_status_q            <= 1'b0;
                    output_backpressure_sticky_o <= 1'b0;
                    // Alignment fail-stop and metric truncation deliberately survive a generic
                    // sticky clear. Only clear_i or clear_metrics_i can make their retained state
                    // trustworthy again.
                end

                if (clear_metrics_i) begin
                    metric_sample_count_q    <= 64'd0;
                    sum_abs_err_lo_o         <= 64'd0;
                    sum_sq_err_lo_o          <= 64'd0;
                    max_abs_err_o            <= 16'd0;
                    metric_overflow_sticky_o <= 1'b0;
                    arithmetic_fault_q       <= 1'b0;
                end

                if (y_output_accept && !pending_commit) begin
                    y_out_valid_q   <= 1'b0;
                    y_sample_q.valid <= 1'b0;
                end

                if (pending_commit) begin
                    y_out_valid_q          <= 1'b1;
                    y_sample_q.valid       <= 1'b1;
                    y_sample_q.data        <= pending_y_sample_q;
                    y_sample_q.sample_idx  <= pending_y_idx_q;

                    tap_sample_q.valid      <= 1'b1;
                    tap_sample_q.x_delayed  <= x_delayed_comb;
                    tap_sample_q.y_out      <= pending_y_sample_q;
                    tap_sample_q.error_i16  <= err_i16_comb;
                    tap_sample_q.sample_idx <= pending_y_idx_q;

                    metric_sample_count_q <= metric_sample_count_q + 64'd1;
                    sum_abs_err_lo_o      <= sum_abs_ext_comb[63:0];
                    sum_sq_err_lo_o       <= sum_sq_ext_comb[63:0];
                    if (abs_err_comb > max_abs_err_o) begin
                        max_abs_err_o <= abs_err_comb;
                    end
                    if (sum_abs_ext_comb[64] || sum_sq_ext_comb[64]) begin
                        metric_overflow_sticky_o <= 1'b1;
                    end
                    pending_y_valid_q <= 1'b0;
                    pending_history_data_valid_q <= 1'b0;
                end

                if (y_request_accept) begin
                    pending_y_valid_q         <= 1'b1;
                    pending_y_sample_q        <= y_sample_i;
                    pending_y_idx_q           <= y_sample_idx_i;
                    pending_y_needs_history_q <= y_needs_history;
                    pending_history_data_valid_q <= 1'b0;
                    next_y_idx_q              <= next_y_idx_q + 64'd1;
                end

                // The synchronous RAM response is a one-cycle pulse. If the public output slot is
                // blocked at that instant, retain the exact delayed-x payload until the pending y
                // can commit. Only one y request may be outstanding, so one response latch is
                // sufficient and cannot be overwritten by a second history read.
                if (pending_y_valid_q && pending_y_needs_history_q &&
                    history_rd_valid && pending_history_tag_ok &&
                    !pending_commit) begin
                    pending_history_data_valid_q <= 1'b1;
                    pending_history_sample_q     <= history_rd_sample;
                end

                if (history_push) begin
                    write_ptr_q  <= increment_ptr(write_ptr_q);
                    next_x_idx_q <= next_x_idx_q + 64'd1;
                end
                if (history_pop) begin
                    read_ptr_q        <= increment_ptr(read_ptr_q);
                    next_retire_idx_q <= next_retire_idx_q + 64'd1;
                end

                unique case ({history_push, history_pop})
                    2'b10: occupancy_q <= occupancy_q + 1'b1;
                    2'b01: occupancy_q <= occupancy_q - 1'b1;
                    default: occupancy_q <= occupancy_q;
                endcase

                if (y_out_valid_q && !y_out_ready_i) begin
                    output_backpressure_sticky_o <= 1'b1;
                end

                // Detect bad producer/consumer tokens before accepting them. Once fail-stop is
                // latched, both input channels remain backpressured and busy stays high until a
                // full alignment clear.
                if (enable_i && x_valid_i &&
                    ((x_sample_idx_i != next_x_idx_q) ||
                     (next_x_idx_q == COUNT_MAX))) begin
                    fail_stop_q       <= 1'b1;
                    protocol_status_q <= 1'b1;
                end
                if (enable_i && y_valid_i &&
                    ((y_sample_idx_i != next_y_idx_q) ||
                     (next_y_idx_q == COUNT_MAX))) begin
                    fail_stop_q       <= 1'b1;
                    protocol_status_q <= 1'b1;
                end
                if (irrecoverable_history_request || pending_history_bad) begin
                    fail_stop_q             <= 1'b1;
                    protocol_status_q       <= 1'b1;
                    delay_not_full_sticky_o <= 1'b1;
                end
                if (history_rd_wr_same_addr || history_wr_oob || history_rd_oob ||
                    (occupancy_q > DEPTH_COUNT) ||
                    (history_push && history_full) ||
                    (history_pop && history_empty)) begin
                    fail_stop_q       <= 1'b1;
                    protocol_status_q <= 1'b1;
                end
                if (pending_y_valid_q && pending_history_ready && err_sat) begin
                    fail_stop_q        <= 1'b1;
                    arithmetic_fault_q <= 1'b1;
                end
                if (!enable_i &&
                    (!history_empty || pending_y_valid_q || y_out_valid_q ||
                     x_valid_i || y_valid_i)) begin
                    fail_stop_q       <= 1'b1;
                    protocol_status_q <= 1'b1;
                end
            end
        end
    end

`ifndef SYNTHESIS
    initial begin
        if (SAMPLE_W != T_SAMPLE_W) begin
            $fatal(1, "trecap_delay_error_metrics: SAMPLE_W must match generated T_SAMPLE_W");
        end
        if (DELAY_D != T_DELAY_D) begin
            $fatal(1, "trecap_delay_error_metrics: DELAY_D must match generated T_DELAY_D");
        end
        if (ERR_W != 16) begin
            $fatal(1, "trecap_delay_error_metrics: ERR_W must be 16 for Revision G WAVE payloads");
        end
        if ((DEPTH < (2*DELAY_D)) || ((DEPTH & (DEPTH - 1)) != 0)) begin
            $fatal(1, "trecap_delay_error_metrics: DEPTH must be a power of two and at least 2*D");
        end
        if (ADDR_W != $clog2(DEPTH)) begin
            $fatal(1, "trecap_delay_error_metrics: ADDR_W must equal clog2(DEPTH)");
        end
        if (ERR_FULL_W > ERR_W) begin
            $fatal(1, "trecap_delay_error_metrics: ERR_W cannot represent the full sample error");
        end
        if ((ABS_W > 64) || (SQ_W > 64)) begin
            $fatal(1, "trecap_delay_error_metrics: metric addends exceed the 64-bit low-word contract");
        end
    end

    always_ff @(posedge clk) begin
        if (rst_n && !clear_i) begin
            if (history_push && history_full) begin
                $error("trecap_delay_error_metrics: accepted x while history was full");
            end
            if (history_pop && history_empty) begin
                $error("trecap_delay_error_metrics: consumed x while history was empty");
            end
            if (history_rd_wr_same_addr) begin
                $error("trecap_delay_error_metrics: forbidden same-address history read/write");
            end
            if (pending_commit && pending_y_needs_history_q &&
                !pending_history_tag_ok) begin
                $error("trecap_delay_error_metrics: committed y without exact delayed-x tag");
            end
        end
    end
`endif

endmodule : trecap_delay_error_metrics

`default_nettype wire
