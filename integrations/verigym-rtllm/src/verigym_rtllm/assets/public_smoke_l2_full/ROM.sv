module public_smoke;
  reg[7:0]addr;wire[15:0]dout;ROM dut(.addr(addr),.dout(dout));
  task automatic check(input[7:0]av,input[15:0]expected);begin addr=av;#1;if(dout!==expected)$fatal(1,"ROM contents or address mapping is wrong");end endtask
  initial begin check(0,16'ha0a0);check(1,16'hb1b1);check(2,16'hc2c2);check(3,16'hd3d3);$display("VERIGYM_PUBLIC_PASS");$finish;end
endmodule
