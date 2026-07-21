module counter (
    input wire clk,
    input wire reset,
    output reg [7:0] q
);

    always @(posedge clk) begin
        if (reset) begin
            q <= 8'h00;
        end else begin
            q <= q + 8'h01;
        end
    end
endmodule

