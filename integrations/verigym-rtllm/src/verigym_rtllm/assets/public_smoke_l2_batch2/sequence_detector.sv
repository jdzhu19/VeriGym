`timescale 1ns/1ps
module public_smoke;
    reg clk = 0;
    reg rst_n = 0;
    reg data_in = 0;
    wire sequence_detected;

    sequence_detector dut (
        .clk(clk), .rst_n(rst_n), .data_in(data_in),
        .sequence_detected(sequence_detected)
    );

    always #5 clk = ~clk;

    task automatic send_bit;
        input value;
        input expected_detection;
        begin
            @(negedge clk);
            data_in = value;
            @(posedge clk); #1;
            if (sequence_detected !== expected_detection)
                $fatal(1, "sequence detector value, overlap, or output latency is wrong");
        end
    endtask

    initial begin
        repeat (2) @(negedge clk);
        if (sequence_detected !== 1'b0)
            $fatal(1, "sequence detector reset output is wrong");
        rst_n = 1;

        send_bit(1, 0);
        send_bit(0, 0);
        send_bit(1, 0);
        send_bit(1, 0);

        send_bit(1, 0);
        send_bit(0, 0);
        send_bit(0, 0);
        send_bit(1, 1);
        send_bit(0, 0);
        send_bit(0, 0);
        send_bit(1, 1);
        send_bit(1, 0);

        send_bit(1, 0);
        send_bit(0, 0);
        @(negedge clk); rst_n = 0; #1;
        if (sequence_detected !== 1'b0)
            $fatal(1, "sequence detector asynchronous reset is wrong");
        rst_n = 1;
        send_bit(1, 0);
        send_bit(0, 0);
        send_bit(0, 0);
        send_bit(1, 1);

        $display("VERIGYM_PUBLIC_PASS");
        $finish;
    end
endmodule
