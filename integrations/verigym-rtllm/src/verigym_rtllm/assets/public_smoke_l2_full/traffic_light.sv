`timescale 1ns/1ps
module public_smoke;
  reg rst_n=0,clk=0,pass_request=0;wire[7:0]clock;wire red,yellow,green;integer i;reg seen_red,seen_green,seen_yellow,shortened;
  traffic_light dut(.rst_n(rst_n),.clk(clk),.pass_request(pass_request),.clock(clock),.red(red),.yellow(yellow),.green(green));always#5 clk=~clk;
  initial begin repeat(2)@(negedge clk);if({red,yellow,green}!==0||clock!==10)$fatal(1,"traffic-light reset is wrong");rst_n=1;seen_red=0;seen_green=0;seen_yellow=0;shortened=0;
    for(i=0;i<140;i=i+1)begin @(posedge clk);#1;if((red+yellow+green)>1)$fatal(1,"traffic-light outputs are not one-hot");seen_red=seen_red|red;seen_green=seen_green|green;seen_yellow=seen_yellow|yellow;
      if(green&&clock>15&&!shortened)begin @(negedge clk);pass_request=1;@(posedge clk);#1;if(clock!==10)$fatal(1,"pedestrian request did not shorten green time");shortened=1;@(negedge clk);pass_request=0;end end
    if(!seen_red||!seen_green||!seen_yellow||!shortened)$fatal(1,"traffic-light sequence is incomplete");@(negedge clk);rst_n=0;#1;if({red,yellow,green}!==0||clock!==10)$fatal(1,"traffic-light re-reset is wrong");$display("VERIGYM_PUBLIC_PASS");$finish;end
endmodule
