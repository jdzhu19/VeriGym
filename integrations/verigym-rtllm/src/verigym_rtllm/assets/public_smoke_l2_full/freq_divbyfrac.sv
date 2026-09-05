`timescale 1ns/1ps
module public_smoke;
  reg clk=0,rst_n=0;wire clk_div;integer i,cnt;reg ave,adjust;
  freq_divbyfrac #(.MUL2_DIV_CLK(7)) dut(.rst_n(rst_n),.clk(clk),.clk_div(clk_div));always#5 clk=~clk;
  initial begin repeat(2)@(negedge clk);#1;if(clk_div!==0)$fatal(1,"fractional-divider reset is wrong");rst_n=1;cnt=0;ave=0;adjust=0;
    for(i=0;i<20;i=i+1)begin @(posedge clk);ave=(cnt==0||cnt==4);if(cnt==6)cnt=0;else cnt=cnt+1;#1;if(clk_div!==(ave|adjust))$fatal(1,"fractional-divider positive-edge phase is wrong");
      @(negedge clk);adjust=(cnt==1||cnt==4);#1;if(clk_div!==(ave|adjust))$fatal(1,"fractional-divider negative-edge phase is wrong");end
    rst_n=0;#1;if(clk_div!==0)$fatal(1,"fractional-divider re-reset is wrong");$display("VERIGYM_PUBLIC_PASS");$finish;end
endmodule
