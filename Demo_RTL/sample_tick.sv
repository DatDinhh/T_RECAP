//============================================================
// Generates a 1-clock-wide tick pulse every DIVIDER cycles.
// Active Low rst_n
//============================================================
module sample_tick #(
	parameter int unsigned DIVIDER = 50
)(
	input  logic clk,
	input  logic rst_n,
	output logic tick
);

	// DIVIDER MINUS 1
	localparam int unsigned DIVM1 = (DIVIDER > 0) ? (DIVIDER-1) : 0;
	// COUNTER WIDTH
	localparam int unsigned CW    = (DIVIDER <= 2) ? 1 : $clog2(DIVIDER);

	logic [CW-1:0] cnt;

	always_ff @(posedge clk or negedge rst_n) begin
		if (!rst_n) begin
			cnt  <= '0;
			tick <= 1'b0;
		end else begin
				if (DIVIDER <= 1) begin
					tick <= 1'b1;
					cnt  <= '0;
				end else begin
					if (cnt == DIVM1[CW-1:0]) begin
						cnt  <= '0;
						tick <= 1'b1;
					end else begin
						cnt  <= cnt + {{(CW-1){1'b0}},1'b1};
						tick <= 1'b0;
					end
				end
			end
	end

endmodule
