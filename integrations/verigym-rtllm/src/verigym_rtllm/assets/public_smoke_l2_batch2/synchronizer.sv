`timescale 1ns/1ps
module public_smoke;
    reg clk_a = 0;
    reg clk_b = 0;
    reg arstn = 1;
    reg brstn = 1;
    reg [3:0] data_in = 0;
    reg data_en = 0;
    wire [3:0] dataout;

    synchronizer dut (
        .clk_a(clk_a), .clk_b(clk_b), .arstn(arstn), .brstn(brstn),
        .data_in(data_in), .data_en(data_en), .dataout(dataout)
    );

    always #5 clk_a = ~clk_a;
    always #7 clk_b = ~clk_b;

    task automatic transfer;
        input [3:0] value;
        input [3:0] previous;
        begin
            @(negedge clk_a);
            data_in = value;
            data_en = 1;
            @(posedge clk_a); #1;
            @(posedge clk_b); #1;
            if (dataout !== previous)
                $fatal(1, "synchronizer output changed before the enable pipeline matured");
            @(posedge clk_b); #1;
            if (dataout !== previous)
                $fatal(1, "synchronizer enable latency is too short");
            @(posedge clk_b); #1;
            if (dataout !== value)
                $fatal(1, "synchronizer did not transfer the stable multi-bit value");
            @(negedge clk_a);
            data_en = 0;
            @(posedge clk_a); #1;
            repeat (3) @(posedge clk_b);
            #1;
        end
    endtask

    initial begin
        #1; arstn = 0; brstn = 0;
        #1;
        if (dataout !== 4'h0)
            $fatal(1, "synchronizer reset output is wrong");
        @(negedge clk_a); arstn = 1;
        @(negedge clk_b); brstn = 1;

        transfer(4'ha, 4'h0);
        @(negedge clk_a); data_in = 4'h3;
        repeat (4) @(posedge clk_b);
        #1;
        if (dataout !== 4'ha)
            $fatal(1, "synchronizer output did not retain its value while disabled");

        @(negedge clk_b); brstn = 0; #1;
        if (dataout !== 4'h0)
            $fatal(1, "synchronizer destination-domain reset is wrong");
        brstn = 1;
        transfer(4'h5, 4'h0);

        @(negedge clk_a); arstn = 0; #1;
        if (dataout !== 4'h5)
            $fatal(1, "source-domain reset incorrectly cleared the destination output");
        arstn = 1;
        transfer(4'hc, 4'h5);

        $display("VERIGYM_PUBLIC_PASS");
        $finish;
    end
endmodule
