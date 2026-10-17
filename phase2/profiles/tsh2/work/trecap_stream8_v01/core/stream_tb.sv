`timescale 1ns/1ps
module stream_tb;
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
    integer full_cycles=0,input_gaps=0,export_stalls=0,y_stalls=0,discontinuities=0;
    integer inventory,tap_file,parsed,mode,expected_bytes;
    reg [31:0] rng=32'h62731529;
    reg y_stalled=0,wire_stalled=0,pcm_took=0;
    reg [11:0] held_y;
    reg [63:0] held_y_idx;
    reg [7:0] held_byte;
    string outdir,fixture_inventory,x_path,y_path,wire_path;
    task require(input logic ok,input string why);
        begin if(ok!==1'b1)$fatal(1,"phase%0d cycle%0d %s",phase,cycles,why);end
    endtask
    task tick;begin @(negedge clk);end endtask
    always @(posedge clk) begin
        cycles=cycles+1;if(cycles>3000000)$fatal(1,"global timeout");
        pcm_took=pcm_valid&&pcm_ready;
        if(rst_n && phase>=0 && !clear) begin
            epoch_cycles=epoch_cycles+1;
            require(!(completion_fault||build_fault||protocol_fault||metric_fault||saturation_fault||
                start_reject||export_overflow||export_protocol||overflow!=0||dropped!=0),"core/export fault");
            require(queued<=1 && frames<=emitted+1,"one-frame credit exceeded");
            if(pcm_valid&&pcm_ready)sent=sent+1;
            if(fifo_level==256)full_cycles=full_cycles+1;
            if(!pcm_valid&&sent<1024)input_gaps=input_gaps+1;
            if(discontinuity)discontinuities=discontinuities+1;
            if(source_valid&&source_ready)begin
                require(source_idx==source_seen,"source index gap");
                require(source_data===((source_seen<1024)?x_gold[source_seen]:12'd0),"input/flush sample differs");
                source_seen=source_seen+1;
            end
            if(y_stalled)require(y_valid&&y_data===held_y&&y_idx===held_y_idx,"Y changed while stalled");
            if(wire_stalled)require(export_valid&&export_data===held_byte,"export changed while stalled");
            y_stalled=y_valid&&!y_ready;held_y=y_data;held_y_idx=y_idx;
            wire_stalled=export_valid&&!export_ready;held_byte=export_data;
            if(y_stalled)y_stalls=y_stalls+1;
            if(wire_stalled)export_stalls=export_stalls+1;
            if(y_valid&&y_ready)begin
                require(y_seen<1536&&y_idx==y_seen&&y_data===y_gold[y_seen],"Y differs from frozen reference");
                y_seen=y_seen+1;
            end
            if(tap_valid)begin
                $fwrite(tap_file,"%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d\n",phase,tap_frame,tap_bin,
                    $signed(tap_re),$signed(tap_im),tap_mag,tap_pre_mask,tap_mask,tap_eligible,tap_threshold);
                taps_seen=taps_seen+1;
            end
            if(export_valid&&export_ready)begin
                require(wire_seen<expected_bytes&&export_data===wire_gold[wire_seen],"export byte differs from frozen reference");
                wire_seen=wire_seen+1;
            end
        end else begin y_stalled=0;wire_stalled=0;end
    end
    // A held valid input is never withdrawn. Chunk-like pauses and each output
    // consumer's backpressure operate independently without resetting the core.
    always @(negedge clk) begin
        rng={rng[30:0],rng[31]^rng[21]^rng[1]^rng[0]};
        if(phase>=0 && !clear && !start)begin
            y_ready=(epoch_cycles%7000>=1000)&&rng[1];
            export_ready=(epoch_cycles%30000>=10000)&&rng[2];
            if(!pcm_valid || pcm_took)begin
                pcm_valid=(sent<1024)&&(epoch_cycles%1300>=220)&&(rng[3:0]!=0);
                pcm_data=(sent<1024)?x_gold[sent]:0;
            end
        end else begin pcm_valid=0;y_ready=0;export_ready=0;end
    end
    initial begin
        if(!$value$plusargs("OUT=%s",outdir)||!$value$plusargs("CASES=%s",fixture_inventory))$fatal(1,"OUT/CASES required");
        inventory=$fopen(fixture_inventory,"r");tap_file=$fopen({outdir,"/taps.csv"},"w");
        $fwrite(tap_file,"phase,frame_idx,bin_idx,real,imag,mag2,pre_mask,mask,eligible,threshold\n");
        repeat(3)tick();rst_n=1;
        for(integer p=0;p<12;p=p+1)begin
            phase=-1;clear=1;tick();clear=0;
            parsed=$fscanf(inventory,"%s %s %s %h %d %d\n",x_path,y_path,wire_path,threshold,mode,expected_bytes);
            require(parsed==6,"inventory");sparse=mode;
            $readmemh(x_path,x_gold);$readmemh(y_path,y_gold);$readmemh(wire_path,wire_gold,0,expected_bytes-1);
            while(top_busy)tick();
            sent=0;source_seen=0;y_seen=0;taps_seen=0;wire_seen=0;epoch_cycles=0;discontinuities=0;
            phase=p;start=1;tick();start=0;
            while(!top_done||emitted!=9)begin tick();if(epoch_cycles>230000)$fatal(1,"epoch timeout sent=%0d source=%0d y=%0d frames=%0d emitted=%0d",sent,source_seen,y_seen,frames,emitted);end
            require(sent==1024&&pcm_accepted==1024&&fifo_level==0&&source_seen==1536&&
                y_seen==1536&&wire_seen==expected_bytes&&taps_seen==1161&&frames==9&&accepted==9,"exact completion counts");
            require(discontinuities==1,"chunk boundary reset/discontinuity");
            $display("EPOCH phase=%0d cycles=%0d bytes=%0d",p,epoch_cycles,wire_seen);
        end
        phase=-1;
        require(full_cycles>0&&input_gaps>0&&export_stalls>0&&y_stalls>0,"backpressure coverage");
        $display("PASS stream epochs=12 fifo_full_cycles=%0d input_gap_cycles=%0d export_stall_cycles=%0d y_stall_cycles=%0d cycles=%0d",full_cycles,input_gaps,export_stalls,y_stalls,cycles);
        $fclose(inventory);$fclose(tap_file);$finish;
    end
endmodule
