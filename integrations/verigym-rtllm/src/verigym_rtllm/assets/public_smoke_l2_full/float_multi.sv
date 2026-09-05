`timescale 1ns/1ps
module public_smoke;
  reg clk=0,rst=0;reg[31:0]a=0,b=0;wire[31:0]z;integer i;
  float_multi dut(.clk(clk),.rst(rst),.a(a),.b(b),.z(z));always#5 clk=~clk;
  task automatic run(input[31:0]av,bv,expected);begin @(negedge clk);rst=1;a=av;b=bv;#1;@(negedge clk);rst=0;
    for(i=0;i<7;i=i+1)@(posedge clk);#1;if(z!==expected)$fatal(1,"floating-point product or staged latency is wrong");end endtask
  initial begin run(32'h3fc00000,32'h40000000,32'h40400000);run(32'hc0800000,32'h3f000000,32'hc0000000);$display("VERIGYM_PUBLIC_PASS");$finish;end
endmodule
