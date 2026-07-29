// SPDX-License-Identifier: Apache-2.0
`timescale 1ns/1ps
module tb_pipeline_public;
    logic clk = 1'b0;
    logic rst = 1'b0;
    logic in_valid = 1'b0;
    logic in_ready;
    logic [7:0] in_data = 8'h00;
    logic out_valid;
    logic out_ready = 1'b0;
    logic [7:0] out_data;

    pipeline_top dut (
        .clk(clk), .rst(rst),
        .in_valid(in_valid), .in_ready(in_ready), .in_data(in_data),
        .out_valid(out_valid), .out_ready(out_ready), .out_data(out_data)
    );
    always #5 clk = ~clk;

    initial begin
        rst = 1'b1;
        repeat (2) @(posedge clk);
        @(negedge clk);
        rst = 1'b0;
        out_ready = 1'b0;
        in_valid = 1'b1;
        in_data = 8'h11;
        @(posedge clk);
        @(negedge clk);
        if (!in_ready) begin
            $display("VERIGYM_FAIL second slot not ready");
            $fatal(1);
        end
        in_data = 8'h22;
        @(posedge clk);
        @(negedge clk);
        in_valid = 1'b0;
        if (!out_valid || out_data !== 8'h11) begin
            $display("VERIGYM_FAIL blocked first item");
            $fatal(1);
        end
        out_ready = 1'b1;
        @(posedge clk);
        @(negedge clk);
        if (!out_valid || out_data !== 8'h22) begin
            $display("VERIGYM_FAIL ordered second item");
            $fatal(1);
        end
        @(posedge clk);
        @(negedge clk);
        if (out_valid) begin
            $display("VERIGYM_FAIL pipeline did not drain");
            $fatal(1);
        end
        $display("VERIGYM_PASS");
        $finish;
    end
endmodule
