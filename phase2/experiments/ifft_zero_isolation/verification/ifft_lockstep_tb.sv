`timescale 1ns/1ps
module ifft_lockstep_tb;
  localparam integer NF=20;
  reg clk=0;always #5 clk=~clk;
  reg rst_n=0,clear=0,clear_sticky=0,iv=0,ordy=0,isolation=1;
  reg signed [27:0] xr=0,xi=0;
  reg [63:0] frame=0;
  wire [3:0] ir,ov,last;
  wire signed [35:0] yr[4],yi[4];
  wire [7:0] offset[4];wire[63:0] out_frame[4];
  wire [6:0] status[4]; // busy,load,compute,output,done,saturation,protocol
  reg [55:0] vin[0:NF*256-1];
  reg [71:0] gold[0:NF*256-1];
  reg gsat[0:NF-1];
  integer cid=0,received=0,checks=0,all_outputs=0,completed=0,aborts=0,stalls=0,owned_frames=0,retention_checks=0;
  reg expect_enabled=0,owned=0,protocol_expected=0;
  reg [63:0] frame_expected=0;
  string vectors;
  baseline_ifft256 ref_dut(.clk(clk),.rst_n(rst_n),.clear_i(clear),.in_valid_i(iv),.in_ready_o(ir[0]),.in_re_i(xr),.in_im_i(xi),.in_frame_idx_i(frame),.out_valid_o(ov[0]),.out_ready_i(ordy),.out_re_o(yr[0]),.out_im_o(yi[0]),.out_sample_offset_o(offset[0]),.out_frame_idx_o(out_frame[0]),.out_last_o(last[0]),.busy_o(status[0][6]),.load_active_o(status[0][5]),.compute_active_o(status[0][4]),.output_active_o(status[0][3]),.frame_done_pulse_o(status[0][2]),.saturation_sticky_o(status[0][1]),.protocol_error_sticky_o(status[0][0]),.clear_sticky_i(clear_sticky));
  genvar g;
  generate for(g=1;g<4;g=g+1)begin:variants
    trecap_ifft256 #(.SUPPORT_ZERO_B_ISOLATION(g!=1)) dut(.clk(clk),.rst_n(rst_n),.clear_i(clear),.zero_b_isolation_i(g==3 ? isolation : (g==1)),.in_valid_i(iv),.in_ready_o(ir[g]),.in_re_i(xr),.in_im_i(xi),.in_frame_idx_i(frame),.out_valid_o(ov[g]),.out_ready_i(ordy),.out_re_o(yr[g]),.out_im_o(yi[g]),.out_sample_offset_o(offset[g]),.out_frame_idx_o(out_frame[g]),.out_last_o(last[g]),.busy_o(status[g][6]),.load_active_o(status[g][5]),.compute_active_o(status[g][4]),.output_active_o(status[g][3]),.frame_done_pulse_o(status[g][2]),.saturation_sticky_o(status[g][1]),.protocol_error_sticky_o(status[g][0]),.clear_sticky_i(clear_sticky));
  end endgenerate
  always @(negedge clk)if(rst_n&&!clear&&status[0][6])begin
    if(variants[3].dut.zero_b_isolation_q !== owned) $fatal(1,"IFFT isolation ownership changed midframe");
    if(variants[1].dut.zero_b_isolation_q !== 0 || variants[2].dut.zero_b_isolation_q !== 0) $fatal(1,"disabled IFFT isolation active");
  end
  always @(posedge clk)begin:monitor
    integer j;
    if(!rst_n || clear)owned=0;
    else begin
      for(j=1;j<4;j=j+1)begin
        if({ir[j],ov[j],status[j]} !== {ir[0],ov[0],status[0]})$fatal(1,"IFFT handshake/status case=%0d variant=%0d",cid,j);
        if(ov[0] && {yr[j],yi[j],offset[j],out_frame[j],last[j]} !== {yr[0],yi[0],offset[0],out_frame[0],last[0]})$fatal(1,"IFFT data lockstep case=%0d offset=%0d variant=%0d",cid,offset[0],j);
      end
      if(iv&&ir[0]&&!status[0][6])begin owned=isolation;owned_frames=owned_frames+1;end
      if(ov[0] && expect_enabled)begin
        if({yr[0],yi[0]} !== gold[cid*256+received])$fatal(1,"IFFT integer oracle case=%0d offset=%0d got=%h expected=%h",cid,received,{yr[0],yi[0]},gold[cid*256+received]);
        if(offset[0] !== received[7:0] || out_frame[0] !== frame_expected || last[0] !== (received==255))$fatal(1,"IFFT metadata");
        if(status[0][1] !== gsat[cid] || status[0][0] !== protocol_expected)$fatal(1,"IFFT sticky status expected sat=%b protocol=%b got=%b",gsat[cid],protocol_expected,status[0][1:0]);
        if(ordy)begin received=received+1;all_outputs=all_outputs+1;end else stalls=stalls+1;
      end
      checks=checks+1;
    end
  end
  task clear_flags;
    begin @(negedge clk);clear_sticky=1;@(negedge clk);clear_sticky=0;protocol_expected=0;end
  endtask
  task load_frame(input integer n,input integer words,input bit bad_index);
    integer i;
    begin
      cid=n;received=0;frame_expected=64'h8000000000000000+owned_frames+1;frame=frame_expected;isolation=(n%3!=1);
      for(i=0;i<words;i=i+1)begin
        @(negedge clk);iv=0;
        if(i>0)isolation=~owned;
        if((i+n)%7==0)repeat(2)@(negedge clk);
        {xr,xi}=vin[n*256+i];frame=(bad_index&&i==133)?frame_expected+1:frame_expected;iv=1;
        do @(posedge clk);while(!ir[0]);
        @(negedge clk);iv=0;
      end
      if(bad_index)protocol_expected=1;
    end
  endtask
  task run_frame(input integer n);
    integer cycles,last_hold;
    begin
      clear_flags();expect_enabled=1;ordy=0;
      load_frame(n,256,n==5);
      cycles=0;last_hold=0;
      while(received<256)begin
        @(negedge clk);cycles=cycles+1;isolation=~isolation;
        if(ov[0]&&last[0]&&last_hold<19)begin ordy=0;last_hold=last_hold+1;end
        else ordy=((cycles%5)!=0 && (cycles%13)!=0);
      end
      ordy=0;expect_enabled=0;
      if(!status[0][2] || status[0][6])$fatal(1,"IFFT completion pulse/idle missing");
      completed=completed+1;
    end
  endtask
  task abort_frame(input integer phase,input bit use_reset);
    begin
      clear_flags();expect_enabled=0;ordy=0;
      load_frame(phase+1,phase==0?73:256,0);
      if(phase==1)repeat(23)@(negedge clk);
      if(phase==2)while(!ov[0])@(negedge clk);
      @(negedge clk);if(use_reset)rst_n=0;else clear=1;
      repeat(3)@(negedge clk);rst_n=1;clear=0;
      repeat(12)begin @(negedge clk);if(ov[0]||status[0][6])$fatal(1,"aborted IFFT leaked output/busy");end
      aborts=aborts+1;run_frame(0);run_frame(2);
    end
  endtask
  integer n;
  initial begin
    if(!$value$plusargs("VECTORS=%s",vectors))$fatal(1,"missing VECTORS");
    $readmemh({vectors,"/ifft_input.memh"},vin);$readmemh({vectors,"/ifft_gold.memh"},gold);$readmemh({vectors,"/ifft_sat.memh"},gsat);
    repeat(4)@(negedge clk);rst_n=1;
    for(n=0;n<NF;n=n+1)begin
      run_frame(n);
      if(n==5 || gsat[n])begin
        // clear_i aborts work but retains sticky diagnostics. clear_sticky_i
        // (at the next frame) and reset are the explicit diagnostic resets.
        @(negedge clk);clear=1;repeat(2)@(negedge clk);clear=0;
        @(negedge clk);
        if(status[0][1:0] !== {gsat[n],protocol_expected})$fatal(1,"IFFT clear lost retained sticky status");
        retention_checks=retention_checks+1;
      end
    end
    for(n=0;n<3;n=n+1)begin abort_frame(n,0);abort_frame(n,1);end
    if(all_outputs!=8192 || completed!=32 || aborts!=6 || stalls<200 || owned_frames!=38 || retention_checks!=2)$fatal(1,"IFFT coverage insufficient outputs=%0d completed=%0d aborts=%0d owned=%0d retention=%0d",all_outputs,completed,aborts,owned_frames,retention_checks);
    $display("STUDY_IFFT_PASS checks=%0d outputs=%0d complete_frames=%0d aborted_frames=%0d owned_frames=%0d stalled_cycles=%0d sticky_retention_checks=%0d",checks,all_outputs,completed,aborts,owned_frames,stalls,retention_checks);$finish;
  end
  initial begin #10000000;$fatal(1,"IFFT watchdog");end
endmodule
