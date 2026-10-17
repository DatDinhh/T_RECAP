`default_nettype none
module fifo_formal #(parameter integer WIDTH=8, DEPTH=4, CHECK_ORDER=1, NEGATIVE=0)(input wire clk);
    (* anyseq *) reg rst_n, clear_i, push_i, pop_i;
    (* anyseq *) reg [WIDTH-1:0] data_i;
    wire [WIDTH-1:0] data_o;
    wire full_o, empty_o;
    wire [31:0] level_o;
    stream_fifo #(.WIDTH(WIDTH), .DEPTH(DEPTH)) dut(.*);
    reg past_valid = 0;
    reg [31:0] accepted_writes = 0, accepted_reads = 0;
    reg saw_full = 0, saw_clear = 0, had_data = 0, saw_reset_after_data = 0;
    wire push = push_i && !full_o;
    wire pop = pop_i && !empty_o;

    always @(posedge clk) begin
        past_valid <= 1;
        if (!past_valid) assume(!rst_n);
        if (past_valid) begin
            a_capacity: assert(level_o <= DEPTH);
            a_full_flag: assert(full_o == (level_o == DEPTH));
            a_empty_flag: assert(empty_o == (level_o == 0));
            if (!rst_n) begin
                a_reset_empty: assert(level_o == 0);
            end else if (!$past(rst_n) || $past(clear_i)) begin
                a_clear_empty: assert(level_o == 0);
            end else begin
                case ({$past(push), $past(pop)})
                    2'b10: a_increment: assert(level_o == $past(level_o) + 1);
                    2'b01: a_decrement: assert(level_o == $past(level_o) - 1);
                    default: a_hold_count: assert(level_o == $past(level_o));
                endcase
                if (!$past(pop)) a_hold_data: assert(data_o == $past(data_o));
            end
            if (NEGATIVE) a_deliberately_false_never_full: assert(!full_o);
        end
        if (!rst_n || clear_i) begin
            accepted_writes <= 0;
            accepted_reads <= 0;
            saw_full <= 0;
            if (past_valid && rst_n && clear_i && level_o != 0) saw_clear <= 1;
        end else begin
            if (push && accepted_writes < 2*DEPTH+1) accepted_writes <= accepted_writes + 1;
            if (pop && accepted_reads < 2*DEPTH+1) accepted_reads <= accepted_reads + 1;
            if (full_o) saw_full <= 1;
        end
        if (past_valid && rst_n && level_o != 0) had_data <= 1;
        if (past_valid && !rst_n && had_data) saw_reset_after_data <= 1;
        if (past_valid && rst_n && !clear_i) begin
            c_full: cover(full_o);
            c_empty_after_full: cover(saw_full && empty_o);
            c_simultaneous_accepted: cover(push && pop);
            c_full_both_requested: cover(full_o && push_i && pop_i);
            c_empty_both_requested: cover(empty_o && push_i && pop_i);
            c_write_and_read_wrap: cover(accepted_writes > DEPTH && accepted_reads > DEPTH);
            c_clear_recovery: cover(saw_clear && push && level_o == 0);
            c_reset_recovery: cover(saw_reset_after_data && push && level_o == 0);
        end
    end

    generate if (CHECK_ORDER) begin : g_order
        // Independent shift queue. DUT uses circular RAM and separate pointers.
        reg [WIDTH-1:0] queue [0:DEPTH-1];
        reg [31:0] count;
        reg [WIDTH-1:0] expected_read;
        reg expected_read_valid = 0;
        wire model_push = push_i && count < DEPTH;
        wire model_pop = pop_i && count != 0;
        integer i;
        always @(posedge clk) begin
            if (past_valid && rst_n) begin
                a_reference_count: assert(level_o == count);
                if (expected_read_valid) a_fifo_order: assert(data_o == expected_read);
            end
            expected_read_valid <= 0;
            if (!rst_n || clear_i) count <= 0;
            else begin
                if (model_pop) begin
                    expected_read <= queue[0];
                    expected_read_valid <= 1;
                    for (i=0; i<DEPTH-1; i=i+1) queue[i] <= queue[i+1];
                end
                if (model_push) queue[count - model_pop] <= data_i;
                case ({model_push,model_pop})
                    2'b10: count <= count + 1;
                    2'b01: count <= count - 1;
                    default: count <= count;
                endcase
            end
        end
    end endgenerate
endmodule
`default_nettype wire
