`timescale 1ns/1ps
module public_smoke;
  reg clk=0,d=0;wire[7:0]q;reg[7:0]expected=0;integer i;reg[15:0]bits=16'b1011_0010_0110_1101;
  right_shifter dut(.clk(clk),.d(d),.q(q));always#5 clk=~clk;
  initial begin #1;if(q!==0)$fatal(1,"right shifter initialization is wrong");for(i=15;i>=0;i=i-1)begin @(negedge clk);d=bits[i];expected={bits[i],expected[7:1]};@(posedge clk);#1;if(q!==expected)$fatal(1,"right-shift order is wrong");end
    $display("VERIGYM_PUBLIC_PASS");$finish;end
endmodule
