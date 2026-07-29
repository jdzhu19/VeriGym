module loadable_counter (
    input  logic       clk,
    input  logic       rst,
    input  logic       load,
    input  logic       enable,
    input  logic [3:0] load_value,
    output logic [3:0] count
);
    always_ff @(posedge clk) begin
        if (rst) begin
            count <= 4'd0;
        end else if (enable) begin
            count <= count + 4'd1;
        end else if (load) begin
            count <= load_value;
        end
    end
endmodule
