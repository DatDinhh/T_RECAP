`timescale 1ns/1ps
module canonical_tb;
 reg clk=0;always #5 clk=~clk;reg rst_n=0,enable_i=1,clear_i=0,clear_sticky_i=0,in_valid_i=0,out_ready_i=0;
 reg[63:0]in_frame_idx_i=0;reg[7:0]in_bin_idx_i=0;reg signed[27:0]in_re_i=0,in_im_i=0;reg in_last_i=0;
 wire in_ready_o,out_valid_o,out_unique_o,out_self_conj_o,out_last_o,protocol_error_sticky_o;
 wire[63:0]out_frame_idx_o;wire[7:0]out_bin_idx_o;wire signed[27:0]out_re_o,out_im_o;
 trecap_hermitian_canonicalizer dut(.*);
 reg signed[27:0] xr[0:255],xi[0:255],yr[0:255],yi[0:255];
 integer eu[0:255],es[0:255],el[0:255],ef[0:255];integer fd,tf,ff,p,rf,rk,f,k,waits,stalls=0,accepted=0,outputs=0;
 reg signed[27:0] captured_re,captured_im;reg[63:0] captured_frame;reg[7:0] captured_bin;reg captured_unique,captured_self,captured_last; string dir;
 task req(input logic b,input string msg);begin if(b!==1'b1)$fatal(1,"CAN f=%0d k=%0d %s",f,k,msg);end endtask
 task tick;begin @(negedge clk);end endtask
 task wipe;begin clear_i=1;tick();clear_i=0;tick();req(in_ready_o&&!out_valid_o&&!protocol_error_sticky_o,"clear resets owner");end endtask
 task send(input integer idx,input integer frame,input integer last);
  begin in_valid_i=1;in_bin_idx_i=idx;in_frame_idx_i=frame;in_last_i=last;tick();in_valid_i=0;end
 endtask
 task compare(input integer b);
  begin req(out_valid_o&&out_frame_idx_o==f&&out_bin_idx_o==b&&out_re_o===yr[b]&&out_im_o===yi[b]&&out_unique_o===1'(eu[b])&&out_self_conj_o===1'(es[b])&&out_last_o===1'(el[b]),"exact canonical payload/metadata");end
 endtask
 always @(posedge clk)if(rst_n)begin if(in_valid_i&&in_ready_o)accepted++;if(out_valid_o&&out_ready_i)outputs++;end
 initial begin
  if(!$value$plusargs("OUT=%s",dir))$fatal(1,"OUT");fd=$fopen({dir,"/vectors.txt"},"r");tf=$fopen({dir,"/trace.csv"},"w");ff=$fopen({dir,"/faults.csv"},"w");
  $fwrite(tf,"frame,bin,re,im,unique,self_conjugate,last,sticky\n");$fwrite(ff,"fault,fail_stop_cycles,sticky_clear_blocked,recovery\n");
  repeat(3)tick();rst_n=1;tick();
  for(f=0;f<8;f++)begin
   wipe();
   if(f>=4)begin
    case(f-4)
     0:send(1,0,0);
     1:send(0,0,1);
     2:begin send(0,0,0);send(1,1,0);end
     3:begin for(k=0;k<256;k++)send(k,0,0);end
    endcase
    repeat(10)begin tick();req(protocol_error_sticky_o&&!in_ready_o&&!out_valid_o,"malformed frame fail stop");end
    clear_sticky_i=1;tick();clear_sticky_i=0;tick();req(protocol_error_sticky_o&&!in_ready_o&&!out_valid_o,"sticky clear cannot recover incomplete epoch");
    if(f%2==0)wipe();else begin enable_i=0;tick();enable_i=1;clear_sticky_i=1;tick();clear_sticky_i=0;tick();req(in_ready_o&&!out_valid_o&&!protocol_error_sticky_o,"disable recovery owner");end
    $fwrite(ff,"%0d,10,1,%0d\n",f-4,f%2);
   end
   for(k=0;k<256;k++)begin p=$fscanf(fd,"%d %d %h %h %h %h %d %d %d %d",rf,rk,xr[k],xi[k],yr[k],yi[k],eu[k],es[k],el[k],ef[k]);req(p==10&&rf==f&&rk==k,"vector cardinality");end
   for(k=0;k<256;k++)begin
    req(in_ready_o&&!out_valid_o,"load admission");in_re_i=xr[k];in_im_i=xi[k];send(k,f,k==255);
    if(k%7==0)tick();
   end
   for(k=0;k<256;k++)begin
    waits=0;while(!out_valid_o)begin tick();waits++;req(waits<8,"bounded canonical response");end
    compare(k);repeat(3)begin tick();compare(k);req(!in_ready_o,"no overwrite while output pending");stalls++;end
    captured_re=out_re_o;captured_im=out_im_o;captured_frame=out_frame_idx_o;captured_bin=out_bin_idx_o;captured_unique=out_unique_o;captured_self=out_self_conj_o;captured_last=out_last_o;out_ready_i=1;tick();out_ready_i=0;req(protocol_error_sticky_o===1'(ef[k]),"expected sticky after accepted output");
    $fwrite(tf,"%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d\n",captured_frame,captured_bin,$signed(captured_re),$signed(captured_im),captured_unique,captured_self,captured_last,protocol_error_sticky_o);
   end
   req(in_ready_o&&!out_valid_o,"complete frame returns admission");
  end
  req(outputs==2048,"output conservation");$display("PASS canonical frames=8 outputs=%0d stalled_checks=%0d malformed_cases=4",outputs,stalls);$fclose(fd);$fclose(tf);$fclose(ff);$finish;
 end
 initial begin #1000000;$fatal(1,"CAN_WATCHDOG");end
endmodule
