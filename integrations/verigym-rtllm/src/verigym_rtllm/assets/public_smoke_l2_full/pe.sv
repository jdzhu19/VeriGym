`timescale 1ns/1ps
module public_smoke;
  reg clk=0,rst=0;reg[31:0]a=0,b=0;wire[31:0]c;reg[31:0]expected;integer i;reg[31:0]av[0:4],bv[0:4];
  pe dut(.clk(clk),.rst(rst),.a(a),.b(b),.c(c));always#5 clk=~clk;
  initial begin av[0]=3;bv[0]=7;av[1]=32'hffff;bv[1]=17;av[2]=91;bv[2]=103;av[3]=32'h10000;bv[3]=32'h10000;av[4]=5;bv[4]=9;
    #1;rst=1;#1;if(c!==0)$fatal(1,"MAC reset is wrong");@(negedge clk);rst=0;expected=0;for(i=0;i<5;i=i+1)begin a=av[i];b=bv[i];expected=expected+av[i]*bv[i];@(posedge clk);#1;if(c!==expected)$fatal(1,"MAC accumulation is wrong");@(negedge clk);end
    rst=1;#1;if(c!==0)$fatal(1,"MAC re-reset is wrong");$display("VERIGYM_PUBLIC_PASS");$finish;end
endmodule
