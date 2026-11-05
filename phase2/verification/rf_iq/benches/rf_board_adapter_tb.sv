`timescale 1ns/1ps
`default_nettype none
module rf_board_adapter_tb;
 reg clk=0;always #5 clk=~clk;
 reg rst_n=0,rf_mode=1;
 reg [20:0] avs_address=0;
 reg avs_read=0,avs_write=0,avs_burstcount=1;
 reg [31:0] avs_writedata=0;
 reg [3:0] avs_byteenable=15;
 wire avs_waitrequest,avs_readdatavalid,avs_writeresponsevalid;
 wire [31:0] avs_readdata;wire [1:0] avs_response;
 wire rf_wait,rf_rvalid,rf_wvalid,base_wait,base_rvalid,base_wvalid;
 wire [31:0] rf_rdata,base_rdata;
 wire [1:0] rf_response,base_response;
 `include "source_id.svh"
 localparam integer NS=2048,NY=2560,NFRAMES=17;
 trecap_rf_board_adapter #(.SOURCE_ID(TEST_SOURCE_ID),.INPUT_SAMPLES(NS),.WATCHDOG_CYCLES(1000000)) dut(
   .clk(clk),.rst_n(rst_n),.avs_address(avs_address),.avs_read(avs_read&&rf_mode),.avs_write(avs_write&&rf_mode),
   .avs_writedata(avs_writedata),.avs_byteenable(avs_byteenable),.avs_burstcount(avs_burstcount),
   .avs_waitrequest(rf_wait),.avs_readdata(rf_rdata),.avs_readdatavalid(rf_rvalid),.avs_writeresponsevalid(rf_wvalid),.avs_response(rf_response));
 trecap_stream_adapter #(.SOURCE_ID(TEST_SOURCE_ID),.INPUT_SAMPLES(NS),.WATCHDOG_CYCLES(1000000)) baseline(
   .clk(clk),.rst_n(rst_n),.avs_address(avs_address),.avs_read(avs_read&&!rf_mode),.avs_write(avs_write&&!rf_mode),
   .avs_writedata(avs_writedata),.avs_byteenable(avs_byteenable),.avs_burstcount(avs_burstcount),
   .avs_waitrequest(base_wait),.avs_readdata(base_rdata),.avs_readdatavalid(base_rvalid),.avs_writeresponsevalid(base_wvalid),.avs_response(base_response));
 assign avs_waitrequest=rf_mode?rf_wait:base_wait;
 assign avs_readdata=rf_mode?rf_rdata:base_rdata;
 assign avs_readdatavalid=rf_mode?rf_rvalid:base_rvalid;
 assign avs_writeresponsevalid=rf_mode?rf_wvalid:base_wvalid;
 assign avs_response=rf_mode?rf_response:base_response;
 wire source_valid=rf_mode?dut.source_valid:baseline.source_valid;
 wire source_ready=rf_mode?dut.source_ready:baseline.source_ready;
 wire [63:0] source_idx=rf_mode?dut.source_idx:baseline.source_idx;
 wire signed [11:0] source_data=rf_mode?dut.core.source_sample_data_o:baseline.core.source_sample_data_o;
 wire y_good=rf_mode?dut.y_good:baseline.y_good;
 wire [63:0] y_idx=rf_mode?dut.y_idx:baseline.y_idx;
 wire signed [11:0] y_data=rf_mode?dut.y_data:baseline.y_data;
 wire export_take=rf_mode?dut.export_take:baseline.export_take;
 wire [7:0] export_data=rf_mode?dut.export_data:baseline.export_data;
 wire tap_valid=rf_mode?dut.tap_valid:baseline.tap_valid;
 reg [11:0] x_gold[0:NS-1],y_gold[0:NY-1];
 reg [15:0] iq_gold[0:511];reg [7:0] wire_gold[0:32767];
 reg [55:0] threshold;reg [31:0] value,v,slevel,ylevel,free_slots,status;
 integer phase=-1,checks=0,cycles=0,transactions=0,negatives=0,start_cycle;
 integer source_seen=0,y_seen=0,wire_seen=0,host_x,host_y,host_bytes,tap_seen;
 integer input_full_cycles=0,s_full_cycles=0,y_full_cycles=0,rf_stall_cycles=0;
 integer inventory,parsed,mode,expected_bytes=0,epoch=0,limit,case_id,pass,normal_epochs=0;
 integer pairs,gain,expected_clips,host_limit,summary_file;
 integer checker_done=0;
 bit finished;
 string outdir,fixture_inventory,iq_path,x_path;
 task require(input logic ok,input string why);begin checks++;if(ok!==1'b1)$fatal(1,"phase%0d RF%0d cycle%0d %s",phase,rf_mode,cycles,why);end endtask
 task tick;begin @(negedge clk);end endtask
 task access(input reg [20:0] address,input reg r,input reg w,input reg [31:0] data,input reg [3:0] be,input reg burst,input reg [1:0] expected,output reg [31:0] result);
 integer waits;begin
  waits=0;while(avs_waitrequest)begin tick();waits++;if(waits>12)$fatal(1,"accept timeout");end
  avs_address=address;avs_read=r;avs_write=w;avs_writedata=data;avs_byteenable=be;avs_burstcount=burst;
  tick();avs_read=0;avs_write=0;avs_address=~address;avs_writedata=~data;avs_byteenable=0;avs_burstcount=0;
  waits=0;while(!avs_readdatavalid&&!avs_writeresponsevalid)begin tick();waits++;if(waits>8)$fatal(1,"response timeout");end
  require(avs_readdatavalid===r&&avs_writeresponsevalid===w,"response direction");
  require(avs_response===expected,$sformatf("response code addr=%h read=%b write=%b data=%h expected=%d actual=%d RFstate=%d RFfault=%h",address,r,w,data,expected,avs_response,dut.state,dut.faults));result=avs_readdata;transactions++;
 end endtask
 task wr(input reg [20:0] a,input reg [31:0] d);reg [31:0] q;begin access(a,0,1,d,15,1,0,q);end endtask
 task rd(input reg [20:0] a,output reg [31:0] q);begin access(a,1,0,0,15,1,0,q);end endtask
 task idle;integer i;begin i=0;rd('h008,value);while(value[0])begin rd('h008,value);i++;if(i>2000)$fatal(1,"clear timeout");end require(value==0,"empty idle");end endtask
 task clear;begin wr('h010,1);idle();end endtask
 task wait_input_ready;integer i;begin
  i=0;rd('h008,value);
  while(!value[3])begin
   require(!value[2],"fault while waiting for input admission");
   rd('h008,value);i++;if(i>2000)$fatal(1,"input ready timeout");
  end
 end endtask
 task bad(input reg [20:0] a,input reg r,input reg w,input reg [31:0] d,input reg [3:0] be,input reg burst);begin
  access(a,r,w,d,be,burst,2,value);rd('h008,value);require(value[2]&&!value[1],"bad access did not fault");negatives++;clear();
 end endtask
 always @(posedge clk)begin
  cycles++;if(cycles>18000000)$fatal(1,"global timeout");
  if(rst_n&&phase>=0)begin
   if(rf_mode)begin
    if(dut.iq_level==256)input_full_cycles++;
    if(dut.s_full)s_full_cycles++;
    if(dut.y_full)y_full_cycles++;
    if(dut.rf_valid&&!dut.pcm_ready_raw)rf_stall_cycles++;
   end
   if(source_valid&&source_ready)begin
    require(source_idx==source_seen,"source index");
    require(source_data===((source_seen<NS)?x_gold[source_seen]:12'd0),"source PCM/flush");source_seen++;
   end
   if(y_good)begin
    require(y_seen<NY&&y_idx==y_seen,"Y count/index");
    if(rf_mode)require(y_data===y_gold[y_seen],"Y differs from independent PCM input baseline");
    else y_gold[y_seen]=y_data;
    y_seen++;
   end
   if(export_take)begin
    require(wire_seen<32768,"spectral bounds");
    if(rf_mode)require(wire_seen<expected_bytes&&export_data===wire_gold[wire_seen],"spectral byte differs from PCM baseline");
    else wire_gold[wire_seen]=export_data;
    wire_seen++;
   end
   if(tap_valid)tap_seen++;
  end
 end
 initial begin
  if(!$value$plusargs("OUT=%s",outdir)||!$value$plusargs("CASES=%s",fixture_inventory))$fatal(1,"OUT/CASES required");
  inventory=$fopen(fixture_inventory,"r");require(inventory!=0,"fixture inventory");
  summary_file=$fopen({outdir,"/epochs.csv"},"w");
  $fwrite(summary_file,"case,rf_mode,pairs,gain,threshold,sparse,y_samples,spectral_bytes,clips,cycles\n");
  repeat(3)tick();rst_n=1;idle();rd(0,value);require(value==32'h54524631,"magic");rd(4,value);require(value=='h10000,"ABI");
  for(integer j=0;j<8;j++)begin rd('h080+4*j,value);require(value===TEST_SOURCE_ID[32*j+:32],"SOURCE_ID");end
  rd('h05c,value);require(value==NS,"Ns");rd('h06c,value);require(value==NY,"Ny");rd('h070,value);require(value==NFRAMES,"frames");
  rd('h0a0,value);require(value==512,"defaultpairs");rd('h0a4,value);require(value==1,"defaultgain");
  bad(1,1,0,0,15,1);bad('h100,1,0,0,15,1);bad(0,1,0,0,7,1);bad(0,1,0,0,15,0);bad(0,1,1,0,15,1);
  bad('h018,0,1,'h01000000,15,1);bad('h01c,0,1,2,15,1);bad('h020,0,1,0,15,1);
  bad('h040,1,0,0,15,1);bad('h044,1,0,0,15,1);
  bad('h0a0,0,1,0,15,1);bad('h0a0,0,1,513,15,1);bad('h0a4,0,1,4,15,1);
  wr('h010,2);epoch++;repeat(20)tick();bad('h014,0,1,1,15,1);
  wr('h010,2);epoch++;repeat(20)tick();bad('h0a0,0,1,128,15,1);
  wr('h010,2);epoch++;repeat(20)tick();bad('h0a4,0,1,2,15,1);
  wr('h010,2);epoch++;repeat(20)tick();bad('h020,0,1,'h10000,15,1);
  wr('h010,2);epoch++;wait_input_ready();wr('h020,'hff00);repeat(10)tick();clear();negatives++;
  for(case_id=0;case_id<16;case_id++)begin
   parsed=$fscanf(inventory,"%s %s %d %d %d %h %d\n",iq_path,x_path,pairs,gain,expected_clips,threshold,mode);require(parsed==7,"case row");
   $readmemh(iq_path,iq_gold,0,pairs-1);$readmemh(x_path,x_gold);
   for(pass=0;pass<2;pass++)begin
    phase=-1;rf_mode=(pass==1);clear();
    source_seen=0;y_seen=0;wire_seen=0;tap_seen=0;host_x=0;host_y=0;host_bytes=0;
    phase=2*case_id+pass;
    wr('h014,threshold[31:0]);wr('h018,{8'd0,threshold[55:32]});wr('h01c,mode);
    if(rf_mode)begin wr('h0a0,pairs);wr('h0a4,gain);end
    wr('h010,2);if(rf_mode)epoch++;start_cycle=cycles;host_limit=rf_mode?pairs:NS;
    status=0;finished=0;
    while(!finished)begin
     rd('h008,status);require(!status[2],"epoch fault");
     rd('h030,slevel);rd('h034,ylevel);
     if(cycles-start_cycle>120000)begin
      limit=(slevel>64)?64:slevel;
      for(integer j=0;j<limit;j++)begin rd('h040,v);
       for(integer k=0;k<4;k++)begin require(host_bytes<32768&&v[8*k+:8]===wire_gold[host_bytes],"host spectral packing/pop");host_bytes++;end
      end
     end
     if(cycles-start_cycle>200000)begin
      limit=(ylevel>64)?64:ylevel;
      for(integer j=0;j<limit;j++)begin rd('h044,v);require(host_y<NY&&v=={{20{y_gold[host_y][11]}},y_gold[host_y]},"host Y pop/sign");host_y++;end
     end
     rd('h008,status);
     if(status[3]&&host_x<host_limit)begin
      rd('h03c,free_slots);limit=(free_slots>64)?64:free_slots;
      if(limit>host_limit-host_x)limit=host_limit-host_x;
      for(integer j=0;j<limit;j++)begin
       if(rf_mode)wr('h020,{16'd0,iq_gold[host_x]});
       else wr('h020,{{20{x_gold[host_x][11]}},x_gold[host_x]});
       host_x++;
      end
     end
     if(status[1]&&slevel==0&&ylevel==0)finished=1;
     repeat(7)tick();if(cycles-start_cycle>800000)$fatal(1,"epoch loop bound");
    end
    require(status[1]&&!status[2],"DONE");
    require(host_x==host_limit&&source_seen==NY&&y_seen==NY&&host_y==NY&&host_bytes==wire_seen&&tap_seen==NFRAMES*129,"all counts");
    if(rf_mode)begin
     require(wire_seen==expected_bytes,"baseline spectral length");
     rd('h024,v);require(v==pairs,"IQ writes CSR");
     rd('h0a8,v);require(v==4*pairs,"RF valid sample total");rd('h0ac,v);require(v==pairs,"RF input total");
     rd('h0b0,v);require(v==expected_clips,"RF clipping total");
     rd('h0b4,v);require(v==(expected_clips?6:2),"RF completion status");
     rd('h0b8,v);require(v==4*pairs,"RF valid length");
     rd('h028,v);require(v==epoch,"one epoch per file");
    end else expected_bytes=wire_seen;
    rd('h058,v);require(v==NS,"real core inputs CSR");
    rd('h048,v);require(v==NY,"Y produced CSR");rd('h068,v);require(v==NY,"Y read CSR");
    rd('h060,v);require(v==host_bytes,"spectral bytes CSR");rd('h064,v);require(v*4==host_bytes,"spectral read CSR");
    rd('h050,v);require(v==0,"drops");rd('h054,v);require(v==NFRAMES,"emitted frames");
    rd('h030,v);require(v==0,"spectral empty");rd('h034,v);require(v==0,"Y empty");
    $fwrite(summary_file,"%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d\n",case_id,rf_mode,pairs,gain,threshold,mode,host_y,host_bytes,expected_clips,cycles-start_cycle);
    $display("EPOCH PASS case=%0d RF=%0d pairs=%0d thr=%0d sparse=%0d bytes=%0d cycles=%0d",case_id,rf_mode,pairs,threshold,mode,host_bytes,cycles-start_cycle);
    normal_epochs++;
   end
  end
  phase=-1;rf_mode=1;clear();rd('h028,v);require(v==epoch,"epoch persists CLEAR");
  require(input_full_cycles>0&&s_full_cycles>0&&y_full_cycles>0&&rf_stall_cycles>0,"all FIFO-full and RF backpressure exercised");
  checker_done=1;
  $display("PASS_RF_BOARD_ADAPTER epochs=%0d negatives=%0d checks=%0d transactions=%0d cycles=%0d iqfull=%0d spectralfull=%0d yfull=%0d rfstalls=%0d",normal_epochs,negatives,checks,transactions,cycles,input_full_cycles,s_full_cycles,y_full_cycles,rf_stall_cycles);
  $fclose(inventory);$fclose(summary_file);$finish;
 end
endmodule
`default_nettype wire
