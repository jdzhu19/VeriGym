`timescale 1ns/1ps
module public_smoke;
  reg clk=0,reset=0;reg[7:0]a=0,b=0;wire[15:0]p;wire rdy;integer i;reg signed[7:0]sa,sb;reg signed[15:0]expected;
  multi_booth_8bit dut(.clk(clk),.reset(reset),.a(a),.b(b),.p(p),.rdy(rdy));always#5 clk=~clk;
  task automatic run(input signed[7:0]av,bv);begin @(negedge clk);a=av;b=bv;reset=1;#1;if(p!==0||rdy!==0)$fatal(1,"booth reset is wrong");
    @(negedge clk);reset=0;for(i=0;i<16;i=i+1)begin @(posedge clk);#1;if(rdy!==0)$fatal(1,"booth ready asserted early");end
    @(posedge clk);#1;sa=av;sb=bv;expected=sa*sb;if(rdy!==1||$signed(p)!==expected)$fatal(1,"booth product or ready latency is wrong");end endtask
  initial begin run(8'sd37,-8'sd11);run(-8'sd64,-8'sd3);run(8'sd7,8'sd19);$display("VERIGYM_PUBLIC_PASS");$finish;end
endmodule
