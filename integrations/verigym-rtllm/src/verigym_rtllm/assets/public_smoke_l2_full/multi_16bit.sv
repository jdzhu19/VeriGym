`timescale 1ns/1ps
module public_smoke;
  reg clk=0,rst_n=0,start=0;reg[15:0]ain=0,bin=0;wire[31:0]yout;wire done;integer i;
  multi_16bit dut(.clk(clk),.rst_n(rst_n),.start(start),.ain(ain),.bin(bin),.yout(yout),.done(done));always#5 clk=~clk;
  initial begin repeat(2)@(negedge clk);if(done!==0||yout!==0)$fatal(1,"multiplier reset is wrong");
    ain=16'h81a3;bin=16'h0127;start=1;rst_n=1;
    for(i=0;i<16;i=i+1)begin @(posedge clk);#1;if(done!==0)$fatal(1,"done asserted early");end
    @(posedge clk);#1;if(done!==1||yout!==(16'h81a3*16'h0127))$fatal(1,"iterative product or done latency is wrong");
    @(posedge clk);#1;if(done!==0)$fatal(1,"done is not one cycle");
    @(negedge clk);rst_n=0;#1;if(done!==0||yout!==0)$fatal(1,"multiplier re-reset is wrong");
    $display("VERIGYM_PUBLIC_PASS");$finish;end
endmodule
