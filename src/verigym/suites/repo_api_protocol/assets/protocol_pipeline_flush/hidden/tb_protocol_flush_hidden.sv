// SPDX-License-Identifier: Apache-2.0
`timescale 1ns/1ps
module tb_protocol_flush_hidden;
    logic clk = 1'b0, rst = 1'b0, flush = 1'b0, in_valid = 1'b0, out_ready = 1'b0;
    logic in_ready, out_valid;
    logic [7:0] in_data = 8'h00, out_data;
    integer cycle;
    logic expected_valid = 1'b0;
    logic [7:0] expected_data = 8'h00;
    flush_pipeline_top dut (.*);
    always #5 clk = ~clk;
    initial begin
        for (cycle = 0; cycle < 45; cycle = cycle + 1) begin
            @(negedge clk);
            rst = (cycle == 0 || cycle == 31);
            flush = (cycle == 9 || cycle == 22 || cycle == 36);
            in_valid = ((cycle % 3) != 0);
            out_ready = ((cycle % 4) == 0);
            in_data = cycle[7:0] + 8'h40;
            @(posedge clk);
            if (rst || flush) begin expected_valid = 1'b0; expected_data = 8'h00; end
            else if (!expected_valid || out_ready) begin
                expected_valid = in_valid;
                if (in_valid) expected_data = in_data;
            end
            #1;
            if (out_valid !== expected_valid || (out_valid && out_data !== expected_data)) begin
                $display("VERIGYM_FAIL cycle=%0d", cycle); $finish;
            end
        end
        $display("VERIGYM_PASS"); $finish;
    end
endmodule
