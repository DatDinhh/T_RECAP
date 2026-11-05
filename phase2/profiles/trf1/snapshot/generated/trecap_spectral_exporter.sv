// SPDX-License-Identifier: MIT
// Isolated observation-only TSP1 exporter. See ../CONTRACT.md and README_RTL.md.
// No ready signal is returned to the mathematical core.
`default_nettype none
module trecap_spectral_exporter #(
    parameter integer QUEUE_FRAMES = 4
) (
    input  wire         clk,
    input  wire         rst_n,
    input  wire         clear_i,
    input  wire         tap_valid_i,
    input  wire [63:0]  tap_frame_id_i,
    input  wire [7:0]   tap_bin_idx_i,
    input  wire [55:0]  tap_mag2_i,
    input  wire         tap_mask_i,
    input  wire         tap_eligible_i,
    input  wire         tap_last_i,
    input  wire [63:0]  tap_thr2_i,
    input  wire         sparse_mode_i,
    output wire         out_valid_o,
    input  wire         out_ready_i,
    output wire [7:0]   out_data_o,
    output wire         out_last_o,
    output wire [15:0]  out_bytes_o,
    output wire [63:0]  out_frame_id_o,
    output wire [63:0]  out_thr2_o,
    output wire         out_sparse_o,
    output reg  [63:0]  accepted_frames_o,
    output reg  [63:0]  emitted_frames_o,
    output reg  [63:0]  dropped_frames_o,
    output reg          overflow_sticky_o,
    output reg          protocol_error_sticky_o,
    output wire [31:0]  queued_frames_o,
    output wire         busy_o
);
    localparam integer PTR_W = (QUEUE_FRAMES > 2) ? $clog2(QUEUE_FRAMES) : 1;
    localparam integer ENTRY_ADDR_W = $clog2(QUEUE_FRAMES*129);
    localparam [2:0] ST_IDLE=3'd0, ST_HASH=3'd1, ST_EMIT=3'd2,
                     ST_HASH_FETCH=3'd3, ST_EMIT_FETCH=3'd4;
    localparam [63:0] FNV_OFFSET=64'd14695981039346656037;
    localparam [63:0] FNV_PRIME=64'd1099511628211;

    // One slot is retained through capture, hashing, and the last output handshake.
    // Dense stores a zero-extended masked u56; sparse stores {magnitude, bin}.
    (* ramstyle = "M10K" *) reg [63:0] entries [0:QUEUE_FRAMES*129-1];
    reg [63:0] frame_id [0:QUEUE_FRAMES-1];
    reg [63:0] threshold [0:QUEUE_FRAMES-1];
    reg        sparse_mode [0:QUEUE_FRAMES-1];
    reg [8:0]  entry_count [0:QUEUE_FRAMES-1];
    reg [PTR_W-1:0] wr_ptr, rd_ptr;
    reg [31:0] queue_count;

    reg capture_active;
    reg discard_until_bin0;
    reg [7:0] expected_bin;
    reg [63:0] capture_frame_id, capture_threshold;
    reg capture_sparse;
    reg [8:0] capture_kept;

    reg [2:0] state;
    reg [10:0] hash_position, emit_position;
    reg [8:0] serial_entry;
    reg [2:0] serial_lane;
    reg [63:0] read_word;
    reg [63:0] hash_value, record_checksum;
    wire [15:0] payload_bytes = sparse_mode[rd_ptr] ?
        ({7'd0, entry_count[rd_ptr]} << 3) : 16'd903;
    wire [15:0] record_bytes = sparse_mode[rd_ptr] ?
        (16'd48 + payload_bytes) : 16'd952;

    // A fetch state makes the synchronous read latency explicit. The registered
    // RAM output is also the holding word for all seven/eight payload byte lanes.
    // It is never overwritten while an output byte is stalled.
    wire [10:0] serial_position=((state==ST_HASH) || (state==ST_HASH_FETCH)) ?
        hash_position : emit_position;
    wire payload_position=({5'd0,serial_position}>=16'd48) &&
        ({5'd0,serial_position}<(16'd48+payload_bytes));
    wire final_lane=(serial_lane==(sparse_mode[rd_ptr] ? 3'd7 : 3'd6));
    wire more_payload=({5'd0,serial_position}+16'd1)<(16'd48+payload_bytes);
    wire ram_read_en=rst_n && !clear_i &&
        ((state==ST_HASH_FETCH) || (state==ST_EMIT_FETCH));
    wire [ENTRY_ADDR_W-1:0] ram_read_address=(rd_ptr*129)+serial_entry;

    // Pure combinational byte formatter; all memory data enters through arguments.
    // Entry/lane counters replace per-byte division and remainder addressing.
    function automatic [7:0] byte_at;
        input integer position;
        input is_sparse;
        input [8:0] stored_count;
        input [63:0] stored_frame_id;
        input [63:0] stored_threshold;
        input [63:0] word_value;
        input [2:0] lane;
        input [63:0] checksum_value;
        reg [31:0] payload;
        reg [15:0] count;
        begin
            count = is_sparse ? {7'd0,stored_count} : 16'd129;
            payload = is_sparse ? ({16'd0,count} << 3) : 32'd903;
            byte_at=8'd0;
            case(position)
                0: byte_at=8'h54;
                1: byte_at=8'h53;
                2: byte_at=8'h50;
                3: byte_at=8'h31;
                4: byte_at=8'd1;
                6: byte_at={7'd0,is_sparse};
                8: byte_at=8'd1;
                10: byte_at=8'd1;
                34: byte_at=8'd1;
                default: begin
                    if(position>=12 && position<16)
                        byte_at=payload >> (8*(position-12));
                    else if(position>=16 && position<24)
                        byte_at=stored_frame_id >> (8*(position-16));
                    else if(position>=24 && position<32)
                        byte_at=stored_threshold >> (8*(position-24));
                    else if(position>=32 && position<34)
                        byte_at=count >> (8*(position-32));
                    else if(position>=40 && position<48)
                        byte_at=checksum_value >> (8*(position-40));
                    else if(position>=48 && position<(48+payload)) begin
                        byte_at=word_value >> (8*lane);
                    end
                end
            endcase
        end
    endfunction

    wire [7:0] serial_byte=byte_at(serial_position,sparse_mode[rd_ptr],
        entry_count[rd_ptr],frame_id[rd_ptr],threshold[rd_ptr],
        read_word,serial_lane,record_checksum);
    wire [63:0] next_hash=(hash_value ^ {56'd0,serial_byte}) * FNV_PRIME;
    wire beat_shape_ok=(tap_bin_idx_i<=8'd128) &&
        (tap_eligible_i==(tap_bin_idx_i!=8'd0)) &&
        (tap_mask_i==((tap_bin_idx_i!=8'd0) &&
                     ({8'd0,tap_mag2_i}<tap_thr2_i))) &&
        (tap_last_i==(tap_bin_idx_i==8'd128));

    // One write port serves the current uncommitted capture slot. A committed
    // read slot remains owned until its final output handshake, so simultaneous
    // enabled read/write addresses cannot collide. Reset/clear flush ownership,
    // not the RAM contents or its output register.
    wire start_write=tap_valid_i && (tap_bin_idx_i==8'd0) &&
        (queue_count<QUEUE_FRAMES) && beat_shape_ok;
    wire continue_valid=tap_valid_i && (tap_bin_idx_i!=8'd0) && capture_active &&
        beat_shape_ok && (tap_bin_idx_i==expected_bin) &&
        (tap_frame_id_i==capture_frame_id) && (tap_thr2_i==capture_threshold);
    wire ram_write_en=rst_n && !clear_i &&
        (start_write || (continue_valid && (!capture_sparse || !tap_mask_i)));
    wire [8:0] write_element=(tap_bin_idx_i==8'd0) ? 9'd0 :
        (capture_sparse ? capture_kept : {1'b0,tap_bin_idx_i});
    wire [ENTRY_ADDR_W-1:0] ram_write_address=(wr_ptr*129)+write_element;
    wire write_sparse=(tap_bin_idx_i==8'd0) ? sparse_mode_i : capture_sparse;
    wire [63:0] ram_write_data=write_sparse ? {tap_mag2_i,tap_bin_idx_i} :
        (tap_mask_i ? 64'd0 : {8'd0,tap_mag2_i});
    always @(posedge clk) begin
        if(ram_write_en) entries[ram_write_address]<=ram_write_data;
        if(ram_read_en) read_word<=entries[ram_read_address];
    end

    assign out_valid_o=rst_n && !clear_i && (state==ST_EMIT);
    assign out_data_o=out_valid_o ? serial_byte : 8'd0;
    assign out_last_o=out_valid_o && ({5'd0,emit_position}==(record_bytes-16'd1));
    assign out_bytes_o=out_valid_o ? record_bytes : 16'd0;
    assign out_frame_id_o=out_valid_o ? frame_id[rd_ptr] : 64'd0;
    assign out_thr2_o=out_valid_o ? threshold[rd_ptr] : 64'd0;
    assign out_sparse_o=out_valid_o && sparse_mode[rd_ptr];
    assign queued_frames_o=queue_count;
    assign busy_o=rst_n && !clear_i &&
        (capture_active || (queue_count!=32'd0) || (state!=ST_IDLE));
    wire release_frame=out_valid_o && out_ready_i && out_last_o;

    // Blocking temporaries accumulate independent events within this clock edge.
    // In particular a resynchronizing bin0 can discard both an incomplete old
    // frame and the newly arriving frame, so the drop increment can be two.
    reg commit_frame;
    reg [1:0] drop_increment;
    always @(posedge clk or negedge rst_n) begin
        if(!rst_n) begin
            wr_ptr<=0; rd_ptr<=0; queue_count<=0;
            capture_active<=0; discard_until_bin0<=0; expected_bin<=0;
            capture_frame_id<=0; capture_threshold<=0; capture_sparse<=0; capture_kept<=0;
            state<=ST_IDLE; hash_position<=0; emit_position<=0;
            serial_entry<=0; serial_lane<=0;
            hash_value<=FNV_OFFSET; record_checksum<=0;
            accepted_frames_o<=0; emitted_frames_o<=0; dropped_frames_o<=0;
            overflow_sticky_o<=0; protocol_error_sticky_o<=0;
            commit_frame=0; drop_increment=0;
        end else if(clear_i) begin
            wr_ptr<=0; rd_ptr<=0; queue_count<=0;
            capture_active<=0; discard_until_bin0<=0; expected_bin<=0;
            capture_frame_id<=0; capture_threshold<=0; capture_sparse<=0; capture_kept<=0;
            state<=ST_IDLE; hash_position<=0; emit_position<=0;
            serial_entry<=0; serial_lane<=0;
            hash_value<=FNV_OFFSET; record_checksum<=0;
            accepted_frames_o<=0; emitted_frames_o<=0; dropped_frames_o<=0;
            overflow_sticky_o<=0; protocol_error_sticky_o<=0;
            commit_frame=0; drop_increment=0;
        end else begin
            commit_frame=0;
            drop_increment=0;

            if(tap_valid_i) begin
                if(tap_bin_idx_i==8'd0) begin
                    if(capture_active) begin
                        drop_increment=drop_increment+2'd1;
                        protocol_error_sticky_o<=1'b1;
                    end
                    capture_active<=1'b0;
                    discard_until_bin0<=1'b1;
                    // A full queue is judged before this edge's release. The
                    // deliberately conservative simultaneous-release drop is counted.
                    if(queue_count>=QUEUE_FRAMES) begin
                        drop_increment=drop_increment+2'd1;
                        overflow_sticky_o<=1'b1;
                        if(!beat_shape_ok) protocol_error_sticky_o<=1'b1;
                    end else if(!beat_shape_ok) begin
                        drop_increment=drop_increment+2'd1;
                        protocol_error_sticky_o<=1'b1;
                    end else begin
                        capture_active<=1'b1;
                        discard_until_bin0<=1'b0;
                        expected_bin<=8'd1;
                        capture_frame_id<=tap_frame_id_i;
                        capture_threshold<=tap_thr2_i;
                        capture_sparse<=sparse_mode_i;
                        capture_kept<=9'd1;
                        frame_id[wr_ptr]<=tap_frame_id_i;
                        threshold[wr_ptr]<=tap_thr2_i;
                        sparse_mode[wr_ptr]<=sparse_mode_i;
                    end
                end else if(capture_active) begin
                    if(!beat_shape_ok || (tap_bin_idx_i!=expected_bin) ||
                       (tap_frame_id_i!=capture_frame_id) ||
                       (tap_thr2_i!=capture_threshold)) begin
                        capture_active<=1'b0;
                        discard_until_bin0<=1'b1;
                        drop_increment=drop_increment+2'd1;
                        protocol_error_sticky_o<=1'b1;
                    end else begin
                        if(capture_sparse) begin
                            if(!tap_mask_i) begin
                                capture_kept<=capture_kept+9'd1;
                            end
                        end
                        expected_bin<=expected_bin+8'd1;
                        if(tap_bin_idx_i==8'd128) begin
                            capture_active<=1'b0;
                            discard_until_bin0<=1'b0;
                            entry_count[wr_ptr]<=capture_sparse ?
                                (capture_kept+(tap_mask_i ? 9'd0 : 9'd1)) : 9'd129;
                            commit_frame=1'b1;
                            accepted_frames_o<=accepted_frames_o+64'd1;
                            wr_ptr<=(wr_ptr==QUEUE_FRAMES-1) ? 0 : wr_ptr+1'b1;
                        end
                    end
                end else if(!discard_until_bin0) begin
                    // A run of stray nonzero bins is one malformed discarded
                    // frame. Ignore the rest of that run until a fresh bin0.
                    discard_until_bin0<=1'b1;
                    drop_increment=drop_increment+2'd1;
                    protocol_error_sticky_o<=1'b1;
                end
            end
            if(drop_increment!=0)
                dropped_frames_o<=dropped_frames_o+{62'd0,drop_increment};

            case(state)
                ST_IDLE: if(queue_count!=0) begin
                    hash_position<=0;
                    serial_entry<=0;
                    serial_lane<=0;
                    hash_value<=FNV_OFFSET;
                    state<=ST_HASH;
                end
                ST_HASH_FETCH: state<=ST_HASH;
                ST_EMIT_FETCH: state<=ST_EMIT;
                ST_HASH: begin
                    hash_value<=next_hash;
                    if({5'd0,hash_position}==(record_bytes-16'd1)) begin
                        record_checksum<=next_hash;
                        emit_position<=0;
                        serial_entry<=0;
                        serial_lane<=0;
                        state<=ST_EMIT;
                    end else if(hash_position==11'd39) begin
                        hash_position<=11'd48;
                        state<=ST_HASH_FETCH;
                    end else begin
                        hash_position<=hash_position+11'd1;
                        if(payload_position && more_payload) begin
                            if(final_lane) begin
                                serial_entry<=serial_entry+9'd1;
                                serial_lane<=0;
                                state<=ST_HASH_FETCH;
                            end else serial_lane<=serial_lane+3'd1;
                        end
                    end
                end
                ST_EMIT: if(out_ready_i) begin
                    if(out_last_o) begin
                        state<=ST_IDLE;
                        rd_ptr<=(rd_ptr==QUEUE_FRAMES-1) ? 0 : rd_ptr+1'b1;
                        emitted_frames_o<=emitted_frames_o+64'd1;
                    end else begin
                        emit_position<=emit_position+11'd1;
                        if(emit_position==11'd47) begin
                            state<=ST_EMIT_FETCH;
                        end else if(payload_position && more_payload) begin
                            if(final_lane) begin
                                serial_entry<=serial_entry+9'd1;
                                serial_lane<=0;
                                state<=ST_EMIT_FETCH;
                            end else serial_lane<=serial_lane+3'd1;
                        end
                    end
                end
                default: state<=ST_IDLE;
            endcase

            case({commit_frame,release_frame})
                2'b10: queue_count<=queue_count+32'd1;
                2'b01: queue_count<=queue_count-32'd1;
                default: queue_count<=queue_count;
            endcase
        end
    end

`ifndef SYNTHESIS
    initial begin
        if(QUEUE_FRAMES<2) $fatal(1,"QUEUE_FRAMES must be >=2");
    end
`endif
endmodule
`default_nettype wire
