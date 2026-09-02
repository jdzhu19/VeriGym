`timescale 1ns/1ps
module public_smoke;
    reg [15:0] A;
    reg [7:0] B;
    wire [15:0] result;
    wire [15:0] odd;
    integer vector_index;

    div_16bit dut (.A(A), .B(B), .result(result), .odd(odd));

    task automatic check(input [15:0] dividend, input [7:0] divisor);
        reg [15:0] expected_quotient;
        reg [15:0] expected_remainder;
        begin
            A = dividend;
            B = divisor;
            expected_quotient = dividend / divisor;
            expected_remainder = dividend % divisor;
            #1;
            if (result !== expected_quotient || odd !== expected_remainder) begin
                $display(
                    "VERIGYM_PUBLIC_FAIL vector=%0d A=%0d B=%0d expected_q=%0d got_q=%0d expected_r=%0d got_r=%0d",
                    vector_index, dividend, divisor, expected_quotient, result,
                    expected_remainder, odd
                );
                $fatal(1, "divider quotient or remainder is wrong");
            end
            vector_index = vector_index + 1;
        end
    endtask

    initial begin
        vector_index = 0;
        check(16'd0, 8'd1);
        check(16'd1, 8'd1);
        check(16'd255, 8'd255);
        check(16'd256, 8'd255);
        check(16'd65535, 8'd1);
        check(16'd32768, 8'd2);
        check(16'd4095, 8'd16);
        check(16'd4096, 8'd16);
        check(16'd7, 8'd13);
        check(16'd49151, 8'd127);
        $display("VERIGYM_PUBLIC_PASS vectors=%0d", vector_index);
        $finish;
    end
endmodule
