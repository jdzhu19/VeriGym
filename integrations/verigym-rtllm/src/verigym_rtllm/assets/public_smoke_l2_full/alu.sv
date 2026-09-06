module public_smoke;
  reg[31:0]a,b;reg[5:0]aluc;wire[31:0]r;wire zero,carry,negative,overflow,flag;
  alu dut(.a(a),.b(b),.aluc(aluc),.r(r),.zero(zero),.carry(carry),.negative(negative),.overflow(overflow),.flag(flag));
  task automatic check(input[5:0]op,input[31:0]av,bv,expected,input expected_zero);begin aluc=op;a=av;b=bv;#1;if(r!==expected||zero!==expected_zero)$fatal(1,"ALU result or zero flag is wrong");end endtask
  initial begin check(6'b100000,32'h7fffffff,1,32'h80000000,0);check(6'b100010,3,9,32'hfffffffa,0);check(6'b100100,32'ha5a55a5a,32'h0ff00ff0,32'h05a00a50,0);check(6'b100111,32'h0000ffff,32'h00ff0000,32'hff000000,0);
    check(6'b000100,4,32'h12345678,32'h23456780,0);check(6'b000111,4,32'hf0000000,32'hff000000,0);check(6'b001111,32'h1234abcd,0,32'habcd0000,0);
    aluc=6'b101010;a=32'hffffffff;b=1;#1;if(r!==1||flag!==1)$fatal(1,"signed SLT is wrong");aluc=6'b101011;#1;if(r!==0||flag!==0)$fatal(1,"unsigned SLT is wrong");check(6'b100110,32'hdeadbeef,32'hdeadbeef,0,1);
    $display("VERIGYM_PUBLIC_PASS");$finish;end
endmodule
