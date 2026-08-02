// SPDX-License-Identifier: Apache-2.0
`timescale 1ns/1ps
module tb_protocol_flush_public;
    logic clk = 1'b0, rst = 1'b0, flush = 1'b0, in_valid = 1'b0, out_ready = 1'b0;
    logic in_ready, out_valid;
    logic [7:0] in_data = 8'h00, out_data;
    flush_pipeline_top dut (.*);
    always #5 clk = ~clk;
    task automatic tick; begin @(posedge clk); #1; end endtask
    initial begin
        rst = 1'b1; tick(); rst = 1'b0;
        in_valid = 1'b1; in_data = 8'h6d; tick(); in_valid = 1'b0;
        if (!out_valid) begin $display("VERIGYM_FAIL load"); $fatal(1); end
        flush = 1'b1; tick(); flush = 1'b0;
        if (out_valid) begin $display("VERIGYM_FAIL flush"); $fatal(1); end
        $display("VERIGYM_PASS"); $finish;
    end
endmodule
