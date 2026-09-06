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
            if (out !== expected) begin
                $display(
                    "VERIGYM_PUBLIC_FAIL phase=sequence cycle=%0d expected=%04b got=%04b",
                    cycle, expected, out
                );
                $fatal(1, "LFSR shift direction, feedback taps, or inversion is wrong");
            end
            cycle = cycle + 1;
        end
    endtask

    initial begin
        cycle = 0;
        rst = 1;
        @(posedge clk); #1;
        if (out !== 4'b0000) begin
            $display("VERIGYM_PUBLIC_FAIL phase=initial-reset expected=0000 got=%04b", out);
            $fatal(1, "LFSR rising-edge reset state is wrong");
        end
        @(negedge clk); rst = 0;
        expected = 4'b0000;
        repeat (15) check_step();

        @(negedge clk); rst = 1;
        @(posedge clk); #1;
        if (out !== 4'b0000) begin
            $display("VERIGYM_PUBLIC_FAIL phase=mid-reset expected=0000 got=%04b", out);
            $fatal(1, "LFSR mid-sequence rising-edge reset is wrong");
        end
        @(negedge clk); rst = 0;
        expected = 4'b0000;
        repeat (4) check_step();
        $display("VERIGYM_PUBLIC_PASS cycles=%0d", cycle);
        $finish;
    end
endmodule
