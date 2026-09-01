`timescale 1ns/1ps
module public_smoke;
  reg clk=0,rst_n=0;wire clk_div;integer i,count;reg expected;
  freq_diveven #(.NUM_DIV(6)) dut(.clk(clk),.rst_n(rst_n),.clk_div(clk_div));always#5 clk=~clk;
  initial begin repeat(2)@(negedge clk);if(clk_div!==0)$fatal(1,"even-divider reset is wrong");rst_n=1;count=0;expected=0;
    for(i=0;i<25;i=i+1)begin if(count<2)count=count+1;else begin count=0;expected=~expected;end @(posedge clk);#1;if(clk_div!==expected)$fatal(1,"even-divider period is wrong");end
    @(negedge clk);rst_n=0;#1;if(clk_div!==0)$fatal(1,"even-divider re-reset is wrong");$display("VERIGYM_PUBLIC_PASS");$finish;end
endmodule
