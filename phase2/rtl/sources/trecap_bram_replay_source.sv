// SPDX-License-Identifier: MIT
// File class: [1] hand-written RTL source module.
// Layer: rtl/sources/
// Owner: T-RECAP Phase 2 implementation.
// Purpose: Emit deterministic reference input vectors from synchronous replay ROM.
// Contract: This source feeds x_in.memh samples followed by a deterministic zero flush. It does
//           not instantiate STFT/FFT/IFFT/WOLA logic, does not format telemetry packets, does not
//           write DDR, and does not depend on HPS, Ethernet, or dashboard code.

`default_nettype none

module trecap_bram_replay_source
#(
    // The default path is intentionally a placeholder. Test and board profiles should override it
    // with artifacts/test_vectors/<vector_name>/x_in.memh from the reference-model artifact set.
    parameter              INIT_FILE                 = "artifacts/test_vectors/vector_name/x_in.memh",
    parameter int unsigned MEM_DEPTH                 = 65536,
    parameter int unsigned INPUT_SAMPLES             = 4096,
    // Full-tail zero flush must be long enough for the causal delay and final frame/tail effects.
    // Profiles may override this with the exact vector contract, but the default is conservative.
    parameter int unsigned FLUSH_SAMPLES             = trecap_core_pkg::T_DELAY_D + trecap_core_pkg::T_FFT_L,
    parameter bit          START_ON_RESET_RELEASE    = 1'b0,
    parameter bit          RESTART_ALLOWED_WHILE_DONE = 1'b1,
    parameter bit          REQUIRE_NONZERO_INPUT     = 1'b1
) (
    input  logic                         clk,
    input  logic                         rst_n,
    input  logic                         enable_i,
    input  logic                         start_i,
    input  logic                         clear_i,
    input  logic                         clear_sticky_i,

    // Ready/valid source stream toward source mux or core input. Replay is allowed to stall; this
    // is a correctness source, not a live unthrottled source.
    input  logic                         sample_ready_i,
    output trecap_iface_pkg::trecap_sample_t               sample_o,
    output logic                         sample_valid_o,
    output logic signed [trecap_core_pkg::T_SAMPLE_W-1:0] sample_data_o,
    output logic [63:0]                  sample_idx_o,

    output logic                         active_o,
    output logic                         done_o,
    output logic                         input_phase_o,
    output logic                         flush_phase_o,
    output logic                         start_accept_pulse_o,
    output logic                         start_reject_pulse_o,
    output logic                         output_accept_pulse_o,
    output logic                         last_sample_pulse_o,
    output logic                         done_pulse_o,
    output logic [63:0]                  next_issue_idx_o,
    output logic [63:0]                  output_accept_count_o,
    output logic [63:0]                  configured_input_samples_o,
    output logic [63:0]                  configured_flush_samples_o,
    output logic                         config_error_sticky_o,
    output logic                         mem_range_error_sticky_o,
    output logic                         replay_overrun_sticky_o
);
  import trecap_core_pkg::*;
  import trecap_iface_pkg::*;


    localparam int unsigned MEM_DEPTH_SAFE = (MEM_DEPTH == 0) ? 1 : MEM_DEPTH;
    localparam int unsigned MEM_ADDR_W = (MEM_DEPTH_SAFE <= 1) ? 1 : $clog2(MEM_DEPTH_SAFE);
    localparam longint unsigned TOTAL_SAMPLES_U64 = longint'(INPUT_SAMPLES) + longint'(FLUSH_SAMPLES);

    // Configuration-time initialized M10K ROM. The data port has no reset;
    // read/output validity carries the replay epoch independently of ROM data.
    (* ramstyle = "M10K" *) logic signed [T_SAMPLE_W-1:0] x_mem [0:MEM_DEPTH_SAFE-1];
    logic signed [T_SAMPLE_W-1:0] rom_read_data_q;
    logic read_pending_q;
    logic [63:0] read_sample_idx_q;
    logic read_input_phase_q;
    logic read_response_transfer;

    trecap_sample_t pending_sample_q;
    logic           active_q;
    logic           done_q;
    logic           start_seen_after_reset_q;
    logic [63:0]    next_issue_idx_q;
    logic [63:0]    output_accept_count_q;

    logic           output_accept;
    logic           can_issue;
    logic           start_request;
    logic           start_allowed;
    logic           total_config_ok;
    logic           mem_config_ok;
    logic           input_config_ok;
    logic           issue_input_phase;

    assign output_accept = sample_valid_o && sample_ready_i;
    assign start_request = start_i || (START_ON_RESET_RELEASE && !start_seen_after_reset_q);
    assign total_config_ok = (TOTAL_SAMPLES_U64 != 0);
    assign mem_config_ok = (MEM_DEPTH != 0) && (INPUT_SAMPLES <= MEM_DEPTH_SAFE);
    assign input_config_ok = !REQUIRE_NONZERO_INPUT || (INPUT_SAMPLES != 0);
    assign start_allowed = start_request && !active_q && !pending_sample_q.valid && !read_pending_q &&
                           mem_config_ok && total_config_ok && input_config_ok &&
                           (RESTART_ALLOWED_WHILE_DONE || !done_q);
    // Elastic ROM response and output stages: each outstanding read owns its
    // metadata until the response can move into the output holding register.
    // Pausing enable stops new issues but preserves already issued samples.
    assign read_response_transfer = rst_n && !clear_i && read_pending_q &&
                                    (!pending_sample_q.valid || output_accept);
    assign can_issue = rst_n && !clear_i && active_q && enable_i &&
                       (next_issue_idx_q < TOTAL_SAMPLES_U64) &&
                       (!read_pending_q || read_response_transfer);
    assign issue_input_phase = can_issue && (next_issue_idx_q < INPUT_SAMPLES);

    always_comb begin
        sample_o = pending_sample_q;
        sample_o.valid = rst_n && !clear_i && pending_sample_q.valid;
    end
    assign sample_valid_o = sample_o.valid;
    assign sample_data_o = pending_sample_q.data;
    assign sample_idx_o = pending_sample_q.sample_idx;
    assign active_o = active_q;
    assign done_o = done_q;
    assign input_phase_o = sample_valid_o && (pending_sample_q.sample_idx < INPUT_SAMPLES);
    assign flush_phase_o = sample_valid_o && (pending_sample_q.sample_idx >= INPUT_SAMPLES);
    assign next_issue_idx_o = next_issue_idx_q;
    assign output_accept_count_o = output_accept_count_q;
    assign configured_input_samples_o = 64'(INPUT_SAMPLES);
    assign configured_flush_samples_o = 64'(FLUSH_SAMPLES);

    initial begin : init_replay_mem
        int unsigned idx;
        for (idx = 0; idx < MEM_DEPTH_SAFE; idx++) begin
            x_mem[idx] = '0;
        end
        if (INIT_FILE != "") begin
            $readmemh(INIT_FILE, x_mem);
        end
    end

    always_ff @(posedge clk) begin : p_replay_rom_read
        if (issue_input_phase)
            rom_read_data_q <= x_mem[next_issue_idx_q[MEM_ADDR_W-1:0]];
    end

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            pending_sample_q          <= '0;
            read_pending_q            <= 1'b0;
            read_sample_idx_q         <= '0;
            read_input_phase_q        <= 1'b0;
            active_q                  <= 1'b0;
            done_q                    <= 1'b0;
            start_seen_after_reset_q  <= 1'b0;
            next_issue_idx_q          <= 64'd0;
            output_accept_count_q     <= 64'd0;
            start_accept_pulse_o      <= 1'b0;
            start_reject_pulse_o      <= 1'b0;
            output_accept_pulse_o     <= 1'b0;
            last_sample_pulse_o       <= 1'b0;
            done_pulse_o              <= 1'b0;
            config_error_sticky_o     <= 1'b0;
            mem_range_error_sticky_o  <= 1'b0;
            replay_overrun_sticky_o   <= 1'b0;
        end else begin
            start_accept_pulse_o  <= 1'b0;
            start_reject_pulse_o  <= 1'b0;
            output_accept_pulse_o <= 1'b0;
            last_sample_pulse_o   <= 1'b0;
            done_pulse_o          <= 1'b0;

            if (clear_i) begin
                pending_sample_q          <= '0;
                read_pending_q            <= 1'b0;
                read_sample_idx_q         <= '0;
                read_input_phase_q        <= 1'b0;
                active_q                  <= 1'b0;
                done_q                    <= 1'b0;
                start_seen_after_reset_q  <= 1'b0;
                next_issue_idx_q          <= 64'd0;
                output_accept_count_q     <= 64'd0;
                config_error_sticky_o     <= 1'b0;
                mem_range_error_sticky_o  <= 1'b0;
                replay_overrun_sticky_o   <= 1'b0;
            end else begin
                if (clear_sticky_i) begin
                    config_error_sticky_o    <= 1'b0;
                    mem_range_error_sticky_o <= 1'b0;
                    replay_overrun_sticky_o  <= 1'b0;
                end

                if (!mem_config_ok || !total_config_ok || !input_config_ok) begin
                    config_error_sticky_o <= 1'b1;
                    if (!mem_config_ok) begin
                        mem_range_error_sticky_o <= 1'b1;
                    end
                end

                if (start_request) begin
                    start_seen_after_reset_q <= 1'b1;
                    if (start_allowed) begin
                        start_accept_pulse_o  <= 1'b1;
                        active_q              <= 1'b1;
                        done_q                <= 1'b0;
                        pending_sample_q      <= '0;
                        read_pending_q        <= 1'b0;
                        next_issue_idx_q      <= 64'd0;
                        output_accept_count_q <= 64'd0;
                    end else if (start_i) begin
                        start_reject_pulse_o <= 1'b1;
                        if (active_q || pending_sample_q.valid) begin
                            replay_overrun_sticky_o <= 1'b1;
                        end
                    end
                end

                if (output_accept) begin
                    output_accept_pulse_o <= 1'b1;
                    output_accept_count_q <= output_accept_count_q + 64'd1;
                    if (pending_sample_q.sample_idx == (TOTAL_SAMPLES_U64 - 1)) begin
                        last_sample_pulse_o <= 1'b1;
                    end
                end

                if (output_accept) pending_sample_q.valid <= 1'b0;
                if (read_response_transfer) begin
                    pending_sample_q.valid      <= 1'b1;
                    pending_sample_q.data       <= read_input_phase_q ? rom_read_data_q : '0;
                    pending_sample_q.sample_idx <= read_sample_idx_q;
                    read_pending_q              <= 1'b0;
                end
                if (can_issue) begin
                    read_pending_q     <= 1'b1;
                    read_sample_idx_q  <= next_issue_idx_q;
                    read_input_phase_q <= (next_issue_idx_q < INPUT_SAMPLES);
                    next_issue_idx_q   <= next_issue_idx_q + 64'd1;
                end

                // Completion belongs to acceptance of the final token. A final
                // ROM response in flight is not an empty/completed replay.
                if (active_q && output_accept &&
                    (pending_sample_q.sample_idx == (TOTAL_SAMPLES_U64 - 1))) begin
                    active_q     <= 1'b0;
                    done_q       <= 1'b1;
                    done_pulse_o <= 1'b1;
                end
            end
        end
    end

`ifndef SYNTHESIS
    logic                         sim_prior_stall_q;
    logic signed [T_SAMPLE_W-1:0] sim_prior_sample_data_q;
    logic [63:0]                  sim_prior_sample_idx_q;

    initial begin
        if (MEM_DEPTH == 0) begin
            $fatal(1, "trecap_bram_replay_source: MEM_DEPTH must be nonzero");
        end
        if (INPUT_SAMPLES > MEM_DEPTH) begin
            $fatal(1, "trecap_bram_replay_source: INPUT_SAMPLES exceeds MEM_DEPTH");
        end
        if (TOTAL_SAMPLES_U64 == 0) begin
            $fatal(1, "trecap_bram_replay_source: total replay sample count must be nonzero");
        end
    end

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            sim_prior_stall_q       <= 1'b0;
            sim_prior_sample_data_q <= '0;
            sim_prior_sample_idx_q  <= 64'd0;
        end else if (clear_i) begin
            sim_prior_stall_q       <= 1'b0;
            sim_prior_sample_data_q <= '0;
            sim_prior_sample_idx_q  <= 64'd0;
        end else begin
            if (pending_sample_q.valid && (^pending_sample_q.data === 1'bx)) begin
                $error("trecap_bram_replay_source: output sample data is X while valid");
            end
            if (pending_sample_q.valid && (^pending_sample_q.sample_idx === 1'bx)) begin
                $error("trecap_bram_replay_source: output sample_idx is X while valid");
            end
            if (sim_prior_stall_q &&
                (!pending_sample_q.valid ||
                 (pending_sample_q.data !== sim_prior_sample_data_q) ||
                 (pending_sample_q.sample_idx !== sim_prior_sample_idx_q))) begin
                $error("trecap_bram_replay_source: output payload changed while stalled");
            end

            sim_prior_stall_q       <= pending_sample_q.valid && !sample_ready_i;
            sim_prior_sample_data_q <= pending_sample_q.data;
            sim_prior_sample_idx_q  <= pending_sample_q.sample_idx;
        end
    end
`endif

endmodule : trecap_bram_replay_source

`default_nettype wire
