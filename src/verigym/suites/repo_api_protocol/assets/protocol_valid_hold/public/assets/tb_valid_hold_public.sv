// SPDX-License-Identifier: Apache-2.0
`timescale 1ns/1ps
module tb_valid_hold_public;
    logic clk = 1'b0;
    logic rst = 1'b0;
    logic load = 1'b0;
    logic hold = 1'b0;
    logic [7:0] data_in = 8'h00;
    logic [7:0] data_q;
    logic valid_q;
    valid_register dut (.*);
    always #5 clk = ~clk;
    task automatic tick; begin @(posedge clk); #1; end endtask
    initial begin
        rst = 1'b1; tick(); rst = 1'b0;
        load = 1'b1; data_in = 8'h3c; tick();
        hold = 1'b1; data_in = 8'ha5; tick();
        if (data_q !== 8'h3c || valid_q !== 1'b1) begin
            $display("VERIGYM_FAIL simultaneous hold/load"); $fatal(1);
        end
        $display("VERIGYM_PASS"); $finish;
    end
endmodule
