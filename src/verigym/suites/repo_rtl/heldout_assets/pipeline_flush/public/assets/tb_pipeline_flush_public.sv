module tb_pipeline_flush_public;
    logic clk = 1'b0;
    logic rst;
    logic flush;
    logic in_valid;
    logic [7:0] in_data;
    logic out_valid;
    logic [7:0] out_data;

    pipeline_top dut (.*);
    always #5 clk = ~clk;

    task tick;
        begin
            @(posedge clk);
            #1;
        end
    endtask

    initial begin
        rst = 1'b1;
        flush = 1'b0;
        in_valid = 1'b0;
        in_data = 8'h00;
        tick();
        rst = 1'b0;

        in_valid = 1'b1;
        in_data = 8'h2a;
        tick();
        in_valid = 1'b0;
        tick();
        if (!out_valid || out_data !== 8'h2a) $fatal(1, "normal transfer failed");

        in_valid = 1'b1;
        in_data = 8'h55;
        tick();
        flush = 1'b1;
        in_valid = 1'b0;
        tick();
        flush = 1'b0;
        if (out_valid) $fatal(1, "flush did not clear pipeline");

        $display("VERIGYM_PASS");
        $finish;
    end
endmodule
