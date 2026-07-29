module pipeline_stage (
    input  logic       clk,
    input  logic       rst,
    input  logic       flush,
    input  logic       in_valid,
    input  logic [7:0] in_data,
    output logic       out_valid,
    output logic [7:0] out_data
);
    always_ff @(posedge clk) begin
        if (rst || flush) begin
            out_valid <= 1'b0;
            out_data <= 8'h00;
        end else begin
            out_valid <= in_valid;
            if (in_valid) begin
                out_data <= in_data;
            end
        end
    end
endmodule
