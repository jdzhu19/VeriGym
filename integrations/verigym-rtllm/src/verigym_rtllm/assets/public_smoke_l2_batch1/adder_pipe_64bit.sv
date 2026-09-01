`timescale 1ns/1ps
module public_smoke;
    reg clk = 0;
    reg rst_n = 0;
    reg i_en = 0;
    reg [63:0] adda = 0;
    reg [63:0] addb = 0;
    wire [64:0] result;
    wire o_en;
    reg [64:0] expected [0:11];
    reg expected_valid [0:11];
    integer cycle;

    adder_pipe_64bit dut (
        .clk(clk), .rst_n(rst_n), .i_en(i_en), .adda(adda), .addb(addb),
        .result(result), .o_en(o_en)
    );

    always #5 clk = ~clk;

    task automatic drive;
        input enabled;
        input [63:0] a;
        input [63:0] b;
        begin
            @(negedge clk);
            i_en = enabled;
            adda = a;
            addb = b;
        end
    endtask

    initial begin
        for (cycle = 0; cycle < 12; cycle = cycle + 1) begin
            expected[cycle] = 0;
            expected_valid[cycle] = 0;
        end
        rst_n = 0;
        repeat (2) @(negedge clk);
        if (o_en !== 1'b0 || result !== 65'd0)
            $fatal(1, "adder reset outputs are wrong");
        rst_n = 1;
        drive(1, 64'h0000_ffff_ffff_ffff, 64'h0000_0000_0000_0001);
        drive(1, 64'hffff_ffff_ffff_ffff, 64'h0000_0000_0000_0001);
        drive(0, 64'hdead_beef_cafe_f00d, 64'h1111_2222_3333_4444);
        drive(1, 64'h1234_ffff_ffff_ffff, 64'h0001_0000_0000_0001);
        drive(1, 64'h0123_4567_89ab_cdef, 64'h1111_1111_1111_1111);
        repeat (5) drive(0, 0, 0);
    end

    initial begin
        wait (rst_n === 1'b1);
        expected_valid[4] = 1;
        expected[4] = 65'h0_0001_0000_0000_0000;
        expected_valid[5] = 1;
        expected[5] = 65'h1_0000_0000_0000_0000;
        expected_valid[7] = 1;
        expected[7] = 65'h0_1236_0000_0000_0000;
        expected_valid[8] = 1;
        expected[8] = 65'h0_1234_5678_9abc_df00;
        for (cycle = 0; cycle < 12; cycle = cycle + 1) begin
            @(posedge clk); #1;
            if (o_en !== expected_valid[cycle])
                $fatal(1, "adder output enable is not aligned to the four-stage pipeline");
            if (expected_valid[cycle] && result !== expected[cycle])
                $fatal(1, "adder sum or carry propagation is wrong");
        end
        $display("VERIGYM_PUBLIC_PASS");
        $finish;
    end
endmodule
