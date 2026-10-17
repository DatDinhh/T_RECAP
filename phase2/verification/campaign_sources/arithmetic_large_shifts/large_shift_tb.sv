`timescale 1ns/1ps
module large_shift_tb;
 import trecap_math_pkg::*;
 reg signed [63:0] value; wire signed [11:0] actual[0:5];wire hi[0:5],lo[0:5],sat[0:5];
 reg signed [127:0] expected[0:5]; string dir;integer fd,tf,parsed,n,row,g,shift;
 for(genvar i=0;i<6;i++)begin:slots
  localparam integer S=i==0?62:i==1?63:i==2?64:i==3?65:i==4?127:128;
  trecap_round_sat #(.IN_W(64),.OUT_W(12),.SHIFT(S)) dut(.value_i(value),.value_o(actual[i]),.sat_hi_o(hi[i]),.sat_lo_o(lo[i]),.sat_any_o(sat[i]));
 end
 initial begin
  if(!$value$plusargs("OUT=%s",dir))$fatal(1,"SETUP");fd=$fopen({dir,"/vectors.txt"},"r");tf=$fopen({dir,"/trace.txt"},"w");
  parsed=$fscanf(fd,"%d",n);if(parsed!=1)$fatal(1,"COUNT");
  for(row=0;row<n;row++)begin
   parsed=$fscanf(fd,"%h %h %h %h %h %h %h",value,expected[0],expected[1],expected[2],expected[3],expected[4],expected[5]);if(parsed!=7)$fatal(1,"ROW");#2;
   for(g=0;g<6;g++)begin
    shift=g==0?62:g==1?63:g==2?64:g==3?65:g==4?127:128;
    if(trecap_rnd_shr(trecap_math_swide_t'(value),shift)!==expected[g] || $signed(actual[g])!==$signed(expected[g][11:0]) || hi[g] || lo[g] || sat[g])$fatal(1,"LARGE_SHIFT_MISMATCH row=%0d shift=%0d",row,shift);
    $fwrite(tf,"%016h %0d %032h\n",value,shift,trecap_rnd_shr(trecap_math_swide_t'(value),shift));
   end
  end
  $display("PASS large_shift rows=%0d comparisons=%0d",n,n*6);$fclose(fd);$fclose(tf);$finish;
 end
endmodule
