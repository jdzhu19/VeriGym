module public_smoke;
  reg clk = 0;
  reg reset = 0;
  reg in = 0;
  wire out;
  TopModule dut(.clk(clk), .reset(reset), .in(in), .out(out));

  task tick;
    begin #4 clk = 1; #1; #4 clk = 0; #1; end
  endtask

  initial begin
    reset = 1; tick(); reset = 0;
    if (out !== 1'b1) $fatal(1, "reset state failed");
    in = 0; tick();
    if (out !== 1'b0) $fatal(1, "B to A failed");
    in = 1; tick();
    if (out !== 1'b0) $fatal(1, "A hold failed");
    in = 0; tick();
    if (out !== 1'b1) $fatal(1, "A to B failed");
    $display("PUBLIC_SMOKE_PASS");
    $finish;
  end
endmodule
