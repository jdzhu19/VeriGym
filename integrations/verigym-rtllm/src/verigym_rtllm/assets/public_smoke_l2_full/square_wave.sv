`timescale 1ns/1ps
module public_smoke;
  reg clk=0;reg[7:0]freq=3;wire wave_out;integer i,count;reg expected;
  square_wave dut(.clk(clk),.freq(freq),.wave_out(wave_out));always#5 clk=~clk;
  initial begin #1;if(wave_out!==0)$fatal(1,"square-wave initialization is wrong");count=0;expected=0;
    for(i=0;i<18;i=i+1)begin if(count==freq-1)begin count=0;expected=~expected;end else count=count+1;@(posedge clk);#1;if(wave_out!==expected)$fatal(1,"square-wave toggle period is wrong");end
    $display("VERIGYM_PUBLIC_PASS");$finish;end
endmodule
