`timescale 1ns/1ps
module public_smoke;
  reg clk=0,rst_n=0;reg[3:0]mul_a=0,mul_b=0;wire[7:0]mul_out;
  multi_pipe_4bit #(.size(4)) dut(.clk(clk),.rst_n(rst_n),.mul_a(mul_a),.mul_b(mul_b),.mul_out(mul_out));always#5 clk=~clk;
  task automatic run(input[3:0]av,bv);begin @(negedge clk);rst_n=0;@(negedge clk);if(mul_out!==0)$fatal(1,"pipeline reset is wrong");rst_n=1;mul_a=av;mul_b=bv;
    @(posedge clk);#1;if(mul_out!==0)$fatal(1,"pipeline latency is too short");@(posedge clk);#1;if(mul_out!==av*bv)$fatal(1,"pipeline product is wrong");end endtask
  initial begin run(4'd13,4'd11);run(4'd15,4'd15);run(4'd7,4'd0);$display("VERIGYM_PUBLIC_PASS");$finish;end
endmodule
