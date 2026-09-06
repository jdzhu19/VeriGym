`timescale 1ns/1ps
module public_smoke;
  reg clk=0,reset=0;wire[7:0]out;reg[7:0]expected;integer i;
  ring_counter dut(.clk(clk),.reset(reset),.out(out));always#5 clk=~clk;
  initial begin #1;reset=1;#1;if(out!==8'h01)$fatal(1,"ring reset is wrong");@(negedge clk);reset=0;expected=1;
    for(i=0;i<17;i=i+1)begin expected={expected[6:0],expected[7]};@(posedge clk);#1;if(out!==expected)$fatal(1,"ring sequence or wrap is wrong");end
    reset=1;#1;if(out!==1)$fatal(1,"ring asynchronous reset is wrong");$display("VERIGYM_PUBLIC_PASS");$finish;end
endmodule
