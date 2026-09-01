`timescale 1ns/1ps
module public_smoke;
  reg IN=0,CLK=0,RST=0;wire MATCH;fsm dut(.IN(IN),.CLK(CLK),.RST(RST),.MATCH(MATCH));always#5 CLK=~CLK;
  task automatic bit_in(input value,input expected);begin @(negedge CLK);IN=value;#1;if(MATCH!==expected)$fatal(1,"FSM match value or Mealy timing is wrong");@(posedge CLK);#1;end endtask
  initial begin #1;RST=1;#1;if(MATCH!==0)$fatal(1,"FSM reset is wrong");@(negedge CLK);RST=0;
    bit_in(1,0);bit_in(0,0);bit_in(1,0);bit_in(0,0);bit_in(0,0);
    bit_in(1,0);bit_in(0,0);bit_in(0,0);bit_in(1,0);bit_in(1,1);bit_in(0,0);bit_in(0,0);bit_in(1,0);bit_in(1,1);
    RST=1;#1;if(MATCH!==0)$fatal(1,"FSM re-reset is wrong");$display("VERIGYM_PUBLIC_PASS");$finish;end
endmodule
