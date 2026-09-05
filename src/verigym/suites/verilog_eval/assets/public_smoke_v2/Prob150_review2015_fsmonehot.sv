module public_smoke;
  reg d;
  reg done_counting;
  reg ack;
  reg [9:0] state;
  wire B3_next, S_next, S1_next, Count_next, Wait_next;
  wire done, counting, shift_ena;
  reg exp_B3_next, exp_S_next, exp_S1_next, exp_Count_next, exp_Wait_next;
  reg exp_done, exp_counting, exp_shift_ena;
  integer state_index;
  integer input_index;
  TopModule dut(.*);

  task check_outputs;
    begin
      exp_B3_next = state[6];
      exp_S_next = (state[0] & ~d) | (state[1] & ~d) |
                   (state[3] & ~d) | (state[9] & ack);
      exp_S1_next = state[0] & d;
      exp_Count_next = state[7] | (state[8] & ~done_counting);
      exp_Wait_next = (state[8] & done_counting) | (state[9] & ~ack);
      exp_done = state[9];
      exp_counting = state[8];
      exp_shift_ena = state[4] | state[5] | state[6] | state[7];
      #1;
      if ({B3_next, S_next, S1_next, Count_next, Wait_next,
           done, counting, shift_ena} !==
          {exp_B3_next, exp_S_next, exp_S1_next, exp_Count_next, exp_Wait_next,
           exp_done, exp_counting, exp_shift_ena}) begin
        $fatal(1, "functional mismatch state=%b inputs=%b%b%b", state,
               d, done_counting, ack);
      end
    end
  endtask

  initial begin
    for (state_index = 0; state_index < 10; state_index = state_index + 1) begin
      state = 10'b1 << state_index;
      for (input_index = 0; input_index < 8; input_index = input_index + 1) begin
        {d, done_counting, ack} = input_index[2:0];
        check_outputs();
      end
    end
    $display("PUBLIC_SMOKE_PASS");
    $finish;
  end
endmodule
