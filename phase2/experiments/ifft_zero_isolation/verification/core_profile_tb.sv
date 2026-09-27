`timescale 1ns/1ps
`define IFFT dut.u_replay.u_core.u_ifft256
module core_profile_tb;
  reg clk=0;always #5 clk=~clk;
  reg rst_n=0;reg[31:0] control=0;
  wire[479:0]probe;wire busy,done,fault;
`ifdef STUDY_CANDIDATE
  trecap_measurement_engine #(.SUPPORT_IFFT_ZERO_ISOLATION(1)) dut(.clk(clk),.rst_n(rst_n),.control_i(control),.probe_o(probe),.busy_o(busy),.done_o(done),.fault_o(fault));
  wire [31:0] comparison_control={control[31:2],(control[1:0]==2'd3)?2'd2:control[1:0]};
  wire [479:0] comparison_probe;wire comparison_busy,comparison_done,comparison_fault;
  trecap_measurement_engine #(.SUPPORT_IFFT_ZERO_ISOLATION(1)) comparison_dut(.clk(clk),.rst_n(rst_n),.control_i(comparison_control),.probe_o(comparison_probe),.busy_o(comparison_busy),.done_o(comparison_done),.fault_o(comparison_fault));
  always @(posedge clk)if(rst_n)begin
    if({busy,done,fault,dut.y_valid,dut.source_valid,dut.source_ready,dut.core_busy,dut.top_busy,dut.core_sample_count,dut.core_frame_count,dut.elapsed_q} !== {comparison_busy,comparison_done,comparison_fault,comparison_dut.y_valid,comparison_dut.source_valid,comparison_dut.source_ready,comparison_dut.core_busy,comparison_dut.top_busy,comparison_dut.core_sample_count,comparison_dut.core_frame_count,comparison_dut.elapsed_q})$fatal(1,"full engine runtime mode2/3 lockstep handshake/count/latency");
    if(dut.y_valid && {dut.y_data,dut.y_idx} !== {comparison_dut.y_data,comparison_dut.y_idx})$fatal(1,"full engine output lockstep");
  end
`else
  trecap_measurement_engine dut(.clk(clk),.rst_n(rst_n),.control_i(control),.probe_o(probe),.busy_o(busy),.done_o(done),.fault_o(fault));
`endif
  integer total[0:17][1:8],az[0:17][1:8],bz[0:17][1:8],bothz[0:17][1:8],neither[0:17][1:8];
  reg [11:0] dense[0:1535],masked[0:1535];
  integer fd,trial=0,mode=0,output_count=0,checks=0,completed=0;
  reg[63:0] common_cycles=0;
  string path;
  always @(posedge clk)begin:observe
    integer f,s;
    if(rst_n&&!dut.core_clear&&busy)begin
      if(dut.y_valid)begin
        if(dut.y_idx !== 64'(output_count%1536) || dut.y_data !== ((mode==1)?dense[output_count%1536]:masked[output_count%1536]))$fatal(1,"external fullcore golden mismatch mode=%0d ordinal=%0d",mode,output_count);
        output_count=output_count+1;
      end
      if(`IFFT.state_q==3 && `IFFT.stage_ready)begin
        f=dut.epochs_q*9+`IFFT.frame_idx_q;s=`IFFT.stage_q;
        if(f<0||f>17||s<1||s>8)$fatal(1,"profile index invalid");
        total[f][s]=total[f][s]+1;
        if(`IFFT.a_rdata_q==0)az[f][s]=az[f][s]+1;
        if(`IFFT.b_rdata_q==0)bz[f][s]=bz[f][s]+1;
        if(`IFFT.a_rdata_q==0&&`IFFT.b_rdata_q==0)bothz[f][s]=bothz[f][s]+1;
        if(`IFFT.a_rdata_q!=0&&`IFFT.b_rdata_q!=0)neither[f][s]=neither[f][s]+1;
`ifdef STUDY_CANDIDATE
        if(`IFFT.zero_b_isolation_q !== (mode==3))$fatal(1,"full engine mode ownership changed during batch");
`endif
      end
      checks=checks+1;
    end
  end
  task batch(input integer m);
    integer f,s,waitcycles;
    reg[31:0] launched;
    reg[63:0] elapsed;
    begin
      @(negedge clk);mode=m;output_count=0;
      for(f=0;f<18;f=f+1)for(s=1;s<=8;s=s+1)begin total[f][s]=0;az[f][s]=0;bz[f][s]=0;bothz[f][s]=0;neither[f][s]=0;end
      control[31:16]=2;control[1:0]=2'(m);
      repeat(3)@(negedge clk);control[2]=~control[2];launched=control;
      wait(busy);waitcycles=0;
      while(busy)begin
        @(negedge clk);waitcycles=waitcycles+1;
        // Change payload without a new start: the admitted batch owns mode/count.
        if(waitcycles==500)begin control[1:0]=(m==3)?2'd1:2'd2;control[31:16]=7;end
        if(waitcycles>200000)$fatal(1,"engine batch watchdog");
      end
      if(!done||fault||output_count!=3072)$fatal(1,"batch failed mode=%0d outputs=%0d",m,output_count);
      control[3]=~control[3];repeat(2)@(negedge clk);
      if(probe[0+:32]!==32'h54524350 || probe[64+:32]!==launched || probe[96+:32]!==32'd2 || probe[128+:32]!==32'd3072 || probe[160+:32]!==32'd0 || probe[192+:32]!==32'd2048 || probe[224+:32]!==32'd18 || probe[320+:32]!==32'hffffffff || probe[352+:32]!==32'd0 || probe[384+:32]!==32'd1536)$fatal(1,"batch snapshot counter/ownership mismatch mode=%0d",m);
      elapsed={probe[288+:32],probe[256+:32]};
      if(common_cycles==0)common_cycles=elapsed;
      else if(elapsed!==common_cycles)$fatal(1,"mode changed cycle count");
`ifdef STUDY_CANDIDATE
      if(probe[32+11] !== (m==3))$fatal(1,"isolation status bit mismatch");
`endif
      for(f=0;f<18;f=f+1)for(s=1;s<=8;s=s+1)begin
        if(total[f][s]!=128)$fatal(1,"stage did not accept exactly128 butterflies");
        $fdisplay(fd,"%0d,%0d,%0d,measured_multitone,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d",trial,m,f/9,(m==1)?64'd0:64'd100000000000,f%9,s,total[f][s],az[f][s],bz[f][s],bothz[f][s],neither[f][s]);
      end
      repeat(100)@(negedge clk);
      if(busy||!done||fault||dut.y_valid)$fatal(1,"completed idle result not retained");
      $display("PROFILE_BATCH_PASS trial=%0d mode=%0d outputs=%0d cycles=%0d checksum=%h",trial,m,output_count,elapsed,probe[448+:32]);
      completed=completed+1;trial=trial+1;
    end
  endtask
  initial begin
    if(!$value$plusargs("PROFILE=%s",path))$fatal(1,"missing PROFILE");
    fd=$fopen(path,"w");if(fd==0)$fatal(1,"cannot open profile");
    $fdisplay(fd,"trial,mode,epoch,signal,threshold2,frame,stage,total_butterflies,a_complex_zero,b_complex_zero,both_complex_zero,neither_complex_zero");
    $readmemh("artifacts/measurement/multitone/y_dense.memh",dense);$readmemh("artifacts/measurement/multitone/y_masked.memh",masked);
    repeat(5)@(negedge clk);rst_n=1;
    batch(1);batch(2);
`ifdef STUDY_CANDIDATE
    batch(3);batch(2);
    if(completed!=4)$fatal(1,"candidate completion coverage");
`else
    if(completed!=2)$fatal(1,"baseline completion coverage");
`endif
    // Explicit mode0 admission returns the completed shell to clean idle.
    @(negedge clk);control[1:0]=0;control[31:16]=0;repeat(2)@(negedge clk);control[2]=~control[2];repeat(4)@(negedge clk);
    if(busy||!done||fault||dut.mode_q!=0)$fatal(1,"mode0 idle admission failed");
    $fclose(fd);$display("STUDY_PROFILE_PASS completed_batches=%0d checked_cycles=%0d",completed,checks);$finish;
  end
  initial begin #10000000;$fatal(1,"profile watchdog");end
endmodule
`undef IFFT
