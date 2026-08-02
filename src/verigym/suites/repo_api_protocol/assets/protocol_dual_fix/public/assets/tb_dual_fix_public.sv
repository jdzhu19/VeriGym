// SPDX-License-Identifier: Apache-2.0
`timescale 1ns/1ps
module tb_dual_fix_public;
    logic clk = 1'b0;
    logic reset_n = 1'b1;
    logic enable = 1'b0;
    logic [7:0] increment = 8'h00;
    logic [7:0] total;
    accumulator_top dut (.*);
    always #5 clk = ~clk;
    task automatic tick; begin @(posedge clk); #1; end endtask
    initial begin
        reset_n = 1'b0; tick(); reset_n = 1'b1;
        if (total !== 8'h00) begin $display("VERIGYM_FAIL reset"); $fatal(1); end
        enable = 1'b1; increment = 8'hf0; tick(); increment = 8'h30; tick();
        if (total !== 8'h20) begin $display("VERIGYM_FAIL wrap"); $fatal(1); end
        $display("VERIGYM_PASS"); $finish;
    end
endmodule
