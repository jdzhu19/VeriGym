module public_smoke;
  reg d;
  reg done_counting;
  reg ack;
  reg [9:0] state;
  wire B3_next, S_next, S1_next, Count_next, Wait_next;
  wire done, counting, shift_ena;
  TopModule dut(.*);

  task clear_inputs;
    begin d = 0; done_counting = 0; ack = 0; end
  endtask

  initial begin
    clear_inputs(); state = 10'b0000000001; d = 1; #1;
    if (S1_next !== 1 || S_next !== 0) $fatal(1, "S transition failed");
    clear_inputs(); state = 10'b0001000000; #1;
    if (B3_next !== 1 || shift_ena !== 1) $fatal(1, "B2 transition failed");
    clear_inputs(); state = 10'b0100000000; done_counting = 1; #1;
    if (Wait_next !== 1 || counting !== 1) $fatal(1, "Count transition failed");
    clear_inputs(); state = 10'b1000000000; ack = 1; #1;
    if (S_next !== 1 || done !== 1) $fatal(1, "Wait transition failed");
    $display("PUBLIC_SMOKE_PASS");
    $finish;
  end
endmodule
