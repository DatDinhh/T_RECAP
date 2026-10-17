`timescale 1ns/1ps
module tsh2_top;
    import uvm_pkg::*;
    import tsh2_uvm_pkg::*;
    logic clk=0; always #5 clk=~clk;
    tsh2_if vif(clk);
    trecap_pcm_stream_top #(.INPUT_SAMPLES(1024)) dut(
        .clk(vif.clk),.rst_n(vif.rst_n),.enable_i(1'b1),.clear_i(vif.clear),.clear_sticky_i(1'b0),
        .clear_metrics_i(1'b0),.replay_start_i(vif.start),.thr2_i(vif.threshold),
        .pcm_valid_i(vif.pcm_valid),.pcm_ready_o(vif.pcm_ready),.pcm_data_i(vif.pcm_data),
        .pcm_accepted_count_o(vif.pcm_accepted),.pcm_fifo_level_o(vif.fifo_level),.export_emitted_frames_i(vif.emitted),
        .y_valid_o(vif.y_valid),.y_ready_i(vif.y_ready),.y_data_o(vif.y_data),.y_sample_idx_o(vif.y_idx),
        .source_sample_valid_o(vif.source_valid),.source_sample_ready_o(vif.source_ready),
        .source_sample_data_o(vif.source_data),.source_sample_idx_o(vif.source_idx),
        .source_discontinuity_pulse_o(vif.discontinuity),.core_frame_count_o(vif.frames),
        .tap_bin_valid_o(vif.tap_valid),.tap_bin_frame_idx_o(vif.tap_frame),.tap_bin_idx_o(vif.tap_bin),
        .tap_bin_re_o(vif.tap_re),.tap_bin_im_o(vif.tap_im),.tap_bin_mag2_o(vif.tap_mag),
        .tap_bin_pre_mask_o(vif.tap_pre_mask),.tap_bin_mask_o(vif.tap_mask),.tap_bin_eligible_o(vif.tap_eligible),
        .tap_bin_last_o(vif.tap_last),.tap_bin_thr2_o(vif.tap_threshold),
        .core_metric_overflow_sticky_o(vif.metric_fault),.core_saturation_sticky_o(vif.saturation_fault),
        .core_protocol_error_sticky_o(vif.protocol_fault),.replay_start_accept_pulse_o(vif.start_accept),
        .replay_start_reject_pulse_o(vif.start_reject),.top_busy_o(vif.top_busy),.top_done_o(vif.top_done),
        .top_completion_error_sticky_o(vif.completion_fault),.top_overflow_flags_o(vif.overflow),
        .build_contract_error_o(vif.build_fault),
        // Unused observation outputs are deliberately open.
        .y_sample_o(), .source_sample_o(), .tap_sample_o(), .tap_frame_o(), .frame_boundary_pulse_o(), .core_alive_o(), .core_busy_o(), .core_sample_count_o(), .core_error_sample_count_o(), .core_sum_abs_err_lo_o(), .core_sum_sq_err_lo_o(), .core_max_abs_err_o(), .core_overflow_flags_o(), .replay_active_o(), .replay_done_o(), .replay_input_phase_o(), .replay_flush_phase_o(), .replay_analysis_flush_phase_o(), .replay_tail_drain_phase_o(), .replay_output_accept_pulse_o(), .replay_last_sample_pulse_o(), .replay_done_pulse_o(), .replay_next_issue_idx_o(), .replay_output_accept_count_o(), .replay_configured_input_samples_o(), .replay_configured_flush_samples_o(), .tail_drain_active_o(), .tail_drain_accept_pulse_o(), .tail_drain_done_pulse_o(), .wola_output_count_o(), .replay_config_error_sticky_o(), .replay_mem_range_error_sticky_o(), .replay_overrun_sticky_o(), .top_alive_o(), .top_done_pulse_o(), .top_output_accept_count_o(), .top_expected_output_count_o()
    );
    trecap_spectral_exporter #(.QUEUE_FRAMES(4)) exporter(
        .clk(vif.clk),.rst_n(vif.rst_n),.clear_i(vif.clear || vif.discontinuity),.tap_valid_i(vif.tap_valid),
        .tap_frame_id_i(vif.tap_frame),.tap_bin_idx_i(vif.tap_bin),.tap_mag2_i(vif.tap_mag),
        .tap_mask_i(vif.tap_mask),.tap_eligible_i(vif.tap_eligible),.tap_last_i(vif.tap_last),
        .tap_thr2_i({8'd0,vif.tap_threshold}),.sparse_mode_i(vif.sparse),
        .out_valid_o(vif.export_valid),.out_ready_i(vif.export_ready),.out_data_o(vif.export_data),
        .accepted_frames_o(vif.accepted),.emitted_frames_o(vif.emitted),.dropped_frames_o(vif.dropped),
        .overflow_sticky_o(vif.export_overflow),.protocol_error_sticky_o(vif.export_protocol),
        .queued_frames_o(vif.queued),.busy_o(vif.export_busy),
        // Unused observation outputs are deliberately open.
        .out_last_o(), .out_bytes_o(), .out_frame_id_o(), .out_thr2_o(), .out_sparse_o()
    );
    assign vif.metric_count=dut.u_core.u_delay_error_metrics.accepted_y_count_o;
    assign vif.sum_abs=dut.u_core.core_sum_abs_err_lo_o;
    assign vif.sum_sq=dut.u_core.core_sum_sq_err_lo_o;
    assign vif.max_abs=dut.u_core.core_max_abs_err_o;
    initial begin
      uvm_config_db#(virtual tsh2_if)::set(null,"*","vif",vif);
      run_test("tsh2_test");
    end
    initial begin #20000000; $fatal(1,"TOP_WATCHDOG"); end
endmodule
