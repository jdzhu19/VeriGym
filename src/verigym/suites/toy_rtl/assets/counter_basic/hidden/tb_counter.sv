`timescale 1ns/1ps

module tb_counter;
    reg clk = 1'b0;
    reg reset = 1'b1;
    wire [7:0] q;
    integer step;

    counter dut (.clk(clk), .reset(reset), .q(q));
    always #5 clk = ~clk;

    task fail;
        input [255:0] reason;
        begin
            $display("VERIGYM_FAIL %0s q=%h", reason, q);
            $finish;
        end
    endtask

    initial begin
        @(posedge clk);
        #1;
        if (q !== 8'h00) fail("reset did not clear q");

        reset = 1'b0;
        for (step = 1; step <= 4; step = step + 1) begin
            @(posedge clk);
            #1;
            if (q !== step[7:0]) fail("increment mismatch");
        end

        reset = 1'b1;
        @(posedge clk);
        #1;
        if (q !== 8'h00) fail("synchronous reset mismatch");

        reset = 1'b0;
        repeat (256) begin
            @(posedge clk);
            #1;
        end
        if (q !== 8'h00) fail("counter did not wrap modulo 256");

        $display("VERIGYM_PASS");
        $finish;
    end
endmodule

