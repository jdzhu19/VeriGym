module public_smoke;
  reg clk = 0;
  reg load = 0;
  reg [255:0] data = 0;
  wire [255:0] q;
  reg [255:0] expected;
  TopModule dut(.clk(clk), .load(load), .data(data), .q(q));

  task tick;
    begin #4 clk = 1; #1; #4 clk = 0; #1; end
  endtask

  task load_grid;
    begin
      load = 1; tick(); load = 0;
      if (q !== data) $fatal(1, "load did not replace the grid");
    end
  endtask

  task step_and_expect;
    begin
      tick();
      if (q !== expected) $fatal(1, "ConwayLife step mismatch");
    end
  endtask

  initial begin
    data = 0; data[5*16+5] = 1;
    load_grid();
    expected = 0;
    step_and_expect();

    data = 0;
    data[5*16+5] = 1; data[5*16+6] = 1;
    data[6*16+5] = 1; data[6*16+6] = 1;
    load_grid();
    expected = data;
    step_and_expect();

    data = 0;
    data[8*16+7] = 1; data[8*16+8] = 1; data[8*16+9] = 1;
    load_grid();
    expected = 0;
    expected[7*16+8] = 1; expected[8*16+8] = 1; expected[9*16+8] = 1;
    step_and_expect();
    expected = 0;
    expected[8*16+7] = 1; expected[8*16+8] = 1; expected[8*16+9] = 1;
    step_and_expect();

    data = 0;
    data[0*16+15] = 1; data[0*16+0] = 1; data[0*16+1] = 1;
    load_grid();
    expected = 0;
    expected[15*16+0] = 1; expected[0*16+0] = 1; expected[1*16+0] = 1;
    step_and_expect();

    $display("PUBLIC_SMOKE_PASS");
    $finish;
  end
endmodule
