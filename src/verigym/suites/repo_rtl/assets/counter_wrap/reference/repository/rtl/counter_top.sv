module counter_top (
    input  logic       clk,
    input  logic       rst,
    input  logic       enable,
    output logic [3:0] count
);
    wrap_counter counter (
        .clk(clk),
        .rst(rst),
        .enable(enable),
        .count(count)
    );
endmodule
