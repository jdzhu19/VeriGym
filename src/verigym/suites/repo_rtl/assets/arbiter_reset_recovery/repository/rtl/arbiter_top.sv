module arbiter_top (
    input  logic       clk,
    input  logic       rst,
    input  logic [1:0] request,
    output logic [1:0] grant
);
    rr_arbiter arbiter (
        .clk(clk),
        .rst(rst),
        .request(request),
        .grant(grant)
    );
endmodule
