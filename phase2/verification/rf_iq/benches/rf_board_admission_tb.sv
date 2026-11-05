`timescale 1ns/1ps
`default_nettype none
module rf_board_admission_tb;
 reg clk=0;always #5 clk=~clk;
 reg rst_n=0;
 reg [20:0] avs_address=0;
 reg avs_read=0,avs_write=0,avs_burstcount=1;
 reg [31:0] avs_writedata=0;
 reg [3:0] avs_byteenable=15;
 wire avs_waitrequest,avs_readdatavalid,avs_writeresponsevalid;
 wire [31:0] avs_readdata;wire [1:0] avs_response;
 `include "source_id.svh"
 trecap_rf_board_adapter #(.SOURCE_ID(TEST_SOURCE_ID),.INPUT_SAMPLES(2048),.WATCHDOG_CYCLES(10000)) dut(.*);
 integer checker_done=0,checks=0,cycles=0;
 integer reset_wait=0;
 string wave;
 reg [31:0] value;
 task require(input logic ok,input string why);begin checks++;if(ok!==1'b1)$fatal(1,"cycle%0d %s",cycles,why);end endtask
 task tick;begin @(negedge clk);end endtask
 task access(input reg [20:0] address,input reg write,input reg [31:0] data,input reg [1:0] expected,output reg [31:0] result);
 integer waits;begin
  waits=0;while(avs_waitrequest)begin tick();waits++;if(waits>12)$fatal(1,"accept timeout");end
  avs_address=address;avs_read=!write;avs_write=write;avs_writedata=data;avs_byteenable=15;avs_burstcount=1;
  tick();avs_read=0;avs_write=0;
  waits=0;while(!avs_readdatavalid&&!avs_writeresponsevalid)begin tick();waits++;if(waits>8)$fatal(1,"response timeout");end
  require(avs_response===expected,$sformatf("response addr%h expected%d actual%d",address,expected,avs_response));
  require(avs_readdatavalid===!write&&avs_writeresponsevalid===write,"response direction");result=avs_readdata;
 end endtask
 task wr(input reg [20:0] address,input reg [31:0] data);reg [31:0] q;begin access(address,1,data,0,q);end endtask
 task rd(input reg [20:0] address);begin access(address,0,0,0,value);end endtask
 task wait_idle;integer n;begin
  n=0;rd('h008);while(value[0])begin rd('h008);n++;if(n>2000)$fatal(1,"idle timeout");end require(value==0,"idle state");
 end endtask
 task clear;begin wr('h010,1);wait_idle();end endtask
 task start_ready;integer n;begin
  wr('h0a0,128);wr('h0a4,1);wr('h010,2);n=0;rd('h008);
  while(!value[3])begin require(!value[2],"fault before ready");rd('h008);n++;if(n>2000)$fatal(1,"ready timeout");end
  require(dut.pcm_ready&&dut.state==5,"actual RUN admission");
 end endtask
 always @(posedge clk)begin cycles++;if(cycles>50000)$fatal(1,"global timeout");end
 initial begin
  if($value$plusargs("VCD=%s",wave))begin $dumpfile(wave);$dumpvars(1,rf_board_admission_tb);$dumpvars(1,dut);end
  repeat(3)tick();rst_n=1;wait_idle();
  start_ready();wr('h020,'h0000ff00);rd('h024);require(value==1,"valid unsigned pair accepted");
  rd('h008);require(value[3]&&dut.pcm_ready,"bad-word test must have free input capacity");
  access('h020,1,'h00010000,2,value);
  rd('h00c);require(value==1,"bad upper16 causes only bus fault");
  rd('h024);require(value==1,"bad upper16 not enqueued");
  clear();rd('h024);require(value==0,"clear host count");rd('h0b4);require(value==0,"clear RF state");
  start_ready();access('h0a4,1,2,2,value);rd('h00c);require(value==1,"gain write while RUN rejected");
  rd('h0a4);require(value==1,"busy gain did not change");
  clear();start_ready();
  repeat(11000)tick();rd('h008);require(value[2]&&!value[1]&&!value[0],"stalled-source watchdog faults");
  rd('h00c);require(value==8,"watchdog fault category");
  clear();rd('h00c);require(value==0,"watchdog recovery");
  start_ready();
  // Drive one legal write, then abort before the registered prefetch is consumed.
  avs_address='h020;avs_read=0;avs_write=1;avs_writedata='h0000ff00;avs_byteenable=15;avs_burstcount=1;
  tick();avs_write=0;reset_wait=0;
  while(!dut.iq_pending)begin tick();reset_wait++;if(reset_wait>40)$fatal(1,"prefetch pending not reached");end
  require(dut.iq_pending,"reset actually observes pending prefetch");
  #1;rst_n=0;avs_read=0;avs_write=0;#1;
  require(!dut.iq_pending&&!dut.iq_stage_valid&&!dut.rf_started,"reset clears prefetch state");
  repeat(3)tick();rst_n=1;wait_idle();rd('h024);require(value==0,"reset host count");
  start_ready();wr('h020,'h0000ff00);wr('h020,'h000000ff);
  reset_wait=0;
  while(!(dut.iq_stage_valid&&!dut.rf_iq_ready))begin tick();reset_wait++;if(reset_wait>40)$fatal(1,"held prefetch not reached");end
  require(dut.iq_stage_valid&&!dut.rf_iq_ready,"clear actually observes held prefetch");
  clear();require(!dut.iq_pending&&!dut.iq_stage_valid&&!dut.rf_started,"clear cancels held prefetch");
  rd('h024);require(value==0,"clear cancels host count");rd('h0ac);require(value==0,"clear cancels adapter count");
  start_ready();wr('h020,'h00008080);rd('h024);require(value==1,"restart accepts fresh pair");clear();
  checker_done=1;
  $display("PASS_RF_BOARD_ADMISSION checks=%0d cycles=%0d ready_bad_word=1 busy_config=1 watchdog_recovery=1 pending_prefetch_reset=1 held_prefetch_clear=1",checks,cycles);
  $finish;
 end
endmodule
`default_nettype wire
