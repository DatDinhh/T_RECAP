`timescale 1ns/1ps
module stage_case #(parameter integer NORM=0, OW=36)(output logic done=0);
  localparam integer N=2304;
  reg clk=0; always #5 clk=~clk;
  reg rst_n=0, clear=0, iv=0, ordy=0;
  reg signed [35:0] ar=0,ai=0,br=0,bi=0;
  reg signed [16:0] wr=0,wi=0;
  wire [3:0] ir,ov,sat,ia,oa;
  wire signed [OW-1:0] y0r[4],y0i[4],y1r[4],y1i[4];
  reg [177:0] vin[0:N-1];
  reg [4*OW:0] gold[0:N-1];
  string vectors;
  integer current=0, checks=0, results=0, zeros=0, nonzeros=0, sats=0;
  integer aborts=0, stalls=0;
  reg check_gold=0;
  reg signed [35:0] hb_r=0,hb_i=0;
  reg signed [16:0] hw_r=0,hw_i=0;
  baseline_fft_stage #(.DATA_W(36),.TWIDDLE_W(17),.OUT_W(OW),.FRAC_SHIFT(15),.NORMALIZE_BY_2(NORM),.REGISTER_OUTPUT(1)) ref_dut
    (.clk(clk),.rst_n(rst_n),.clear_i(clear),.valid_i(iv),.ready_o(ir[0]),.a_re_i(ar),.a_im_i(ai),.b_re_i(br),.b_im_i(bi),.tw_re_i(wr),.tw_im_i(wi),.valid_o(ov[0]),.ready_i(ordy),.y0_re_o(y0r[0]),.y0_im_o(y0i[0]),.y1_re_o(y1r[0]),.y1_im_o(y1i[0]),.sat_any_o(sat[0]),.input_accept_pulse_o(ia[0]),.output_accept_pulse_o(oa[0]));
  genvar g;
  generate for(g=1;g<4;g=g+1) begin: variants
    trecap_fft_stage #(.DATA_W(36),.TWIDDLE_W(17),.OUT_W(OW),.FRAC_SHIFT(15),.NORMALIZE_BY_2(NORM),.REGISTER_OUTPUT(1),.SUPPORT_ZERO_B_ISOLATION(g!=1)) dut
      (.clk(clk),.rst_n(rst_n),.clear_i(clear),.zero_b_isolation_i(g!=2),.valid_i(iv),.ready_o(ir[g]),.a_re_i(ar),.a_im_i(ai),.b_re_i(br),.b_im_i(bi),.tw_re_i(wr),.tw_im_i(wi),.valid_o(ov[g]),.ready_i(ordy),.y0_re_o(y0r[g]),.y0_im_o(y0i[g]),.y1_re_o(y1r[g]),.y1_im_o(y1i[g]),.sat_any_o(sat[g]),.input_accept_pulse_o(ia[g]),.output_accept_pulse_o(oa[g]));
  end endgenerate
  always @(posedge clk) begin: check
    integer j;
    if (!rst_n || clear) begin hb_r=0;hb_i=0;hw_r=0;hw_i=0;end
    else begin
      for(j=1;j<4;j=j+1) begin
        if ({ir[j],ov[j],ia[j],oa[j]} !== {ir[0],ov[0],ia[0],oa[0]}) $fatal(1,"stage handshake norm=%0d case=%0d",NORM,current);
        if(ov[0] && {sat[j],y0r[j],y0i[j],y1r[j],y1i[j]} !== {sat[0],y0r[0],y0i[0],y1r[0],y1i[0]}) $fatal(1,"stage lockstep norm=%0d case=%0d variant=%0d",NORM,current,j);
      end
      if(ov[0] && check_gold && {sat[0],y0r[0],y0i[0],y1r[0],y1i[0]} !== gold[current]) $fatal(1,"stage integer oracle norm=%0d case=%0d got=%h expected=%h",NORM,current,{sat[0],y0r[0],y0i[0],y1r[0],y1i[0]},gold[current]);
      if(ov[0] && !ordy) stalls=stalls+1;
      if(ia[0]) begin
        if(br==0 && bi==0) begin
          zeros=zeros+1;
          if({variants[3].dut.gen_registered_output.mul_b_re,variants[3].dut.gen_registered_output.mul_b_im,variants[3].dut.gen_registered_output.mul_tw_re,variants[3].dut.gen_registered_output.mul_tw_im} !== {hb_r,hb_i,hw_r,hw_i}) $fatal(1,"isolated multiplier inputs changed for zero b");
        end else begin
          nonzeros=nonzeros+1;
          if({variants[3].dut.gen_registered_output.mul_b_re,variants[3].dut.gen_registered_output.mul_b_im,variants[3].dut.gen_registered_output.mul_tw_re,variants[3].dut.gen_registered_output.mul_tw_im} !== {br,bi,wr,wi}) $fatal(1,"nonzero multiplier inputs incorrect");
          hb_r=br;hb_i=bi;hw_r=wr;hw_i=wi;
        end
      end
      if(oa[0] && check_gold) begin results=results+1;if(sat[0])sats=sats+1;end
      checks=checks+1;
    end
  end
  task send(input integer k,input integer delay_out);
    begin
      @(negedge clk); current=k;check_gold=1;{ar,ai,br,bi,wr,wi}=vin[k];iv=1;ordy=0;
      do @(posedge clk); while(!ir[0]);
      @(negedge clk);iv=0;
      // Accepted operands are owned by the pipeline; subsequent input activity
      // must not affect the result, including a zero/nonzero boundary.
      ar=36'h812345678;ai=36'h7abcdef01;br=~br;bi=~bi;wr=~wr;wi=~wi;
      while(!ov[0]) @(negedge clk);
      repeat(delay_out) @(negedge clk);
      ordy=1;@(posedge clk);@(negedge clk);ordy=0;check_gold=0;
    end
  endtask
  task abort_transaction(input integer phase,input bit use_reset);
    begin
      @(negedge clk);check_gold=0;{ar,ai,br,bi,wr,wi}=vin[1];iv=1;ordy=0;
      @(posedge clk);@(negedge clk);iv=0;
      repeat(phase) @(negedge clk);
      if(use_reset)rst_n=0;else clear=1;
      repeat(2) @(negedge clk);
      rst_n=1;clear=0;
      repeat(8) begin @(negedge clk);if(ov[0])$fatal(1,"aborted stage leaked valid");end
      aborts=aborts+1;
      send(0,2);send(1,1);
    end
  endtask
  integer i;
  initial begin
    if(!$value$plusargs("VECTORS=%s",vectors)) $fatal(1,"missing VECTORS");
    $readmemh({vectors,"/stage_input.memh"},vin);
    $readmemh({vectors,NORM ? "/stage_norm_gold.memh" : "/stage_gold.memh"},gold);
    repeat(3)@(negedge clk);rst_n=1;
    for(i=0;i<N;i=i+1)send(i,(i%19==0)?17:(i%4));
    for(i=0;i<6;i=i+1)begin abort_transaction(i,0);abort_transaction(i,1);end
    if(zeros<100 || nonzeros<100 || sats<100 || results!=N+24 || aborts!=12 || stalls<100) $fatal(1,"stage coverage insufficient");
    $display("STAGE_CASE_PASS norm=%0d width=%0d checks=%0d outputs=%0d zero=%0d nonzero=%0d saturated=%0d aborts=%0d stalled_cycles=%0d",NORM,OW,checks,results,zeros,nonzeros,sats,aborts,stalls);
    done=1;
  end
endmodule
module stage_lockstep_tb;
  wire a,b;
  stage_case #(.NORM(0),.OW(36)) normal(a);
  stage_case #(.NORM(1),.OW(28)) normalized(b);
  initial begin wait(a&&b);$display("STUDY_STAGE_PASS");$finish;end
  initial begin #10000000;$fatal(1,"stage watchdog");end
endmodule
