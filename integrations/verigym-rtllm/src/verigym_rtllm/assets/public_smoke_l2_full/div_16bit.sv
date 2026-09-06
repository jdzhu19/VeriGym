module public_smoke;
  reg[15:0]A;reg[7:0]B;wire[15:0]result,odd;
  div_16bit dut(.A(A),.B(B),.result(result),.odd(odd));
  task automatic check(input[15:0]av,input[7:0]bv);begin A=av;B=bv;#1;
    if(result!==av/bv||odd!==av%bv)$fatal(1,"divider quotient or remainder is wrong");end endtask
  initial begin check(16'd65535,8'd255);check(16'd12345,8'd37);check(16'd4097,8'd16);check(16'd7,8'd13);check(16'd49152,8'd127);$display("VERIGYM_PUBLIC_PASS");$finish;end
endmodule
