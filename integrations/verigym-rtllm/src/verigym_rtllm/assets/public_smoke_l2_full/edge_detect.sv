`timescale 1ns/1ps
module public_smoke;
  reg clk=0,rst_n=0,a=0;wire rise,down;reg previous;integer i;reg[11:0]values=12'b001110010110;
  edge_detect dut(.clk(clk),.rst_n(rst_n),.a(a),.rise(rise),.down(down));always#5 clk=~clk;
  initial begin repeat(2)@(negedge clk);if(rise!==0||down!==0)$fatal(1,"edge reset is wrong");rst_n=1;previous=0;
    for(i=11;i>=0;i=i-1)begin @(negedge clk);a=values[i];@(posedge clk);#1;if({rise,down}!={(values[i]&&!previous),(!values[i]&&previous)})$fatal(1,"edge pulse or polarity is wrong");previous=values[i];end
    @(negedge clk);rst_n=0;#1;if(rise!==0||down!==0)$fatal(1,"edge re-reset is wrong");$display("VERIGYM_PUBLIC_PASS");$finish;end
endmodule
