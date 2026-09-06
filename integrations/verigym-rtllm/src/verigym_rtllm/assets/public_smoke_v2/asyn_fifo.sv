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
    integer edges;

    asyn_fifo #(.WIDTH(WIDTH), .DEPTH(DEPTH)) dut (
        .wclk(wclk), .rclk(rclk), .wrstn(wrstn), .rrstn(rrstn),
        .winc(winc), .rinc(rinc), .wdata(wdata),
        .wfull(wfull), .rempty(rempty), .rdata(rdata)
    );

    always #5 wclk = ~wclk;
    initial begin
        #2;
        forever #7 rclk = ~rclk;
    end

    task automatic fail;
        input [8*96-1:0] message;
        begin
            $display("VERIGYM_PUBLIC_FAIL %0s", message);
            $fatal(1);
        end
    endtask

    task automatic write_value;
        input [WIDTH-1:0] value;
        begin
            @(negedge wclk);
            if (wfull !== 1'b0) fail("full asserted before sixteen accepted writes");
            wdata = value;
            winc = 1;
            @(negedge wclk);
            winc = 0;
        end
    endtask

    task automatic read_value;
        input [WIDTH-1:0] expected;
        begin
            edges = 0;
            while (rempty !== 1'b0 && edges < 4) begin
                @(posedge rclk); #1;
                edges = edges + 1;
            end
            if (rempty !== 1'b0) fail("write pointer was not visible within four read edges");
            rinc = 1;
            @(posedge rclk); #1;
            if (rdata !== expected) fail("synchronous read data violated FIFO ordering");
            @(negedge rclk);
            rinc = 0;
        end
    endtask

    initial begin
        #1;
        wrstn = 0;
        rrstn = 0;
        #1;
        if (wfull !== 1'b0 || rempty !== 1'b1)
            fail("active-low asynchronous reset state is wrong");
        repeat (2) @(posedge wclk);
        repeat (2) @(posedge rclk);
        wrstn = 1;
        rrstn = 1;

        write_value(8'ha5);
        edges = 0;
        while (rempty !== 1'b0 && edges < 4) begin
            @(posedge rclk); #1;
            edges = edges + 1;
        end
        if (rempty !== 1'b0 || edges < 2)
            fail("read-domain empty flag crossed outside the two-to-four-edge window");
        read_value(8'ha5);

        for (index = 0; index < DEPTH; index = index + 1)
            write_value(8'h30 + index[WIDTH-1:0]);
        @(posedge wclk); #1;
        if (wfull !== 1'b1) fail("full did not assert after exactly DEPTH writes");

        @(negedge wclk);
        wdata = 8'hee;
        winc = 1;
        repeat (2) @(negedge wclk);
        winc = 0;
        if (wfull !== 1'b1) fail("full-state write was not blocked");

        for (index = 0; index < DEPTH; index = index + 1)
            read_value(8'h30 + index[WIDTH-1:0]);
        @(posedge rclk); #1;
        if (rempty !== 1'b1) fail("empty did not assert after the final accepted read");

        @(negedge rclk);
        rinc = 1;
        repeat (2) @(posedge rclk);
        #1;
        if (rempty !== 1'b1) fail("empty-state read was not blocked");
        rinc = 0;

        // A coordinated reset invalidates all prior cross-domain queue content.
        wrstn = 0;
        #1;
        rrstn = 0;
        #1;
        if (wfull !== 1'b0 || rempty !== 1'b1)
            fail("coordinated recovery reset state is wrong");
        wrstn = 1;
        rrstn = 1;
        repeat (4) @(posedge rclk);
        if (rempty !== 1'b1) fail("reset queue content remained externally valid");

        $display("VERIGYM_PUBLIC_PASS");
        $finish;
    end
endmodule
