`timescale 1ns/1ps

module tb_smoke;
    reg a;
    reg b;
    wire y;

    and_gate dut (.a(a), .b(b), .y(y));

    initial begin
        a = 1'b0; b = 1'b0; #1;
        if (y !== 1'b0) begin $display("VERIGYM_FAIL"); $finish; end
        a = 1'b1; b = 1'b1; #1;
        if (y !== 1'b1) begin $display("VERIGYM_FAIL"); $finish; end
        $display("VERIGYM_PASS");
        $finish;
    end
endmodule
