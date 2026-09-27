// SPDX-License-Identifier: MIT
// Native finite-core measurement shell qualification; no hardware accesses.
`timescale 1ns/1ps
`default_nettype none
module measurement_engine_tb;
    logic clk = 1'b0;
    logic rst_n = 1'b0;
    logic [31:0] control = 32'd0;
    wire [479:0] probe;
    wire busy, done, fault;
    integer monitor_mode = 0;
    integer observed_outputs = 0, observed_inputs = 0, observed_frames = 0;
    integer observed_epoch_offset = 0;
    integer test_checks = 0;
    logic [11:0] dense_reference [0:1535];
    logic [11:0] masked_reference [0:1535];
    logic [479:0] saved_probe;
    logic [63:0] saved_elapsed;
    integer saved_outputs, saved_inputs, saved_frames;
    always #10 clk = ~clk;
    trecap_measurement_engine dut (
        .clk(clk), .rst_n(rst_n), .control_i(control), .probe_o(probe),
        .busy_o(busy), .done_o(done), .fault_o(fault)
    );
    function automatic logic [31:0] word(input integer idx);
        word = probe[idx*32 +: 32];
    endfunction
    task automatic check(input bit ok, input string label_text);
        if (!ok) $fatal(1, "MEASUREMENT_FAIL: %s state=%0d status=%08x flags=%08x", label_text, dut.state_q, word(1), word(11));
        test_checks = test_checks + 1;
    endtask
    task automatic snapshot;
        @(negedge clk);
        control[3] = ~control[3];
        @(posedge clk); #1;
        check(probe[41] === control[3], "atomic snapshot acknowledge");
        check(word(0) === 32'h54524350, "snapshot magic");
    endtask
    task automatic command(input integer mode, input integer count);
        @(negedge clk);
        check(!busy, "command issued while shell idle");
        monitor_mode = mode;
        observed_outputs = 0;
        observed_inputs = 0;
        observed_frames = 0;
        observed_epoch_offset = 0;
        control = {16'(count),12'd0,control[3],~control[2],2'(mode)};
        @(posedge clk); #1;
    endtask
    task automatic wait_terminal;
        integer cycles;
        cycles = 0;
        while (busy && (cycles < 600000)) begin
            @(negedge clk);
            cycles = cycles + 1;
        end
        check(!busy, "bounded terminal completion");
    endtask
    task automatic check_success(input integer epochs, input integer mode);
        wait_terminal();
        check(done && !fault, "successful batch completion");
        snapshot();
        check(word(3) == epochs, "completed epochs");
        check(word(4) == epochs*1536, "all output words compared");
        check(word(5) == 0, "no output mismatch");
        check(word(6) == epochs*1024, "useful input count excludes flush");
        check(word(7) == epochs*9, "frame statistics count");
        check(word(10) == 32'hffffffff, "first mismatch unset");
        check(word(11) == 0, "no fault flags");
        check(word(12) == 1536, "last epoch output count");
        check(word(13) > 70000 && word(13) < 110000, "last epoch cycles bounded");
        check((word(2) & 3) == mode, "latched command mode");
        check(observed_outputs == epochs*1536 && observed_inputs == epochs*1024 &&
              observed_frames == epochs*9, "independent passive counts");
        saved_elapsed = {word(9),word(8)};
        repeat (37) @(posedge clk);
        snapshot();
        check({word(9),word(8)} == saved_elapsed, "elapsed freezes when completed");
        $display("MEASUREMENT_BATCH_PASS mode=%0d epochs=%0d outputs=%0d inputs=%0d frames=%0d elapsed=%0d last_epoch=%0d checksum=%08x",
                 mode,epochs,word(4),word(6),word(7),{word(9),word(8)},word(13),word(14));
    endtask

    // Independent passive output checker uses TB-command ownership, not dut.mode_q.
    always @(posedge clk) begin
        if (rst_n && busy && !dut.core_clear) begin
            if (dut.source_valid && dut.source_ready && (dut.source_idx < 1024))
                observed_inputs = observed_inputs + 1;
            if (dut.tap_frame.valid) observed_frames = observed_frames + 1;
            if (dut.y_valid) begin
                if (dut.y_idx !== 64'(observed_epoch_offset))
                    $fatal(1, "passive output index mismatch");
                if (dut.y_data !== ((monitor_mode == 2) ? masked_reference[observed_epoch_offset] : dense_reference[observed_epoch_offset]))
                    $fatal(1, "passive numerical mismatch mode=%0d idx=%0d observed=%0d",monitor_mode,observed_epoch_offset,dut.y_data);
                observed_outputs = observed_outputs + 1;
                observed_epoch_offset = (observed_epoch_offset == 1535) ? 0 : observed_epoch_offset+1;
            end
        end
    end
    initial begin
        $readmemh("artifacts/measurement/multitone/y_dense.memh",dense_reference);
        $readmemh("artifacts/measurement/multitone/y_masked.memh",masked_reference);
        repeat(5) @(negedge clk);
        rst_n = 1'b1;
        repeat(5) @(negedge clk);
        snapshot();
        check(!busy && !done && !fault, "reset idle");

        command(1,2);
        while (observed_outputs < 5) @(negedge clk);
        // Changing mode/target without a start edge must not change active ownership.
        control[1:0] = 2'd2;
        control[31:16] = 16'd99;
        snapshot();
        check((word(2) & 3) == 1 && (word(2) >> 16) == 2, "mode/target held in flight");
        saved_probe = probe;
        repeat(200) @(negedge clk);
        check(probe === saved_probe, "snapshot remains frozen while counters advance");
        // Record counters before the snapshot edge: all words must describe that edge.
        saved_outputs=observed_outputs; saved_inputs=observed_inputs; saved_frames=observed_frames;
        control[3] = ~control[3];
        @(posedge clk); #1;
        check(word(4)==saved_outputs && word(6)==saved_inputs && word(7)==saved_frames,
              "snapshot counters captured coherently");
        check_success(2,1);

        // A completed result is revoked if the supposedly quiescent core emits
        // a late output. Snapshot must expose the fault; a new batch recovers.
        @(negedge clk); force dut.y_valid = 1'b1;
        @(posedge clk); #1;
        check(!done && fault && !busy, "late output revokes completed success");
        @(negedge clk); release dut.y_valid;
        snapshot();
        check(word(3)==2 && word(4)==3072 && (word(11)&32'h1000)!=0 && probe[34],
              "postdone activity retains counts and fault bit12");

        command(2,2);
        check_success(2,2);

        command(1,2);
        while (observed_outputs < 10) @(negedge clk);
        control[2] = ~control[2];
        control[1:0] = 2'd2;
        control[31:16] = 16'd7;
        wait_terminal();
        snapshot();
        check(fault && !done && probe[35] && !probe[34], "busy command rejected, not numerical fault");
        check(word(3)==1 && word(4)==1536 && word(11)==32'h800,
              "busy rejection finishes one epoch then freezes repetitions");
        check((word(2)&3)==1 && (word(2)>>16)==2, "busy rejection preserves accepted command");
        saved_probe=probe;
        repeat(100) @(negedge clk);
        snapshot();
        check(word(4)==1536 && word(3)==1, "rejected batch remains stopped");

        // Alter test-only expected ROM word, never production input/arithmetic.
        dut.expected_dense[0] = dut.expected_dense[0] ^ 12'd1;
        command(1,1);
        wait_terminal();
        snapshot();
        check(fault && !done && probe[34], "numerical disagreement halts");
        check(word(5)==1 && word(10)==0 && (word(11)&32'h100)!=0,
              "first-word mismatch has retained evidence");
        check(word(3)==0 && word(4)<1536, "no success or restart after mismatch");
        saved_elapsed={word(9),word(8)};
        repeat(51) @(negedge clk);
        snapshot();
        check({word(9),word(8)}==saved_elapsed && word(5)==1, "fault evidence freezes");
        dut.expected_dense[0] = dut.expected_dense[0] ^ 12'd1;
        command(1,1);
        check_success(1,1);

        // Fault-inject a watchdog expiration to test its terminal path.
        command(2,1);
        wait(dut.state_q == 4'd5);
        @(negedge clk); force dut.watchdog_q = 32'd1000000;
        @(posedge clk); #1; release dut.watchdog_q;
        wait_terminal(); snapshot();
        check(fault && !done && (word(11)&32'h200)!=0, "watchdog expiration terminal");

        command(0,0);
        snapshot();
        check(!busy && done && !fault && word(4)==0 && word(11)==0, "explicit idle command clears retained faults");
        // Zero active epoch count is rejected without launching the core.
        @(negedge clk); control={16'd0,12'd0,control[3],~control[2],2'd1};
        repeat(3) @(negedge clk); snapshot();
        check(fault && !busy && !done && probe[35] && word(4)==0, "invalid zero epoch target rejected");
        $display("MEASUREMENT_ENGINE_PASS checks=%0d",test_checks);
        $finish;
    end
    initial begin
        #40000000;
        $fatal(1,"MEASUREMENT_TEST_TIMEOUT");
    end
endmodule
`default_nettype wire
