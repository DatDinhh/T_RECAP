`timescale 1ns/1ps
module mask_tb;
 import trecap_core_pkg::*; import trecap_iface_pkg::*;
 reg clk=0; always #5 clk=~clk;
 reg rst_n=0,in_valid_i=0,out_ready_i=0;
 reg [55:0] thr2_i; reg [63:0] in_frame_idx_i; reg [7:0] in_bin_idx_i;
 reg signed [27:0] in_re_i,in_im_i; reg in_unique_i,in_self_conj_i,in_last_i;
 wire in_ready_o,out_valid_o; wire [63:0] out_frame_idx_o; wire [7:0] out_bin_idx_o;
 wire signed [27:0] out_re_o,out_im_o; wire [55:0] out_mag2_o;
 wire out_pre_mask_o,out_mask_o,out_eligible_o,out_unique_o,out_last_o;
 wire frame_stats_valid_o; wire [63:0] frame_stats_frame_idx_o; trecap_frame_stats_t frame_stats_o;
 wire overflow_sticky_o;
 trecap_mag2_mask dut(.clk(clk),.rst_n(rst_n),.enable_i(1'b1),.clear_i(1'b0),.clear_metrics_i(1'b0),.clear_sticky_i(1'b0),.*);
 string dir; integer vf,sf,tf,parsed,n,count=0,stalled_checks=0,stats_checks=0;
 integer fr,bin,uni,selfc,last,pre,mask,eligible;
 reg [55:0] gold_mag; reg [27:0] gold_re,gold_im; reg [55:0] gold_thr;
 integer ef,eu,es,ee,ees; reg [63:0] ek,et;
 task require(input logic ok,input string why);begin if(ok!==1'b1)$fatal(1,"MASK_CHECK row=%0d %s",count,why);end endtask
 task compare;begin
  require(out_valid_o && out_frame_idx_o==fr && out_bin_idx_o==bin,"identity");
  require(out_re_o===gold_re && out_im_o===gold_im && out_mag2_o===gold_mag,"magnitude");
  require(out_pre_mask_o===1'(pre) && out_mask_o===1'(mask) && out_eligible_o===1'(eligible),"threshold/protection");
  require(out_unique_o===1'(uni) && out_last_o===1'(last),"flags");
 end endtask
 always @(posedge clk)begin
  if(rst_n && $isunknown({in_valid_i,out_ready_i}))$fatal(1,"MASK_UNKNOWN_CONTROL");
  if(rst_n && in_valid_i && $isunknown({in_re_i,in_im_i,thr2_i,in_frame_idx_i,in_bin_idx_i,in_unique_i,in_self_conj_i,in_last_i}))$fatal(1,"MASK_UNKNOWN_VALID_PAYLOAD");
  #1;
  if(rst_n && frame_stats_valid_o)begin
   parsed=$fscanf(sf,"%d %d %d %d %d %h %h",ef,eu,es,ee,ees,ek,et);
   require(parsed==7,"stats inventory");
   require(frame_stats_frame_idx_o==ef && frame_stats_o.unique_bins==eu && frame_stats_o.unique_suppressed_bins==es && frame_stats_o.eligible_unique_bins==ee && frame_stats_o.eligible_suppressed_bins==ees,"stats counts");
   require(frame_stats_o.eligible_kept_mag2_lo===ek && frame_stats_o.eligible_total_mag2_lo===et && !frame_stats_o.mag2_truncated,"stats energies");stats_checks++;
  end
 end
 initial begin
  if(!$value$plusargs("OUT=%s",dir))$fatal(1,"MASK_SETUP");
  vf=$fopen({dir,"/vectors.txt"},"r");sf=$fopen({dir,"/stats.txt"},"r");tf=$fopen({dir,"/trace.csv"},"w");
  $fwrite(tf,"frame,bin,mag2,pre_mask,mask,eligible\n"); parsed=$fscanf(vf,"%d",n);require(parsed==1,"count");
  repeat(3)@(negedge clk);rst_n=1;
  for(count=0;count<n;count++)begin
   parsed=$fscanf(vf,"%h %h %h %d %d %d %d %d %h %d %d %d",gold_re,gold_im,gold_thr,fr,bin,uni,selfc,last,gold_mag,pre,mask,eligible);require(parsed==12,"inventory");
   in_re_i=gold_re;in_im_i=gold_im;thr2_i=gold_thr;in_frame_idx_i=fr;in_bin_idx_i=bin;in_unique_i=uni;in_self_conj_i=selfc;in_last_i=last;
   in_valid_i=1;out_ready_i=0;
   if(count==0 && $test$plusargs("INJECT_X"))in_re_i='x;
   if(count==0 && $test$plusargs("INJECT_Z"))in_valid_i=1'bz;
   @(posedge clk);while(!in_ready_o)@(posedge clk);@(negedge clk);in_valid_i=0;
   compare();thr2_i=~gold_thr;
   repeat(3)begin @(negedge clk);compare();stalled_checks++;end
   $fwrite(tf,"%0d,%0d,%0d,%0d,%0d,%0d\n",out_frame_idx_o,out_bin_idx_o,out_mag2_o,out_pre_mask_o,out_mask_o,out_eligible_o);
   out_ready_i=1;@(negedge clk);require(!out_valid_o,"single output per input");
   require(!overflow_sticky_o,"unexpected overflow/protocol fault");
  end
  require(stats_checks==12,"all frame stats");
  $display("PASS mask rows=%0d stalled_checks=%0d stats_checks=%0d",count,stalled_checks,stats_checks);$fclose(vf);$fclose(sf);$fclose(tf);$finish;
 end
 initial begin #1000000;$fatal(1,"MASK_WATCHDOG");end
endmodule
