`timescale 1ns/1ps
module public_smoke;
    reg Clk = 0;
    reg Rst = 0;
    reg EN = 0;
    reg RW = 0;
    reg [3:0] dataIn = 0;
    wire EMPTY;
    wire FULL;
    wire [3:0] dataOut;
    integer index;
    reg [3:0] values [0:3];

    LIFObuffer dut (
        .dataIn(dataIn), .RW(RW), .EN(EN), .Rst(Rst), .Clk(Clk),
        .EMPTY(EMPTY), .FULL(FULL), .dataOut(dataOut)
    );

    always #5 Clk = ~Clk;

    task automatic step;
        input enabled;
        input read_not_write;
        input [3:0] value;
        begin
            @(negedge Clk);
            EN = enabled;
            RW = read_not_write;
            dataIn = value;
            @(posedge Clk); #1;
        end
    endtask

    initial begin
        values[0] = 4'h3; values[1] = 4'hc; values[2] = 4'h5; values[3] = 4'ha;
        EN = 1; Rst = 1;
        @(posedge Clk); #1;
        Rst = 0;
        if (EMPTY !== 1'b1 || dataOut !== 4'h0)
            $fatal(1, "LIFO reset state is wrong");
        step(0, 0, 4'hf);
        if (EMPTY !== 1'b1) $fatal(1, "disabled LIFO operation changed state");
        for (index = 0; index < 4; index = index + 1)
            step(1, 0, values[index]);
        if (FULL !== 1'b1 || EMPTY !== 1'b0) $fatal(1, "LIFO full boundary is wrong");
        step(1, 0, 4'h7);
        if (FULL !== 1'b1) $fatal(1, "LIFO accepted a push while full");
        for (index = 3; index >= 0; index = index - 1) begin
            step(1, 1, 0);
            if (dataOut !== values[index]) $fatal(1, "LIFO pop order is wrong");
        end
        if (EMPTY !== 1'b1 || FULL !== 1'b0) $fatal(1, "LIFO empty boundary is wrong");
        step(1, 1, 0);
        if (EMPTY !== 1'b1) $fatal(1, "LIFO accepted a pop while empty");
        $display("VERIGYM_PUBLIC_PASS");
        $finish;
    end
endmodule
