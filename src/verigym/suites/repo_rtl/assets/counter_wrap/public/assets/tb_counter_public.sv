// SPDX-License-Identifier: Apache-2.0
`timescale 1ns/1ps
module tb_counter_public;
    logic clk = 1'b0;
    logic rst = 1'b0;
    logic enable = 1'b0;
    logic [3:0] count;
    integer index;

    wrap_counter dut (.clk(clk), .rst(rst), .enable(enable), .count(count));
    always #5 clk = ~clk;

    task automatic tick;
        begin
            @(posedge clk);
            #1;
        end
    endtask

    initial begin
        rst = 1'b1;
        tick();
        if (count !== 4'h0) begin
            $display("VERIGYM_FAIL reset");
            $fatal(1);
        end
        rst = 1'b0;
        enable = 1'b1;
        for (index = 0; index < 16; index = index + 1) begin
            tick();
        end
        if (count !== 4'h0) begin
            $display("VERIGYM_FAIL wrap count=%h", count);
            $fatal(1);
        end
        enable = 1'b0;
        tick();
        if (count !== 4'h0) begin
            $display("VERIGYM_FAIL hold");
            $fatal(1);
        end
        $display("VERIGYM_PASS");
        $finish;
    end
endmodule
