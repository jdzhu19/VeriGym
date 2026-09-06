module public_smoke;
  reg [32:1] A,B; wire [32:1] S; wire C32; reg [32:0] expected;
  adder_32bit dut(.A(A),.B(B),.S(S),.C32(C32));
  task automatic check(input [31:0] av,bv); begin A=av;B=bv;#1;expected={1'b0,av}+{1'b0,bv};
    if({C32,S}!==expected) $fatal(1,"32-bit CLA sum or carry is wrong"); end endtask
  initial begin check(0,0);check(32'hffff,1);check(32'hffff_ffff,1);check(32'h89ab_cdef,32'h7654_3211);check(32'h1357_9bdf,32'h2468_ace0);$display("VERIGYM_PUBLIC_PASS");$finish;end
endmodule
