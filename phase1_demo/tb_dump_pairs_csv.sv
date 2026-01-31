`timescale 1ns/1ps
`default_nettype none

module tb_dump_pairs_csv;

  logic CLOCK_50;
  logic [1:0] KEY;
  logic [9:0] SW;
  logic [9:0] LEDR;
  logic [6:0] HEX0,HEX1,HEX2,HEX3,HEX4,HEX5;

  // 50 MHz clock
  initial CLOCK_50 = 0;
  always #10 CLOCK_50 = ~CLOCK_50;

 
  t_recap_demo_top #(
    .SAMPLE_DIV(10),
    .DBG_DIV(1000)
  ) dut (
    .CLOCK_50(CLOCK_50),
    .KEY(KEY),
    .SW(SW),
    .LEDR(LEDR),
    .HEX0(HEX0), .HEX1(HEX1), .HEX2(HEX2),
    .HEX3(HEX3), .HEX4(HEX4), .HEX5(HEX5)
  );

  integer fh;
  int k;

  task automatic reset_dut();
    begin
      KEY = 2'b11;
      KEY[0] = 0;
      repeat (5) @(posedge CLOCK_50);
      KEY[0] = 1;
      repeat (5) @(posedge CLOCK_50);
    end
  endtask

  initial begin
    // threshold = 15
    SW = '0;
    SW[9:8] = 2'b10;     // manual
    SW[7:0] = 8'd15;

    fh = $fopen("pairs_dump.csv", "w");
    if (!fh) $fatal("Could not open CSV");

    // Header 
    $fwrite(fh,
      "k_pairs,x0,x1,a,d,sk,d_prime,y0,y1\n"
    );

    reset_dut();

    k = 0;
    while (k < 1000) begin
      @(posedge CLOCK_50);
      	if (dut.pair_out_valid) begin
        	$fwrite(
  				fh,
  				"%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d\n",
  				k,
  				$signed(dut.x0_a),
  				$signed(dut.x1_a),
  				$signed(dut.a_tap),
  				$signed(dut.d_tap),
  				dut.suppressed,
  				dut.suppressed ? 0 : $signed(dut.d_tap),
  				$signed(dut.y0),
  				$signed(dut.y1)
				);
        k++;
      end
    end

    $fclose(fh);
    $display("Wrote %0d pairs to pairs_dump.csv", k);
    $stop;
  end

endmodule

`default_nettype wire