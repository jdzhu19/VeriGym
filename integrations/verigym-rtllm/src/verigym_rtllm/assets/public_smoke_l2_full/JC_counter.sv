`timescale 1ns/1ps
module public_smoke;
  reg clk=0,rst_n=0;wire[63:0]Q;reg[63:0]expected;integer i;
  JC_counter dut(.clk(clk),.rst_n(rst_n),.Q(Q));always#5 clk=~clk;
  initial begin repeat(2)@(negedge clk);if(Q!==0)$fatal(1,"Johnson reset is wrong");expected=0;rst_n=1;
    for(i=0;i<132;i=i+1)begin expected={~expected[0],expected[63:1]};@(posedge clk);#1;if(Q!==expected)$fatal(1,"Johnson sequence or wrap is wrong");end
    @(negedge clk);rst_n=0;#1;if(Q!==0)$fatal(1,"Johnson re-reset is wrong");$display("VERIGYM_PUBLIC_PASS");$finish;end
endmodule
