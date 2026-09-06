module public_smoke;
  reg clk = 0;
  reg reset = 0;
  reg slowena = 0;
  wire [3:0] q;
  TopModule dut(.clk(clk), .reset(reset), .slowena(slowena), .q(q));

  task tick;
    begin #4 clk = 1; #1; #4 clk = 0; #1; end
  endtask

  initial begin
    reset = 1; tick(); reset = 0;
    repeat (2) tick();
    if (q !== 4'd0) $fatal(1, "pause failed");
    slowena = 1;
    repeat (9) tick();
    if (q !== 4'd9) $fatal(1, "count failed");
    tick();
    if (q !== 4'd0) $fatal(1, "decade wrap failed");
    $display("PUBLIC_SMOKE_PASS");
    $finish;
  end
endmodule
