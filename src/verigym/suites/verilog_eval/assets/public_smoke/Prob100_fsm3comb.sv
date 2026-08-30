module public_smoke;
  reg in;
  reg [1:0] state;
  wire [1:0] next_state;
  wire out;
  TopModule dut(.in(in), .state(state), .next_state(next_state), .out(out));

  task check(input [1:0] s, input bit i, input [1:0] n, input bit o);
    begin
      state = s; in = i; #1;
      if (next_state !== n || out !== o) $fatal(1, "transition mismatch");
    end
  endtask

  initial begin
    check(2'b00, 0, 2'b00, 0); check(2'b00, 1, 2'b01, 0);
    check(2'b01, 0, 2'b10, 0); check(2'b01, 1, 2'b01, 0);
    check(2'b10, 0, 2'b00, 0); check(2'b10, 1, 2'b11, 0);
    check(2'b11, 0, 2'b10, 1); check(2'b11, 1, 2'b01, 1);
    $display("PUBLIC_SMOKE_PASS");
    $finish;
  end
endmodule
