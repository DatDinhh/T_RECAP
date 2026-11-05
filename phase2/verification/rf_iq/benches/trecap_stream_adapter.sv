// TSH2: one finite numerical epoch with streaming host input/output FIFOs.
`default_nettype none
module trecap_stream_adapter #(
    parameter [255:0] SOURCE_ID=256'd0,
    parameter integer INPUT_SAMPLES=384000,
    parameter [31:0] WATCHDOG_CYCLES=32'd3000000000
)(
    input wire clk,rst_n,
    input wire [20:0] avs_address,input wire avs_read,avs_write,
    input wire [31:0] avs_writedata,input wire [3:0] avs_byteenable,
    input wire avs_burstcount,output wire avs_waitrequest,
    output reg [31:0] avs_readdata,output reg avs_readdatavalid,
    output reg avs_writeresponsevalid,output reg [1:0] avs_response
);
    localparam integer FRAMES=(INPUT_SAMPLES+254)/128;
    localparam integer OUTPUT_SAMPLES=(FRAMES-1)*128+512;
    localparam [2:0] B_IDLE=0,B_EXEC=1,B_DATA=2,B_REPLY=3;
    localparam [3:0] IDLE=0,CLEAR_CORE=1,WAIT_INIT=2,ISSUE_START=3,
        WAIT_ACCEPT=4,RUN=5,DRAIN=6,DONE=7,FAULT=8;
    reg [2:0] bus_state;
    reg [20:0] req_addr;
    reg req_read,req_write,req_burst;
    reg [3:0] req_be,state;
    reg [31:0] req_data,faults,loaded,y_count,input_count,elapsed;
    reg [31:0] spectral_bytes,spectral_read,y_read_count;
    reg [55:0] threshold;
    reg sparse,pending_run;
    reg [63:0] epoch;
    wire busy=state!=IDLE&&state!=DONE&&state!=FAULT;
    wire done=state==DONE&&faults==0;
    wire core_clear=state==CLEAR_CORE||state==FAULT;
    wire core_start=state==ISSUE_START;
    wire running=state==WAIT_ACCEPT||state==RUN||state==DRAIN;
    wire config_allowed=state==IDLE&&faults==0;
    wire top_busy,top_done,core_busy,start_accept,start_reject;
    wire completion_fault,build_fault,protocol_fault,metric_fault,saturation_fault;
    wire [31:0] overflow_flags;
    wire source_valid,source_ready,y_valid,start_discontinuity;
    wire [63:0] source_idx,y_idx,core_frames,pcm_accepted;
    wire signed [11:0] y_data;
    wire pcm_ready_raw;
    wire [31:0] pcm_level;
    wire pcm_ready=running&&!core_clear&&faults==0&&loaded<INPUT_SAMPLES&&pcm_ready_raw;
    wire tap_valid,tap_mask,tap_eligible,tap_last;
    wire [7:0] tap_bin;
    wire [63:0] tap_frame;
    wire [55:0] tap_mag,tap_threshold;
    wire export_valid,export_last,export_busy,export_overflow,export_protocol;
    wire [7:0] export_data;
    wire [63:0] export_accepted,export_emitted,export_dropped;
    wire [31:0] export_queued;
    wire numerical_fault=completion_fault||build_fault||protocol_fault||metric_fault||
        saturation_fault||start_reject||overflow_flags!=0;
    wire transport_fault=export_overflow||export_protocol||export_dropped!=0;
    wire fifo_clear=core_clear||start_discontinuity;
    wire y_full,y_empty,s_full,s_empty;
    wire [31:0] y_level,s_level,y_word,s_word;
    wire y_ready=running&&!fifo_clear&&!y_full&&faults==0;
    wire y_take=y_valid&&y_ready;
    wire y_good=y_take&&y_idx=={32'd0,y_count}&&y_count<OUTPUT_SAMPLES;
    reg [1:0] pack_lane;
    reg [23:0] pack_low;
    wire export_ready=running&&!fifo_clear&&(pack_lane!=3||!s_full)&&faults==0;
    wire export_take=export_valid&&export_ready;
    wire spectral_push=export_take&&pack_lane==3;
    wire format_ok=(req_read!=req_write)&&req_be==15&&req_burst&&req_addr[1:0]==0;
    reg [31:0] read_next;
    reg [1:0] response_next;
    reg do_clear,do_start,do_pcm,do_lo,do_hi,do_sparse,do_s_pop,do_y_pop;
    assign avs_waitrequest=!rst_n||bus_state!=B_IDLE;

    always @* begin
        read_next=0;response_next=0;
        do_clear=0;do_start=0;do_pcm=0;do_lo=0;do_hi=0;do_sparse=0;do_s_pop=0;do_y_pop=0;
        if(bus_state==B_EXEC) begin
            if(!format_ok) response_next=2;
            else if(req_read) begin
                case(req_addr)
                    'h000:read_next=32'h54534832;
                    'h004:read_next=32'h00020000;
                    'h008:read_next={26'd0,!y_empty,!s_empty,pcm_ready,(faults!=0),done,busy};
                    'h00c:read_next=faults;
                    'h014:read_next=threshold[31:0];
                    'h018:read_next={8'd0,threshold[55:32]};
                    'h01c:read_next={31'd0,sparse};
                    'h024:read_next=loaded;
                    'h028:read_next=epoch[31:0];
                    'h02c:read_next=epoch[63:32];
                    'h030:read_next=s_level;
                    'h034:read_next=y_level;
                    'h038:read_next=pcm_level;
                    'h03c:read_next=32'd256-pcm_level;
                    'h040:if((running||done)&&!s_empty)do_s_pop=1;else response_next=2;
                    'h044:if((running||done)&&!y_empty)do_y_pop=1;else response_next=2;
                    'h048:read_next=y_count;
                    'h04c:read_next=elapsed;
                    'h050:read_next=export_dropped[31:0];
                    'h054:read_next=export_emitted[31:0];
                    'h058:read_next=input_count;
                    'h05c:read_next=INPUT_SAMPLES;
                    'h060:read_next=spectral_bytes;
                    'h064:read_next=spectral_read;
                    'h068:read_next=y_read_count;
                    'h06c:read_next=OUTPUT_SAMPLES;
                    'h070:read_next=FRAMES;
                    'h074:read_next=256;
                    'h078,'h07c:read_next=1024;
                    default:if(req_addr>='h080&&req_addr<='h09c)
                        read_next=SOURCE_ID[32*req_addr[4:2]+:32];else response_next=2;
                endcase
            end else begin
                case(req_addr)
                    'h010:if(req_data==1)do_clear=1;
                        else if(req_data==2&&config_allowed&&loaded==0)do_start=1;else response_next=2;
                    'h014:if(config_allowed)do_lo=1;else response_next=2;
                    'h018:if(config_allowed&&req_data[31:24]==0)do_hi=1;else response_next=2;
                    'h01c:if(config_allowed&&req_data<=1)do_sparse=1;else response_next=2;
                    'h020:if(pcm_ready&&req_data[31:12]=={20{req_data[11]}})do_pcm=1;else response_next=2;
                    default:response_next=2;
                endcase
            end
        end
    end
    always @(posedge clk or negedge rst_n) begin
        if(!rst_n)begin
            bus_state<=B_IDLE;req_addr<=0;req_read<=0;req_write<=0;req_burst<=0;req_be<=0;req_data<=0;
            avs_readdata<=0;avs_readdatavalid<=0;avs_writeresponsevalid<=0;avs_response<=0;
        end else begin
            avs_readdatavalid<=0;avs_writeresponsevalid<=0;
            case(bus_state)
                B_IDLE:if(avs_read||avs_write)begin
                    req_addr<=avs_address;req_read<=avs_read;req_write<=avs_write;
                    req_be<=avs_byteenable;req_burst<=avs_burstcount;req_data<=avs_writedata;bus_state<=B_EXEC;
                end
                B_EXEC:begin
                    avs_readdata<=read_next;avs_response<=response_next;
                    bus_state<=(do_s_pop||do_y_pop)?B_DATA:B_REPLY;
                end
                B_DATA:begin avs_readdata<=(req_addr=='h040)?s_word:y_word;bus_state<=B_REPLY;end
                B_REPLY:begin avs_readdatavalid<=req_read;avs_writeresponsevalid<=req_write;bus_state<=B_IDLE;end
                default:bus_state<=B_IDLE;
            endcase
        end
    end
    stream_fifo y_fifo(.clk(clk),.rst_n(rst_n),.clear_i(fifo_clear),.push_i(y_good),
        .data_i({{20{y_data[11]}},y_data}),.pop_i(do_y_pop),.data_o(y_word),
        .full_o(y_full),.empty_o(y_empty),.level_o(y_level));
    stream_fifo spectral_fifo(.clk(clk),.rst_n(rst_n),.clear_i(fifo_clear),.push_i(spectral_push),
        .data_i({export_data,pack_low}),.pop_i(do_s_pop),.data_o(s_word),
        .full_o(s_full),.empty_o(s_empty),.level_o(s_level));
    always @(posedge clk or negedge rst_n) begin
        if(!rst_n)begin pack_lane<=0;pack_low<=0;end
        else if(fifo_clear)begin pack_lane<=0;pack_low<=0;end
        else if(export_take)begin
            pack_lane<=pack_lane+1'b1;
            case(pack_lane)
                0:pack_low[7:0]<=export_data;
                1:pack_low[15:8]<=export_data;
                2:pack_low[23:16]<=export_data;
                default:begin end
            endcase
        end
    end
    always @(posedge clk or negedge rst_n) begin
        if(!rst_n)begin
            state<=CLEAR_CORE;faults<=0;loaded<=0;y_count<=0;input_count<=0;elapsed<=0;
            threshold<=0;sparse<=0;pending_run<=0;epoch<=0;
            spectral_bytes<=0;spectral_read<=0;y_read_count<=0;
        end else begin
            if(busy)elapsed<=elapsed+1'b1;
            if(do_pcm)loaded<=loaded+1'b1;
            if(do_lo)threshold[31:0]<=req_data;
            if(do_hi)threshold[55:32]<=req_data[23:0];
            if(do_sparse)sparse<=req_data[0];
            if(y_good)y_count<=y_count+1'b1;
            if(export_take)spectral_bytes<=spectral_bytes+1'b1;
            if(do_s_pop)spectral_read<=spectral_read+1'b1;
            if(do_y_pop)y_read_count<=y_read_count+1'b1;
            if(running&&source_valid&&source_ready&&source_idx<INPUT_SAMPLES)input_count<=input_count+1'b1;
            case(state)
                CLEAR_CORE:state<=WAIT_INIT;
                WAIT_INIT:if(!top_busy)state<=pending_run?ISSUE_START:IDLE;
                ISSUE_START:state<=WAIT_ACCEPT;
                WAIT_ACCEPT:if(start_accept)state<=RUN;
                RUN:if(top_done&&!top_busy)state<=DRAIN;
                DRAIN:if(!export_busy&&!export_valid&&export_queued==0)begin
                    if(y_count==OUTPUT_SAMPLES&&loaded==INPUT_SAMPLES&&input_count==INPUT_SAMPLES&&
                       pcm_accepted==INPUT_SAMPLES&&core_frames==FRAMES&&
                       export_accepted==FRAMES&&export_emitted==FRAMES&&pack_lane==0)state<=DONE;
                    else begin faults[3]<=1;state<=FAULT;end
                end
                default:begin end
            endcase
            if((running||state==DONE||state==ISSUE_START)&&numerical_fault)begin faults[1]<=1;state<=FAULT;end
            if((running||state==DONE)&&transport_fault)begin faults[2]<=1;state<=FAULT;end
            if((y_take&&!y_good)||(export_take&&export_last&&pack_lane!=3)||
               (busy&&elapsed>=WATCHDOG_CYCLES)||(state==DONE&&(y_valid||top_busy||core_busy)))begin
                faults[3]<=1;state<=FAULT;
            end
            if(bus_state==B_EXEC&&response_next!=0)begin faults[0]<=1;state<=FAULT;end
            if(do_start)begin
                state<=CLEAR_CORE;pending_run<=1;epoch<=epoch+1'b1;
                loaded<=0;y_count<=0;input_count<=0;elapsed<=0;spectral_bytes<=0;spectral_read<=0;y_read_count<=0;
            end
            if(do_clear)begin
                state<=CLEAR_CORE;pending_run<=0;faults<=0;loaded<=0;
                threshold<=0;sparse<=0;y_count<=0;input_count<=0;elapsed<=0;
                spectral_bytes<=0;spectral_read<=0;y_read_count<=0;
            end
        end
    end
    trecap_pcm_stream_top #(.INPUT_FIFO_DEPTH(256),.INPUT_SAMPLES(INPUT_SAMPLES),
        .START_ON_RESET_RELEASE(1'b0),.RESTART_ALLOWED_WHILE_DONE(1'b1)) core(
        .clk(clk),.rst_n(rst_n),.enable_i(1'b1),.clear_i(core_clear),.clear_sticky_i(1'b0),
        .clear_metrics_i(1'b0),.replay_start_i(core_start),
        .pcm_valid_i(do_pcm),.pcm_ready_o(pcm_ready_raw),.pcm_data_i(req_data[11:0]),
        .pcm_accepted_count_o(pcm_accepted),.pcm_fifo_level_o(pcm_level),
        .export_emitted_frames_i(export_emitted),
        .thr2_i(threshold),.y_valid_o(y_valid),.y_ready_i(y_ready),.y_data_o(y_data),.y_sample_idx_o(y_idx),
        .source_sample_valid_o(source_valid),.source_sample_ready_o(source_ready),.source_sample_idx_o(source_idx),
        .source_discontinuity_pulse_o(start_discontinuity),
        .tap_bin_valid_o(tap_valid),.tap_bin_frame_idx_o(tap_frame),.tap_bin_idx_o(tap_bin),
        .tap_bin_mag2_o(tap_mag),.tap_bin_mask_o(tap_mask),.tap_bin_eligible_o(tap_eligible),
        .tap_bin_last_o(tap_last),.tap_bin_thr2_o(tap_threshold),
        .core_busy_o(core_busy),.core_frame_count_o(core_frames),
        .core_metric_overflow_sticky_o(metric_fault),.core_saturation_sticky_o(saturation_fault),
        .core_protocol_error_sticky_o(protocol_fault),.replay_start_accept_pulse_o(start_accept),
        .replay_start_reject_pulse_o(start_reject),.top_busy_o(top_busy),.top_done_o(top_done),
        .top_completion_error_sticky_o(completion_fault),.top_overflow_flags_o(overflow_flags),.build_contract_error_o(build_fault)
    );
    trecap_spectral_exporter #(.QUEUE_FRAMES(4)) exporter(
        .clk(clk),.rst_n(rst_n),.clear_i(fifo_clear),.tap_valid_i(tap_valid),
        .tap_frame_id_i(tap_frame),.tap_bin_idx_i(tap_bin),.tap_mag2_i(tap_mag),
        .tap_mask_i(tap_mask),.tap_eligible_i(tap_eligible),.tap_last_i(tap_last),
        .tap_thr2_i({8'd0,tap_threshold}),.sparse_mode_i(sparse),
        .out_valid_o(export_valid),.out_ready_i(export_ready),.out_data_o(export_data),.out_last_o(export_last),
        .accepted_frames_o(export_accepted),.emitted_frames_o(export_emitted),.dropped_frames_o(export_dropped),
        .overflow_sticky_o(export_overflow),.protocol_error_sticky_o(export_protocol),.queued_frames_o(export_queued),.busy_o(export_busy)
    );
endmodule
`default_nettype wire
