module public_smoke;
  reg[63:0]A,B;wire[63:0]result;wire overflow;reg[63:0]expected;reg expected_overflow;
  sub_64bit dut(.A(A),.B(B),.result(result),.overflow(overflow));
  task automatic check(input[63:0]av,bv);begin A=av;B=bv;#1;expected=av-bv;expected_overflow=(av[63]!=bv[63])&&(expected[63]!=av[63]);
    if(result!==expected||overflow!==expected_overflow)$fatal(1,"64-bit subtraction or overflow is wrong");end endtask
  initial begin check(64'd100,64'd37);check(64'h7fff_ffff_ffff_ffff,64'hffff_ffff_ffff_ffff);check(64'h8000_0000_0000_0000,64'd1);check(64'hffff_ffff_ffff_fff0,64'hffff_ffff_ffff_fff8);$display("VERIGYM_PUBLIC_PASS");$finish;end
endmodule
