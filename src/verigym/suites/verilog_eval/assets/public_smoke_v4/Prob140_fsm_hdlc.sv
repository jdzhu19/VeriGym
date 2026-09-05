module public_smoke;
  reg clk = 0;
  reg reset = 0;
  reg in = 0;
  wire disc, flag, err;
  integer i;
  TopModule dut(.clk(clk), .reset(reset), .in(in), .disc(disc), .flag(flag), .err(err));

  task tick;
    begin #4 clk = 1; #1; #4 clk = 0; #1; end
  endtask

  task expect_outputs(input exp_disc, input exp_flag, input exp_err);
    begin
      if ({disc, flag, err} !== {exp_disc, exp_flag, exp_err})
        $fatal(1, "HDLC output mismatch got=%b%b%b expected=%b%b%b",
               disc, flag, err, exp_disc, exp_flag, exp_err);
    end
  endtask

  initial begin
    reset = 1; tick(); reset = 0;
    expect_outputs(0, 0, 0);

    for (i = 0; i < 5; i = i + 1) begin
      in = 1; tick(); expect_outputs(0, 0, 0);
    end
    in = 0; tick(); expect_outputs(1, 0, 0);
    in = 0; tick(); expect_outputs(0, 0, 0);

    for (i = 0; i < 6; i = i + 1) begin
      in = 1; tick(); expect_outputs(0, 0, 0);
    end
    in = 0; tick(); expect_outputs(0, 1, 0);
    in = 0; tick(); expect_outputs(0, 0, 0);

    for (i = 0; i < 6; i = i + 1) begin
      in = 1; tick(); expect_outputs(0, 0, 0);
    end
    in = 1; tick(); expect_outputs(0, 0, 1);
    in = 1; tick(); expect_outputs(0, 0, 1);
    in = 0; tick(); expect_outputs(0, 0, 0);

    $display("PUBLIC_SMOKE_PASS");
    $finish;
  end
endmodule
