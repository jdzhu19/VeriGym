`timescale 1ns/1ps
module tb;
    logic clk;
    logic reset;
    logic [2:0] q_ref;
    logic [2:0] q_dut;
    integer mismatches;
    integer samples;

    RefModule golden (.clk(clk), .reset(reset), .q(q_ref));
    TopModule candidate (.clk(clk), .reset(reset), .q(q_dut));

    always #1 clk = ~clk;

    initial begin
        clk = 0;
        reset = 1;
        mismatches = 0;
        samples = 0;
        repeat (2) @(posedge clk);
        reset = 0;
        repeat (10) begin
            @(negedge clk);
            samples = samples + 1;
            if (q_ref !== q_dut)
                mismatches = mismatches + 1;
        end
        $display("Mismatches: %0d in %0d samples", mismatches, samples);
        $finish;
    end

    initial begin
        #100;
        $display("TIMEOUT");
        $finish;
    end
endmodule
