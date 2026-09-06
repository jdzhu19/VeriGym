`timescale 1ns/1ps
module public_smoke;
    localparam WIDTH = 8;
    localparam DEPTH = 16;
    reg wclk = 0;
    reg rclk = 0;
    reg wrstn = 1;
    reg rrstn = 1;
    reg winc = 0;
    reg rinc = 0;
    reg [WIDTH-1:0] wdata = 0;
    wire wfull;
    wire rempty;
    wire [WIDTH-1:0] rdata;
    integer index;
    integer guard;

    asyn_fifo #(.WIDTH(WIDTH), .DEPTH(DEPTH)) dut (
        .wclk(wclk), .rclk(rclk), .wrstn(wrstn), .rrstn(rrstn),
        .winc(winc), .rinc(rinc), .wdata(wdata),
        .wfull(wfull), .rempty(rempty), .rdata(rdata)
    );

    always #5 wclk = ~wclk;
    always #7 rclk = ~rclk;

    task automatic write_value;
        input [7:0] value;
        begin
            @(negedge wclk);
            if (wfull) $fatal(1, "FIFO became full before DEPTH writes");
            wdata = value;
            winc = 1;
            @(negedge wclk);
            winc = 0;
        end
    endtask

    task automatic read_value;
        input [7:0] expected;
        begin
            guard = 0;
            while (rempty !== 1'b0 && guard < 12) begin
                @(negedge rclk);
                guard = guard + 1;
            end
            if (rempty !== 1'b0) $fatal(1, "FIFO data did not cross into the read domain");
            rinc = 1;
            @(posedge rclk); #1;
            if (rdata !== expected) $fatal(1, "FIFO data order is wrong");
            @(negedge rclk);
            rinc = 0;
        end
    endtask

    initial begin
        #1; wrstn = 0; rrstn = 0;
        #2;
        if (wfull !== 1'b0 || rempty !== 1'b1)
            $fatal(1, "FIFO asynchronous reset state is wrong");
        wrstn = 1;
        repeat (2) @(negedge wclk);
        if (rempty !== 1'b1) $fatal(1, "read reset domain changed unexpectedly");
        rrstn = 1;
        for (index = 0; index < DEPTH; index = index + 1)
            write_value(8'h40 + index[7:0]);
        guard = 0;
        while (wfull !== 1'b1 && guard < 6) begin
            @(negedge wclk);
            guard = guard + 1;
        end
        if (wfull !== 1'b1) $fatal(1, "FIFO full transition is wrong");
        for (index = 0; index < DEPTH; index = index + 1)
            read_value(8'h40 + index[7:0]);
        guard = 0;
        while (rempty !== 1'b1 && guard < 12) begin
            @(negedge rclk);
            guard = guard + 1;
        end
        if (rempty !== 1'b1) $fatal(1, "FIFO empty transition is wrong");
        $display("VERIGYM_PUBLIC_PASS");
        $finish;
    end
endmodule
