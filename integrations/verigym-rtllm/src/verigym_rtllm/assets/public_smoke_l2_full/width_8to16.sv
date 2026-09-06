`timescale 1ns/1ps
module public_smoke;
  reg clk=0,rst_n=0,valid_in=0;reg[7:0]data_in=0;wire valid_out;wire[15:0]data_out;
  width_8to16 dut(.clk(clk),.rst_n(rst_n),.valid_in(valid_in),.data_in(data_in),.valid_out(valid_out),.data_out(data_out));always#5 clk=~clk;
  task automatic drive(input valid,input[7:0]value,input expected_valid,input[15:0]expected_data);begin @(negedge clk);valid_in=valid;data_in=value;@(posedge clk);#1;if(valid_out!==expected_valid)$fatal(1,"width-converter valid cadence is wrong");if(expected_valid&&data_out!==expected_data)$fatal(1,"width-converter byte order is wrong");end endtask
  initial begin repeat(2)@(negedge clk);if(valid_out!==0||data_out!==0)$fatal(1,"width-converter reset is wrong");rst_n=1;
    drive(1,8'ha6,0,0);drive(0,8'hff,0,0);drive(1,8'h3d,1,16'ha63d);drive(1,8'h12,0,0);drive(1,8'hef,1,16'h12ef);drive(0,0,0,0);
    @(negedge clk);rst_n=0;#1;if(valid_out!==0||data_out!==0)$fatal(1,"width-converter re-reset is wrong");$display("VERIGYM_PUBLIC_PASS");$finish;end
endmodule
