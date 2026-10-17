`timescale 1ns/1ps
interface tsh2_if(input logic clk);
    logic rst_n=0,clear=0,start=0,pcm_valid=0,y_ready=0,export_ready=0;
    logic signed [11:0] pcm_data=0;
    logic [55:0] threshold=0;
    logic sparse=0;
    logic pcm_ready,y_valid,source_valid,source_ready,top_busy,top_done,start_accept,start_reject;
    logic signed [11:0] y_data,source_data;
    logic [63:0] pcm_accepted,source_idx,y_idx,frames,emitted,accepted,dropped;
    logic [31:0] fifo_level,overflow,queued;
    logic completion_fault,build_fault,protocol_fault,metric_fault,saturation_fault;
    logic discontinuity,tap_valid,tap_mask,tap_eligible,tap_last,tap_pre_mask;
    logic [7:0] tap_bin,export_data;
    logic [63:0] tap_frame;
    logic signed [27:0] tap_re,tap_im;
    logic [55:0] tap_mag,tap_threshold;
    logic export_valid,export_busy,export_overflow,export_protocol;
    integer case_id=0, epoch_id=0;
    integer checker_done=0;
    logic [63:0] metric_count, sum_abs, sum_sq;
    logic [31:0] max_abs;
endinterface
