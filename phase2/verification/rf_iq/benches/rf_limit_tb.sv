`timescale 1ns/1ps
`default_nettype none
module rf_limit_tb;
    reg clk=0;
    always #5 clk=~clk;
    reg rst_n=0,clear_i=0,start_valid_i=0,iq_valid_i=0,sample_ready_i=0;
    reg [31:0] pair_count_i=0;
    reg [1:0] gain_shift_i=0;
    reg [7:0] iq_i_i=0,iq_q_i=0;
    wire start_ready_o,iq_ready_o,sample_valid_o,sample_last_o,sample_clipped_o;
    wire busy_o,done_o,config_error_o,clip_sticky_o;
    wire signed [11:0] sample_data_o;
    wire [31:0] sample_index_o,input_count_o,output_count_o,clip_count_o;
    trecap_rf_iq_adapter dut(.*);
    reg [15:0] input_mem [0:95999];
    reg [11:0] expected_mem [0:383999];
    reg clip_mem [0:383999];
    integer fd,rc,n,g,expected_clips,cases=0,total_samples=0;
    integer stalls=0,source_gaps=0,long_stalls=0,aborts=0;
    integer seed=1,negative=0;
    integer checker_done=0;
    string name,path,wave;
    reg [31:0] rng;
    function automatic [31:0] advance_rng(input [31:0] v);
        reg [31:0] x;
        begin x=v^(v<<13);x=x^(x>>17);advance_rng=x^(x<<5);end
    endfunction

    task automatic clear_all;
        begin
            @(negedge clk); clear_i=1; start_valid_i=0; iq_valid_i=0; sample_ready_i=0;
            #1;
            if(start_ready_o || iq_ready_o || sample_valid_o || busy_o) $fatal(1,"CLEAR_GATING");
            @(posedge clk);#1;
            if(input_count_o || output_count_o || clip_count_o || clip_sticky_o || config_error_o || done_o)
                $fatal(1,"CLEAR_COUNTERS");
            @(negedge clk);clear_i=0;
        end
    endtask

    task automatic start_run(input integer count,input integer gain);
        begin
            @(negedge clk);pair_count_i=count;gain_shift_i=gain;start_valid_i=1;
            @(posedge clk);
            if(!start_ready_o) $fatal(1,"START_NOT_READY");
            #1;
            @(negedge clk);start_valid_i=0;
        end
    endtask

    task automatic run_case(input string case_name,input integer count,input integer gain,input integer clip_total);
        integer sent,received,clips,cycles,pending,stall_budget;
        reg held,expected_done;
        reg [45:0] held_payload;
        reg [11:0] expected_value;
        begin
            if(count<1 || count>96000) $fatal(1,"FIXTURE_SIZE_OUTSIDE_TEST_MEMORY");
            path={"vectors_limit/",case_name,".input.hex"};$readmemh(path,input_mem,0,count-1);
            path={"vectors_limit/",case_name,".output.hex"};$readmemh(path,expected_mem,0,4*count-1);
            path={"vectors_limit/",case_name,".clip.hex"};$readmemh(path,clip_mem,0,4*count-1);
            sent=0;received=0;clips=0;cycles=0;pending=0;held=0;stall_budget=64;
            start_run(count,gain);
            while(received<4*count) begin
                @(negedge clk);
                rng=advance_rng(rng);
                // Deliberately perturb unlatched configuration throughout busy.
                pair_count_i=32'hffffffff;gain_shift_i=rng[5:4];start_valid_i=(cycles%13)==0;
                if(!pending) begin
                    if(sent<count && rng[3:0]!=0) begin
                        iq_valid_i=1;{iq_q_i,iq_i_i}=input_mem[sent];pending=1;
                    end else begin iq_valid_i=0;source_gaps=source_gaps+1;end
                end
                sample_ready_i=rng[7:6]!=0;
                if(sample_valid_o && received==0 && stall_budget>0) begin
                    sample_ready_i=0;stall_budget=stall_budget-1;long_stalls=long_stalls+1;
                end
                @(posedge clk);
                if(!busy_o || start_ready_o || config_error_o) $fatal(1,"BUSY_CONTRACT %s",case_name);
                if(held && (!sample_valid_o || {sample_data_o,sample_index_o,sample_last_o,sample_clipped_o}!==held_payload))
                    $fatal(1,"STALLED_PAYLOAD_CHANGED %s",case_name);
                held=sample_valid_o && !sample_ready_i;
                if(held) begin
                    held_payload={sample_data_o,sample_index_o,sample_last_o,sample_clipped_o};
                    stalls=stalls+1;
                end
                if(sent==count && iq_ready_o) $fatal(1,"EXTRA_INPUT_READY %s",case_name);
                if(iq_valid_i && iq_ready_o) begin sent=sent+1;pending=0;end
                expected_done=sample_valid_o && sample_ready_i && sample_last_o;
                if(sample_valid_o && sample_ready_i) begin
                    expected_value=expected_mem[received];
                    if(negative && cases==0 && received==0) expected_value=expected_value^12'h001;
                    if(sample_data_o!==expected_value)
                        $fatal(1,"GOLD_MISMATCH %s idx=%0d got=%0d expected=%0d",case_name,received,$signed(sample_data_o),$signed(expected_value));
                    if(sample_index_o!==received || sample_last_o!==(received==4*count-1) || sample_clipped_o!==clip_mem[received])
                        $fatal(1,"OUTPUT_METADATA %s idx=%0d",case_name,received);
                    clips=clips+sample_clipped_o;received=received+1;
                end
                #1;
                if(done_o!==expected_done) $fatal(1,"DONE_NOT_LAST_HANDSHAKE %s",case_name);
                if(input_count_o!==sent || output_count_o!==received || clip_count_o!==clips || clip_sticky_o!==(clips!=0))
                    $fatal(1,"COUNTERS %s",case_name);
                cycles=cycles+1;
                if(cycles>(count+10)*250+2000) $fatal(1,"WATCHDOG %s",case_name);
            end
            if(busy_o || sent!=count || clips!=clip_total) $fatal(1,"FINAL_TOTALS %s",case_name);
            @(negedge clk);start_valid_i=0;iq_valid_i=1;sample_ready_i=1;
            repeat(8) begin
                @(posedge clk);#1;
                if(sample_valid_o || iq_ready_o || done_o || busy_o || output_count_o!=4*count)
                    $fatal(1,"POST_COMPLETE_ACTIVITY %s",case_name);
            end
            @(negedge clk);iq_valid_i=0;
            total_samples=total_samples+received;cases=cases+1;
            $display("CASE_PASS %s N=%0d gain=%0d samples=%0d clips=%0d cycles=%0d",case_name,count,gain,received,clips,cycles);
        end
    endtask

    task automatic invalid_count(input integer count);
        begin
            clear_all();start_run(count,2);
            if(!config_error_o || busy_o || iq_ready_o || sample_valid_o || start_ready_o) $fatal(1,"INVALID_CONFIG");
            repeat(5) begin
                @(negedge clk);pair_count_i=1;start_valid_i=1;iq_valid_i=1;sample_ready_i=1;
                @(posedge clk);#1;
                if(!config_error_o || busy_o || iq_ready_o || sample_valid_o || done_o || input_count_o)
                    $fatal(1,"CONFIG_ERROR_NOT_STICKY");
            end
            clear_all();
        end
    endtask

    task automatic abort_in_state(input integer mode);
        integer timeout;
        begin
            clear_all();start_run(1,3);
            if(mode!=0) begin
                @(negedge clk);iq_valid_i=1;iq_i_i=255;iq_q_i=0;
                @(posedge clk);if(!iq_ready_o) $fatal(1,"ABORT_INPUT");
                @(negedge clk);iq_valid_i=0;
            end
            if(mode==1) repeat(7) @(negedge clk);
            if(mode==2 || mode==3) begin
                timeout=0;
                while(!sample_valid_o) begin @(negedge clk);timeout=timeout+1;if(timeout>2000)$fatal(1,"ABORT_WAIT");end
                repeat(4) @(negedge clk);
            end
            if(mode==3) begin
                // Asynchronous reset while a valid output is stalled.
                rst_n=0;#1;
                if(sample_valid_o || iq_ready_o || start_ready_o || busy_o) $fatal(1,"RESET_GATING");
                @(negedge clk);rst_n=1;
            end else clear_all();
            aborts=aborts+1;
            run_case("single_mid",1,2,0);
        end
    endtask

    initial begin
        if($value$plusargs("SEED=%d",seed)) begin end
        negative=$test$plusargs("NEGATIVE");rng=seed ? seed : 1;
        if($value$plusargs("VCD=%s",wave)) begin $dumpfile(wave);$dumpvars(0,rf_limit_tb.dut);end
        repeat(3) @(negedge clk);rst_n=1;
        clear_all();
        fd=$fopen("vectors_limit/cases.txt","r");if(!fd)$fatal(1,"NO_CASE_MANIFEST");
        while(!$feof(fd)) begin
            rc=$fscanf(fd,"%s %d %d %d\n",name,n,g,expected_clips);
            if(rc==4) begin
                run_case(name,n,g,expected_clips);
                if(cases==2) $dumpoff;
            end else if(rc!=-1) $fatal(1,"CASE_MANIFEST_PARSE");
        end
        $fclose(fd);
        if(cases!=1 || total_samples!=384000 || stalls==0 || source_gaps==0 || long_stalls==0) $fatal(1,"COVERAGE_EMPTY");
        $display("PASS_RF_LIMIT seed=%0d cases=%0d samples=%0d stalls=%0d source_gaps=%0d long_stalls=%0d",seed,cases,total_samples,stalls,source_gaps,long_stalls);
        checker_done=1;
        $finish;
    end
    initial begin #1000000000;$fatal(1,"GLOBAL_WATCHDOG");end
endmodule
`default_nettype wire
