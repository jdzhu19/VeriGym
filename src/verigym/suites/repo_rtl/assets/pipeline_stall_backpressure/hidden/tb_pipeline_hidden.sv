// SPDX-License-Identifier: Apache-2.0
`timescale 1ns/1ps
module tb_pipeline_hidden;
    logic clk = 1'b0;
    logic rst = 1'b0;
    logic in_valid = 1'b0;
    logic in_ready;
    logic [7:0] in_data = 8'h00;
    logic out_valid;
    logic out_ready = 1'b0;
    logic [7:0] out_data;
    logic [7:0] expected [0:127];
    integer head = 0;
    integer tail = 0;
    integer cycle;
    logic accepted;
    logic emitted;
    logic [7:0] accepted_data;
    logic [7:0] emitted_data;

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
        for (cycle = 0; cycle < 80; cycle = cycle + 1) begin
            in_valid = ((cycle % 5) != 3);
            in_data = cycle[7:0] ^ 8'h5a;
            out_ready = ((cycle % 7) != 2) && ((cycle % 7) != 3);
            #1;
            accepted = in_valid && in_ready;
            emitted = out_valid && out_ready;
            accepted_data = in_data;
            emitted_data = out_data;
            @(posedge clk);
            #1;
            if (emitted) begin
                if (head >= tail || emitted_data !== expected[head]) begin
                    $display("VERIGYM_FAIL ordering cycle=%0d", cycle);
                    $finish;
                end
                head = head + 1;
            end
            if (accepted) begin
                expected[tail] = accepted_data;
                tail = tail + 1;
            end
            @(negedge clk);
        end
        in_valid = 1'b0;
        out_ready = 1'b1;
        while (head < tail) begin
            #1;
            emitted = out_valid && out_ready;
            emitted_data = out_data;
            @(posedge clk);
            #1;
            if (emitted) begin
                if (emitted_data !== expected[head]) begin
                    $display("VERIGYM_FAIL drain ordering");
                    $finish;
                end
                head = head + 1;
            end
            @(negedge clk);
        end
        if (tail < 20) begin
            $display("VERIGYM_FAIL insufficient throughput=%0d", tail);
            $finish;
        end
        $display("VERIGYM_PASS");
        $finish;
    end
endmodule
