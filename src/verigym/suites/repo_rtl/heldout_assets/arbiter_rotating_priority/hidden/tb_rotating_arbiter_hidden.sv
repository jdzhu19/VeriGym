module tb_rotating_arbiter_hidden;
    logic clk = 1'b0;
    logic rst_n;
    logic [2:0] request;
    logic [2:0] grant;

    arbiter_top dut (.*);
    always #5 clk = ~clk;

    task tick;
        begin
            @(posedge clk);
            #1;
        end
    endtask

    task expect_grant(input logic [2:0] expected);
        begin
            if (grant !== expected) begin
                $fatal(1, "expected grant %b, got %b", expected, grant);
            end
        end
    endtask

    initial begin
        rst_n = 1'b0;
        request = 3'b110;
        tick();
        rst_n = 1'b1;

        expect_grant(3'b010);
        tick();
        expect_grant(3'b100);
        tick();
        expect_grant(3'b010);
        tick();

        request = 3'b101;
        #1;
        expect_grant(3'b100);
        tick();
        expect_grant(3'b001);

        request = 3'b010;
        #1;
        expect_grant(3'b010);
        tick();
        request = 3'b111;
        #1;
        expect_grant(3'b100);

        rst_n = 1'b0;
        tick();
        rst_n = 1'b1;
        expect_grant(3'b001);

        request = 3'b000;
        #1;
        expect_grant(3'b000);
        tick();
        request = 3'b010;
        #1;
        expect_grant(3'b010);

        $display("VERIGYM_PASS");
        $finish;
    end
endmodule
