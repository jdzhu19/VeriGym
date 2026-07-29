// SPDX-License-Identifier: Apache-2.0
`timescale 1ns/1ps
module tb_counter_hidden;
    logic clk = 1'b0;
    logic rst = 1'b0;
    logic enable = 1'b0;
    logic [3:0] count;
    logic [3:0] expected = 4'h0;
    integer cycle;

    wrap_counter dut (.clk(clk), .rst(rst), .enable(enable), .count(count));
    always #5 clk = ~clk;

    initial begin
        for (cycle = 0; cycle < 64; cycle = cycle + 1) begin
            @(negedge clk);
            rst = (cycle == 0 || cycle == 23 || cycle == 47);
            enable = ((cycle % 4) != 1);
            @(posedge clk);
            if (rst) begin
                expected = 4'h0;
            end else if (enable) begin
                expected = expected + 4'h1;
            end
            #1;
            if (count !== expected) begin
                $display(
                    "VERIGYM_FAIL cycle=%0d got=%h expected=%h",
                    cycle, count, expected
                );
                $finish;
            end
        end
        $display("VERIGYM_PASS");
        $finish;
    end
endmodule
