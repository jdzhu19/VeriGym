module public_smoke;
  reg [3:0] A,B;reg Cin;wire [3:0] Sum;wire Cout;integer value;reg[4:0]expected;
  adder_bcd dut(.A(A),.B(B),.Cin(Cin),.Sum(Sum),.Cout(Cout));
  task automatic check(input [3:0] av,bv,input cv);begin A=av;B=bv;Cin=cv;#1;value=av+bv+cv;expected=(value>=10)?value+6:value;
    if({Cout,Sum}!==expected) $fatal(1,"BCD correction or carry is wrong");end endtask
  initial begin check(0,0,0);check(4,5,0);check(9,0,1);check(7,8,0);check(9,9,1);$display("VERIGYM_PUBLIC_PASS");$finish;end
endmodule
