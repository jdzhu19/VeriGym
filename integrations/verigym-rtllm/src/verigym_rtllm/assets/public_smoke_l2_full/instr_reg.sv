`timescale 1ns/1ps
module public_smoke;
  reg clk=0,rst=0;reg[1:0]fetch=0;reg[7:0]data=0;wire[2:0]ins;wire[4:0]ad1;wire[7:0]ad2;
  instr_reg dut(.clk(clk),.rst(rst),.fetch(fetch),.data(data),.ins(ins),.ad1(ad1),.ad2(ad2));always#5 clk=~clk;
  task automatic load(input[1:0]f,input[7:0]v);begin @(negedge clk);fetch=f;data=v;@(posedge clk);#1;end endtask
  initial begin repeat(2)@(negedge clk);if({ins,ad1,ad2}!==0)$fatal(1,"instruction-register reset is wrong");rst=1;
    load(2'b01,8'b101_10011);if(ins!==3'b101||ad1!==5'b10011||ad2!==0)$fatal(1,"first instruction field mapping is wrong");
    load(2'b10,8'hd7);if(ins!==3'b101||ad1!==5'b10011||ad2!==8'hd7)$fatal(1,"second instruction register is wrong");
    load(0,8'h00);if(ins!==3'b101||ad1!==5'b10011||ad2!==8'hd7)$fatal(1,"instruction hold behavior is wrong");
    @(negedge clk);rst=0;#1;if({ins,ad1,ad2}!==0)$fatal(1,"instruction-register re-reset is wrong");$display("VERIGYM_PUBLIC_PASS");$finish;end
endmodule
