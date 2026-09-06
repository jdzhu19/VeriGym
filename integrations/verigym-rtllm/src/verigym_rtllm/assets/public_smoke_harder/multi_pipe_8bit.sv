`timescale 1ns/1ps
module public_smoke;
    reg clk = 0;
    reg rst_n = 0;
    reg mul_en_in = 0;
    reg [7:0] mul_a = 0;
    reg [7:0] mul_b = 0;
    wire mul_en_out;
    wire [15:0] mul_out;
    reg [15:0] expected [0:9];
    reg expected_valid [0:9];
    integer cycle;

    multi_pipe_8bit dut (
        .clk(clk), .rst_n(rst_n), .mul_a(mul_a), .mul_b(mul_b),
        .mul_en_in(mul_en_in), .mul_en_out(mul_en_out), .mul_out(mul_out)
    );

    always #5 clk = ~clk;

    task automatic drive;
        input enabled;
        input [7:0] a;
        input [7:0] b;
        begin
            @(negedge clk);
            mul_en_in = enabled;
            mul_a = a;
            mul_b = b;
        end
    endtask

    initial begin
        for (cycle = 0; cycle < 10; cycle = cycle + 1) begin
            expected[cycle] = 0;
            expected_valid[cycle] = 0;
        end
        rst_n = 0;
        repeat (2) @(negedge clk);
        if (mul_en_out !== 1'b0 || mul_out !== 16'd0)
            $fatal(1, "multiplier reset outputs are wrong");
        rst_n = 1;
        drive(1, 8'd19, 8'd23);
        drive(1, 8'd255, 8'd3);
        drive(0, 8'd77, 8'd91);
        drive(1, 8'd14, 8'd17);
        drive(0, 0, 0);
        drive(0, 0, 0);
        drive(0, 0, 0);
        drive(0, 0, 0);
    end

    initial begin
        wait (rst_n === 1'b1);
        expected_valid[4] = 1; expected[4] = 16'd437;
        expected_valid[5] = 1; expected[5] = 16'd765;
        expected_valid[7] = 1; expected[7] = 16'd238;
        for (cycle = 0; cycle < 10; cycle = cycle + 1) begin
            @(posedge clk); #1;
            if (mul_en_out !== expected_valid[cycle])
                $fatal(1, "multiplier enable is not aligned to the three-cycle pipeline");
            if (expected_valid[cycle] && mul_out !== expected[cycle])
                $fatal(1, "multiplier product is wrong");
            if (!expected_valid[cycle] && mul_out !== 16'd0)
                $fatal(1, "multiplier output must be zero outside valid cycles");
        end
        $display("VERIGYM_PUBLIC_PASS");
        $finish;
    end
endmodule
