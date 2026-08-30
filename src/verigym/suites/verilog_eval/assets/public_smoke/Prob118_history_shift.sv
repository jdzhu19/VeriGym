module public_smoke;
  reg clk = 0;
  reg areset = 0;
  reg predict_valid = 0;
  reg predict_taken = 0;
  reg train_mispredicted = 0;
  reg train_taken = 0;
  reg [31:0] train_history = 0;
  wire [31:0] predict_history;
  TopModule dut(.*);

  task tick;
    begin #4 clk = 1; #1; #4 clk = 0; #1; end
  endtask

  initial begin
    #1 areset = 1; #1; areset = 0;
    if (predict_history !== 32'd0) $fatal(1, "async reset failed");
    predict_valid = 1; predict_taken = 1; tick();
    if (predict_history !== 32'd1) $fatal(1, "prediction shift failed");
    predict_taken = 0; tick();
    if (predict_history !== 32'd2) $fatal(1, "history ordering failed");
    train_mispredicted = 1; train_history = 32'h00000005; train_taken = 1;
    predict_taken = 1; tick();
    if (predict_history !== 32'h0000000b) $fatal(1, "rollback precedence failed");
    $display("PUBLIC_SMOKE_PASS");
    $finish;
  end
endmodule
