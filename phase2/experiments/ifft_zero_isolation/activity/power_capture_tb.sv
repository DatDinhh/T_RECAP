`timescale 1ns/1ps
`default_nettype none
module power_capture_tb;
    reg clk=0;
    reg rst_n=0;
    reg [31:0] control=0;
    wire [479:0] probe;
    wire busy,done,fault;
    integer mode,cycles;
    string vcd_path;
    always #10 clk=~clk;
    trecap_measurement_engine #(.SUPPORT_IFFT_ZERO_ISOLATION(1'b1)) dut (
        .clk(clk),.rst_n(rst_n),.control_i(control),.probe_o(probe),
        .busy_o(busy),.done_o(done),.fault_o(fault)
    );
    initial begin
        if (!$value$plusargs("MODE=%d",mode) || (mode!=2 && mode!=3))
            $fatal(1,"POWER_CAPTURE_FAIL: MODE must be 2 or 3");
        if (!$value$plusargs("VCD=%s",vcd_path))
            $fatal(1,"POWER_CAPTURE_FAIL: VCD destination missing");
        $dumpfile(vcd_path);
        $dumpvars(0,dut);
        repeat(6) @(negedge clk);
        rst_n=1;
        repeat(8) @(negedge clk);
        control=(32'd2<<16)|32'd4|32'(mode);
        @(negedge clk);
        if (!busy) $fatal(1,"POWER_CAPTURE_FAIL: no start");
        cycles=0;
        while(busy && cycles<400000) begin
            @(negedge clk);
            cycles=cycles+1;
        end
        if (busy || !done || fault) $fatal(1,"POWER_CAPTURE_FAIL: terminal fault");
        control=control^32'd8;
        @(negedge clk);
        if (probe[32+:32]>>24 != 2 || probe[32+11]!=(mode==3) ||
            probe[3*32+:32]!=2 || probe[4*32+:32]!=3072 ||
            probe[5*32+:32]!=0 || probe[6*32+:32]!=2048 ||
            probe[7*32+:32]!=18 || probe[11*32+:32]!=0 ||
            {probe[9*32+:32],probe[8*32+:32]}!=64'd176662)
            $fatal(1,"POWER_CAPTURE_FAIL: counters, mode or cycle mismatch");
        repeat(4) @(negedge clk);
        $display("POWER_CAPTURE_PASS mode=%0d cycles=176662 outputs=3072 mismatches=0",mode);
        $finish;
    end
    initial begin
        #10000000;
        $fatal(1,"POWER_CAPTURE_FAIL: timeout");
    end
endmodule
`default_nettype wire
