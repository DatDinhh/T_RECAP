`timescale 1ns/1ps
module window_tb;
 reg clk=0;always #5 clk=~clk;reg rst_n=0,enable_i=1,clear_i=0,clear_sticky_i=0,frame_valid_i=0,sample_valid_i=0,out_ready_i=0;
 reg[63:0]frame_idx_i=0,frame_start_sample_idx_i=0,sample_idx_i=0;reg signed[11:0]sample_i=0;
 wire frame_ready_o,sample_ready_o,out_valid_o,out_last_o,busy_o,frame_accept_pulse_o,sample_accept_pulse_o,output_accept_pulse_o,frame_done_pulse_o,input_underrun_sticky_o,output_backpressure_sticky_o,protocol_error_sticky_o,window_oob_sticky_o,saturation_sticky_o;
 wire signed[26:0]out_sample_o;wire[7:0]out_sample_offset_o;wire[63:0]out_frame_idx_o,out_source_sample_idx_o;
 trecap_analysis_window #(.WINDOW_FILE("directed_window.memh")) dut(.*);
 reg[15:0]qw[0:255];integer f,k,expected,fd,expected_saturation=0,stalls=0,inputs=0,outputs=0;string dir;
 task req(input logic b,input string msg);begin if(b!==1'b1)$fatal(1,"WINDOW f=%0d k=%0d %s",f,k,msg);end endtask
 task tick;begin @(negedge clk);end endtask
 task compare;begin req(out_valid_o&&$signed(out_sample_o)==expected&&out_sample_offset_o==k&&out_frame_idx_o==f&&out_source_sample_idx_o==f*256+k&&out_last_o==(k==255),"unsigned coefficient product/metadata");end endtask
 always @(posedge clk)if(rst_n)begin if(sample_valid_i&&sample_ready_o)inputs++;if(out_valid_o&&out_ready_i)outputs++;end
 initial begin
  if(!$value$plusargs("OUT=%s",dir))$fatal(1,"OUT");fd=$fopen({dir,"/trace.csv"},"w");$fwrite(fd,"frame,offset,sample,coefficient,actual_product,source_index,last,saturation_sticky\n");$readmemh("directed_window.memh",qw);
  repeat(3)tick();rst_n=1;tick();
  for(f=0;f<4;f++)begin
   clear_i=1;tick();clear_i=0;tick();expected_saturation=0;req(frame_ready_o,"frame admission");frame_idx_i=f;frame_start_sample_idx_i=f*256;frame_valid_i=1;tick();frame_valid_i=0;
   for(k=0;k<256;k++)begin
    sample_i=(f==0)?-2048:(f==1)?2047:(f==2)?-1:1;sample_idx_i=f*256+k;expected=$signed(sample_i)*$signed({1'b0,qw[k]});if(expected>67108863)begin expected=67108863;expected_saturation=1;end if(expected< -67108864)begin expected=-67108864;expected_saturation=1;end
    req(sample_ready_o,"sample admission");sample_valid_i=1;tick();sample_valid_i=0;
    compare();repeat(3)begin tick();compare();stalls++;end
    req(!protocol_error_sticky_o&&!window_oob_sticky_o&&(saturation_sticky_o===1'(expected_saturation)),"no arithmetic/geometry fault");
    $fwrite(fd,"%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d\n",out_frame_idx_o,out_sample_offset_o,$signed(sample_i),qw[k],$signed(out_sample_o),out_source_sample_idx_o,out_last_o,saturation_sticky_o);
    out_ready_i=1;tick();out_ready_i=0;req(!out_valid_o,"singleoutput");
   end
   req(!busy_o,"frame retired");
  end
  req(inputs==1024&&outputs==1024&&output_backpressure_sticky_o,"conservation/backpressure event");$display("PASS window inputs=%0d outputs=%0d held_checks=%0d",inputs,outputs,stalls);$fclose(fd);$finish;
 end
 initial begin #1000000;$fatal(1,"WINDOW_WATCHDOG");end
endmodule
