module pipeline_register (
    input  logic       clk,
    input  logic       rst,
    input  logic       load,
    input  logic [7:0] data_in,
    output logic [7:0] data_out
);
    always_ff @(posedge clk) begin
        if (rst) begin
            data_out <= 8'h00;
        end else if (load) begin
            data_out <= data_in;
        end
    end
endmodule
