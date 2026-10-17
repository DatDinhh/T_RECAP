// Single-clock FIFO. RAM output is valid one edge after an accepted pop.
`default_nettype none
module stream_fifo #(parameter integer WIDTH=32, DEPTH=1024)(
    input wire clk, rst_n, clear_i,
    input wire push_i, input wire [WIDTH-1:0] data_i,
    input wire pop_i, output reg [WIDTH-1:0] data_o,
    output wire full_o, empty_o, output reg [31:0] level_o
);
    localparam integer AW=$clog2(DEPTH);
    reg [AW-1:0] wp,rp;
    (* ramstyle="M10K" *) reg [WIDTH-1:0] mem[0:DEPTH-1];
    wire push=push_i&&!full_o, pop=pop_i&&!empty_o;
    assign full_o=level_o==DEPTH;
    assign empty_o=level_o==0;
    always @(posedge clk) begin
        if(rst_n&&!clear_i) begin
            if(push) mem[wp]<=data_i;
            if(pop) data_o<=mem[rp];
        end
    end
    always @(posedge clk or negedge rst_n) begin
        if(!rst_n) begin wp<=0;rp<=0;level_o<=0;end
        else if(clear_i) begin wp<=0;rp<=0;level_o<=0;end
        else begin
            if(push) wp<=(wp==DEPTH-1)?0:wp+1'b1;
            if(pop) rp<=(rp==DEPTH-1)?0:rp+1'b1;
            case({push,pop})
                2'b10:level_o<=level_o+1'b1;
                2'b01:level_o<=level_o-1'b1;
                default:begin end
            endcase
        end
    end
endmodule
`default_nettype wire
