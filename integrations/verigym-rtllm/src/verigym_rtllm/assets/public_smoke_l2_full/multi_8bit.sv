module public_smoke;
  reg[7:0]A,B;wire[15:0]product;integer i;
  multi_8bit dut(.A(A),.B(B),.product(product));
  task automatic check(input[7:0]av,bv);begin A=av;B=bv;#1;if(product!==av*bv)$fatal(1,"8-bit product is wrong");end endtask
  initial begin check(0,255);check(1,173);check(13,19);check(128,3);check(255,255);for(i=0;i<8;i=i+1)check(8'h81,1<<i);$display("VERIGYM_PUBLIC_PASS");$finish;end
endmodule
