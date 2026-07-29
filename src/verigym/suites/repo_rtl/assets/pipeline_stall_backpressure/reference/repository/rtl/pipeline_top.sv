// SPDX-License-Identifier: Apache-2.0
module pipeline_top (
    input  logic       clk,
    input  logic       rst,
    input  logic       in_valid,
    output logic       in_ready,
    input  logic [7:0] in_data,
    output logic       out_valid,
    input  logic       out_ready,
    output logic [7:0] out_data
);
    logic       middle_valid;
    logic       middle_ready;
    logic [7:0] middle_data;

    pipeline_stage first (
        .clk(clk),
        .rst(rst),
        .in_valid(in_valid),
        .in_ready(in_ready),
        .in_data(in_data),
        .out_valid(middle_valid),
        .out_ready(middle_ready),
        .out_data(middle_data)
    );

    pipeline_stage second (
        .clk(clk),
        .rst(rst),
        .in_valid(middle_valid),
        .in_ready(middle_ready),
        .in_data(middle_data),
        .out_valid(out_valid),
        .out_ready(out_ready),
        .out_data(out_data)
    );
endmodule
