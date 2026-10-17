`timescale 1ns/1ps
module dv_stream_tb;
    reg clk=0;always #5 clk=~clk;
    reg rst_n=0,clear=0,start=0,pcm_valid=0,y_ready=0,export_ready=0;
    reg signed [11:0] pcm_data=0;
    reg [55:0] threshold=0;
    reg sparse=0;
    wire pcm_ready,y_valid,source_valid,source_ready,top_busy,top_done,start_accept,start_reject;
    wire signed [11:0] y_data,source_data;
    wire [63:0] pcm_accepted,source_idx,y_idx,frames,emitted,accepted,dropped;
    wire [31:0] fifo_level,overflow,queued;
    wire completion_fault,build_fault,protocol_fault,metric_fault,saturation_fault;
    wire discontinuity,tap_valid,tap_mask,tap_eligible,tap_last,tap_pre_mask;
    wire [7:0] tap_bin,export_data;
    wire [63:0] tap_frame;
    wire signed [27:0] tap_re,tap_im;
    wire [55:0] tap_mag,tap_threshold;
    wire export_valid,export_busy,export_overflow,export_protocol;
    trecap_pcm_stream_top #(.INPUT_SAMPLES(1024)) dut(
        .clk(clk),.rst_n(rst_n),.enable_i(1'b1),.clear_i(clear),.clear_sticky_i(1'b0),
        .clear_metrics_i(1'b0),.replay_start_i(start),.thr2_i(threshold),
        .pcm_valid_i(pcm_valid),.pcm_ready_o(pcm_ready),.pcm_data_i(pcm_data),
        .pcm_accepted_count_o(pcm_accepted),.pcm_fifo_level_o(fifo_level),.export_emitted_frames_i(emitted),
        .y_valid_o(y_valid),.y_ready_i(y_ready),.y_data_o(y_data),.y_sample_idx_o(y_idx),
        .source_sample_valid_o(source_valid),.source_sample_ready_o(source_ready),
        .source_sample_data_o(source_data),.source_sample_idx_o(source_idx),
        .source_discontinuity_pulse_o(discontinuity),.core_frame_count_o(frames),
        .tap_bin_valid_o(tap_valid),.tap_bin_frame_idx_o(tap_frame),.tap_bin_idx_o(tap_bin),
        .tap_bin_re_o(tap_re),.tap_bin_im_o(tap_im),.tap_bin_mag2_o(tap_mag),
        .tap_bin_pre_mask_o(tap_pre_mask),.tap_bin_mask_o(tap_mask),.tap_bin_eligible_o(tap_eligible),
        .tap_bin_last_o(tap_last),.tap_bin_thr2_o(tap_threshold),
        .core_metric_overflow_sticky_o(metric_fault),.core_saturation_sticky_o(saturation_fault),
        .core_protocol_error_sticky_o(protocol_fault),.replay_start_accept_pulse_o(start_accept),
        .replay_start_reject_pulse_o(start_reject),.top_busy_o(top_busy),.top_done_o(top_done),
        .top_completion_error_sticky_o(completion_fault),.top_overflow_flags_o(overflow),
        .build_contract_error_o(build_fault)
    );
    trecap_spectral_exporter #(.QUEUE_FRAMES(4)) exporter(
        .clk(clk),.rst_n(rst_n),.clear_i(clear || discontinuity),.tap_valid_i(tap_valid),
        .tap_frame_id_i(tap_frame),.tap_bin_idx_i(tap_bin),.tap_mag2_i(tap_mag),
        .tap_mask_i(tap_mask),.tap_eligible_i(tap_eligible),.tap_last_i(tap_last),
        .tap_thr2_i({8'd0,tap_threshold}),.sparse_mode_i(sparse),
        .out_valid_o(export_valid),.out_ready_i(export_ready),.out_data_o(export_data),
        .accepted_frames_o(accepted),.emitted_frames_o(emitted),.dropped_frames_o(dropped),
        .overflow_sticky_o(export_overflow),.protocol_error_sticky_o(export_protocol),
        .queued_frames_o(queued),.busy_o(export_busy)
    );
    reg [11:0] x_gold[0:1023],y_gold[0:1535];
    reg [7:0] wire_gold[0:16383];
    integer phase=-1,cycles=0,epoch_cycles=0,sent=0,source_seen=0,y_seen=0,taps_seen=0,wire_seen=0;
    integer full_cycles=0,empty_cycles=0,one_cycles=0,input_gaps=0,export_stalls=0,y_stalls=0,discontinuities=0;
    integer simultaneous_push_pop=0,write_wraps=0,read_wraps=0,final_hold=0,hold_target=32;
    integer inventory,tap_file,y_file,source_file,packet_file,coverage_file,parsed,mode,expected_bytes,case_count=0;
    reg [31:0] rng=1,seed=1,schedule_hash=32'h811c9dc5;
    reg y_stalled=0,wire_stalled=0,pcm_took=0,inject_bad_y=0;
    integer checker_done=0;
    reg [11:0] held_y;reg [63:0] held_y_idx;reg [7:0] held_byte;
    string outdir,fixture_inventory,x_path,y_path,wire_path;
    task require(input logic ok,input string why);
        begin if(ok!==1'b1)$fatal(1,"CHECK_FAIL phase=%0d cycle=%0d %s",phase,cycles,why);end
    endtask
    // Driver at falling edge +1ns; coordinator at falling edge +2ns;
    // checker samples accepted transfers on rising edge before NBA updates.
    task tick;begin @(negedge clk);#2;end endtask
    always @(posedge clk) begin
        cycles++;if(cycles>2000000)$fatal(1,"SIM_WATCHDOG");
        pcm_took=pcm_valid&&pcm_ready;
        if(rst_n && phase>=0 && !clear) begin
            epoch_cycles++;
            require((^{pcm_valid,pcm_ready,y_valid,y_ready,source_valid,source_ready,export_valid,export_ready,top_busy,top_done,tap_valid})!==1'bx,"UNKNOWN_CONTROL");
            require(!(completion_fault||build_fault||protocol_fault||metric_fault||saturation_fault||start_reject||export_overflow||export_protocol||overflow!=0||dropped!=0),"DUT_FAULT");
            require(queued<=1 && frames<=emitted+1,"FRAME_CREDIT");
            require(!top_done || y_seen==1536,"EARLY_COMPLETION");
            schedule_hash=(schedule_hash ^ {24'd0,pcm_valid,pcm_ready,y_valid,y_ready,source_valid,source_ready,export_valid,export_ready})*32'd16777619;
            if(pcm_took)sent++;
            if(fifo_level==256)full_cycles++;
            if(fifo_level==0)empty_cycles++;
            if(fifo_level==1)one_cycles++;
            if(!pcm_valid&&sent<1024)input_gaps++;
            if(discontinuity)discontinuities++;
            if(pcm_took&&dut.u_bram_replay_source.input_issue)simultaneous_push_pop++;
            if(pcm_took&&dut.u_bram_replay_source.wr_q==255)write_wraps++;
            if(dut.u_bram_replay_source.input_issue&&dut.u_bram_replay_source.rd_q==255)read_wraps++;
            if(source_valid&&source_ready)begin
                require(source_idx==source_seen,"SOURCE_INDEX");
                require(source_data===((source_seen<1024)?x_gold[source_seen]:12'd0),"SOURCE_DATA");
                $fwrite(source_file,"%0d,%0d,%0d\n",phase,source_idx,$signed(source_data));source_seen++;
            end
            if(y_stalled)require(y_valid&&y_data===held_y&&y_idx===held_y_idx,"Y_STABILITY");
            if(wire_stalled)require(export_valid&&export_data===held_byte,"PACKET_STABILITY");
            y_stalled=y_valid&&!y_ready;held_y=y_data;held_y_idx=y_idx;
            wire_stalled=export_valid&&!export_ready;held_byte=export_data;
            if(y_stalled)y_stalls++;
            if(wire_stalled)export_stalls++;
            if(y_stalled&&y_idx==1535)begin require(top_busy&&!top_done,"FINAL_Y_COMPLETION");final_hold++;end
            if(y_valid&&y_ready)begin
                require(y_seen<1536&&y_idx==y_seen,"Y_INDEX");
                require(y_data===y_gold[y_seen],"Y_GOLD_MISMATCH");
                $fwrite(y_file,"%0d,%0d,%0d\n",phase,y_idx,$signed(y_data));y_seen++;
            end
            if(tap_valid)begin
                require((^{tap_frame,tap_bin,tap_re,tap_im,tap_mag,tap_pre_mask,tap_mask,tap_eligible,tap_threshold})!==1'bx,"UNKNOWN_TAP");
                $fwrite(tap_file,"%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d\n",phase,tap_frame,tap_bin,$signed(tap_re),$signed(tap_im),tap_mag,tap_pre_mask,tap_mask,tap_eligible,tap_threshold);taps_seen++;
            end
            if(export_valid&&export_ready)begin
                require(wire_seen<expected_bytes&&export_data===wire_gold[wire_seen],"PACKET_GOLD_MISMATCH");
                $fwrite(packet_file,"%c",export_data);wire_seen++;
            end
        end else begin y_stalled=0;wire_stalled=0;end
    end
    // Explicit32-bit recurrence is reproducible across simulator implementations.
    // A valid PCM token stays asserted with unchanged data until accepted.
    always @(negedge clk)begin
        #1;rng={rng[30:0],rng[31]^rng[21]^rng[1]^rng[0]};
        if(phase>=0&&!clear&&!start)begin
            y_ready=(y_seen==1535)?(final_hold>=hold_target):((epoch_cycles%7000>=1000)&&rng[1]);
            export_ready=(epoch_cycles%30000>=10000)&&rng[2];
            if(!pcm_valid||pcm_took)begin
                pcm_valid=(sent<1024)&&(epoch_cycles%1300>=220)&&(rng[3:0]!=0);
                pcm_data=(sent<1024)?x_gold[sent]:0;
            end
        end else begin pcm_valid=0;y_ready=0;export_ready=0;end
    end
    initial begin
        if(!$value$plusargs("OUT=%s",outdir)||!$value$plusargs("CASES=%s",fixture_inventory)||!$value$plusargs("COUNT=%d",case_count)||!$value$plusargs("SEED=%d",seed))$fatal(1,"SETUP_PLUSARGS");
        require(seed!=0&&case_count>0&&case_count<=4,"SETUP_PARAMETERS");rng=seed;hold_target=32+(seed%32);inject_bad_y=$test$plusargs("INJECT_BAD_Y");
        inventory=$fopen(fixture_inventory,"r");tap_file=$fopen({outdir,"/taps.csv"},"w");y_file=$fopen({outdir,"/y.csv"},"w");source_file=$fopen({outdir,"/source.csv"},"w");coverage_file=$fopen({outdir,"/coverage.csv"},"w");
        require(inventory&&tap_file&&y_file&&source_file&&coverage_file,"SETUP_FILES");
        $fwrite(tap_file,"phase,frame_idx,bin_idx,real,imag,mag2,pre_mask,mask,eligible,threshold\n");$fwrite(y_file,"phase,index,value\n");$fwrite(source_file,"phase,index,value\n");
        $fwrite(coverage_file,"phase,seed,cycles,input_tokens,source_tokens,y_tokens,tap_rows,packet_bytes,fifo_empty_cycles,fifo_one_cycles,fifo_full_cycles,input_gap_cycles,y_stall_cycles,export_stall_cycles,simultaneous_push_pop,write_wraps,read_wraps,final_y_hold_cycles,discontinuities,schedule_hash,metric_count,sum_abs,sum_sq,max_abs\n");
        repeat(3)tick();rst_n=1;
        for(integer p=0;p<case_count;p++)begin
            phase=-1;clear=1;tick();clear=0;
            parsed=$fscanf(inventory,"%s %s %s %h %d %d\n",x_path,y_path,wire_path,threshold,mode,expected_bytes);require(parsed==6,"SETUP_INVENTORY");sparse=mode;
            $readmemh(x_path,x_gold);$readmemh(y_path,y_gold);$readmemh(wire_path,wire_gold,0,expected_bytes-1);
            if(inject_bad_y)y_gold[0]=y_gold[0]^12'd1;
            packet_file=$fopen($sformatf("%s/packet_%0d.bin",outdir,p),"wb");require(packet_file!=0,"PACKET_FILE");
            while(top_busy)tick();
            sent=0;source_seen=0;y_seen=0;taps_seen=0;wire_seen=0;epoch_cycles=0;discontinuities=0;final_hold=0;
            full_cycles=0;empty_cycles=0;one_cycles=0;input_gaps=0;export_stalls=0;y_stalls=0;simultaneous_push_pop=0;write_wraps=0;read_wraps=0;schedule_hash=32'h811c9dc5;
            phase=p;start=1;tick();start=0;
            while(!top_done||emitted!=9)begin tick();if(epoch_cycles>300000)$fatal(1,"EPOCH_WATCHDOG");end
            require(sent==1024&&pcm_accepted==1024&&fifo_level==0&&source_seen==1536&&y_seen==1536&&wire_seen==expected_bytes&&taps_seen==1161&&frames==9&&accepted==9,"COMPLETION_COUNTS");
            require(discontinuities==1&&final_hold==hold_target,"EPOCH_BOUNDARY_COVERAGE");
            require(full_cycles>0&&empty_cycles>0&&one_cycles>0&&input_gaps>0&&export_stalls>0&&y_stalls>0&&simultaneous_push_pop>0&&write_wraps==4&&read_wraps==4,"REQUIRED_EVENT_BINS");
            $fwrite(coverage_file,"%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d\n",phase,seed,epoch_cycles,sent,source_seen,y_seen,taps_seen,wire_seen,empty_cycles,one_cycles,full_cycles,input_gaps,y_stalls,export_stalls,simultaneous_push_pop,write_wraps,read_wraps,final_hold,discontinuities,schedule_hash,dut.u_core.u_delay_error_metrics.accepted_y_count_o,dut.u_core.core_sum_abs_err_lo_o,dut.u_core.core_sum_sq_err_lo_o,dut.u_core.core_max_abs_err_o);
            $fclose(packet_file);$display("CASE_COMPLETE phase=%0d seed=%0d cycles=%0d",phase,seed,epoch_cycles);
        end
        phase=-1;$fclose(inventory);$fclose(tap_file);$fclose(y_file);$fclose(source_file);$fclose(coverage_file);
        checker_done=1;$display("DV_COMPLETE cases=%0d seed=%0d",case_count,seed);#1;$finish;
    end
endmodule
