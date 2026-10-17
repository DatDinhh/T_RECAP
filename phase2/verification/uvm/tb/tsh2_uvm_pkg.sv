`timescale 1ns/1ps
`include "uvm_macros.svh"
package tsh2_uvm_pkg;
  import uvm_pkg::*;
  typedef enum {START,PCM,SOURCE,Y,TAP,PACKET,COMPLETE,ABORT} event_kind;
  // Observed counters, not a simulator coverage database or a coverage percentage.
  typedef enum {CYCLES,INPUTS,SOURCES,YS,TAPS,BYTES,EMPTY,ONE,FULL,GAPS,Y_STALL,PACKET_STALL,FINAL_HOLD,MASKED,KEPT,INELIGIBLE,DISCONTINUITY} count_kind;
  localparam NC=17;

  class tsh2_config extends uvm_object;
    `uvm_object_utils(tsh2_config)
    virtual tsh2_if vif;
    string input_path[4],y_path[4],bin_path[4],packet_path[4],outdir;
    logic [55:0] threshold[4];
    int sparse[4],packet_bytes[4];
    logic [11:0] input_gold[0:1023];
    int unsigned seed;
    function new(string name="tsh2_config");super.new(name);endfunction
    function void load();
      string path;int f,n;
      if(!$value$plusargs("CASES=%s",path)||!$value$plusargs("OUT=%s",outdir)||!$value$plusargs("SEED=%d",seed))
        `uvm_fatal("CONFIG","Required CASES, OUT, SEED plusargs missing")
      if(seed==0) `uvm_fatal("CONFIG","Seed must be nonzero")
      f=$fopen(path,"r");if(!f) `uvm_fatal("CONFIG","Cannot open inventory")
      for(int i=0;i<4;i++)begin
        n=$fscanf(f,"%s %s %s %s %h %d %d\n",input_path[i],y_path[i],bin_path[i],packet_path[i],threshold[i],sparse[i],packet_bytes[i]);
        if(n!=7) `uvm_fatal("CONFIG","Inventory must contain exactly four valid cases")
      end
      $fclose(f);$readmemh(input_path[0],input_gold);
    endfunction
  endclass

  class epoch_item extends uvm_sequence_item;
    `uvm_object_utils(epoch_item)
    int case_id,epoch_id;bit abort_busy;
    function new(string name="epoch_item");super.new(name);endfunction
  endclass
  class epoch_sequence extends uvm_sequence#(epoch_item);
    `uvm_object_utils(epoch_sequence)
    function new(string name="epoch_sequence");super.new(name);endfunction
    task body();
      epoch_item req;
      for(int i=0;i<5;i++)begin
        req=epoch_item::type_id::create($sformatf("epoch%0d",i));
        start_item(req);req.epoch_id=i;req.case_id=(i==0)?0:i-1;req.abort_busy=(i==0);finish_item(req);
      end
    endtask
  endclass

  class epoch_driver extends uvm_driver#(epoch_item);
    `uvm_component_utils(epoch_driver)
    tsh2_config cfg;virtual tsh2_if vif;logic [31:0] rng;
    function new(string name,uvm_component parent);super.new(name,parent);endfunction
    function void build_phase(uvm_phase phase);
      if(!uvm_config_db#(tsh2_config)::get(this,"","cfg",cfg)) `uvm_fatal("CONFIG","Driver config missing")
      vif=cfg.vif;rng=cfg.seed;
    endfunction
    task falling();@(negedge vif.clk);#1;endtask
    task idle();vif.pcm_valid=0;vif.y_ready=0;vif.export_ready=0;vif.start=0;endtask
    task execute(epoch_item item);
      int sent,cycles,held;bit took,abort_now;
      sent=0;cycles=0;held=0;took=0;abort_now=0;
      falling();idle();vif.clear=1;falling();vif.clear=0;
      vif.case_id=item.case_id;vif.epoch_id=item.epoch_id;
      vif.threshold=cfg.threshold[item.case_id];vif.sparse=cfg.sparse[item.case_id];
      // RAM initialization after reset/clear is part of DUT busy, not an epoch.
      while(vif.top_busy)falling();
      vif.start=1;falling();vif.start=0;
      while(1)begin
        rng={rng[30:0],rng[31]^rng[21]^rng[1]^rng[0]};
        vif.y_ready=(vif.y_valid&&vif.y_idx==1535)?(held>=32+cfg.seed%32):((cycles%7000>=1000)&&rng[1]);
        vif.export_ready=(cycles%30000>=10000)&&rng[2];
        if(!vif.pcm_valid||took)begin
          vif.pcm_valid=(sent<1024)&&(cycles%1300>=220)&&(rng[3:0]!=0);
          vif.pcm_data=(sent<1024)?cfg.input_gold[sent]:0;
        end
        @(posedge vif.clk);
        took=vif.pcm_valid&&vif.pcm_ready;if(took)sent++;
        if(vif.y_valid&&!vif.y_ready&&vif.y_idx==1535)held++;
        abort_now=item.abort_busy&&vif.top_busy&&vif.tap_valid&&vif.tap_bin==16;
        falling();cycles++;
        if(abort_now)begin
          idle();vif.rst_n=0;repeat(3)falling();vif.rst_n=1;repeat(3)falling();break;
        end
        if(vif.top_done&&vif.emitted==9)begin repeat(3)falling();idle();break;end
        if(cycles>400000) `uvm_fatal("EPOCH_WATCHDOG","Epoch did not complete within cycle bound")
      end
    endtask
    task run_phase(uvm_phase phase);
      epoch_item req;
      idle();vif.rst_n=0;vif.clear=0;repeat(3)falling();vif.rst_n=1;
      forever begin seq_item_port.get_next_item(req);execute(req);seq_item_port.item_done();end
    endtask
  endclass

  class observed_item extends uvm_sequence_item;
    `uvm_object_utils(observed_item)
    event_kind kind;int case_id,epoch_id;
    logic [63:0] index,frame;
    logic signed [63:0] value,re,im;
    logic [55:0] mag,threshold;
    logic pre_mask,mask,eligible,last;
    longint unsigned counts[NC];
    logic [63:0] metric_count=0,sum_abs=0,sum_sq=0;
    logic [31:0] max_abs=0,schedule_hash=0;
    function new(string name="observed_item");super.new(name);endfunction
  endclass

  class stream_monitor extends uvm_monitor;
    `uvm_component_utils(stream_monitor)
    uvm_analysis_port#(observed_item) ap;
    tsh2_config cfg;virtual tsh2_if vif;
    bit active=0,y_stalled=0,packet_stalled=0,pcm_stalled=0;
    logic [11:0] held_y,held_pcm;logic [63:0] held_idx;logic [7:0] held_byte;
    longint unsigned counts[NC];logic [31:0] schedule_hash;
    int timing_file,reset_window=64,final_window=0;
    function new(string name,uvm_component parent);super.new(name,parent);ap=new("ap",this);endfunction
    function void build_phase(uvm_phase phase);
      if(!uvm_config_db#(tsh2_config)::get(this,"","cfg",cfg)) `uvm_fatal("CONFIG","Monitor config missing")
      vif=cfg.vif;
      timing_file=$fopen({cfg.outdir,"/timing.csv"},"w");if(!timing_file) `uvm_fatal("FILES","Cannot open measured timing trace")
      $fwrite(timing_file,"time_ns,epoch,case_id,rst_n,clear,start,start_accept,busy,done,y_valid,y_ready,y_index,y_data,packet_valid,packet_ready,tap_valid,tap_bin\n");
    endfunction
    function observed_item item(event_kind kind);
      observed_item t=observed_item::type_id::create("observed");
      t.kind=kind;t.case_id=vif.case_id;t.epoch_id=vif.epoch_id;
      return t;
    endfunction
    task run_phase(uvm_phase phase);
      observed_item t;
      forever begin
        @(posedge vif.clk);
        // Passive samples at actual clock edges, including reset windows,
        // early spectral bins, and final-Y hold/release. No inferred waveform.
        if(!vif.rst_n)reset_window=64;
        if(vif.y_valid&&vif.y_idx==1535)final_window=16;
        if(reset_window>0||final_window>0||(vif.tap_valid&&vif.tap_bin<24))
          $fwrite(timing_file,"%0d,%0d,%0d,%b,%b,%b,%b,%b,%b,%b,%b,%0d,%0d,%b,%b,%b,%0d\n",$time/1ns,vif.epoch_id,vif.case_id,vif.rst_n,vif.clear,vif.start,vif.start_accept,vif.top_busy,vif.top_done,vif.y_valid,vif.y_ready,vif.y_idx,$signed(vif.y_data),vif.export_valid,vif.export_ready,vif.tap_valid,vif.tap_bin);
        if(reset_window>0)reset_window--;if(final_window>0)final_window--;
        if(!vif.rst_n)begin
          if(active)begin t=item(ABORT);t.counts=counts;t.schedule_hash=schedule_hash;ap.write(t);end
          active=0;y_stalled=0;packet_stalled=0;pcm_stalled=0;
        end else if(vif.clear)begin
          if(active) `uvm_fatal("CLEAR_BUSY","Unexpected clear during an observed active epoch")
          y_stalled=0;packet_stalled=0;pcm_stalled=0;
        end else begin
          if(vif.start_accept)begin
            if(active) `uvm_fatal("DOUBLE_START","A new start overlapped an active epoch")
            active=1;foreach(counts[i])counts[i]=0;schedule_hash=32'h811c9dc5;
            t=item(START);ap.write(t);
            `uvm_info("EPOCH_STARTED",$sformatf("Observed accepted epoch=%0d case=%0d",vif.epoch_id,vif.case_id),UVM_LOW)
          end
          if(vif.start_reject) `uvm_fatal("START_REJECTED","Driver start was rejected")
          if(active)begin
            if((^{vif.pcm_valid,vif.pcm_ready,vif.y_valid,vif.y_ready,vif.source_valid,vif.source_ready,vif.export_valid,vif.export_ready,vif.top_busy,vif.top_done,vif.tap_valid})===1'bx)
              `uvm_fatal("UNKNOWN_CONTROL","Observed unknown control")
            if((vif.pcm_valid&&((^vif.pcm_data)===1'bx))||(vif.y_valid&&((^{vif.y_data,vif.y_idx})===1'bx))||(vif.export_valid&&((^vif.export_data)===1'bx)))
              `uvm_fatal("UNKNOWN_VALID_PAYLOAD","Valid PCM, Y or packet payload contains X/Z, including stalls")
            if(vif.completion_fault||vif.build_fault||vif.protocol_fault||vif.metric_fault||vif.saturation_fault||vif.start_reject||vif.export_overflow||vif.export_protocol||vif.overflow!=0||vif.dropped!=0)
              `uvm_fatal("DUT_FAULT","Unexpected DUT sticky fault or rejected start")
            if(vif.queued>1||vif.frames>vif.emitted+1) `uvm_fatal("FRAME_CREDIT","More than one uncommitted frame")
            if(vif.top_done&&counts[YS]!=1536) `uvm_fatal("EARLY_DONE","DONE preceded the final Y transfer")
            if(y_stalled&&!(vif.y_valid&&vif.y_data===held_y&&vif.y_idx===held_idx)) `uvm_fatal("Y_STABILITY","Y changed while stalled")
            if(packet_stalled&&!(vif.export_valid&&vif.export_data===held_byte)) `uvm_fatal("PACKET_STABILITY","Packet byte changed while stalled")
            if(pcm_stalled&&!(vif.pcm_valid&&vif.pcm_data===held_pcm)) `uvm_fatal("PCM_STABILITY","Driver changed a blocked input")
            y_stalled=vif.y_valid&&!vif.y_ready;held_y=vif.y_data;held_idx=vif.y_idx;
            packet_stalled=vif.export_valid&&!vif.export_ready;held_byte=vif.export_data;
            pcm_stalled=vif.pcm_valid&&!vif.pcm_ready;held_pcm=vif.pcm_data;
            counts[CYCLES]++;counts[EMPTY]+=(vif.fifo_level==0);counts[ONE]+=(vif.fifo_level==1);counts[FULL]+=(vif.fifo_level==256);
            counts[GAPS]+=(!vif.pcm_valid&&counts[INPUTS]<1024);counts[Y_STALL]+=y_stalled;counts[PACKET_STALL]+=packet_stalled;
            counts[DISCONTINUITY]+=vif.discontinuity;
            schedule_hash=(schedule_hash^{24'd0,vif.pcm_valid,vif.pcm_ready,vif.y_valid,vif.y_ready,vif.source_valid,vif.source_ready,vif.export_valid,vif.export_ready})*32'd16777619;
            if(y_stalled&&vif.y_idx==1535)begin
              counts[FINAL_HOLD]++;
              if(!vif.top_busy||vif.top_done) `uvm_fatal("FINAL_Y_COMPLETION","Final Y stall must retain busy")
            end
            if(vif.pcm_valid&&vif.pcm_ready)begin t=item(PCM);t.index=counts[INPUTS];t.value=$signed(vif.pcm_data);counts[INPUTS]++;ap.write(t);end
            if(vif.source_valid&&vif.source_ready)begin t=item(SOURCE);t.index=vif.source_idx;t.value=$signed(vif.source_data);counts[SOURCES]++;ap.write(t);end
            if(vif.y_valid&&vif.y_ready)begin t=item(Y);t.index=vif.y_idx;t.value=$signed(vif.y_data);counts[YS]++;ap.write(t);end
            if(vif.tap_valid)begin
              if((^{vif.tap_frame,vif.tap_bin,vif.tap_re,vif.tap_im,vif.tap_mag,vif.tap_pre_mask,vif.tap_mask,vif.tap_eligible,vif.tap_last,vif.tap_threshold})===1'bx) `uvm_fatal("UNKNOWN_TAP","Observed unknown spectral tap")
              t=item(TAP);t.index=vif.tap_bin;t.frame=vif.tap_frame;t.re=$signed(vif.tap_re);t.im=$signed(vif.tap_im);t.mag=vif.tap_mag;t.threshold=vif.tap_threshold;t.pre_mask=vif.tap_pre_mask;t.mask=vif.tap_mask;t.eligible=vif.tap_eligible;t.last=vif.tap_last;
              counts[TAPS]++;counts[MASKED]+=vif.tap_mask;counts[KEPT]+=vif.tap_eligible&&!vif.tap_mask;counts[INELIGIBLE]+=!vif.tap_eligible;ap.write(t);
            end
            if(vif.export_valid&&vif.export_ready)begin t=item(PACKET);t.index=counts[BYTES];t.value=vif.export_data;counts[BYTES]++;ap.write(t);end
            if(vif.top_done&&vif.emitted==9)begin
              if(vif.pcm_accepted!=1024||vif.fifo_level!=0||vif.frames!=9||vif.accepted!=9) `uvm_fatal("DUT_FINAL_COUNTS","Final DUT counters differ from finite geometry")
              t=item(COMPLETE);t.counts=counts;t.schedule_hash=schedule_hash;t.metric_count=vif.metric_count;t.sum_abs=vif.sum_abs;t.sum_sq=vif.sum_sq;t.max_abs=vif.max_abs;
              ap.write(t);active=0;y_stalled=0;packet_stalled=0;pcm_stalled=0;
            end
          end else if(vif.y_valid||vif.tap_valid||vif.export_valid) `uvm_fatal("ORPHAN_OUTPUT","Output observed outside an accepted epoch")
        end
      end
    endtask
    function void final_phase(uvm_phase phase);$fclose(timing_file);endfunction
  endclass

  class stream_scoreboard extends uvm_scoreboard;
    `uvm_component_utils(stream_scoreboard)
    uvm_analysis_imp#(observed_item,stream_scoreboard) observed;
    tsh2_config cfg;logic [11:0] yg[4][1536];logic [7:0] pg[4][16384];
    longint signed tr[4][1161],ti[4][1161];longint unsigned tm[4][1161];
    int tf[4][1161],tb[4][1161],te[4][1161],tp[4][1161],tk[4][1161];
    longint unsigned expected_abs[4],expected_sq[4],expected_max[4];
    int pc,sc,yc,tc,bc,completed=0,aborted=0,active_case=-1,active_epoch=-1;
    bit active=0;int trace_file,coverage_file;
    function new(string name,uvm_component parent);super.new(name,parent);observed=new("observed",this);endfunction
    function void build_phase(uvm_phase phase);
      int f,n;string header;longint signed e,x,y;
      if(!uvm_config_db#(tsh2_config)::get(this,"","cfg",cfg)) `uvm_fatal("CONFIG","Scoreboard config missing")
      for(int c=0;c<4;c++)begin
        // Explicit file reads avoid older ModelSim multidimensional-array slice
        // limitations in $readmemh. Every expected element must parse.
        f=$fopen(cfg.y_path[c],"r");if(!f) `uvm_fatal("GOLD","Missing Y reference")
        for(int i=0;i<1536;i++)begin n=$fscanf(f,"%h\n",yg[c][i]);if(n!=1) `uvm_fatal("GOLD","Invalid Y element") end
        $fclose(f);
        f=$fopen(cfg.packet_path[c],"r");if(!f) `uvm_fatal("GOLD","Missing packet reference")
        for(int i=0;i<cfg.packet_bytes[c];i++)begin n=$fscanf(f,"%h\n",pg[c][i]);if(n!=1) `uvm_fatal("GOLD","Invalid packet element") end
        $fclose(f);
        f=$fopen(cfg.bin_path[c],"r");if(!f) `uvm_fatal("GOLD","Missing bin reference")
        n=$fgets(header,f);
        for(int i=0;i<1161;i++)begin
          n=$fscanf(f,"%d,%d,%d,%d,%d,%d,%d,%d\n",tf[c][i],tb[c][i],tr[c][i],ti[c][i],tm[c][i],te[c][i],tp[c][i],tk[c][i]);
          if(n!=8) `uvm_fatal("GOLD","Invalid bin reference row")
        end
        $fclose(f);expected_abs[c]=0;expected_sq[c]=0;expected_max[c]=0;
        for(int i=0;i<1536;i++)begin
          x=(i>=384&&i<1408)?$signed(cfg.input_gold[i-384]):0;y=$signed(yg[c][i]);e=x-y;
          expected_abs[c]+=(e<0)?-e:e;expected_sq[c]+=e*e;if(((e<0)?-e:e)>expected_max[c])expected_max[c]=(e<0)?-e:e;
        end
      end
      if($test$plusargs("INJECT_BAD_Y"))for(int c=0;c<4;c++)yg[c][0]^=12'd1;
      trace_file=$fopen({cfg.outdir,"/observed.csv"},"w");coverage_file=$fopen({cfg.outdir,"/coverage.csv"},"w");
      if(!trace_file||!coverage_file) `uvm_fatal("FILES","Cannot open result traces")
      $fwrite(trace_file,"epoch,case_id,kind,index,frame,value,real,imag,mag2,threshold,pre_mask,mask,eligible,last\n");
      $fwrite(coverage_file,"epoch,case_id,status,seed,cycles,inputs,sources,y,taps,bytes,fifo_empty,fifo_one,fifo_full,input_gaps,y_stalls,packet_stalls,final_y_hold,masked,kept,ineligible,discontinuities,schedule_hash,metric_count,sum_abs,sum_sq,max_abs\n");
    endfunction
    function void write(observed_item t);
      int c;longint signed expected;
      c=t.case_id;
      if(t.kind==START)begin
        if(active) `uvm_fatal("SCOREBOARD_EPOCH","Overlapping epoch")
        active=1;active_case=c;active_epoch=t.epoch_id;pc=0;sc=0;yc=0;tc=0;bc=0;
      end else begin
        if(!active||c!=active_case||t.epoch_id!=active_epoch) `uvm_fatal("STALE_OUTPUT","Observation belongs to no current epoch")
        case(t.kind)
          PCM:begin
            if(pc>=1024||t.index!=pc||t.value!==$signed(cfg.input_gold[pc])) `uvm_fatal("PCM_GOLD_MISMATCH",$sformatf("epoch%0d input%0d",t.epoch_id,pc))
            pc++;
          end
          SOURCE:begin
            expected=(sc<1024)?$signed(cfg.input_gold[sc]):0;
            if(sc>=1536||t.index!=sc||t.value!==expected) `uvm_fatal("SOURCE_GOLD_MISMATCH",$sformatf("epoch%0d source%0d",t.epoch_id,sc))
            sc++;
          end
          Y:begin
            if(yc>=1536||t.index!=yc||t.value!==$signed(yg[c][yc])) `uvm_fatal("Y_GOLD_MISMATCH",$sformatf("epoch%0d Y%0d observed=%0d",t.epoch_id,yc,t.value))
            yc++;
          end
          TAP:begin
            if(tc>=1161||t.frame!==tf[c][tc]||t.index!==tb[c][tc]||t.re!==tr[c][tc]||t.im!==ti[c][tc]||t.mag!==tm[c][tc]||t.eligible!==te[c][tc]||t.pre_mask!==tp[c][tc]||t.mask!==tk[c][tc]||t.threshold!==cfg.threshold[c]||t.last!==(t.index==128)) `uvm_fatal("TAP_GOLD_MISMATCH",$sformatf("epoch%0d tap%0d",t.epoch_id,tc))
            tc++;
          end
          PACKET:begin
            if(bc>=cfg.packet_bytes[c]||t.index!=bc||t.value!==pg[c][bc]) `uvm_fatal("PACKET_GOLD_MISMATCH",$sformatf("epoch%0d byte%0d",t.epoch_id,bc))
            bc++;
          end
          ABORT:begin
            if(t.epoch_id!=0||pc==0||tc<16||tc>=1161) `uvm_fatal("RESET_COVERAGE","Reset did not interrupt an observed busy spectral prefix")
            aborted++;active=0;
            `uvm_info("RESET_ABORT_CHECKED",$sformatf("Observed reset aborted prefix: PCM=%0d source=%0d Y=%0d taps=%0d bytes=%0d",pc,sc,yc,tc,bc),UVM_LOW)
          end
          COMPLETE:begin
            if(pc!=1024||sc!=1536||yc!=1536||tc!=1161||bc!=cfg.packet_bytes[c]) `uvm_fatal("EXACT_COUNTS","Completed epoch has missing or extra records")
            if(t.metric_count!=1536||t.sum_abs!=expected_abs[c]||t.sum_sq!=expected_sq[c]||t.max_abs!=expected_max[c]) `uvm_fatal("METRIC_MISMATCH","Final time-domain metrics differ")
            if(t.counts[EMPTY]==0||t.counts[ONE]==0||t.counts[FULL]==0||t.counts[GAPS]==0||t.counts[Y_STALL]==0||t.counts[PACKET_STALL]==0||t.counts[FINAL_HOLD]!=32+cfg.seed%32||t.counts[DISCONTINUITY]!=1) `uvm_fatal("UNHIT_EVENT","Required observed flow-control bin missing")
            completed++;active=0;
            `uvm_info("EPOCH_CHECKED",$sformatf("epoch=%0d case=%0d seed=%0d exact PCM1024/source1536/Y1536/taps1161/packet%0d",t.epoch_id,c,cfg.seed,bc),UVM_LOW)
          end
        endcase
      end
      if(t.kind==COMPLETE||t.kind==ABORT)begin
        $fwrite(coverage_file,"%0d,%0d,%s,%0d",t.epoch_id,c,t.kind.name(),cfg.seed);
        foreach(t.counts[i])$fwrite(coverage_file,",%0d",t.counts[i]);
        $fwrite(coverage_file,",%0d,%0d,%0d,%0d,%0d\n",t.schedule_hash,t.metric_count,t.sum_abs,t.sum_sq,t.max_abs);
      end else $fwrite(trace_file,"%0d,%0d,%s,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d\n",t.epoch_id,c,t.kind.name(),t.index,t.frame,t.value,t.re,t.im,t.mag,t.threshold,t.pre_mask,t.mask,t.eligible,t.last);
    endfunction
    function void check_phase(uvm_phase phase);
      if(active||completed!=4||aborted!=1) `uvm_fatal("INCOMPLETE_TEST",$sformatf("completed=%0d aborted=%0d active=%0d",completed,aborted,active))
    endfunction
    function void final_phase(uvm_phase phase);$fclose(trace_file);$fclose(coverage_file);endfunction
  endclass

  class tsh2_agent extends uvm_agent;
    `uvm_component_utils(tsh2_agent)
    uvm_sequencer#(epoch_item) sequencer;epoch_driver driver;stream_monitor monitor;
    function new(string name,uvm_component parent);super.new(name,parent);endfunction
    function void build_phase(uvm_phase phase);
      sequencer=uvm_sequencer#(epoch_item)::type_id::create("sequencer",this);
      driver=epoch_driver::type_id::create("driver",this);monitor=stream_monitor::type_id::create("monitor",this);
    endfunction
    function void connect_phase(uvm_phase phase);driver.seq_item_port.connect(sequencer.seq_item_export);endfunction
  endclass
  class tsh2_env extends uvm_env;
    `uvm_component_utils(tsh2_env)
    tsh2_agent agent;stream_scoreboard scoreboard;
    function new(string name,uvm_component parent);super.new(name,parent);endfunction
    function void build_phase(uvm_phase phase);agent=tsh2_agent::type_id::create("agent",this);scoreboard=stream_scoreboard::type_id::create("scoreboard",this);endfunction
    function void connect_phase(uvm_phase phase);agent.monitor.ap.connect(scoreboard.observed);endfunction
  endclass
  class tsh2_test extends uvm_test;
    `uvm_component_utils(tsh2_test)
    tsh2_config cfg;tsh2_env env;
    function new(string name,uvm_component parent);super.new(name,parent);endfunction
    function void build_phase(uvm_phase phase);
      cfg=tsh2_config::type_id::create("cfg");
      if(!uvm_config_db#(virtual tsh2_if)::get(this,"","vif",cfg.vif)) `uvm_fatal("CONFIG","Virtual interface missing")
      cfg.load();uvm_config_db#(tsh2_config)::set(this,"*","cfg",cfg);env=tsh2_env::type_id::create("env",this);
    endfunction
    task run_phase(uvm_phase phase);
      epoch_sequence seq=epoch_sequence::type_id::create("seq");
      phase.raise_objection(this);seq.start(env.agent.sequencer);repeat(5)@(posedge cfg.vif.clk);phase.drop_objection(this);
    endtask
    function void report_phase(uvm_phase phase);
      uvm_report_server reports=uvm_report_server::get_server();
      if(env.scoreboard.completed==4&&env.scoreboard.aborted==1&&reports.get_severity_count(UVM_ERROR)==0&&reports.get_severity_count(UVM_FATAL)==0)begin
        cfg.vif.checker_done=1;
        `uvm_info("TSH2_UVM_COMPLETE",$sformatf("seed=%0d completed=4 reset_aborts=1",cfg.seed),UVM_NONE)
      end
    endfunction
  endclass
endpackage
