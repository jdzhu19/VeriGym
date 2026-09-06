module public_smoke;
  reg clk = 0;
  reg rst_n = 1;
  reg valid_count = 0;
  wire [3:0] out;
  counter_12 dut(.*);

  task tick;
    begin #4 clk = 1; #1; #4 clk = 0; #1; end
  endtask

  initial begin
    rst_n = 0; tick(); rst_n = 1;
    if (out !== 4'd0) $fatal(1, "reset failed");
    repeat (2) tick();
    if (out !== 4'd0) $fatal(1, "enable hold failed");
    valid_count = 1;
    repeat (11) tick();
    if (out !== 4'd11) $fatal(1, "count failed");
    tick();
    if (out !== 4'd0) $fatal(1, "wrap failed");
    $display("PUBLIC_SMOKE_PASS");
    $finish;
  end
endmodule
