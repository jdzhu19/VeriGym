module public_smoke;
  reg[7:0]in;reg[2:0]ctrl;wire[7:0]out;integer i,j;
  barrel_shifter dut(.in(in),.ctrl(ctrl),.out(out));
  initial begin for(i=0;i<8;i=i+1)for(j=0;j<8;j=j+1)begin in=(8'h81^(i*8'h13));ctrl=j;#1;if(out!==(in>>j))$fatal(1,"barrel shift amount or fill is wrong");end
    $display("VERIGYM_PUBLIC_PASS");$finish;end
endmodule
