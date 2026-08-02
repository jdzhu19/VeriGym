// SPDX-License-Identifier: Apache-2.0
module flush_pipeline_top (
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
    flush_stage u_stage (.*);
endmodule
