`timescale 1ns/1ps
module public_smoke;
    reg clk = 0;
    reg rst = 0;
    wire [3:0] out;
    reg [3:0] expected;
    integer cycle;

    LFSR dut (.out(out), .clk(clk), .rst(rst));

    always #5 clk = ~clk;

    task automatic check_step;
        begin
            expected = {expected[2:0], ~(expected[3] ^ expected[2])};
            @(posedge clk); #1;
            if (out !== expected)
                $fatal(1, "LFSR shift direction, feedback taps, or inversion is wrong");
        end
    endtask

    initial begin
        #2; rst = 1;
        #1;
        if (out !== 4'b0000) $fatal(1, "LFSR reset state is wrong");
        @(negedge clk); rst = 0;
        expected = 4'b0000;
        for (cycle = 0; cycle < 12; cycle = cycle + 1)
            check_step();
        @(negedge clk); rst = 1;
        #1;
        if (out !== 4'b0000) $fatal(1, "LFSR mid-sequence reset is wrong");
        rst = 0;
        expected = 4'b0000;
        check_step();
        check_step();
        $display("VERIGYM_PUBLIC_PASS");
        $finish;
    end
endmodule
