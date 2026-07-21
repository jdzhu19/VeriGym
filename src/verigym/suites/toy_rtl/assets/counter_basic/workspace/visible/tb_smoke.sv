`timescale 1ns/1ps

module tb_smoke;
    reg clk = 1'b0;
    reg reset = 1'b1;
    wire [7:0] q;

    counter dut (.clk(clk), .reset(reset), .q(q));
    always #5 clk = ~clk;

    initial begin
        @(posedge clk);
        #1;
        if (q !== 8'h00) begin
            $display("VERIGYM_FAIL visible reset mismatch: %h", q);
            $finish;
        end
        $display("VERIGYM_PASS");
        $finish;
    end
endmodule

