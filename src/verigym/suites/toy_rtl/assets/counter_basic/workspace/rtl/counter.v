module counter (
    input wire clk,
    input wire reset,
    output reg [7:0] q
);

    always @(posedge clk) begin
        q <= 8'h00;
    end
endmodule

