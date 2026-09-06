module public_smoke;
  reg clk = 0;
  reg reset = 0;
  reg [7:0] in = 0;
  wire done;
  TopModule dut(.clk(clk), .reset(reset), .in(in), .done(done));

  task tick;
    begin #4 clk = 1; #1; #4 clk = 0; #1; end
  endtask

  initial begin
    reset = 1; tick(); reset = 0;
    in = 8'h00; tick();
    if (done !== 1'b0) $fatal(1, "discard failed");
    in = 8'h08; tick(); in = 8'h55; tick(); in = 8'haa; tick();
    if (done !== 1'b1) $fatal(1, "message completion failed");
    in = 8'h00; tick();
    if (done !== 1'b0) $fatal(1, "done pulse failed");
    $display("PUBLIC_SMOKE_PASS");
    $finish;
  end
endmodule
