module tb_tiny_and;
    reg a;
    reg b;
    wire y;
    integer i;
    tiny_and dut(.a(a), .b(b), .y(y));
    initial begin
        for (i = 0; i < 4; i = i + 1) begin
            {a, b} = i[1:0];
            #1;
            if (y !== (a & b)) $fatal(1, "mismatch");
        end
        $display("VERIGYM_PASS");
    end
endmodule
