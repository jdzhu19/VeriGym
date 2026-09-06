module public_smoke;
  reg clk = 0;
  reg reset = 0;
  wire [3:0] q;
  TopModule dut(.clk(clk), .reset(reset), .q(q));

  task tick;
    begin #4 clk = 1; #1; #4 clk = 0; #1; end
  endtask

  initial begin
    reset = 1; tick();
    if (q !== 4'd0) $fatal(1, "reset failed");
    reset = 0;
    repeat (15) tick();
    if (q !== 4'd15) $fatal(1, "count failed");
    tick();
    if (q !== 4'd0) $fatal(1, "wrap failed");
    $display("PUBLIC_SMOKE_PASS");
    $finish;
  end
endmodule
