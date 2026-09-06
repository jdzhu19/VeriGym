`timescale 1ns/1ps
module public_smoke;
  reg clk=0,rst_n=0,data_in=0;wire data_out;integer i;reg[12:0]bits=13'b1101010010100;reg[1:0]history;
  pulse_detect dut(.clk(clk),.rst_n(rst_n),.data_in(data_in),.data_out(data_out));always#5 clk=~clk;
  initial begin repeat(2)@(negedge clk);if(data_out!==0)$fatal(1,"pulse-detector reset is wrong");rst_n=1;history=2'b11;
    for(i=12;i>=0;i=i-1)begin @(negedge clk);data_in=bits[i];#1;if(data_out!==({history,bits[i]}==3'b010))$fatal(1,"010 detection or Mealy timing is wrong");@(posedge clk);#1;history={history[0],bits[i]};end
    @(negedge clk);rst_n=0;#1;if(data_out!==0)$fatal(1,"pulse-detector re-reset is wrong");$display("VERIGYM_PUBLIC_PASS");$finish;end
endmodule
