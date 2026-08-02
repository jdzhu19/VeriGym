// SPDX-License-Identifier: Apache-2.0
`timescale 1ns/1ps
module tb_dual_fix_hidden;
    logic clk = 1'b0;
    logic reset_n = 1'b1;
    logic enable = 1'b0;
    logic [7:0] increment = 8'h00;
    logic [7:0] total;
    logic [7:0] expected = 8'h00;
    integer cycle;
    accumulator_top dut (.*);
    always #5 clk = ~clk;
    initial begin
        for (cycle = 0; cycle < 50; cycle = cycle + 1) begin
            @(negedge clk);
            reset_n = !(cycle == 0 || cycle == 27);
            enable = ((cycle % 4) != 1);
            increment = (cycle * 8'd29) + 8'd7;
            @(posedge clk);
            if (!reset_n) expected = 8'h00;
            else if (enable) expected = expected + increment;
            #1;
            if (total !== expected) begin
                $display("VERIGYM_FAIL cycle=%0d", cycle); $finish;
            end
        end
        $display("VERIGYM_PASS"); $finish;
    end
endmodule
