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

  task send_valid_frame;
    begin
      in = 0; tick();
      for (i = 0; i < 8; i = i + 1) begin
        in = (8'hA5 >> i) & 1'b1;
        tick();
      end
      in = 1; tick();
      if (done !== 1'b1) $fatal(1, "valid frame was not detected");
      tick();
      if (done !== 1'b0) $fatal(1, "done pulse failed");
    end
  endtask

  initial begin
    reset = 1; tick(); reset = 0;
    send_valid_frame();

    // An invalid stop bit must discard the frame. Finding a later 1 only
    // resynchronizes the receiver; it must never turn the bad frame into done.
    in = 0; tick();
    for (i = 0; i < 8; i = i + 1) begin
      in = (8'h3C >> i) & 1'b1;
      tick();
    end
    in = 0; tick();
    if (done !== 1'b0) $fatal(1, "invalid stop accepted");
    in = 1; #1;
    if (done !== 1'b0) $fatal(1, "resynchronization asserted done");
    tick();
    if (done !== 1'b0) $fatal(1, "bad frame produced a done pulse");

    send_valid_frame();
    $display("PUBLIC_SMOKE_PASS");
    $finish;
  end
endmodule
