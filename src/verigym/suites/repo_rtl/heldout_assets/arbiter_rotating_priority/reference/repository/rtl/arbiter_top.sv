module arbiter_top (
    input  logic       clk,
    input  logic       rst_n,
    input  logic [2:0] request,
    output logic [2:0] grant
);
    rotating_arbiter u_rotating_arbiter (
        .clk(clk),
        .rst_n(rst_n),
        .request(request),
        .grant(grant)
    );
endmodule
