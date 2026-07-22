`timescale 1ns/1ps

module tb_and_gate;
    reg a;
    reg b;
    wire y;
    integer vector;

    and_gate dut (.a(a), .b(b), .y(y));

    initial begin
        for (vector = 0; vector < 4; vector = vector + 1) begin
            {a, b} = vector[1:0];
            #1;
            if (y !== (a & b)) begin
                $display("VERIGYM_FAIL vector=%0d y=%b", vector, y);
                $finish;
            end
        end
        $display("VERIGYM_PASS");
        $finish;
    end
endmodule
