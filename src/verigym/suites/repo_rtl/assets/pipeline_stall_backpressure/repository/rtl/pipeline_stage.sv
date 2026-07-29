// SPDX-License-Identifier: Apache-2.0
module pipeline_stage (
    input  logic       clk,
    input  logic       rst,
    input  logic       in_valid,
    output logic       in_ready,
    input  logic [7:0] in_data,
    output logic       out_valid,
    input  logic       out_ready,
    output logic [7:0] out_data
);
    logic       valid_q;
    logic [7:0] data_q;

    assign in_ready = ~valid_q;
    assign out_valid = valid_q;
    assign out_data = data_q;

    always_ff @(posedge clk) begin
        if (rst) begin
            valid_q <= 1'b0;
            data_q <= 8'h00;
        end else if (in_ready) begin
            valid_q <= in_valid;
            if (in_valid) begin
                data_q <= in_data;
            end
        end
    end
endmodule
