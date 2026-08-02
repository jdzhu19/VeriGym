// SPDX-License-Identifier: Apache-2.0
module flush_stage (
    input  logic       clk,
    input  logic       rst,
    input  logic       flush,
    input  logic       in_valid,
    output logic       in_ready,
    input  logic [7:0] in_data,
    output logic       out_valid,
    input  logic       out_ready,
    output logic [7:0] out_data
);
    assign in_ready = ~out_valid | out_ready;
    always_ff @(posedge clk) begin
        if (rst) begin
            out_valid <= 1'b0;
            out_data <= 8'h00;
        end else if (in_ready) begin
            out_valid <= in_valid;
            if (in_valid) out_data <= in_data;
        end
    end
endmodule
