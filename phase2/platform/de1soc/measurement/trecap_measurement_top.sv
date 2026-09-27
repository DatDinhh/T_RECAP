// Standalone DE1-SoC measurement image. No HPS or activity-dependent LEDs.
`default_nettype none
module trecap_measurement_top (
    input  wire       CLOCK_50,
    input  wire [0:0] KEY,
    output wire [9:0] LEDR
);
    // FPGA register power-up initialization supplies a reset even without a key
    // press. KEY[0] asynchronously asserts reset; release is CLOCK_50 synchronous.
    reg [15:0] powerup_q = 16'b0;
    (* async_reg = "true" *) reg [1:0] key_release_q = 2'b0;
    (* async_reg = "true" *) reg [1:0] reset_release_q = 2'b0;
    always @(posedge CLOCK_50 or negedge KEY[0]) begin
        if (!KEY[0]) begin
            powerup_q <= 16'b0;
            key_release_q <= 2'b0;
            reset_release_q <= 2'b0;
        end else begin
            if (!(&powerup_q)) powerup_q <= powerup_q + 16'd1;
            key_release_q <= {key_release_q[0], 1'b1};
            reset_release_q <= {reset_release_q[0], (&powerup_q) & key_release_q[1]};
        end
    end
    wire reset_n = reset_release_q[1];
    wire [31:0] control;
    wire [479:0] probe;

    altsource_probe #(
        .sld_auto_instance_index("YES"),
        .sld_instance_index(0),
        .instance_id("TREC"),
        .source_width(32),
        .probe_width(480),
        .source_initial_value("0"),
        .enable_metastability("YES")
    ) u_measurement_jtag (
        .source_clk(CLOCK_50),
        .source_ena(1'b1),
        .source(control),
        .probe(probe)
    );

    trecap_measurement_engine u_engine (
        .clk(CLOCK_50),
        .rst_n(reset_n),
        .control_i(control),
        .probe_o(probe),
        .busy_o(),
        .done_o(),
        .fault_o()
    );
    assign LEDR = 10'b0;
endmodule
`default_nettype wire
