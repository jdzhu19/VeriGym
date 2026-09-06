`timescale 1ns/1ps
module public_smoke;
  reg clk=0,rst_n=0,valid_in=0; reg [7:0] data_in=0; wire valid_out; wire [9:0] data_out;
  accu dut(.clk(clk),.rst_n(rst_n),.data_in(data_in),.valid_in(valid_in),.valid_out(valid_out),.data_out(data_out));
  always #5 clk=~clk;
  task automatic sample(input [7:0] value,input expected_valid,input [9:0] expected_sum);
    begin @(negedge clk); valid_in=1; data_in=value; @(posedge clk); #1;
      if(valid_out!==expected_valid) $fatal(1,"accumulator valid cadence is wrong");
      if(expected_valid && data_out!==expected_sum) $fatal(1,"accumulator sum is wrong"); end
  endtask
  initial begin repeat(2) @(negedge clk); if(valid_out!==0||data_out!==0) $fatal(1,"accumulator reset is wrong");
    rst_n=1;valid_in=1;data_in=8'd201;@(posedge clk);#1;if(valid_out!==0)$fatal(1,"accumulator valid cadence is wrong");
    sample(8'd17,0,0); sample(8'd99,0,0); sample(8'd3,1,10'd320);
    @(negedge clk); rst_n=0; #1; if(valid_out!==0||data_out!==0) $fatal(1,"accumulator re-reset is wrong");
    $display("VERIGYM_PUBLIC_PASS"); $finish; end
endmodule
