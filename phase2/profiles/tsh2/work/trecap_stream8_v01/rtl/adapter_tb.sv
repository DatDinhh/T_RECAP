`timescale 1ns/1ps
module adapter_tb;
 reg clk=0;always #5 clk=~clk;
 reg rst_n=0;
 reg [20:0] avs_address=0;
 reg avs_read=0,avs_write=0,avs_burstcount=1;
 reg [31:0] avs_writedata=0;
 reg [3:0] avs_byteenable=15;
 wire avs_waitrequest,avs_readdatavalid,avs_writeresponsevalid;
 wire [31:0] avs_readdata;wire [1:0] avs_response;
 `include "source_id.svh"
 trecap_stream_adapter #(.SOURCE_ID(TEST_SOURCE_ID),.INPUT_SAMPLES(1024),.WATCHDOG_CYCLES(1000000)) dut(.*);
 reg [11:0] x_gold[0:1023],y_gold[0:1535];reg [7:0] wire_gold[0:16383];
 reg [55:0] threshold;reg [31:0] value,v,slevel,ylevel,free_slots,status;
 integer phase=-1,checks=0,cycles=0,transactions=0,negatives=0,start_cycle;
 integer source_seen=0,y_seen=0,wire_seen=0,host_x,host_y,host_bytes,tap_seen;
 integer input_full_cycles=0,s_full_cycles=0,y_full_cycles=0;
 integer inventory,parsed,mode,expected_bytes,epoch=0,n,limit;
 string outdir,fixture_inventory,x_path,y_path,wire_path;
 task require(input logic ok,input string why);begin checks++;if(ok!==1'b1)$fatal(1,"phase%0d cycle%0d %s",phase,cycles,why);end endtask
 task tick;begin @(negedge clk);end endtask
 task access(input reg [20:0] address,input reg r,input reg w,input reg [31:0] data,input reg [3:0] be,input reg burst,input reg [1:0] expected,output reg [31:0] result);
 integer waits;begin
  waits=0;while(avs_waitrequest)begin tick();waits++;if(waits>12)$fatal(1,"accept timeout");end
  avs_address=address;avs_read=r;avs_write=w;avs_writedata=data;avs_byteenable=be;avs_burstcount=burst;
  tick();avs_read=0;avs_write=0;avs_address=~address;avs_writedata=~data;avs_byteenable=0;avs_burstcount=0;
  waits=0;while(!avs_readdatavalid&&!avs_writeresponsevalid)begin tick();waits++;if(waits>8)$fatal(1,"response timeout");end
  require(avs_readdatavalid===r&&avs_writeresponsevalid===w,"response direction");require(avs_response===expected,"response code");result=avs_readdata;transactions++;
 end endtask
 task wr(input reg [20:0] a,input reg [31:0] d);reg [31:0] q;begin access(a,0,1,d,15,1,0,q);end endtask
 task rd(input reg [20:0] a,output reg [31:0] q);begin access(a,1,0,0,15,1,0,q);end endtask
 task idle;integer i;begin i=0;rd('h008,value);while(value[0])begin rd('h008,value);i++;if(i>2000)$fatal(1,"clear timeout");end require(value==0,"empty idle");end endtask
 task clear;begin wr('h010,1);idle();end endtask
 task bad(input reg [20:0] a,input reg r,input reg w,input reg [31:0] d,input reg [3:0] be,input reg burst);begin
  access(a,r,w,d,be,burst,2,value);rd('h008,value);require(value[2]&&!value[1],"bad access did not fault");negatives++;clear();
 end endtask
 always @(posedge clk)begin
  cycles++;if(cycles>3500000)$fatal(1,"global timeout");
  if(rst_n&&phase>=0)begin
   if(dut.pcm_level==256)input_full_cycles++;
   if(dut.s_full)s_full_cycles++;
   if(dut.y_full)y_full_cycles++;
   if(dut.source_valid&&dut.source_ready)begin
    require(dut.source_idx==source_seen,"source index");
    require(dut.core.source_sample_data_o===((source_seen<1024)?x_gold[source_seen]:12'd0),"source PCM/flush");source_seen++;
   end
   if(dut.y_good)begin require(y_seen<1536&&dut.y_idx==y_seen&&dut.y_data===y_gold[y_seen],"Y numerical output");y_seen++;end
   if(dut.export_take)begin require(wire_seen<expected_bytes&&dut.export_data===wire_gold[wire_seen],"spectral byte output");wire_seen++;end
   if(dut.tap_valid)tap_seen++;
  end
 end
 initial begin
  if(!$value$plusargs("OUT=%s",outdir)||!$value$plusargs("CASES=%s",fixture_inventory))$fatal(1,"OUT/CASES required");
  inventory=$fopen(fixture_inventory,"r");require(inventory!=0,"fixture inventory");
  repeat(3)tick();rst_n=1;idle();rd(0,value);require(value==32'h54534832,"magic");rd(4,value);require(value=='h20000,"ABI");
  for(integer j=0;j<8;j++)begin rd('h080+4*j,value);require(value===TEST_SOURCE_ID[32*j+:32],"SOURCE_ID");end
  rd('h05c,value);require(value==1024,"Ns");rd('h06c,value);require(value==1536,"Ny");rd('h070,value);require(value==9,"frames");
  bad(1,1,0,0,15,1);bad('h100,1,0,0,15,1);bad(0,1,0,0,7,1);bad(0,1,0,0,15,0);bad(0,1,1,0,15,1);
  bad('h018,0,1,'h01000000,15,1);bad('h01c,0,1,2,15,1);bad('h020,0,1,0,15,1);
  bad('h040,1,0,0,15,1);bad('h044,1,0,0,15,1);
  wr('h010,2);epoch++;repeat(20)tick();bad('h014,0,1,1,15,1);
  wr('h010,2);epoch++;repeat(20)tick();bad('h020,0,1,2048,15,1);
  wr('h010,2);epoch++;repeat(20)tick();clear();negatives++;
  for(phase=0;phase<12;phase++)begin
   parsed=$fscanf(inventory,"%s %s %s %h %d %d\n",x_path,y_path,wire_path,threshold,mode,expected_bytes);require(parsed==6,"case row");
   $readmemh(x_path,x_gold);$readmemh(y_path,y_gold);$readmemh(wire_path,wire_gold,0,expected_bytes-1);
   clear();source_seen=0;y_seen=0;wire_seen=0;tap_seen=0;host_x=0;host_y=0;host_bytes=0;
   wr('h014,threshold[31:0]);wr('h018,{8'd0,threshold[55:32]});wr('h01c,mode);wr('h010,2);epoch++;start_cycle=cycles;
   status=0;n=0;
   while(!status[1]||host_y<1536||host_bytes<expected_bytes)begin
    rd('h008,status);require(!status[2],"epoch fault");
    rd('h030,slevel);rd('h034,ylevel);
    if(cycles-start_cycle>60000)begin
     limit=(slevel>64)?64:slevel;
     for(integer j=0;j<limit;j++)begin rd('h040,v);
      for(integer k=0;k<4;k++)begin require(host_bytes<expected_bytes&&v[8*k+:8]===wire_gold[host_bytes],"host spectral packing/pop");host_bytes++;end
     end
    end
    if(cycles-start_cycle>110000)begin
     limit=(ylevel>64)?64:ylevel;
     for(integer j=0;j<limit;j++)begin rd('h044,v);require(host_y<1536&&v=={{20{y_gold[host_y][11]}},y_gold[host_y]},"host Y pop/sign");host_y++;end
    end
    rd('h008,status);
    if(status[3]&&host_x<1024)begin
     rd('h03c,free_slots);limit=(free_slots>32)?32:free_slots;
     if(limit>1024-host_x)limit=1024-host_x;
     for(integer j=0;j<limit;j++)begin wr('h020,{{20{x_gold[host_x][11]}},x_gold[host_x]});host_x++;end
    end
    repeat(7)tick();n++;if(n>12000)$fatal(1,"epoch loop bound");
   end
   require(status[1]&&!status[2],"DONE");require(host_x==1024&&source_seen==1536&&y_seen==1536&&wire_seen==expected_bytes&&tap_seen==1161,"all counts");
   rd('h024,v);require(v==1024,"PCM writes CSR");rd('h058,v);require(v==1024,"PCM consumed CSR");
   rd('h048,v);require(v==1536,"Y produced CSR");rd('h068,v);require(v==1536,"Y read CSR");
   rd('h060,v);require(v==expected_bytes,"spectral bytes CSR");rd('h064,v);require(v*4==expected_bytes,"spectral read CSR");
   rd('h050,v);require(v==0,"drops");rd('h054,v);require(v==9,"emitted frames");rd('h028,v);require(v==epoch,"one epoch per full input");
   rd('h030,v);require(v==0,"spectral empty");rd('h034,v);require(v==0,"Y empty");
   $display("EPOCH PASS phase=%0d thr=%0d sparse=%0d bytes=%0d cycles=%0d",phase,threshold,mode,host_bytes,cycles-start_cycle);
  end
  phase=-1;clear();rd('h028,v);require(v==epoch,"epoch persists CLEAR");
  require(input_full_cycles>0&&s_full_cycles>0&&y_full_cycles>0,"all FIFO-full backpressure exercised");
  $display("PASS streamadapter normal_epochs=12 negatives=%0d checks=%0d transactions=%0d cycles=%0d inputfull=%0d spectralfull=%0d yfull=%0d",negatives,checks,transactions,cycles,input_full_cycles,s_full_cycles,y_full_cycles);
  $fclose(inventory);$finish;
 end
endmodule
