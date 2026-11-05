// SPDX-License-Identifier: MIT
// Finite host stream with bounded synchronous PCM FIFO and exact zero extension.
// Host pauses do not reset the sample index, analysis overlap, or WOLA state.
`default_nettype none
module trecap_pcm_stream_source #(
    parameter int unsigned FIFO_DEPTH=256,
    parameter int unsigned INPUT_SAMPLES=384000,
    parameter int unsigned FLUSH_SAMPLES=512,
    parameter bit START_ON_RESET_RELEASE=1'b0,
    parameter bit RESTART_ALLOWED_WHILE_DONE=1'b1
)(
    input logic clk, rst_n, enable_i, start_i, clear_i, clear_sticky_i,
    input logic pcm_valid_i,
    output logic pcm_ready_o,
    input logic signed [11:0] pcm_data_i,
    output logic [63:0] pcm_accepted_count_o,
    output logic [31:0] pcm_fifo_level_o,
    input logic sample_ready_i,
    output trecap_iface_pkg::trecap_sample_t sample_o,
    output logic sample_valid_o,
    output logic signed [trecap_core_pkg::T_SAMPLE_W-1:0] sample_data_o,
    output logic [63:0] sample_idx_o,
    output logic active_o, done_o, input_phase_o, flush_phase_o,
    output logic start_accept_pulse_o, start_reject_pulse_o,
    output logic output_accept_pulse_o, last_sample_pulse_o, done_pulse_o,
    output logic [63:0] next_issue_idx_o, output_accept_count_o,
    output logic [63:0] configured_input_samples_o, configured_flush_samples_o,
    output logic config_error_sticky_o, mem_range_error_sticky_o, replay_overrun_sticky_o
);
    import trecap_core_pkg::*;
    import trecap_iface_pkg::*;
    localparam int AW=(FIFO_DEPTH<=1)?1:$clog2(FIFO_DEPTH);
    localparam longint unsigned TOTAL=64'(INPUT_SAMPLES)+64'(FLUSH_SAMPLES);
    localparam bit CONFIG_OK=(FIFO_DEPTH>=2) && ((FIFO_DEPTH&(FIFO_DEPTH-1))==0) &&
        (INPUT_SAMPLES>0) && (TOTAL>INPUT_SAMPLES) && (T_SAMPLE_W==12);
    (* ramstyle="M10K" *) logic signed [11:0] pcm_mem[0:FIFO_DEPTH-1];
    logic [AW-1:0] wr_q,rd_q;
    logic [31:0] level_q;
    logic signed [11:0] read_data_q;
    logic read_pending_q,read_input_q;
    logic [63:0] read_idx_q;
    trecap_sample_t pending_q;
    logic active_q,done_q,started_q;
    logic [63:0] issue_q,accepted_q,host_accepted_q;
    wire output_accept=sample_valid_o && sample_ready_i;
    wire response_transfer=rst_n && !clear_i && read_pending_q &&
        (!pending_q.valid || output_accept);
    wire start_request=start_i || (START_ON_RESET_RELEASE && !started_q);
    wire start_allowed=CONFIG_OK && !active_q && !pending_q.valid && !read_pending_q &&
        (RESTART_ALLOWED_WHILE_DONE || !done_q);
    wire can_issue=rst_n && !clear_i && active_q && enable_i && issue_q<TOTAL &&
        (!read_pending_q || response_transfer) && (issue_q>=INPUT_SAMPLES || level_q!=0);
    wire input_issue=can_issue && issue_q<INPUT_SAMPLES;
    wire pcm_take=pcm_valid_i && pcm_ready_o;
    assign pcm_ready_o=rst_n && !clear_i && active_q && host_accepted_q<INPUT_SAMPLES &&
        (level_q<FIFO_DEPTH);
    assign pcm_accepted_count_o=host_accepted_q;
    assign pcm_fifo_level_o=level_q;
    always_comb begin
        sample_o=pending_q;
        sample_o.valid=rst_n && !clear_i && pending_q.valid;
    end
    assign sample_valid_o=sample_o.valid;
    assign sample_data_o=pending_q.data;
    assign sample_idx_o=pending_q.sample_idx;
    assign active_o=active_q;
    assign done_o=done_q;
    assign input_phase_o=sample_valid_o && pending_q.sample_idx<INPUT_SAMPLES;
    assign flush_phase_o=sample_valid_o && pending_q.sample_idx>=INPUT_SAMPLES;
    assign next_issue_idx_o=issue_q;
    assign output_accept_count_o=accepted_q;
    assign configured_input_samples_o=64'(INPUT_SAMPLES);
    assign configured_flush_samples_o=64'(FLUSH_SAMPLES);
    // Ownership is reset; data RAM and its registered read port are not reset.
    always_ff @(posedge clk) begin
        if(pcm_take) pcm_mem[wr_q]<=pcm_data_i;
        if(input_issue) read_data_q<=pcm_mem[rd_q];
    end
    always_ff @(posedge clk or negedge rst_n) begin
        if(!rst_n) begin
            wr_q<=0;rd_q<=0;level_q<=0;read_pending_q<=0;read_input_q<=0;read_idx_q<=0;
            pending_q<='0;active_q<=0;done_q<=0;started_q<=0;issue_q<=0;accepted_q<=0;
            host_accepted_q<=0;start_accept_pulse_o<=0;start_reject_pulse_o<=0;
            output_accept_pulse_o<=0;last_sample_pulse_o<=0;done_pulse_o<=0;
            config_error_sticky_o<=0;mem_range_error_sticky_o<=0;replay_overrun_sticky_o<=0;
        end else begin
            start_accept_pulse_o<=0;start_reject_pulse_o<=0;
            output_accept_pulse_o<=0;last_sample_pulse_o<=0;done_pulse_o<=0;
            if(clear_i) begin
                wr_q<=0;rd_q<=0;level_q<=0;read_pending_q<=0;read_input_q<=0;read_idx_q<=0;
                pending_q<='0;active_q<=0;done_q<=0;started_q<=0;issue_q<=0;accepted_q<=0;
                host_accepted_q<=0;config_error_sticky_o<=0;mem_range_error_sticky_o<=0;
                replay_overrun_sticky_o<=0;
            end else begin
                if(clear_sticky_i) begin
                    config_error_sticky_o<=0;mem_range_error_sticky_o<=0;replay_overrun_sticky_o<=0;
                end
                if(!CONFIG_OK) begin config_error_sticky_o<=1;mem_range_error_sticky_o<=1;end
                if(start_request) begin
                    started_q<=1;
                    if(start_allowed) begin
                        active_q<=1;done_q<=0;start_accept_pulse_o<=1;
                        wr_q<=0;rd_q<=0;level_q<=0;issue_q<=0;accepted_q<=0;host_accepted_q<=0;
                    end else if(start_i) begin
                        start_reject_pulse_o<=1;replay_overrun_sticky_o<=1;
                    end
                end
                if(pcm_take) begin wr_q<=wr_q+1'b1;host_accepted_q<=host_accepted_q+1'b1;end
                if(input_issue) rd_q<=rd_q+1'b1;
                case({pcm_take,input_issue})
                    2'b10:level_q<=level_q+1'b1;
                    2'b01:level_q<=level_q-1'b1;
                    default:begin end
                endcase
                if(output_accept) begin
                    pending_q.valid<=0;accepted_q<=accepted_q+1'b1;output_accept_pulse_o<=1;
                    if(pending_q.sample_idx==TOTAL-1) begin
                        active_q<=0;done_q<=1;last_sample_pulse_o<=1;done_pulse_o<=1;
                    end
                end
                if(response_transfer) begin
                    pending_q.valid<=1;pending_q.data<=read_input_q ? read_data_q : '0;
                    pending_q.sample_idx<=read_idx_q;read_pending_q<=0;
                end
                if(can_issue) begin
                    read_pending_q<=1;read_input_q<=issue_q<INPUT_SAMPLES;
                    read_idx_q<=issue_q;issue_q<=issue_q+1'b1;
                end
            end
        end
    end
endmodule
`default_nettype wire
