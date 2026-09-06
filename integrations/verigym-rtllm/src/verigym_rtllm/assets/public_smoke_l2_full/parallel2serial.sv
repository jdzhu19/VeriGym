`timescale 1ns/1ps
module public_smoke;
  reg clk=0,rst_n=0;reg[3:0]d=0;wire valid_out,dout;integer i;
  parallel2serial dut(.clk(clk),.rst_n(rst_n),.d(d),.valid_out(valid_out),.dout(dout));always#5 clk=~clk;
  initial begin repeat(2)@(negedge clk);if(valid_out!==0||dout!==0)$fatal(1,"serializer reset is wrong");rst_n=1;d=4'b1010;
    for(i=0;i<3;i=i+1)begin @(posedge clk);#1;if(valid_out!==0)$fatal(1,"serializer valid asserted before load");end
    @(posedge clk);#1;if(valid_out!==1||dout!==1)$fatal(1,"serializer load cycle is wrong");
    @(posedge clk);#1;if(valid_out!==0||dout!==0)$fatal(1,"serializer bit 2 is wrong");
    @(posedge clk);#1;if(valid_out!==0||dout!==1)$fatal(1,"serializer bit 1 is wrong");
    @(posedge clk);#1;if(valid_out!==0||dout!==0)$fatal(1,"serializer bit 0 is wrong");
    @(negedge clk);rst_n=0;#1;if(valid_out!==0||dout!==0)$fatal(1,"serializer re-reset is wrong");$display("VERIGYM_PUBLIC_PASS");$finish;end
endmodule
