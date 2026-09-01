module public_smoke;
  reg [7:0] a,b; reg cin; wire [7:0] sum; wire cout; reg [8:0] expected;
  adder_8bit dut(.a(a),.b(b),.cin(cin),.sum(sum),.cout(cout));
  task automatic check(input [7:0] av,bv,input cv); begin a=av;b=bv;cin=cv;#1;expected=av+bv+cv;
    if({cout,sum}!==expected) $fatal(1,"8-bit sum or carry is wrong");end endtask
  initial begin check(0,0,0);check(8'h0f,1,0);check(8'hff,0,1);check(8'ha5,8'h5a,1);check(8'h81,8'h82,0);$display("VERIGYM_PUBLIC_PASS");$finish;end
endmodule
