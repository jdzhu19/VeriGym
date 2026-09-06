`timescale 1ns/1ps
module public_smoke;
  reg CLK_in=0,RST=0;wire CLK_50,CLK_10,CLK_1;integer i,c10,c100;reg e50,e10,e1;
  freq_div dut(.CLK_in(CLK_in),.RST(RST),.CLK_50(CLK_50),.CLK_10(CLK_10),.CLK_1(CLK_1));always#5 CLK_in=~CLK_in;
  initial begin #1;RST=1;#1;if({CLK_50,CLK_10,CLK_1}!==0)$fatal(1,"frequency-divider reset is wrong");@(negedge CLK_in);RST=0;e50=0;e10=0;e1=0;c10=0;c100=0;
    for(i=0;i<205;i=i+1)begin e50=~e50;if(c10==4)begin c10=0;e10=~e10;end else c10=c10+1;if(c100==49)begin c100=0;e1=~e1;end else c100=c100+1;
      @(posedge CLK_in);#1;if({CLK_50,CLK_10,CLK_1}!={e50,e10,e1})$fatal(1,"frequency division cadence is wrong");end
    RST=1;#1;if({CLK_50,CLK_10,CLK_1}!==0)$fatal(1,"frequency-divider re-reset is wrong");$display("VERIGYM_PUBLIC_PASS");$finish;end
endmodule
