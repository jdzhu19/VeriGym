module public_smoke;
  reg clk = 0;
  reg areset = 0;
  reg bump_left = 0;
  reg bump_right = 0;
  reg ground = 1;
  reg dig = 0;
  wire walk_left, walk_right, aaah, digging;
  integer i;
  TopModule dut(.*);

  task tick;
    begin #4 clk = 1; #1; #4 clk = 0; #1; end
  endtask

  task expect_outputs(
    input expected_left,
    input expected_right,
    input expected_aaah,
    input expected_digging
  );
    begin
      if ({walk_left, walk_right, aaah, digging} !==
          {expected_left, expected_right, expected_aaah, expected_digging})
        $fatal(1, "lemming output mismatch left=%b right=%b aaah=%b digging=%b",
               walk_left, walk_right, aaah, digging);
    end
  endtask

  initial begin
    areset = 1; #1;
    expect_outputs(1, 0, 0, 0);
    tick(); areset = 0;

    bump_right = 1; tick(); bump_right = 0;
    expect_outputs(1, 0, 0, 0);
    bump_left = 1; tick(); bump_left = 0;
    expect_outputs(0, 1, 0, 0);
    bump_left = 1; tick(); bump_left = 0;
    expect_outputs(0, 1, 0, 0);
    bump_right = 1; tick(); bump_right = 0;
    expect_outputs(1, 0, 0, 0);
    bump_left = 1; tick(); bump_left = 0;
    expect_outputs(0, 1, 0, 0);

    ground = 0; bump_right = 1; dig = 1; tick();
    expect_outputs(0, 0, 1, 0);
    bump_right = 0; dig = 0;
    repeat (3) tick();
    ground = 1; bump_right = 1; tick(); bump_right = 0;
    expect_outputs(0, 1, 0, 0);

    dig = 1; bump_right = 1; tick(); dig = 0; bump_right = 0;
    expect_outputs(0, 0, 0, 1);
    ground = 0; bump_left = 1; tick(); bump_left = 0;
    expect_outputs(0, 0, 1, 0);
    repeat (2) tick();
    ground = 1; tick();
    expect_outputs(0, 1, 0, 0);

    ground = 0; tick();
    for (i = 1; i < 20; i = i + 1) tick();
    ground = 1; tick();
    expect_outputs(0, 1, 0, 0);

    ground = 0; tick();
    for (i = 1; i < 21; i = i + 1) tick();
    ground = 1; tick();
    expect_outputs(0, 0, 0, 0);
    bump_left = 1; bump_right = 1; dig = 1;
    repeat (2) tick();
    expect_outputs(0, 0, 0, 0);

    areset = 1; #1;
    expect_outputs(1, 0, 0, 0);
    bump_left = 0; bump_right = 0; dig = 0;
    tick(); areset = 0;
    bump_left = 1; bump_right = 1; tick();
    expect_outputs(0, 1, 0, 0);
    bump_left = 0; bump_right = 0;

    ground = 0; tick();
    repeat (39) tick();
    ground = 1; tick();
    expect_outputs(0, 0, 0, 0);

    $display("PUBLIC_SMOKE_PASS");
    $finish;
  end
endmodule
