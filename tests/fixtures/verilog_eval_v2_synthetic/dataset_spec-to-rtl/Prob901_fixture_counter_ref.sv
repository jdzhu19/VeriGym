module RefModule (
    input  logic       clk,
    input  logic       reset,
    output logic [2:0] q
);
    always_ff @(posedge clk) begin
        if (reset)
            q <= 3'b000;
        else
            q <= q + 3'b001;
    end
endmodule
