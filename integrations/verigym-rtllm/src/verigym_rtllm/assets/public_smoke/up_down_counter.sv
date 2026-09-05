module public_smoke;
  reg clk = 0;
  reg reset = 0;
  reg up_down = 1;
  wire [15:0] count;
  up_down_counter dut(.*);

  task tick;
    begin #4 clk = 1; #1; #4 clk = 0; #1; end
  endtask

  initial begin
    reset = 1; tick(); reset = 0;
    if (count !== 16'd0) $fatal(1, "reset failed");
    repeat (3) tick();
    if (count !== 16'd3) $fatal(1, "increment failed");
    up_down = 0; repeat (2) tick();
    if (count !== 16'd1) $fatal(1, "decrement failed");
    tick(); tick();
    if (count !== 16'hffff) $fatal(1, "underflow wrap failed");
    $display("PUBLIC_SMOKE_PASS");
    $finish;
  end
endmodule
