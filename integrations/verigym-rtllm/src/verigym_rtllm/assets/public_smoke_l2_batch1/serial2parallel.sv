`timescale 1ns/1ps
module public_smoke;
    reg clk = 0;
    reg rst_n = 0;
    reg din_serial = 0;
    reg din_valid = 0;
    wire [7:0] dout_parallel;
    wire dout_valid;
    integer bit_index;

    serial2parallel dut (
        .clk(clk), .rst_n(rst_n), .din_serial(din_serial), .din_valid(din_valid),
        .dout_parallel(dout_parallel), .dout_valid(dout_valid)
    );

    always #5 clk = ~clk;

    task automatic send_bit;
        input value;
        begin
            @(negedge clk);
            din_valid = 1;
            din_serial = value;
            @(posedge clk); #1;
            if (dout_valid !== 1'b0)
                $fatal(1, "serial converter asserted valid before the output cycle");
        end
    endtask

    task automatic idle_cycle;
        begin
            @(negedge clk);
            din_valid = 0;
            din_serial = 0;
            @(posedge clk); #1;
        end
    endtask

    task automatic send_word;
        input [7:0] value;
        begin
            for (bit_index = 7; bit_index >= 0; bit_index = bit_index - 1)
                send_bit(value[bit_index]);
            idle_cycle();
            if (dout_valid !== 1'b1 || dout_parallel !== value)
                $fatal(1, "serial converter output, bit order, or valid latency is wrong");
            idle_cycle();
            if (dout_valid !== 1'b0)
                $fatal(1, "serial converter valid must be a one-cycle pulse");
        end
    endtask

    initial begin
        rst_n = 0;
        repeat (2) @(negedge clk);
        if (dout_valid !== 1'b0 || dout_parallel !== 8'h00)
            $fatal(1, "serial converter reset outputs are wrong");
        rst_n = 1;

        send_bit(1'b1);
        send_bit(1'b0);
        send_bit(1'b1);
        idle_cycle();
        if (dout_valid !== 1'b0)
            $fatal(1, "serial converter did not discard a partial frame");

        send_word(8'h96);
        send_word(8'h2d);

        @(negedge clk); rst_n = 0;
        #1;
        if (dout_valid !== 1'b0 || dout_parallel !== 8'h00)
            $fatal(1, "serial converter mid-stream reset is wrong");
        $display("VERIGYM_PUBLIC_PASS");
        $finish;
    end
endmodule
