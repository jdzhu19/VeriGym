`timescale 1ns/1ps
module public_smoke;
  reg clk=0,rst_n=0;wire clk_div;integer i,c1,c2;reg d1,d2;
  freq_divbyodd #(.NUM_DIV(5)) dut(.clk(clk),.rst_n(rst_n),.clk_div(clk_div));always#5 clk=~clk;
  initial begin repeat(2)@(negedge clk);#1;if(clk_div!==1)$fatal(1,"odd-divider reset is wrong");rst_n=1;c1=0;c2=0;d1=1;d2=1;
    for(i=0;i<20;i=i+1)begin @(posedge clk);d1=(c1<2);if(c1<4)c1=c1+1;else c1=0;#1;if(clk_div!==(d1|d2))$fatal(1,"odd-divider positive-edge phase is wrong");
      @(negedge clk);d2=(c2<2);if(c2<4)c2=c2+1;else c2=0;#1;if(clk_div!==(d1|d2))$fatal(1,"odd-divider negative-edge phase is wrong");end
    rst_n=0;#1;if(clk_div!==1)$fatal(1,"odd-divider re-reset is wrong");$display("VERIGYM_PUBLIC_PASS");$finish;end
endmodule
