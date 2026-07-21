`timescale 1ns/1ps
module tb;
    logic a;
    logic b;
    logic y_ref;
    logic y_dut;
    integer mismatches;
    integer samples;

    RefModule golden (.a(a), .b(b), .y(y_ref));
    TopModule candidate (.a(a), .b(b), .y(y_dut));

    initial begin
        mismatches = 0;
        samples = 0;
        for (integer value = 0; value < 4; value = value + 1) begin
            {a, b} = value[1:0];
            #1;
            samples = samples + 1;
            if (y_ref !== y_dut)
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
