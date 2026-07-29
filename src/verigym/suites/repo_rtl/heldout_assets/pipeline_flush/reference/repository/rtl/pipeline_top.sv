module pipeline_top (
    input  logic       clk,
    input  logic       rst,
    input  logic       flush,
    input  logic       in_valid,
    input  logic [7:0] in_data,
    output logic       out_valid,
    output logic [7:0] out_data
);
    logic       middle_valid;
    logic [7:0] middle_data;

    pipeline_stage u_first (
        .clk(clk),
        .rst(rst),
        .flush(flush),
        .in_valid(in_valid),
        .in_data(in_data),
        .out_valid(middle_valid),
        .out_data(middle_data)
    );

    pipeline_stage u_second (
        .clk(clk),
        .rst(rst),
        .flush(flush),
        .in_valid(middle_valid),
        .in_data(middle_data),
        .out_valid(out_valid),
        .out_data(out_data)
    );
endmodule
