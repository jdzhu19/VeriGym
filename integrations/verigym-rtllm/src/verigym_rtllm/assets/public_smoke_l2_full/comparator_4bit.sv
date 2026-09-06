module public_smoke;
  reg[3:0]A,B;wire A_greater,A_equal,A_less;integer i,j;
  comparator_4bit dut(.A(A),.B(B),.A_greater(A_greater),.A_equal(A_equal),.A_less(A_less));
  initial begin for(i=0;i<16;i=i+1)for(j=0;j<16;j=j+1)begin A=i;B=j;#1;
    if({A_greater,A_equal,A_less}!={(i>j),(i==j),(i<j)})$fatal(1,"4-bit comparison is wrong");end
    $display("VERIGYM_PUBLIC_PASS");$finish;end
endmodule
