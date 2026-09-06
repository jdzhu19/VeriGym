`timescale 1ns/1ps
module public_smoke;
    reg clk = 0;
    reg rst_n = 0;
    wire clk_div_3;
    wire clk_div_5;
    integer edge_index;
    integer pos_count_3, neg_count_3, pos_count_5, neg_count_5;
    reg pos_phase_3, neg_phase_3, pos_phase_5, neg_phase_5;

    freq_divbyodd #(.NUM_DIV(3)) dut3 (.clk(clk), .rst_n(rst_n), .clk_div(clk_div_3));
    freq_divbyodd #(.NUM_DIV(5)) dut5 (.clk(clk), .rst_n(rst_n), .clk_div(clk_div_5));
    always #5 clk = ~clk;

    task automatic check_outputs(input [8*16-1:0] edge_name);
        reg expected_3;
        reg expected_5;
        begin
            expected_3 = pos_phase_3 | neg_phase_3;
            expected_5 = pos_phase_5 | neg_phase_5;
            if (clk_div_3 !== expected_3 || clk_div_5 !== expected_5) begin
                $display(
                    "VERIGYM_PUBLIC_FAIL edge=%0s index=%0d div3_expected=%0b div3_got=%0b div5_expected=%0b div5_got=%0b",
                    edge_name, edge_index, expected_3, clk_div_3, expected_5, clk_div_5
                );
                $fatal(1, "odd-divider phase or parameter handling is wrong");
            end
            edge_index = edge_index + 1;
        end
    endtask

    initial begin
        repeat (2) @(negedge clk);
        @(posedge clk); @(negedge clk); #1;
        if (clk_div_3 !== 1'b1 || clk_div_5 !== 1'b1) begin
            $display(
                "VERIGYM_PUBLIC_FAIL phase=reset div3_expected=1 div3_got=%0b div5_expected=1 div5_got=%0b",
                clk_div_3, clk_div_5
            );
            $fatal(1, "odd-divider reset state is wrong after both edge domains sampled reset");
        end

        rst_n = 1;
        edge_index = 0;
        pos_count_3 = 0; neg_count_3 = 0; pos_phase_3 = 1; neg_phase_3 = 1;
        pos_count_5 = 0; neg_count_5 = 0; pos_phase_5 = 1; neg_phase_5 = 1;
        repeat (30) begin
            @(posedge clk);
            pos_phase_3 = (pos_count_3 < 1);
            pos_phase_5 = (pos_count_5 < 2);
            if (pos_count_3 < 2) pos_count_3 = pos_count_3 + 1; else pos_count_3 = 0;
            if (pos_count_5 < 4) pos_count_5 = pos_count_5 + 1; else pos_count_5 = 0;
            #1; check_outputs("posedge");

            @(negedge clk);
            neg_phase_3 = (neg_count_3 < 1);
            neg_phase_5 = (neg_count_5 < 2);
            if (neg_count_3 < 2) neg_count_3 = neg_count_3 + 1; else neg_count_3 = 0;
            if (neg_count_5 < 4) neg_count_5 = neg_count_5 + 1; else neg_count_5 = 0;
            #1; check_outputs("negedge");
        end

        rst_n = 0;
        @(posedge clk); @(negedge clk); #1;
        if (clk_div_3 !== 1'b1 || clk_div_5 !== 1'b1) begin
            $display(
                "VERIGYM_PUBLIC_FAIL phase=re-reset div3_expected=1 div3_got=%0b div5_expected=1 div5_got=%0b",
                clk_div_3, clk_div_5
            );
            $fatal(1, "odd-divider re-reset state is wrong");
        end
        $display("VERIGYM_PUBLIC_PASS checked_edges=%0d divisors=3,5", edge_index);
        $finish;
    end
endmodule
