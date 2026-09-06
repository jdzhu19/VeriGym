module public_smoke;
  reg[31:0]a,b;wire[31:0]c;fixed_point_adder dut(.a(a),.b(b),.c(c));
  task automatic check(input[31:0]av,bv,expected);begin a=av;b=bv;#1;if(c!==expected)$fatal(1,"fixed-point sign-magnitude addition is wrong");end endtask
  initial begin check(32'd25,32'd17,32'd42);check(32'h80000019,32'h80000011,32'h8000002a);check(32'd40,32'h8000000d,32'd27);check(32'd13,32'h80000028,32'h8000001b);check(32'd9,32'h80000009,0);$display("VERIGYM_PUBLIC_PASS");$finish;end
endmodule
