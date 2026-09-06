module public_smoke;
  reg clk = 0;
  reg reset = 0;
  reg data = 0;
  wire start_shifting;
  TopModule dut(.clk(clk), .reset(reset), .data(data), .start_shifting(start_shifting));

  task tick;
    begin #4 clk = 1; #1; #4 clk = 0; #1; end
  endtask

  task send(input bit value);
    begin data = value; tick(); end
  endtask

  initial begin
    reset = 1; tick(); reset = 0;
    send(1); send(1); send(0); send(1);
    if (start_shifting !== 1'b1) $fatal(1, "sequence was not detected");
    send(0); send(0);
    if (start_shifting !== 1'b1) $fatal(1, "latched output was not retained");
    reset = 1; tick();
    if (start_shifting !== 1'b0) $fatal(1, "reset failed");
    $display("PUBLIC_SMOKE_PASS");
    $finish;
  end
endmodule
