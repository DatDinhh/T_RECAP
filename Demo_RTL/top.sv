//============================================================
// top.sv  (DE10-Lite)
//
// Real-time demo pipeline:
//   LFSR noise -> (small delta) -> integrator x[n] -> Haar fwd -> threshold -> Haar inv -> y[n]
//
// Controls:
//   KEY[0]   : reset (active-low)
//   SW[9:0]  : threshold control (scaled internally to W bits)
//
// Displays:
//   HEX3..HEX0 : y_out (reconstructed sample) as 16-bit hex
//   HEX5..HEX4 : abs_d (|detail| from Haar) upper byte as hex
//
// LEDs:
//   LEDR[0]    : heartbeat
//   LEDR[9:1]  : mirrors SW[9:1]
//
// Required submodules (you will create these):
//   - sample_tick.sv   (clk,rst_n,tick) with parameter DIVIDER
//   - lfsr_noise.sv    (clk,rst_n,en,sample) with params W, SEED
//   - haar_pair_core.sv(clk,rst_n,en,x_in,thresh,bypass,y_out,y_valid,abs_d)
//   - hex7seg.sv       (nibble,seg) active-low 7seg
//============================================================

module top (
    input  logic        CLOCK_50,
    input  logic [1:0]   KEY,
    input  logic [9:0]   SW,
    output logic [9:0]   LEDR,
    output logic [6:0]   HEX0,
    output logic [6:0]   HEX1,
    output logic [6:0]   HEX2,
    output logic [6:0]   HEX3,
    output logic [6:0]   HEX4,
    output logic [6:0]   HEX5
);

    // -----------------------------
    // Parameters you can tune
    // -----------------------------
    localparam int unsigned CLK_HZ      = 50_000_000;
    localparam int unsigned SAMPLE_HZ   = 8_000;     // "real-time" processing tick
    localparam int unsigned DISP_HZ     = 20;        // slow latch so HEX is readable
    localparam int unsigned W           = 16;

    // Noise shaping: use LFSR as a delta, then integrate to make correlated signal.
    // Larger shift => smaller steps => smoother input.
    localparam int unsigned NOISE_SHIFT = 8;

    localparam int unsigned SAMPLE_DIV  = (CLK_HZ / SAMPLE_HZ);
    localparam int unsigned DISP_DIV    = (CLK_HZ / DISP_HZ);

    // -----------------------------
    // Reset
    // -----------------------------
    logic rst_n;
    assign rst_n = KEY[0];   // active-low on DE10-Lite

    // -----------------------------
    // Heartbeat + LED mirror
    // -----------------------------
    logic [25:0] hb_cnt;
    always_ff @(posedge CLOCK_50 or negedge rst_n) begin
        if (!rst_n) hb_cnt <= '0;
        else        hb_cnt <= hb_cnt + 26'd1;
    end

    assign LEDR[0]   = hb_cnt[25];
    assign LEDR[9:1] = SW[9:1];

    // -----------------------------
    // Sample enable tick (clock-enable pulse)
    // -----------------------------
    logic sample_en;

    sample_tick #(
        .DIVIDER(SAMPLE_DIV)
    ) u_sample_tick (
        .clk   (CLOCK_50),
        .rst_n (rst_n),
        .tick  (sample_en)
    );

    // -----------------------------
    // Threshold scaling: SW is 10b; scale up to W bits by left shift
    // thresh = SW << (W-10)
    // -----------------------------
    logic [W-1:0] thresh;
    assign thresh = {SW, {(W-10){1'b0}}};

    // -----------------------------
    // LFSR noise source (raw)
    // -----------------------------
    logic signed [W-1:0] noise_raw;

    lfsr_noise #(
        .W    (W),
        .SEED (16'hACE1)
    ) u_lfsr_noise (
        .clk    (CLOCK_50),
        .rst_n  (rst_n),
        .en     (sample_en),
        .sample (noise_raw)
    );

    // -----------------------------
    // Correlated input stream x[n] = x[n-1] + (noise_raw >> NOISE_SHIFT)
    // This makes Haar detail often "small", so thresholding shows effect clearly.
    // -----------------------------
    logic signed [W-1:0] x_stream;
    logic signed [W-1:0] noise_step;

    always_comb begin
        noise_step = noise_raw >>> NOISE_SHIFT; // arithmetic shift (signed)
    end

    always_ff @(posedge CLOCK_50 or negedge rst_n) begin
        if (!rst_n) begin
            x_stream <= '0;
        end else if (sample_en) begin
            x_stream <= x_stream + noise_step;
        end
    end

    // -----------------------------
    // Haar transform -> threshold -> inverse (reconstruct)
    // -----------------------------
    logic signed [W-1:0] y_out;
    logic               y_valid;
    logic [W-1:0]        abs_d;

    // No bypass needed: set SW=0 for "effectively bypass" behavior
    logic bypass;
    assign bypass = 1'b0;

    haar_pair_core #(
        .W(W)
    ) u_haar_pair_core (
        .clk     (CLOCK_50),
        .rst_n   (rst_n),
        .en      (sample_en),
        .x_in    (x_stream),
        .thresh  (thresh),
        .bypass  (bypass),
        .y_out   (y_out),
        .y_valid (y_valid),
        .abs_d   (abs_d)
    );

    // -----------------------------
    // Slow display latch (so HEX is readable)
    // -----------------------------
    logic [31:0] disp_cnt;
    logic        disp_tick;

    always_ff @(posedge CLOCK_50 or negedge rst_n) begin
        if (!rst_n) begin
            disp_cnt  <= 32'd0;
            disp_tick <= 1'b0;
        end else begin
            if (disp_cnt == (DISP_DIV-1)) begin
                disp_cnt  <= 32'd0;
                disp_tick <= 1'b1;
            end else begin
                disp_cnt  <= disp_cnt + 32'd1;
                disp_tick <= 1'b0;
            end
        end
    end

    logic signed [W-1:0] disp_y;
    logic [W-1:0]        disp_abs_d;

    always_ff @(posedge CLOCK_50 or negedge rst_n) begin
        if (!rst_n) begin
            disp_y     <= '0;
            disp_abs_d <= '0;
        end else if (disp_tick) begin
            // latch whatever is currently being produced
            disp_y     <= y_out;
            disp_abs_d <= abs_d;
        end
    end

    // -----------------------------
    // 7-seg display (HEX0 is low nibble)
    // -----------------------------
    hex7seg u_hex0 (.nibble(disp_y[3:0]),    .seg(HEX0));
    hex7seg u_hex1 (.nibble(disp_y[7:4]),    .seg(HEX1));
    hex7seg u_hex2 (.nibble(disp_y[11:8]),   .seg(HEX2));
    hex7seg u_hex3 (.nibble(disp_y[15:12]),  .seg(HEX3));

    // Show abs(detail) upper byte (gives a feel for "detail energy")
    hex7seg u_hex4 (.nibble(disp_abs_d[11:8]),  .seg(HEX4));
    hex7seg u_hex5 (.nibble(disp_abs_d[15:12]), .seg(HEX5));

endmodule
