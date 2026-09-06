`timescale 1ns/1ps
module public_smoke;
  reg clk=0,rst_n=0;wire[4:0]wave;integer i;reg state;reg[4:0]expected;
  signal_generator dut(.clk(clk),.rst_n(rst_n),.wave(wave));always#5 clk=~clk;
  initial begin repeat(2)@(negedge clk);if(wave!==0)$fatal(1,"triangle reset is wrong");rst_n=1;state=0;expected=0;
    for(i=0;i<136;i=i+1)begin if(!state)begin if(expected==31)state=1;else expected=expected+1;end else begin if(expected==0)state=0;else expected=expected-1;end
      @(posedge clk);#1;if(wave!==expected)$fatal(1,"triangle direction or endpoint behavior is wrong");end
    @(negedge clk);rst_n=0;#1;if(wave!==0)$fatal(1,"triangle re-reset is wrong");$display("VERIGYM_PUBLIC_PASS");$finish;end
endmodule
