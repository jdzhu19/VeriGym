`timescale 1ns/1ps
module public_smoke;
  reg CLK=0,RST=0;wire[5:0]Hours,Mins,Secs;integer i,eh,em,es;reg roll_s,roll_m;
  calendar dut(.CLK(CLK),.RST(RST),.Hours(Hours),.Mins(Mins),.Secs(Secs));always#5 CLK=~CLK;
  initial begin #1;RST=1;#1;if({Hours,Mins,Secs}!==0)$fatal(1,"calendar reset is wrong");@(negedge CLK);RST=0;eh=0;em=0;es=0;
    for(i=0;i<86405;i=i+1)begin roll_s=(es==59);roll_m=roll_s&&(em==59);if(roll_s)es=0;else es=es+1;if(roll_m)em=0;else if(roll_s)em=em+1;if(roll_m)begin if(eh==23)eh=0;else eh=eh+1;end
      @(posedge CLK);#1;if(Hours!==eh||Mins!==em||Secs!==es)$fatal(1,"calendar rollover is wrong");end
    RST=1;#1;if({Hours,Mins,Secs}!==0)$fatal(1,"calendar re-reset is wrong");$display("VERIGYM_PUBLIC_PASS");$finish;end
endmodule
