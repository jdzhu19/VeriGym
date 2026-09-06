module public_smoke;
  reg[31:0]a,b;wire[31:0]c;fixed_point_subtractor dut(.a(a),.b(b),.c(c));
  task automatic check(input[31:0]av,bv,expected);begin a=av;b=bv;#1;if(c!==expected)$fatal(1,"fixed-point sign-magnitude subtraction is wrong");end endtask
  initial begin check(32'd25,32'd7,32'd18);check(32'h80000019,32'h80000007,32'h80000012);check(32'd19,32'h80000005,32'd24);check(32'h80000013,32'd5,32'h80000018);$display("VERIGYM_PUBLIC_PASS");$finish;end
endmodule
