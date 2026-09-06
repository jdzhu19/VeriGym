module public_smoke;
  reg [15:0] a,b; reg Cin; wire [15:0] y; wire Co; reg [16:0] expected;
  adder_16bit dut(.a(a),.b(b),.Cin(Cin),.y(y),.Co(Co));
  task automatic check(input [15:0] av,bv,input cv); begin a=av;b=bv;Cin=cv;#1;expected=av+bv+cv;
    if({Co,y}!==expected) $fatal(1,"16-bit sum or carry is wrong"); end endtask
  initial begin check(0,0,0);check(16'h00ff,16'h0001,0);check(16'hffff,0,1);check(16'h8ace,16'h7532,0);check(16'hbeef,16'h1234,1);$display("VERIGYM_PUBLIC_PASS");$finish;end
endmodule
