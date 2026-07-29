// SPDX-License-Identifier: Apache-2.0
`timescale 1ns/1ps
module tb_arbiter_public;
    logic clk = 1'b0;
    logic rst = 1'b0;
    logic [1:0] request = 2'b00;
    logic [1:0] grant;

    rr_arbiter dut (.clk(clk), .rst(rst), .request(request), .grant(grant));
    always #5 clk = ~clk;

    initial begin
        rst = 1'b1;
        request = 2'b11;
        #1;
        if (grant !== 2'b00) begin
            $display("VERIGYM_FAIL grant during reset");
            $fatal(1);
        end
        @(posedge clk);
        @(negedge clk);
        rst = 1'b0;
        request = 2'b11;
        #1;
        if (grant !== 2'b01) begin
            $display("VERIGYM_FAIL first recovery grant=%b", grant);
            $fatal(1);
        end
        @(posedge clk);
        @(negedge clk);
        #1;
        if (grant !== 2'b10) begin
            $display("VERIGYM_FAIL alternation grant=%b", grant);
            $fatal(1);
        end
        $display("VERIGYM_PASS");
        $finish;
    end
endmodule
