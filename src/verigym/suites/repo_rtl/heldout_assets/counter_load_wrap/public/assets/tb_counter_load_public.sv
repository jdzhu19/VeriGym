module tb_counter_load_public;
    logic clk = 1'b0;
    logic rst;
    logic load;
    logic enable;
    logic [3:0] load_value;
    logic [3:0] count;

    counter_top dut (.*);
    always #5 clk = ~clk;

    task tick;
        begin
            @(posedge clk);
            #1;
        end
    endtask

    initial begin
        rst = 1'b1;
        load = 1'b0;
        enable = 1'b0;
        load_value = 4'd0;
        tick();
        rst = 1'b0;
        if (count !== 4'd0) $fatal(1, "reset failed");

        load = 1'b1;
        enable = 1'b0;
        load_value = 4'd7;
        tick();
        if (count !== 4'd7) $fatal(1, "load failed");

        load = 1'b0;
        enable = 1'b1;
        tick();
        if (count !== 4'd8) $fatal(1, "increment failed");

        load = 1'b1;
        enable = 1'b1;
        load_value = 4'd3;
        tick();
        if (count !== 4'd3) $fatal(1, "load priority failed");

        $display("VERIGYM_PASS");
        $finish;
    end
endmodule
