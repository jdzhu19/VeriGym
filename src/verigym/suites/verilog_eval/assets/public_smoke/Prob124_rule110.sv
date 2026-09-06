module public_smoke;
  reg clk = 0;
  reg load = 0;
  reg [511:0] data = 0;
  wire [511:0] q;
  reg [511:0] expected;
  TopModule dut(.clk(clk), .load(load), .data(data), .q(q));

  task tick;
    begin #4 clk = 1; #1; #4 clk = 0; #1; end
  endtask

  function automatic [511:0] rule110(input [511:0] current);
    integer i;
    reg left_bit;
    reg center_bit;
    reg right_bit;
    begin
      for (i = 0; i < 512; i = i + 1) begin
        left_bit = (i == 511) ? 1'b0 : current[i+1];
        center_bit = current[i];
        right_bit = (i == 0) ? 1'b0 : current[i-1];
        case ({left_bit, center_bit, right_bit})
          3'b110, 3'b101, 3'b011, 3'b010, 3'b001: rule110[i] = 1'b1;
          default: rule110[i] = 1'b0;
        endcase
      end
    end
  endfunction

  initial begin
    data = 512'd0; data[0] = 1'b1; data[5:3] = 3'b110;
    load = 1; tick();
    if (q !== data) $fatal(1, "load failed");
    expected = rule110(data); load = 0; tick();
    if (q !== expected) $fatal(1, "rule update failed");
    $display("PUBLIC_SMOKE_PASS");
    $finish;
  end
endmodule
