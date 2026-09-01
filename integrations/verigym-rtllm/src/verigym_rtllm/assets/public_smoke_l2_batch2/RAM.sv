`timescale 1ns/1ps
module public_smoke;
    reg clk = 0;
    reg rst_n = 0;
    reg write_en = 0;
    reg [7:0] write_addr = 0;
    reg [5:0] write_data = 0;
    reg read_en = 0;
    reg [7:0] read_addr = 0;
    wire [5:0] read_data;

    RAM dut (
        .clk(clk), .rst_n(rst_n), .write_en(write_en), .write_addr(write_addr),
        .write_data(write_data), .read_en(read_en), .read_addr(read_addr),
        .read_data(read_data)
    );

    always #5 clk = ~clk;

    task automatic write_word;
        input [7:0] address;
        input [5:0] value;
        begin
            @(negedge clk);
            write_en = 1;
            write_addr = address;
            write_data = value;
            @(posedge clk); #1;
            @(negedge clk); write_en = 0;
        end
    endtask

    task automatic read_word;
        input [7:0] address;
        input [5:0] expected;
        begin
            @(negedge clk);
            read_en = 1;
            read_addr = address;
            @(posedge clk); #1;
            if (read_data !== expected)
                $fatal(1, "RAM synchronous read data or latency is wrong");
            @(negedge clk); read_en = 0;
            @(posedge clk); #1;
            if (read_data !== 6'h00)
                $fatal(1, "RAM read output must clear while read_en is low");
        end
    endtask

    initial begin
        repeat (2) @(negedge clk);
        if (read_data !== 6'h00)
            $fatal(1, "RAM reset output is wrong");
        rst_n = 1;

        read_word(8'd7, 6'h00);
        write_word(8'd2, 6'h2a);
        write_word(8'd5, 6'h15);
        read_word(8'd2, 6'h2a);
        read_word(8'd5, 6'h15);

        @(negedge clk);
        write_en = 1;
        write_addr = 8'd4;
        write_data = 6'h33;
        read_en = 1;
        read_addr = 8'd2;
        @(posedge clk); #1;
        if (read_data !== 6'h2a)
            $fatal(1, "RAM ports did not support simultaneous write and read");
        @(negedge clk); write_en = 0; read_en = 0;
        read_word(8'd4, 6'h33);

        write_word(8'd1, 6'h3f);
        @(negedge clk); rst_n = 0; #1;
        if (read_data !== 6'h00)
            $fatal(1, "RAM asynchronous reset output is wrong");
        @(negedge clk); rst_n = 1;
        read_word(8'd1, 6'h00);
        read_word(8'd2, 6'h00);

        $display("VERIGYM_PUBLIC_PASS");
        $finish;
    end
endmodule
