module public_smoke;
  reg[2:0]A,B;wire A_greater,A_equal,A_less;integer i,j;
  comparator_3bit dut(.A(A),.B(B),.A_greater(A_greater),.A_equal(A_equal),.A_less(A_less));
  initial begin for(i=0;i<8;i=i+1)for(j=0;j<8;j=j+1)begin A=i;B=j;#1;
    if({A_greater,A_equal,A_less}!={(i>j),(i==j),(i<j)})$fatal(1,"3-bit comparison is wrong");end
    $display("VERIGYM_PUBLIC_PASS");$finish;end
endmodule
