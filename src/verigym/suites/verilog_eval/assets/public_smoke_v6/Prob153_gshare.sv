module public_smoke;
  reg clk = 0;
  reg areset = 0;
  reg predict_valid = 0;
  reg [6:0] predict_pc = 0;
  wire predict_taken;
  wire [6:0] predict_history;
  reg train_valid = 0;
  reg train_taken = 0;
  reg train_mispredicted = 0;
  reg [6:0] train_history = 0;
  reg [6:0] train_pc = 0;
  integer i;
  TopModule dut(.*);

  task tick;
    begin #4 clk = 1; #1; #4 clk = 0; #1; end
  endtask

  initial begin
    predict_valid = 1;
    predict_pc = 7'h33;
    areset = 1; #1;
    if (predict_history !== 7'b0) $fatal(1, "asynchronous history reset failed");
    tick(); areset = 0;

    predict_valid = 0;
    train_valid = 1;
    train_taken = 1;
    train_mispredicted = 0;
    train_history = 0;
    train_pc = 7'h33;
    tick();
    train_valid = 0;
    predict_valid = 1;
    predict_pc = 7'h33;
    #1;
    if (predict_history !== 0 || predict_taken !== 1)
      $fatal(1, "PHT reset was not weakly not-taken");

    areset = 1; #1;
    tick(); areset = 0;
    predict_pc = 0;

    train_valid = 1;
    train_taken = 1;
    train_mispredicted = 0;
    train_history = 0;
    train_pc = 7'h12;
    for (i = 0; i < 3; i = i + 1) tick();
    train_valid = 0;

    predict_pc = 7'h12;
    #1;
    if (predict_history !== 0 || predict_taken !== 1)
      $fatal(1, "taken training or prediction history failed");

    train_valid = 1;
    train_taken = 0;
    train_history = 0;
    train_pc = 7'h12;
    #1;
    if (predict_taken !== 1) $fatal(1, "prediction did not observe pre-training PHT");
    tick();
    predict_valid = 0;
    repeat (2) tick();
    train_valid = 0;

    predict_valid = 1;
    predict_pc = 7'h13;
    #1;
    if (predict_history !== 7'b1 || predict_taken !== 0)
      $fatal(1, "not-taken saturation failed");

    train_valid = 1;
    train_taken = 1;
    train_mispredicted = 1;
    train_history = 7'b0101010;
    train_pc = 7'h55;
    tick();
    if (predict_history !== 7'b1010101)
      $fatal(1, "misprediction recovery did not override younger prediction");

    areset = 1; #1;
    if (predict_history !== 0) $fatal(1, "second asynchronous reset failed");
    $display("PUBLIC_SMOKE_PASS");
    $finish;
  end
endmodule
