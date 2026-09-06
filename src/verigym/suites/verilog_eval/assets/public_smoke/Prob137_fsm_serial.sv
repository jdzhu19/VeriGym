module public_smoke;
  reg clk = 0;
  reg reset = 0;
  reg in = 1;
  wire done;
  integer i;
  TopModule dut(.clk(clk), .reset(reset), .in(in), .done(done));

  task tick;
    begin #4 clk = 1; #1; #4 clk = 0; #1; end
  endtask

  initial begin
    reset = 1; tick(); reset = 0;
    in = 0; tick();
    for (i = 0; i < 8; i = i + 1) begin in = i[0]; tick(); end
    in = 1; tick();
    if (done !== 1'b1) $fatal(1, "valid frame was not detected");
    tick();
    if (done !== 1'b0) $fatal(1, "done pulse failed");
    $display("PUBLIC_SMOKE_PASS");
    $finish;
  end
endmodule
