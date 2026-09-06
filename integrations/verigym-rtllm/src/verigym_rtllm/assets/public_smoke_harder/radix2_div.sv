`timescale 1ns/1ps
module public_smoke;
    reg clk = 0;
    reg rst = 0;
    reg sign = 0;
    reg [7:0] dividend = 0;
    reg [7:0] divisor = 1;
    reg opn_valid = 0;
    reg res_ready = 0;
    wire res_valid;
    wire [15:0] result;
    integer cycles;

    radix2_div dut (
        .clk(clk), .rst(rst), .dividend(dividend), .divisor(divisor), .sign(sign),
        .opn_valid(opn_valid), .res_valid(res_valid), .res_ready(res_ready), .result(result)
    );

    always #5 clk = ~clk;

    task automatic check_division;
        input [7:0] task_dividend;
        input [7:0] task_divisor;
        input task_sign;
        input [15:0] expected;
        begin
            @(negedge clk);
            dividend = task_dividend;
            divisor = task_divisor;
            sign = task_sign;
            opn_valid = 1;
            @(negedge clk);
            opn_valid = 0;
            cycles = 0;
            while (res_valid !== 1'b1 && cycles < 16) begin
                @(negedge clk);
                cycles = cycles + 1;
            end
            if (res_valid !== 1'b1 || cycles < 6 || result !== expected)
                $fatal(1, "divider result, field order, or multi-cycle validity is wrong");
            repeat (2) begin
                @(negedge clk);
                if (res_valid !== 1'b1 || result !== expected)
                    $fatal(1, "divider result must remain valid until accepted");
            end
            res_ready = 1;
            @(negedge clk);
            res_ready = 0;
            if (res_valid !== 1'b0)
                $fatal(1, "divider valid did not clear after ready");
        end
    endtask

    initial begin
        rst = 1;
        repeat (2) @(negedge clk);
        rst = 0;
        if (res_valid !== 1'b0) $fatal(1, "divider reset did not clear valid");
        check_division(8'd173, 8'd13, 1'b0, {8'd4, 8'd13});
        check_division(-8'sd91, 8'd9, 1'b1, {-8'sd1, -8'sd10});
        check_division(8'd91, -8'sd9, 1'b1, {8'd1, -8'sd10});
        $display("VERIGYM_PUBLIC_PASS");
        $finish;
    end
endmodule
