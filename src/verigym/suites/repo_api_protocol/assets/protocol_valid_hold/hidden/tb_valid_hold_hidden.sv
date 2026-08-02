// SPDX-License-Identifier: Apache-2.0
`timescale 1ns/1ps
module tb_valid_hold_hidden;
    logic clk = 1'b0;
    logic rst = 1'b0;
    logic load = 1'b0;
    logic hold = 1'b0;
    logic [7:0] data_in = 8'h00;
    logic [7:0] data_q;
    logic valid_q;
    integer cycle;
    logic [7:0] expected_data = 8'h00;
    logic expected_valid = 1'b0;
    valid_register dut (.*);
    always #5 clk = ~clk;
    initial begin
        for (cycle = 0; cycle < 40; cycle = cycle + 1) begin
            @(negedge clk);
            rst = (cycle == 0 || cycle == 21);
            hold = ((cycle % 5) == 2);
            load = ((cycle % 3) != 0);
            data_in = cycle[7:0] ^ 8'h5a;
            @(posedge clk);
            if (rst) begin expected_data = 8'h00; expected_valid = 1'b0; end
            else if (!hold && load) begin expected_data = data_in; expected_valid = 1'b1; end
            #1;
            if (data_q !== expected_data || valid_q !== expected_valid) begin
                $display("VERIGYM_FAIL cycle=%0d", cycle); $finish;
            end
        end
        $display("VERIGYM_PASS"); $finish;
    end
endmodule
