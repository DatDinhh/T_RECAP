`timescale 1ns/1ps
module butterfly_tb #(parameter integer DW=28,NORM=1);
 reg clk=0;always #5 clk=~clk;reg rst_n=0,valid_i=0,ready_i=0;
 reg signed[DW-1:0] a_re_i,a_im_i,b_re_i,b_im_i;reg signed[16:0] tw_re_i,tw_im_i;
 wire ready_o,valid_o,sat_any_o,input_accept_pulse_o,output_accept_pulse_o;
 wire signed[DW-1:0] y0_re_o,y0_im_o,y1_re_o,y1_im_o;
 trecap_fft_stage #(.DATA_W(DW),.OUT_W(DW),.REGISTER_OUTPUT(1),.NORMALIZE_BY_2(NORM)) dut(.clk(clk),.rst_n(rst_n),.clear_i(1'b0),.*);
 reg signed[DW-1:0] e0r,e0i,e1r,e1i;integer ef,n,row,parsed,fd,tf,waits,stall_checks=0,accepts=0,outputs=0;string dir;
 task require(input logic ok,input string why);begin if(ok!==1'b1)$fatal(1,"BUTTERFLY row=%0d %s",row,why);end endtask
 task compare;begin require(valid_o && y0_re_o===e0r && y0_im_o===e0i && y1_re_o===e1r && y1_im_o===e1i && sat_any_o===1'(ef),"exact arithmetic/flags");end endtask
 always @(posedge clk)if(rst_n)begin if(input_accept_pulse_o)accepts++;if(output_accept_pulse_o)outputs++;end
 initial begin
  if(!$value$plusargs("OUT=%s",dir))$fatal(1,"SETUP");fd=$fopen({dir,"/vectors.txt"},"r");tf=$fopen({dir,"/trace.csv"},"w");
  $fwrite(tf,"row,y0_re,y0_im,y1_re,y1_im,saturated\n");parsed=$fscanf(fd,"%d",n);require(parsed==1,"count");
  repeat(3)@(negedge clk);rst_n=1;
  for(row=0;row<n;row++)begin
   parsed=$fscanf(fd,"%h %h %h %h %h %h %h %h %h %h %d",a_re_i,a_im_i,b_re_i,b_im_i,tw_re_i,tw_im_i,e0r,e0i,e1r,e1i,ef);require(parsed==11,"vectors");
   ready_i=0;valid_i=1;@(posedge clk);require(ready_o,"ready at admission");@(negedge clk);valid_i=0;
   // Invalid input data may change while the accepted transaction is in flight.
   a_re_i=0;a_im_i=0;b_re_i=0;b_im_i=0;tw_re_i=0;tw_im_i=0;
   waits=0;while(!valid_o)begin @(negedge clk);waits++;require(waits<12,"bounded pipeline response");end
   compare();repeat(3)begin @(negedge clk);compare();stall_checks++;end
   $fwrite(tf,"%0d,%0d,%0d,%0d,%0d,%0d\n",row,$signed(y0_re_o),$signed(y0_im_o),$signed(y1_re_o),$signed(y1_im_o),sat_any_o);
   ready_i=1;@(negedge clk);require(!valid_o,"single output");
  end
  require(accepts==n&&outputs==n,"accept/conservation");$display("PASS butterfly rows=%0d accepts=%0d outputs=%0d stalled_checks=%0d",n,accepts,outputs,stall_checks);$fclose(fd);$fclose(tf);$finish;
 end
 initial begin #10000000;$fatal(1,"BUTTERFLY_WATCHDOG");end
endmodule
