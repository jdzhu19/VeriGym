// SPDX-License-Identifier: Apache-2.0
`timescale 1ns/1ps
module tb_arbiter_hidden;
    logic clk = 1'b0;
    logic rst = 1'b0;
    logic [1:0] request = 2'b00;
    logic [1:0] grant;
    logic expected_last = 1'b1;
    logic [1:0] expected_grant;
    integer cycle;

    rr_arbiter dut (.clk(clk), .rst(rst), .request(request), .grant(grant));
    always #5 clk = ~clk;

    initial begin
        for (cycle = 0; cycle < 48; cycle = cycle + 1) begin
            @(negedge clk);
            rst = (cycle == 0 || cycle == 19 || cycle == 37);
            if (cycle == 1 || cycle == 20 || cycle == 38) begin
                request = 2'b11;
            end else begin
                request = cycle[1:0];
            end
            if (rst) begin
                expected_grant = 2'b00;
            end else begin
                case (request)
                    2'b01: expected_grant = 2'b01;
                    2'b10: expected_grant = 2'b10;
                    2'b11: expected_grant = expected_last ? 2'b01 : 2'b10;
                    default: expected_grant = 2'b00;
                endcase
            end
            #1;
            if (grant !== expected_grant || grant === 2'b11) begin
                $display(
                    "VERIGYM_FAIL cycle=%0d got=%b expected=%b",
                    cycle, grant, expected_grant
                );
                $finish;
            end
            @(posedge clk);
            if (rst) begin
                expected_last = 1'b1;
            end else if (expected_grant[0]) begin
                expected_last = 1'b0;
            end else if (expected_grant[1]) begin
                expected_last = 1'b1;
            end
        end
        $display("VERIGYM_PASS");
        $finish;
    end
endmodule
