module tb_counter_load_hidden;
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

        load = 1'b1;
        load_value = 4'd9;
        tick();
        load = 1'b0;
        enable = 1'b1;
        tick();
        if (count !== 4'd0) $fatal(1, "decade wrap failed");

        enable = 1'b0;
        repeat (2) tick();
        if (count !== 4'd0) $fatal(1, "hold failed");

        load = 1'b1;
        enable = 1'b1;
        load_value = 4'd6;
        tick();
        if (count !== 4'd6) $fatal(1, "simultaneous load priority failed");

        rst = 1'b1;
        load_value = 4'd4;
        tick();
        if (count !== 4'd0) $fatal(1, "reset priority failed");

        $display("VERIGYM_PASS");
        $finish;
    end
endmodule
