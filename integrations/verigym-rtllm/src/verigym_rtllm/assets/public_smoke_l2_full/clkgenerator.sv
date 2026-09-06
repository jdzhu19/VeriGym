`timescale 1ns/1ps
module public_smoke;
  wire clk;clkgenerator #(.PERIOD(10)) dut(.clk(clk));integer i;time last_edge,half_period;
  initial begin #1;if(clk!==0)$fatal(1,"generated clock initial level is wrong");@(posedge clk);last_edge=$time;@(negedge clk);half_period=$time-last_edge;
    if(half_period==0)$fatal(1,"generated clock did not advance in time");last_edge=$time;for(i=0;i<4;i=i+1)begin
    @(posedge clk);if($time-last_edge!=half_period)$fatal(1,"generated clock rising-edge spacing is wrong");last_edge=$time;
    @(negedge clk);if($time-last_edge!=half_period)$fatal(1,"generated clock falling-edge spacing is wrong");last_edge=$time;end
    $display("VERIGYM_PUBLIC_PASS");$finish;end
endmodule
